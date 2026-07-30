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

## 0.1.2

### Что изменилось

Пока ничего, что видно при работе с программой. Этот выпуск набирается, и
раздел будет расти вместе с ним.

- **Надёжность выпуска.** Пакет для `pip` и `uvx` теперь устанавливается и
  запускается до публикации, а не после: раньше файл, попадавший в индекс,
  первым запускал незнакомый человек. Версии зависимостей закреплены, поэтому
  две сборки одного кода больше не собираются из разного.
- **Приложение и пакет конвертируют одним и тем же.** Приложение отставало по
  версии конвертера для документов не-PDF; теперь версии совпадают. Вывод при
  этом не изменился — сверено на семи форматах.

### What changed

Nothing yet that shows while using the program. This release is still
accumulating and the section will grow with it.

- **Release reliability.** The `pip` and `uvx` package is now installed and run
  before publication rather than after: the file reaching the index used to be
  one a stranger ran first. Dependency versions are pinned, so two builds of the
  same code are no longer assembled out of different parts.
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
