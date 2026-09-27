from abc import ABC, abstractmethod
import json
import logging
import re
import aiohttp

from bot.config import get_settings
from bot.services.content_engine.brand_voice import BRAND_VOICE_SYSTEM_PROMPT, build_user_prompt
from bot.services.content_engine.types import AIGenerationResult, GeneratedVariant, SocialPlatform

logger = logging.getLogger(__name__)


class ImageGenerator(ABC):
    @abstractmethod
    async def generate(self, prompt: str, aspect_ratio: str = "4:5") -> str | None:
        pass


class DefaultImageGenerator(ImageGenerator):
    """
    Default image generator that logs the prompt.
    External image generation services (e.g. OpenAI DALL-E / FLUX / Midjourney)
    can be plugged in here or provided via manual image URL/attachment.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key

    async def generate(self, prompt: str, aspect_ratio: str = "4:5") -> str | None:
        if not self.api_key:
            logger.info(f"Image generation skipped (no API key). Prompt: {prompt[:80]}...")
            return None

        # Example implementation via OpenAI Images API if key exists
        url = "https://api.openai.com/v1/images/generations"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "dall-e-3",
            "prompt": prompt,
            "n": 1,
            "size": "1024x1024",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=45)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data["data"][0]["url"]
                    else:
                        err_text = await resp.text()
                        logger.warning(f"Image generation failed ({resp.status}): {err_text}")
                        return None
        except Exception as e:
            logger.warning(f"Error calling Image API: {e}")
            return None


class ContentAIEngine:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or get_settings().openai_api_key
        self.image_generator = DefaultImageGenerator(self.api_key)

    async def generate_variants(
        self,
        topic: str,
        main_point: str,
        facts: str = "",
        cta: str = "Полный гайд доступен в нашем Telegram-боте!",
        target_story: str = "",
    ) -> AIGenerationResult:
        if self.api_key:
            try:
                return await self._generate_with_llm(topic, main_point, facts, cta, target_story)
            except Exception as e:
                logger.error(f"LLM generation failed: {e}. Falling back to template generation.")

        return self._generate_template_fallback(topic, main_point, facts, cta, target_story)

    async def _generate_with_llm(
        self,
        topic: str,
        main_point: str,
        facts: str,
        cta: str,
        target_story: str,
    ) -> AIGenerationResult:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        user_prompt = build_user_prompt(topic, main_point, facts, cta, target_story)
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": BRAND_VOICE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.7,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=40)) as resp:
                if resp.status != 200:
                    err = await resp.text()
                    raise RuntimeError(f"OpenAI API error ({resp.status}): {err}")
                data = await resp.json()
                content = data["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                return self._parse_json_result(parsed, topic, target_story)

    def _parse_json_result(self, parsed: dict, topic: str, target_story: str) -> AIGenerationResult:
        img_prompt = parsed.get("image_prompt") or f"Romantic scene, Romance Club story '{target_story or topic}', cinematic lighting, digital art, 8k --ar 4:5"
        variants = {
            SocialPlatform.TELEGRAM: GeneratedVariant(
                platform=SocialPlatform.TELEGRAM,
                text=parsed.get("telegram") or f"📖 <b>{topic}</b>\n\n{parsed.get('vk', '')}",
                image_prompt=img_prompt,
            ),
            SocialPlatform.VK: GeneratedVariant(
                platform=SocialPlatform.VK,
                text=parsed.get("vk") or f"🔥 {topic}\n\n{parsed.get('telegram', '')}",
                image_prompt=img_prompt,
            ),
            SocialPlatform.INSTAGRAM: GeneratedVariant(
                platform=SocialPlatform.INSTAGRAM,
                text=parsed.get("instagram") or f"✨ {topic}\n\n{parsed.get('threads', '')}\n\n#клубромантики #romanceclub",
                image_prompt=img_prompt,
            ),
            SocialPlatform.THREADS: GeneratedVariant(
                platform=SocialPlatform.THREADS,
                text=parsed.get("threads") or f"А вы уже прошли {topic}? Делитесь впечатлениями в комментариях!",
                image_prompt=img_prompt,
            ),
        }
        return AIGenerationResult(variants=variants, image_prompt=img_prompt)

    def _generate_template_fallback(
        self,
        topic: str,
        main_point: str,
        facts: str,
        cta: str,
        target_story: str,
    ) -> AIGenerationResult:
        story_prefix = f" по новелле «{target_story}»" if target_story else ""
        facts_block = f"\n\n📌 <b>Важные детали:</b>\n{facts}" if facts else ""
        cta_text = cta or "Полный гайд доступен в нашем боте!"

        tg_text = (
            f"💎 <b>{topic}</b>{story_prefix}\n\n"
            f"{main_point}{facts_block}\n\n"
            f"💡 <i>{cta_text}</i>\n"
            f"👉 <a href=\"https://t.me/bot\">Открыть интерактивный гайд</a>"
        )

        vk_text = (
            f"🔥 {topic.upper()}{story_prefix.upper()} 🔥\n\n"
            f"{main_point}\n"
            f"{facts}\n\n"
            f"Качайте статы правильно и делитесь своими впечатлениями в комментариях!\n"
            f"👉 {cta_text}"
        )

        ig_text = (
            f"Как пройти {topic} без лишних трат? 💎👇\n\n"
            f"{main_point}\n\n"
            f"{cta_text}\n"
            f"Ссылка на подробный гайд в шапке профиля!\n\n"
            f"#клубромантики #romanceclub #кргайды #новеллы #клубромантикигайды"
        )

        threads_text = (
            f"Наболевший вопрос про {topic}:\n"
            f"{main_point}\n\n"
            f"А вы сколько алмазов слили на эту ветку? Делитесь в реплаях 👇"
        )

        img_prompt = (
            f"Romantic fantasy art inspired by Romance Club, atmospheric scene for '{topic}', "
            f"cinematic dramatic lighting, soft color grading, high detail, 8k, digital romance painting --ar 4:5"
        )

        return AIGenerationResult(
            variants={
                SocialPlatform.TELEGRAM: GeneratedVariant(SocialPlatform.TELEGRAM, tg_text, img_prompt),
                SocialPlatform.VK: GeneratedVariant(SocialPlatform.VK, vk_text, img_prompt),
                SocialPlatform.INSTAGRAM: GeneratedVariant(SocialPlatform.INSTAGRAM, ig_text, img_prompt),
                SocialPlatform.THREADS: GeneratedVariant(SocialPlatform.THREADS, threads_text, img_prompt),
            },
            image_prompt=img_prompt,
        )
