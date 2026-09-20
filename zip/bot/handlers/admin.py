import re

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from bot.config import get_settings
from bot.database.database import AsyncSessionFactory
from bot.database.models import Choice, Episode, Season, Story, User
from bot.database.repositories import content
from bot.handlers.common import ensure_user_from_callback, ensure_user_from_message
from bot.states.states import state_storage


router = Router(name="admin")
settings = get_settings()
ADMIN_PAGE_SIZE = 8


def _is_admin(user_id: int | None) -> bool:
    return bool(user_id and user_id in settings.admin_id_set)


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def _menu(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _as_int(value: str, default: int = 0) -> int:
    try:
        return int(value.strip())
    except ValueError:
        return default


def _has_admin_state(message: Message) -> bool:
    if not message.from_user:
        return False
    state = state_storage.get(message.from_user.id)
    return bool(state and state.name.startswith("admin_"))


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-zA-Zа-яА-ЯёЁ0-9]+", "-", title.lower()).strip("-")
    return slug[:100] or "story"


async def _unique_slug(session, title: str, current_story_id: int | None = None) -> str:
    base = _slugify(title)
    slug = base
    suffix = 2
    while True:
        statement = select(Story).where(Story.slug == slug)
        if current_story_id:
            statement = statement.where(Story.id != current_story_id)
        if await session.scalar(statement) is None:
            return slug
        slug = f"{base}-{suffix}"
        suffix += 1


async def _deny_callback(callback: CallbackQuery) -> None:
    await callback.answer("Недостаточно прав.", show_alert=True)


async def _require_admin_callback(callback: CallbackQuery) -> bool:
    if not _is_admin(callback.from_user.id):
        await _deny_callback(callback)
        return False
    await ensure_user_from_callback(callback)
    return True


async def _safe_edit(callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup) -> None:
    if callback.message:
        await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


async def _answer_payload(message: Message, payload: tuple[str, InlineKeyboardMarkup] | None) -> None:
    if payload is None:
        await message.answer("Запись не найдена или уже удалена.")
        return
    text, keyboard = payload
    await message.answer(text, reply_markup=keyboard)


def _admin_home_keyboard() -> InlineKeyboardMarkup:
    return _menu(
        [
            [_btn("📚 Истории", "admin:stories:1"), _btn("➕ Новая история", "admin:add_story")],
            [_btn("📊 Статистика", "admin:stats"), _btn("📢 Рассылка", "admin:broadcast")],
        ]
    )


async def _send_admin_menu(target: Message | CallbackQuery) -> None:
    text = (
        "🛠 Админ-панель\n\n"
        "Управление контентом:\n"
        "• истории;\n"
        "• сезоны;\n"
        "• серии;\n"
        "• пункты гайда и последствия.\n\n"
        "Выбери раздел:"
    )
    if isinstance(target, CallbackQuery):
        if target.message:
            await target.message.edit_text(text, reply_markup=_admin_home_keyboard())
        await target.answer()
    else:
        await target.answer(text, reply_markup=_admin_home_keyboard())


async def _stories_keyboard(page: int) -> tuple[str, InlineKeyboardMarkup]:
    async with AsyncSessionFactory() as session:
        total = await session.scalar(select(func.count(Story.id))) or 0
        total_pages = max(1, (total + ADMIN_PAGE_SIZE - 1) // ADMIN_PAGE_SIZE)
        page = max(1, min(page, total_pages))
        stories = list(
            (
                await session.scalars(
                    select(Story).order_by(Story.title).offset((page - 1) * ADMIN_PAGE_SIZE).limit(ADMIN_PAGE_SIZE)
                )
            ).all()
        )
    rows = [[_btn(f"📖 {story.title}", f"admin:story:{story.id}")] for story in stories]
    rows.append(
        [
            _btn("⬅️", f"admin:stories:{max(1, page - 1)}"),
            _btn(f"{page}/{total_pages}", "admin:noop"),
            _btn("➡️", f"admin:stories:{min(total_pages, page + 1)}"),
        ]
    )
    rows.append([_btn("➕ Новая история", "admin:add_story")])
    rows.append([_btn("🔙 Админ", "admin")])
    return f"📚 Истории\n\nВсего: {total}\nВыбери историю:", _menu(rows)


async def _story_payload(story_id: int) -> tuple[str, InlineKeyboardMarkup] | None:
    async with AsyncSessionFactory() as session:
        story = await session.scalar(
            select(Story)
            .options(selectinload(Story.seasons).selectinload(Season.episodes))
            .where(Story.id == story_id)
        )
    if story is None:
        return None
    seasons_count = len(story.seasons)
    episodes_count = sum(len(season.episodes) for season in story.seasons)
    text = (
        f"📖 {story.title}\n\n"
        f"ID: {story.id}\n"
        f"Жанр: {story.genre or 'не указан'}\n"
        f"Статус: {story.status}\n"
        f"Сезонов: {seasons_count}\n"
        f"Серий: {episodes_count}\n\n"
        f"{story.description or 'Описание не заполнено.'}"
    )
    rows = [
        [_btn("✏️ Название", f"admin:story_edit:{story.id}:title"), _btn("📝 Описание", f"admin:story_edit:{story.id}:description")],
        [_btn("🏷 Жанр", f"admin:story_edit:{story.id}:genre"), _btn("📌 Статус", f"admin:story_edit:{story.id}:status")],
        [_btn("📚 Сезоны", f"admin:seasons:{story.id}"), _btn("➕ Сезон", f"admin:add_season:{story.id}")],
        [_btn("🗑 Удалить историю", f"admin:delete_story_confirm:{story.id}")],
        [_btn("🔙 К списку", "admin:stories:1"), _btn("🏠 Админ", "admin")],
    ]
    return text, _menu(rows)


async def _seasons_payload(story_id: int) -> tuple[str, InlineKeyboardMarkup] | None:
    async with AsyncSessionFactory() as session:
        story = await session.get(Story, story_id)
        seasons = list((await session.scalars(select(Season).where(Season.story_id == story_id).order_by(Season.number))).all())
    if story is None:
        return None
    rows = [[_btn(f"📚 Сезон {season.number}: {season.title or 'Без названия'}", f"admin:season:{season.id}")] for season in seasons]
    rows.append([_btn("➕ Добавить сезон", f"admin:add_season:{story_id}")])
    rows.append([_btn("🔙 История", f"admin:story:{story_id}")])
    return f"📚 Сезоны\n\nИстория: {story.title}\nВсего: {len(seasons)}", _menu(rows)


async def _season_payload(season_id: int) -> tuple[str, InlineKeyboardMarkup] | None:
    async with AsyncSessionFactory() as session:
        season = await session.scalar(select(Season).options(selectinload(Season.story)).where(Season.id == season_id))
        episodes = list((await session.scalars(select(Episode).where(Episode.season_id == season_id).order_by(Episode.number))).all())
    if season is None:
        return None
    rows = [[_btn(f"🎬 Серия {episode.number}: {episode.title or 'Без названия'}", f"admin:episode:{episode.id}")] for episode in episodes]
    rows.append([_btn("➕ Добавить серию", f"admin:add_episode:{season_id}")])
    rows.append([_btn("✏️ Название сезона", f"admin:season_edit:{season_id}:title")])
    rows.append([_btn("🗑 Удалить сезон", f"admin:delete_season_confirm:{season_id}")])
    rows.append([_btn("🔙 Сезоны", f"admin:seasons:{season.story_id}")])
    text = f"📚 {season.story.title}\nСезон {season.number}: {season.title or 'Без названия'}\n\nСерий: {len(episodes)}"
    return text, _menu(rows)


async def _episode_payload(episode_id: int) -> tuple[str, InlineKeyboardMarkup] | None:
    async with AsyncSessionFactory() as session:
        episode = await session.scalar(
            select(Episode)
            .options(selectinload(Episode.season).selectinload(Season.story), selectinload(Episode.choices))
            .where(Episode.id == episode_id)
        )
    if episode is None:
        return None
    text = (
        f"🎬 {episode.season.story.title}\n"
        f"Сезон {episode.season.number} • Серия {episode.number}\n\n"
        f"Название: {episode.title or 'Без названия'}\n"
        f"Пунктов гайда: {len(episode.choices)}\n\n"
        f"Кратко: {episode.summary or 'не заполнено'}\n\n"
        f"Вступление гайда: {episode.guide_intro or 'не заполнено'}"
    )
    rows = [
        [_btn("✏️ Название", f"admin:episode_edit:{episode.id}:title"), _btn("📝 Кратко", f"admin:episode_edit:{episode.id}:summary")],
        [_btn("🧭 Вступление гайда", f"admin:episode_edit:{episode.id}:guide_intro")],
        [_btn("📋 Пункты гайда", f"admin:choices:{episode.id}:1"), _btn("➕ Пункт гайда", f"admin:add_choice:{episode.id}")],
        [_btn("🗑 Удалить серию", f"admin:delete_episode_confirm:{episode.id}")],
        [_btn("🔙 Сезон", f"admin:season:{episode.season_id}")],
    ]
    return text, _menu(rows)


async def _choices_payload(episode_id: int, page: int) -> tuple[str, InlineKeyboardMarkup] | None:
    async with AsyncSessionFactory() as session:
        episode = await session.scalar(select(Episode).options(selectinload(Episode.season).selectinload(Season.story)).where(Episode.id == episode_id))
        total = await session.scalar(select(func.count(Choice.id)).where(Choice.episode_id == episode_id)) or 0
        total_pages = max(1, (total + ADMIN_PAGE_SIZE - 1) // ADMIN_PAGE_SIZE)
        page = max(1, min(page, total_pages))
        choices = list(
            (
                await session.scalars(
                    select(Choice)
                    .where(Choice.episode_id == episode_id)
                    .order_by(Choice.order_index, Choice.id)
                    .offset((page - 1) * ADMIN_PAGE_SIZE)
                    .limit(ADMIN_PAGE_SIZE)
                )
            ).all()
        )
    if episode is None:
        return None
    rows = [[_btn(f"{choice.order_index}. {choice.scene_title or choice.recommended_option[:35]}", f"admin:choice:{choice.id}")] for choice in choices]
    rows.append([_btn("⬅️", f"admin:choices:{episode_id}:{max(1, page - 1)}"), _btn(f"{page}/{total_pages}", "admin:noop"), _btn("➡️", f"admin:choices:{episode_id}:{min(total_pages, page + 1)}")])
    rows.append([_btn("➕ Добавить пункт", f"admin:add_choice:{episode_id}")])
    rows.append([_btn("🔙 Серия", f"admin:episode:{episode_id}")])
    text = f"📋 Пункты гайда\n\n{episode.season.story.title}\nСезон {episode.season.number} • Серия {episode.number}\nВсего: {total}"
    return text, _menu(rows)


async def _choice_payload(choice_id: int) -> tuple[str, InlineKeyboardMarkup] | None:
    async with AsyncSessionFactory() as session:
        choice = await session.scalar(select(Choice).options(selectinload(Choice.episode)).where(Choice.id == choice_id))
    if choice is None:
        return None
    text = (
        f"🧭 Пункт гайда #{choice.id}\n\n"
        f"Порядок: {choice.order_index}\n"
        f"Сцена: {choice.scene_title or 'не указана'}\n"
        f"Текст: {choice.text}\n\n"
        f"Рекомендация: {choice.recommended_option}\n"
        f"Стоимость: {choice.cost_diamonds} 💎\n"
        f"Последствие: {choice.consequence or 'не заполнено'}\n"
        f"Теги: {choice.tags or 'нет'}"
    )
    rows = [
        [_btn("✏️ Сцена", f"admin:choice_edit:{choice.id}:scene_title"), _btn("🧾 Текст", f"admin:choice_edit:{choice.id}:text")],
        [_btn("✅ Рекомендация", f"admin:choice_edit:{choice.id}:recommended_option")],
        [_btn("💎 Стоимость", f"admin:choice_edit:{choice.id}:cost_diamonds"), _btn("📌 Порядок", f"admin:choice_edit:{choice.id}:order_index")],
        [_btn("📎 Последствие", f"admin:choice_edit:{choice.id}:consequence"), _btn("🏷 Теги", f"admin:choice_edit:{choice.id}:tags")],
        [_btn("🗑 Удалить пункт", f"admin:delete_choice_confirm:{choice.id}")],
        [_btn("🔙 Пункты", f"admin:choices:{choice.episode_id}:1")],
    ]
    return text, _menu(rows)


@router.message(Command("admin"))
async def admin_command(message: Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        await message.answer("Недостаточно прав.")
        return
    await ensure_user_from_message(message)
    await _send_admin_menu(message)


@router.message(Command("cancel"))
async def admin_cancel_command(message: Message) -> None:
    if message.from_user:
        state = state_storage.get(message.from_user.id)
        if state and state.name.startswith("admin_"):
            state_storage.clear(message.from_user.id)
            await message.answer("Действие отменено.", reply_markup=_admin_home_keyboard())


@router.callback_query(F.data == "admin")
async def admin_callback(callback: CallbackQuery) -> None:
    if await _require_admin_callback(callback):
        await _send_admin_menu(callback)


@router.callback_query(F.data == "admin:noop")
async def admin_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data == "admin:stats")
async def admin_stats_callback(callback: CallbackQuery) -> None:
    if not await _require_admin_callback(callback):
        return
    async with AsyncSessionFactory() as session:
        stats = await content.admin_stats(session)
    text = (
        "📊 Статистика\n\n"
        f"👥 Пользователи: {stats['users']}\n"
        f"📖 Истории: {stats['stories']}\n"
        f"🎬 Серии: {stats['episodes']}\n"
        f"🧭 Пункты гайдов: {stats['choices']}\n"
        f"⭐ Избранное: {stats['favorites']}\n"
        f"🔔 Подписки: {stats['subscriptions']}"
    )
    await _safe_edit(callback, text, _menu([[_btn("🔙 Админ", "admin")]]))


@router.callback_query(F.data.startswith("admin:stories:"))
async def admin_stories_callback(callback: CallbackQuery) -> None:
    if await _require_admin_callback(callback):
        await _safe_edit(callback, *await _stories_keyboard(int(callback.data.rsplit(":", 1)[1])))


@router.callback_query(F.data.startswith("admin:story:"))
async def admin_story_callback(callback: CallbackQuery) -> None:
    if not await _require_admin_callback(callback):
        return
    payload = await _story_payload(int(callback.data.rsplit(":", 1)[1]))
    if payload:
        await _safe_edit(callback, *payload)
    else:
        await callback.answer("История не найдена.", show_alert=True)


@router.callback_query(F.data.startswith("admin:seasons:"))
async def admin_seasons_callback(callback: CallbackQuery) -> None:
    if not await _require_admin_callback(callback):
        return
    payload = await _seasons_payload(int(callback.data.rsplit(":", 1)[1]))
    if payload:
        await _safe_edit(callback, *payload)


@router.callback_query(F.data.startswith("admin:season:"))
async def admin_season_callback(callback: CallbackQuery) -> None:
    if not await _require_admin_callback(callback):
        return
    payload = await _season_payload(int(callback.data.rsplit(":", 1)[1]))
    if payload:
        await _safe_edit(callback, *payload)


@router.callback_query(F.data.startswith("admin:episode:"))
async def admin_episode_callback(callback: CallbackQuery) -> None:
    if not await _require_admin_callback(callback):
        return
    payload = await _episode_payload(int(callback.data.rsplit(":", 1)[1]))
    if payload:
        await _safe_edit(callback, *payload)


@router.callback_query(F.data.startswith("admin:choices:"))
async def admin_choices_callback(callback: CallbackQuery) -> None:
    if not await _require_admin_callback(callback):
        return
    _, _, raw_episode_id, raw_page = callback.data.split(":", 3)
    payload = await _choices_payload(int(raw_episode_id), int(raw_page))
    if payload:
        await _safe_edit(callback, *payload)


@router.callback_query(F.data.startswith("admin:choice:"))
async def admin_choice_callback(callback: CallbackQuery) -> None:
    if not await _require_admin_callback(callback):
        return
    payload = await _choice_payload(int(callback.data.rsplit(":", 1)[1]))
    if payload:
        await _safe_edit(callback, *payload)


@router.callback_query(F.data == "admin:add_story")
async def admin_add_story_callback(callback: CallbackQuery) -> None:
    if not await _require_admin_callback(callback):
        return
    state_storage.set(callback.from_user.id, "admin_add_story_title")
    await _safe_edit(callback, "➕ Новая история\n\nВведи название истории.\n\n/cancel — отмена", _menu([[_btn("🔙 Админ", "admin")]]))


@router.callback_query(F.data.startswith("admin:add_season:"))
async def admin_add_season_callback(callback: CallbackQuery) -> None:
    if not await _require_admin_callback(callback):
        return
    story_id = int(callback.data.rsplit(":", 1)[1])
    state_storage.set(callback.from_user.id, "admin_add_season_number", story_id=story_id)
    await _safe_edit(callback, "➕ Новый сезон\n\nВведи номер сезона, например: 1\n\n/cancel — отмена", _menu([[_btn("🔙 История", f"admin:story:{story_id}")]]))


@router.callback_query(F.data.startswith("admin:add_episode:"))
async def admin_add_episode_callback(callback: CallbackQuery) -> None:
    if not await _require_admin_callback(callback):
        return
    season_id = int(callback.data.rsplit(":", 1)[1])
    state_storage.set(callback.from_user.id, "admin_add_episode_number", season_id=season_id)
    await _safe_edit(callback, "➕ Новая серия\n\nВведи номер серии, например: 1\n\n/cancel — отмена", _menu([[_btn("🔙 Сезон", f"admin:season:{season_id}")]]))


@router.callback_query(F.data.startswith("admin:add_choice:"))
async def admin_add_choice_callback(callback: CallbackQuery) -> None:
    if not await _require_admin_callback(callback):
        return
    episode_id = int(callback.data.rsplit(":", 1)[1])
    state_storage.set(callback.from_user.id, "admin_add_choice_scene", episode_id=episode_id)
    await _safe_edit(callback, "➕ Пункт гайда\n\nВведи название сцены/выбора.\n\n/cancel — отмена", _menu([[_btn("🔙 Серия", f"admin:episode:{episode_id}")]]))


@router.callback_query(F.data.startswith("admin:story_edit:"))
async def admin_story_edit_callback(callback: CallbackQuery) -> None:
    if not await _require_admin_callback(callback):
        return
    _, _, raw_id, field = callback.data.split(":", 3)
    state_storage.set(callback.from_user.id, "admin_edit_story_field", story_id=int(raw_id), field=field)
    await _safe_edit(callback, f"✏️ Введи новое значение для поля `{field}`.\n\n/cancel — отмена", _menu([[_btn("🔙 История", f"admin:story:{raw_id}")]]))


@router.callback_query(F.data.startswith("admin:season_edit:"))
async def admin_season_edit_callback(callback: CallbackQuery) -> None:
    if not await _require_admin_callback(callback):
        return
    _, _, raw_id, field = callback.data.split(":", 3)
    state_storage.set(callback.from_user.id, "admin_edit_season_field", season_id=int(raw_id), field=field)
    await _safe_edit(callback, f"✏️ Введи новое значение для поля `{field}`.\n\n/cancel — отмена", _menu([[_btn("🔙 Сезон", f"admin:season:{raw_id}")]]))


@router.callback_query(F.data.startswith("admin:episode_edit:"))
async def admin_episode_edit_callback(callback: CallbackQuery) -> None:
    if not await _require_admin_callback(callback):
        return
    _, _, raw_id, field = callback.data.split(":", 3)
    state_storage.set(callback.from_user.id, "admin_edit_episode_field", episode_id=int(raw_id), field=field)
    await _safe_edit(callback, f"✏️ Введи новое значение для поля `{field}`.\n\n/cancel — отмена", _menu([[_btn("🔙 Серия", f"admin:episode:{raw_id}")]]))


@router.callback_query(F.data.startswith("admin:choice_edit:"))
async def admin_choice_edit_callback(callback: CallbackQuery) -> None:
    if not await _require_admin_callback(callback):
        return
    _, _, raw_id, field = callback.data.split(":", 3)
    state_storage.set(callback.from_user.id, "admin_edit_choice_field", choice_id=int(raw_id), field=field)
    await _safe_edit(callback, f"✏️ Введи новое значение для поля `{field}`.\n\n/cancel — отмена", _menu([[_btn("🔙 Пункт", f"admin:choice:{raw_id}")]]))


@router.callback_query(F.data.startswith("admin:delete_story_confirm:"))
async def admin_delete_story_confirm(callback: CallbackQuery) -> None:
    if await _require_admin_callback(callback):
        story_id = int(callback.data.rsplit(":", 1)[1])
        await _safe_edit(callback, "Удалить историю со всем содержимым?", _menu([[_btn("✅ Удалить", f"admin:delete_story:{story_id}")], [_btn("🔙 Назад", f"admin:story:{story_id}")]]))


@router.callback_query(F.data.startswith("admin:delete_season_confirm:"))
async def admin_delete_season_confirm(callback: CallbackQuery) -> None:
    if await _require_admin_callback(callback):
        season_id = int(callback.data.rsplit(":", 1)[1])
        await _safe_edit(callback, "Удалить сезон со всеми сериями?", _menu([[_btn("✅ Удалить", f"admin:delete_season:{season_id}")], [_btn("🔙 Назад", f"admin:season:{season_id}")]]))


@router.callback_query(F.data.startswith("admin:delete_episode_confirm:"))
async def admin_delete_episode_confirm(callback: CallbackQuery) -> None:
    if await _require_admin_callback(callback):
        episode_id = int(callback.data.rsplit(":", 1)[1])
        await _safe_edit(callback, "Удалить серию со всеми пунктами гайда?", _menu([[_btn("✅ Удалить", f"admin:delete_episode:{episode_id}")], [_btn("🔙 Назад", f"admin:episode:{episode_id}")]]))


@router.callback_query(F.data.startswith("admin:delete_choice_confirm:"))
async def admin_delete_choice_confirm(callback: CallbackQuery) -> None:
    if await _require_admin_callback(callback):
        choice_id = int(callback.data.rsplit(":", 1)[1])
        await _safe_edit(callback, "Удалить пункт гайда?", _menu([[_btn("✅ Удалить", f"admin:delete_choice:{choice_id}")], [_btn("🔙 Назад", f"admin:choice:{choice_id}")]]))


@router.callback_query(F.data.startswith("admin:delete_story:"))
async def admin_delete_story_callback(callback: CallbackQuery) -> None:
    if not await _require_admin_callback(callback):
        return
    async with AsyncSessionFactory() as session:
        await session.execute(delete(Story).where(Story.id == int(callback.data.rsplit(":", 1)[1])))
        await session.commit()
    await _safe_edit(callback, *await _stories_keyboard(1))


@router.callback_query(F.data.startswith("admin:delete_season:"))
async def admin_delete_season_callback(callback: CallbackQuery) -> None:
    if not await _require_admin_callback(callback):
        return
    season_id = int(callback.data.rsplit(":", 1)[1])
    async with AsyncSessionFactory() as session:
        season = await session.get(Season, season_id)
        story_id = season.story_id if season else None
        await session.execute(delete(Season).where(Season.id == season_id))
        await session.commit()
    if story_id:
        await _safe_edit(callback, *await _seasons_payload(story_id))


@router.callback_query(F.data.startswith("admin:delete_episode:"))
async def admin_delete_episode_callback(callback: CallbackQuery) -> None:
    if not await _require_admin_callback(callback):
        return
    episode_id = int(callback.data.rsplit(":", 1)[1])
    async with AsyncSessionFactory() as session:
        episode = await session.get(Episode, episode_id)
        season_id = episode.season_id if episode else None
        await session.execute(delete(Episode).where(Episode.id == episode_id))
        await session.commit()
    if season_id:
        await _safe_edit(callback, *await _season_payload(season_id))


@router.callback_query(F.data.startswith("admin:delete_choice:"))
async def admin_delete_choice_callback(callback: CallbackQuery) -> None:
    if not await _require_admin_callback(callback):
        return
    choice_id = int(callback.data.rsplit(":", 1)[1])
    async with AsyncSessionFactory() as session:
        choice = await session.get(Choice, choice_id)
        episode_id = choice.episode_id if choice else None
        await session.execute(delete(Choice).where(Choice.id == choice_id))
        await session.commit()
    if episode_id:
        await _safe_edit(callback, *await _choices_payload(episode_id, 1))


@router.callback_query(F.data == "admin:broadcast")
async def admin_broadcast_callback(callback: CallbackQuery) -> None:
    if await _require_admin_callback(callback):
        state_storage.set(callback.from_user.id, "admin_broadcast_text")
        await _safe_edit(callback, "📢 Рассылка\n\nОтправь текст сообщения.\n\n/cancel — отмена", _menu([[_btn("🔙 Админ", "admin")]]))


@router.callback_query(F.data == "admin:broadcast:send")
async def admin_broadcast_send_callback(callback: CallbackQuery, bot: Bot) -> None:
    if not await _require_admin_callback(callback):
        return
    state = state_storage.get(callback.from_user.id)
    if not state or "text" not in state.data:
        await callback.answer("Текст рассылки не найден.", show_alert=True)
        return
    text = str(state.data["text"])
    sent = 0
    async with AsyncSessionFactory() as session:
        users = (await session.scalars(select(User.telegram_id))).all()
    for telegram_id in users:
        try:
            await bot.send_message(telegram_id, text)
            sent += 1
        except Exception:
            continue
    state_storage.clear(callback.from_user.id)
    await _safe_edit(callback, f"📢 Рассылка завершена.\n\nОтправлено: {sent}", _admin_home_keyboard())


@router.callback_query(F.data == "admin:broadcast:cancel")
async def admin_broadcast_cancel_callback(callback: CallbackQuery) -> None:
    if await _require_admin_callback(callback):
        state_storage.clear(callback.from_user.id)
        await _safe_edit(callback, "Рассылка отменена.", _admin_home_keyboard())


@router.message(F.text, _has_admin_state)
async def admin_text_state_handler(message: Message) -> None:
    if not message.from_user or not message.text or message.text.startswith("/"):
        return
    state = state_storage.get(message.from_user.id)
    if not state or not state.name.startswith("admin_"):
        return
    if not _is_admin(message.from_user.id):
        state_storage.clear(message.from_user.id)
        return

    text = message.text.strip()

    if state.name == "admin_add_story_title":
        state_storage.set(message.from_user.id, "admin_add_story_description", title=text)
        await message.answer("Теперь введи описание.")
        return
    if state.name == "admin_add_story_description":
        state_storage.set(message.from_user.id, "admin_add_story_genre", title=state.data["title"], description=text)
        await message.answer("Введи жанр. Если не нужен, напиши `-`.")
        return
    if state.name == "admin_add_story_genre":
        async with AsyncSessionFactory() as session:
            title = str(state.data["title"])
            story = Story(title=title, slug=await _unique_slug(session, title), description=str(state.data["description"]), genre=None if text == "-" else text, status="ongoing", is_published=True, views_count=0)
            session.add(story)
            await session.commit()
            await session.refresh(story)
            story_id = story.id
        state_storage.clear(message.from_user.id)
        await message.answer("✅ История создана.")
        await _answer_payload(message, await _story_payload(story_id))
        return

    if state.name == "admin_add_season_number":
        state_storage.set(message.from_user.id, "admin_add_season_title", story_id=state.data["story_id"], number=_as_int(text, 1))
        await message.answer("Введи название сезона. Если не нужно, напиши `-`.")
        return
    if state.name == "admin_add_season_title":
        async with AsyncSessionFactory() as session:
            season = Season(story_id=int(state.data["story_id"]), number=int(state.data["number"]), title=None if text == "-" else text, description="")
            session.add(season)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                await message.answer("Такой номер сезона уже есть у этой истории. Введи другой номер.")
                state_storage.set(message.from_user.id, "admin_add_season_number", story_id=state.data["story_id"])
                return
            await session.refresh(season)
            season_id = season.id
        state_storage.clear(message.from_user.id)
        await message.answer("✅ Сезон создан.")
        await _answer_payload(message, await _season_payload(season_id))
        return

    if state.name == "admin_add_episode_number":
        state_storage.set(message.from_user.id, "admin_add_episode_title", season_id=state.data["season_id"], number=_as_int(text, 1))
        await message.answer("Введи название серии.")
        return
    if state.name == "admin_add_episode_title":
        state_storage.set(message.from_user.id, "admin_add_episode_summary", **state.data, title=text)
        await message.answer("Введи краткое описание серии. Если не нужно, напиши `-`.")
        return
    if state.name == "admin_add_episode_summary":
        state_storage.set(message.from_user.id, "admin_add_episode_intro", **state.data, summary="" if text == "-" else text)
        await message.answer("Введи вступление гайда. Если не нужно, напиши `-`.")
        return
    if state.name == "admin_add_episode_intro":
        async with AsyncSessionFactory() as session:
            episode = Episode(season_id=int(state.data["season_id"]), number=int(state.data["number"]), title=str(state.data["title"]), summary=str(state.data["summary"]), guide_intro="" if text == "-" else text, is_published=True)
            session.add(episode)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                await message.answer("Такая серия уже есть в этом сезоне. Введи другой номер серии.")
                state_storage.set(message.from_user.id, "admin_add_episode_number", season_id=state.data["season_id"])
                return
            await session.refresh(episode)
            episode_id = episode.id
        state_storage.clear(message.from_user.id)
        await message.answer("✅ Серия создана.")
        await _answer_payload(message, await _episode_payload(episode_id))
        return

    if state.name == "admin_add_choice_scene":
        state_storage.set(message.from_user.id, "admin_add_choice_text", episode_id=state.data["episode_id"], scene_title=text)
        await message.answer("Введи текст выбора/ситуации.")
        return
    if state.name == "admin_add_choice_text":
        state_storage.set(message.from_user.id, "admin_add_choice_recommended", **state.data, choice_text=text)
        await message.answer("Введи рекомендуемый вариант.")
        return
    if state.name == "admin_add_choice_recommended":
        state_storage.set(message.from_user.id, "admin_add_choice_cost", **state.data, recommended_option=text)
        await message.answer("Введи стоимость в алмазах числом. Если бесплатно, напиши `0`.")
        return
    if state.name == "admin_add_choice_cost":
        state_storage.set(message.from_user.id, "admin_add_choice_consequence", **state.data, cost_diamonds=_as_int(text, 0))
        await message.answer("Введи последствие выбора.")
        return
    if state.name == "admin_add_choice_consequence":
        state_storage.set(message.from_user.id, "admin_add_choice_tags", **state.data, consequence=text)
        await message.answer("Введи теги через запятую: diamond, romance, parameter, critical. Если не нужны, напиши `-`.")
        return
    if state.name == "admin_add_choice_tags":
        async with AsyncSessionFactory() as session:
            max_order = await session.scalar(select(func.max(Choice.order_index)).where(Choice.episode_id == int(state.data["episode_id"]))) or 0
            choice = Choice(episode_id=int(state.data["episode_id"]), order_index=max_order + 1, scene_title=str(state.data["scene_title"]), text=str(state.data["choice_text"]), recommended_option=str(state.data["recommended_option"]), cost_diamonds=int(state.data["cost_diamonds"]), consequence=str(state.data["consequence"]), requirements="", parameter_changes="", character_effects="", future_effects="", tags="" if text == "-" else text, spoiler_level=1, is_critical="critical" in text.lower())
            session.add(choice)
            await session.commit()
            await session.refresh(choice)
            choice_id = choice.id
        state_storage.clear(message.from_user.id)
        await message.answer("✅ Пункт гайда создан.")
        await _answer_payload(message, await _choice_payload(choice_id))
        return

    if state.name == "admin_edit_story_field":
        story_id = int(state.data["story_id"])
        field = str(state.data["field"])
        async with AsyncSessionFactory() as session:
            story = await session.get(Story, story_id)
            if story:
                setattr(story, field, text)
                if field == "title":
                    story.slug = await _unique_slug(session, text, story_id)
                await session.commit()
        state_storage.clear(message.from_user.id)
        await message.answer("✅ История обновлена.")
        await _answer_payload(message, await _story_payload(story_id))
        return

    if state.name == "admin_edit_season_field":
        season_id = int(state.data["season_id"])
        field = str(state.data["field"])
        async with AsyncSessionFactory() as session:
            season = await session.get(Season, season_id)
            if season:
                setattr(season, field, None if text == "-" else text)
                await session.commit()
        state_storage.clear(message.from_user.id)
        await message.answer("✅ Сезон обновлён.")
        await _answer_payload(message, await _season_payload(season_id))
        return

    if state.name == "admin_edit_episode_field":
        episode_id = int(state.data["episode_id"])
        field = str(state.data["field"])
        async with AsyncSessionFactory() as session:
            episode = await session.get(Episode, episode_id)
            if episode:
                setattr(episode, field, "" if text == "-" else text)
                await session.commit()
        state_storage.clear(message.from_user.id)
        await message.answer("✅ Серия обновлена.")
        await _answer_payload(message, await _episode_payload(episode_id))
        return

    if state.name == "admin_edit_choice_field":
        choice_id = int(state.data["choice_id"])
        field = str(state.data["field"])
        async with AsyncSessionFactory() as session:
            choice = await session.get(Choice, choice_id)
            if choice:
                if field in {"cost_diamonds", "order_index"}:
                    setattr(choice, field, _as_int(text, 0))
                else:
                    setattr(choice, field, "" if text == "-" else text)
                if field == "tags":
                    choice.is_critical = "critical" in text.lower()
                await session.commit()
        state_storage.clear(message.from_user.id)
        await message.answer("✅ Пункт гайда обновлён.")
        await _answer_payload(message, await _choice_payload(choice_id))
        return

    if state.name == "admin_broadcast_text":
        state_storage.set(message.from_user.id, "admin_broadcast_confirm", text=text)
        async with AsyncSessionFactory() as session:
            stats = await content.admin_stats(session)
        await message.answer(
            f"📢 Предпросмотр\n\n{text}\n\n👥 Получателей: {stats['users']}",
            reply_markup=_menu([[_btn("✅ Отправить", "admin:broadcast:send")], [_btn("❌ Отмена", "admin:broadcast:cancel")]]),
        )
