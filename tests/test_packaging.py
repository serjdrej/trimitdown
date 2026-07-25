"""Упаковка: то, что ломается молча и всплывает только у пользователя."""
import sys
from importlib import resources
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_tiktoken_cache_ships_with_the_package():
    # Если кэш не попал в пакет, счёт токенов уходит в сеть: в офлайне это отказ,
    # и заметит его пользователь, а не мы.
    cache = resources.files("trimitdown") / "tiktoken_cache"
    assert cache.is_dir()
    assert any(cache.iterdir())


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
    ]
    literal = [
        p.relative_to(REPO_ROOT).as_posix()
        for p in sources
        if '"0.1.0"' in p.read_text(encoding="utf-8")
    ]
    assert literal == ["src/trimitdown/__init__.py"], (
        f"номер версии продублирован литералом в {literal}"
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
        assert "core/tiktoken_cache" not in text, f"{spec} still points at the old path"
        assert "tiktoken_cache" in text, f"{spec} lost the tiktoken cache entirely"
