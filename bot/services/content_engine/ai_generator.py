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

    @classmethod
    def _to_visual_english_prompt(cls, prompt: str) -> str:
        """
        Translates and enriches Romance Club prompts into structured, highly aesthetic English
        for diffusion models to prevent dark/blurry outputs.
        """
        p_low = prompt.lower()

        # 1. Heroine archetype & styling
        heroine_style = "breathtaking gorgeous young heroine with long wavy hair and captivating eyes"
        if any(w in p_low for w in ["дворянк", "версаль", "корсет", "платье"]):
            heroine_style = "breathtaking noble young lady in elegant embroidered Victorian corset dress and pearls"
        elif any(w in p_low for w in ["чернокниж", "нил", "египет"]):
            heroine_style = "enchanting mysterious dark-haired sorceress in ornate Egyptian silk robes and gold jewelry"
        elif any(w in p_low for w in ["воительниц", "меч", "доспех", "солнцем"]):
            heroine_style = "brave beautiful warrior heroine in fantasy adventurer attire"
        elif any(w in p_low for w in ["кимоно", "ивы", "япони"]):
            heroine_style = "exquisite geisha heroine in luxurious silk kimono with ornate floral hair ornaments"
        elif any(w in p_low for w in ["инди", "сари", "кали"]):
            heroine_style = "stunning noble Indian beauty in royal embroidered silk saree and glowing gold jewelry"
        elif any(w in p_low for w in ["киберпанк", "пси", "куртк"]):
            heroine_style = "stylish cyberpunk heroine in sleek futuristic jacket with glowing neon accents"

        # 2. Scenery & backdrop
        setting = "fairy tale twilight castle courtyard"
        if "нил" in p_low or "египет" in p_low:
            setting = "ancient Egyptian temple with golden columns and torchlight"
        elif "версаль" in p_low:
            setting = "opulent Versailles palace hall with chandeliers and grand mirrors"
        elif "ивы" in p_low:
            setting = "tranquil Japanese pagoda garden with blooming pink cherry blossoms"
        elif "кали" in p_low:
            setting = "majestic ancient Indian temple with incense smoke and lotus pond"
        elif "пси" in p_low:
            setting = "rain-slicked futuristic neon cityscape with holographic billboards"
        elif "лес" in p_low or "морок" in p_low:
            setting = "mystical twilight birch forest with soft ethereal fog"

        # 3. Main action / Composition
        action = "gazing at magical glowing crossroads, luminous sparkling crystals floating in air"
        if any(w in p_low for w in ["ветк", "фаворит", "любов", "романтик"]):
            action = "intimate romantic scene standing close with handsome charismatic male suitor, tender passionate eye contact, glowing fairy lights"
        elif "алмаз" in p_low:
            action = "holding sparkling luminous diamond crystals, glittering magical gemstones floating around"
        elif any(w in p_low for w in ["стат", "баланс"]):
            action = "holding two swirling spheres of magical light in opposing colors, balance of elemental powers"

        full_en = (
            f"vertical visual novel digital art illustration, Romance Club aesthetic, "
            f"{heroine_style}, {action}, {setting} in background, "
            f"vibrant romantic colors, intricate details, cinematic volumetric lighting, "
            f"ArtStation trending, breathtaking romantic CG masterpiece, 8k resolution"
        )
        return full_en

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

        # 2. Convert to high-aesthetic Romance Club English prompt
        visual_prompt = self._to_visual_english_prompt(clean_prompt)

        # 3. Clean Pollinations AI URL (full prompt without truncation, no payment parameters)
        try:
            import urllib.parse
            encoded = urllib.parse.quote(visual_prompt)
            pollinations_url = f"https://image.pollinations.ai/prompt/{encoded}"
            return pollinations_url
        except Exception as e:
            logger.error(f"Image URL creation failed: {e}")
            import random
            return random.choice(self.FALLBACK_IMAGES)


class HuggingFaceFluxImageGenerator(ImageGenerator):
    """
    State-of-the-art image generator using FLUX.1-schnell via Hugging Face Inference API.
    Converts prompts to detailed visual novel instructions and uploads the resulting
    image to a high-speed CDN (freeimage.host) for instant public preview and multi-platform publishing.
    """
    HF_ROUTER_URL = "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell"
    HF_FALLBACK_URL = "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-schnell"
    FREEIMAGE_API_KEY = "6d207e02198a847aa98d0a2a901485a5"

    def __init__(self, hf_token: str | None = None) -> None:
        self.hf_token = (hf_token or "").strip()

    @staticmethod
    def _build_flux_prompt(prompt: str) -> str:
        clean = re.sub(r"--ar\s+\d+:\d+", "", prompt).strip()
        style_keywords = (
            "vertical 4:5 visual novel digital art illustration, Romance Club aesthetic, "
            "vibrant romantic colors, gorgeous heroine, intricate details, cinematic romantic fantasy lighting, "
            "ArtStation trending, 8k masterpiece"
        )
        return f"{clean}, {style_keywords}"

    async def generate(self, prompt: str, aspect_ratio: str = "4:5") -> str | None:
        if not self.hf_token:
            return None

        flux_prompt = self._build_flux_prompt(prompt)
        headers = {
            "Authorization": f"Bearer {self.hf_token}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        }
        payload = {
            "inputs": flux_prompt[:1000],
            "parameters": {
                "num_inference_steps": 4,
                "width": 768,
                "height": 1024,
            },
        }

        endpoints = [self.HF_ROUTER_URL, self.HF_FALLBACK_URL]
        img_bytes: bytes | None = None

        async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
            for url in endpoints:
                try:
                    async with session.post(
                        url,
                        headers=headers,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=50),
                    ) as resp:
                        if resp.status == 200:
                            content_type = resp.headers.get("Content-Type", "")
                            if "image" in content_type:
                                img_bytes = await resp.read()
                                break
                            data = await resp.json()
                            if isinstance(data, list) and len(data) > 0 and "image" in data[0]:
                                import base64
                                img_bytes = base64.b64decode(data[0]["image"])
                                break
                        else:
                            err_text = await resp.text()
                            logger.warning(f"HF FLUX inference returned {resp.status} at {url}: {err_text[:200]}")
                except Exception as e:
                    logger.warning(f"HF inference error at {url}: {e}")

            if not img_bytes:
                return None

            # Upload to high-speed CDN
            try:
                import base64
                b64_source = base64.b64encode(img_bytes).decode("utf-8")
                upload_data = {
                    "key": self.FREEIMAGE_API_KEY,
                    "action": "upload",
                    "source": b64_source,
                    "format": "json",
                }
                async with session.post(
                    "https://freeimage.host/api/1/upload",
                    data=upload_data,
                    timeout=aiohttp.ClientTimeout(total=25),
                ) as up_resp:
                    if up_resp.status == 200:
                        up_json = await up_resp.json()
                        cdn_url = up_json.get("image", {}).get("url")
                        if cdn_url:
                            logger.info(f"FLUX.1 image generated and uploaded to CDN: {cdn_url}")
                            return cdn_url
            except Exception as e:
                logger.warning(f"Failed to upload FLUX image to CDN: {e}")

        return None


class TogetherFluxImageGenerator(ImageGenerator):
    """
    High-speed, high-quality image generator using FLUX.1-schnell on Together AI.
    Converts prompts to Romance Club visual aesthetic and uploads the result to CDN
    (or uses direct Together URL) for public multi-platform publishing.
    """
    TOGETHER_API_URL = "https://api.together.xyz/v1/images/generations"
    FREEIMAGE_API_KEY = "6d207e02198a847aa98d0a2a901485a5"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = (api_key or "").strip()

    @staticmethod
    def _build_flux_prompt(prompt: str) -> str:
        clean = re.sub(r"--ar\s+\d+:\d+", "", prompt).strip()
        style_keywords = (
            "vertical 4:5 visual novel digital art illustration, Romance Club aesthetic, "
            "vibrant romantic colors, gorgeous heroine, intricate details, cinematic romantic fantasy lighting, "
            "ArtStation trending, 8k masterpiece"
        )
        return f"{clean}, {style_keywords}"

    async def generate(self, prompt: str, aspect_ratio: str = "4:5") -> str | None:
        if not self.api_key:
            return None

        flux_prompt = self._build_flux_prompt(prompt)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
        }
        payload = {
            "model": "black-forest-labs/FLUX.1-schnell",
            "prompt": flux_prompt[:1000],
            "width": 768,
            "height": 1024,
            "steps": 4,
            "n": 1,
            "response_format": "b64_json",
        }

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    self.TOGETHER_API_URL,
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=40),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        item = data.get("data", [{}])[0]
                        b64_str = item.get("b64_json")
                        direct_url = item.get("url")

                        if direct_url and direct_url.startswith("http"):
                            return direct_url

                        if b64_str:
                            upload_data = {
                                "key": self.FREEIMAGE_API_KEY,
                                "action": "upload",
                                "source": b64_str,
                                "format": "json",
                            }
                            async with session.post(
                                "https://freeimage.host/api/1/upload",
                                data=upload_data,
                                timeout=aiohttp.ClientTimeout(total=25),
                            ) as up_resp:
                                if up_resp.status == 200:
                                    up_json = await up_resp.json()
                                    cdn_url = up_json.get("image", {}).get("url")
                                    if cdn_url:
                                        logger.info(f"Together FLUX.1 image uploaded to CDN: {cdn_url}")
                                        return cdn_url
                    else:
                        err_text = await resp.text()
                        logger.warning(f"Together AI image generation failed ({resp.status}): {err_text[:250]}")
            except Exception as e:
                logger.warning(f"Error calling Together AI image API: {e}")

        return None


class ContentAIEngine:
    def __init__(
        self,
        api_key: str | None = None,
        hf_token: str | None = None,
        together_api_key: str | None = None,
    ) -> None:
        settings = get_settings()
        self.api_key = api_key or settings.openai_api_key
        self.hf_token = hf_token or settings.hf_token
        self.together_api_key = together_api_key or settings.together_api_key

        self.default_generator = DefaultImageGenerator(self.api_key)
        self.together_generator = TogetherFluxImageGenerator(self.together_api_key) if self.together_api_key else None
        self.hf_generator = HuggingFaceFluxImageGenerator(self.hf_token) if self.hf_token else None

    async def generate_image(self, prompt: str) -> str | None:
        if self.together_generator:
            try:
                url = await self.together_generator.generate(prompt)
                if url:
                    return url
            except Exception as e:
                logger.warning(f"Together AI FLUX generation failed: {e}. Falling back.")
        if self.hf_generator:
            try:
                url = await self.hf_generator.generate(prompt)
                if url:
                    return url
            except Exception as e:
                logger.warning(f"HuggingFace FLUX image generation failed: {e}. Falling back to default.")
        return await self.default_generator.generate(prompt)

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
            img_url = await self.generate_image(res.image_prompt)
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
