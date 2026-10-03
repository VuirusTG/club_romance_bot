import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from bot.database.database import AsyncSessionFactory
from bot.database.models import SocialPost, SocialPostVariant
from bot.database.repositories import social
from bot.handlers.admin import _admin_home_keyboard
from bot.handlers.admin_content import _content_home_payload, _social_settings_keyboard
from bot.services.content_engine.ai_generator import ContentAIEngine
from bot.services.content_engine.attribution import generate_deep_link, parse_attribution_payload
from bot.services.content_engine.brand_voice import build_user_prompt
from bot.services.content_engine.publishers import (
    InstagramPublisher,
    TelegramPublisher,
    ThreadsPublisher,
    VkPublisher,
)
from bot.services.content_engine.scheduler import (
    dispatch_post,
    publish_single_variant,
    run_scheduled_publications_once,
)
from bot.services.content_engine.types import (
    PostStatus,
    PublishResult,
    SocialPlatform,
    VariantStatus,
)


def test_brand_voice_prompt_and_ai_fallback():
    prompt = build_user_prompt(
        topic="Экономия алмазов",
        main_point="В 3 серии можно пропустить платье",
        facts="Платье не дает статы",
        cta="Гайд в боте",
        target_story="7 Братьев",
    )
    assert "Экономия алмазов" in prompt
    assert "7 Братьев" in prompt
    assert "JSON" in prompt

    engine = ContentAIEngine(api_key=None)
    result = engine._generate_template_fallback(
        topic="Экономия алмазов",
        main_point="В 3 серии можно пропустить платье",
        facts="Платье не дает статы",
        cta="Гайд в боте",
        target_story="7 Братьев",
    )
    assert SocialPlatform.TELEGRAM in result.variants
    assert SocialPlatform.VK in result.variants
    assert SocialPlatform.INSTAGRAM in result.variants
    assert SocialPlatform.THREADS in result.variants
    assert result.image_prompt
    assert "--ar 4:5" in result.image_prompt

    # Verify platform-specific rules
    tg_text = result.variants[SocialPlatform.TELEGRAM].text
    assert "Экономия алмазов" in tg_text
    assert "Гайд" in tg_text

    ig_text = result.variants[SocialPlatform.INSTAGRAM].text
    assert "#клубромантики" in ig_text

    threads_text = result.variants[SocialPlatform.THREADS].text
    assert "?" in threads_text  # Ends with question/discussion prompt


def test_admin_keyboard_and_settings_display():
    kb = _admin_home_keyboard()
    all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
    all_cbs = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "📱 Контент" in all_texts
    assert "admin:content:home" in all_cbs

    text, kb_settings = _social_settings_keyboard()
    assert "Telegram:" in text
    assert "VK:" in text
    assert "Instagram:" in text
    assert "Threads:" in text
    assert "Dry-Run:" in text
    # Ensure no secrets or tokens are ever leaked
    assert "token" not in text.lower() or "защищены" in text


def test_social_models_and_repository_crud():
    async def _test():
        async with AsyncSessionFactory() as session:
            # 1. Create Post
            post = await social.create_social_post(
                session=session,
                topic="Тестовая тема",
                source_text="Основная мысль",
                created_by=123456,
            )
            assert post.id is not None
            assert post.status == PostStatus.DRAFT.value

            # 2. Create Variants
            var_tg = await social.create_variant(
                session=session,
                post_id=post.id,
                platform=SocialPlatform.TELEGRAM.value,
                text="Текст для телеграм",
                image_prompt="A beautiful art prompt",
            )
            var_vk = await social.create_variant(
                session=session,
                post_id=post.id,
                platform=SocialPlatform.VK.value,
                text="Текст для вк",
            )
            assert var_tg.id is not None
            assert var_vk.id is not None

            # 3. Update variant text & image
            await social.update_variant_text(session, var_tg.id, "Обновленный текст для TG")
            await social.update_variant_image(session, var_tg.id, "https://example.com/cover.jpg")

            # 4. Fetch with relations
            fetched = await social.get_post_with_variants(session, post.id)
            assert fetched is not None
            assert len(fetched.variants) == 2
            tg_fetched = next(v for v in fetched.variants if v.platform == SocialPlatform.TELEGRAM.value)
            assert tg_fetched.text == "Обновленный текст для TG"
            assert tg_fetched.image_url == "https://example.com/cover.jpg"

            # 5. Cleanup
            await social.delete_social_post(session, post.id)
            assert await social.get_post_with_variants(session, post.id) is None

    asyncio.run(_test())


def test_publishers_dry_run():
    async def _test():
        v = SocialPostVariant(
            id=999,
            post_id=1,
            platform="telegram",
            text="Тестовый пост",
            image_url=None,
        )

        tg_pub = TelegramPublisher()
        vk_pub = VkPublisher()
        ig_pub = InstagramPublisher()
        th_pub = ThreadsPublisher()

        # Dry-run execution
        res_tg = await tg_pub.publish(v, dry_run=True)
        assert res_tg.success is True
        assert res_tg.is_dry_run is True
        assert "dry_run_tg" in res_tg.external_post_id

        res_vk = await vk_pub.publish(v, dry_run=True)
        assert res_vk.success is True
        assert res_vk.is_dry_run is True

        res_ig = await ig_pub.publish(v, dry_run=True)
        assert res_ig.success is True
        assert res_ig.is_dry_run is True

        res_th = await th_pub.publish(v, dry_run=True)
        assert res_th.success is True
        assert res_th.is_dry_run is True

    asyncio.run(_test())


def test_duplicate_publication_protection_and_idempotency():
    async def _test():
        async with AsyncSessionFactory() as session:
            post = await social.create_social_post(
                session=session,
                topic="Идемпотентность",
                source_text="Тест",
                created_by=111,
            )
            variant = await social.create_variant(
                session=session,
                post_id=post.id,
                platform=SocialPlatform.TELEGRAM.value,
                text="Пост для проверки дублей",
            )

            mock_pub = MagicMock()
            mock_pub.publish = AsyncMock(return_value=PublishResult(success=True, external_post_id="tg_12345"))

            # First call publishes
            res1 = await publish_single_variant(session, variant, mock_pub, dry_run=False)
            assert res1.success is True
            assert res1.external_post_id == "tg_12345"
            assert mock_pub.publish.call_count == 1

            # Second call on refreshed variant MUST skip publishing
            refreshed = await social.get_variant(session, variant.id)
            assert refreshed.status == VariantStatus.PUBLISHED.value
            assert refreshed.external_post_id == "tg_12345"

            res2 = await publish_single_variant(session, refreshed, mock_pub, dry_run=False)
            assert res2.success is True
            # Call count MUST remain 1 (no duplicate network call!)
            assert mock_pub.publish.call_count == 1

            await social.delete_social_post(session, post.id)

    asyncio.run(_test())


def test_partial_publishing_and_retry_limit():
    async def _test():
        async with AsyncSessionFactory() as session:
            post = await social.create_social_post(
                session=session,
                topic="Частичная публикация",
                source_text="Тест",
                created_by=111,
            )
            var_tg = await social.create_variant(session, post.id, SocialPlatform.TELEGRAM.value, "Текст TG")
            var_ig = await social.create_variant(session, post.id, SocialPlatform.INSTAGRAM.value, "Текст IG")

            pub_tg = MagicMock()
            pub_tg.publish = AsyncMock(return_value=PublishResult(success=True, external_post_id="tg_ok"))

            pub_ig = MagicMock()
            pub_ig.publish = AsyncMock(return_value=PublishResult(success=False, error_message="IG API token expired"))

            publishers = {
                SocialPlatform.TELEGRAM.value: pub_tg,
                SocialPlatform.INSTAGRAM.value: pub_ig,
            }

            full_post = await social.get_post_with_variants(session, post.id)
            results = await dispatch_post(session, full_post, publishers, dry_run=False)

            assert results[SocialPlatform.TELEGRAM.value].success is True
            assert results[SocialPlatform.INSTAGRAM.value].success is False

            # Post status must be PARTIALLY_PUBLISHED
            post_after = await social.get_post_with_variants(session, post.id)
            assert post_after.status == PostStatus.PARTIALLY_PUBLISHED.value

            # Retry failed IG variant 2 more times to trigger max limit of 3
            var_ig_refreshed = next(v for v in post_after.variants if v.platform == SocialPlatform.INSTAGRAM.value)
            assert var_ig_refreshed.retry_count == 1

            # Attempt 2
            await publish_single_variant(session, var_ig_refreshed, pub_ig, dry_run=False)
            var_ig_2 = await social.get_variant(session, var_ig_refreshed.id)
            assert var_ig_2.retry_count == 2
            assert var_ig_2.status == VariantStatus.APPROVED.value

            # Attempt 3 -> exceeds max retries, must transition to FAILED
            await publish_single_variant(session, var_ig_2, pub_ig, dry_run=False)
            var_ig_3 = await social.get_variant(session, var_ig_refreshed.id)
            assert var_ig_3.retry_count == 3
            assert var_ig_3.status == VariantStatus.FAILED.value

            await social.delete_social_post(session, post.id)

    asyncio.run(_test())


def test_scheduler_due_posts_claiming():
    async def _test():
        async with AsyncSessionFactory() as session:
            due_time = datetime.now(timezone.utc) - timedelta(minutes=5)
            future_time = datetime.now(timezone.utc) + timedelta(hours=2)

            p_due = await social.create_social_post(
                session=session,
                topic="Срочный пост",
                source_text="Тест",
                created_by=111,
                status=PostStatus.SCHEDULED.value,
                scheduled_at=due_time,
            )
            p_future = await social.create_social_post(
                session=session,
                topic="Будущий пост",
                source_text="Тест",
                created_by=111,
                status=PostStatus.SCHEDULED.value,
                scheduled_at=future_time,
            )

            claimed = await social.claim_due_scheduled_posts(session)
            claimed_ids = [p.id for p in claimed]
            assert p_due.id in claimed_ids
            assert p_future.id not in claimed_ids

            # Cleanup
            await social.delete_social_post(session, p_due.id)
            await social.delete_social_post(session, p_future.id)

    asyncio.run(_test())



def test_utm_deep_link_generation_and_attribution_parsing():
    link_tg = generate_deep_link("RomanceClubBot", "tg", post_id=42)
    assert link_tg == "https://t.me/RomanceClubBot?start=from_tg_p42"

    link_vk = generate_deep_link("RomanceClubBot", "vk", campaign="summer2026")
    assert link_vk == "https://t.me/RomanceClubBot?start=from_vk_summer2026"

    parsed_tg = parse_attribution_payload("from_tg_p42")
    assert parsed_tg is not None
    assert parsed_tg["platform"] == "tg"
    assert parsed_tg["post_id"] == 42

    parsed_plain = parse_attribution_payload("from_instagram")
    assert parsed_plain is not None
    assert parsed_plain["platform"] == "instagram"
    assert parsed_plain["post_id"] is None

    assert parse_attribution_payload("unknown_link") is None


def test_post_preview_payload_character_limit():
    from bot.handlers.admin_content import _post_preview_payload

    async def _run():
        async with AsyncSessionFactory() as session:
            # Create a post with very long texts (1500+ chars each)
            post = await social.create_social_post(
                session=session,
                topic="Очень длинная тема для тестирования лимитов",
                source_text="Длинный исходный текст " * 50,
                created_by=1,
            )
            # Add variants with 1500 characters each and a 1000 char prompt
            for plat in ["telegram", "vk", "instagram", "threads"]:
                await social.create_variant(
                    session=session,
                    post_id=post.id,
                    platform=plat,
                    text=("Анализ новеллы и гайд с подробностями " * 40),
                    image_prompt=("Промпт для Midjourney со всеми деталями стиля, персонажами и атмосферой " * 15),
                )

            payload = await _post_preview_payload(post.id)
            assert payload is not None
            text, kb = payload
            # Must strictly not exceed Telegram limit (4096)
            assert len(text) <= 3900
            assert "💡 Нажмите кнопку с названием платформы ниже" in text
            # Ensure keyboard has buttons
            button_texts = [btn.text for row in kb.inline_keyboard for btn in row]
            assert "✏️ TELEGRAM" in button_texts
            assert "✏️ VK" in button_texts
            assert "✏️ INSTAGRAM" in button_texts
            assert "✏️ THREADS" in button_texts

            # Cleanup
            await social.delete_social_post(session, post.id)

    asyncio.run(_run())

