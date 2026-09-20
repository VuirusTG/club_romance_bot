# GamesIsArt Import Audit

Дата аудита: 2026-08-17.

Статус: PHASE 1 выполнена. База данных не изменялась, импорт не запускался, destructive operations не выполнялись.

## 1. Текущая архитектура проекта

Проект является существующим Telegram-ботом на aiogram 3. Рабочий код находится в корневых директориях `bot/`, `scripts/`, `tests/`, `migrations/`. В проекте также лежит архивная/дублирующая копия `zip/`; для дальнейших работ нужно менять рабочий код в корне, а не `zip/`.

Основные компоненты:

- `bot/main.py` запускает aiogram polling, вызывает `init_db()` и регистрирует handlers.
- `bot/config.py` читает `.env` через Pydantic Settings. Используемая БД по умолчанию: `sqlite+aiosqlite:///./club_romance.db`.
- `bot/database/models.py` содержит SQLAlchemy 2 ORM-модели.
- `bot/database/database.py` создаёт async engine/session и выполняет минимальные SQLite-миграции через `ALTER TABLE` для уже добавленных source fields.
- `bot/database/repositories/content.py` содержит repository-функции для пользовательского flow.
- `bot/handlers/stories.py` реализует flow `Истории -> Сезон -> Серия -> Гайд`.
- `bot/keyboards/guides.py` реализует фильтры гайда.
- `bot/handlers/admin.py` содержит текущую админку для ручного управления историями, сезонами, сериями, пунктами гайда, статистикой и рассылкой.

## 2. Текущая схема данных

Ключевые ORM-модели:

- `Story` (`bot/database/models.py:46`): `title`, `slug`, `description`, `genre`, `status`, `guide_source_name`, `guide_source_url`, `is_published`, `views_count`.
- `Season` (`bot/database/models.py:66`): `story_id`, `number`, `title`, `description`; уникальность `(story_id, number)`.
- `Episode` (`bot/database/models.py:80`): `season_id`, `number`, `title`, `summary`, `guide_intro`, `guide_source_name`, `guide_source_url`, `is_published`; уникальность `(season_id, number)`.
- `Choice` (`bot/database/models.py:143`): `episode_id`, `order_index`, `scene_title`, `text`, `recommended_option`, `cost_diamonds`, `consequence`, `requirements`, `parameter_changes`, `character_effects`, `future_effects`, `tags`, `spoiler_level`, `is_critical`.
- `UpdatePost` (`bot/database/models.py:165`): игровые обновления.

В текущей схеме отсутствуют:

- `source_key`;
- `source_hash`;
- `source_title`;
- `display_title`;
- `parser_version`;
- отдельный журнал импорта;
- таблица alias/mapping для source identity;
- таблица для сохранения DOM/block-level структуры гайда.

Следствие: текущая БД не может надёжно отличить изменение отображаемого названия от новой истории.

## 3. Пользовательский Telegram flow

`bot/handlers/stories.py` использует существующую структуру:

- список историй через `content.list_stories`;
- карточка истории через `content.get_story`;
- сезоны через `content.list_seasons`;
- серии через `content.list_episodes`;
- гайд через `content.get_episode_with_choices`.

Фильтры гайда находятся в `_filter_choices` (`bot/handlers/stories.py:16`):

- `diamond`: `choice.cost_diamonds > 0`;
- `romance`: строковые теги `romance` или `роман`;
- `parameter`: непустое `choice.parameter_changes`;
- `critical`: `choice.is_critical`.

Форматирование гайда (`bot/utils/formatting.py:25`) выводит:

- `scene_title`;
- `recommended_option`;
- `cost_diamonds`;
- `consequence`;
- `parameter_changes`;
- `character_effects`;
- `future_effects`;
- `requirements`.

Новый импортёр должен сохранять совместимость с этими полями. Иначе фильтры Telegram-бота будут показывать неполную или неверную информацию.

## 4. Текущая админка

`bot/handlers/admin.py` уже поддерживает:

- добавление Story (`admin_add_story`, `bot/handlers/admin.py:394`);
- добавление Season (`admin_add_season`, `bot/handlers/admin.py:402`);
- добавление Episode (`admin_add_episode`, `bot/handlers/admin.py:411`);
- добавление Choice (`admin_add_choice`, `bot/handlers/admin.py:420`);
- редактирование Choice (`admin_edit_choice`, `bot/handlers/admin.py:455` и state handler ниже);
- удаление Story/Season/Episode/Choice через подтверждение (`bot/handlers/admin.py:465`-`531`).

GamesIsArt Preview/Import в админке пока отсутствует.

## 5. Текущая логика импорта GamesIsArt

В проекте есть два импортёра:

1. `scripts/import_gamesisart_guides.py`
2. `scripts/import_gamesisart_guides_sqlite.py`

### SQLAlchemy importer

`scripts/import_gamesisart_guides.py`:

- использует `HTMLParser` (`GuideHeadingParser`, строка 32);
- извлекает историю из заголовков через regex;
- нормализует название через большой hardcoded dictionary (`normalize_story_title`, строка 111);
- определяет серии из heading regex вида `(\d+)\.(\d+)\.?\s+(.+)`;
- складывает весь текст внутри текущей серии в `body_parts`;
- выделяет "важные" пункты через `IMPORTANT_MARKERS` (`строка 244`);
- режет общий текст серии через `split_episode_notes()` (`строка 273`);
- создаёт `Choice` из фрагментов текста в `replace_imported_choices()` (`строка 410`);
- ищет/создаёт Story только по `Story.title` (`get_or_create_story`, строка 333).

### Direct sqlite importer

`scripts/import_gamesisart_guides_sqlite.py`:

- импортирует `sqlite3` напрямую (`строка 5`);
- использует отдельный `GuideParser` на `HTMLParser` (`строка 47`);
- собирает ссылки через `collect_guide_urls()` (`строка 187`);
- содержит свой `normalize_story_title()` (`строка 121`), отличный от SQLAlchemy importer;
- использует `IMPORTANT_MARKERS` (`строка 203`);
- режет общий текст серии через `split_notes()` (`строка 215`);
- выполняет ручные `ALTER TABLE` и CRUD через SQL (`ensure_columns`, `get_story`, `get_episode`, `replace_choices`);
- пишет напрямую в SQLite (`sqlite3.connect`, строка 429), обходя SQLAlchemy layer.

## 6. Найденные проблемы старого импорта

### 6.1 Нет полноценного DOM parser

Оба импортёра используют `html.parser.HTMLParser` и собирают данные как поток текста. Последовательная DOM-структура страницы не сохраняется. В результате parser не знает, где именно paragraph, option, price, effect, relationship, parameter или scene block.

### 6.2 Choice создаются эвристически

`Choice` создаются не из фактической структуры выбора на странице, а из фрагментов, найденных по словам-маркерам:

- `+1`;
- `-1`;
- `алмаз`;
- `кристалл`;
- `отнош`;
- `репутац`;
- `путь`;
- `выбираем`;
- `повлияет`;
- и т.д.

Это приводит к ложным choices, пропускам и неверным `recommended_option`.

### 6.3 Story identity построен на title

Текущий `get_or_create_story()` ищет Story по `title`. При изменении орфографии, регистра, `ё/е`, сокращения или display title создаётся новая Story.

Уже обнаружен реальный дубль:

- `Рожденная Луной`
- `Рождённая Луной`

### 6.4 `guide_source_url` у Story не является identity

В текущей БД импортированные GamesIsArt stories имеют `guide_source_url = https://gamesisart.ru/guide/Romance_Club_Prohozhdenie.html`, то есть URL общего индекса, а не URL конкретной истории.

Это делает невозможным безопасное сопоставление Story по источнику после факта.

### 6.5 Два database layer

Наличие `scripts/import_gamesisart_guides_sqlite.py` нарушает архитектуру проекта: основной проект использует SQLAlchemy, а importer пишет в БД напрямую через `sqlite3`.

### 6.6 Нет intermediate JSON

Невозможно посмотреть, что именно parser извлёк до записи в БД. Это усложняет отладку и повышает риск повреждения данных при массовом импорте.

### 6.7 Нет validator

Перед записью не проверяется:

- уникальность сезонов;
- уникальность серий внутри сезона;
- пропуски номеров;
- непустые titles;
- сохранение block order;
- корректность стоимости;
- корректность effects/tags.

### 6.8 Нет import log

Нельзя понять:

- когда импорт запускался;
- какой URL импортировался;
- какой hash страницы был обработан;
- какой parser_version использовался;
- сколько было warnings/errors;
- был ли rollback.

## 7. Snapshot текущей SQLite database

Файл: `club_romance.db`.

Read-only аудит показал:

- размер: 5 636 096 bytes;
- `users`: 1;
- `stories`: 54;
- `seasons`: 60;
- `episodes`: 635;
- `choices`: 8235;
- `characters`: 2;
- `parameters`: 0;
- `updates`: 4;
- `subscriptions`: 1;
- `progress`: 4.

GamesIsArt stories по текущему признаку `guide_source_name/guide_source_url`: 51.

Подтверждён потенциальный дубль:

```text
Рожденная Луной
Рождённая Луной
```

Топ тегов в `choices`:

- `gamesisart_import,parameter`: 4480;
- `gamesisart_import,romance`: 1644;
- `gamesisart_import`: 1368;
- `gamesisart_import,romance,parameter`: 428;
- `gamesisart_import,diamond`: 95.

Это показывает перекос: большая часть choices классифицирована маркерами, а структурные поля `parameter_changes` и `character_effects` часто не заполнены.

## 8. Текущие тесты

В `tests/test_imports.py` есть только `test_project_compiles`, который проверяет компиляцию `bot/`.

Отсутствуют тесты для:

- discovery;
- parser;
- story detection;
- season detection;
- episode detection;
- episode order;
- choice parsing;
- validator;
- duplicate detection;
- dry-run;
- import idempotency;
- update hash check.

## 9. Риски миграции

### 9.1 Риск потери ручных правок

В текущей БД есть 8235 choices. Часть могла быть отредактирована вручную через админку. Автоматическое удаление `gamesisart_import` choices без отчёта может потерять полезные ручные исправления.

### 9.2 Риск неверного merge дублей

Сливать истории по похожести строк нельзя. Например, `Рождённая Луной` и `Рождённая Солнцем` похожи по форме, но это разные истории. Критерий merge должен быть source identity: canonical URL/source_key.

### 9.3 Риск несовместимости с Telegram filters

Если новый importer будет сохранять effects только в JSON/block model и не перенесёт их в существующие поля `Choice`, фильтры `Алмазы`, `Романтика`, `Параметры`, `Критичные` перестанут быть полезными.

### 9.4 Риск отсутствия обратной совместимости схемы

Добавление `source_key`, `source_hash`, `source_title`, `parser_version`, import log и, возможно, block table потребует миграции. Нужно сделать её идемпотентной для SQLite и не ломать уже существующие записи.

### 9.5 Риск сетевой нестабильности

GamesIsArt может отдавать HTML в нестандартной кодировке или временно возвращать ошибки. Новый client обязан иметь timeout, User-Agent, retry limit и raw HTML debug dump.

### 9.6 Риск изменения HTML источника

Parser должен быть DOM-based, но с validator warnings. При изменении структуры страницы importer должен завершаться preview/import с ошибкой или warnings, а не тихо писать мусор в БД.

## 10. Рекомендованная новая архитектура

Следующие фазы должны строиться вокруг отдельного package:

```text
scripts/gamesisart/
  __init__.py
  client.py
  discovery.py
  parser.py
  models.py
  normalizer.py
  validator.py
  importer.py
  reporter.py
  cli.py
```

Ключевые принципы:

- HTTP client отдельно от parsing.
- Discovery ищет конкретные guide URLs и нормализует их.
- Story identity строится по `source_name + source_key/canonical_url`, а не по title.
- Parser работает по DOM и сохраняет последовательные blocks.
- Parser создаёт intermediate JSON в `data/gamesisart/parsed/`.
- Validator блокирует импорт при критических ошибках.
- Import работает через SQLAlchemy, транзакционно и идемпотентно.
- Direct sqlite importer должен быть заменён/удалён после появления нового SQLAlchemy importer.
- Старые GamesIsArt данные нельзя удалять до backup, old data audit и успешного теста `7 братьев`.

## 11. Вывод PHASE 1

Текущий импорт GamesIsArt нужно заменить, а не дорабатывать точечно. Главные blockers:

1. отсутствует source identity;
2. Story создаётся по display title;
3. choices создаются по regex-маркерам из общего текста;
4. нет JSON preview/debug слоя;
5. нет validation;
6. нет import log;
7. есть direct sqlite importer, обходящий SQLAlchemy;
8. в БД уже есть дубль `Рожденная Луной` / `Рождённая Луной`.

Следующая безопасная фаза: PHASE 2 Backup. До неё нельзя выполнять destructive operations и нельзя запускать массовый импорт.
