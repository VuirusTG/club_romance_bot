"""
Art Prompt Generator for Romance Club social media posts.
Constructs rich, cinematic, story-adapted 4:5 vertical illustration prompts
specifically tailored for visual novel fan posts across VK, Telegram, and Instagram.
"""

import re
from bot.services.content_engine.story_lore import get_story_lore, is_generic_heroine


class ArtPromptGenerator:
    """Generates rich, highly tailored image generation prompts in Russian for visual novel social posts."""

    GENRE_PALETTES = {
        "royal": "royal gold, velvet crimson and deep sapphire palette, warm candlelit cinematic lighting",
        "egypt": "warm desert gold, turquoise, smoldering amber and lapis lazuli palette, dramatic sunbeam lighting",
        "cyberpunk": "neon cyan, electric violet, chrome and dark rain-slicked noir palette, moody volumetric lighting",
        "slavic": "deep forest emerald, mist-gray, twilight gold and ember palette, eerie ethereal lighting",
        "gothic": "deep gothic crimson, midnight navy, silver moonlight and velvet shadow palette",
        "fantasy": "purple, blue and pink palette, glowing neon accents, cinematic magical lighting",
        "modern": "stylish pastel neon, magenta, stage spotlights and glossy modern aesthetic",
        "default": "purple, blue and pink palette, cinematic romantic lighting",
    }

    @classmethod
    def _detect_palette(cls, story_title: str, genre: str) -> str:
        title_low = story_title.lower()
        genre_low = genre.lower()

        if any(w in title_low or w in genre_low for w in ["версаль", "треспия", "дворцов", "корол"]):
            return cls.GENRE_PALETTES["royal"]
        if any(w in title_low or w in genre_low for w in ["нил", "египет", "фараон"]):
            return cls.GENRE_PALETTES["egypt"]
        if any(w in title_low or w in genre_low for w in ["пси", "киберпанк", "антиутопия"]):
            return cls.GENRE_PALETTES["cyberpunk"]
        if any(w in title_low or w in genre_low for w in ["морок", "славянск", "ведьм"]):
            return cls.GENRE_PALETTES["slavic"]
        if any(w in title_low or w in genre_low for w in ["дракул", "арканум", "сентфор", "хоррор", "вампир"]):
            return cls.GENRE_PALETTES["gothic"]
        if any(w in title_low or w in genre_low for w in ["сад", "братьев", "студент", "k-pop"]):
            return cls.GENRE_PALETTES["modern"]
        if any(w in title_low or w in genre_low for w in ["фэнтези", "небес", "тиамат", "ивы", "астре"]):
            return cls.GENRE_PALETTES["fantasy"]
        return cls.GENRE_PALETTES["default"]

    @classmethod
    def _get_heroine_description(cls, story_title: str, lore_heroine: str) -> str:
        t_low = story_title.lower()
        from bot.services.content_engine.story_lore import CANONICAL_HEROINES
        canonical = CANONICAL_HEROINES.get(story_title)
        clean_name = canonical or (lore_heroine.split("—")[0].split("(")[0].strip() if lore_heroine else "")
        if is_generic_heroine(clean_name):
            clean_name = ""

        name_part = f" в образе героини {clean_name}" if clean_name else ""

        if "версаль" in t_low:
            return f"Молодая утончённая дворянка{name_part} с длинными тёмными волнистыми волосами в роскошном историческом корсетном платье"
        elif "нил" in t_low:
            return f"Молодая загадочная чернокнижница{name_part} с пышными тёмными волосами и выразительными глазами в восточном одеянии"
        elif "солнцем" in t_low:
            return f"Молодая смелая девушка-воительница{name_part} с длинными развевающимися волосами в стильном фэнтезийном одеянии"
        elif "ивы" in t_low:
            return f"Утончённая восточная красавица{name_part} в традиционном шёлковом кимоно с изящной причёской"
        elif "кали" in t_low:
            return f"Прекрасная благородная девушка{name_part} с проницательным взглядом в традиционном расшитом индийском сари и золотых украшениях"
        elif "реквием" in t_low or "небес" in t_low:
            return f"Молодая привлекательная девушка{name_part} с выразительными глазами и длинными тёмными волнистыми волосами в атмосферном плаще"
        elif "пси" in t_low:
            return f"Стильная молодая девушка-псионик{name_part} с дерзким взглядом в кожаной куртке футуристичного кроя"
        elif "бездушн" in t_low:
            return f"Ослепительная соблазнительная красавица{name_part} с чарующим взглядом в элегантном вечернем образе"
        else:
            return f"Молодая привлекательная девушка{name_part} с длинными тёмными волнистыми волосами и выразительным взглядом в эстетичном наряде"

    @classmethod
    def _get_setting_backdrop(cls, story_title: str, lore_setting: str) -> str:
        t_low = story_title.lower()
        if "версаль" in t_low:
            return "блистательная зеркальная галерея Версаля с хрустальными люстрами и королевский парк в сумерках"
        elif "нил" in t_low:
            return "древнеегипетский храм с величественными колоннами, золотые пески Фив и южное звёздное небо"
        elif "солнцем" in t_low:
            return "величественная фэнтезийная цитадель на фоне заката и древние башни"
        elif "ивы" in t_low:
            return "туманный японский сад с цветущей сакурой, бамбуком и старинной пагодой в сумерках"
        elif "кали" in t_low:
            return "резной дворец в Калькутте, мерцающие лампады, лепестки жасмина и душная звёздная ночь"
        elif "реквием" in t_low:
            return "заснеженные руины базы в суровых сибирских горах и холодное северное сияние"
        elif "небес" in t_low:
            return "парящие в облаках острова небесной академии и закатные лучи солнца"
        elif "пси" in t_low:
            return "дождливый неоновый мегаполис будущего, высотки инквизиции и свет мокрых витрин"
        elif "морок" in t_low:
            return "дремучий славянский лес в густом тумане, деревянный частокол и языческое капище"
        elif "дракул" in t_low:
            return "готический замок в Карпатах под серебристым лунным светом и туманные ущелья"
        elif lore_setting:
            clean_s = lore_setting.split(",")[0].strip()
            return f"{clean_s} в атмосферных сумерках"
        return "сказочный замок в сумерках"

    @classmethod
    def build_art_prompt(
        cls,
        story_title: str = "",
        topic: str = "",
        category: str = "",
        character_name: str = "",
        main_point: str = "",
    ) -> str:
        """
        Creates a rich, cinematic, story-adapted 4:5 illustration prompt in Russian.
        Follows the standard:
        1. Context & Format: Vertical illustration 4:5 for Romance Club post.
        2. Heroine / Main character & expression.
        3. Visual theme metaphor (Choice roads, romantic spark, stat balance, sparkling diamonds).
        4. Setting background.
        5. Atmosphere & Mood.
        6. Digital art style & customized palette.
        7. Top space reservation for post headline text.
        8. Anti-copyright and originality guarantee.
        """
        st_clean = story_title.strip() if story_title else ""
        lore = get_story_lore(st_clean) if st_clean else None
        genre = lore.genre if lore else ""
        setting = lore.setting if lore else ""
        heroine_lore = lore.heroine if lore else ""

        full_context = f"{topic} {category} {main_point}".lower()
        cat_low = (category or "").lower()

        if "diamond" in cat_low or "алмаз" in cat_low or any(w in full_context for w in ["алмаз", "лихорадк", "трат", "эконом", "покупк"]):
            mode = "diamonds"
        elif "stat" in cat_low or "стат" in cat_low or "баланс" in cat_low or any(w in full_context for w in ["стат", "баланс", "путь разум", "путь чувств", "накоплен"]):
            mode = "stats"
        elif "fav" in cat_low or "ветк" in cat_low or bool(character_name) or any(w in full_context for w in ["ветк", "фаворит", "любов", "романтич"]):
            mode = "favorite"
        elif "dil" in cat_low or "дилемм" in cat_low or any(w in full_context for w in ["дилемм", "развилк", "правильный выбор", "ошибк", "поступить"]):
            mode = "dilemma"
        else:
            mode = "overview"

        story_mention = f" о новелле «{st_clean}»" if st_clean else ""
        story_tag = f" («Клуб Романтики»)" if st_clean else " о «Клубе Романтики»"

        heroine_desc = cls._get_heroine_description(st_clean, heroine_lore)
        backdrop = cls._get_setting_backdrop(st_clean, setting)
        palette = cls._detect_palette(st_clean, genre)

        if mode == "dilemma":
            char_action = (
                f"{heroine_desc} смотрит на развилку судьбы с обеспокоенным и сосредоточенным выражением лица."
            )
            central_elements = (
                "Перед ней визуально расходятся три сияющие магические дороги: одна ведёт к сияющему сердцу страсти, "
                "вторая к тёмной мистической трещине сомнений, третья к золотой королевской короне власти. "
                "Вокруг летают голубые кристаллы, мерцающие искры и светящиеся символы сюжетного выбора."
            )
            header_text = "ТЫ ТОЧНО СДЕЛАЛ ПРАВИЛЬНЫЙ ВЫБОР?"
            mood = "Атмосфера интриги, напряжения, глубокого выбора и романтики."

        elif mode == "favorite":
            fav_display = character_name.strip() if character_name else "харизматичным фаворитом"
            char_action = (
                f"Романтическая сцена: {heroine_desc} и статный привлекательный персонаж ({fav_display}) "
                f"стоят в полушаге друг от друга, их взгляды полны нежности, страсти и скрытого эмоционального напряжения."
            )
            central_elements = (
                "Вокруг них витают мягкие светящиеся романтические искры, парящие лепестки цветов и нежные световые кристаллы чувств, "
                "подчёркивающие искреннюю эмоциональную близость и трепет кульминационного момента."
            )
            header_text = f"СЕКРЕТЫ ИДЕАЛЬНОЙ ВЕТКИ С {fav_display.upper()}" if character_name else "КАК НЕ ПОТЕРЯТЬ ВЕТКУ С ФАВОРИТОМ?"
            mood = "Атмосфера романтики, глубоких чувств, трепета и магнетического притяжения."

        elif mode == "stats":
            char_action = (
                f"{heroine_desc} стоит в центре композиции с величественной уверенностью на лице, олицетворяя гармонию стихий."
            )
            central_elements = (
                "В её ладонях парят две светящиеся магические сферы контрастных цветов, символизирующие противоположные пути развития. "
                "Вокруг летают светящиеся руны равновесия, чаши весов судьбы, кристаллы энергии и тонкие потоки магии света и тени."
            )
            header_text = "КАК НЕ ЗАВАЛИТЬ БАЛАНС СТАТОВ?"
            mood = "Атмосфера гармонии, мистической силы, концентрации и судьбоносного баланса."

        elif mode == "diamonds":
            char_action = (
                f"{heroine_desc} в сияющем роскошном образе с лёгкой игривой улыбкой и блеском предвкушения в глазах."
            )
            central_elements = (
                "Вокруг в воздухе парят мерцающие огранённые кристаллы алмазов, переливающиеся яркими искрами, "
                "россыпи драгоценных самоцветов и золотые световые частицы сказочного богатства."
            )
            header_text = "СТОИТ ЛИ ТРАТИТЬ АЛМАЗЫ?"
            mood = "Атмосфера роскоши, праздника, тайных сокровищ и соблазна."

        else:
            # Overview / Why play
            char_action = (
                f"Эпический кинематографичный кадр: {heroine_desc} решительно устремила взгляд вперёд, "
                f"готовая к раскрытию тайн и судьбоносным приключениям."
            )
            central_elements = (
                "Вокруг летают парящие световые частицы, лёгкий мистический туман, сияющие кристаллы и искры, "
                "создающие ощущение ожившей легенды и захватывающей интерактивной новеллы."
            )
            header_text = "ПОЧЕМУ ЭТУ ИСТОРИЮ ОБЯЗАН ПРОЙТИ КАЖДЫЙ?"
            mood = "Атмосфера захватывающего приключения, загадки, красоты и романтики."

        prompt_parts = [
            f"Вертикальная иллюстрация 4:5 для поста в соцсетях{story_mention}{story_tag}.",
            char_action,
            central_elements,
            f"На заднем плане {backdrop}.",
            mood,
            f"Профессиональный fantasy digital art, cinematic lighting, {palette}.",
            f"Место сверху для крупного текста «{header_text}».",
            "Без официальных персонажей и копирования материалов игры. --ar 4:5",
        ]

        return " ".join(prompt_parts)
