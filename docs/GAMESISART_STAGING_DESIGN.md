# GamesIsArt Staging & Safe Import Design — PHASE 7

**Версия спецификации**: 1.0.0  
**Parser version**: 1.2.0  
**Staging DB**: `data/gamesisart/staging.db`  
**Production DB (Read-Only)**: `club_romance.db`  
**Статус**: ✅ APPROVED & IMPLEMENTED

---

## 1. Общая архитектура Staging Pipeline

Архитектура пайплайна разделена на изолированные контуры, гарантирующие 100% защиту production БД от случайной перезаписи или порчи:

```
[GamesIsArt Raw HTML] 
        │
        ▼ (DOM Parser v1.2.0)
 [StoryDocument JSON]
        │
        ├──────────────────────────────────────────┐
        ▼ (Staging Import Engine)                  ▼ (Dry-Run / Diff Engine)
[Staging SQLite DB]                        [Read-Only Prod Comparator]
(data/gamesisart/staging.db)               (club_romance.db mode=ro)
- staging_sources                                  │
- staging_stories                                  ▼
- staging_seasons                          [Detailed Diff Report]
- staging_episodes                         - NEW / MATCH / CHANGED
- staging_choices                          - Potential conflicts
                                           - Zero DB writes
```

---

## 2. Идентификация сущностей (Source Identity & Idempotency)

Для предотвращения дубликатов при повторных запусках определена многоуровневая система идентификаторов:

### 2.1. Story Identity
- **Ключ**: `source_key` (например, `gamesisart:romance_club_prohozhdenie_seven`).
- **Свойства**:
  - `source_key`: уникальный детерминированный ключ из URL.
  - `canonical_url`: нормализованный абсолютный URL страницы истории.
  - `source_title`: название истории, извлеченное из `h1.TextTopOn`.
- **Сопоставление с Production**:
  1. Поиск по `guide_source_url == canonical_url`.
  2. Fallback: поиск по токовому совпадению `title == source_title`.

### 2.2. Season Identity
- **Ключ**: `f"{story_source_key}:s{season_number}"`.
- **Сопоставление с Production**: `(story_id, season_number)`.

### 2.3. Episode Identity
- **Ключ**: `f"{story_source_key}:s{season_number}:e{episode_number}"`.
- **Сопоставление с Production**: `(season_id, episode_number)`.

### 2.4. Choice Identity
- **Ключ**: `f"{story_source_key}:s{season_number}:e{episode_number}:c{order_index}"`.
- **Позиционирование**: Порядковый номер `order_index` (1..N) внутри серии гарантирует стабильную последовательность развилок при отображении пользователю Telegram-бота.

---

## 3. Анализ Multi-Option и выработка технического решения

### 3.1. Исследование реальных HTML-конструкций

В историях GamesIsArt выборы гардероба, причёсок и комнат оформляются не как отдельные диалоговые строки `<font class="TextItem">`, а как единый абзац, начинающийся с длинного тире `— `.

#### Пример 1. Выбор одежды (7 братьев, S1E1, Блок #52)
- **HTML**:
  ```html
  <p>— Рубашка в клетку (0), Кашемир (18 к, <font class="TextUp">+1 лисичка</font>), Мешковатые штаны (33 к, <font class="TextUp">+1 чертовка</font>), Последний день лета (33 к, <font class="TextUp">+1 принцесса</font>), Всё (<font class="TextUp">+1 ко всему</font>).</p>
  ```
- **Логических вариантов**: 5.
- **Связь параметров**:
  - Рубашка в клетку (0) → без статов.
  - Кашемир (18 к) → `+1 лисичка`.
  - Мешковатые штаны (33 к) → `+1 чертовка`.
  - Последний день лета (33 к) → `+1 принцесса`.
  - Всё → `+1 ко всему`.
- **Что сохраняет парсер**: 1 `ChoiceDocument`, `cost_diamonds=33`, `parameter_changes=['+1 лисичка', '+1 чертовка', '+1 принцесса', '+1 ко всему']`.
- **Проблема**: Параметры всех подвариантов слиты в один массив.

#### Пример 2. Выбор причёски с дубликатами (7 братьев, S1E1, Блок #53)
- **HTML**:
  ```html
  <p>— Хвост (бесплатно), Наполовину собранные – светлые (18 к, <font class="TextUp">+1 принцесса</font>), С заколками – каштановые (18 к, <font class="TextUp">+1 чертовка</font>), Идеальные локоны – черные (18 к, <font class="TextUp">+1 лисичка</font>), Коса "рыбий хвост" – черные (33 к, <font class="TextUp">+1 принцесса</font>), Сбритый висок (33 к, <font class="TextUp">+1 чертовка</font>), Каре (33 к, <font class="TextUp">+1 лисичка</font>), Выбрать всё (138 к, <font class="TextUp">+2 ко всему</font>).</p>
  ```
- **Логических вариантов**: 8.
- **Что сохраняет парсер**: `cost_diamonds=138`, `parameter_changes` содержит 7 записей с явными дубликатами (`+1 принцесса` x2, `+1 чертовка` x2, `+1 лисичка` x2, `+2 ко всему`).

#### Пример 3. Выбор комнаты (7 братьев, S1E2, Блок #96)
- **HTML**:
  ```html
  <p>— Базовый (бесплатно), Летняя ночь (8 к, <font class="TextUp">+2 принцесса</font>), Оттенки серого (8 к, <font class="TextUp">+2 лисичка</font>), Чёрный на чёрном (8 к, <font class="TextUp">+2 чертовка</font>).</p>
  ```
- **Логических вариантов**: 4.
- **Параметры**: 3 разных стата по 8 алмазов каждый.

#### Пример 4. Вечернее платье (7 братьев, S1E2, Блок #122)
- **HTML**:
  ```html
  <p>— Свитер и юбка в клетку (бесплатно), Изысканное облегающее вечернее платье (23 к, <font class="TextUp">+1 лисичка</font>), Коктейльное платье (26 к, <font class="TextUp">+1 принцесса</font>), Мини-платье с корсетом (26 к, <font class="TextUp">+1 чертовка</font>), Выбрать все (67 к, <font class="TextUp">+1 ко всему</font>).</p>
  ```
- **Логических вариантов**: 5.

#### Пример 5. Причёски для бала (7 братьев, S1E2, Блок #123)
- **HTML**:
  ```html
  <p>— Прямые с пробором посередине – каштановые (бесплатно), Два пучка (23 к, <font class="TextUp">+1 чертовка</font>), Волны с боковым пробором – рыжие (23 к, <font class="TextUp">+1 лисичка</font>), Повязка – светлые (23 к, <font class="TextUp">+1 принцесса</font>), Длинные косы (26 к, <font class="TextUp">+1 принцесса</font>), Чёлка – каштановые (26 к, <font class="TextUp">+1 лисичка</font>), Чёрно-белые (26 к, <font class="TextUp">+1 Чертовка</font>), Выбрать все (132 к, <font class="TextUp">+2 ко всему</font>).</p>
  ```
- **Логических вариантов**: 8.

---

### 3.2. Сравнение архитектурных решений

| Критерий | Вариант А: 1 ChoiceDocument + `sub_options` | Вариант Б: Расщепление на N отдельных Choice |
|---|---|---|
| **Соответствие игре** | **Полное**. В игре это один экран примерки, игрок выбирает 1 вещь из списка. | **Искажение**. Бот задаст игроку 8 последовательных вопросов подряд на одном экране. |
| **DOM-границы** | **Точное**. Весь список находится внутри одного тега `<p>`. | **Искусственное**. Требует разбиения текста запятыми внутри абзаца. |
| **Схема БД (таблица `choices`)** | **Совместима**. Сохраняется 1 запись на экран, текст списка доступен игроку. | **Несовместима**. Увеличивает число записей в таблице в 5-8 раз, ломая пагинацию. |
| **Риск ошибки привязки статов** | **Нулевой**. Все варианты отображаются в исходном контексте автора. | **Высокий**. Ошибки парсинга при сложных запятых внутри названий вариантов. |

### 3.3. Вывод и решение
Выбран **Вариант А**:
1. На уровне DOM-парсера и Staging DB multi-option блок сохраняется как **одна логическая развилка сцены** (`ChoiceDocument`).
2. В поле `text` сохраняется исходный полный текст вариантов автора.
3. В поле `cost_diamonds` сохраняется максимальная стоимость выбора («Выбрать всё» или самый дорогой наряд).
4. Расширение модели на `sub_options: list[SubOption]` спроектировано для будущей фазы семантического отображения в UI Telegram-бота, но не требует ломки схемы БД `choices`.

---

## 4. Staging База Данных (`data/gamesisart/staging.db`)

Для изолированного хранения распарсенных данных создана отдельная база данных SQLite:

### Схема таблиц:
- `staging_sources`:
  - `source_key` (PK), `canonical_url`, `source_title`, `parser_version`, `content_hash`, `page_urls`, `status`, `created_at`, `updated_at`.
- `staging_stories`:
  - `id` (PK), `source_key` (UNIQUE, FK), `title`, `canonical_url`, `parser_version`, `content_hash`, `created_at`.
- `staging_seasons`:
  - `id` (PK), `source_key` (FK), `number`, `title`, `UNIQUE(source_key, number)`.
- `staging_episodes`:
  - `id` (PK), `source_key` (FK), `season_number`, `episode_number`, `title`, `blocks_count`, `choices_count`, `UNIQUE(source_key, season_number, episode_number)`.
- `staging_choices`:
  - `id` (PK), `source_key` (FK), `season_number`, `episode_number`, `order_index`, `text`, `cost_diamonds`, `parameter_changes`, `character_effects`, `future_effects`, `is_critical`, `tags`, `UNIQUE(source_key, season_number, episode_number, order_index)`.

### Идемпотентность:
- Если `content_hash` и `parser_version` совпадают с имеющимися в базе, операция возвращает `status: 'UP_TO_DATE'` без выполнения дисковых операций записи.
- При принудительном перезапуске (`force=True` или изменении хэша/версии) транзакция атомарно перезаписывает дочерние таблицы источника, исключая дубликаты.

---

## 5. Dry-Run & Diff Engine

Механизм **Dry-Run** позволяет полностью смоделировать импорт без записи в БД:
1. **Parse**: Загрузка сырого HTML и преобразование в `StoryDocument`.
2. **Validate**: Проверка целостности и связности объектов.
3. **Hash**: Вычисление SHA-256 хэша страниц истории.
4. **Diff (Read-Only)**: Открытие `club_romance.db` в режиме `mode=ro` и построение отчета:
   - **MATCH**: Существующие совпадающие сущности.
   - **NEW**: Новые сущности, отсутствующие в базе.
   - **CHANGED**: Сущности с изменившимися метаданными (например, URL источника).
   - **PLACEHOLDER_REPLACE**: Существующие плейсхолдеры, готовые к безопасной замене на структурированные данные.

### CLI-команды:
```bash
# 1. Запуск dry-run с полным отчетом
python -m scripts.gamesisart.cli dry-run --url "https://gamesisart.ru/guide/Romance_Club_Prohozhdenie_Seven.html"

# 2. Детальный diff с production БД
python -m scripts.gamesisart.cli diff --url "https://gamesisart.ru/guide/Romance_Club_Prohozhdenie_Seven.html"

# 3. Идемпотентный импорт в Staging DB
python -m scripts.gamesisart.cli stage --url "https://gamesisart.ru/guide/Romance_Club_Prohozhdenie_Seven.html"
```

---

## 6. Результаты Diff для «7 братьев»

| Сущность | В Production БД | В Parsed GamesIsArt | Статус Diff | Примечание |
|---|---|---|---|---|
| **Story** | id=53 («7 братьев») | «7 братьев» | **MATCH / CHANGED** | Найдено совпадение по title. `guide_source_url` изменится с каталога на канонический URL истории. |
| **Seasons** | 1 сезон (id=52) | 3 сезона | **1 MATCH, 2 NEW** | Сезоны 2 и 3 отсутствуют в production БД и будут безопасно созданы. |
| **Episodes** | 10 эпизодов | 30 эпизодов | **10 MATCH, 20 NEW** | Серии 1.1–1.10 существуют; серии сезонов 2 и 3 являются новыми. |
| **Choices** | 269 плейсхолдеров | 1 533 реальных выбора | **653 PLACEHOLDER_REPLACE, 880 NEW** | 269 низкокачественных плейсхолдеров в Сезоне 1 готовы к замене на 653 реальных выбора. Все 880 выборов Сезонов 2 и 3 — новые. |

---

## 7. План подготовки к будущему массовому импорту (Phase 8+)

1. Сформировать резервную копию `club_romance.db.bak`.
2. Запустить staging-импорт для всех проверенных источников в `staging.db`.
3. Сгенерировать batch diff report по всем источникам.
4. Выполнить транзакционное обновление production базы данных с автоматической заменой старых плейсхолдеров.
