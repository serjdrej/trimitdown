import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

import config_store
import desktop_api


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config_store, "CONFIG_PATH", tmp_path / "config.json")


def test_save_server_url_persists_value(isolated_config):
    api = desktop_api.Api()
    api.save_server_url("https://192.168.1.10:8002")
    assert api.get_server_url() == "https://192.168.1.10:8002"


def test_save_server_url_persists_across_a_new_api_instance(isolated_config):
    # Read-after-write on the same Api object only proves in-memory state
    # round-trips -- an Api that just kept the URL on self would pass that
    # check without ever touching disk. The setting exists so it survives an
    # app restart, which recreates the Api object from scratch, so a second,
    # fresh instance (and the config file itself) is the only way to prove
    # the write actually reached storage.
    api = desktop_api.Api()
    api.save_server_url("https://192.168.1.10:8002")

    restarted = desktop_api.Api()
    assert restarted.get_server_url() == "https://192.168.1.10:8002"
    assert config_store.load_config()["server_url"] == "https://192.168.1.10:8002"


def test_save_server_url_empty_string_resets_to_none(isolated_config):
    api = desktop_api.Api()
    api.save_server_url("https://192.168.1.10:8002")
    api.save_server_url("")
    assert api.get_server_url() is None


def test_get_server_url_defaults_to_none(isolated_config):
    api = desktop_api.Api()
    assert api.get_server_url() is None


def test_check_reachable_true_on_200(monkeypatch):
    class FakeResponse:
        status_code = 200

    monkeypatch.setattr(desktop_api.requests, "get", lambda *a, **k: FakeResponse())
    api = desktop_api.Api()
    assert api.check_reachable("https://example.com") is True


def test_check_reachable_false_on_non_200(monkeypatch):
    class FakeResponse:
        status_code = 500

    monkeypatch.setattr(desktop_api.requests, "get", lambda *a, **k: FakeResponse())
    api = desktop_api.Api()
    assert api.check_reachable("https://example.com") is False


def test_check_reachable_false_on_exception(monkeypatch):
    def raise_error(*a, **k):
        raise Exception("timeout")

    monkeypatch.setattr(desktop_api.requests, "get", raise_error)
    api = desktop_api.Api()
    assert api.check_reachable("https://example.com") is False
