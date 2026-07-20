<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="brand/wordmark_dark.svg">
  <img src="brand/wordmark_light.svg" alt="TrimItDown" width="360">
</picture>

**Любой документ → чистый Markdown, готовый для LLM. На вашем сервере, на всех ваших устройствах.**

*Читать на: [English](README.md) · русском (этот файл)*

[![Latest release](https://img.shields.io/github/v/release/serjdrej/trimitdown)](https://github.com/serjdrej/trimitdown/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/serjdrej/trimitdown/total)](https://github.com/serjdrej/trimitdown/releases)
[![macOS build](https://github.com/serjdrej/trimitdown/actions/workflows/build-macos.yml/badge.svg)](https://github.com/serjdrej/trimitdown/actions/workflows/build-macos.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
![Platforms](https://img.shields.io/badge/platforms-iOS%20PWA%20·%20Windows%20·%20macOS%20·%20Docker-8A6FE8)

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/result-dark.png">
  <img src="docs/images/result-light.png" alt="TrimItDown конвертирует PDF: живой предпросмотр Markdown с настоящей таблицей и счётчиком токенов" width="850">
</picture>

</div>

TrimItDown превращает PDF, Word (docx), PowerPoint (pptx), Excel (xlsx/xls) и письма Outlook
(.msg) в чистый, читаемый Markdown — чтобы вставить в Claude/ChatGPT, Obsidian, Notion или
любую markdown-базу. Работает как приложение для iPhone/iPad (устанавливается прямо из Safari,
без App Store), портативная программа для Windows, приложение для macOS и self-hosted
Docker-сервер — с одним общим архивом конвертаций на всех устройствах.

## PDF-движок

Большинство конвертеров — включая стандартный PDF-путь
[MarkItDown](https://github.com/microsoft/markitdown) — спотыкаются на реальных PDF тремя
измеримыми способами: **слепляют слова**, **выдумывают таблицы из обычного текста** и
**теряют настоящие таблицы с разлиновкой**. На нашем корпусе из 700 реальных файлов
стандартный конвертер нагаллюцинировал таблицы в 49 файлах — 2 442 строки «таблиц», которых
в документах никогда не было.

Поэтому в v1.1.0 мы заменили его собственным движком извлечения:

- **Слова разбиваются по измеренному порогу межсловного интервала** — доля от размера шрифта,
  а не фиксированные пункты, поэтому работает и для мелкого кегля, и для крупных заголовков.
- **Отдельная стадия детекции таблиц** проверяет каждую сетку-кандидата по тому, как реально
  заполнены её ячейки (голосование по заполненности строк), вместо того чтобы верить каждому
  разлинованному прямоугольнику. Диаграммы и декоративные рамки отбрасываются, а их текст
  возвращается в прозу, не пропадая.
- **Настоящие разлинованные таблицы рендерятся честными Markdown-таблицами**, ячейка в ячейку.

Один и тот же документ в стандартном конвертере и в TrimItDown:

**Стандартный конвертер** — фантомная пустая колонка, съехавшие заголовки:

```markdown
| Parameter            | Unit | Before service |     | After service | Limit |
| -------------------- | ---- | -------------- | --- | ------------- | ----- |
| Supply airflow       | m³/h |                | 352 | 398           | ≥ 380 |
| Extract airflow      | m³/h |                | 341 | 402           | ≥ 380 |
| Filter pressure drop | Pa   |                | 184 | 92            | ≤ 150 |
```

**TrimItDown** — таблица такая же, как на странице:

```markdown
| Parameter            | Unit | Before service | After service | Limit |
| -------------------- | ---- | -------------- | ------------- | ----- |
| Supply airflow       | m³/h | 352            | 398           | ≥ 380 |
| Extract airflow      | m³/h | 341            | 402           | ≥ 380 |
| Filter pressure drop | Pa   | 184            | 92            | ≤ 150 |
```

Коротко: мы добавляем стадию *валидации* таблиц, которая есть в классическом конвейере
tabula-java и которой не хватает Python-экстракторам, — в виде голосования по заполненности
ячеек на разлинованных сетках pdfplumber, с фолбэком в прозу для каждой отдельной сетки. Без
ML-моделей, без облака, достаточно компактно, чтобы уместиться в портативный бинарник. Все
остальные форматы по-прежнему идут через MarkItDown.

## Зачем это нужно

- **Сделано под работу с LLM.** На выходе чистый Markdown, живой предпросмотр и счётчик
  токенов — видно, сколько документ «стоит», ещё до вставки в контекст модели.
- **Файлы не покидают вашу инфраструктуру.** Конвертация — на вашем собственном сервере
  (домашний NAS, VPS) или полностью офлайн на компьютере. Без стороннего SaaS, без платы
  за страницы.
- **Один архив на все устройства.** Конвертировали на телефоне — результат уже на компьютере,
  и наоборот. С поиском, батч-конвертацией и выгрузкой в ZIP.
- **Настоящее приложение на каждой платформе.** iPhone PWA из Safari (без App Store),
  портативный exe для Windows, приложение для macOS. Интерфейс на русском и английском,
  светлая/тёмная тема, две цветовые схемы.

## Как получить

| Платформа | Как |
|---|---|
| **Windows** | Скачать `TrimItDown-windows-x64.exe` из [Releases](https://github.com/serjdrej/trimitdown/releases/latest) — portable, без установки |
| **macOS** (Apple Silicon / Intel) | Скачать подходящий `.zip` из [Releases](https://github.com/serjdrej/trimitdown/releases/latest), распаковать, правый клик → «Открыть» |
| **iPhone / iPad** | Отдаётся вашим Docker-сервером — открыть в Safari → «Поделиться» → *На экран «Домой»* |
| **Docker-сервер** | См. [Свой сервер](#свой-сервер) ниже |

Десктоп-приложения из коробки работают полностью офлайн. Чтобы получить общий архив, укажите
адрес сервера на экране **Настройки**.

## Свой сервер

Docker-сервер — источник истины: он конвертирует, хранит общий архив и отдаёт PWA для iPhone.

```bash
git clone https://github.com/serjdrej/trimitdown.git
cd trimitdown/docker-server
# один раз: сгенерировать самоподписанный HTTPS-сертификат (готовая команда в docker-server/README.md)
docker-compose up -d --build
```

Затем открыть `https://ВАШ_СЕРВЕР:8002`. Полная инструкция — генерация сертификата, доверие
к нему на iOS/Windows/macOS и API — в [`docker-server/README.md`](docker-server/README.md).

## Скриншоты

| Архив, общий между устройствами | Настройки |
|---|---|
| ![Архив с поиском](docs/images/archive-light.png) | ![Экран настроек](docs/images/settings-dark.png) |

| Тема «океан», светлая | Тема «океан», тёмная |
|---|---|
| ![Океан, светлая](docs/images/home-ocean-light.png) | ![Океан, тёмная](docs/images/home-ocean-dark.png) |

<!-- TODO: сюда — реальные скриншоты iPhone (PWA на экране «Домой», конвертация через «Поделиться») -->

## Как это работает

- **Docker-сервер** — сервис на FastAPI с HTTPS; архив хранится на сервере. Тот же сервис
  отдаёт PWA для iPhone.
- **Приложения для Windows/macOS** при старте проверяют доступность сервера: доступен —
  открываются прямо на нём (общий архив); нет — поднимают встроенный локальный сервер и
  работают полностью офлайн. Оболочка — [pywebview](https://pywebview.flowrl.com/)
  (WebView2 / WKWebView), упаковка — PyInstaller.
- **Конвертация:** PDF идут через собственный движок TrimItDown
  ([`core/pdf_extract.py`](core/pdf_extract.py), построен на pdfplumber); все остальные
  форматы — через [MarkItDown](https://github.com/microsoft/markitdown) от Microsoft.

## Структура репозитория

- [`core/`](core/) — общая логика конвертации и собственный PDF-движок
- [`docker-server/`](docker-server/) — self-hosted сервис + PWA для iPhone
- [`static/`](static/), [`main.py`](main.py), [`server_app.py`](server_app.py) — десктоп-приложения (UI, точка входа, офлайн-режим)
- [`tests/`](tests/) — юнит-тесты + размеченный корпус для стадии детекции таблиц

## Участие в разработке

Баг-репорты и PR приветствуются — см. [CONTRIBUTING.md](CONTRIBUTING.md).
В [DEVELOPMENT.md](DEVELOPMENT.md) — настройка dev-окружения и устройство десктоп-сборки.

## Ограничения

- Самоподписанный HTTPS-сертификат сервера нужно один раз вручную одобрить на каждом
  устройстве (iOS: профиль + полное доверие; Windows: импорт в `CurrentUser\Root`;
  macOS: Keychain).
- Бинарники не подписаны сертификатом разработчика (ни Apple, ни Microsoft) — при первом
  запуске нужно одно подтверждение (macOS: правый клик → «Открыть»; Windows: SmartScreen).

## Лицензия и благодарности

Код — под лицензией [MIT](LICENSE). Конвертация не-PDF форматов — на
[MarkItDown](https://github.com/microsoft/markitdown) (Microsoft, MIT); лицензии встроенных
сторонних компонентов перечислены в [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
