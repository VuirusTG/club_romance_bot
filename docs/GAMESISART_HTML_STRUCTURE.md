# GamesIsArt HTML Structure: 7 братьев

Дата исследования: 2026-08-17.

Страница:

```text
https://gamesisart.ru/guide/Romance_Club_Prohozhdenie_Seven.html
```

PHASE 4 scope: исследована только тестовая история `7 братьев`. База данных не изменялась.

## Общая структура

Страница GamesIsArt является обычным HTML-документом с основным контентом внутри:

```text
div#general_container_980
  div#content_980
    table#content_table
      td.main_table_td
```

Правая колонка, меню, footer, share-виджеты и служебные элементы находятся рядом с основным контентом и не должны попадать в parsed guide.

## Story

Название истории находится в:

```html
<h1 class="TextTopOn">Клуб романтики. 7 братьев</h1>
```

Для source title parser берёт фактический текст `7 братьев`, удаляя только служебный префикс `Клуб романтики.`. Никакой display-title normalization и старый replacements dictionary не используются.

## Canonical URL

На странице есть canonical:

```html
<link rel="canonical" href="https://gamesisart.ru/guide/Romance_Club_Prohozhdenie_Seven.html">
```

Этот URL используется как canonical для `source_key`.

## Seasons

История разбита на отдельные страницы по сезонам:

```html
Romance_Club_Prohozhdenie_Seven.html
Romance_Club_Prohozhdenie_Seven_2.html
Romance_Club_Prohozhdenie_Seven_3.html
```

Ссылки на сезоны находятся в навигационных блоках страницы. Parser использует только URL, относящиеся к этой же истории:

```text
Romance_Club_Prohozhdenie_Seven(?:_\d+)?.html
```

Каждая season-page имеет `h2.TextTop`:

```html
<h2 class="TextTop">Прохождение истории "7 братьев". Сезон 1</h2>
```

Номер сезона извлекается из фактического текста `Сезон N`.

## Episodes

Серии обозначены как:

```html
<h3 class="TextH2">
  1.1. К лучшему или к худшему
  <br>
  <font class="GreyText">Клуб романтики</font>
</h3>
```

Фактическая структура:

- tag: `h3`;
- class: `TextH2`;
- direct text до `<br>` содержит `season.episode. title`;
- `font.GreyText` содержит SEO/служебное описание и не является названием серии.

Parser берёт direct text `h3.text`, а не полный `text_content()`, чтобы не склеивать title с GreyText.

## Episode Content

После каждого `h3.TextH2` идут sibling-элементы внутри `td#main_table_td`.

Содержимое серии продолжается до следующего `h3.TextH2`.

Основные content tags:

- `<p>`;
- `<div>`;
- `<table>`;
- `<ul>/<ol>`;
- иногда `<b>` внутри `<p>`.

Служебные и пустые элементы:

- `<br>`;
- `<hr>`;
- пустые `<center>`;
- рекламные/видео blocks без значимого текста;
- меню/footer/share widgets.

Parser сохраняет порядок sibling-элементов как `Block.order`.

## Choices

Обычный выбор представлен так:

```html
<p>
  <font class="TextItem">Джентльмены. Не могли бы вы помочь мне с багажом?</font>
  <font class="TextUp">+1 принцесса</font>.
</p>
```

DOM-признаки choice:

- `<p>` содержит `font.TextItem`;
- `TextItem` содержит текст варианта выбора;
- `TextUp`, `TextDown`, `TextDownLink` содержат параметрические эффекты;
- `TextLove` содержит relationship effects.

Parser создаёт `Block(type="choice")` и `ChoiceDocument` только когда видит реальные DOM-признаки выбора.

## Diamond Cost

Стоимость может быть внутри `TextItem` или общего текста `<p>`:

```html
<font class="TextItem">(Помочь Лилиан.) (8 к)</font>
```

Также встречаются строки группового выбора:

```html
<p>— Кашемир (18 к, <font class="TextUp">+1 лисичка</font>), ...</p>
```

Parser извлекает цену только из контекста:

```text
N к
N алмазов
N кристаллов
```

Числа в параметрах (`+1`, `+2`) не считаются стоимостью.

## Parameters

Параметры явно размечены классами:

```html
<font class="TextUp">+1 принцесса</font>
<font class="TextDownLink">...</font>
```

Parser сохраняет их в `parameter_changes` только при наличии таких DOM-классов.

## Character Effects

Отношения явно размечены:

```html
<font class="TextLove">+ отношения с Тристаном</font>
```

Parser сохраняет такой текст в `character_effects`.

Если персонаж не выделен отдельно, parser не угадывает его, а сохраняет raw effect text.

## Future Effects

Future/effect blocks встречаются в обычных `<p>`:

```text
Выбор изменит сюжет, может повлиять на отношения...
Вы больше не сможете развивать...
```

Parser классифицирует такие блоки как `effect` и сохраняет текст в block. Для choice future effects используются только явные marker phrases в тексте choice.

## Unknown Elements

Если content element внутри episode section имеет значимый текст, но parser не распознал его как `text`, `choice`, `effect`, `requirement`, `heading` или `note`, он сохраняется как:

```json
{
  "type": "unknown",
  "text": "...",
  "metadata": {
    "tag": "...",
    "classes": [...]
  }
}
```

Это нужно для loss detection и последующей доработки parser.

## Loss Detection

Parser считает значимые content-elements в episode sections и количество represented blocks.

Если значимый элемент не представлен в `StoryDocument`, создаётся warning:

```text
Parser loss warning for <url>: N source elements were not represented.
```

Пустые служебные элементы, `<br>`, `<hr>`, scripts/styles и элементы без текста не считаются потерей.

## DOM Rules Used

Основные правила parser:

- main container: `td.main_table_td` with fallback to `//*[@id="main_table_td"]` and then `<body>`;
- story title: `//h1[contains(@class, "TextTopOn")]`;
- season heading: `//h2[contains(@class, "TextTop")]`;
- episode heading: child `h3.TextH2` внутри main container;
- episode title: direct text of `h3` before `<br>`;
- choice: element with descendant `font.TextItem`;
- parameter effect: descendant `font.TextUp`, `font.TextDown`, `font.TextDownLink`;
- character effect: descendant `font.TextLove`;
- source page links for the same story: `Romance_Club_Prohozhdenie_Seven(?:_\d+)?.html`.

Parser не зависит от одного случайного selector: для контейнера есть fallback на `<body>`, а для блоков используется DOM order и semantic classes together.
