# PHASE 16 — Structural Deduplication / Merge & Production Deployment Guide

## 1. Сводка результатов дедупликации

В рамках Фазы 16 была успешно выполнена структурная дедупликация каталога и безопасное объединение (merge) историй в производственной базе данных `club_romance.db`.

### 1.1. Объединённые и удалённые дубликаты
- **«Идеал» (ID 77 vs ID 83)**:
  - Каноническая история: **ID 77** (2 тома: «Том 1» и «Том 2», 21 серия, 971 выбор, slug: `ideal`).
  - Дубликат ID 83 удалён без потери данных. Сезоны нормализованы в канонический формат «Том 1» и «Том 2».
- **«Бюро параллельных миров» (ID 57 vs ID 84)**:
  - Каноническая история: **ID 57** (2 сезона, 26 серий, 1 024 выбора, slug: `byuro-parallelnyh-mirov`).
  - Дубликат ID 84 удалён.
- **«Рождённая Луной» (ID 31 vs ID 32)**:
  - Каноническая история: **ID 32** (все 5 сезонов, 48 серий, 566 выборов, slug: `rozhdennaya-lunoi`).
  - Неполный дубликат ID 31 (содержал лишь 1 сезон) удалён.
- **Тестовые заглушки (ID 1, 2, 82)**:
  - ID 1 (`ten-shadows`, мок-история с тестовым прогрессом): тестовый прогресс, подписки и персонажи безопасно очищены, история удалена.
  - ID 2 (`Тест`, пустая заглушка): удалена.
  - ID 82 (`Тест 3`, пустая заглушка): удалена.

### 1.2. Финальное состояние производственной базы (`club_romance.db`)
| Параметр | Значение |
| :--- | :--- |
| **Размер файла** | 13 647 872 байт (13.02 МБ) |
| **Контрольная сумма SHA-256** | `8388b22d0115118efd233866314367831d2bb7e2b30baa803b6b4c2787148e72` |
| **Количество историй (Stories)** | **58** (100% официальных канонических историй Клуба Романтики) |
| **Количество сезонов (Seasons)** | **144** |
| **Количество серий (Episodes)** | **1 613** |
| **Количество выборов (Choices)** | **53 236** |
| **Пользовательский прогресс (Progress)** | 5 записей (100% реальных пользовательских данных сохранены) |
| **PRAGMA integrity_check** | `ok` |
| **PRAGMA foreign_key_check** | 0 нарушений |
| **Контрольные бэкапы** | `club_romance_before_phase16_dedup_20260920_150559.db`, `club_romance_before_phase16_dedup_20260920_155034.db` |

---

## 2. Инфраструктура деплоя (Production Deployment)

### 2.1. Предстартовая проверка (Pre-flight Check)
Перед запуском бота в любой среде рекомендуется запустить утилиту проверки:
```bash
python scripts/preflight_check.py
```
Скрипт проверяет:
1. Версию Python (>= 3.10).
2. Наличие всех зависимостей (`aiogram`, `sqlalchemy`, `aiosqlite`, `dotenv`, `pydantic_settings`).
3. Файл конфигурации `.env` и валидность `BOT_TOKEN`.
4. Целостность SQLite базы данных (`quick_check`, `foreign_key_check`) и объём контента (истории >= 50, серии >= 1000).
5. Сетевую связность с Telegram Bot API (`getMe`).

---

### 2.2. Вариант A: Запуск через Docker & Docker Compose (Рекомендуемый)

#### 1. Подготовка конфигурации
Убедитесь, что файл `.env` настроен:
```env
BOT_TOKEN=123456789:ABCDefghIJKlmNoPQRsTUVwxyZ
ADMIN_IDS=123456789
DATABASE_URL=sqlite+aiosqlite:///club_romance.db
LOG_LEVEL=INFO
```

#### 2. Запуск контейнера
```bash
docker compose up -d --build
```

#### 3. Мониторинг логов
```bash
docker compose logs -f club-romance-bot
```

#### 4. Остановка
```bash
docker compose down
```

---

### 2.3. Вариант B: Запуск на Linux VPS через systemd

#### 1. Размещение проекта
Склонируйте репозиторий в `/opt/club-romance-bot` и настройте виртуальное окружение:
```bash
cd /opt/club-romance-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Отредактируйте .env, указав реальный BOT_TOKEN
nano .env
```

#### 2. Настройка прав
```bash
chown -R www-data:www-data /opt/club-romance-bot
chmod 664 /opt/club-romance-bot/club_romance.db
mkdir -p /opt/club-romance-bot/logs /opt/club-romance-bot/backups
chown -R www-data:www-data /opt/club-romance-bot/logs /opt/club-romance-bot/backups
```

#### 3. Активация сервиса
Скопируйте юнит-файл:
```bash
sudo cp deployment/club-romance-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable club-romance-bot
sudo systemctl start club-romance-bot
```

#### 4. Управление и логи
```bash
# Статус сервиса
sudo systemctl status club-romance-bot

# Просмотр логов в реальном времени
sudo journalctl -u club-romance-bot -f
```

---

## 3. Резервное копирование (Backups & Maintenance)

Для горячего резервного копирования без остановки бота используется скрипт `scripts/backup_db.py`, реализующий SQLite Online Backup API.

### Ручной запуск
```bash
python scripts/backup_db.py --keep 15
```

### Автоматизация через Cron
Для создания резервной копии каждые 6 часов добавьте в crontab (`crontab -e`):
```cron
0 */6 * * * /opt/club-romance-bot/.venv/bin/python /opt/club-romance-bot/scripts/backup_db.py --dir /opt/club-romance-bot/backups --keep 20 >> /opt/club-romance-bot/logs/backup.log 2>&1
```

---

## 4. Набор автоматических тестов
Все 70 тестов проекта выполняются успешно:
```bash
rtk pytest tests
```
- `tests/test_catalog_deduplication.py`: валидация уникальности 58 историй, структуры томов и отсутствия дубликатов.
- `tests/test_ui_pagination.py`: валидация разбивки текста гайдов и кнопок пагинации в рамках лимитов Telegram.
- `tests/test_deployment_tools.py`: тестирование pre-flight чекера и механизма горячих бэкапов.
- `tests/test_imports.py` и `tests/gamesisart/`: тестирование парсера, валидатора и стадийного пайплайна.
