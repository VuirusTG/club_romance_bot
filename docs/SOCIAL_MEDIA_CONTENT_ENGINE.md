# Social Media Content Engine — Руководство и Архитектура

## 1. Архитектура системы

Система Social Media Content Engine представляет собой изолированный омниканальный модуль внутри бота «Клуб Романтики — Гайды». Она позволяет из единой точки создавать, адаптировать с помощью AI, утверждать, планировать и автоматически публиковать контент в **Telegram**, **VK**, **Instagram** и **Threads**.

### Схема компонентов:
- **Admin Interface (`bot/handlers/admin_content.py`)**: FSM-диалоги создания поста, интерактивное превью, редактирование вариантов по платформам, планирование времени, ручной вызов публикации и повтора (retry).
- **Brand Voice & AI Generator (`bot/services/content_engine/`)**: Централизованный системный промпт исключает галлюцинации и гарантирует каноничный голос фанатского сообщества. Адаптирует исходную тему в 4 специфичных формата + формирует промпт для арта (`4:5`).
- **Data Layer (`social_posts`, `social_post_variants`, `social_publications`, `user_attributions`)**: Полное сохранение истории, статусов, попыток и UTM-аналитики переходов.
- **Safe Scheduler (`bot/services/content_engine/scheduler.py`)**: Фоновый цикл с атомарным захватом постов (`SELECT ... FOR UPDATE`), защитой от двойных публикаций и поддержкой частичной публикации (`PARTIALLY_PUBLISHED`).
- **Platform Publishers (`publishers/`)**: Драйверы официальных API Telegram Bot API, VK API, Meta Instagram Graph API и Meta Threads API.

---

## 2. Схема базы данных

```sql
-- Мастер-пост
CREATE TABLE social_posts (
    id SERIAL PRIMARY KEY,
    topic VARCHAR(255) NOT NULL,
    source_text TEXT DEFAULT '',
    target_story_id INTEGER REFERENCES stories(id) ON DELETE SET NULL,
    status VARCHAR(50) DEFAULT 'DRAFT',
    created_by BIGINT NOT NULL,
    scheduled_at TIMESTAMP WITH TIME ZONE,
    published_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Адаптированные варианты по площадкам
CREATE TABLE social_post_variants (
    id SERIAL PRIMARY KEY,
    post_id INTEGER NOT NULL REFERENCES social_posts(id) ON DELETE CASCADE,
    platform VARCHAR(50) NOT NULL,
    text TEXT DEFAULT '',
    image_prompt TEXT,
    image_url VARCHAR(1024),
    status VARCHAR(50) DEFAULT 'DRAFT',
    external_post_id VARCHAR(255),
    published_at TIMESTAMP WITH TIME ZONE,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Журнал попыток и аудита публикаций
CREATE TABLE social_publications (
    id SERIAL PRIMARY KEY,
    variant_id INTEGER NOT NULL REFERENCES social_post_variants(id) ON DELETE CASCADE,
    platform VARCHAR(50) NOT NULL,
    attempt_number INTEGER DEFAULT 1,
    external_post_id VARCHAR(255),
    status VARCHAR(50) NOT NULL,
    response_payload TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- UTM & Deep-Link Атрибуция стартов бота
CREATE TABLE user_attributions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    platform VARCHAR(50) NOT NULL,
    post_id INTEGER,
    campaign VARCHAR(100),
    raw_payload VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

---

## 3. Жизненный цикл контента (Content Lifecycle)

1. **Создание**: Администратор запускает `➕ Создать пост` или `🤖 Создать с AI`. Вводит тему, основную мысль, факты, CTA и опционально новеллу. Создается запись со статусом `DRAFT`.
2. **Адаптация**: Генерируются 4 платформенных варианта текста + Image Prompt.
3. **Предпросмотр и правки**: Админ видит тексты в Telegram. Может нажать `✏️ TG`, `✏️ VK`, `✏️ IG`, `✏️ Threads` и изменить конкретный вариант без влияния на остальные.
4. **Утверждение и планирование**:
   - `🚀 Опубликовать сейчас`: немедленный вызов диспетчера.
   - `📅 Запланировать`: ввод даты/времени в формате `YYYY-MM-DD HH:MM`. Статус становится `SCHEDULED`.
5. **Публикация**: Планировщик атомарно блокирует пост (`PUBLISHING`), вызывает драйверы площадок.
6. **Частичная публикация**:
   - Если TG и VK успешны, а IG упал — пост переходит в `PARTIALLY_PUBLISHED`.
   - В интерфейсе появляется кнопка `🔄 Повторить INSTAGRAM`.
   - После 3 неудачных попыток вариант переводится в `FAILED`.

---

## 4. Переменные окружения (.env)

```env
# Режим Dry-Run (безопасное тестирование без реальной отправки в соцсети)
SOCIAL_PUBLISH_DRY_RUN=true

# AI Provider
OPENAI_API_KEY=sk-...

# Telegram Channel
TELEGRAM_CHANNEL_ID=-1001234567890

# VK Community
VK_GROUP_ID=123456789
VK_ACCESS_TOKEN=vk1.a....

# Meta Instagram Graph API
INSTAGRAM_BUSINESS_ACCOUNT_ID=178414...
META_ACCESS_TOKEN=EAA...

# Meta Threads API
THREADS_USER_ID=123456...
THREADS_ACCESS_TOKEN=THQ...
```

---

## 5. Подключение площадок

### 1. Telegram
- Добавьте бота администратором в ваш публичный или приватный канал с правом публикации сообщений.
- Укажите ID канала в `TELEGRAM_CHANNEL_ID` (например, `-1001987654321` или `@my_channel`).

### 2. VK
- В настройках сообщества VK создайте API-токен с правами `wall`, `photos` и `offline`.
- Укажите ID сообщества в `VK_GROUP_ID` (только цифры) и токен в `VK_ACCESS_TOKEN`.

### 3. Instagram (Meta Graph API)
- Требуется Instagram Professional (Business или Creator) аккаунт, привязанный к Facebook Page.
- В [Meta for Developers](https://developers.facebook.com/) создайте приложение, добавьте разрешение `instagram_content_publish`.
- Получите долгосрочный `Page Access Token` и `Instagram Business Account ID`.
- *Примечание*: Instagram API требует публичный URL картинки (HTTP/HTTPS).

### 4. Threads (Meta Threads API)
- В панели Meta for Developers подключите продукт **Threads API**.
- Запросите разрешение `threads_content_publish`.
- Получите `threads_user_id` и `threads_access_token`.

---

## 6. Как создать первый пост и запланировать публикацию

1. В боте введите команду `/admin`.
2. Нажмите кнопку **`📱 Контент`**.
3. Выберите **`🤖 Создать с AI`**.
4. Введите тему (например, *«Как накопить 1000 алмазов к новой обнове»*).
5. Введите мысль (*«Ежедневный вход, реклама каждые 1.5 часа, прохождение первых серий новых историй»*).
6. Введите факты и CTA (или отправьте `-` для дефолтных).
7. Бот пришлет карточку предпросмотра со всеми 4 версиями.
8. Нажмите **`📅 Запланировать`** и введите, например, `2026-10-01 15:00`.
9. Пост сохранен и отображается в разделе `📅 Запланированные`. В назначенное время шедулер автоматически отправит его во все подключенные каналы!
