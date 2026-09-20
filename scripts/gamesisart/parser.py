from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin

from lxml import html
from lxml.html import HtmlElement

from scripts.gamesisart.discovery import (
    CATALOG_URL,
    SOURCE,
    cleanup_source_title,
    fetch_html,
    normalize_text,
    normalize_url,
    source_key_from_url,
)
from scripts.gamesisart.models import Block, ChoiceDocument, EpisodeDocument, SeasonDocument, StoryDocument
from scripts.gamesisart.validator import validate_story_document


PARSER_VERSION = "1.2.0"
DEFAULT_RAW_DIR = Path("data/gamesisart/raw")
DEFAULT_PARSED_DIR = Path("data/gamesisart/parsed")


EPISODE_HEADING_RE = re.compile(r"^\s*(\d+)\.(\d+)\.?\s+(.+?)\s*$")
SEASON_RE = re.compile(r"(?:Сезон|Том)\s+(\d+)", re.IGNORECASE)
# Primary: explicit diamond keyword
COST_RE_EXPLICIT = re.compile(r"(?<![+-])\b(\d+)\s*(?:к\b|алмаз\w*|кристалл\w*)", re.IGNORECASE)
# Fallback: plain number in multi-option dash-list "(NN, ..." or "(NN)" without keyword
# Only used when block starts with "—" (wardrobe/hairstyle block) and has no explicit keyword
COST_RE_PLAIN = re.compile(r"\((\d{1,3})(?:\s*,|\s*\))", re.IGNORECASE)

FUTURE_MARKERS = (
    "в будущем",
    "изменит сюжет",
    "изменит ваше отношение",
    "повлияет на отношения",
    "может повлиять",
    "больше не сможете",
)
CRITICAL_MARKERS = ("критич",)
CONTENT_TAGS = {"p", "div", "table", "ul", "ol", "blockquote"}
SKIP_CLASSES = {"youtube", "ya-share2", "s-menu", "m-menu", "Footer_Table", "Tab_Dop"}
# Service-only text signatures (checked against html_text of element)
SKIP_TEXT_FRAGMENTS = (
    "window.yaContextCb",
    "adfoxCode",
    "Добавить комментарий",
    "Читать дальше",
    "Меню выбора страницы",
    "Почётный читатель gamesisart.ru",
    "Почётный спонсор gamesisart.ru",
)


def parse_html_document(raw_html: str | bytes):
    parser = html.HTMLParser(encoding="utf-8")
    if isinstance(raw_html, str):
        raw_html = raw_html.encode("utf-8")
    return html.fromstring(raw_html, parser=parser)


def html_text(element: HtmlElement) -> str:
    return normalize_text(" ".join(element.text_content().split()))


def element_classes(element: HtmlElement) -> list[str]:
    return [item for item in (element.get("class") or "").split() if item]


def primary_heading_text(element: HtmlElement) -> str:
    direct_text = normalize_text(element.text or "")
    return direct_text or html_text(element)


def parse_season_number(text: str) -> int | None:
    match = SEASON_RE.search(text)
    return int(match.group(1)) if match else None


def parse_episode_heading(text: str) -> tuple[int, int, str] | None:
    match = EPISODE_HEADING_RE.match(text)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), normalize_text(match.group(3))


def extract_cost(text: str, is_dash_list: bool = False) -> int:
    """Extract diamond cost from text.

    Primary: looks for explicit 'к', 'алмаз', 'кристалл' keywords.
    Fallback: for multi-option dash-list blocks (is_dash_list=True) where some
    seasons write costs as plain numbers without keyword, e.g. "(83, +1 чертовка)".
    """
    matches = [int(m.group(1)) for m in COST_RE_EXPLICIT.finditer(text)]
    if matches:
        return max(matches)
    if is_dash_list:
        # Fallback: plain number in parentheses — only the maximum (= "Выбрать всё" price)
        plain_matches = [int(m.group(1)) for m in COST_RE_PLAIN.finditer(text) if int(m.group(1)) > 0]
        if plain_matches:
            return max(plain_matches)
    return 0


def extract_font_texts(element: HtmlElement, class_name: str) -> list[str]:
    values = []
    for item in element.xpath(f'.//*[contains(concat(" ", normalize-space(@class), " "), " {class_name} ")]'):
        text = html_text(item)
        if text:
            values.append(text)
    return values


def tags_for_choice(cost: int, parameters: list[str], characters: list[str], future: list[str], critical: bool) -> list[str]:
    tags: list[str] = []
    if cost > 0:
        tags.append("diamond")
    if parameters:
        tags.append("parameter")
    if characters:
        tags.append("romance")
    if future:
        tags.append("future")
    if critical:
        tags.append("critical")
    return tags


def future_effects_from_text(text: str) -> list[str]:
    lowered = text.lower()
    if any(marker in lowered for marker in FUTURE_MARKERS):
        return [text]
    return []


def is_critical_text(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in CRITICAL_MARKERS)


def classify_text_block(text: str) -> str:
    lowered = text.lower()
    if lowered.startswith("если ") or "при условии" in lowered:
        return "requirement"
    if any(marker in lowered for marker in FUTURE_MARKERS):
        return "effect"
    if lowered.startswith("выбираем") or "выбираем:" in lowered:
        return "note"
    return "text"


def is_navigation_or_service(element: HtmlElement) -> bool:
    if not isinstance(element.tag, str):
        return True
    classes = set(element_classes(element))
    if classes & SKIP_CLASSES:
        return True
    if element.tag in {"script", "style", "noscript", "br", "hr", "img"}:
        return True
    text = html_text(element)
    if not text:
        return True
    if element.tag == "center" and not text:
        return True
    # Filter known service text signatures (ads, navigation, comments)
    if any(fragment in text for fragment in SKIP_TEXT_FRAGMENTS):
        return True
    return False


def block_from_element(element: HtmlElement, order: int) -> Block | None:
    if is_navigation_or_service(element):
        return None
    text = html_text(element)
    if not text:
        return None

    metadata = {"tag": element.tag, "classes": element_classes(element)}
    text_items = extract_font_texts(element, "TextItem")
    text_up = extract_font_texts(element, "TextUp")
    text_down = extract_font_texts(element, "TextDown") + extract_font_texts(element, "TextDownLink")
    text_love = extract_font_texts(element, "TextLove")
    parameter_changes = text_up + text_down
    character_effects = text_love
    future_effects = future_effects_from_text(text)
    is_dash_list = element.tag == "p" and text.startswith("—")
    cost = extract_cost(text, is_dash_list=is_dash_list)
    critical = is_critical_text(text)

    if text_items:
        choice_text = " / ".join(text_items)
        choice = ChoiceDocument(
            order=order,
            text=choice_text,
            cost_diamonds=cost,
            parameter_changes=parameter_changes,
            character_effects=character_effects,
            future_effects=future_effects,
            is_critical=critical,
        )
        choice.tags = tags_for_choice(cost, parameter_changes, character_effects, future_effects, critical)
        metadata.update(
            {
                "raw_text": text,
                "text_items": text_items,
                "parameter_classes": ["TextUp"] if text_up else [],
                "character_classes": ["TextLove"] if text_love else [],
            }
        )
        return Block(order=order, type="choice", text=text, metadata=metadata, choice=choice)

    if element.tag == "p" and text.startswith("—") and (cost or parameter_changes or character_effects):
        choice = ChoiceDocument(
            order=order,
            text=text,
            cost_diamonds=cost,
            parameter_changes=parameter_changes,
            character_effects=character_effects,
            future_effects=future_effects,
            is_critical=critical,
        )
        choice.tags = tags_for_choice(cost, parameter_changes, character_effects, future_effects, critical)
        return Block(order=order, type="choice", text=text, metadata=metadata, choice=choice)


    if parameter_changes or character_effects:
        metadata.update({"parameter_changes": parameter_changes, "character_effects": character_effects})
        return Block(order=order, type="effect", text=text, metadata=metadata)

    if element.tag in {"p", "b"}:
        return Block(order=order, type=classify_text_block(text), text=text, metadata=metadata)

    return Block(order=order, type="unknown", text=text, metadata=metadata)


def find_main_container(document) -> HtmlElement:
    candidates = document.xpath('//*[@id="main_table_td"] | //td[contains(concat(" ", normalize-space(@class), " "), " main_table_td ")]')
    if candidates:
        return candidates[0]
    body = document.xpath("//body")
    return body[0] if body else document


def discover_story_page_urls(document, source_url: str) -> list[str]:
    """Discover all season page URLs for a story.

    GamesIsArt splits multi-season stories across pages:
      Romance_Club_Prohozhdenie_Foo.html     → Season 1
      Romance_Club_Prohozhdenie_Foo_2.html   → Season 2
      Romance_Club_Prohozhdenie_Foo_3.html   → Season 3  … etc.

    Works for ANY story URL by deriving the base from source_url.
    Links are searched inside the main content container only to avoid
    false matches from the global navigation sidebar (which lists ALL stories).
    """
    # Derive base name (without extension and without trailing _N suffix)
    base_url = source_url.split("?")[0].split("#")[0]
    stem = Path(base_url).stem  # e.g. "Romance_Club_Prohozhdenie_Pirate"
    # Remove trailing _N suffix from stem to get pure story base
    base_stem = re.sub(r"_\d+$", "", stem)

    urls: list[str] = [normalize_url(source_url, source_url) or source_url]

    # Pattern for season pages: base_stem + optional _N + .html (no further path)
    pattern = re.compile(
        rf"{re.escape(base_stem)}(?:_\d+)?\.html$",
        re.IGNORECASE,
    )

    # Only search links inside the main content container to avoid false
    # positives from the navigation sidebar that lists all stories.
    main_containers = document.xpath(
        '//*[@id="main_table_td"] | //td[contains(concat(" ", normalize-space(@class), " "), " main_table_td ")]'
    )
    search_root = main_containers[0] if main_containers else document

    for href in search_root.xpath(".//a/@href"):
        absolute = normalize_url(urljoin(source_url, href), source_url)
        if not absolute:
            continue
        # Must match our story's pattern
        clean = absolute.split("#")[0]
        if not pattern.search(clean):
            continue
        if absolute.split("#")[0] not in urls:
            urls.append(absolute.split("#")[0])

    # Deduplicate, sort by numeric suffix (S1 first, then S2, S3, …)
    def sort_key(u: str) -> int:
        m = re.search(r"_(\d+)\.html$", u, re.IGNORECASE)
        return int(m.group(1)) if m else 1

    urls = sorted(set(urls), key=sort_key)
    return urls


def source_title_from_document(document) -> str:
    h1 = document.xpath('string(//h1[contains(@class, "TextTopOn")])')
    title = cleanup_source_title(h1)
    title = re.sub(r"\s*\(\d+\)\s*$", "", title)
    title = re.sub(r"^Клуб романтики\.\s*", "", title, flags=re.IGNORECASE)
    return normalize_text(title)


def parse_season_page(raw_html: str | bytes, source_url: str, warnings: list[str]) -> tuple[SeasonDocument | None, str, str]:
    document = parse_html_document(raw_html)
    canonical_url = normalize_url(document.xpath('string(//link[@rel="canonical"]/@href)'), source_url) or (
        normalize_url(source_url, source_url) or source_url
    )
    source_title = source_title_from_document(document)
    season_heading = document.xpath('//h2[contains(@class, "TextTop")]')
    season_number = None
    season_title = ""
    if season_heading:
        season_text = html_text(season_heading[0])
        season_number = parse_season_number(season_text)
        season_title = season_text

    if season_number is None:
        # Fallback: a page URL without a numeric suffix (_2, _3, …) is Season 1.
        # Some older stories (e.g., Pirate) label S1 with the story title, not "Сезон 1".
        clean_url = source_url.split("?")[0].split("#")[0]
        if not re.search(r"_\d+\.html?$", clean_url, re.IGNORECASE):
            season_number = 1
            if not season_title:
                season_title = source_title
        else:
            # Try to infer season number from URL suffix
            m = re.search(r"_(\d+)\.html?$", clean_url, re.IGNORECASE)
            if m:
                season_number = int(m.group(1))
                if not season_title:
                    season_title = f"Сезон {season_number}"
            else:
                warnings.append(f"Season number not found in {source_url}.")
                return None, source_title, canonical_url

    # Reconcile season_number if URL suffix and first episode heading agree against h2 typo
    clean_url = source_url.split("?")[0].split("#")[0]
    m_url = re.search(r"_(\d+)\.html?$", clean_url, re.IGNORECASE)
    url_season = int(m_url.group(1)) if m_url else 1
    first_h3 = document.xpath('//h3[contains(@class, "TextH2")]')
    if first_h3:
        first_ep = parse_episode_heading(primary_heading_text(first_h3[0]))
        if first_ep and first_ep[0] == url_season and season_number != url_season:
            warnings.append(
                f"Page heading season {season_number} contradicts URL season {url_season} and episode headings {first_ep[0]}. Reconciling to {url_season}."
            )
            season_number = url_season
            if season_title:
                season_title = re.sub(r"(?:Сезон|Том)\s+\d+", f"Сезон {url_season}", season_title)

    season = SeasonDocument(number=season_number, title=season_title)
    main = find_main_container(document)
    current_episode: EpisodeDocument | None = None
    block_order = 1
    significant_elements = 0
    represented_elements = 0

    for element in main.iterchildren():
        if element.tag == "h3" and "TextH2" in element_classes(element):
            parsed = parse_episode_heading(primary_heading_text(element))
            if not parsed:
                warnings.append(f"Unrecognized episode heading in {source_url}: {html_text(element)}")
                current_episode = None
                continue
            heading_season, episode_number, episode_title = parsed
            if heading_season != season_number:
                warnings.append(
                    f"Skipping out-of-season preview episode {heading_season}.{episode_number} ({episode_title}) in Season {season_number} page."
                )
                current_episode = None
                continue
            current_episode = EpisodeDocument(number=episode_number, title=episode_title)
            current_episode.blocks.append(
                Block(
                    order=block_order,
                    type="heading",
                    text=primary_heading_text(element),
                    metadata={"tag": element.tag, "classes": element_classes(element)},
                )
            )
            block_order += 1
            season.episodes.append(current_episode)
            represented_elements += 1
            significant_elements += 1
            continue
        if current_episode is None:
            continue
        if is_navigation_or_service(element):
            continue
        if element.tag in CONTENT_TAGS and html_text(element):
            significant_elements += 1
        block = block_from_element(element, block_order)
        if block is None:
            continue
        current_episode.blocks.append(block)
        block_order += 1
        represented_elements += 1

    if significant_elements > represented_elements:
        warnings.append(
            f"Parser loss warning for {source_url}: {significant_elements - represented_elements} source elements were not represented."
        )
    return season, source_title, canonical_url


def raw_filename_for_url(url: str) -> str:
    stem = Path(url.split("#", 1)[0]).stem.lower()
    return f"{stem}.html"


def load_or_fetch_raw(url: str, raw_dir: Path = DEFAULT_RAW_DIR, overwrite: bool = False) -> str:
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / raw_filename_for_url(url)
    if path.exists() and not overwrite:
        return path.read_text(encoding="utf-8")
    text = fetch_html(url, timeout=20, retries=2, delay=0.5)
    path.write_text(text, encoding="utf-8")
    return text


def parse_story_from_url(
    url: str,
    raw_dir: Path = DEFAULT_RAW_DIR,
    parsed_dir: Path = DEFAULT_PARSED_DIR,
    overwrite_raw: bool = False,
) -> StoryDocument:
    first_raw = load_or_fetch_raw(url, raw_dir, overwrite=overwrite_raw)
    first_document = parse_html_document(first_raw)
    page_urls = discover_story_page_urls(first_document, url)
    warnings: list[str] = []
    seasons: list[SeasonDocument] = []
    source_title = ""
    canonical_url = normalize_url(url, url) or url

    for page_url in page_urls:
        raw = first_raw if (normalize_url(page_url, page_url) == normalize_url(url, url)) else load_or_fetch_raw(page_url, raw_dir, overwrite=overwrite_raw)
        season, page_title, page_canonical = parse_season_page(raw, page_url, warnings)
        if page_title and not source_title:
            source_title = page_title
        if page_canonical and normalize_url(page_url, page_url) == normalize_url(url, url):
            canonical_url = page_canonical
        if season:
            seasons.append(season)

    document = StoryDocument(
        parser_version=PARSER_VERSION,
        source=SOURCE,
        source_key=source_key_from_url(canonical_url),
        source_url=normalize_url(url, url) or url,
        canonical_url=canonical_url,
        source_title=source_title,
        seasons=seasons,
        warnings=warnings,
        metadata={"page_urls": page_urls},
    )
    validation = validate_story_document(document)
    document.warnings.extend(validation.warnings)
    document.errors.extend(validation.errors)
    write_parsed_json(document, parsed_dir)
    return document


def parsed_filename(document: StoryDocument) -> str:
    key = document.source_key.split(":", 1)[-1]
    return f"{key}.json"


def write_parsed_json(document: StoryDocument, parsed_dir: Path = DEFAULT_PARSED_DIR) -> Path:
    parsed_dir.mkdir(parents=True, exist_ok=True)
    path = parsed_dir / parsed_filename(document)
    path.write_text(json.dumps(document.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def iter_blocks(document: StoryDocument):
    for season in document.seasons:
        for episode in season.episodes:
            for block in episode.blocks:
                yield season, episode, block


def parser_summary(document: StoryDocument) -> dict[str, int]:
    blocks = list(iter_blocks(document))
    choices = [block.choice for _season, _episode, block in blocks if block.choice]
    return {
        "seasons": len(document.seasons),
        "episodes": sum(len(season.episodes) for season in document.seasons),
        "blocks": len(blocks),
        "choices": len(choices),
        "diamond_choices": sum(1 for choice in choices if choice and choice.cost_diamonds > 0),
        "parameter_effects": sum(1 for choice in choices if choice and choice.parameter_changes),
        "character_effects": sum(1 for choice in choices if choice and choice.character_effects),
        "future_effects": sum(1 for choice in choices if choice and choice.future_effects),
        "critical": sum(1 for choice in choices if choice and choice.is_critical),
        "unknown_blocks": sum(1 for _season, _episode, block in blocks if block.type == "unknown"),
        "warnings": len(document.warnings),
        "errors": len(document.errors),
    }
