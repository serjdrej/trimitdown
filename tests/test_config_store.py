import importlib
import json
import sys
from pathlib import Path

import config_store


def _reload(monkeypatch, platform, home, executable, *, appdata=None, xdg=None):
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(sys, "executable", str(executable))
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("HOME", str(home))
    if appdata is None:
        monkeypatch.delenv("APPDATA", raising=False)
    else:
        monkeypatch.setenv("APPDATA", str(appdata))
    if xdg is None:
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    else:
        monkeypatch.setenv("XDG_DATA_HOME", str(xdg))
    return importlib.reload(config_store)


def test_data_directory_uses_user_location_not_executable(monkeypatch, tmp_path):
    home = tmp_path / "home"
    executable_a = tmp_path / "Downloads" / "TrimItDown.app" / "Contents" / "MacOS" / "TrimItDown"
    executable_b = tmp_path / "Applications" / "TrimItDown.app" / "Contents" / "MacOS" / "TrimItDown"

    store = _reload(monkeypatch, "darwin", home, executable_a)
    first = store.resolve_data_dir()
    monkeypatch.setattr(sys, "executable", str(executable_b))
    assert store.resolve_data_dir() == first
    assert first == home / "Library" / "Application Support" / "TrimItDown"


def test_data_directory_uses_platform_user_data_rules(monkeypatch, tmp_path):
    """Each platform's own convention, and the fallback when the variable is unset.

    A loop rather than the usual pytest decorator: that decorator's line reads
    as an email address to the PII hook, and a false positive there is fixed by
    rewording the line, never by bypassing the guard.
    """
    # Roots come from tmp_path rather than literal absolute paths: a written-out
    # Windows profile path matches the PII guard's user-path shape, and the rule
    # for a false positive is to reword the line, not to weaken the guard.
    cases = [
        ("win32", str(tmp_path / "roaming"), None),
        ("linux", None, str(tmp_path / "custom-data")),
        ("linux", None, None),
    ]
    for platform, appdata, xdg in cases:
        store = _reload(monkeypatch, platform, tmp_path / "home", tmp_path / "app",
                        appdata=appdata, xdg=xdg)
        if appdata:
            expected_root = Path(appdata)
        elif xdg:
            expected_root = Path(xdg)
        else:
            expected_root = tmp_path / "home" / ".local" / "share"
        assert store.resolve_data_dir() == expected_root / "TrimItDown", \
            f"{platform} with APPDATA={appdata!r} XDG_DATA_HOME={xdg!r}"


def test_legacy_config_and_archive_are_migrated(monkeypatch, tmp_path):
    store = _reload(monkeypatch, "darwin", tmp_path / "home", tmp_path / "app")
    destination = tmp_path / "user-data"
    legacy = tmp_path / "translocated-app"
    legacy.mkdir()
    (legacy / "config.json").write_text(json.dumps({"server_url": "https://old.example"}), encoding="utf-8")
    (legacy / "archive").mkdir()
    (legacy / "archive" / "old.md").write_text("# old", encoding="utf-8")
    monkeypatch.setattr(store, "DATA_DIR", destination)
    monkeypatch.setattr(store, "CONFIG_PATH", destination / "config.json")
    monkeypatch.setattr(store, "ARCHIVE_DIR", destination / "archive")
    monkeypatch.setattr(store, "_legacy_app_dir", lambda: legacy)

    store.ensure_config_exists()

    assert store.load_config()["server_url"] == "https://old.example"
    assert (destination / "archive" / "old.md").read_text(encoding="utf-8") == "# old"


def test_unreadable_legacy_data_does_not_block_start(monkeypatch, tmp_path):
    store = _reload(monkeypatch, "darwin", tmp_path / "home", tmp_path / "app")
    destination = tmp_path / "user-data"
    legacy = tmp_path / "old-app"
    legacy.mkdir()
    (legacy / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(store, "DATA_DIR", destination)
    monkeypatch.setattr(store, "CONFIG_PATH", destination / "config.json")
    monkeypatch.setattr(store, "ARCHIVE_DIR", destination / "archive")
    monkeypatch.setattr(store, "_legacy_app_dir", lambda: legacy)

    def fail_copy(*args, **kwargs):
        raise OSError("read-only translocated application")

    monkeypatch.setattr(store.shutil, "copy2", fail_copy)
    store.ensure_config_exists()
    assert store.CONFIG_PATH.exists()
