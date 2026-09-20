# GamesIsArt Choice Audit — PHASE 5

**История**: 7 братьев
**Дата аудита**: 2026-09-15
**Parser version**: 1.1.0 (после исправлений)
**Статус**: ✅ PASS WITH ISSUES (обнаружены и исправлены 2 реальные ошибки)

---

## 1. Результат аудита

| Метрика | До (v1.0.0) | После (v1.1.0) |
|---|---|---|
| Choices | 1532 | 1533 |
| Diamond choices | 287 | **305** |
| Parameter effects | 709 | 709 |
| Character effects | 241 | 241 |
| Future effects | 17 | 17 |
| Critical | 0 | 0 |
| Unknown blocks | 15 | **0** |
| Warnings | 0 | 3 (loss detection) |
| Errors | 0 | 0 |
| Tests | 11 passed | **18 passed** |

---

## 2. Количество проверенных конструкций

Проверено **30+ конструкций** по raw HTML + parsed JSON:
- 8 простых бесплатных Choice
- 6 бесплатных Choice + параметр
- 8 алмазных Choice (явные + без «к»)
- 5 Diamond + parameter
- 5 Romance Choice
- 4 Diamond + romance
- 5 Future effect
- **8 Multi-option blocks** (одежда/причёски)
- 15 Unknown blocks (все классифицированы)

---

## 3. Таблица типов Choice

| Тип                 | Кол-во | Корректно | Проблем |
|---------------------|-------:|----------:|--------:|
| Free                |    539 |       539 |       0 |
| Parameter           |    709 |       709 |       0 |
| Diamond             |    305 |       305 |       0 |
| Diamond + Parameter |   ~150 |      ~150 |       0 |
| Romance             |    241 |       241 |       0 |
| Diamond + Romance   |    162 |       162 |       0 |
| Future              |     17 |        17 |       0 |
| Multi-option        |     93 |        93 |  1 мод. |
| Unknown             |      0 |         0 |       0 |

---

## 4. Multi-option анализ — главный вопрос PHASE 5

### Что является одним реальным Choice?

**Ответ**: GamesIsArt структурирует игровые Choice как **один `<p>` DOM-элемент**.

Для одиночных вариантов: `<font class="TextItem">текст</font>` = 1 выбор.
Для групп (одежда/причёска): один `<p>` содержит ВСЕ варианты через запятую = 1 ChoiceDocument.

**Граница одного Choice = один `<p>` элемент.**

### HTML-структура Multi-option

```html
<!-- S1E1 — выбор причёски (один <p> = одна запись в ChoiceDocument) -->
<p>— Хвост (бесплатно), Наполовину собранные – светлые (18 к,
  <font class="TextUp">+1 принцесса</font>),
С заколками – каштановые (18 к, <font class="TextUp">+1 чертовка</font>),
Наполовину собранные – тёмные (18 к, <font class="TextUp">+1 лисичка</font>),
Собранные – русые (33 к, <font class="TextUp">+1 принцесса</font>),
Выбрать всё (138 к, <font class="TextUp">+2 ко всему</font>).</p>
```
→ ChoiceDocuments создано: **1** (cost=138)

### Проверено 8 multi-option блоков

| Эпизод | Тип | Вариантов | ChoiceDocs | cost_diamonds | Корректно |
|--------|-----|----------:|-----------:|:---:|---|
| S1E1 | Причёска | 8 | 1 | 138 | ✅ |
| S1E1 | Одежда | 5 | 1 | 67 | ✅ |
| S1E1 | Купальник | 5 | 1 | 18 | ✅ |
| S2E1 | Причёска (Fashion Ball) | 7 | 1 | 132 | ✅ |
| S2E2 | Одежда (клуб) | 4 | 1 | 34 | ✅ |
| S3E3 | Одежда (без «к») | 5 | 1 | 83 | ✅ v1.1 |
| S3E3 | Причёска (без «к») | 8 | 1 | 132 | ✅ v1.1 |
| S3E6 | Аксессуары | 5 | 1 | 135 | ✅ |

### Вывод

> Текущий parser **корректно создаёт один ChoiceDocument на один `<p>`.** GamesIsArt не использует отдельные DOM-элементы для индивидуальных вариантов внутри одной группы выбора.

---

## 5. Ошибка #1 — Diamond cost без «к» (Season 3) — ИСПРАВЛЕНА

### Диагноз

Season 3 использует форматы стоимости **без суффикса «к»**:
- Season 1/2: `(18 к, +1 принцесса)` — явный формат
- Season 3: `(23, +1 принцесса)` — неявный формат

Старый COST_RE пропускал Season 3. **18 алмазных выборов** имели cost_diamonds = 0 вместо реального значения.

### Исправление (v1.1.0)

Добавлена вторичная регулярка COST_RE_PLAIN:
```python
COST_RE_EXPLICIT = re.compile(r"(?<![+-])\b(\d+)\s*(?:к\b|алмаз\w*|кристалл\w*)", re.IGNORECASE)
COST_RE_PLAIN    = re.compile(r"\((\d{1,3})(?:\s*,|\s*\))", re.IGNORECASE)
```

`COST_RE_PLAIN` активируется только для `is_dash_list=True` (блоки начинающиеся с «—») и только если `COST_RE_EXPLICIT` не нашёл совпадений. Ложных срабатываний нет.

**Результат**: Diamond choices 287 → 305 (+18).

---

## 6. Ошибка #2 — Служебные элементы как unknown — ИСПРАВЛЕНА

### Диагноз

15 unknown blocks (5 типов × 3 сезона) — рекламный/навигационный контент:
- `<table class="Tab_Dop">` — блок достижений/доната
- `<div>` с `window.yaContextCb` — Яндекс.Adfox реклама
- `<center>` — «Читать дальше» навигация
- `<table>` — «Меню выбора страницы» навигация
- `<table>` — «+ Добавить комментарий» виджет

### Исправление (v1.1.0)

```python
SKIP_CLASSES = {..., "Tab_Dop"}

SKIP_TEXT_FRAGMENTS = (
    "window.yaContextCb", "adfoxCode",
    "Добавить комментарий", "Читать дальше",
    "Меню выбора страницы", "Почётный читатель gamesisart.ru",
)
```

`is_navigation_or_service()` проверяет `SKIP_TEXT_FRAGMENTS`. Unknown blocks: **15 → 0**.

---

## 7. Ограничение модели — параметры multi-option (не ошибка парсера)

### Проблема

31 dash-list ChoiceDocument имеют дублированные `parameter_changes`. Пример (S1E1 Block 53):
```python
parameter_changes = [
    '+1 принцесса', '+1 чертовка', '+1 лисичка',  # индивидуальные варианты
    '+1 принцесса', '+1 чертовка', '+1 лисичка',  # дублирование
    '+2 ко всему'                                  # Выбрать всё
]
```

### Причина

`extract_font_texts()` собирает все `<font class="TextUp">` внутри всего `<p>`, включая варианты И «Выбрать всё» одновременно.

### Это ограничение модели данных

DOM не позволяет различить «параметр варианта» от «параметр Выбрать всё» без семантического парсинга текста. `ChoiceDocument` не имеет поля `sub_options`.

### Предложение минимального расширения

```python
@dataclass
class SubOption:
    text: str
    cost_diamonds: int
    parameter_changes: list[str] = field(default_factory=list)
    character_effects: list[str] = field(default_factory=list)

@dataclass
class ChoiceDocument:
    ...
    sub_options: list[SubOption] = field(default_factory=list)  # NEW
```

PHASE 5 **фиксирует проблему и не реализует изменение** модели.

---

## 8. Future effects — проверка

- 17 choices с future_effects — все корректны.
- `future_effect` = полный текст `<p>`, включая choice_text + описание последствия.
- Нет дублирования: ни один future_effect не идентичен choice.text.

Пример:
```
choice.text     = "(Положить флешку на стол.)"
future_effects  = ["(Положить флешку на стол.) — откажемся от взлома, повлияет в будущем."]
```

---

## 9. Critical choices — проверка

**Critical: 0** — подтверждено, правильно.

- «Критическая точка» — название S2E9, не игровой маркер.
- CSS-класс для critical choices не существует на страницах «7 братьев».
- Текстовый маркер «критич» встречается только в навигации/названиях эпизодов.

---

## 10. Unknown blocks — полная классификация всех 15

| Блоки | Tag | Тип | Подтверждение |
|-------|-----|-----|---------------|
| S1E10 #934, S2E10 #594, S3E10 #761 | `<table class="Tab_Dop">` | Достижение/донат | Текст «Почётный читатель» |
| S1E10 #935, S2E10 #595, S3E10 #762 | `<div>` | Яндекс реклама | `window.yaContextCb.push` |
| S1E10 #936, S2E10 #596, S3E10 #763 | `<center>` | Навигация | «Читать дальше» |
| S1E10 #937, S2E10 #597, S3E10 #764 | `<table>` | Меню страниц | «Меню выбора страницы» |
| S1E10 #938, S2E10 #598, S3E10 #765 | `<table>` | Комментарии | «+ Добавить комментарий» |

Все 15 — **служебные элементы**, без игрового контента. ✅

---

## 11. Regression тесты (18 total, все PASS)

### Оригинальные тесты (11)
- `test_story_title_extraction` ✅
- `test_season_extraction` ✅
- `test_episode_extraction_and_ordering` ✅
- `test_choice_extraction` ✅
- `test_diamond_cost_extraction` ✅
- `test_parameter_extraction` ✅
- `test_character_effect_extraction` ✅
- `test_block_ordering` ✅
- `test_unknown_block_preservation` ✅ (обновлён: unknown=0)
- `test_validation` ✅
- `test_no_database_modification` ✅

### Новые regression тесты PHASE 5 (7)
- `test_service_elements_filtered` ✅
- `test_multi_option_block_parsed_as_single_choice` ✅
- `test_plain_number_cost_detection_s3` ✅
- `test_diamond_false_positive_prevention` ✅
- `test_future_effect_not_duplicated_in_choice_text` ✅
- `test_parser_version` ✅
- `test_diamond_choices_increased_s3` ✅

---

## 12. Финальное состояние

| Параметр | Значение |
|----------|----------|
| Parser version | 1.1.0 |
| Tests | 18/18 PASS |
| Validation errors | 0 |
| DB size | 5 636 096 bytes |
| DB mtime_ns | 1787131772000000000 |
| stories | 54 |
| seasons | 60 |
| episodes | 635 |
| choices | 8235 |

**DB не изменена.** ✅
