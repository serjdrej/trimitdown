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

# Подстановка входа workflow_dispatch. Ловит и ${{ inputs.x }}, и
# ${{ github.event.inputs.x }} -- обе разворачиваются одинаково.
DISPATCH_INPUT = re.compile(r"\$\{\{[^}]*\binputs\.")


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


def _script(step):
    # Комментарии -- не код. Проверка, которая их не отсеивает, зеленеет на
    # закомментированной гарантии: этот проект уже ловил такую мутацию.
    return "\n".join(
        line
        for line in step.get("run", "").splitlines()
        if not line.strip().startswith("#")
    )


def _command(step, opening):
    """Одна команда целиком: от её первой строки до конца продолжений через `\\`."""
    lines = _script(step).splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip().startswith(opening))
    command = [lines[start]]
    while command[-1].rstrip().endswith("\\"):
        command.append(lines[start + len(command)])
    return "\n".join(command)


def _bundle_checks(workflow_name):
    run = _script(_step(workflow_name, "build", "Verify package contents are in the bundle"))
    return set(re.findall(r'grep -\S+ "([^"]+)"', run))


def test_the_windows_bundle_is_verified_like_the_macos_one():
    # Спеки уже расходились молча: в одной был collect_all, в другой нет. Проверки
    # содержимого обязаны быть одинаковыми, иначе .exe уедет в релиз без движка
    # при зелёной сборке -- ровно тот отказ, который видит только пользователь.
    windows = _bundle_checks("build-windows.yml")

    assert windows == _bundle_checks("build-macos.yml")
    assert "trimitdown_pdf" in windows
    assert "tiktoken_cache" in windows


def test_no_dispatch_input_reaches_a_shell_or_an_action():
    # Подстановка ${{ }} разворачивается в текст скрипта ДО его запуска, поэтому
    # номер версии вида $(...) выполнится раньше любой проверки внутри скрипта --
    # в том числе там, где у токена есть contents: write. Инвариант обратный:
    # проверять наличие безопасной формы мало, старую можно вернуть, не убрав
    # новую. Опасной формы не должно быть нигде, вход едет только через env.
    for name in sorted(p.name for p in WORKFLOWS.glob("*.yml")):
        for job in _workflow(name)["jobs"].values():
            for step in job.get("steps", []):
                assert not DISPATCH_INPUT.search(_script(step)), (
                    f"{name}: вход workflow_dispatch подставляется прямо в скрипт"
                )
                for key, value in (step.get("with") or {}).items():
                    assert not DISPATCH_INPUT.search(str(value)), (
                        f"{name}: вход workflow_dispatch подставляется во вход действия ({key})"
                    )


def test_the_release_carries_every_artifact_the_manifests_will_need():
    release = _workflow("release.yml")["jobs"]["release"]

    assert set(release["env"]["ARTIFACTS"].split()) == RELEASE_ARTIFACTS
    # Комплектность проверяется по тому же списку. Своя копия списка в проверке
    # разошлась бы с загрузкой молча -- релиз ушёл бы неполным и зелёным.
    assert "$ARTIFACTS" in _script(
        _step("release.yml", "release", "Verify every expected artifact arrived")
    )


def test_checksums_cover_the_whole_release_set():
    # Артефакт без суммы -- это артефакт, который манифест brew поставить не может.
    checksum = _script(_step("release.yml", "release", "Checksum every artifact"))
    create = _command(_step("release.yml", "release", "Create the draft release"), "gh release create")

    assert "sha256sum $ARTIFACTS" in checksum
    assert "$ARTIFACTS SHA256SUMS" in create


def test_the_release_refuses_a_version_the_package_does_not_declare():
    # Разъехавшись, номер релиза и номер пакета уже не чинятся: бинарники собраны,
    # а внутри они сообщают другое число.
    guard = _workflow("release.yml")["jobs"]["guard"]["steps"]
    step = next((s for s in guard if "__version__" in s.get("run", "")), None)

    assert step is not None, "релиз не сверяет запрошенный номер с версией пакета"
    assert step["env"]["VERSION"] == "${{ inputs.version }}"
    assert 'test "$declared" = "$VERSION"' in _script(step)
    assert "exit 1" in _script(step)


def test_the_release_step_knows_which_repository_it_targets():
    # Джоба не делает checkout, .git рядом нет, а gh без GH_REPO падает с
    # "not a git repository" -- уже после того, как всё собрано и посчитано.
    # GITHUB_REPOSITORY он не читает: проверено вручную на gh 2.96.0.
    create = _step("release.yml", "release", "Create the draft release")

    assert create["env"]["GH_REPO"] == "${{ github.repository }}"


def test_the_draft_is_pinned_to_the_commit_that_was_built():
    # Без --target тег привяжется к верхушке default-ветки на момент публикации.
    # Сборка идёт долго; приехавший тем временем коммит увёл бы тег с того кода,
    # из которого собраны вложенные бинарники, и по релизу это уже не видно.
    # Флаг проверяется внутри самой команды: рядом с ней он ничего не значит.
    create = _step("release.yml", "release", "Create the draft release")

    assert '--target "$GITHUB_SHA"' in _command(create, "gh release create")


def test_only_main_can_produce_a_release():
    # Даёт прогнать весь конвейер с ветки на живых раннерах, не создавая релизных
    # объектов от неслитого кода.
    create = _step("release.yml", "release", "Create the draft release")

    assert create.get("if") == "github.ref == 'refs/heads/main'"


def test_the_publish_workflow_can_publish_both_projects():
    # Приложение и движок -- два разных проекта на PyPI. Пока workflow умеет
    # только движок, канал uvx закрыт, а второй workflow-близнец разошёлся бы с
    # первым так же, как расходились спеки.
    publish = _workflow("publish-pypi.yml")
    options = publish["on"]["workflow_dispatch"]["inputs"]["package"]["options"]
    build = _step("publish-pypi.yml", "build", "Build sdist and wheel")

    assert set(options) == {"trimitdown", "trimitdown-pdf"}
    assert build["env"]["PACKAGE"] == "${{ inputs.package }}"
    assert 'case "$PACKAGE" in' in _script(build), (
        "сборка игнорирует выбор и всегда публикует один и тот же проект"
    )
