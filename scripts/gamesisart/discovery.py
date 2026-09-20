from __future__ import annotations

import argparse
import hashlib
import html
import json
import logging
import re
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen


LOGGER = logging.getLogger(__name__)

SOURCE = "gamesisart"
SOURCE_NAME = "GamesIsArt.ru"
CATALOG_URL = "https://gamesisart.ru/guide/Romance_Club_Prohozhdenie.html"
GUIDE_PREFIX = "/guide/Romance_Club_Prohozhdenie"
USER_AGENT = "ClubRomanceBotDiscovery/1.0 (+https://gamesisart.ru/guide/Romance_Club_Prohozhdenie.html)"
DEFAULT_OUTPUT_PATH = Path("data/gamesisart/discovered_sources.json")
DEFAULT_REPORT_PATH = Path("docs/GAMESISART_DISCOVERY.md")
DEFAULT_DATABASE_PATH = Path("club_romance.db")


@dataclass(frozen=True)
class GamesIsArtSource:
    source: str
    source_key: str
    source_url: str
    canonical_url: str
    source_title: str
    discovered_at: str
    discovery_method: str = "catalog_link"


@dataclass
class LinkDiscoveryStats:
    total_links: int = 0
    filtered_links: int = 0
    duplicate_urls: int = 0
    catalog_links: int = 0
    catalog_pages: int = 0
    unique_source_urls: int = 0


@dataclass
class DiscoveryResult:
    source: str
    catalog_url: str
    discovered_at: str
    sources: list[GamesIsArtSource]
    warnings: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)
    existing_db_matches: list[dict[str, str | int | None]] = field(default_factory=list)
    potential_duplicates: list[dict[str, object]] = field(default_factory=list)


class CatalogLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.hrefs.append(href)


class SourceMetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.canonical_url: str | None = None
        self.h1_parts: list[str] = []
        self.title_parts: list[str] = []
        self._capture_h1 = False
        self._capture_title = False

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        attrs_dict = {str(key).lower(): str(value) for key, value in attrs}
        if tag == "link" and attrs_dict.get("rel", "").lower() == "canonical":
            self.canonical_url = attrs_dict.get("href")
        elif tag == "h1":
            self._capture_h1 = True
        elif tag == "title":
            self._capture_title = True

    def handle_data(self, data: str) -> None:
        if self._capture_h1:
            self.h1_parts.append(data)
        if self._capture_title:
            self.title_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "h1":
            self._capture_h1 = False
        elif tag == "title":
            self._capture_title = False

    @property
    def source_title(self) -> str:
        h1 = normalize_text(" ".join(self.h1_parts))
        if h1:
            return cleanup_source_title(h1)
        return cleanup_source_title(normalize_text(" ".join(self.title_parts)))


def normalize_text(value: str) -> str:
    value = html.unescape(value or "")
    return re.sub(r"\s+", " ", value).strip()


def cleanup_source_title(value: str) -> str:
    value = normalize_text(value)
    value = re.sub(r"\s*[-—]\s*GamesIsArt\.ru.*$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^Клуб Романтики\.\s*", "", value, flags=re.IGNORECASE)
    match = re.search(r"Прохождение(?:\s+истории|\s+игры)?\s+[«\"]([^»\"]+)[»\"]", value, flags=re.IGNORECASE)
    if match:
        return normalize_text(match.group(1))
    return value


def normalize_url(raw_url: str, base_url: str = CATALOG_URL) -> str | None:
    if not raw_url:
        return None
    absolute = urljoin(base_url, raw_url)
    absolute, _fragment = urldefrag(absolute)
    parsed = urlparse(absolute)
    scheme = "https"
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = re.sub(r"/+", "/", parsed.path)
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return urlunparse((scheme, host, path, "", "", ""))


def is_story_guide_url(url: str, catalog_url: str = CATALOG_URL) -> bool:
    normalized = normalize_url(url, catalog_url)
    if not normalized or is_catalog_page_url(normalized, catalog_url):
        return False
    parsed = urlparse(normalized)
    if parsed.netloc != "gamesisart.ru":
        return False
    path = parsed.path
    if not path.startswith(GUIDE_PREFIX):
        return False
    if not path.endswith(".html"):
        return False
    lower_path = path.lower()
    blocked_suffixes = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".css", ".js")
    return not lower_path.endswith(blocked_suffixes)


def is_catalog_page_url(url: str, catalog_url: str = CATALOG_URL) -> bool:
    normalized = normalize_url(url, catalog_url)
    if not normalized:
        return False
    parsed = urlparse(normalized)
    if parsed.netloc != "gamesisart.ru":
        return False
    filename = Path(parsed.path).name
    return bool(re.fullmatch(r"Romance_Club_Prohozhdenie(?:_\d+)?\.html", filename))


def source_key_from_url(canonical_url: str) -> str:
    parsed = urlparse(canonical_url)
    stem = Path(parsed.path).stem
    key = re.sub(r"[^a-zA-Z0-9]+", "_", stem).strip("_").lower()
    if not key:
        key = hashlib.sha1(canonical_url.encode("utf-8")).hexdigest()[:16]
    return f"gamesisart:{key}"


def fetch_html(url: str, timeout: float = 20.0, retries: int = 2, delay: float = 0.5) -> str:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=timeout) as response:
                body = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
            try:
                return body.decode(charset)
            except UnicodeDecodeError:
                return body.decode("cp1251", errors="replace")
        except (HTTPError, URLError, TimeoutError) as error:
            last_error = error
            LOGGER.warning("Failed to fetch %s on attempt %s/%s: %s", url, attempt + 1, retries + 1, error)
            if attempt < retries:
                time.sleep(delay)
    raise RuntimeError(f"Unable to fetch {url}: {last_error}") from last_error


def discover_page_links(catalog_html: str, catalog_url: str = CATALOG_URL) -> tuple[list[str], list[str], LinkDiscoveryStats]:
    parser = CatalogLinkParser()
    parser.feed(catalog_html)
    stats = LinkDiscoveryStats(total_links=len(parser.hrefs))
    seen_sources: set[str] = set()
    seen_catalogs: set[str] = set()
    source_urls: list[str] = []
    catalog_urls: list[str] = []
    for href in parser.hrefs:
        normalized = normalize_url(href, catalog_url)
        if not normalized:
            stats.filtered_links += 1
            continue
        if is_catalog_page_url(normalized, catalog_url):
            stats.catalog_links += 1
            stats.filtered_links += 1
            if normalized not in seen_catalogs:
                seen_catalogs.add(normalized)
                catalog_urls.append(normalized)
            continue
        if not is_story_guide_url(normalized, catalog_url):
            stats.filtered_links += 1
            continue
        if normalized in seen_sources:
            stats.duplicate_urls += 1
            continue
        seen_sources.add(normalized)
        source_urls.append(normalized)
    stats.catalog_pages = len(catalog_urls)
    stats.unique_source_urls = len(source_urls)
    return source_urls, catalog_urls, stats


def discover_source_urls(catalog_html: str, catalog_url: str = CATALOG_URL) -> tuple[list[str], LinkDiscoveryStats]:
    source_urls, _catalog_urls, stats = discover_page_links(catalog_html, catalog_url)
    return source_urls, stats


def merge_stats(target: LinkDiscoveryStats, item: LinkDiscoveryStats) -> None:
    target.total_links += item.total_links
    target.filtered_links += item.filtered_links
    target.duplicate_urls += item.duplicate_urls
    target.catalog_links += item.catalog_links
    target.catalog_pages += item.catalog_pages


def discover_all_source_urls(
    catalog_url: str = CATALOG_URL,
    timeout: float = 20.0,
    retries: int = 2,
    delay: float = 0.5,
) -> tuple[list[str], LinkDiscoveryStats]:
    root_catalog = normalize_url(catalog_url, catalog_url) or catalog_url
    queue = [root_catalog]
    visited_catalogs: set[str] = set()
    seen_sources: set[str] = set()
    source_urls: list[str] = []
    stats = LinkDiscoveryStats()

    while queue:
        current_catalog = queue.pop(0)
        if current_catalog in visited_catalogs:
            continue
        visited_catalogs.add(current_catalog)
        catalog_html = fetch_html(current_catalog, timeout=timeout, retries=retries, delay=delay)
        page_sources, page_catalogs, page_stats = discover_page_links(catalog_html, current_catalog)
        merge_stats(stats, page_stats)
        for source_url in page_sources:
            if source_url in seen_sources:
                stats.duplicate_urls += 1
                continue
            seen_sources.add(source_url)
            source_urls.append(source_url)
        for page_catalog_url in page_catalogs:
            if page_catalog_url not in visited_catalogs and page_catalog_url not in queue:
                queue.append(page_catalog_url)
        time.sleep(delay)

    stats.catalog_pages = len(visited_catalogs)
    stats.unique_source_urls = len(source_urls)
    return source_urls, stats


def read_source_metadata(page_html: str, fallback_url: str) -> tuple[str, str, bool, bool]:
    parser = SourceMetadataParser()
    parser.feed(page_html)
    canonical = normalize_url(parser.canonical_url or "", fallback_url)
    has_canonical = bool(canonical)
    canonical_url = canonical or normalize_url(fallback_url, fallback_url) or fallback_url
    title = parser.source_title
    has_title = bool(title)
    return title, canonical_url, has_title, has_canonical


def build_sources(
    source_urls: list[str],
    discovered_at: str,
    timeout: float = 20.0,
    retries: int = 2,
    delay: float = 0.5,
) -> tuple[list[GamesIsArtSource], list[str], dict[str, int]]:
    warnings: list[str] = []
    sources: list[GamesIsArtSource] = []
    stats = {"without_title": 0, "without_canonical": 0, "suspicious": 0}
    for url in source_urls:
        try:
            page_html = fetch_html(url, timeout=timeout, retries=retries, delay=delay)
            source_title, canonical_url, has_title, has_canonical = read_source_metadata(page_html, url)
        except RuntimeError as error:
            warnings.append(str(error))
            source_title = ""
            canonical_url = normalize_url(url, url) or url
            has_title = False
            has_canonical = False
        if not has_title:
            stats["without_title"] += 1
            warnings.append(f"Source has no title: {url}")
        if not has_canonical:
            stats["without_canonical"] += 1
        if normalize_url(canonical_url, url) != normalize_url(url, url):
            stats["suspicious"] += 1
            warnings.append(f"Canonical differs from discovered URL: {url} -> {canonical_url}")
        sources.append(
            GamesIsArtSource(
                source=SOURCE,
                source_key=source_key_from_url(canonical_url),
                source_url=normalize_url(url, url) or url,
                canonical_url=canonical_url,
                source_title=source_title,
                discovered_at=discovered_at,
            )
        )
        time.sleep(delay)
    return sources, warnings, stats


def validate_sources(sources: list[GamesIsArtSource]) -> list[str]:
    conflicts: list[str] = []
    for field_name in ("source_key", "canonical_url"):
        seen: dict[str, GamesIsArtSource] = {}
        for source in sources:
            value = getattr(source, field_name)
            if value in seen:
                conflicts.append(
                    f"Duplicate {field_name}: {value} for {seen[value].source_url} and {source.source_url}"
                )
            else:
                seen[value] = source
    return conflicts


def fold_title(value: str) -> str:
    value = normalize_text(value).lower().replace("ё", "е")
    value = re.sub(r"[^a-zа-я0-9]+", "", value)
    return value


def compare_with_existing_database(
    sources: list[GamesIsArtSource],
    database_path: Path = DEFAULT_DATABASE_PATH,
) -> tuple[list[dict[str, str | int | None]], list[dict[str, object]]]:
    if not database_path.exists():
        return [], []
    by_url = {source.canonical_url: source for source in sources}
    by_title: dict[str, list[GamesIsArtSource]] = {}
    for source in sources:
        by_title.setdefault(fold_title(source.source_title), []).append(source)

    connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    rows = list(
        connection.execute(
            """
            SELECT id, title, slug, guide_source_url
            FROM stories
            WHERE guide_source_name LIKE '%GamesIsArt%' OR guide_source_url LIKE '%gamesisart%'
            ORDER BY title
            """
        )
    )
    connection.close()

    matches: list[dict[str, str | int | None]] = []
    duplicate_groups: dict[str, list[dict[str, str | int | None]]] = {}
    for row in rows:
        current_url = normalize_url(row["guide_source_url"] or "", CATALOG_URL)
        folded = fold_title(row["title"])
        title_matches = by_title.get(folded, [])
        exact_url = by_url.get(current_url or "")
        if exact_url:
            status = "exact URL match"
            discovery_url = exact_url.source_url
            discovery_title = exact_url.source_title
            source_key = exact_url.source_key
        elif title_matches:
            status = "likely title match"
            discovery_url = title_matches[0].source_url
            discovery_title = title_matches[0].source_title
            source_key = title_matches[0].source_key
        else:
            status = "no match"
            discovery_url = None
            discovery_title = None
            source_key = None
        item = {
            "story_id": row["id"],
            "current_title": row["title"],
            "current_guide_source_url": row["guide_source_url"],
            "discovery_source_url": discovery_url,
            "discovery_source_title": discovery_title,
            "source_key": source_key,
            "match_status": status,
        }
        matches.append(item)
        duplicate_groups.setdefault(folded, []).append(item)

    potential_duplicates: list[dict[str, object]] = []
    for folded, items in duplicate_groups.items():
        if len(items) <= 1:
            continue
        potential_duplicates.append(
            {
                "folded_title": folded,
                "reason": "Existing GamesIsArt stories collapse to the same title after case/punctuation/ё normalization. Report only; no merge performed.",
                "stories": items,
            }
        )
    return matches, potential_duplicates


def write_json(result: DiscoveryResult, output_path: Path = DEFAULT_OUTPUT_PATH) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": result.source,
        "catalog_url": result.catalog_url,
        "discovered_at": result.discovered_at,
        "sources": [asdict(source) for source in result.sources],
        "warnings": result.warnings,
        "conflicts": result.conflicts,
        "stats": result.stats,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_report(result: DiscoveryResult, report_path: Path = DEFAULT_REPORT_PATH) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    source_keys = {source.source_key for source in result.sources}
    canonical_urls = {source.canonical_url for source in result.sources}
    matched_count = sum(1 for item in result.existing_db_matches if item["match_status"] != "no match")
    lines = [
        "# GamesIsArt Discovery Report",
        "",
        f"Дата discovery: `{result.discovered_at}`.",
        "",
        "Статус: PHASE 3 выполнена. База данных не изменялась; parser/import/update не запускались.",
        "",
        "## Summary",
        "",
        f"- Catalog URL: `{result.catalog_url}`.",
        f"- Найдено ссылок в каталоге: `{result.stats.get('total_links', 0)}`.",
        f"- Уникальных source URLs: `{result.stats.get('unique_source_urls', len(result.sources))}`.",
        f"- Уникальных canonical URLs: `{len(canonical_urls)}`.",
        f"- Дубликатов URL в каталоге: `{result.stats.get('duplicate_urls', 0)}`.",
        f"- Отфильтрованных ссылок: `{result.stats.get('filtered_links', 0)}`.",
        f"- Источников без title: `{result.stats.get('without_title', 0)}`.",
        f"- Источников без canonical: `{result.stats.get('without_canonical', 0)}`.",
        f"- Подозрительных источников: `{result.stats.get('suspicious', 0)}`.",
        f"- Конфликтов source_key/canonical_url: `{len(result.conflicts)}`.",
        f"- Совпадений с текущей БД: `{matched_count}`.",
        f"- Потенциальных дублей в текущей БД: `{len(result.potential_duplicates)}`.",
        "",
        "## First 10 Sources",
        "",
        "| source_key | source_url | source_title |",
        "| --- | --- | --- |",
    ]
    for source in result.sources[:10]:
        lines.append(f"| `{source.source_key}` | `{source.source_url}` | {source.source_title or '-'} |")
    lines.extend(["", "## Last 10 Sources", "", "| source_key | source_url | source_title |", "| --- | --- | --- |"])
    for source in result.sources[-10:]:
        lines.append(f"| `{source.source_key}` | `{source.source_url}` | {source.source_title or '-'} |")

    lines.extend(["", "## Existing Database Comparison", "", "| Discovery source URL | Existing current guide_source_url | Source title | Current title | Source key | Match status |", "| --- | --- | --- | --- | --- | --- |"])
    for item in result.existing_db_matches:
        lines.append(
            "| "
            f"`{item.get('discovery_source_url') or '-'}` | "
            f"`{item.get('current_guide_source_url') or '-'}` | "
            f"{item.get('discovery_source_title') or '-'} | "
            f"{item.get('current_title') or '-'} | "
            f"`{item.get('source_key') or '-'}` | "
            f"{item.get('match_status') or '-'} |"
        )

    lines.extend(["", "## Potential Duplicate Stories", ""])
    if not result.potential_duplicates:
        lines.append("Потенциальные дубли по текущему read-only анализу не найдены.")
    else:
        for duplicate in result.potential_duplicates:
            lines.append(f"### `{duplicate['folded_title']}`")
            lines.append("")
            lines.append(str(duplicate["reason"]))
            lines.append("")
            lines.append("| Story ID | Current title | Current guide_source_url | Match status |")
            lines.append("| --- | --- | --- | --- |")
            for item in duplicate["stories"]:
                lines.append(
                    f"| `{item.get('story_id')}` | {item.get('current_title')} | "
                    f"`{item.get('current_guide_source_url') or '-'}` | {item.get('match_status')} |"
                )
            lines.append("")

    lines.extend(["", "## Conflicts", ""])
    if result.conflicts:
        lines.extend(f"- {conflict}" for conflict in result.conflicts)
    else:
        lines.append("Конфликтов `source_key` или `canonical_url` не обнаружено.")

    lines.extend(["", "## Warnings", ""])
    if result.warnings:
        lines.extend(f"- {warning}" for warning in result.warnings)
    else:
        lines.append("Warnings отсутствуют.")

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def discover(
    catalog_url: str = CATALOG_URL,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
    database_path: Path = DEFAULT_DATABASE_PATH,
    timeout: float = 20.0,
    retries: int = 2,
    delay: float = 0.5,
) -> DiscoveryResult:
    discovered_at = datetime.now(timezone.utc).isoformat()
    source_urls, link_stats = discover_all_source_urls(catalog_url, timeout=timeout, retries=retries, delay=delay)
    sources, warnings, metadata_stats = build_sources(source_urls, discovered_at, timeout=timeout, retries=retries, delay=delay)
    conflicts = validate_sources(sources)
    existing_matches, potential_duplicates = compare_with_existing_database(sources, database_path)
    stats = {
        **asdict(link_stats),
        **metadata_stats,
        "sources": len(sources),
        "source_keys": len({source.source_key for source in sources}),
        "canonical_urls": len({source.canonical_url for source in sources}),
        "conflicts": len(conflicts),
        "existing_db_matches": sum(1 for item in existing_matches if item["match_status"] != "no match"),
        "potential_duplicates": len(potential_duplicates),
    }
    result = DiscoveryResult(
        source=SOURCE,
        catalog_url=normalize_url(catalog_url, catalog_url) or catalog_url,
        discovered_at=discovered_at,
        sources=sources,
        warnings=warnings,
        conflicts=conflicts,
        stats=stats,
        existing_db_matches=existing_matches,
        potential_duplicates=potential_duplicates,
    )
    write_json(result, output_path)
    write_report(result, report_path)
    return result


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Discover GamesIsArt Romance Club story guide sources.")
    parser.add_argument("--catalog-url", default=CATALOG_URL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--delay", type=float, default=0.5)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    result = discover(
        catalog_url=args.catalog_url,
        output_path=args.output,
        report_path=args.report,
        database_path=args.database,
        timeout=args.timeout,
        retries=args.retries,
        delay=args.delay,
    )
    print(f"Discovered sources: {len(result.sources)}")
    print(f"Unique canonical URLs: {result.stats.get('canonical_urls', 0)}")
    print(f"Duplicate URLs: {result.stats.get('duplicate_urls', 0)}")
    print(f"Filtered links: {result.stats.get('filtered_links', 0)}")
    print(f"Conflicts: {len(result.conflicts)}")
    print(f"JSON: {args.output}")
    print(f"Report: {args.report}")
    return 0 if not result.conflicts else 2


if __name__ == "__main__":
    raise SystemExit(main())
