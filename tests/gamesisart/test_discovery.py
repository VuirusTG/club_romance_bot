from scripts.gamesisart.discovery import (
    CATALOG_URL,
    GamesIsArtSource,
    discover_source_urls,
    is_catalog_page_url,
    is_story_guide_url,
    normalize_url,
    read_source_metadata,
    source_key_from_url,
    validate_sources,
)


def test_normalize_url_removes_fragment_and_unifies_host() -> None:
    assert (
        normalize_url("http://www.gamesisart.ru/guide/Romance_Club_Prohozhdenie_Seven.html#s1")
        == "https://gamesisart.ru/guide/Romance_Club_Prohozhdenie_Seven.html"
    )


def test_source_key_is_stable_from_canonical_url() -> None:
    url = "https://gamesisart.ru/guide/Romance_Club_Prohozhdenie_Seven.html"
    assert source_key_from_url(url) == "gamesisart:romance_club_prohozhdenie_seven"
    assert source_key_from_url(url) == source_key_from_url(url + "#ignored")


def test_discover_source_urls_filters_catalog_external_and_duplicates() -> None:
    html = """
    <a href="Romance_Club_Prohozhdenie.html">catalog</a>
    <a href="Romance_Club_Prohozhdenie_Seven.html#one">seven</a>
    <a href="https://gamesisart.ru/guide/Romance_Club_Prohozhdenie_Seven.html#two">seven duplicate</a>
    <a href="https://example.com/guide/Romance_Club_Prohozhdenie_Test.html">external</a>
    <a href="/img/banner.png">image</a>
    """
    urls, stats = discover_source_urls(html, CATALOG_URL)
    assert urls == ["https://gamesisart.ru/guide/Romance_Club_Prohozhdenie_Seven.html"]
    assert stats.total_links == 5
    assert stats.duplicate_urls == 1
    assert stats.catalog_links == 1
    assert stats.filtered_links == 3
    assert stats.unique_source_urls == 1


def test_is_story_guide_url_rejects_catalog_and_external_urls() -> None:
    assert is_story_guide_url("https://gamesisart.ru/guide/Romance_Club_Prohozhdenie_Seven.html")
    assert not is_story_guide_url(CATALOG_URL)
    assert not is_story_guide_url("https://gamesisart.ru/guide/Romance_Club_Prohozhdenie_2.html")
    assert not is_story_guide_url("https://example.com/guide/Romance_Club_Prohozhdenie_Seven.html")
    assert not is_story_guide_url("https://gamesisart.ru/other/Romance_Club_Prohozhdenie_Seven.html")


def test_catalog_page_url_detects_catalog_continuations() -> None:
    assert is_catalog_page_url(CATALOG_URL)
    assert is_catalog_page_url("https://gamesisart.ru/guide/Romance_Club_Prohozhdenie_2.html#top")
    assert not is_catalog_page_url("https://gamesisart.ru/guide/Romance_Club_Prohozhdenie_Seven.html")


def test_read_source_metadata_uses_canonical_and_source_title_without_display_normalization() -> None:
    html = """
    <html>
      <head>
        <link rel="canonical" href="https://gamesisart.ru/guide/Romance_Club_Prohozhdenie_Seven.html">
        <title>Клуб Романтики. Прохождение истории "Семь братьев" - GamesIsArt.ru</title>
      </head>
      <body><h1>Прохождение истории «Семь братьев»</h1></body>
    </html>
    """
    title, canonical, has_title, has_canonical = read_source_metadata(
        html,
        "https://gamesisart.ru/guide/Romance_Club_Prohozhdenie_Seven.html?utm=1",
    )
    assert title == "Семь братьев"
    assert canonical == "https://gamesisart.ru/guide/Romance_Club_Prohozhdenie_Seven.html"
    assert has_title
    assert has_canonical


def test_validate_sources_reports_duplicate_source_key_and_canonical_url() -> None:
    sources = [
        GamesIsArtSource(
            source="gamesisart",
            source_key="gamesisart:one",
            source_url="https://gamesisart.ru/guide/Romance_Club_Prohozhdenie_One.html",
            canonical_url="https://gamesisart.ru/guide/Romance_Club_Prohozhdenie_One.html",
            source_title="One",
            discovered_at="2026-08-17T00:00:00+00:00",
        ),
        GamesIsArtSource(
            source="gamesisart",
            source_key="gamesisart:one",
            source_url="https://gamesisart.ru/guide/Romance_Club_Prohozhdenie_One_Copy.html",
            canonical_url="https://gamesisart.ru/guide/Romance_Club_Prohozhdenie_One.html",
            source_title="One Copy",
            discovered_at="2026-08-17T00:00:00+00:00",
        ),
    ]
    conflicts = validate_sources(sources)
    assert len(conflicts) == 2
    assert any("Duplicate source_key" in conflict for conflict in conflicts)
    assert any("Duplicate canonical_url" in conflict for conflict in conflicts)
