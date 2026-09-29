import asyncio
import pytest
from bot.database.database import AsyncSessionFactory
from bot.handlers.admin_content import _content_home_payload
from bot.services.content_engine.ai_generator import ContentAIEngine
from bot.services.content_engine.topic_generator import AutoContentSuggester, TopicIdea


def test_suggest_topic_ideas():
    async def _test():
        async with AsyncSessionFactory() as session:
            ideas = await AutoContentSuggester.suggest_topic_ideas(session, count=4)
            assert len(ideas) == 4
            for idea in ideas:
                assert isinstance(idea, TopicIdea)
                assert idea.title
                assert idea.topic
                assert idea.main_point
                assert idea.facts
                assert idea.cta
                assert idea.image_concept
    asyncio.run(_test())


def test_get_random_topic():
    async def _test():
        async with AsyncSessionFactory() as session:
            idea = await AutoContentSuggester.get_random_topic(session)
            assert isinstance(idea, TopicIdea)
            assert idea.topic
            assert len(idea.facts) > 0
    asyncio.run(_test())


def test_expand_user_query_character():
    async def _test():
        async with AsyncSessionFactory() as session:
            idea = await AutoContentSuggester.expand_user_query(session, "Люцифер")
            assert "Люцифер" in idea.topic or (idea.character_name and "Люцифер" in idea.character_name)
            assert idea.target_story
            assert idea.main_point
            assert idea.cta
    asyncio.run(_test())


def test_expand_user_query_story():
    async def _test():
        async with AsyncSessionFactory() as session:
            idea = await AutoContentSuggester.expand_user_query(session, "Секрет Небес")
            assert "Секрет Небес" in idea.target_story or "Секрет Небес" in idea.topic
    asyncio.run(_test())


def test_expand_user_query_diamonds():
    async def _test():
        async with AsyncSessionFactory() as session:
            idea = await AutoContentSuggester.expand_user_query(session, "как копить алмазы")
            assert "алмаз" in idea.topic.lower() or "алмаз" in idea.title.lower()
    asyncio.run(_test())


def test_clean_input_strips_technical_labels():
    engine = ContentAIEngine(api_key=None)
    dirty_facts = "Факты:\nВ некоторых сериях не обязательно покупать все платные выборы"
    cleaned = engine._clean_input(dirty_facts)
    assert not cleaned.lower().startswith("факты:")
    assert "В некоторых сериях" in cleaned

    dirty_cta = "СТА: Полный гайд доступен в нашем Telegram-боте!"
    cleaned_cta = engine._clean_input(dirty_cta)
    assert not cleaned_cta.lower().startswith("ста:")
    assert "Полный гайд доступен" in cleaned_cta

    # Generate fallback without raw labels
    result = engine._generate_template_fallback(
        topic="Секреты ветки с Люцифером",
        main_point="В некоторых сериях не обязательно покупать выборы",
        facts="Факты:\nСТА: Полный гайд доступен в нашем Telegram-боте!",
        cta="СТА: Полный гайд доступен в нашем Telegram-боте!",
        target_story="Секрет Небес",
    )
    for plat, v in result.variants.items():
        assert "Факты:" not in v.text
        assert "СТА:" not in v.text


def test_content_home_has_new_autopilot_buttons():
    async def _test():
        text, kb = await _content_home_payload()
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "admin:content:auto_ideas" in callbacks
        assert "admin:content:smart_create" in callbacks
    asyncio.run(_test())
