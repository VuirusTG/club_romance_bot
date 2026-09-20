from pathlib import Path

from scripts.gamesisart.parser import iter_blocks, parse_story_from_url, parser_summary
from scripts.gamesisart.validator import validate_story_document


SEVEN_URL = "https://gamesisart.ru/guide/Romance_Club_Prohozhdenie_Seven.html"
RAW_DIR = Path("data/gamesisart/raw")
PARSED_DIR = Path("data/gamesisart/parsed")


def parse_fixture():
    return parse_story_from_url(SEVEN_URL, raw_dir=RAW_DIR, parsed_dir=PARSED_DIR)


def choice_texts(document):
    return [block.choice for _season, _episode, block in iter_blocks(document) if block.choice]


def test_story_title_extraction() -> None:
    document = parse_fixture()
    assert document.source_title == "7 братьев"
    assert document.source_key == "gamesisart:romance_club_prohozhdenie_seven"


def test_season_extraction() -> None:
    document = parse_fixture()
    assert [season.number for season in document.seasons] == [1, 2, 3]
    assert [len(season.episodes) for season in document.seasons] == [10, 10, 10]


def test_episode_extraction_and_ordering() -> None:
    document = parse_fixture()
    season_one = document.seasons[0]
    assert [episode.number for episode in season_one.episodes] == list(range(1, 11))
    assert season_one.episodes[0].title == "К лучшему или к худшему"
    assert season_one.episodes[-1].title == "Как в раю"


def test_choice_extraction() -> None:
    document = parse_fixture()
    choices = choice_texts(document)
    assert len(choices) > 1000
    assert any(choice.text == "Джентльмены. Не могли бы вы помочь мне с багажом?" for choice in choices)


def test_diamond_cost_extraction() -> None:
    document = parse_fixture()
    choices = choice_texts(document)
    assert any(choice.text == "(Поцеловать её.) (20 к)" and choice.cost_diamonds == 20 for choice in choices)
    assert all(choice.cost_diamonds >= 0 for choice in choices)


def test_parameter_extraction() -> None:
    document = parse_fixture()
    choices = choice_texts(document)
    assert any("+1 принцесса" in choice.parameter_changes for choice in choices)


def test_character_effect_extraction() -> None:
    document = parse_fixture()
    choices = choice_texts(document)
    assert any("+ отношения с Тристаном" in choice.character_effects for choice in choices)


def test_block_ordering() -> None:
    document = parse_fixture()
    for season in document.seasons:
        for episode in season.episodes:
            orders = [block.order for block in episode.blocks]
            assert orders == sorted(orders)
            assert len(orders) == len(set(orders))


def test_unknown_block_preservation() -> None:
    """All 15 former unknown blocks in 7 brothers are service elements (ads, navigation,
    comment widgets) confirmed by HTML inspection. After parser v1.1.0 they are filtered
    by SKIP_TEXT_FRAGMENTS / SKIP_CLASSES, so unknown_blocks == 0 for this story.
    The parser still produces 'unknown' type blocks for truly unrecognized game content;
    this story just happens to have none."""
    document = parse_fixture()
    summary = parser_summary(document)
    # All 15 were service elements — correctly filtered now
    assert summary["unknown_blocks"] == 0


def test_validation() -> None:
    document = parse_fixture()
    result = validate_story_document(document)
    assert result.ok


def test_no_database_modification() -> None:
    db_path = Path("club_romance.db")
    before = (db_path.stat().st_size, db_path.stat().st_mtime_ns)
    parse_fixture()
    after = (db_path.stat().st_size, db_path.stat().st_mtime_ns)
    assert after == before


# ===== PHASE 5 REGRESSION TESTS =====


def test_service_elements_filtered() -> None:
    """Service elements (ads, nav, comment widgets) must NOT appear as unknown blocks.
    Confirmed by HTML inspection: all 15 former unknowns were service elements."""
    document = parse_fixture()
    for _s, _ep, block in iter_blocks(document):
        if block.type == "unknown":
            assert "window.yaContextCb" not in block.text
            assert "adfoxCode" not in block.text
            assert "Добавить комментарий" not in block.text
            assert "Читать дальше" not in block.text
            assert "Меню выбора страницы" not in block.text


def test_multi_option_block_parsed_as_single_choice() -> None:
    """Multi-option wardrobe/hairstyle blocks (dash-lists starting with '—') are
    represented as a single ChoiceDocument per <p> element.
    GamesIsArt does NOT use separate DOM elements for individual options within a group."""
    document = parse_fixture()
    choices = choice_texts(document)
    # These multi-option blocks must exist as choices
    multi_option_texts = [c.text for c in choices if c.text.startswith("—")]
    assert len(multi_option_texts) > 80, f"Expected 80+ dash-list choices, got {len(multi_option_texts)}"
    # Verify a known wardrobe block is present as a single choice
    wardrobe_choices = [c for c in choices if "Выбрать всё" in c.text or "Выбрать все" in c.text]
    assert len(wardrobe_choices) > 0, "No 'Выбрать всё' multi-option choices found"


def test_plain_number_cost_detection_s3() -> None:
    """Season 3 uses costs without 'к' keyword, e.g. '(83, +1 чертовка)'.
    Parser v1.1.0 must detect these via COST_RE_PLAIN fallback."""
    document = parse_fixture()
    choices = choice_texts(document)
    # S3 episodes must contain wardrobe blocks with costs (plain number format)
    s3 = document.seasons[2]
    s3_choices = []
    for ep in s3.episodes:
        for block in ep.blocks:
            if block.choice:
                s3_choices.append(block.choice)
    s3_diamond = [c for c in s3_choices if c.cost_diamonds > 0]
    assert len(s3_diamond) > 0, "Season 3 must have diamond choices (including plain-number format)"
    # Specific: a block with cost >= 83 must exist in S3 (e.g. 'Выбрать всё (83, ...)')
    max_cost = max(c.cost_diamonds for c in s3_diamond)
    assert max_cost >= 83, f"Expected max S3 cost >= 83, got {max_cost}"


def test_diamond_false_positive_prevention() -> None:
    """'+1 принцесса', '+2 чертовка' etc. must NOT be treated as diamond costs."""
    document = parse_fixture()
    choices = choice_texts(document)
    # Choices with '+N' stats but explicitly zero cost must stay at cost=0
    free_param_choices = [
        c for c in choices
        if c.parameter_changes and c.cost_diamonds == 0
    ]
    assert len(free_param_choices) > 100, "Expected 100+ free choices with parameters"


def test_future_effect_not_duplicated_in_choice_text() -> None:
    """Future effects must not be identical to choice.text — they should include
    extra description beyond the choice text itself."""
    document = parse_fixture()
    choices = choice_texts(document)
    for c in choices:
        for fe in c.future_effects:
            # future_effect must include more than just the choice text
            assert fe != c.text, f"Future effect identical to choice text: {c.text!r}"


def test_parser_version() -> None:
    """Parser version must be updated when logic changes."""
    from scripts.gamesisart.parser import PARSER_VERSION
    assert PARSER_VERSION == "1.2.0"


def test_diamond_choices_increased_s3() -> None:
    """After plain-number cost fix, Season 3 should have more diamond choices than before fix."""
    document = parse_fixture()
    summary = parser_summary(document)
    # With the fix, total diamond choices must be >= 300 (was 287 before fix)
    assert summary["diamond_choices"] >= 300, (
        f"Expected >= 300 diamond choices after plain-number fix, got {summary['diamond_choices']}"
    )


def test_generic_url_discovery() -> None:
    """URL discovery must dynamically match any story stem, not just Seven."""
    from scripts.gamesisart.parser import parse_html_document, discover_story_page_urls
    html_sample = (
        '<html><body><div id="main_table_td">'
        '<a href="Romance_Club_Prohozhdenie_Pirate.html#Act_1">1</a>'
        '<a href="Romance_Club_Prohozhdenie_Pirate_2.html">2</a>'
        '<a href="Romance_Club_Prohozhdenie_Pirate_3.html">3</a>'
        '</div></body></html>'
    )
    doc = parse_html_document(html_sample)
    urls = discover_story_page_urls(doc, "https://gamesisart.ru/guide/Romance_Club_Prohozhdenie_Pirate.html")
    assert len(urls) == 3
    assert urls[0].endswith("Pirate.html")
    assert urls[1].endswith("Pirate_2.html")
    assert urls[2].endswith("Pirate_3.html")


def test_season_number_variations() -> None:
    """parse_season_number must handle standard 'Сезон N' and volume 'Том N'."""
    from scripts.gamesisart.parser import parse_season_number
    assert parse_season_number('Прохождение истории "7 братьев". Сезон 1') == 1
    assert parse_season_number('Прохождение игры "Паруса в тумане". Сезон 5') == 5
    assert parse_season_number('Прохождение игры "Идеал". Том 2') == 2
    assert parse_season_number('Без номера') is None


def test_kristall_cost_detection() -> None:
    """extract_cost must handle explicit 'кристалл' variants."""
    from scripts.gamesisart.parser import extract_cost
    assert extract_cost("Выхватить его кинжал (23 кристалла)") == 23
    assert extract_cost("Особый выбор (15 кристаллов)") == 15


def test_loss_detection_zero_warnings_on_fixture() -> None:
    """After filtering service elements before counting, fixture must have zero warnings."""
    document = parse_fixture()
    assert len(document.warnings) == 0, f"Expected 0 warnings, got {document.warnings}"
