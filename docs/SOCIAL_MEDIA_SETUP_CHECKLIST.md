# Чеклист запуска и настройки Social Media Content Engine

Используйте этот чеклист при настройке production-окружения и подключении новых социальных сетей:

- [x] **Базовая архитектура и БД**
  - [x] Модели `social_posts`, `social_post_variants`, `social_publications`, `user_attributions` созданы.
  - [x] Автоматическая инициализация схемы БД при запуске (`init_db`).
  - [x] Изолированное хранилище состояний и FSM-хэндлеры.

- [x] **Telegram Admin UI**
  - [x] Кнопка `📱 Контент` доступна в `/admin`.
  - [x] Разделы `Черновики`, `Запланированные`, `Опубликованные`, `Ошибки`.
  - [x] Раздел `⚙️ Соцсети` с маскированием токенов и индикацией статусов.

- [x] **AI и генерация вариантов**
  - [x] Brand Voice промпт настроен (каноничность, дружелюбный стиль, без галлюцинаций).
  - [x] Раздельная адаптация под Telegram, VK, Instagram, Threads.
  - [x] Генерация Image Prompt в формате `4:5`.
  - [x] Защитный шаблонный генератор (fallback) при отсутствии `OPENAI_API_KEY`.

- [x] **Безопасность и Dry-Run**
  - [x] `SOCIAL_PUBLISH_DRY_RUN=true` протестирован (эмуляция публикации без выхода в сеть).
  - [x] Защита от дублей (Idempotency) на уровне статусов и ID.
  - [x] Лимит retry (максимум 3 попытки, статус FAILED).
  - [x] Никаких hardcoded-секретов в кодовой базе и логах.

- [x] **Шедулер и частичная публикация**
  - [x] Фоновый `SafeContentScheduler` встроен в жизненный цикл бота в `bot/main.py`.
  - [x] Атомарный захват задач по расписанию (`claim_due_scheduled_posts`).
  - [x] Поддержка частичной публикации (`PARTIALLY_PUBLISHED`) и повтора упавшей площадки.

- [x] **UTM и Deep-link Атрибуция**
  - [x] Генератор ссылок `generate_deep_link` (`from_tg_p{id}`, `from_vk_p{id}`, и т.д.).
  - [x] Парсер `/start` сохраняет визит в `user_attributions` и открывает новеллу поста.

- [ ] **Подключение боевых аккаунтов (Production Credentials)**
  - [ ] `TELEGRAM_CHANNEL_ID` добавлен в Render Secrets.
  - [ ] Бот назначен админом Telegram-канала.
  - [ ] `VK_GROUP_ID` и `VK_ACCESS_TOKEN` получены и добавлены.
  - [ ] `META_ACCESS_TOKEN` и `INSTAGRAM_BUSINESS_ACCOUNT_ID` получены.
  - [ ] `THREADS_ACCESS_TOKEN` и `THREADS_USER_ID` получены.
  - [ ] Протестирован тестовый пост в режиме `SOCIAL_PUBLISH_DRY_RUN=false`.
