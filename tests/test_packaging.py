"""Упаковка: то, что ломается молча и всплывает только у пользователя."""
import re
import sys
from importlib import resources
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # 3.10: tomllib -- стандартная библиотека только с 3.11
    import tomli as tomllib

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_tiktoken_cache_ships_with_the_package():
    # Если кэш не попал в пакет, счёт токенов уходит в сеть: в офлайне это отказ,
    # и заметит его пользователь, а не мы.
    cache = resources.files("trimitdown") / "tiktoken_cache"
    assert cache.is_dir()
    assert (cache / "9b5ad71b2ce5302211f9c61530b329a4922fc6a4").is_file()

    package_data = tomllib.loads(
        (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )["tool"]["setuptools"]["package-data"]
    # Проверяем декларацию, а не только editable src/: без неё wheel теряет кэш,
    # хотя проверка resources.files() на машине разработчика остаётся зелёной.
    assert "tiktoken_cache/*" in package_data["trimitdown"]


def test_package_does_not_pull_audio_dependencies():
    # Расширения markitdown узкие намеренно: pip/uvx -- канал документов. Из-за
    # этого pydub в пакет не приезжает, и предупреждение об отсутствующем ffmpeg
    # пользователю CLI не показывается вовсе -- проверено установкой в чистый
    # venv. Docker ставит markitdown[all], и там аудио заявлено; расширять
    # extras пакета до [all] означало бы затащить ML-хвост в тот канал, который
    # ценен лёгкостью, и вернуть шум в терминал.
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    markitdown = next(
        requirement
        for requirement in project["project"]["dependencies"]
        if _distribution_key(requirement) == "markitdown"
    )
    extras = markitdown[markitdown.index("[") + 1 : markitdown.index("]")].split(",")

    assert "all" not in extras
    assert "audio-transcription" not in extras


def test_library_dependencies_are_not_exact_pins():
    """Changing one library dependency to ``name==version`` must fail this test.

    The published library deliberately leaves dependency selection to its
    consumer. This examines its declared metadata, not the currently installed
    environment, because an artifact lock must not turn into a library pin.

    Our own engine is exempt, and the exemption is narrow on purpose: the rule
    exists so that our pin cannot collide with the graph of whoever installs
    us, and nobody but us publishes trimitdown-pdf, so there is no graph to
    collide with. Its exact pin is a decision about output quality -- a range
    would raise the engine silently on a rebuild, and the engine is what the
    output is made of -- and raising it is meant to be its own commit.
    """
    from packaging.requirements import Requirement

    ours = {"trimitdown-pdf", "trimitdown_pdf"}
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    exact_pins = []
    for declared in project["project"]["dependencies"]:
        requirement = Requirement(declared)
        if requirement.name in ours:
            continue
        if any(
            specifier.operator in {"==", "==="}
            and not specifier.version.endswith(".*")
            for specifier in requirement.specifier
        ):
            exact_pins.append(declared)

    assert not exact_pins, (
        "library dependencies must remain ranges; exact pins belong in "
        f"requirements.lock: {exact_pins}"
    )


def test_declared_version_is_the_one_that_ships():
    from trimitdown import __version__

    assert __version__ == "0.1.1"


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
        for match in re.finditer(
            r"(?<![\d.])" + re.escape(__version__) + r"(?!\d)", text
        ):
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


def test_changelog_has_a_section_for_the_declared_version():
    """Notes with no description of the changes are notes we have already shipped.

    The pipeline builds release notes from a template that has no place for one,
    so the description was typed in by hand -- twice -- and lost once when the
    draft was recreated. The section in CHANGELOG.md is what the notes are built
    from: a missing section has to stop the build rather than quietly produce
    notes that say nothing.

    Uses the parser the pipeline itself calls rather than a second regex of its
    own: two readers of one file drift apart, and then the suite is green about
    a section the release job cannot find.
    """
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from changelog_section import section

    from trimitdown import __version__

    body = section((REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), __version__)
    assert body, f"CHANGELOG.md has no section describing {__version__}"


def test_api_mode_reports_the_package_version():
    # То, что видит пользователь в UI, обязано быть тем же числом, что публикуется
    # на PyPI, -- в этом весь смысл унификации.
    sys.path.insert(0, str(REPO_ROOT))
    from server_app import VERSION
    from trimitdown import __version__

    assert VERSION == __version__ == "0.1.1"


def test_specs_reference_the_package_cache_path():
    # datas указывали на core/tiktoken_cache, которого больше нет. PyInstaller не
    # падает на отсутствующем datas-пути -- он просто соберёт бандл без кэша.
    for spec in ("main.spec", "windows.spec"):
        text = "\n".join(
            line
            for line in (REPO_ROOT / spec).read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("#")
        )
        assert (
            "('src/trimitdown/tiktoken_cache', 'trimitdown/tiktoken_cache')" in text
        ), f"{spec} lost the package cache datas entry"
        assert re.search(r"pathex\s*=\s*\[[^\]]*['\"]src['\"]", text), (
            f"{spec} no longer puts src on PyInstaller's import path"
        )


def test_compose_bind_mount_sources_exist_in_a_fresh_clone():
    # Образ собирается зелёным, а контейнер не стартует: docker-compose требует,
    # чтобы источник bind mount существовал. Git пустых каталогов не хранит,
    # поэтому свежий клон падал на `archive does not exist` -- поймано на NAS
    # при переустановке, а не тестом.
    compose = (REPO_ROOT / "docker-server" / "docker-compose.yaml").read_text(
        encoding="utf-8"
    )
    sources = re.findall(r"^\s*-\s+(\./[^:]+):", compose, flags=re.MULTILINE)

    assert sources, "в compose не нашлось ни одного bind mount -- проверка ослепла"
    for source in sources:
        path = (REPO_ROOT / "docker-server" / source).resolve()
        assert path.is_dir(), f"{source} нет в репозитории: контейнер не запустится"


def _distribution_key(requirement: str) -> str:
    name = re.split(r"[<>=!~\[]", requirement, maxsplit=1)[0]
    return re.sub(r"[._-]+", "-", name).lower()


def test_docker_installs_the_hashed_lock_before_local_projects():
    """Removing the lock install or ``--no-deps`` must make this test fail.

    The direct runtime requirements must also be present in the lock. The
    release workflow running on each target platform is the proof that the
    universal lock installs there.
    """
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    runtime_dependencies = {
        _distribution_key(requirement)
        for requirement in [
            *project["project"]["dependencies"],
            *project["project"]["optional-dependencies"]["server"],
        ]
    }
    engine = _distribution_key("trimitdown-pdf")
    dockerfile = (REPO_ROOT / "docker-server" / "Dockerfile").read_text(encoding="utf-8")
    instructions = [
        line.strip()
        for line in dockerfile.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    lock = (REPO_ROOT / "requirements.lock").read_text(encoding="utf-8")
    locked_packages = {
        _distribution_key(line)
        for line in lock.splitlines()
        if re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]*==", line)
    }

    assert "COPY requirements.lock ./" in instructions
    assert "RUN pip install --no-cache-dir --require-hashes -r requirements.lock" in instructions
    assert "RUN pip install --no-cache-dir --no-deps -e . ./packages/trimitdown-pdf" in instructions
    assert runtime_dependencies - {engine} <= locked_packages


def test_the_pii_hook_offers_no_bypass():
    """The guard must not hand out the key to itself.

    The hook printed `git commit --no-verify` twice as its own advice, in the
    two places a contributor reads only when they are already blocked and in a
    hurry -- while AGENTS.md forbids the bypass in as many words. Personal data
    reached this repository in public once; the cost of that is not
    hypothetical, and a documented escape hatch is how it happens twice.

    Scanning only the hook is deliberate. A repo-wide scan for the flag would
    fail on AGENTS.md, which has to be able to name the thing it forbids -- the
    same trap as a version scanner that cannot tell a source from a mention.
    """
    hook = (REPO_ROOT / ".githooks" / "pre-commit").read_text(encoding="utf-8")
    assert "--no-verify" not in hook, \
        "the PII hook mentions its own bypass; reword the message instead"

    # Weak on purpose, and the only part that can be: it catches the rule being
    # deleted, not the rule being restated badly.
    rules = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "--no-verify" in rules, \
        "AGENTS.md no longer forbids the bypass -- the prohibition was the point"


def test_the_bundle_cannot_silently_build_cryptography_from_source():
    """The macOS app died for its whole life on a package pip built on the fly.

    cryptography 49.0.0 dropped macOS x86_64 wheels upstream, so on the Intel
    runner pip fetched the sdist and linked it against whatever OpenSSL Homebrew
    happened to have. Two different OpenSSL builds then entered the bundle under
    one basename, PyInstaller kept the older one, and dlopen failed on a symbol
    that only the newer one defines.

    Two independent assertions, because the two failures are different: the
    range going stale, and the source build coming back. Neither is the real
    guarantee -- the smoke launch in CI is, and it goes red if this regresses.
    This one is the early warning that fires in the portable suite, seconds
    after the edit instead of minutes into a macOS build.
    """
    from packaging.requirements import Requirement
    from packaging.version import Version

    text = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
    lines = [line.strip() for line in text.splitlines()
             if line.strip() and not line.strip().startswith("#")]

    def named(line):
        # Path installs (./packages/..., -e .[server]) are not PEP 508 and are
        # not what this test is about.
        try:
            return Requirement(line)
        except Exception:
            return None

    pins = [req for req in map(named, lines)
            if req is not None and req.name == "cryptography"]
    assert pins, "cryptography is unconstrained: the bundle takes whatever resolves"
    # The property, not the text: any release without a macOS x86_64 wheel must
    # be excluded. Asserting the literal "<49" would pass on ">=49".
    assert not pins[0].specifier.contains(Version("49.0.0")), \
        "cryptography 49.0.0 publishes no macOS x86_64 wheel; the Intel bundle " \
        "would be built from source against an OpenSSL nobody chose"

    assert "--only-binary=cryptography" in lines, \
        "without --only-binary a vanished wheel becomes a silent source build " \
        "instead of a failed install"
