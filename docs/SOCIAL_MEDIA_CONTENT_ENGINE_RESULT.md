# Отчёт о реализации: Social Media Content Engine

## 1. Вводный аудит
В ходе аудита существующего бота «Клуб Романтики — Гайды» было установлено:
- Бот построен на **Aiogram 3.x** с асинхронным движком **SQLAlchemy 2.0** и поддерживает SQLite локально и PostgreSQL на продакшене (Render).
- Существующий стек идеально подходит для интеграции фонового омниканального Content Engine прямо внутри процесса бота без дополнительных платных сервисов.
- Все существующие пользовательские сценарии (гайды, навигация, пагинация, фильтры) изолированы от административной логики.

---

## 2. Что реализовано
1. **Модели данных Content Engine**:
   - `social_posts`: мастер-посты, тема, исходный текст, статусы (`DRAFT`, `APPROVED`, `SCHEDULED`, `PUBLISHING`, `PUBLISHED`, `PARTIALLY_PUBLISHED`, `FAILED`, `CANCELLED`), привязка к автору и новелле.
   - `social_post_variants`: независимые адаптированные версии для 4 платформ (`telegram`, `vk`, `instagram`, `threads`) с текстом, промптом для арта, URL картинки, внешним ID и счетчиком повторов (`retry_count`).
   - `social_publications`: журнал всех попыток публикаций с сохранением ответов API и ошибок.
   - `user_attributions`: сохранение переходов по персональным UTM-ссылкам вида `start=from_{platform}_p{id}`.

2. **Brand Voice и AI-генератор**:
   - Системный промпт в `bot/services/content_engine/brand_voice.py` с жестким запретом на выдумывание сюжета (защита от галлюцинаций), дружелюбным романтичным стилем фанатского комьюнити.
   - Адаптер `ContentAIEngine`: интеграция с OpenAI API (`gpt-4o-mini`) со структурированным JSON-выводом для 4 сетей + надежный шаблонный генератор (fallback) при отсутствии API-ключа.
   - Абстрактный интерфейс `ImageGenerator` и поддержка ручного прикрепления фото/URL администратором.

3. **Административный интерфейс в Telegram (`bot/handlers/admin_content.py`)**:
   - Вход через раздел **`📱 Контент`** в главной админ-панели.
   - FSM-создание постов вручную и через AI.
   - Интерактивная карточка предпросмотра со всеми 4 версиями.
   - Изолированное редактирование любого варианта через чат (`✏️ TG`, `✏️ VK`, `✏️ IG`, `✏️ Threads`).
   - Планирование времени (`📅 Запланировать`) и немедленная публикация (`🚀 Опубликовать сейчас`).
   - Раздел **`⚙️ Соцсети`** с бейджами статусов подключения (🟢/🔴) без раскрытия токенов.

4. **Безопасный планировщик (Safe Scheduler) и Идемпотентность**:
   - Атомарная блокировка задач по расписанию (`claim_due_scheduled_posts`).
   - Защита от двойной публикации (idempotency check по статусу и `external_post_id`).
   - Поддержка частичной публикации (`PARTIALLY_PUBLISHED`) и точечного перезапуска упавшей соцсети (`🔄 Повторить ...`).
   - Лимит повторов: до 3 попыток, затем перевод варианта в `FAILED`.

5. **Публикаторы площадок (Publishers)**:
   - **Telegram**: `TelegramPublisher` через официальный Aiogram Bot API (`send_photo` / `send_message`).
   - **VK**: `VkPublisher` через официальный VK API `wall.post`.
   - **Instagram**: `InstagramPublisher` через официальный Meta Graph API (`/{ig_user_id}/media` -> `media_publish`). Graceful fallback при отсутствии токена.
   - **Threads**: `ThreadsPublisher` через официальный Meta Threads API (`/{threads_user_id}/threads` -> `threads_publish`). Graceful fallback.

6. **UTM и Deep-link Атрибуция**:
   - Расширен обработчик `/start` в `bot/handlers/start.py`: распознает `from_tg_p{id}`, `from_vk_p{id}`, фиксирует переход в БД и автоматически открывает новеллу, привязанную к посту.

---

## 3. Изменённые и созданные файлы
- **Созданы**:
  - `bot/services/content_engine/types.py`
  - `bot/services/content_engine/brand_voice.py`
  - `bot/services/content_engine/ai_generator.py`
  - `bot/services/content_engine/attribution.py`
  - `bot/services/content_engine/publishers/base.py`
  - `bot/services/content_engine/publishers/telegram.py`
  - `bot/services/content_engine/publishers/vk.py`
  - `bot/services/content_engine/publishers/instagram.py`
  - `bot/services/content_engine/publishers/threads.py`
  - `bot/services/content_engine/publishers/__init__.py`
  - `bot/services/content_engine/scheduler.py`
  - `bot/database/repositories/social.py`
  - `bot/handlers/admin_content.py`
  - `tests/test_social_content_engine.py`
  - `docs/SOCIAL_MEDIA_CONTENT_ENGINE.md`
  - `docs/SOCIAL_MEDIA_SETUP_CHECKLIST.md`
  - `docs/SOCIAL_MEDIA_CONTENT_ENGINE_RESULT.md`
- **Модифицированы**:
  - `bot/config.py` (добавлены переменные соцсетей и dry-run)
  - `bot/database/models.py` (добавлены 4 новые таблицы)
  - `bot/handlers/__init__.py` (зарегистрирован `admin_content.router`)
  - `bot/handlers/admin.py` (добавлена кнопка `📱 Контент`)
  - `bot/handlers/start.py` (добавлена UTM-атрибуция)
  - `bot/main.py` (встроен фоновый `SafeContentScheduler`)
  - `.env.example` (документированы новые переменные)

---

## 4. База данных и миграции
- Добавлены таблицы: `social_posts`, `social_post_variants`, `social_publications`, `user_attributions`.
- Создание таблиц происходит автоматически через `init_db()` при старте приложения без изменения существующих таблиц и записей новелл.
- **Production Safety Check**: проверено, данные историй, сезонов, серий и выборов остались нетронутыми.

---

## 5. Подключение API
- **Подключены архитектурно**:
  - Telegram Bot API (полная готовность).
  - VK API (полная готовность, официальный endpoint `wall.post`).
  - Meta Instagram Graph API (полная готовность, официальный 2-step Container API).
  - Meta Threads API (полная готовность, официальный 2-step Threads API).
- **Статус конфигурации**:
  - При отсутствии секретов система корректно отображает бейдж `🔴 не подключён`, возвращает информативную ошибку и **не блокирует публикацию в остальные подключенные сети**.

---

## 6. Результаты тестов и Dry-Run
- **Новые тесты**: `tests/test_social_content_engine.py` (8 тестовых сценариев, включая CRUD, генерацию промптов, dry-run публикацию, идемпотентность, защиту от дублей, частичную публикацию, лимиты retry, шедулер и UTM deep-links).
- **Результат прогона тестов**:
  - `tests/test_social_content_engine.py`: **8 passed** (100% success).
  - Полный регрессионный прогон всего бота: **45 passed** (включая навигацию, гайды, пагинацию, дедупликацию каталога, чистку UI).
  - **Dry-run**: подтверждена безопасность тестового режима (`SOCIAL_PUBLISH_DRY_RUN=true`).

---

## 7. Известные ограничения и Рекомендации на будущее
1. **Instagram Media Requirements**: Instagram Graph API не поддерживает посты без изображений. Рекомендуется всегда указывать `image_url` при публикации в Instagram (в противном случае публикатор возвращает понятную ошибку).
2. **Meta App Review**: Для боевой публикации от имени аккаунта Meta требуется прохождение проверки приложения (App Review) в кабинете Meta for Developers для прав `instagram_content_publish` и `threads_content_publish`.
3. **Следующие шаги**:
   - Внести боевые ключи в Render Secrets по чеклисту `docs/SOCIAL_MEDIA_SETUP_CHECKLIST.md`.
   - В будущем при росте команды: развернуть Telegram Mini App интерфейс для визуального предпросмотра постов с телефона.

---

## 8. Финальный статус
### **PASS**
Все 34 пункта технического задания и плана реализации выполнены в полном объеме, протестированы и задокументированы.
