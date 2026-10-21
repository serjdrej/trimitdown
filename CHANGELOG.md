# Changelog

Одна секция на версию. Секция этой версии становится телом заметок к релизу,
поэтому она двуязычная — как и сами заметки. Релиз **отказывается собираться**,
если секции для запрашиваемой версии здесь нет: до этого файла описание
изменений вписывалось руками и один раз потерялось вместе с пересобранным
черновиком.

One section per version. The section for the version being released becomes the
body of the release notes, so it is bilingual — as the notes themselves are. The
release **refuses to build** when this file has no section for the requested
version: before this file the description of the changes was typed in by hand
and was lost once, together with a recreated draft.

## 0.3.1

### Что изменилось

- **Исправления в DOCX, DOC и RTF больше не теряются молча.** anydoc не видит исправлений: из
  DOCX он выбрасывал удалённое и оставлял вставленное, не сказав, что исправления были; из DOC и
  RTF печатал удалённую формулировку рядом со вставленной, как действующую. Замер на синтетических
  документах Word 365 (проверка по `Revisions`, `Comments`, `InlineShapes`). Теперь файл
  проверяется до anydoc, и **документ с неразрешёнными исправлениями отклоняется** с числом вставок
  и удалений в сообщении.
- **`--accept-changes`** (`accept_changes=True` в Python) конвертирует **DOCX** с принятием всех
  исправлений. Для DOC и RTF ключ не помогает — они отклоняются: anydoc не отдаёт у них принятый
  вариант; сохраните файл как DOCX в Word. Ключ отказывается и от тех конструкций DOCX, где текст
  anydoc не равен «принять все» в Word (удалённая строка или ячейка таблицы, удалённый пункт
  списка, удалённый разрыв абзаца).
- **Пропущенное названо.** Колонтитулы с текстом, примечания и изображения anydoc тоже выбрасывал
  молча. Теперь вывод начинается строкой
  `<!-- trimitdown: omitted 2 header/footer parts, 1 comment, 1 image -->` (только ненулевое; с
  `--accept-changes` в ней ещё сколько вставок и удалений принято), те же числа идут в stderr.
- **`--report PATH`** пишет JSON-отчёт (схема 1): формат, исправления, пропущенное; для PDF —
  формат и счётчики страниц по маршрутам. Описание в README.
- **ODT отклоняется.** На документе, сохранённом из Word как ODT, нумерация второго уровня не
  начинается заново (`2.1.` → `2.3.`, `a)` → `c)`), а примечание с автором и датой вклеивается в
  слово. ODS и ODP не затронуты.
- Не изменилось и закреплено тестами: нумерация DOCX/DOC/RTF печатается ровно так, как её
  показывает Word (`1.`, `1.1.`, `1.2.1.`, список с `5.`), сноски и объединённые ячейки целы.
- В опцию `office` добавлен `olefile` (BSD, чистый Python): им читается составной файл DOC.

### What changed

- **Tracked changes in DOCX, DOC and RTF are no longer lost silently.** anydoc cannot see
  revisions: from a DOCX it dropped the deleted wording and kept the inserted one without saying
  revisions had existed; from a DOC or RTF it printed the deleted wording next to the inserted one,
  as if in force. Measured on synthetic Word 365 documents (checked against `Revisions`,
  `Comments`, `InlineShapes`). The file is now inspected before anydoc, and **a document with
  unresolved tracked changes is refused**, with the counts of insertions and deletions in the
  message.
- **`--accept-changes`** (`accept_changes=True` in Python) converts a **DOCX** with every change
  accepted. For DOC and RTF the flag does not help -- they are refused: anydoc has no accepted
  reading of them; save the file as DOCX in Word. The flag also declines the DOCX constructs where
  anydoc's text differs from Word's "accept all" (a deleted table row or cell, a deleted list
  item, a deleted paragraph break).
- **What is left out is named.** anydoc also dropped headers and footers with text, comments and
  images without a word. The output now starts with a line such as
  `<!-- trimitdown: omitted 2 header/footer parts, 1 comment, 1 image -->` (non-zero parts only;
  with `--accept-changes` it also says how many insertions and deletions were accepted), and the
  same counts go to stderr.
- **`--report PATH`** writes a JSON report (schema 1): format, tracked changes, what is left out;
  for a PDF, the format and the page counts per route. Documented in the README.
- **ODT is refused.** On a document saved from Word as ODT, second-level numbering does not
  restart (`2.1.` became `2.3.`, `a)` became `c)`) and a comment with its author and date is
  pasted into a word. ODS and ODP are not affected.
- Unchanged, and now pinned by tests: DOCX/DOC/RTF numbering is printed exactly as Word shows it
  (`1.`, `1.1.`, `1.2.1.`, a list starting at `5.`); footnotes and merged cells are intact.
- `olefile` (BSD, pure Python) joins the `office` extra: it reads the compound file of a DOC.

## 0.3.0

### Что изменилось

- **Опция `office` больше не использует MarkItDown.** Теперь это `firecrawl-anydoc` (версия
  зафиксирована точно, `==0.2.4`) и `markdownify`. Опция ставится на Python 3.15: MarkItDown не
  ставился там из-за цепочки markitdown → magika → onnxruntime (колёс под 3.15 нет), а сам
  markitdown 0.1.8 объявляет `requires-python <3.15`.
- **`.doc` и `.rtf` теперь читаются.** MarkItDown не открывал `.doc` вовсе, а `.rtf` отдавал
  сырой RTF-разметкой (около 125 тысяч токенов, ни одной русской буквы). Замер на двадцати
  файлах: один и тот же русский документ в DOC, DOCX и RTF даёт одну и ту же верную
  таблицу Markdown; объединённая ячейка встаёт на место; кириллица цела.
- **HTML и простой текст по-прежнему работают.** `.html`/`.htm` и файлы, содержимое которых —
  HTML (например, страница, сохранённая как `.pdf`), идут через markdownify без `<script>` и
  `<style>`; `.txt` и `.md` проходят без изменений. Кодировка: BOM, затем `<meta charset>`,
  затем UTF-8; страница без объявления и не в UTF-8 читается как windows-1252 (правило HTML5), а
  простой текст не в UTF-8 отклоняется с понятным сообщением — кодировку мы не угадываем.
- **Документ никогда не уходит в облако.** anydoc умеет отправлять документ на распознавание в
  Firecrawl; мы всегда вызываем его с `ocr="reject"` и без ключей, тест это проверяет.
  Сканированные страницы в офисном файле отклоняются.
- Ошибки anydoc (зашифровано, повреждено, не хватает части, нужен OCR, неизвестный формат)
  приходят как короткое сообщение `ConversionError`, а не трассировка.

### Что убрано (несовместимое изменение)

- **Больше не конвертируются:** письма Outlook (`.msg`), JSON, XML, ZIP, изображения и звук,
  которые принимал MarkItDown. Такие файлы получают отказ с перечнем поддерживаемых форматов.
- **Сервер (`docker-server/`, опция `server`) и десктопное приложение не обновлялись** и не
  выпускаются: их офисный путь с этой версии не работает. Их тесты проходят.

### What changed

- **The `office` extra no longer uses MarkItDown.** It is now `firecrawl-anydoc` (pinned
  exactly, `==0.2.4`) plus `markdownify`. The extra installs on Python 3.15: MarkItDown could
  not be installed there because of the chain markitdown -> magika -> onnxruntime (no cp315
  wheels), and markitdown 0.1.8 itself declares `requires-python <3.15`.
- **`.doc` and `.rtf` are now read.** MarkItDown did not open `.doc` at all and returned raw RTF
  markup for `.rtf` (about 125 thousand tokens, not one Russian letter). A measurement on
  twenty files: the same Russian document as DOC, DOCX and RTF gives the same correct Markdown
  table, a merged cell lands in the right place, Cyrillic is intact.
- **HTML and plain text keep working.** `.html`/`.htm` and files whose content is HTML (a page
  saved as `.pdf`, say) go through markdownify without `<script>` and `<style>`; `.txt` and `.md`
  pass through unchanged. Encoding: BOM, then `<meta charset>`, then UTF-8; an undeclared page
  that is not UTF-8 is read as windows-1252 (the HTML5 rule), while plain text that is not UTF-8
  is refused with a clear message -- no encoding is guessed.
- **A document never leaves the machine.** anydoc can send a document to Firecrawl for
  recognition; we always call it with `ocr="reject"` and no keys, and a test checks that.
  Scanned pages in an office file are refused.
- anydoc's errors (encrypted, damaged, missing part, needs OCR, unknown format) arrive as a
  short `ConversionError` message, not a traceback.

### What was dropped (breaking)

- **No longer converted:** Outlook messages (`.msg`), JSON, XML, ZIP, images and audio, which
  MarkItDown accepted. Such files are refused, with the list of supported formats.
- **The server (`docker-server/`, the `server` extra) and the desktop app were not updated** and
  are not released: their office path does not work from this version on. Their tests pass.

## 0.2.1

### Что изменилось

- **Сборка сохраняет границы страниц.** `trimitdown assemble` в 0.2.0 склеивал страницы и
  выбрасывал `<!-- page N -->`: сослаться на «стр. N» по выверенному документу было нельзя.
  Теперь якорь стоит в начале каждой страницы; `--no-page-anchors` убирает его.
- **`trimitdown convert --page-anchors`** — то же для обычной конвертации PDF. Без ключа вывод
  прежний, побайтно равный pdf-inspector.
- **Пустая страница в `reviewed/` больше не останавливает сборку.** Проверяющий, который пишет
  все страницы, пишет пустую одной строкой заголовка; 0.2.0 отказывал, потому что такая страница
  не отправлялась на сверку. Строка заголовка без текста пропускается, текст для такой страницы
  по-прежнему отказ. Правило сверки говорит об этом прямо.

Обе ошибки нашла сессия сверки сканов arbitrazh-ru на выпущенной 0.2.0.

### What changed

- **Assembly keeps the page boundaries.** In 0.2.0 `trimitdown assemble` joined the pages and
  dropped `<!-- page N -->`, so a reviewed document could not be cited by page. Every page now
  starts with its anchor; `--no-page-anchors` drops it.
- **`trimitdown convert --page-anchors`** does the same for a plain PDF conversion. Without the
  flag the output is unchanged, byte-identical to pdf-inspector.
- **A blank page in `reviewed/` no longer stops assembly.** A reviewer who writes every page
  writes a blank one as its header line alone; 0.2.0 refused it because the page was not sent
  for review. A header without text is skipped; text for such a page is still refused. The
  review rule now says so.

Both were found on the released 0.2.0 by the arbitrazh-ru scan review session.

## 0.2.0

### Что изменилось

Пакет `trimitdown` теперь — весь продукт: извлекатель текста для скиллов и агентов,
консольный и Python. **Вывод PDF меняется** — проверьте, если вы разбираете его программно.

- **Новый маршрут PDF.** PDF читает pdf-inspector: появляются заголовки и таблицы без линий,
  токенов меньше. Таблицы пишутся без пробелов у разделителей (`|A|B|` вместо `| A | B |`).
- **Каждая страница проверяется.** pdf-inspector иногда теряет текст молча — отдаёт пустую
  страницу при живом текстовом слое или кириллицу латиницей. Каждая страница сверяется с
  независимым декодером (pypdf); потерянный текст возвращается из слоя простым текстом.
- **Сомнительные страницы помечены.** Скан без слоя и нечитаемый слой дают строку
  `[trimitdown: page N has no usable text layer (scan|corrupt)]`; слой OCR, который никто не
  выверял, отдаётся с пометкой `[trimitdown: page N: OCR layer, not verified]`. Пустые листы
  пропускаются. Если в документе есть такие страницы, `convert` пишет одну строку-сводку в
  stderr.
- **Сверка сканов агентом.** `trimitdown convert doc.pdf --review-dir out/` готовит каталог:
  картинки страниц, текст-кандидат (слой OCR из PDF или Tesseract, если он установлен),
  манифест и порядок сверки `REVIEW.md`. Пометки сверки по умолчанию русские
  (`[неразборчиво]`, `=== стр. N ===`), `--review-markers en` — английские.
  `trimitdown assemble out/` возвращает выверенные страницы в документ, `trimitdown render`
  пишет картинки страниц для сверки цифр. Сам пакет ничего не распознаёт без Tesseract и
  ничего не сверяет.
- **`python -m trimitdown`** — та же команда, что `trimitdown`, для окружений, где каталог
  скриптов не в PATH; правило сверки называет её для обрезков в полном разрешении.
- **Word, PowerPoint, Excel и Outlook — опция `office`.** `pip install "trimitdown[office]"`.
  Базовая установка — PDF без ML-модели и onnxruntime; ставится и на Python 3.15, где опция пока
  не ставится: у onnxruntime нет колёс под 3.15.
- **Зависимости.** Вместо `trimitdown-pdf` — `pdf-inspector` (закреплён точно), `pypdf`,
  `pypdfium2`, `Pillow`; все под разрешительными лицензиями.
- **Десктопное приложение, Docker-сервер и Scoop больше не выпускаются.** Последние сборки —
  в релизе 0.1.2; код остаётся в репозитории.

### What changed

The `trimitdown` package is now the whole product: a text extractor for skills and agents,
from the command line and from Python. **PDF output changes** — check it if you parse it.

- **A new PDF route.** PDFs are read by pdf-inspector: headings and tables without rules
  appear, and output takes fewer tokens. Tables are written without padding (`|A|B|` rather
  than `| A | B |`).
- **Every page is checked.** pdf-inspector sometimes loses text without saying so — an empty
  page while the text layer is intact, or Cyrillic returned as Latin. Every page is compared
  with an independent decoder (pypdf), and lost text comes back from the layer as plain text.
- **Doubtful pages are marked.** A scan with no layer and an unreadable layer give the line
  `[trimitdown: page N has no usable text layer (scan|corrupt)]`; an OCR layer nobody has
  checked comes with `[trimitdown: page N: OCR layer, not verified]`. Blank sheets are
  skipped. When a document has such pages, `convert` prints one summary line to stderr.
- **Agent review for scans.** `trimitdown convert doc.pdf --review-dir out/` prepares a
  directory: page images, a candidate text (the PDF's OCR layer, or Tesseract if installed),
  a manifest and the review procedure, `REVIEW.md`. Review marks are Russian by default
  (`[неразборчиво]`, `=== стр. N ===`); `--review-markers en` gives English ones.
  `trimitdown assemble out/` puts reviewed pages back, `trimitdown render` writes page images
  for checking digits. Without Tesseract the package recognises nothing, and it never
  reviews anything itself.
- **`python -m trimitdown`** runs the same command as `trimitdown`, for environments whose
  scripts directory is not on PATH; the review rule names it for full-resolution crops.
- **Word, PowerPoint, Excel and Outlook are the `office` extra.** `pip install "trimitdown[office]"`.
  The base install is PDF without an ML model or onnxruntime; it installs on Python 3.15 too,
  where the extra does not yet: onnxruntime has no 3.15 wheels.
- **Dependencies.** `trimitdown-pdf` is replaced by `pdf-inspector` (pinned exactly), `pypdf`,
  `pypdfium2` and `Pillow`, all under permissive licenses.
- **The desktop app, the Docker server and Scoop are no longer released.** Their last builds
  are in the 0.1.2 release; the code stays in the repository.

## 0.1.2

### Что изменилось

Выпуск про надёжность и безопасность. Одно изменение требует действия при
обновлении: Docker-серверу теперь нужен `TRIMITDOWN_TOKEN` — без него он не
обслуживает запросы. Подробности в пункте про замок ниже.

- **Надёжность выпуска.** Пакет для `pip` и `uvx` теперь устанавливается и
  запускается до публикации, а не после: раньше файл, попадавший в индекс,
  первым запускал незнакомый человек. Версии зависимостей закреплены, поэтому
  две сборки одного кода больше не собираются из разного.
- **В серверном интерфейсе видно, что именно пошло не так.** Раньше при отказе,
  который сервер вернул не в JSON, показывалось сообщение разборщика вроде
  «Unexpected token», а настоящая причина терялась.
- **Адрес сервера больше не прячется.** Когда приложение открывает удалённый
  сервер, блок «Адрес сервера» мог не появиться вовсе — то есть поменять адрес
  было нечем именно в том режиме, ради которого туда и заходят.
- **Слишком большой файл отклоняется, не съев память.** Ограничение в 200 МБ
  проверялось после того, как файл целиком оказывался в памяти: двухгигабайтный
  документ сначала занимал два гигабайта и только потом получал отказ, а
  контейнер с лимитом памяти успевал умереть раньше. Для этого не нужен
  злоумышленник — достаточно перетащить не тот файл.
- **У сервера появился замок.** Docker-сервер больше не отдаёт архив всякому, кто
  доберётся до порта: нужен общий секрет из `TRIMITDOWN_TOKEN`, и без него сервер
  отказывается обслуживать запросы. Открыть один раз ссылку с секретом — дальше
  устройство помнит. Это не учётные записи: сервер хранит один архив и
  принадлежит одному человеку. **При обновлении нужно завести `.env`** —
  `docker-server/.env.example` показывает как.
- **Установка на Windows через scoop.** `scoop bucket add trimitdown
  https://github.com/serjdrej/trimitdown`, затем `scoop install trimitdown` —
  ярлык в меню «Пуск» и обновление одной командой. Предупреждения SmartScreen на
  этом пути нет.
- **Приложение и пакет конвертируют одним и тем же.** Приложение отставало по
  версии конвертера для документов не-PDF; теперь версии совпадают. Вывод при
  этом не изменился — сверено на семи форматах.

### What changed

A reliability and security release. One change needs action on upgrade: the
Docker server now requires `TRIMITDOWN_TOKEN` and refuses to serve without it.
See the lock entry below.

- **Release reliability.** The `pip` and `uvx` package is now installed and run
  before publication rather than after: the file reaching the index used to be
  one a stranger ran first. Dependency versions are pinned, so two builds of the
  same code are no longer assembled out of different parts.
- **The server interface says what actually went wrong.** A failure the server
  returned as something other than JSON used to surface as a parser message like
  "Unexpected token", and the real cause was lost.
- **The server address stops hiding.** When the app opens a remote server, the
  Server Address controls could fail to appear at all — leaving no way to change
  the address in the one mode where that is why you opened settings.
- **An oversized file is refused without eating memory first.** The 200 MB limit
  was checked after the whole upload was already in memory, so a two-gigabyte
  document was a two-gigabyte allocation first and a refusal second -- and a
  container with a memory limit died before it could refuse at all. No attacker
  required: dragging the wrong file does it.
- **The server has a lock now.** The Docker server no longer hands the archive to
  whoever reaches the port: it wants the shared secret in `TRIMITDOWN_TOKEN` and
  refuses to serve without one. Open the link carrying it once and the device
  remembers. Not accounts — the server holds one archive and belongs to one
  person. **Upgrading requires creating `.env`**; `docker-server/.env.example`
  shows how.
- **Windows installs through scoop.** `scoop bucket add trimitdown
  https://github.com/serjdrej/trimitdown`, then `scoop install trimitdown` — a
  Start-menu entry and updates in one command. No SmartScreen prompt on this
  path.
- **The app and the package convert with the same thing.** The app trailed the
  package on the converter used for non-PDF documents; the versions now match.
  The output did not change -- checked across seven formats.

## 0.1.1

### Что изменилось

Релиз-исправление. Десктопные приложения до него не запускались.

- **macOS: приложение запускается.** Обе архитектуры. Сборка для Intel падала при
  старте: в неё попадали две несовместимые сборки OpenSSL.
- **macOS: раздача образом.** `.dmg` с перетаскиванием в «Программы» вместо
  архива. Запуск из папки загрузок раньше приводил к тому, что приложение
  закрывалось без окна.
- **Windows: приложение запускается двойным кликом.** Прежняя сборка при запуске
  из проводника завершалась, не показав окна.
- **Данные переехали в профиль пользователя** — `~/Library/Application
  Support/TrimItDown` и `%APPDATA%\TrimItDown`. Настройки и архив прежней версии
  подхватываются автоматически.
- **CLI: `--type pdf` без точки больше не портит таблицы.** Раньше документ молча
  уходил на резервный конвертер, и таблицы разваливались в строки.
- **Не удавшийся счётчик токенов больше не выдаётся за не удавшуюся конверсию.**

### What changed

A fix release. Before it, the desktop apps did not start.

- **macOS: the app starts.** Both architectures. The Intel build died on launch:
  two incompatible OpenSSL builds ended up inside the bundle.
- **macOS: shipped as a disk image.** A `.dmg` with drag-to-Applications instead
  of a zip. Running it from the downloads folder used to make the app close
  without ever showing a window.
- **Windows: the app starts from a double-click.** The previous build exited
  without a window when launched from Explorer.
- **Application data moved into the user profile** — `~/Library/Application
  Support/TrimItDown` and `%APPDATA%\TrimItDown`. Settings and the archive from
  an earlier version are picked up automatically.
- **CLI: `--type pdf` without the dot no longer ruins tables.** The document used
  to fall through to the fallback converter in silence, and tables came back as
  loose lines.
- **A failed token count is no longer reported as a failed conversion.**
