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
    Intelligent image generator for Romance Club social media posts.
    Uses OpenAI DALL-E 3 if OPENAI_API_KEY is configured,
    or falls back to high-resolution FLUX.1 generation via Pollinations AI.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key

    async def generate(self, prompt: str, aspect_ratio: str = "4:5") -> str | None:
        clean_prompt = prompt.replace("--ar 4:5", "").replace("--ar 1:1", "").strip()

        # 1. Try OpenAI DALL-E 3 if API key is provided
        if self.api_key:
            try:
                url = "https://api.openai.com/v1/images/generations"
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                }
                payload = {
                    "model": "dall-e-3",
                    "prompt": clean_prompt[:950],
                    "n": 1,
                    "size": "1024x1024",
                }
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=45)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            return data["data"][0]["url"]
                        else:
                            err_text = await resp.text()
                            logger.warning(f"OpenAI Image API failed ({resp.status}): {err_text}. Falling back to FLUX.")
            except Exception as e:
                logger.warning(f"Error calling OpenAI Image API: {e}. Falling back to FLUX.")

        # 2. Public FLUX.1 endpoint (Pollinations AI) - produces direct instant image URL
        try:
            import random
            import urllib.parse
            encoded_prompt = urllib.parse.quote(clean_prompt[:350])
            seed = random.randint(10000, 999999)
            flux_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1080&height=1350&model=flux&nologo=true&seed={seed}"
            return flux_url
        except Exception as e:
            logger.error(f"FLUX image URL creation failed: {e}")
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
        res: AIGenerationResult
        if self.api_key:
            try:
                res = await self._generate_with_llm(topic, main_point, facts, cta, target_story)
            except Exception as e:
                logger.error(f"LLM generation failed: {e}. Falling back to template generation.")
                res = self._generate_template_fallback(topic, main_point, facts, cta, target_story)
        else:
            res = self._generate_template_fallback(topic, main_point, facts, cta, target_story)

        # Automatically generate 1 matching image for all platforms
        try:
            img_url = await self.image_generator.generate(res.image_prompt)
            res.image_url = img_url
            for var in res.variants.values():
                var.image_url = img_url
        except Exception as e:
            logger.warning(f"Failed to generate auto image: {e}")

        return res

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

    @staticmethod
    def _clean_input(text: str) -> str:
        if not text or text.strip() == "-":
            return ""
        # Remove literal technical prefixes if user or raw prompt included them
        lines = []
        for line in text.strip().splitlines():
            cleaned_line = re.sub(r"^(факты|facts|cta|ста|тема|мысль|основная мысль)[:\s-]*", "", line.strip(), flags=re.IGNORECASE).strip()
            if cleaned_line:
                lines.append(cleaned_line)
        return "\n".join(lines).strip()

    def _generate_template_fallback(
        self,
        topic: str,
        main_point: str,
        facts: str,
        cta: str,
        target_story: str,
    ) -> AIGenerationResult:
        clean_topic = self._clean_input(topic) or topic
        clean_main = self._clean_input(main_point) or "Разбираем ключевые развилки, скрытые последствия и лучшие выборы для идеального финала."
        clean_facts = self._clean_input(facts)
        clean_cta = self._clean_input(cta) or "Полный интерактивный гайд доступен в нашем Telegram-боте!"

        story_prefix = f" | «{target_story}»" if target_story and target_story not in clean_topic else ""
        facts_block = f"📌 <b>Главные нюансы:</b>\n{clean_facts}\n\n" if clean_facts else ""
        vk_facts_block = f"{clean_facts}\n\n" if clean_facts else ""

        tg_text = (
            f"💎 <b>{clean_topic}</b>{story_prefix}\n\n"
            f"{clean_main}\n\n"
            f"{facts_block}"
            f"💡 <i>{clean_cta}</i>\n"
            f"👉 <b>Интерактивный путеводитель ждёт вас в боте!</b>"
        )

        vk_text = (
            f"🔥 {clean_topic.upper()}{story_prefix.upper()} 🔥\n\n"
            f"{clean_main}\n\n"
            f"{vk_facts_block}"
            f"💬 Делитесь своим мнением и любимыми ветками в комментариях!\n"
            f"👉 {clean_cta}"
        )

        ig_text = (
            f"✨ {clean_topic} 💎👇\n\n"
            f"{clean_main}\n\n"
            f"{vk_facts_block}"
            f"📌 {clean_cta}\n"
            f"Ссылка на интерактивный гайд — в шапке профиля! ⬆️\n\n"
            f"#клубромантики #romanceclub #кргайды #новеллы #клубромантикигайды"
        )

        threads_text = (
            f"Наболевший вопрос про {clean_topic}:\n\n"
            f"{clean_main}\n\n"
            f"А как поступили вы? Делитесь впечатлениями в реплаях 👇"
        )

        img_prompt = (
            f"Romantic fantasy art inspired by Romance Club '{target_story or clean_topic}', "
            f"atmospheric dramatic scene for '{clean_topic}', cinematic lighting, digital romance painting, 8k --ar 4:5"
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
