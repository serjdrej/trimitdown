import json
import sys
from pathlib import Path


def resolve_app_dir() -> Path:
    if getattr(sys, "frozen", False):
        exe_path = Path(sys.executable).resolve()
        if sys.platform == "darwin" and ".app/Contents/MacOS" in str(exe_path):
            return exe_path.parents[3]  # folder containing the .app bundle
        return exe_path.parent
    return Path(__file__).parent


APP_DIR = resolve_app_dir()
CONFIG_PATH = APP_DIR / "config.json"


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"server_url": None}


def save_config(config: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


def get_server_url() -> str | None:
    return load_config().get("server_url") or None


def ensure_config_exists() -> None:
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
