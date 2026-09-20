import hashlib
import html
import os
import re
import sqlite3
import time
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen


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


class GuideLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href", "")
        href = href.split("#", 1)[0]
        if "Romance_Club_Prohozhdenie" not in href or not href.endswith(".html"):
            return
        url = urljoin(SOURCE_URL, href)
        if url not in self.urls:
            self.urls.append(url)


class GuideParser(HTMLParser):
    def __init__(self, source_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.source_url = source_url
        self.capture_tag: str | None = None
        self.capture_attrs: dict[str, str] = {}
        self.parts: list[str] = []
        self.current_story: str | None = None
        self.current_episode: EpisodeGuide | None = None
        self.episodes: list[EpisodeGuide] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if self.capture_tag and tag == "a":
            link_attrs = dict(attrs)
            for key in ("id", "name", "href"):
                if key in link_attrs and key not in self.capture_attrs:
                    self.capture_attrs[key] = link_attrs[key]
            return
        if tag in {"h1", "h2", "h3", "h4"}:
            self.capture_tag = tag
            self.capture_attrs = dict(attrs)
            self.parts = []

    def handle_data(self, data: str) -> None:
        if self.capture_tag:
            self.parts.append(data)
            return
        if self.current_episode:
            text = normalize_text(data)
            if len(text) >= 6:
                self.current_episode.body_parts.append(text)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != self.capture_tag:
            return
        text = normalize_text("".join(self.parts))
        attrs = self.capture_attrs
        self.capture_tag = None
        self.capture_attrs = {}
        self.parts = []
        self.handle_heading(text, attrs)

    def handle_heading(self, text: str, attrs: dict[str, str]) -> None:
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
        fragment = attrs.get("id") or attrs.get("name") or ""
        if not fragment and attrs.get("href", "").startswith("#"):
            fragment = attrs["href"][1:]
        guide = EpisodeGuide(
            story_title=self.current_story,
            season_number=int(episode_match.group(1)),
            episode_number=int(episode_match.group(2)),
            episode_title=normalize_text(episode_match.group(3)),
            source_url=f"{self.source_url}#{quote(fragment)}" if fragment else self.source_url,
        )
        self.current_episode = guide
        self.episodes.append(guide)


def normalize_text(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" .\n\t")


def normalize_story_title(value: str) -> str:
    replacements = {
        "Рожденная Луной": "Рождённая Луной",
        "Дракула. История": "Дракула. История любви",
        "Любовь со Звезд": "Любовь со звёзд",
        "Песнь о Кр. Ниле": "Песнь о Красном Ниле",
        "Ловчая Времени": "W: Ловчая времени",
        "И поглотит нас морок": "И туман поглотит нас",
        "Эдемов сад": "Райский сад",
        "Идеал Том 2": "Идеал. Том 2",
        "Разбитое сердце": "Разбитое сердце Астреи",
        "СН: Реквием": "Секрет Небес — Реквием",
        "Семь братьев": "7 Братьев",
        "Шифр Шекспира": "Код Шекспира",
        "Бюро парал. миров": "Бюро параллельных вселенных. Том 1",
        "Пришествие Номер Три": "Адвент №3",
        "Код синий": "Код Блю",
        "Там, Где Любовь": "Где любовь горит вечно",
        "Бюро. Том 2": "Бюро параллельных вселенных. Том 2",
        "Грехи, просящие": "Грехи, просящие возмездия",
        "Тени Сентфора 2": "Тени Сентфора 2 — Вне времени",
        "О красном и безмолв...": "О красном и безмолвном",
    }
    value = normalize_text(value)
    return replacements.get(value, value)


TRANSLIT = str.maketrans(
    {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ы": "y",
        "э": "e", "ю": "yu", "я": "ya", "ь": "", "ъ": "",
    }
)


def slugify(title: str) -> str:
    value = unicodedata.normalize("NFKD", title.lower()).translate(TRANSLIT)
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value[:100] if value else "story-" + hashlib.sha1(title.encode("utf-8")).hexdigest()[:12]


def db_path() -> Path:
    database_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./club_romance.db")
    if database_url.startswith("sqlite+aiosqlite:///"):
        raw = database_url.removeprefix("sqlite+aiosqlite:///")
        return Path(raw)
    if database_url.startswith("sqlite:///"):
        raw = database_url.removeprefix("sqlite:///")
        return Path(raw)
    return Path("club_romance.db")


def fetch_page(url: str) -> str:
    request = Request(url, headers={"User-Agent": "ClubRomanceBotImporter/1.0"})
    with urlopen(request, timeout=30) as response:
        body = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
    try:
        return body.decode(charset)
    except UnicodeDecodeError:
        return body.decode("cp1251", errors="replace")


def collect_guide_urls(index_html: str) -> list[str]:
    parser = GuideLinkParser()
    parser.feed(index_html)
    urls = [SOURCE_URL]
    for url in parser.urls:
        if url not in urls:
            urls.append(url)
    return urls


def parse_guides(page_html: str, source_url: str) -> list[EpisodeGuide]:
    parser = GuideParser(source_url)
    parser.feed(page_html)
    return parser.episodes


IMPORTANT_MARKERS = (
    "+1", "-1", "алмаз", "кристалл", "отнош", "репутац", "стойк", "дипломат",
    "путь", "выбираем", "выберите", "ответ", "вариант", "повлияет", "отразится",
    "улучшим", "ухудшим", "получим",
)


def trim_text(value: str, limit: int = 420) -> str:
    value = normalize_text(value)
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def split_notes(guide: EpisodeGuide) -> list[str]:
    text = normalize_text(" ".join(guide.body_parts))
    chunks = re.split(r"(?<=[.!?])\s+|(?=\([^)]+\)\s*[+—-])", text)
    notes: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        chunk = trim_text(chunk)
        lowered = chunk.lower()
        if len(chunk) < 25 or not any(marker in lowered for marker in IMPORTANT_MARKERS):
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
    for pattern in (r"\(([^()]{3,120})\)", r"[«\"]([^»\"]{3,120})[»\"]", r"[:—]\s*([^.;]{3,140})"):
        match = re.search(pattern, note)
        if match:
            return trim_text(match.group(1), 180)
    return "См. краткое последствие"


def tags_for(note: str) -> str:
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


def ensure_columns(connection: sqlite3.Connection) -> None:
    migrations = {
        "stories": {
            "guide_source_name": "ALTER TABLE stories ADD COLUMN guide_source_name VARCHAR(255)",
            "guide_source_url": "ALTER TABLE stories ADD COLUMN guide_source_url VARCHAR(500)",
        },
        "episodes": {
            "guide_source_name": "ALTER TABLE episodes ADD COLUMN guide_source_name VARCHAR(255)",
            "guide_source_url": "ALTER TABLE episodes ADD COLUMN guide_source_url VARCHAR(500)",
        },
    }
    for table, columns in migrations.items():
        existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        for column, statement in columns.items():
            if column not in existing:
                connection.execute(statement)


def remove_placeholders(connection: sqlite3.Connection) -> int:
    rows = list(
        connection.execute(
            "SELECT id FROM stories WHERE description LIKE ? AND guide_source_name IS NULL",
            (f"%{PLACEHOLDER_MARKER}%",),
        )
    )
    for (story_id,) in rows:
        connection.execute("DELETE FROM stories WHERE id = ?", (story_id,))
    return len(rows)


def get_story(connection: sqlite3.Connection, title: str) -> int:
    row = connection.execute("SELECT id FROM stories WHERE title = ? LIMIT 1", (title,)).fetchone()
    if row:
        story_id = row[0]
        connection.execute(
            "UPDATE stories SET guide_source_name = ?, guide_source_url = ? WHERE id = ?",
            (SOURCE_NAME, SOURCE_URL, story_id),
        )
        return story_id
    slug = slugify(title)
    suffix = 2
    base_slug = slug
    while connection.execute("SELECT id FROM stories WHERE slug = ?", (slug,)).fetchone():
        slug = f"{base_slug}-{suffix}"
        suffix += 1
    cursor = connection.execute(
        """
        INSERT INTO stories
            (title, slug, description, status, guide_source_name, guide_source_url, is_published, views_count)
        VALUES (?, ?, ?, ?, ?, ?, 1, 0)
        """,
        (
            title,
            slug,
            f"История импортирована с {SOURCE_NAME}. Внутри доступны сезоны, серии и краткие пункты гайда.",
            "unknown",
            SOURCE_NAME,
            SOURCE_URL,
        ),
    )
    return int(cursor.lastrowid)


def get_season(connection: sqlite3.Connection, story_id: int, number: int) -> int:
    row = connection.execute(
        "SELECT id FROM seasons WHERE story_id = ? AND number = ? LIMIT 1",
        (story_id, number),
    ).fetchone()
    if row:
        return row[0]
    cursor = connection.execute(
        "INSERT INTO seasons (story_id, number, title, description) VALUES (?, ?, ?, ?)",
        (story_id, number, f"Сезон {number}", f"Импортировано с {SOURCE_NAME}."),
    )
    return int(cursor.lastrowid)


def get_episode(connection: sqlite3.Connection, season_id: int, guide: EpisodeGuide) -> int:
    row = connection.execute(
        "SELECT id FROM episodes WHERE season_id = ? AND number = ? LIMIT 1",
        (season_id, guide.episode_number),
    ).fetchone()
    intro = (
        "Гайд автоматически собран по материалам GamesIsArt: ниже показаны пункты выборов, "
        "стоимости и последствий. Для сверки доступна ссылка на источник."
    )
    if row:
        episode_id = row[0]
        connection.execute(
            """
            UPDATE episodes
            SET title = ?, guide_intro = ?, guide_source_name = ?, guide_source_url = ?
            WHERE id = ?
            """,
            (guide.episode_title, intro, SOURCE_NAME, guide.source_url, episode_id),
        )
        return episode_id
    cursor = connection.execute(
        """
        INSERT INTO episodes
            (season_id, number, title, summary, guide_intro, guide_source_name, guide_source_url, is_published)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (
            season_id,
            guide.episode_number,
            guide.episode_title,
            f"Серия импортирована с {SOURCE_NAME}.",
            intro,
            SOURCE_NAME,
            guide.source_url,
        ),
    )
    return int(cursor.lastrowid)


def replace_choices(connection: sqlite3.Connection, episode_id: int, guide: EpisodeGuide) -> int:
    connection.execute(
        "DELETE FROM choices WHERE episode_id = ? AND tags LIKE ?",
        (episode_id, "%gamesisart_import%"),
    )
    notes = split_notes(guide)
    if not notes:
        notes = ["Автоматический импорт не нашёл коротких пунктов выбора. Откройте источник по кнопке в боте."]
    for index, note in enumerate(notes, start=1):
        tags = tags_for(note)
        connection.execute(
            """
            INSERT INTO choices
                (episode_id, order_index, scene_title, text, recommended_option, cost_diamonds,
                 consequence, requirements, parameter_changes, character_effects, future_effects,
                 tags, spoiler_level, is_critical)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                episode_id,
                index,
                f"Пункт гайда {index}",
                "Краткий пункт выбора из импортированного прохождения",
                extract_option(note),
                extract_cost(note),
                f"Краткий импортированный пункт: {trim_text(note, 360)}",
                "",
                "",
                "",
                "",
                tags,
                1,
                1 if "critical" in tags else 0,
            ),
        )
    return len(notes)


def main() -> None:
    index_page = fetch_page(SOURCE_URL)
    guide_urls = collect_guide_urls(index_page)
    guides: list[EpisodeGuide] = []
    for index, url in enumerate(guide_urls, start=1):
        page = index_page if url == SOURCE_URL else fetch_page(url)
        page_guides = parse_guides(page, url)
        guides.extend(page_guides)
        print(f"[{index}/{len(guide_urls)}] {url} -> {len(page_guides)} episodes")
        time.sleep(0.05)
    if not guides:
        raise RuntimeError("Не удалось найти истории/серии на GamesIsArt.")

    path = db_path()
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys=ON")
    ensure_columns(connection)
    deleted = remove_placeholders(connection)
    choices_count = 0
    for guide in guides:
        story_id = get_story(connection, guide.story_title)
        season_id = get_season(connection, story_id, guide.season_number)
        episode_id = get_episode(connection, season_id, guide)
        choices_count += replace_choices(connection, episode_id, guide)
    connection.commit()
    connection.close()

    print(
        f"Imported {len({guide.story_title for guide in guides})} stories, "
        f"{len(guides)} episodes and {choices_count} guide points. "
        f"Removed {deleted} old placeholder stories."
    )


if __name__ == "__main__":
    main()
