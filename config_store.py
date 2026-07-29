import json
import os
import shutil
import sys
from pathlib import Path


def resolve_data_dir() -> Path:
    """Per-user, always writable, and deliberately unrelated to where the app sits.

    The old name for this was APP_DIR and it was computed from sys.executable,
    which is what made the macOS app vanish on double-click: Gatekeeper runs a
    quarantined app from a read-only copy under AppTranslocation, so writing
    config.json "next to the app" raised OSError on a read-only filesystem
    before any window existed. The two directories are different things, and
    the code now says so -- the app's location is _legacy_app_dir, and it is
    read from, never written to.
    """
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "TrimItDown"
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming") / "TrimItDown"
    return Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share") / "TrimItDown"


DATA_DIR = resolve_data_dir()
CONFIG_PATH = DATA_DIR / "config.json"
ARCHIVE_DIR = DATA_DIR / "archive"


def _legacy_app_dir() -> Path:
    """Return the directory used by versions before user data was separated."""
    if getattr(sys, "frozen", False):
        exe_path = Path(sys.executable).resolve()
        if sys.platform == "darwin" and ".app/Contents/MacOS" in str(exe_path):
            return exe_path.parents[3]
        return exe_path.parent
    return Path(__file__).parent


def _copy_legacy_config(legacy_dir: Path) -> None:
    source = legacy_dir / "config.json"
    if CONFIG_PATH.exists() or not source.exists():
        return
    shutil.copy2(source, CONFIG_PATH)


def _copy_legacy_archive(legacy_dir: Path) -> None:
    source = legacy_dir / "archive"
    if not source.is_dir():
        return
    if ARCHIVE_DIR.exists() and any(ARCHIVE_DIR.iterdir()):
        return
    files = [path for path in source.rglob("*") if path.is_file()]
    if not files:
        return
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    for path in files:
        target = ARCHIVE_DIR / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(path, target)


def _migrate_legacy_data() -> None:
    legacy_dir = _legacy_app_dir()
    if legacy_dir == DATA_DIR:
        return
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _copy_legacy_config(legacy_dir)
        _copy_legacy_archive(legacy_dir)
    except (OSError, shutil.Error):
        # The old location can be a read-only App Translocation copy. It is
        # safer to keep the old files in place and start with fresh storage.
        pass


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # Falling back to the offline default silently is how a server
            # address disappears without anyone learning why. Keep the file:
            # it is the only copy of an address the user typed by hand, and a
            # human can read it even when json cannot.
            try:
                CONFIG_PATH.replace(CONFIG_PATH.with_suffix(".json.broken"))
            except OSError:
                pass
        except OSError:
            pass
    return {"server_url": None}


def save_config(config: dict) -> None:
    """Write via a temporary file in the same directory, then replace.

    A direct write truncates first and fills after, so an interrupted save --
    a crash, a full disk, two windows saving at once -- leaves valid JSON
    replaced by half of it. os.replace is atomic within one filesystem, which
    is why the temporary file has to be a sibling rather than somewhere tidy.
    """
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(config, indent=2, ensure_ascii=False)
    temporary = CONFIG_PATH.with_name(CONFIG_PATH.name + f".{os.getpid()}.tmp")
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, CONFIG_PATH)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def get_server_url() -> str | None:
    return load_config().get("server_url") or None


def ensure_config_exists() -> None:
    _migrate_legacy_data()
    if not CONFIG_PATH.exists():
        save_config({
            "_comment_ru": (
                "Адрес твоего сервера (docker-server), например https://192.168.1.100:8002 — "
                "обязательно https, без слэша на конце. Оставь server_url как null, "
                "чтобы приложение всегда работало офлайн."
            ),
            "_comment_en": (
                "Your server's address (docker-server), e.g. https://192.168.1.100:8002 — "
                "https is required, no trailing slash. Leave server_url as null to always "
                "run offline."
            ),
            "server_url": None,
        })
