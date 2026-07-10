# MarkItDown Desktop — контекст для разработки

Portable-приложение (Windows exe уже готов и работает) для конвертации файлов в Markdown
через [MarkItDown](https://github.com/microsoft/markitdown). При запуске:

1. Проверяет доступность NAS (`https://192.168.1.100:8002`, самоподписанный сертификат).
2. Если NAS доступен — открывает окно прямо на него (общий архив с NAS).
3. Если недоступен — поднимает встроенный локальный FastAPI-сервер на `127.0.0.1` и работает
   офлайн, архив кладёт в папку `archive/` рядом с приложением.

Оболочка окна — [pywebview](https://pywebview.flowrl.com/) (на Windows это WebView2, на macOS —
WKWebView через cocoa-бэкенд). Упаковка в один файл — PyInstaller.

## Структура репозитория

- `main.py` — точка входа: проверка NAS, поднятие локального сервера, создание окна pywebview.
- `server_app.py` — FastAPI-приложение (конвертация, архив). Общее для NAS-режима (это то же
  приложение, что крутится на NAS в Docker) и локального режима.
- `static/` — HTML/CSS/JS фронтенда (drag&drop конвертация, вкладка «Архив», бейдж режима NAS/локально).
- `mac-build/AppIcon.iconset/` — набор PNG для иконки (тот же дизайн «M↓», что и PWA-иконка на iPhone).
- `icon.ico` — та же иконка, но для Windows-сборки.
- `.github/workflows/build-macos.yml` — CI-сборка `.app` для arm64 и x86_64 на macOS-раннерах GitHub.
- `requirements.txt` — общие зависимости (markitdown с ограниченным набором extras: docx, pdf,
  pptx, xlsx, xls, outlook — без audio-transcription/az-*, они тяжёлые и не нужны офлайн).

## Известная проблема (открой это первым)

На собранном через GitHub Actions `.app` (macos-14 arm64 runner) окно приложения открывается
**пустым**. На Windows exe всё работает (NAS-режим и локальный офлайн-режим оба проверены).

Вероятные причины, по убыванию вероятности:

1. **App Transport Security (ATS) блокирует `http://127.0.0.1:<port>`** — WKWebView на macOS по
   умолчанию требует HTTPS; для NAS-режима это не проблема (там HTTPS), но для локального
   фолбэка сервер поднят на голом HTTP. Если ATS блокирует, страница будет пустой без явной
   ошибки в UI. Фикс — добавить в Info.plist собранного `.app` (через PyInstaller `--osx-bundle-identifier`
   и кастомный `Info.plist`, либо через `NSAppTransportSecurity` / `NSAllowsLocalNetworking`)
   разрешение на loopback-соединения.
2. **NAS не был доступен в момент теста** (другая сеть/Wi-Fi) → ушли в локальный офлайн-режим →
   упёрлись в проблему №1.
3. Что-то не собралось внутри `--collect-all` для magika/markitdown на macOS (модель magika для
   определения типов файлов, ML-веса) — тогда упал бы сам сервер при старте, а не отрисовка окна,
   но стоит исключить.
4. macOS Local Network Privacy (разрешение на доступ к локальной сети) могло молча блокировать
   запрос к NAS без явного системного диалога, если оно не задекларировано.

## Как быстро итерировать (без пересборки .app каждый раз)

```bash
git clone https://github.com/serjdrej/markitdown-desktop.git
cd markitdown-desktop
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

Запуск `python main.py` напрямую (не через собранный `.app`) даёт: вывод в консоль,
осмысленные исключения вместо тихого падения, и мгновенную перезагрузку после правок —
так проблему из раздела выше можно будет увидеть в логе за секунды. Для проверки именно
локального (офлайн) режима временно смени `NAS_URL` в `main.py` на заведомо недоступный адрес.

## Пересборка `.app` вручную (если нужно проверить именно собранный бинарник)

```bash
pip install pyinstaller
iconutil -c icns mac-build/AppIcon.iconset -o mac-build/AppIcon.icns
pyinstaller --onefile --windowed --name MarkItDown \
  --icon mac-build/AppIcon.icns \
  --add-data "static:static" \
  --collect-all markitdown --collect-all magika --collect-all mammoth \
  --collect-all pdfminer --collect-all pptx --collect-all openpyxl \
  --collect-all xlrd --collect-all olefile --collect-all bs4 --collect-all lxml \
  main.py
```

Первый запуск собранного `.app` требует правого клика → «Открыть» (приложение не подписано
сертификатом Apple Developer, обычный двойной клик заблокирует Gatekeeper).

## CI

Пуш в `main` автоматически собирает обе архитектуры (`macos-14` → arm64, `macos-15-intel` →
x86_64) и кладёт `.zip` с `.app` в Artifacts запуска. `macos-13` использовать нельзя — лейбл
выведен из эксплуатации GitHub в декабре 2025.

## Известные особенности pywebview, уже учтённые в коде

- Скачивание файлов из архива по умолчанию заблокировано pywebview
  (`webview.settings['ALLOW_DOWNLOADS']`, default `False`) — уже включено в `main.py`.
  На Windows это открывает диалог «Сохранить как», на macOS (см. `platforms/cocoa.py`)
  сохраняет сразу в `~/Downloads` без диалога — это ожидаемо, не баг.
