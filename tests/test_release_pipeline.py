"""Релизный конвейер: то, что ломается ровно один раз и уже необратимо."""
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

# Имена, на которые сошлются манифесты brew/scoop/winget. Каждое обязано приехать
# в релиз с контрольной суммой, иначе манифест не из чего писать.
RELEASE_ARTIFACTS = {
    "TrimItDown-macOS-x86_64.zip",
    "TrimItDown-macOS-arm64.zip",
    "TrimItDown-windows-x64.exe",
}


def _workflow(name):
    # PyYAML разбирает YAML 1.1, где `on:` -- булев True, а не строка. Без этой
    # нормализации проверка триггеров молча смотрит в пустоту и всегда зелена.
    document = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    if True in document:
        document["on"] = document.pop(True)
    return document


def _step(workflow_name, job, step_name):
    steps = _workflow(workflow_name)["jobs"][job]["steps"]
    return next(s for s in steps if s.get("name") == step_name)


def _bundle_checks(workflow_name):
    run = _step(workflow_name, "build", "Verify package contents are in the bundle")["run"]
    return set(re.findall(r'grep -\S+ "([^"]+)"', run))


def test_the_windows_bundle_is_verified_like_the_macos_one():
    # Спеки уже расходились молча: в одной был collect_all, в другой нет. Проверки
    # содержимого обязаны быть одинаковыми, иначе .exe уедет в релиз без движка
    # при зелёной сборке -- ровно тот отказ, который видит только пользователь.
    windows = _bundle_checks("build-windows.yml")

    assert windows == _bundle_checks("build-macos.yml")
    assert "trimitdown_pdf" in windows
    assert "tiktoken_cache" in windows


def test_the_release_carries_every_artifact_the_manifests_will_need():
    release = _workflow("release.yml")["jobs"]["release"]

    assert set(release["env"]["ARTIFACTS"].split()) == RELEASE_ARTIFACTS
    # Комплектность проверяется по тому же списку. Своя копия списка в проверке
    # разошлась бы с загрузкой молча -- релиз ушёл бы неполным и зелёным.
    assert "$ARTIFACTS" in _step(
        "release.yml", "release", "Verify every expected artifact arrived"
    )["run"]


def test_checksums_cover_the_whole_release_set():
    # Артефакт без суммы -- это артефакт, который манифест brew поставить не может.
    checksum = _step("release.yml", "release", "Checksum every artifact")["run"]
    create = _step("release.yml", "release", "Create the draft release")["run"]

    assert "sha256sum $ARTIFACTS" in checksum
    assert "$ARTIFACTS SHA256SUMS" in create


def test_the_release_refuses_a_version_the_package_does_not_declare():
    # Разъехавшись, номер релиза и номер пакета уже не чинятся: бинарники собраны,
    # а внутри они сообщают другое число.
    guard = _workflow("release.yml")["jobs"]["guard"]["steps"]
    step = next((s for s in guard if "__version__" in s.get("run", "")), None)

    assert step is not None, "релиз не сверяет запрошенный номер с версией пакета"
    assert "inputs.version" in step["run"]
    assert "exit 1" in step["run"]


def test_only_main_can_produce_a_release():
    # Даёт прогнать весь конвейер с ветки на живых раннерах, не создавая релизных
    # объектов от неслитого кода.
    create = _step("release.yml", "release", "Create the draft release")

    assert create.get("if") == "github.ref == 'refs/heads/main'"
