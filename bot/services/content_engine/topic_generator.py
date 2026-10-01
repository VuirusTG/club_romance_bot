import random
import re
from dataclasses import dataclass
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.database.models import Story, Character, Episode, Choice
from bot.services.content_engine.story_lore import get_story_lore


@dataclass
class TopicIdea:
    id: str
    category: str
    title: str
    topic: str
    main_point: str
    facts: str
    cta: str
    target_story: str
    character_name: str | None = None
    image_concept: str = ""


# Fallback knowledge base for top stories and favorites when DB details are sparse
POPULAR_FAVORITES = {
    "Секрет Небес": ["Люцифер", "Мальбонте", "Дино", "Мими", "Энди"],
    "Секрет Небес 2": ["Люцифер", "Мальбонте", "Астарот", "Война", "Голод", "Дино"],
    "Песнь о Красном Ниле": ["Амен", "Ливий", "Сет", "Реммао", "Агния"],
    "Кали: Зов Тьмы": ["Рэйтан", "Амрит Дубей", "Киллан", "Лима"],
    "Кали: Пламя Сансары": ["Кристиан (Тиан)", "Рам Дубей", "Камал", "Доран Басу"],
    "Легенда Ивы": ["Кадзу", "Масамунэ", "Такао", "Сино-Одори"],
    "Тени Сентфора": ["Майкл", "Люк", "Дерек", "Человек в Маске", "Аарон"],
    "Рождённая Луной": ["Виктор Ван Арт", "Макс Фолл", "Бенни Барт"],
    "Я Охочусь на Тебя": ["Александр", "Сэм", "Эллиа", "Рэйчел"],
    "Пси": ["Иво Мартен", "Кей Стоун", "Йонас", "Даниэль"],
    "Покрой меня тьмой": ["Винсент", "Уолтер", "Эллиот"],
}

STAT_PATHS = {
    "Секрет Небес": ("Ангел", "Демон", "Мальбонте (Баланс)"),
    "Секрет Небес 2": ("Хладнокровие", "Темперамент", "Сила"),
    "Песнь о Красном Ниле": ("Честность", "Хитрость", "Признание"),
    "Кали: Зов Тьмы": ("Гнев Богини", "Милость Богини", "Лояльность / Независимость"),
    "Кали: Пламя Сансары": ("Гордость", "Страсть", "Достоинство"),
    "Легенда Ивы": ("Холод", "Страсть", "Жемчужная Лиса / Янтарная Лиса"),
    "Тени Сентфора": ("Смелость", "Осторожность", "Имидж"),
    "Рождённая Луной": ("Стойкость", "Дипломатия"),
    "Я Охочусь на Тебя": ("Логика", "Интуиция", "Авторитет"),
    "Пси": ("Импульс", "Форма", "Вектор"),
}


class AutoContentSuggester:
    """
    Intelligent topic and lore discovery engine that automatically mines
    stories, characters, and choices from the database to generate compelling social posts.
    """

    @staticmethod
    async def get_popular_stories(session: AsyncSession, limit: int = 12) -> list[Story]:
        query = select(Story).where(Story.is_published.is_(True)).order_by(Story.views_count.desc(), Story.id.desc()).limit(limit)
        res = await session.execute(query)
        stories = list(res.scalars().all())
        if not stories:
            query = select(Story).limit(limit)
            res = await session.execute(query)
            stories = list(res.scalars().all())
        return stories

    @classmethod
    async def suggest_topic_ideas(cls, session: AsyncSession, count: int = 4) -> list[TopicIdea]:
        """
        Generate a curated list of diverse content ideas across different categories:
        Romance branches, Diamond management, Stat paths, Dilemmas, and Story overviews.
        """
        stories = await cls.get_popular_stories(session, limit=20)
        if not stories:
            return cls._get_static_fallback_ideas(count)

        ideas: list[TopicIdea] = []
        categories = ["favorite", "diamonds", "stats", "dilemma", "overview"]
        random.shuffle(categories)

        for cat in categories[:count]:
            story = random.choice(stories)
            idea = await cls._generate_idea_for_category(session, story, cat)
            if idea:
                ideas.append(idea)

        # Fill remaining if needed
        while len(ideas) < count:
            story = random.choice(stories)
            idea = await cls._generate_idea_for_category(session, story, "favorite")
            if idea:
                ideas.append(idea)
            else:
                break

        return ideas[:count]

    @classmethod
    async def get_random_topic(cls, session: AsyncSession, category: str | None = None) -> TopicIdea:
        """Get a single rich topic idea immediately in 1 click."""
        stories = await cls.get_popular_stories(session, limit=20)
        story = random.choice(stories) if stories else None
        cat = category or random.choice(["favorite", "diamonds", "stats", "dilemma", "overview"])
        idea = await cls._generate_idea_for_category(session, story, cat) if story else None
        return idea or cls._get_static_fallback_ideas(1)[0]

    @classmethod
    async def expand_user_query(cls, session: AsyncSession, query_text: str) -> TopicIdea:
        """
        Smart parser: Takes any loose keyword, character name, or short phrase
        (e.g., 'Люцифер', 'СН', 'алмазы', 'Амен') and automatically constructs
        a complete, fully structured post package.
        """
        clean_query = query_text.strip()
        lower_query = clean_query.lower()

        # 1. Search for matching character
        char_query = select(Character).options(selectinload(Character.story)).where(
            func.lower(Character.name).contains(lower_query)
        ).limit(1)
        char_res = await session.execute(char_query)
        character = char_res.scalar_one_or_none()

        if character and character.story:
            story = character.story
            return cls._build_favorite_idea(story, character.name)

        # 2. Search for matching story
        story_query = select(Story).where(
            func.lower(Story.title).contains(lower_query)
        ).limit(1)
        story_res = await session.execute(story_query)
        story = story_res.scalar_one_or_none()

        if story:
            # Check if user mentioned stats or diamonds
            if any(w in lower_query for w in ["алмаз", "трат", "цен", "копит", "плат"]):
                return cls._build_diamond_idea(story)
            if any(w in lower_query for w in ["стат", "баланс", "путь", "финал"]):
                return cls._build_stats_idea(story)
            # Default to romance branch or overview
            return await cls._generate_idea_for_category(session, story, "favorite") or cls._build_overview_idea(story)

        # 3. Check popular lore dicts
        for story_title, favs in POPULAR_FAVORITES.items():
            for f in favs:
                if f.lower() in lower_query or lower_query in f.lower():
                    dummy_story = Story(id=0, title=story_title, genre="Фэнтези, Романтика")
                    return cls._build_favorite_idea(dummy_story, f)

        # 4. Keyword based fallback
        if any(w in lower_query for w in ["алмаз", "копить", "лихорадк", "экономи"]):
            dummy_story = Story(id=0, title="Клуб Романтики", genre="Интерактивные новеллы")
            return TopicIdea(
                id="custom_diamonds",
                category="diamonds",
                title="💎 Гайд: Как эффективно копить и тратить алмазы",
                topic=f"Секреты экономии алмазов: {clean_query}",
                main_point="Гайд для тех, кто хочет брать лучшие сцены с фаворитами и при этом не остаться с нулём алмазов перед новой обновой.",
                facts="• За просмотр рекламы каждые 1.5 часа можно собрать до 30+ алмазов в сутки.\n• Ежедневный вход в игру увеличивает награду вплоть до максимума.\n• Дорогие сюжетные выборы лучше откладывать на Алмазную Лихорадку, а ключевые статы брать сразу.\n• Все цены выборов и точные статы собраны в нашем интерактивном гайде.",
                cta="Откройте нашего бота, чтобы проходить любимые истории без лишних трат!",
                target_story="Клуб Романтики",
                image_concept="Glowing blue diamonds, romantic fantasy atmosphere, Romance Club UI style, cinematic lighting, 8k --ar 4:5",
            )

        # 5. General generic expansion
        return TopicIdea(
            id="custom_expanded",
            category="general",
            title=f"✨ {clean_query.capitalize()}",
            topic=clean_query,
            main_point=f"Подробный разбор и полезные советы по теме: {clean_query}. Всё самое важное для идеального прохождения.",
            facts="• Своевременный выбор правильных вариантов гарантирует высокий результат.\n• Прокачка отношений и баланс статов открывают эксклюзивные сцены.\n• Пошаговые интерактивные развилки по всем сериям доступны в нашем Telegram-боте.",
            cta="Полный интерактивный гайд доступен в нашем Telegram-боте!",
            target_story="",
            image_concept=f"Cinematic romantic illustration for Romance Club, theme: {clean_query}, atmospheric lighting, 8k, digital art --ar 4:5",
        )

    @classmethod
    async def _generate_idea_for_category(cls, session: AsyncSession, story: Story | None, category: str) -> TopicIdea | None:
        if not story:
            return None

        if category == "favorite":
            # Find love interests for story
            char_query = select(Character).where(
                Character.story_id == story.id,
                Character.is_love_interest.is_(True)
            ).limit(10)
            res = await session.execute(char_query)
            chars = list(res.scalars().all())
            char_name = random.choice(chars).name if chars else None

            if not char_name:
                known = POPULAR_FAVORITES.get(story.title, [])
                char_name = random.choice(known) if known else "любимым фаворитом"

            return cls._build_favorite_idea(story, char_name)

        elif category == "diamonds":
            return cls._build_diamond_idea(story)

        elif category == "stats":
            return cls._build_stats_idea(story)

        elif category == "dilemma":
            return cls._build_dilemma_idea(story)

        elif category == "overview":
            return cls._build_overview_idea(story)

        return cls._build_favorite_idea(story, "фаворитом")

    @classmethod
    def _build_favorite_idea(cls, story: Story, char_name: str) -> TopicIdea:
        lore = get_story_lore(story.title, story.genre or "")
        topic = f"Секреты идеальной ветки с {char_name} в «{story.title}»"
        main_point = (
            f"Как выйти на крепкую романтическую ветку с {char_name} в новелле «{story.title}». "
            f"Разбираем ключевые развилки, скрытые улучшения и как не допустить обидного разрыва отношений."
        )
        heroine_note = f" Судьба героини ({lore.heroine}) в ваших руках." if lore.heroine and lore.heroine != "Главная героиня" else ""
        facts = (
            f"• В новелле «{story.title}» каждый диалог с фаворитом может стать решающим.{heroine_note}\n"
            f"• Не совмещайте параллельные ветки в критических сериях, чтобы избежать ревности и блокировки финала.\n"
            f"• В кульминациях сезонов высокий уровень симпатии открывает уникальные эксклюзивные кат-сцены.\n"
            f"• Пошаговые цепочки выборов и тайминги для ветки с {char_name} всегда доступны в нашем интерактивном боте."
        )
        cta = f"Откройте нашего бота, чтобы построить идеальную ветку с {char_name} без сюжетных ошибок!"
        return TopicIdea(
            id=f"fav_{story.id}_{random.randint(100, 999)}",
            category="❤️ Ветка с фаворитом",
            title=f"❤️ Ветка: {char_name} ({story.title})",
            topic=topic,
            main_point=main_point,
            facts=facts,
            cta=cta,
            target_story=story.title,
            character_name=char_name,
            image_concept=f"Breathtaking romantic visual novel illustration, handsome {char_name} and gorgeous heroine from Romance Club '{story.title}', vibrant colors, emotional gaze, cinematic golden lighting, 8k masterpiece",
        )

    @classmethod
    def _build_diamond_idea(cls, story: Story) -> TopicIdea:
        lore = get_story_lore(story.title, story.genre or "")
        favs = ", ".join(lore.key_favorites[:3]) if lore.key_favorites else "фаворитами"
        topic = f"Топ самых дорогих выборов в «{story.title}»: стоят ли они того?"
        main_point = (
            f"Разбираемся, какие платные решения в новелле «{story.title}» действительно меняют сюжет "
            f"и дают статы, а на чём можно спокойно сэкономить без ущерба для финала."
        )
        facts = (
            f"• В истории «{story.title}» ключевые платные выборы спасают союзников и авторитет героини.\n"
            f"• Дорогие наряды и украшения часто приносят скрытые характеристики — проверяйте гайд перед покупкой!\n"
            f"• Сюжетные романтические сцены с ключевыми персонажами ({favs}) существенно углубляют любовные линии.\n"
            f"• Интерактивная база бота подсказывает точную стоимость в алмазах и эффект каждого выбора заранее."
        )
        cta = f"Сверяйтесь с гайдами в нашем боте и тратьте алмазы с максимальной пользой!"
        return TopicIdea(
            id=f"dia_{story.id}_{random.randint(100, 999)}",
            category="💎 Алмазы и экономия",
            title=f"💎 Разбор трат: «{story.title}»",
            topic=topic,
            main_point=main_point,
            facts=facts,
            cta=cta,
            target_story=story.title,
            image_concept=f"Radiant sparkling diamonds and glowing gems, elegant Romance Club '{story.title}' aesthetic, vibrant colors, royal atmosphere, 8k masterpiece",
        )

    @classmethod
    def _build_stats_idea(cls, story: Story) -> TopicIdea:
        lore = get_story_lore(story.title, story.genre or "")
        stats = lore.stat_paths if lore.stat_paths else STAT_PATHS.get(story.title, ("Путь Разума", "Путь Чувств", "Авторитет"))
        stats_str = " / ".join(stats[:2])
        topic = f"Путь {stats[0]} или {stats[1]}: как не завалить баланс в «{story.title}»"
        heroine_desc = f" ({lore.heroine})" if lore.heroine and lore.heroine != "Главная героиня" else ""
        main_point = (
            f"В новелле «{story.title}» правильное распределение характеристик решает судьбу героини{heroine_desc}. "
            f"Разбираем главные ошибки игроков при накоплении статов {stats_str}."
        )
        facts = (
            f"• Проверки статов на финалах сезонов не прощают нехватки даже 1-2 баллов.\n"
            f"• Сюжетный вызов истории: {lore.core_conflict}.\n"
            f"• Распыляться на оба пути рискованно, если механика новеллы требует строгой специализации.\n"
            f"• Все правильные реплики для накопления максимума характеристик отмечены в нашем интерактивном боте."
        )
        cta = f"Узнайте правильный путь для новеллы «{story.title}» в нашем Telegram-боте!"
        return TopicIdea(
            id=f"stat_{story.id}_{random.randint(100, 999)}",
            category="⚖️ Баланс и статы",
            title=f"⚖️ Статы: {stats_str} ({story.title})",
            topic=topic,
            main_point=main_point,
            facts=facts,
            cta=cta,
            target_story=story.title,
            image_concept=f"Gorgeous duality composition, balance of paths {stats_str}, elegant heroine from Romance Club '{story.title}', vibrant fantasy art, cinematic lighting, 8k",
        )

    @classmethod
    def _build_dilemma_idea(cls, story: Story) -> TopicIdea:
        lore = get_story_lore(story.title, story.genre or "")
        topic = f"Главная дилемма в «{story.title}»: правильный ли выбор вы сделали?"
        main_point = (
            f"В новелле «{story.title}» наступает момент, когда эмоции зашкаливают, а цена ошибки смертельно высока: {lore.dramatic_dilemma} "
            f"Разбираем последствия каждого решения."
        )
        facts = (
            f"• Ключевой конфликт новеллы: {lore.core_conflict}.\n"
            f"• Неочевидный выбор на первый взгляд кажется безопасным, но способен привести к тяжёлым потерям в будущих сериях.\n"
            f"• Подробный разбор скрытых последствий каждого варианта есть в схемах нашего бота.\n"
            f"• Интерактивные развилки спасут от необходимости перепроходить сезон заново из-за одной оплошности."
        )
        cta = "А какой выбор сделали вы? Делитесь в комментариях и сверяйтесь с гайдом в боте!"
        return TopicIdea(
            id=f"dil_{story.id}_{random.randint(100, 999)}",
            category="🎭 Сюжетная развилка",
            title=f"🎭 Сложный выбор: «{story.title}»",
            topic=topic,
            main_point=main_point,
            facts=facts,
            cta=cta,
            target_story=story.title,
            image_concept=f"Intense dramatic crossroads scene, emotional visual novel CG, Romance Club '{story.title}', vibrant colors, gorgeous aesthetic, 8k masterpiece",
        )

    @classmethod
    def _build_overview_idea(cls, story: Story) -> TopicIdea:
        lore = get_story_lore(story.title, story.genre or "")
        topic = f"Почему вам стоит пройти «{story.title}» прямо сейчас"
        heroine_part = f" Главная героиня — {lore.heroine}." if lore.heroine and lore.heroine != "Главная героиня" else ""
        main_point = f"{lore.compelling_pitch}{heroine_part}"
        favs_sample = ", ".join(lore.key_favorites[:3]) if lore.key_favorites else "яркие фавориты"
        facts = (
            f"• Сеттинг и атмосфера: {lore.setting}.\n"
            f"• Главный конфликт: {lore.core_conflict}.\n"
            f"• Романтические ветки: {favs_sample}.\n"
            f"• С интерактивным гайдом в нашем боте прохождение станет лёгким, понятным и максимально приятным!"
        )
        cta = f"Начните играть в «{story.title}» вместе с нашим ботом-помощником!"
        return TopicIdea(
            id=f"over_{story.id}_{random.randint(100, 999)}",
            category="📖 Обзор новеллы",
            title=f"📖 Обзор: «{story.title}»",
            topic=topic,
            main_point=main_point,
            facts=facts,
            cta=cta,
            target_story=story.title,
            image_concept=f"Breathtaking romantic visual novel key art, Romance Club '{story.title}', gorgeous heroine, vibrant cinematic atmosphere, fantasy illustration, 8k masterpiece",
        )


    @staticmethod
    def _get_static_fallback_ideas(count: int = 4) -> list[TopicIdea]:
        fallbacks = [
            TopicIdea(
                id="fallback_lucifer",
                category="❤️ Ветка с фаворитом",
                title="❤️ Ветка: Люцифер (Секрет Небес)",
                topic="Секреты идеальной ветки с Люцифером в СН",
                main_point="Как растопить сердце властного сына Сатаны, не потерять признание и выйти на счастливый финал.",
                facts="• В 1 сезоне важно забирать сцены тренировок и диалоги на крыше.\n• Не берите романтические сцены с Дино, чтобы не заблокировать ветку.\n• Пошаговое руководство доступно в нашем боте!",
                cta="Откройте нашего бота, чтобы увидеть полное прохождение ветки с Люцифером!",
                target_story="Секрет Небес",
                character_name="Люцифер",
                image_concept="Lucifer from Heaven's Secret, glowing red demon wings, handsome demonic gaze, cinematic lighting, 8k --ar 4:5",
            ),
            TopicIdea(
                id="fallback_amen",
                category="❤️ Ветка с фаворитом",
                title="❤️ Ветка: Амен (Песнь о Красном Ниле)",
                topic="Как спастись от гнева верховного эпистата Амена в ПОКН",
                main_point="Разбор опасных развилок и романтических взаимодействий с Аменом для чернокнижницы Эвы.",
                facts="• Держите баланс между скрытностью и сближением с охотниками.\n• Все скрытые реакции Амена подробно расписаны в гайде бота.",
                cta="Сверяйтесь с нашим Telegram-ботом, чтобы не попасться эпистату!",
                target_story="Песнь о Красном Ниле",
                character_name="Амен",
                image_concept="Amen epistat from Song of the Crimson Nile, white hair, ancient Egyptian aesthetic, dramatic sunset, 8k --ar 4:5",
            ),
            TopicIdea(
                id="fallback_kazu",
                category="❤️ Ветка с фаворитом",
                title="❤️ Ветка: Кадзу (Легенда Ивы)",
                topic="Кадзу: почему ветка с ним считается одной из лучших в КР",
                main_point="Тонкий психологизм, сдержанная забота и ключевые развилки в отношениях с ниндзя клана Синоби.",
                facts="• Доверие Кадзу выстраивается постепенно через уважение к его выбору.\n• Полный путь синоби описан в нашем интерактивном путеводителе.",
                cta="Полный гайд по «Легенде Ивы» ждёт вас в нашем боте!",
                target_story="Легенда Ивы",
                character_name="Кадзу",
                image_concept="Kazu shinobi from Legend of the Willow, bamboo forest at night, moonlight, Japanese aesthetic, 8k --ar 4:5",
            ),
            TopicIdea(
                id="fallback_diamonds",
                category="💎 Алмазы и экономия",
                title="💎 Гайд: Экономия алмазов в Клубе Романтики",
                topic="Как проходить новеллы без доната и копить тысячи алмазов",
                main_point="Рабочие лайфхаки для подготовки к Алмазной Лихорадке и правильного распределения ресурсов.",
                facts="• Регулярный сбор наград за просмотр рекламы каждые 1.5 часа.\n• Использование гайдов бота, чтобы не платить за пустые выборы.",
                cta="Читайте с удовольствием и пользуйтесь нашими бесплатными гайдами!",
                target_story="Клуб Романтики",
                image_concept="Shining blue diamonds, magic glow, fantasy romance style, 8k --ar 4:5",
            ),
        ]
        return fallbacks[:count]
