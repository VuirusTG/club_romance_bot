import asyncio
import hashlib
import html
import re
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import quote
from urllib.request import Request, urlopen

from sqlalchemy import delete, select

from bot.database.database import AsyncSessionFactory, init_db
from bot.database.models import Choice, Episode, Season, Story


SOURCE_NAME = "GamesIsArt.ru"
SOURCE_URL = "https://gamesisart.ru/guide/Romance_Club_Prohozhdenie.html"
PLACEHOLDER_MARKER = "Базовая запись добавлена для каталога"


@dataclass
class EpisodeGuide:
    story_title: str
    season_number: int
    episode_number: int
    episode_title: str
    source_url: str
    body_parts: list[str] = field(default_factory=list)


class GuideHeadingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._capture_tag: str | None = None
        self._capture_attrs: dict[str, str] = {}
        self._parts: list[str] = []
        self.current_story: str | None = None
        self.current_episode: EpisodeGuide | None = None
        self.episodes: list[EpisodeGuide] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if self._capture_tag and tag == "a":
            link_attrs = dict(attrs)
            for key in ("id", "name", "href"):
                if key in link_attrs and key not in self._capture_attrs:
                    self._capture_attrs[key] = link_attrs[key]
            return
        if tag in {"h1", "h2", "h3", "h4"}:
            self._capture_tag = tag
            self._capture_attrs = dict(attrs)
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._capture_tag:
            self._parts.append(data)
            return
        if self.current_episode:
            text = normalize_text(data)
            if len(text) >= 6:
                self.current_episode.body_parts.append(text)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != self._capture_tag:
            return
        text = normalize_text("".join(self._parts))
        attrs = self._capture_attrs
        self._capture_tag = None
        self._capture_attrs = {}
        self._parts = []
        self._handle_heading(text, attrs)

    def _handle_heading(self, text: str, attrs: dict[str, str]) -> None:
        story_match = re.search(r'Прохождение(?:\s+истории|\s+игры)?\s+[«"]([^"»]+)', text, flags=re.IGNORECASE)
        if story_match:
            self.current_story = normalize_story_title(story_match.group(1))
            self.current_episode = None
            return

        if not self.current_story:
            return

        episode_match = re.match(r"(\d+)\.(\d+)\.?\s+(.+)", text)
        if not episode_match:
            return

        season_number = int(episode_match.group(1))
        episode_number = int(episode_match.group(2))
        episode_title = normalize_text(episode_match.group(3))
        fragment = attrs.get("id") or attrs.get("name") or ""
        if not fragment and attrs.get("href", "").startswith("#"):
            fragment = attrs["href"][1:]
        source_url = f"{SOURCE_URL}#{quote(fragment)}" if fragment else SOURCE_URL
        self.current_episode = EpisodeGuide(
            story_title=self.current_story,
            season_number=season_number,
            episode_number=episode_number,
            episode_title=episode_title,
            source_url=source_url,
        )
        self.episodes.append(self.current_episode)


def normalize_text(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" .\n\t")


def normalize_story_title(value: str) -> str:
    replacements = {
        "Рожденная Луной": "Рождённая Луной",
        "Рожденная луной": "Рождённая Луной",
        "Паруса в тумане": "Паруса в тумане",
        "Моя Голл. История": "Моя Голливудская История",
        "Королева за 30 дней": "Королева за 30 дней",
        "Высокий прибой": "Высокий прибой",
        "Тени Сентфора": "Тени Сентфора",
        "В ритме страсти": "В ритме страсти",
        "Я Охочусь на Тебя": "Я охочусь на тебя",
        "Секрет Небес": "Секрет Небес",
        "Легенда Ивы": "Легенда Ивы",
        "Дракула. История": "Дракула. История любви",
        "Любовь со Звезд": "Любовь со звёзд",
        "Путь Валькирии": "Путь Валькирии",
        "Ярость Титанов": "Ярость Титанов",
        "10 Желаний Софи": "10 желаний Софи",
        "Грешный Лондон": "Грешный Лондон",
        "По тонкому льду": "По тонкому льду",
        "Арканум": "Арканум",
        "Хроники Гладиаторов": "Хроники Гладиаторов",
        "Сердце Треспии": "Сердце Треспии",
        "Кали: Зов Тьмы": "Кали: Зов Тьмы",
        "Цветок из Огня Тиамат": "Цветок из огня Тиамат",
        "Теодора": "Теодора",
        "Сквозь бурю и пламя": "Сквозь бурю и пламя",
        "Идеал": "Идеал",
        "Пси": "Пси",
        "Покоряя Версаль": "Покоряя Версаль",
        "Роза пустыни": "Роза пустыни",
        "Секрет Небес 2": "Секрет Небес 2",
        "Игра в ТЭГ": "Игра в ТЭГ",
        "Песнь о Кр. Ниле": "Песнь о Красном Ниле",
        "Я охочусь на тебя 2": "Я охочусь на тебя 2",
        "Любовь, Грех и Зло": "Любовь, грех и зло",
        "Ловчая Времени": "W: Ловчая времени",
        "И поглотит нас морок": "И туман поглотит нас",
        "Эдемов сад": "Райский сад",
        "Бездушная": "Бездушная",
        "Идеал Том 2": "Идеал. Том 2",
        "Разбитое сердце": "Разбитое сердце Астреи",
        "СН: Реквием": "Секрет Небес — Реквием",
        "Семь братьев": "7 Братьев",
        "Сага о грозах": "Сага о грозах",
        "Шифр Шекспира": "Код Шекспира",
        "Бюро парал. миров": "Бюро параллельных вселенных. Том 1",
        "Пропавшие": "Пропавшие",
        "Пришествие Номер Три": "Адвент №3",
        "Te Amo Залив над.": "Te Amo. Залив надежд",
        "Код синий": "Код Блю",
        "Там, Где Любовь": "Где любовь горит вечно",
        "Секрет Небес 3": "Секрет Небес 3",
        "Бюро. Том 2": "Бюро параллельных вселенных. Том 2",
        "Te Amo Том 2": "Te Amo. Том 2",
        "Аверрис": "Аверрис",
        "Грехи, просящие": "Грехи, просящие возмездия",
        "Тени Сентфора 2": "Тени Сентфора 2 — Вне времени",
        "Водяная Лилия": "Водяная Лилия",
        "Рождённая Солнцем": "Рождённая Солнцем",
        "Рождённый Тенью": "Рождённый Тенью",
        "О красном и безмолв...": "О красном и безмолвном",
    }
    value = normalize_text(value)
    return replacements.get(value, value)


TRANSLIT = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "e",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "y",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "h",
        "ц": "c",
        "ч": "ch",
        "ш": "sh",
        "щ": "sch",
        "ы": "y",
        "э": "e",
        "ю": "yu",
        "я": "ya",
        "ь": "",
        "ъ": "",
    }
)


def slugify(title: str) -> str:
    value = unicodedata.normalize("NFKD", title.lower())
    value = value.translate(TRANSLIT)
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    if value:
        return value[:100]
    digest = hashlib.sha1(title.encode("utf-8")).hexdigest()[:12]
    return f"story-{digest}"


def fetch_page(url: str = SOURCE_URL) -> str:
    request = Request(url, headers={"User-Agent": "ClubRomanceBotImporter/1.0"})
    with urlopen(request, timeout=30) as response:
        body = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
    try:
        return body.decode(charset)
    except UnicodeDecodeError:
        return body.decode("cp1251", errors="replace")


def parse_guides(page_html: str) -> list[EpisodeGuide]:
    parser = GuideHeadingParser()
    parser.feed(page_html)
    return parser.episodes


IMPORTANT_MARKERS = (
    "+1",
    "-1",
    "алмаз",
    "кристалл",
    "отнош",
    "репутац",
    "стойк",
    "дипломат",
    "путь",
    "выбираем",
    "выберите",
    "ответ",
    "вариант",
    "повлияет",
    "отразится",
    "улучшим",
    "ухудшим",
    "получим",
)


def trim_text(value: str, limit: int = 420) -> str:
    value = normalize_text(value)
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def split_episode_notes(guide: EpisodeGuide) -> list[str]:
    text = normalize_text(" ".join(guide.body_parts))
    if not text:
        return []
    chunks = re.split(r"(?<=[.!?])\s+|(?=\([^)]+\)\s*[+—-])", text)
    notes: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        chunk = trim_text(chunk)
        lowered = chunk.lower()
        if len(chunk) < 25:
            continue
        if not any(marker in lowered for marker in IMPORTANT_MARKERS):
            continue
        if chunk in seen:
            continue
        seen.add(chunk)
        notes.append(chunk)
        if len(notes) >= 45:
            break
    return notes


def extract_cost(note: str) -> int:
    match = re.search(r"(\d+)\s*(?:алмаз|кристалл)", note, flags=re.IGNORECASE)
    return int(match.group(1)) if match else 0


def extract_option(note: str) -> str:
    paren_match = re.search(r"\(([^()]{3,120})\)", note)
    if paren_match:
        return trim_text(paren_match.group(1), 180)
    quote_match = re.search(r"[«\"]([^»\"]{3,120})[»\"]", note)
    if quote_match:
        return trim_text(quote_match.group(1), 180)
    dash_match = re.search(r"[:—]\s*([^.;]{3,140})", note)
    if dash_match:
        return trim_text(dash_match.group(1), 180)
    return "См. краткое последствие"


def tags_for_note(note: str) -> str:
    lowered = note.lower()
    tags = ["gamesisart_import"]
    if "алмаз" in lowered or "кристалл" in lowered:
        tags.append("diamond")
    if "отнош" in lowered or "роман" in lowered or "флирт" in lowered or "поцел" in lowered:
        tags.append("romance")
    if any(marker in lowered for marker in ("+1", "-1", "стойк", "дипломат", "репутац", "путь")):
        tags.append("parameter")
    if "повлияет" in lowered or "отразится" in lowered or "в будущем" in lowered:
        tags.append("critical")
    return ",".join(dict.fromkeys(tags))


def consequence_for_note(note: str) -> str:
    note = trim_text(note, 360)
    return f"Краткий импортированный пункт: {note}"


async def get_or_create_story(session, title: str) -> Story:
    story = await session.scalar(select(Story).where(Story.title == title))
    if story is None:
        story = Story(
            title=title,
            slug=slugify(title),
            description=f"История импортирована из структуры гайдов {SOURCE_NAME}. Подробности можно уточнить в источнике.",
            genre=None,
            status="unknown",
            guide_source_name=SOURCE_NAME,
            guide_source_url=SOURCE_URL,
            is_published=True,
        )
        session.add(story)
        await session.flush()
    else:
        story.guide_source_name = SOURCE_NAME
        story.guide_source_url = SOURCE_URL
    return story


async def remove_old_placeholder_stories(session) -> int:
    placeholders = (
        await session.scalars(
            select(Story).where(
                Story.description.ilike(f"%{PLACEHOLDER_MARKER}%"),
                Story.guide_source_name.is_(None),
            )
        )
    ).all()
    deleted = len(placeholders)
    for story in placeholders:
        await session.delete(story)
    if deleted:
        await session.flush()
    return deleted


async def get_or_create_season(session, story: Story, number: int) -> Season:
    season = await session.scalar(select(Season).where(Season.story_id == story.id, Season.number == number))
    if season is None:
        season = Season(story_id=story.id, number=number, title=f"Сезон {number}", description=f"Импортировано из {SOURCE_NAME}.")
        session.add(season)
        await session.flush()
    return season


async def get_or_create_episode(session, season: Season, guide: EpisodeGuide) -> Episode:
    episode = await session.scalar(
        select(Episode).where(Episode.season_id == season.id, Episode.number == guide.episode_number)
    )
    if episode is None:
        episode = Episode(
            season_id=season.id,
            number=guide.episode_number,
            title=guide.episode_title,
            summary=f"Серия найдена в структуре прохождений {SOURCE_NAME}.",
            guide_intro=(
                "Гайд автоматически собран по материалам GamesIsArt: ниже показаны краткие пункты выборов, "
                "стоимости и последствий. Для сверки доступна ссылка на источник."
            ),
            guide_source_name=SOURCE_NAME,
            guide_source_url=guide.source_url,
            is_published=True,
        )
        session.add(episode)
        await session.flush()
    else:
        episode.title = guide.episode_title
        episode.guide_source_name = SOURCE_NAME
        episode.guide_source_url = guide.source_url
        if not episode.guide_intro:
            episode.guide_intro = "Гайд автоматически собран по материалам GamesIsArt; подробности доступны по ссылке на источник."
    return episode


async def replace_imported_choices(session, episode: Episode, guide: EpisodeGuide) -> int:
    notes = split_episode_notes(guide)
    await session.execute(
        delete(Choice).where(
            Choice.episode_id == episode.id,
            Choice.tags.ilike("%gamesisart_import%"),
        )
    )
    if not notes:
        existing_manual = await session.scalar(select(Choice).where(Choice.episode_id == episode.id))
        if existing_manual is not None:
            return 0
        session.add(
            Choice(
                episode_id=episode.id,
                order_index=1,
                scene_title="Источник прохождения",
                text="Автоматический импорт не нашёл коротких пунктов выбора для этой серии.",
                recommended_option="Открыть источник гайда по кнопке под сообщением",
                consequence="В БД сохранена структура серии и ссылка на первоисточник.",
                tags="gamesisart_import,source",
                spoiler_level=0,
            )
        )
        return 1

    for index, note in enumerate(notes, start=1):
        tags = tags_for_note(note)
        session.add(
            Choice(
                episode_id=episode.id,
                order_index=index,
                scene_title=f"Пункт гайда {index}",
                text="Краткий пункт выбора из импортированного прохождения",
                recommended_option=extract_option(note),
                cost_diamonds=extract_cost(note),
                consequence=consequence_for_note(note),
                tags=tags,
                spoiler_level=0 if "source" in tags else 1,
                is_critical="critical" in tags,
            )
        )
    return len(notes)


async def ensure_source_choice(session, episode: Episode) -> None:
    existing = await session.scalar(select(Choice).where(Choice.episode_id == episode.id))
    if existing is not None:
        return
    session.add(
        Choice(
            episode_id=episode.id,
            order_index=1,
            scene_title="Источник прохождения",
            text="Подробные выборы для этой серии нужно перенести в сокращённом проверенном виде.",
            recommended_option="Открыть источник гайда по кнопке под сообщением",
            consequence="В БД сохранена структура серии и ссылка на первоисточник.",
            tags="gamesisart_import,source",
            spoiler_level=0,
        )
    )


async def import_guides() -> None:
    await init_db()
    page_html = fetch_page()
    guides = parse_guides(page_html)
    if not guides:
        raise RuntimeError("Не удалось найти сезоны и серии на странице GamesIsArt.")

    async with AsyncSessionFactory() as session:
        deleted_placeholders = await remove_old_placeholder_stories(session)
        choices_count = 0
        for guide in guides:
            story = await get_or_create_story(session, guide.story_title)
            season = await get_or_create_season(session, story, guide.season_number)
            episode = await get_or_create_episode(session, season, guide)
            choices_count += await replace_imported_choices(session, episode, guide)
        await session.commit()

    stories_count = len({guide.story_title for guide in guides})
    print(
        f"Imported {stories_count} stories, {len(guides)} episodes and {choices_count} guide points from {SOURCE_NAME}. "
        f"Removed {deleted_placeholders} old placeholder stories."
    )


if __name__ == "__main__":
    asyncio.run(import_guides())
