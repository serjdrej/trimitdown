<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="brand/wordmark_dark.svg">
  <img src="brand/wordmark_light.svg" alt="TrimItDown" width="360">
</picture>

**Документы → Markdown для LLM. PDF проверяется постранично, сканы уходят на сверку.**

*Читать на: [English](README.md) · русском (этот файл)*

[![PyPI](https://img.shields.io/pypi/v/trimitdown?label=trimitdown&color=3775A9)](https://pypi.org/project/trimitdown/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

</div>

`trimitdown` превращает PDF, Word (docx), PowerPoint (pptx), Excel (xlsx/xls) и письма Outlook
(.msg) в Markdown, который вставляют в LLM или читает агент. Цель — меньше токенов при
сохранённой информации: настоящая таблица становится таблицей Markdown, а страница, тексту
которой нельзя верить, так и помечается, а не выдаётся за текст.

Это консольная программа и библиотека Python, работает без сети. С 0.2.0 пакет — весь продукт;
о десктопном приложении и Docker-сервере — в разделе [Прежние выпуски](#прежние-выпуски).

## Установка

Нужен Python 3.10+.

```bash
uv tool install trimitdown     # или: pipx install trimitdown
uvx trimitdown convert report.pdf   # один раз, без установки
```

Обычный `pip install` в системный Python на многих дистрибутивах и в Homebrew отклоняется
(PEP 668); команды выше ставят пакет в изолированное окружение. В своём виртуальном окружении
`pip install trimitdown` работает.

## Конвертация

```bash
trimitdown convert report.pdf -o report.md
trimitdown convert - --type pdf < report.pdf     # из потока
```

Без `-o` Markdown идёт в стандартный вывод.

```python
from trimitdown.convert import convert_path

result = convert_path("report.pdf")
result.text            # Markdown
result.pages           # для PDF: каким путём прошла каждая страница и почему
result.tokens_after    # токены cl100k
```

Форматы, кроме PDF, идут через [MarkItDown](https://github.com/microsoft/markitdown) от Microsoft.

## Как обрабатывается PDF

PDF читает [pdf-inspector](https://pypi.org/project/pdf-inspector/): в наших замерах он лучше
всех по структуре (заголовки, таблицы с линиями и без) и по токенам. Но он же теряет текст молча:
целые страницы возвращаются пустыми при живом текстовом слое, а на некоторых кириллица приходит
латиницей без всякого флага. Поэтому каждая страница сверяется с независимым декодером
([pypdf](https://pypi.org/project/pypdf/)) и идёт одним из пяти путей:

| Путь | Когда | Что страница даёт в документ |
|---|---|---|
| `accept` | pdf-inspector прочёл страницу | его Markdown без изменений |
| `substitute` | pdf-inspector потерял текст, который в слое есть | текстовый слой простым текстом |
| `scan` | слоя нет, или под картинкой страницы лежит слой OCR | пометку — или слой OCR с пометкой «не выверен» |
| `corrupt` | слой есть, но у всех декодеров мусор | пометку |
| `blank` | слоя нет, и на странице ничего нет | ничего |

Потеря считается по письменностям (кириллица, латиница, греческий, CJK…), поэтому страница,
где один алфавит молча подменён другим, ловится, хотя число букв не изменилось.

Пометки — одна строка на страницу:

```
[trimitdown: page 12 has no usable text layer (scan)]
[trimitdown: page 14: OCR layer, not verified]
```

Если хоть одна страница пришла не от pdf-inspector, `convert` печатает в stderr одну строку,
например `7 pages: 1 accept, 2 substitute, 2 scan, 1 corrupt, 1 blank; 3 need review`. Чистый
документ конвертируется молча.

## Сверка: сканы и нечитаемые страницы

Сам `trimitdown` не распознаёт и ничего не сверяет. Он готовит страницы, на которые нужно
посмотреть, для агента (или человека), который это сделает:

```bash
trimitdown convert scan.pdf --review-dir out/
```

пишет

| | |
|---|---|
| `out/document.md` | документ, перед каждой страницей якорь `<!-- page N -->` |
| `out/manifest.json` | все страницы: путь и причины, картинка, кандидат, статус OCR, метрики |
| `out/REVIEW.md` | порядок сверки: сначала OCR, потом сравнить с картинкой и править только расхождения |
| `out/pages/pNNNN.png` | картинка каждой страницы на сверку (исходный скан, если он во всю страницу, иначе рендер 300 dpi) |
| `out/candidates/pNNNN.txt` | текст, с которого начинать: слой OCR из самого PDF или свежий вывод Tesseract; пустой, если нечего |
| `out/reviewed/` | сюда пишет тот, кто сверяет |

[Tesseract](https://github.com/tesseract-ocr/tesseract) необязателен и ставится отдельно. Он
ищется в `--tesseract`, `TRIMITDOWN_TESSERACT`, `PATH`, затем в обычных местах установки
(установщик под Windows может не прописать себя в `PATH`). По умолчанию — измеренная
конфигурация (`-l rus --psm 3`, ориентация через `--psm 0`), меняется ключами `--ocr-lang` и
`--tessdata-dir`. Без Tesseract или без языковых данных страницы всё равно уходят на сверку, с
пустым кандидатом, а манифест и stderr говорят почему.

Ещё ключи: `--ocr-fresh` (распознать и сканы, у которых уже есть слой OCR), `--no-ocr`,
`--review-substitute` (отправить на сверку и страницы `substitute`), `--review-markers ru|en`
(какими пометками пользуется сверка: по умолчанию `[неразборчиво]`, `=== стр. N ===`, либо
`[illegible]`, `=== page N ===`).

Когда сверка сделана:

```bash
trimitdown assemble out/ -o report.md
```

ставит каждую выверенную страницу на место её пометки. Читает `reviewed/doc.txt` со строкой
`=== стр. N ===` (или `=== page N ===`) перед каждой страницей либо файлы `reviewed/pNNNN.txt`
по страницам и отказывает, если страница выверена дважды, если такой страницы нет или если она
не отправлялась на сверку.

Читаемый текстовый слой ещё не доказывает, что цифры в нём верны. Для страниц, не ушедших на
сверку, `trimitdown render report.pdf --pages 5,7 -o img/` пишет картинки страниц, чтобы сверить
с ними.

Из Python: `trimitdown.review.prepare_review`, `assemble` и `render_pages`.

## Ограничения

- Своего OCR нет, и сверку программа не выполняет: для сканов нужны Tesseract и тот, кто сверяет.
- Потеря одних только латинских букв не проверяется. На бенчмарке из 200 документов проверка
  латиницы чаще заменяла хороший структурированный Markdown (заголовки) простым текстом, чем
  возвращала текст, поэтому она выключена (`GATE_LATIN` в `text_metrics.py`). Кириллица,
  подменённая латиницей, по-прежнему ловится: это потеря кириллицы.
- Текст под картинкой (слой OCR другой формы или текст, который наложение должно было скрыть)
  принимается как текст; манифест сверки записывает, какая доля страницы под картинками.
- Детектор мусора для пути `corrupt` работает на осторожных порогах, на реальных документах
  ещё не измеренных.
- PDF с паролем не открываются.

## Прежние выпуски

До 0.1.2 TrimItDown выпускал ещё приложение для Windows и macOS, self-hosted Docker-сервер с
PWA для iPhone и манифест Scoop. Они больше не выпускаются. Последние сборки приложены к
[v0.1.2](https://github.com/serjdrej/trimitdown/releases/tag/v0.1.2), бакет Scoop в этом
репозитории остаётся на нём, а код остаётся в дереве — см. [DEVELOPMENT.md](DEVELOPMENT.md).
Их PDF-движок `trimitdown-pdf` описан в [docs/pdf-engine.md](docs/pdf-engine.md); пакет от него
больше не зависит.

## Устройство репозитория

- [`src/trimitdown/`](src/trimitdown/) — пакет: конвертация, маршрут PDF, сверка
- [`tests/`](tests/) — переносимый набор тестов на синтетических PDF, собранных в самих тестах
- [`packages/trimitdown-pdf/`](packages/trimitdown-pdf/), [`core/`](core/),
  [`docker-server/`](docker-server/), [`static/`](static/), [`main.py`](main.py) — прежние
  десктопное и серверное приложения и их движок

## Участие

Сообщения об ошибках и PR приветствуются — см. [CONTRIBUTING.md](CONTRIBUTING.md) и
[DEVELOPMENT.md](DEVELOPMENT.md).

## Лицензия и благодарности

Код — [MIT](LICENSE). PDF читают [pdf-inspector](https://pypi.org/project/pdf-inspector/) (MIT),
[pypdf](https://pypi.org/project/pypdf/) (BSD) и
[pypdfium2](https://pypi.org/project/pypdfium2/) (Apache-2.0 / BSD, с PDFium); остальные
форматы — [MarkItDown](https://github.com/microsoft/markitdown) (Microsoft, MIT). См.
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
