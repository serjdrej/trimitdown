"""Упаковка: то, что ломается молча и всплывает только у пользователя."""
import re
import shlex
import sys
import tomllib
from importlib import resources
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_tiktoken_cache_ships_with_the_package():
    # Если кэш не попал в пакет, счёт токенов уходит в сеть: в офлайне это отказ,
    # и заметит его пользователь, а не мы.
    cache = resources.files("trimitdown") / "tiktoken_cache"
    assert cache.is_dir()
    assert any(cache.iterdir())

    package_data = tomllib.loads(
        (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )["tool"]["setuptools"]["package-data"]
    # Проверяем декларацию, а не только editable src/: без неё wheel теряет кэш,
    # хотя проверка resources.files() на машине разработчика остаётся зелёной.
    assert "tiktoken_cache/*" in package_data["trimitdown"]


def test_declared_version_is_the_one_that_ships():
    from trimitdown import __version__

    assert __version__ == "0.1.0"


def test_version_has_exactly_one_source():
    # Раньше версия жила в двух местах и они были обязаны совпадать, ничем к
    # этому не принуждаясь. Второй источник удалён; тест не даёт ему вернуться.
    assert not (REPO_ROOT / "core" / "version.py").exists()

    sources = list((REPO_ROOT / "src").rglob("*.py")) + [
        REPO_ROOT / "server_app.py",
        REPO_ROOT / "docker-server" / "app.py",
        REPO_ROOT / "pyproject.toml",
        *REPO_ROOT.glob(".github/ISSUE_TEMPLATE/*.yml"),
        *REPO_ROOT.glob(".github/workflows/*.yml"),
    ]
    from trimitdown import __version__

    version_literals = []
    for path in sources:
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(re.escape(__version__) + r"(?!\d)", text):
            before = text[: match.start()].rsplit("\n", 1)[-1]
            # Литерал в спецификаторе зависимости -- ограничение на чужой пакет, а
            # не второй источник нашей версии, и отличается он контекстом: перед
            # версией зависимости всегда стоит оператор сравнения. Первая версия
            # этой проверки исключала одну конкретную строку с пином движка по
            # шаблону и поэтому сработала на version pin pdfplumber в workflow --
            # правило должно быть общим, иначе каждый новый пин ломает тест.
            if re.search(r"[<>=!~]=?\s*$", before):
                continue
            version_literals.append(
                f"{path.relative_to(REPO_ROOT).as_posix()}:{match.group()}"
            )
    assert version_literals == ["src/trimitdown/__init__.py:" + __version__], (
        f"номер версии продублирован литералом в {version_literals}"
    )


def test_api_mode_reports_the_package_version():
    # То, что видит пользователь в UI, обязано быть тем же числом, что публикуется
    # на PyPI, -- в этом весь смысл унификации.
    sys.path.insert(0, str(REPO_ROOT))
    from server_app import VERSION
    from trimitdown import __version__

    assert VERSION == __version__ == "0.1.0"


def test_specs_reference_the_package_cache_path():
    # datas указывали на core/tiktoken_cache, которого больше нет. PyInstaller не
    # падает на отсутствующем datas-пути -- он просто соберёт бандл без кэша.
    for spec in ("main.spec", "windows.spec"):
        text = (REPO_ROOT / spec).read_text(encoding="utf-8")
        assert (
            "('src/trimitdown/tiktoken_cache', 'trimitdown/tiktoken_cache')" in text
        ), f"{spec} lost the package cache datas entry"
        assert re.search(r"pathex\s*=\s*\[[^\]]*['\"]src['\"]", text), (
            f"{spec} no longer puts src on PyInstaller's import path"
        )


def _distribution_key(requirement: str) -> str:
    name = re.split(r"[<>=!~\[]", requirement, maxsplit=1)[0]
    return re.sub(r"[._-]+", "-", name).lower()


def test_docker_warms_every_runtime_package_dependency():
    # Эта проверка существует, потому что --no-deps даёт зелёную сборку образа,
    # а пропущенная прогретая зависимость проявляется только при старте контейнера.
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    runtime_dependencies = {
        _distribution_key(requirement)
        for requirement in project["project"]["dependencies"]
    }
    engine = _distribution_key("trimitdown-pdf")

    dockerfile = (REPO_ROOT / "docker-server" / "Dockerfile").read_text(encoding="utf-8")
    warmup_line = next(
        line for line in dockerfile.splitlines() if line.startswith("RUN pip install ")
    )
    warmup_packages = {
        _distribution_key(argument)
        for argument in shlex.split(warmup_line)
        if argument not in {"RUN", "pip", "install"} and not argument.startswith("-")
    }

    assert "pip install --no-cache-dir ./packages/trimitdown-pdf" in dockerfile
    assert runtime_dependencies - {engine} <= warmup_packages
