from datetime import datetime, timezone
import logging
from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import get_settings
from bot.database.database import AsyncSessionFactory
from bot.database.models import Story
from bot.database.repositories import content, social
from bot.handlers.common import ensure_user_from_callback, ensure_user_from_message
from bot.services.content_engine.ai_generator import ContentAIEngine
from bot.services.content_engine.publishers import (
    InstagramPublisher,
    TelegramPublisher,
    ThreadsPublisher,
    VkPublisher,
)
from bot.services.content_engine.scheduler import dispatch_post, get_platform_publishers
from bot.services.content_engine.topic_generator import AutoContentSuggester, TopicIdea
from bot.services.content_engine.types import PostStatus, SocialPlatform, VariantStatus
from bot.states.states import state_storage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)
router = Router(name="admin_content")
settings = get_settings()
ai_engine = ContentAIEngine()
_cached_ideas: dict[str, TopicIdea] = {}


def _is_admin(user_id: int | None) -> bool:
    return bool(user_id and user_id in settings.admin_id_set)


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def _menu(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _deny(callback: CallbackQuery) -> None:
    await callback.answer("Недостаточно прав.", show_alert=True)


# --- Keyboards ---

async def _content_home_payload() -> tuple[str, InlineKeyboardMarkup]:
    async with AsyncSessionFactory() as session:
        overview = await social.get_social_overview(session)

    text = (
        "📱 <b>Управление контентом для соцсетей</b>\n\n"
        "Централизованный хаб создания, AI-адаптации и публикации постов в Telegram, VK, Instagram и Threads.\n\n"
        f"📝 Черновики: <b>{overview['drafts']}</b>\n"
        f"📅 Запланировано: <b>{overview['scheduled']}</b>\n"
        f"✅ Опубликовано: <b>{overview['published']}</b>\n"
        f"❌ Ошибки: <b>{overview['failed']}</b>\n"
        f"🔗 Переходов по UTM: <b>{overview['attributions']}</b>"
    )
    kb = _menu([
        [_btn("✨ Придумать пост (Автопилот)", "admin:content:auto_ideas")],
        [_btn("💡 Создать по теме (1 шаг)", "admin:content:smart_create"), _btn("🛠 По шагам", "admin:content:create")],
        [_btn(f"📝 Черновики ({overview['drafts']})", f"admin:content:list:{PostStatus.DRAFT.value}:1"), _btn(f"📅 Запланированные ({overview['scheduled']})", f"admin:content:list:{PostStatus.SCHEDULED.value}:1")],
        [_btn(f"✅ Опубликованные ({overview['published']})", f"admin:content:list:{PostStatus.PUBLISHED.value}:1"), _btn(f"❌ Ошибки ({overview['failed']})", f"admin:content:list:{PostStatus.FAILED.value}:1")],
        [_btn("⚙️ Соцсети", "admin:content:settings")],
        [_btn("🔙 В админ-панель", "admin")],
    ])
    return text, kb


def _social_settings_keyboard() -> tuple[str, InlineKeyboardMarkup]:
    tg_pub = TelegramPublisher()
    vk_pub = VkPublisher()
    ig_pub = InstagramPublisher()
    th_pub = ThreadsPublisher()
    curr_settings = get_settings()

    tg_icon = "🟢 подключён" if tg_pub.is_configured() else "🔴 не подключён"
    vk_icon = "🟢 подключён" if vk_pub.is_configured() else "🔴 не подключён"
    ig_icon = "🟢 подключён" if ig_pub.is_configured() else "🔴 не подключён"
    th_icon = "🟢 подключён" if th_pub.is_configured() else "🔴 не подключён"
    dry_run_text = "⚠️ <b>ВКЛЮЧЁН (Безопасный режим)</b>" if curr_settings.social_publish_dry_run else "🟢 ВЫКЛЮЧЕН (Реальные публикации)"
    dry_run_btn_title = "🟢 Выключить Dry-Run (Боевой режим)" if curr_settings.social_publish_dry_run else "⚠️ Включить Dry-Run (Безопасный режим)"

    text = (
        "⚙️ <b>Состояние подключения площадок</b>\n\n"
        f"• Telegram: {tg_icon}\n"
        f"• VK: {vk_icon}\n"
        f"• Instagram: {ig_icon}\n"
        f"• Threads: {th_icon}\n\n"
        f"🛡 Dry-Run: {dry_run_text}\n\n"
        "<i>Нажмите «Тест», чтобы отправить проверочное сообщение на подключенную площадку.</i>"
    )
    rows = [
        [_btn(dry_run_btn_title, "admin:content:toggle_dry_run")],
        [_btn("🧪 Тест Telegram", "admin:content:test_channel:telegram"), _btn("🧪 Тест VK", "admin:content:test_channel:vk")],
        [_btn("🧪 Тест Instagram", "admin:content:test_channel:instagram"), _btn("🧪 Тест Threads", "admin:content:test_channel:threads")],
        [_btn("🔙 К контенту", "admin:content:home")],
    ]
    return text, _menu(rows)



async def _post_preview_payload(post_id: int) -> tuple[str, InlineKeyboardMarkup] | None:
    async with AsyncSessionFactory() as session:
        post = await social.get_post_with_variants(session, post_id)
    if not post:
        return None

    story_info = f" • Новелла: «{post.target_story.title}»" if post.target_story else ""
    sched_info = f"\n⏰ Запланирован на: <b>{post.scheduled_at.strftime('%Y-%m-%d %H:%M UTC')}</b>" if post.scheduled_at else ""

    lines = [
        f"📄 <b>Пост #{post.id}: {post.topic}</b>{story_info}",
        f"Статус: <b>{post.status}</b>{sched_info}",
        "──────────────────────",
    ]

    edit_buttons: list[InlineKeyboardButton] = []
    retry_buttons: list[InlineKeyboardButton] = []

    for v in post.variants:
        status_icon = "✅" if v.status == VariantStatus.PUBLISHED.value else ("❌" if v.status == VariantStatus.FAILED.value else "📝")
        plat_title = v.platform.upper()
        lines.append(f"\n{status_icon} <b>{plat_title}</b> ({v.status}):")
        lines.append(v.text)
        if v.error_message:
            lines.append(f"⚠️ <i>Ошибка: {v.error_message}</i>")

        edit_buttons.append(_btn(f"✏️ {plat_title}", f"admin:content:edit_var:{v.id}"))

        if v.status == VariantStatus.FAILED.value:
            retry_buttons.append(_btn(f"🔄 Повторить {plat_title}", f"admin:content:retry:{post.id}:{v.platform}"))

    # Image Prompt & Generated Art
    sample_prompt = next((v.image_prompt for v in post.variants if v.image_prompt), "Не сформирован")
    sample_url = next((v.image_url for v in post.variants if v.image_url), None)
    image_url_info = f'\n🖼 <b>Арт:</b> <a href="{sample_url}">Посмотреть сгенерированное фото</a>' if sample_url else ""
    lines.append("\n──────────────────────")
    lines.append(f"🎨 <b>ПРОМПТ ДЛЯ АРТА:</b>\n<code>{sample_prompt}</code>{image_url_info}")

    rows: list[list[InlineKeyboardButton]] = []
    if edit_buttons:
        # 2 per row
        for i in range(0, len(edit_buttons), 2):
            rows.append(edit_buttons[i:i+2])

    if retry_buttons:
        for i in range(0, len(retry_buttons), 2):
            rows.append(retry_buttons[i:i+2])

    action_row = [
        _btn("🖼 Сменить фото", f"admin:content:set_img:{post.id}"),
        _btn("🔄 AI Реген", f"admin:content:regen:{post.id}"),
    ]
    rows.append(action_row)

    if post.status in [PostStatus.DRAFT.value, PostStatus.SCHEDULED.value, PostStatus.FAILED.value]:
        rows.append([
            _btn("📅 Запланировать", f"admin:content:sched_prompt:{post.id}"),
            _btn("🚀 Опубликовать сейчас", f"admin:content:pub_now:{post.id}"),
        ])

    rows.append([
        _btn("🗑 Удалить пост", f"admin:content:del:{post.id}"),
        _btn("🔙 К списку", f"admin:content:list:{post.status}:1"),
    ])
    rows.append([_btn("📱 Главное меню контента", "admin:content:home")])

    return "\n".join(lines), _menu(rows)


# --- Handlers ---

@router.callback_query(F.data == "admin:content:home")
async def content_home_callback(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await _deny(callback)
        return
    text, kb = await _content_home_payload()
    if callback.message:
        await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "admin:content:settings")
async def content_settings_callback(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await _deny(callback)
        return
    text, kb = _social_settings_keyboard()
    if callback.message:
        await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "admin:content:toggle_dry_run")
async def content_toggle_dry_run_callback(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await _deny(callback)
        return
    curr_settings = get_settings()
    curr_settings.social_publish_dry_run = not curr_settings.social_publish_dry_run
    mode_name = "ВКЛЮЧЁН (эмуляция)" if curr_settings.social_publish_dry_run else "ВЫКЛЮЧЕН (боевой режим)"
    await callback.answer(f"Dry-run переключен: {mode_name}", show_alert=True)
    text, kb = _social_settings_keyboard()
    if callback.message:
        await callback.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data.startswith("admin:content:test_channel:"))
async def content_test_channel_callback(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await _deny(callback)
        return
    channel = callback.data.split(":")[3]
    publishers = get_platform_publishers(callback.bot)
    pub = publishers.get(channel)
    if not pub:
        await callback.answer("Публикатор не найден.", show_alert=True)
        return

    curr_settings = get_settings()
    if not pub.is_configured() and not curr_settings.social_publish_dry_run:
        await callback.answer(f"Площадка {channel.upper()} не настроена в .env", show_alert=True)
        return

    now_str = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M:%S UTC")
    from bot.database.models import SocialPostVariant

    test_variant = SocialPostVariant(
        id=0,
        post_id=0,
        platform=channel,
        text=(
            f"🧪 <b>Тестовое сообщение от бота «Клуб Романтики»</b>\n\n"
            f"Канал интеграции: <b>{channel.upper()}</b>\n"
            f"Время отправки: {now_str}\n\n"
            "Связь успешно установлена! 🎉"
        ),
    )
    result = await pub.publish(test_variant, dry_run=curr_settings.social_publish_dry_run)
    if result.success:
        dry_note = " [DRY-RUN]" if result.is_dry_run else ""
        msg = f"✅ Успешно отправлено в {channel.upper()}{dry_note}!\nID: {result.external_post_id}"
        await callback.answer(msg, show_alert=True)
    else:
        msg = f"❌ Ошибка в {channel.upper()}:\n{result.error_message}"
        await callback.answer(msg, show_alert=True)



@router.callback_query(F.data.startswith("admin:content:list:"))
async def content_list_callback(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await _deny(callback)
        return
    _, _, _, status, page_str = callback.data.split(":")
    page = int(page_str)
    page_size = 6

    async with AsyncSessionFactory() as session:
        posts, total = await social.list_posts_by_status(session, status=status, page=page, page_size=page_size)

    total_pages = max(1, (total + page_size - 1) // page_size)
    status_names = {
        PostStatus.DRAFT.value: "📝 Черновики",
        PostStatus.SCHEDULED.value: "📅 Запланированные",
        PostStatus.PUBLISHED.value: "✅ Опубликованные",
        PostStatus.FAILED.value: "❌ Ошибки",
    }
    title = status_names.get(status, f"Посты: {status}")

    rows: list[list[InlineKeyboardButton]] = []
    for p in posts:
        sched = f" ({p.scheduled_at.strftime('%d.%m %H:%M')})" if p.scheduled_at else ""
        rows.append([_btn(f"#{p.id} {p.topic[:28]}{sched}", f"admin:content:post:{p.id}")])

    nav_row = [
        _btn("⬅️", f"admin:content:list:{status}:{max(1, page - 1)}"),
        _btn(f"{page}/{total_pages}", "admin:noop"),
        _btn("➡️", f"admin:content:list:{status}:{min(total_pages, page + 1)}"),
    ]
    rows.append(nav_row)
    rows.append([_btn("🔙 К контенту", "admin:content:home")])

    text = f"<b>{title}</b> (Всего: {total})\n\nВыберите пост для просмотра или редактирования:"
    if callback.message:
        await callback.message.edit_text(text, reply_markup=_menu(rows))
    await callback.answer()


@router.callback_query(F.data.startswith("admin:content:post:"))
async def content_view_post_callback(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await _deny(callback)
        return
    post_id = int(callback.data.split(":")[3])
    payload = await _post_preview_payload(post_id)
    if payload and callback.message:
        text, kb = payload
        await callback.message.edit_text(text, reply_markup=kb)
    else:
        await callback.answer("Пост не найден.")
        return
    await callback.answer()


# --- Autopilot & Smart Post Creation ---

async def _create_post_from_idea(session: AsyncSession, user_id: int, idea: TopicIdea) -> int:
    story_id = None
    if idea.target_story:
        st_res = await session.execute(select(Story).where(Story.title == idea.target_story).limit(1))
        st = st_res.scalar_one_or_none()
        if st:
            story_id = st.id

    ai_res = await ai_engine.generate_variants(
        topic=idea.topic,
        main_point=idea.main_point,
        facts=idea.facts,
        cta=idea.cta,
        target_story=idea.target_story,
    )

    clean_source = idea.main_point
    if idea.facts:
        clean_source += f"\n\n{idea.facts}"

    post = await social.create_social_post(
        session=session,
        topic=idea.topic,
        source_text=clean_source,
        created_by=user_id,
        target_story_id=story_id,
    )

    for plat in [SocialPlatform.TELEGRAM, SocialPlatform.VK, SocialPlatform.INSTAGRAM, SocialPlatform.THREADS]:
        v = ai_res.variants[plat]
        await social.create_variant(
            session=session,
            post_id=post.id,
            platform=plat.value,
            text=v.text,
            image_prompt=v.image_prompt,
            image_url=v.image_url,
        )

    return post.id


@router.callback_query(F.data == "admin:content:auto_ideas")
async def content_auto_ideas_callback(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await _deny(callback)
        return
    await callback.answer("Подбираю горячие темы из базы...")

    async with AsyncSessionFactory() as session:
        ideas = await AutoContentSuggester.suggest_topic_ideas(session, count=4)

    for idea in ideas:
        _cached_ideas[idea.id] = idea

    rows = []
    for idea in ideas:
        rows.append([_btn(f"{idea.title}", f"admin:content:pick_idea:{idea.id}")])

    rows.append([_btn("🎲 Случайный пост в 1 клик", "admin:content:instant_random")])
    rows.append([_btn("🔄 Обновить темы", "admin:content:auto_ideas"), _btn("🔙 К контенту", "admin:content:home")])

    text = (
        "✨ <b>Автопилот тем из базы Клуба Романтики</b>\n\n"
        "Я проанализировал истории, фаворитов и ключевые развилки. "
        "Выберите тему — я сразу сформирую готовые посты для Telegram, VK, Instagram и Threads:\n"
    )
    if callback.message:
        await callback.message.edit_text(text, reply_markup=_menu(rows))


@router.callback_query(F.data.startswith("admin:content:pick_idea:"))
async def content_pick_idea_callback(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await _deny(callback)
        return
    idea_id = callback.data.split(":")[3]
    idea = _cached_ideas.get(idea_id)
    if not idea:
        async with AsyncSessionFactory() as session:
            idea = await AutoContentSuggester.get_random_topic(session)

    await callback.answer("Генерирую посты...")
    if callback.message:
        await callback.message.edit_text("⏳ Создаю и адаптирую пост под все платформы...")

    async with AsyncSessionFactory() as session:
        post_id = await _create_post_from_idea(session, callback.from_user.id, idea)

    payload = await _post_preview_payload(post_id)
    if payload and callback.message:
        text, kb = payload
        await callback.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data == "admin:content:instant_random")
async def content_instant_random_callback(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await _deny(callback)
        return
    await callback.answer("Придумываю пост в 1 клик...")
    if callback.message:
        await callback.message.edit_text("🎲 Выбираю интересную тему из базы и генерирую посты...")

    async with AsyncSessionFactory() as session:
        idea = await AutoContentSuggester.get_random_topic(session)
        post_id = await _create_post_from_idea(session, callback.from_user.id, idea)

    payload = await _post_preview_payload(post_id)
    if payload and callback.message:
        text, kb = payload
        await callback.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data == "admin:content:smart_create")
async def content_smart_create_start(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await _deny(callback)
        return
    state_storage.set(callback.from_user.id, "content_create_smart")
    if callback.message:
        await callback.message.edit_text(
            "💡 <b>Создание поста по свободной теме (в 1 шаг)</b>\n\n"
            "Напишите любую тему, имя фаворита или мысль следующим сообщением в чат.\n\n"
            "<i>Примеры:</i>\n"
            "• <code>Люцифер</code>\n"
            "• <code>Ветка с Аменом в ПОКН</code>\n"
            "• <code>Дорогие выборы в Кали</code>\n"
            "• <code>Как копить алмазы перед обновой</code>\n\n"
            "Бот сам определит историю, подберёт факты, сделает хук, вопрос для комментариев и CTA!",
            reply_markup=_menu([[_btn("❌ Отмена", "admin:content:home")]]),
        )
    await callback.answer()


# --- Classic Step-by-Step Creation (FSM) ---

@router.callback_query(F.data == "admin:content:create")
async def content_create_start(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await _deny(callback)
        return
    state_storage.set(callback.from_user.id, "content_create_topic", mode="manual")
    if callback.message:
        await callback.message.edit_text(
            "➕ <b>Создание нового поста (Вручную)</b>\n\n"
            "Шаг 1 из 4: Введите <b>Тему поста</b> (например: <i>Как экономить алмазы в 7 братьях</i>):",
            reply_markup=_menu([[_btn("❌ Отмена", "admin:content:home")]]),
        )
    await callback.answer()


@router.callback_query(F.data == "admin:content:ai_create")
async def content_ai_create_start(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await _deny(callback)
        return
    state_storage.set(callback.from_user.id, "content_create_topic", mode="ai")
    if callback.message:
        await callback.message.edit_text(
            "🤖 <b>Создание поста с помощью AI</b>\n\n"
            "Шаг 1 из 4: Введите <b>Тему поста</b> (например: <i>Секреты ветки с Люцифером в СН</i>):",
            reply_markup=_menu([[_btn("❌ Отмена", "admin:content:home")]]),
        )
    await callback.answer()


# --- Post Actions: Schedule, Publish, Edit, Delete ---

@router.callback_query(F.data.startswith("admin:content:sched_prompt:"))
async def content_schedule_prompt_callback(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await _deny(callback)
        return
    post_id = int(callback.data.split(":")[3])
    state_storage.set(callback.from_user.id, "content_schedule_datetime", post_id=post_id)
    if callback.message:
        await callback.message.edit_text(
            f"📅 <b>Планирование публикации поста #{post_id}</b>\n\n"
            "Введите дату и время в формате: <code>YYYY-MM-DD HH:MM</code> (по UTC)\n"
            "Пример: <code>2026-09-30 18:00</code>",
            reply_markup=_menu([[_btn("🔙 Назад", f"admin:content:post:{post_id}")]])
        )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:content:pub_now:"))
async def content_publish_now_callback(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await _deny(callback)
        return
    post_id = int(callback.data.split(":")[3])
    await callback.answer("Запускаю публикацию...")

    async with AsyncSessionFactory() as session:
        post = await social.get_post_with_variants(session, post_id)
        if not post:
            return
        publishers = get_platform_publishers(callback.bot)
        results = await dispatch_post(session, post, publishers)

    payload = await _post_preview_payload(post_id)
    if payload and callback.message:
        text, kb = payload
        await callback.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data.startswith("admin:content:retry:"))
async def content_retry_callback(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await _deny(callback)
        return
    _, _, _, post_id_str, platform = callback.data.split(":")
    post_id = int(post_id_str)
    await callback.answer(f"Повторяю публикацию для {platform.upper()}...")

    async with AsyncSessionFactory() as session:
        post = await social.get_post_with_variants(session, post_id)
        if not post:
            return
        publishers = get_platform_publishers(callback.bot)
        await dispatch_post(session, post, publishers, target_platform=platform)

    payload = await _post_preview_payload(post_id)
    if payload and callback.message:
        text, kb = payload
        await callback.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data.startswith("admin:content:edit_var:"))
async def content_edit_variant_prompt(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await _deny(callback)
        return
    variant_id = int(callback.data.split(":")[3])
    async with AsyncSessionFactory() as session:
        variant = await social.get_variant(session, variant_id)
    if not variant:
        await callback.answer("Вариант не найден.")
        return

    state_storage.set(callback.from_user.id, "content_edit_variant_text", variant_id=variant_id, post_id=variant.post_id)
    if callback.message:
        await callback.message.edit_text(
            f"✏️ <b>Редактирование версии для {variant.platform.upper()}</b> (Пост #{variant.post_id})\n\n"
            f"Текущий текст:\n\n{variant.text}\n\n"
            "Отправьте новый текст следующим сообщением в чат:",
            reply_markup=_menu([[_btn("🔙 Отмена", f"admin:content:post:{variant.post_id}")]])
        )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:content:set_img:"))
async def content_set_image_prompt(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await _deny(callback)
        return
    post_id = int(callback.data.split(":")[3])
    state_storage.set(callback.from_user.id, "content_set_image_url", post_id=post_id)
    if callback.message:
        await callback.message.edit_text(
            f"🖼 <b>Прикрепление изображения к посту #{post_id}</b>\n\n"
            "Отправьте публичный <b>URL изображения</b> или пришлите фото в этот чат:",
            reply_markup=_menu([[_btn("🔙 Отмена", f"admin:content:post:{post_id}")]])
        )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:content:del:"))
async def content_delete_post_callback(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await _deny(callback)
        return
    post_id = int(callback.data.split(":")[3])
    async with AsyncSessionFactory() as session:
        await social.delete_social_post(session, post_id)
    await callback.answer("Пост удален.", show_alert=True)
    text, kb = await _content_home_payload()
    if callback.message:
        await callback.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data.startswith("admin:content:regen:"))
async def content_regenerate_callback(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await _deny(callback)
        return
    post_id = int(callback.data.split(":")[3])
    await callback.answer("Перегенерирую контент...")

    async with AsyncSessionFactory() as session:
        post = await social.get_post_with_variants(session, post_id)
        if not post:
            return
        story_title = post.target_story.title if post.target_story else ""
        ai_res = await ai_engine.generate_variants(
            topic=post.topic,
            main_point=post.source_text,
            target_story=story_title,
        )
        for var in post.variants:
            gen_var = ai_res.variants.get(SocialPlatform(var.platform))
            if gen_var:
                await social.update_variant_text(session, var.id, gen_var.text)
                await social.update_variant_image(session, var.id, gen_var.image_url or var.image_url, gen_var.image_prompt)

    payload = await _post_preview_payload(post_id)
    if payload and callback.message:
        text, kb = payload
        await callback.message.edit_text(text, reply_markup=kb)


# --- FSM Message Handler ---

@router.message()
async def content_fsm_message_handler(message: Message) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    state = state_storage.get(message.from_user.id)
    if not state or not state.name.startswith("content_"):
        return

    text = (message.text or "").strip()

    # Step 1: Topic
    if state.name == "content_create_topic":
        mode = state.data.get("mode", "manual")
        state_storage.set(message.from_user.id, "content_create_point", mode=mode, topic=text)
        await message.answer(
            f"Тема: <b>{text}</b>\n\n"
            "Шаг 2 из 4: Введите <b>Основную мысль</b> поста:\n"
            "(Например: <i>В некоторых сериях не обязательно покупать все платные выборы.</i>)",
            reply_markup=_menu([[_btn("❌ Отмена", "admin:content:home")]])
        )
        return

    # Step 2: Main Point
    if state.name == "content_create_point":
        mode = state.data.get("mode", "manual")
        topic = state.data.get("topic", "")
        state_storage.set(message.from_user.id, "content_create_facts", mode=mode, topic=topic, main_point=text)
        await message.answer(
            "Шаг 3 из 4: Введите <b>Дополнительные факты / условия</b> (или отправьте <code>-</code>, если нет):",
            reply_markup=_menu([[_btn("❌ Отмена", "admin:content:home")]])
        )
        return

    # Step 3: Facts
    if state.name == "content_create_facts":
        mode = state.data.get("mode", "manual")
        topic = state.data.get("topic", "")
        main_point = state.data.get("main_point", "")
        facts = "" if text == "-" else text
        state_storage.set(message.from_user.id, "content_create_cta", mode=mode, topic=topic, main_point=main_point, facts=facts)
        await message.answer(
            "Шаг 4 из 4: Введите <b>Призыв к действию (CTA)</b>:\n"
            "(Или отправьте <code>-</code> для дефолтного <i>«Полный гайд доступен в нашем Telegram-боте»</i>):",
            reply_markup=_menu([[_btn("❌ Отмена", "admin:content:home")]])
        )
        return

    # Smart 1-step creation
    if state.name == "content_create_smart":
        state_storage.clear(message.from_user.id)
        await message.answer("⏳ Анализирую запрос, подбираю лор и генерирую посты...")
        async with AsyncSessionFactory() as session:
            idea = await AutoContentSuggester.expand_user_query(session, text)
            post_id = await _create_post_from_idea(session, message.from_user.id, idea)

        payload = await _post_preview_payload(post_id)
        if payload:
            text_p, kb_p = payload
            await message.answer(text_p, reply_markup=kb_p)
        return

    # Step 4: CTA -> Generate post & variants
    if state.name == "content_create_cta":
        mode = state.data.get("mode", "manual")
        topic = str(state.data.get("topic", ""))
        main_point = str(state.data.get("main_point", ""))
        facts = str(state.data.get("facts", ""))
        cta = "Полный гайд доступен в нашем Telegram-боте!" if text == "-" else text
        state_storage.clear(message.from_user.id)

        await message.answer("⏳ Создаю пост и адаптирую под платформы...")

        async with AsyncSessionFactory() as session:
            idea = TopicIdea(
                id="manual",
                category="manual",
                title=topic,
                topic=topic,
                main_point=main_point,
                facts=facts,
                cta=cta,
                target_story="",
            )
            post_id = await _create_post_from_idea(session, message.from_user.id, idea)

        await message.answer(f"✅ Пост #{post_id} успешно создан!")
        payload = await _post_preview_payload(post_id)
        if payload:
            text_p, kb_p = payload
            await message.answer(text_p, reply_markup=kb_p)
        return

    # Edit single variant text
    if state.name == "content_edit_variant_text":
        variant_id = int(state.data["variant_id"])
        post_id = int(state.data["post_id"])
        state_storage.clear(message.from_user.id)
        async with AsyncSessionFactory() as session:
            await social.update_variant_text(session, variant_id, text)
        await message.answer("✅ Версия обновлена!")
        payload = await _post_preview_payload(post_id)
        if payload:
            text_p, kb_p = payload
            await message.answer(text_p, reply_markup=kb_p)
        return

    # Set image URL or photo
    if state.name == "content_set_image_url":
        post_id = int(state.data["post_id"])
        image_url = None
        if message.photo:
            image_url = message.photo[-1].file_id
        elif text.startswith("http"):
            image_url = text
        else:
            await message.answer("Пожалуйста, отправьте корректный URL или фото.")
            return

        state_storage.clear(message.from_user.id)
        async with AsyncSessionFactory() as session:
            post = await social.get_post_with_variants(session, post_id)
            if post:
                for v in post.variants:
                    await social.update_variant_image(session, v.id, image_url)
        await message.answer("✅ Изображение прикреплено ко всем вариантам!")
        payload = await _post_preview_payload(post_id)
        if payload:
            text_p, kb_p = payload
            await message.answer(text_p, reply_markup=kb_p)
        return

    # Schedule datetime
    if state.name == "content_schedule_datetime":
        post_id = int(state.data["post_id"])
        try:
            scheduled_dt = datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        except ValueError:
            await message.answer("Неверный формат даты. Используйте <code>YYYY-MM-DD HH:MM</code>, например: <code>2026-09-30 18:00</code>")
            return

        state_storage.clear(message.from_user.id)
        async with AsyncSessionFactory() as session:
            await social.update_post_status(session, post_id, PostStatus.SCHEDULED.value, scheduled_at=scheduled_dt)
        await message.answer(f"✅ Публикация запланирована на {scheduled_dt.strftime('%Y-%m-%d %H:%M UTC')}!")
        payload = await _post_preview_payload(post_id)
        if payload:
            text_p, kb_p = payload
            await message.answer(text_p, reply_markup=kb_p)
        return
