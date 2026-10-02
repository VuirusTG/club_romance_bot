from abc import ABC, abstractmethod
import json
import logging
import re
import aiohttp

from bot.config import get_settings
from bot.services.content_engine.art_prompt_generator import ArtPromptGenerator
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
    or falls back to high-resolution visual novel generation via Pollinations AI.
    """

    FALLBACK_IMAGES = [
        "https://images.unsplash.com/photo-1518709268805-4e9042af9f23?q=80&w=1200&auto=format&fit=crop",
        "https://images.unsplash.com/photo-1534447677768-be436bb09401?q=80&w=1200&auto=format&fit=crop",
        "https://images.unsplash.com/photo-1509198397868-475647b2a1e5?q=80&w=1200&auto=format&fit=crop",
        "https://images.unsplash.com/photo-1516589178581-6cd7833ae3b2?q=80&w=1200&auto=format&fit=crop",
    ]

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
                            logger.warning(f"OpenAI Image API failed ({resp.status}): {err_text}. Falling back.")
            except Exception as e:
                logger.warning(f"Error calling OpenAI Image API: {e}. Falling back.")

        # 2. Enhanced visual novel prompt (remove decay / horror keywords, enforce bright romantic aesthetic)
        filtered_prompt = re.sub(
            r"\b(гниёт|гниль|гной|смерть|труп|гниение|rotting|decay|rotten|corpse|horror|ugly|gloomy|darkness|gore)\b",
            "mystery",
            clean_prompt,
            flags=re.IGNORECASE,
        )
        style_suffix = "breathtaking visual novel CG illustration, Romance Club aesthetic, vibrant colors, gorgeous characters, cinematic romantic lighting, ArtStation trending, 8k masterpiece"
        full_prompt = f"{filtered_prompt}, {style_suffix}".strip()

        # 3. Clean Pollinations AI URL (avoid width/height/seed/nologo parameters that trigger 402 Payment Required)
        try:
            import urllib.parse
            encoded = urllib.parse.quote(full_prompt[:250])
            pollinations_url = f"https://image.pollinations.ai/prompt/{encoded}"
            return pollinations_url
        except Exception as e:
            logger.error(f"Image URL creation failed: {e}")
            import random
            return random.choice(self.FALLBACK_IMAGES)


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
        img_prompt = parsed.get("image_prompt")
        if not img_prompt or len(img_prompt.strip()) < 30:
            img_prompt = ArtPromptGenerator.build_art_prompt(
                story_title=target_story,
                topic=topic,
            )
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
    def _clean_brackets(text: str) -> str:
        """Removes robotic parenthetical expressions and unwraps names/descriptions into seamless text."""
        if not text:
            return ""
        # e.g. "героини (София)" -> "героини София"
        text = re.sub(r"героини\s*\(([^\)]+)\)", r"героини \1", text, flags=re.IGNORECASE)
        # e.g. "фаворитом (Имя)" -> "фаворитом \1"
        text = re.sub(r"фаворитом\s*\(([^\)]+)\)", r"фаворитом \1", text, flags=re.IGNORECASE)
        # e.g. "персонажем (Имя)" -> "персонажем \1"
        text = re.sub(r"персонажем\s*\(([^\)]+)\)", r"персонажем \1", text, flags=re.IGNORECASE)
        # e.g. "ветку с (Имя)" -> "ветку с \1"
        text = re.sub(r"ветку\s+с\s*\(([^\)]+)\)", r"ветку с \1", text, flags=re.IGNORECASE)
        # e.g. "судьбу (Имя)" -> "судьбу \1"
        text = re.sub(r"судьбу\s*\(([^\)]+)\)", r"судьбу \1", text, flags=re.IGNORECASE)
        # Unwrap any capitalized name/word in brackets: "(София)" -> "София"
        text = re.sub(r"\(([A-ZА-ЯЁ][a-zа-яё]+)\)", r"\1", text)
        return text

    @classmethod
    def _clean_input(cls, text: str) -> str:
        if not text or text.strip() == "-":
            return ""
        # Remove literal technical prefixes if user or raw prompt included them
        lines = []
        for line in text.strip().splitlines():
            cleaned_line = re.sub(r"^(факты|facts|cta|ста|тема|мысль|основная мысль)[:\s-]*", "", line.strip(), flags=re.IGNORECASE).strip()
            if cleaned_line:
                lines.append(cls._clean_brackets(cleaned_line))
        return "\n".join(lines).strip()

    def _generate_template_fallback(
        self,
        topic: str,
        main_point: str,
        facts: str,
        cta: str,
        target_story: str,
    ) -> AIGenerationResult:
        raw_topic = self._clean_input(topic) or topic
        # Clean trailing genre or technical tags in parentheses
        clean_topic = re.sub(r"\s*\([^\)]*\)$", "", raw_topic).strip()
        clean_topic = self._clean_brackets(clean_topic)
        clean_main = self._clean_brackets(self._clean_input(main_point)) or "Разбираем ключевые развилки, скрытые последствия и лучшие выборы для идеального финала."
        clean_facts = self._clean_brackets(self._clean_input(facts))
        clean_cta = self._clean_brackets(self._clean_input(cta)) or "Полный интерактивный гайд доступен в нашем Telegram-боте!"

        # Avoid redundant "| «Story»" if story is already mentioned in topic
        story_in_topic = target_story and target_story.lower() in clean_topic.lower()
        story_badge = f" | «{target_story}»" if (target_story and not story_in_topic) else ""
        story_name = target_story or clean_topic

        # Structured blocks
        facts_block = f"📌 <b>Главные нюансы и развилки:</b>\n{clean_facts}\n\n" if clean_facts else ""
        vk_facts_block = f"{clean_facts}\n\n" if clean_facts else ""

        # 1. Telegram: engaging, aesthetic, informative with formatted bold/emojis
        tg_text = (
            f"✨ <b>{clean_topic}</b>{story_badge}\n\n"
            f"{clean_main}\n\n"
            f"{facts_block}"
            f"💡 <b>Совет редакции:</b> {clean_cta}\n\n"
            f"📱 <i>Все скрытые пути, проверки статов и цены в алмазах доступны в нашем Telegram-боте!</i>"
        )

        # 2. VK: friendly community tone, clear storytelling, active discussion CTA
        vk_text = (
            f"✨ {clean_topic}{story_badge}\n\n"
            f"{clean_main}\n\n"
            f"{vk_facts_block}"
            f"💬 Делитесь своим мнением и любимыми ветками в комментариях!\n"
            f"👉 {clean_cta}\n\n"
            f"#клубромантики #romanceclub #кргайды #новеллы"
        )

        # 3. Instagram: aesthetic hook, concise, mobile-friendly spacing
        ig_text = (
            f"✨ {clean_topic} 💎👇\n\n"
            f"{clean_main}\n\n"
            f"{vk_facts_block}"
            f"📌 Сохраняйте в закладки, чтобы не потерять статы!\n"
            f"👉 Ссылка на интерактивный гайд — в шапке профиля! ⬆️\n\n"
            f"#клубромантики #romanceclub #кргайды #визуальныеновеллы #кр"
        )

        # 4. Threads: natural human discussion starter that REVEALS the facts and answers the topic
        threads_facts_bullets = ""
        if clean_facts:
            lines = [l.strip() for l in clean_facts.splitlines() if l.strip()]
            if lines:
                threads_facts_bullets = "\n".join(lines[:4])

        lower_topic = clean_topic.lower()
        if "почему" in lower_topic or "стоит пройти" in lower_topic:
            facts_block = f"\n\nЧем цепляет эта новелла:\n{threads_facts_bullets}" if threads_facts_bullets else ""
            threads_hook = (
                f"Честно, если вы до сих пор откладывали «{story_name}» — самое время начать.\n\n"
                f"{clean_main}"
                f"{facts_block}\n\n"
                f"А кто уже проходит: как вам сюжет и кого выбрали своей веткой? Делитесь в комментариях 👇"
            )
        elif "ветк" in lower_topic or "фаворит" in lower_topic or "секрет" in lower_topic:
            facts_block = f"\n\nГлавные нюансы, чтобы не запороть ветку:\n{threads_facts_bullets}" if threads_facts_bullets else ""
            threads_hook = (
                f"Разбираем романтические ветки в «{story_name}» 💔\n\n"
                f"{clean_main}"
                f"{facts_block}\n\n"
                f"Признавайтесь: кто ваш главный фаворит в этой истории и были ли у вас ошибки с выборами? 👇"
            )
        elif "алмаз" in lower_topic or "дорог" in lower_topic or "трат" in lower_topic:
            facts_block = f"\n\nНа что обратить внимание перед покупкой:\n{threads_facts_bullets}" if threads_facts_bullets else ""
            threads_hook = (
                f"Вечная боль игроков в «{story_name}» — это дорогие выборы за алмазы 💎\n\n"
                f"{clean_main}"
                f"{facts_block}\n\n"
                f"А как проходите вы: скупаете все платные сцены или копите до Алмазной Лихорадки? 👇"
            )
        elif "стат" in lower_topic or "баланс" in lower_topic or "путь" in lower_topic:
            facts_block = f"\n\nПравила успешного баланса:\n{threads_facts_bullets}" if threads_facts_bullets else ""
            threads_hook = (
                f"Самое обидное в «{story_name}» — не добрать 1-2 стата в финале сезона ⚖️\n\n"
                f"{clean_main}"
                f"{facts_block}\n\n"
                f"По какому пути идёте вы и удаётся ли держать баланс? Рассказывайте в реплаях 👇"
            )
        elif "дилемм" in lower_topic or "выбор" in lower_topic or "развилк" in lower_topic:
            facts_block = f"\n\nРазбор развилок:\n{threads_facts_bullets}" if threads_facts_bullets else ""
            threads_hook = (
                f"Главная дилемма в «{story_name}», где ошибаются многие 🎭\n\n"
                f"{clean_main}"
                f"{facts_block}\n\n"
                f"А как поступили вы на этой развилке? Делитесь впечатлениями в реплаях 👇"
            )
        else:
            facts_block = f"\n\n{threads_facts_bullets}" if threads_facts_bullets else ""
            threads_hook = (
                f"Горячая тема по «{story_name}»:\n\n"
                f"{clean_topic}\n\n"
                f"{clean_main}"
                f"{facts_block}\n\n"
                f"А как поступили вы на этих развилках? Делитесь впечатлениями в реплаях 👇"
            )

        # Rich, cinematic 4:5 illustration prompt adapted specifically for the post
        img_prompt = ArtPromptGenerator.build_art_prompt(
            story_title=target_story,
            topic=clean_topic,
            main_point=clean_main,
        )

        return AIGenerationResult(
            variants={
                SocialPlatform.TELEGRAM: GeneratedVariant(SocialPlatform.TELEGRAM, tg_text, img_prompt),
                SocialPlatform.VK: GeneratedVariant(SocialPlatform.VK, vk_text, img_prompt),
                SocialPlatform.INSTAGRAM: GeneratedVariant(SocialPlatform.INSTAGRAM, ig_text, img_prompt),
                SocialPlatform.THREADS: GeneratedVariant(SocialPlatform.THREADS, threads_hook, img_prompt),
            },
            image_prompt=img_prompt,
        )
