"""Релизный конвейер: то, что ломается ровно один раз и уже необратимо."""
import re
import runpy
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

# Имена, на которые сошлются манифесты brew/scoop/winget. Каждое обязано приехать
# в релиз с контрольной суммой, иначе манифест не из чего писать.
RELEASE_ARTIFACTS = {
    "TrimItDown-macOS-x86_64.dmg",
    "TrimItDown-macOS-arm64.dmg",
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


def test_bundle_verification_greps_cannot_be_neutered_by_or_true():
    # _bundle_checks only extracts WHAT each grep searches for -- it says
    # nothing about whether the grep can still fail the build. `grep -q "x"
    # file || true` always exits 0, so `... || true || { exit 1; }` never
    # takes the failure branch: the pattern is still found by the regex above
    # and the two workflows still compare equal, while the check itself has
    # become a silent no-op.
    for workflow in ("build-windows.yml", "build-macos.yml"):
        run = _script(_step(workflow, "build", "Verify package contents are in the bundle"))
        assert "|| true" not in run, (
            f"{workflow}: a grep in the bundle-contents check is followed by "
            "`|| true`, which always succeeds and swallows a real failure"
        )


def test_the_macos_release_is_a_verified_drag_to_install_image():
    """Removing either image check must make this test fail.

    A DMG that merely has the expected filename can omit the application, and
    an application that works from ``dist`` can still write beside itself and
    fail on the read-only mounted image. Both regressions reach users only
    after release, so the workflow must retain both checks.
    """
    image = _step("build-macos.yml", "build", "Build drag-to-install image")
    install = _step("build-macos.yml", "build", "Install dependencies")
    contents = _step("build-macos.yml", "build", "Verify image contents")
    smoke = _step("build-macos.yml", "build", "Smoke-launch the mounted image")

    image_run = _script(image)
    install_run = _script(install)
    contents_run = _script(contents)
    smoke_run = _script(smoke)

    assert "dmgbuild" in install_run
    assert "dmgbuild" in image_run
    assert "mac-build/dmgbuild_settings.py" in image_run
    assert "-D app=dist/TrimItDown.app" in image_run
    assert "hdiutil attach" in contents_run
    assert 'test -d "$mount_dir/TrimItDown.app"' in contents_run
    assert 'test -L "$mount_dir/Applications"' in contents_run
    assert 'readlink "$mount_dir/Applications"' in contents_run
    assert "hdiutil attach" in smoke_run
    assert "-readonly" in smoke_run
    assert "TrimItDown.app/Contents/MacOS/TrimItDown" in smoke_run
    assert "TRIMITDOWN_SMOKE=smoke.pdf" in smoke_run
    assert "tail -1 smoke-mounted.log | grep -q '^smoke ok:'" in smoke_run


def test_dmgbuild_settings_create_a_symmetric_install_layout():
    """Removing Finder geometry returns the image to its large default window."""
    settings_path = REPO_ROOT / "mac-build" / "dmgbuild_settings.py"
    assert settings_path.is_file(), "the macOS image has no dmgbuild settings"

    settings = runpy.run_path(
        str(settings_path),
        init_globals={"defines": {"app": "dist/TrimItDown.app"}},
    )

    assert settings["files"] == ["dist/TrimItDown.app"]
    assert settings["symlinks"] == {"Applications": "/Applications"}
    assert settings["background"] is None
    assert settings["window_rect"] == ((200, 200), (660, 400))
    assert settings["icon_size"] == 128
    assert settings["icon_locations"] == {
        "TrimItDown.app": (180, 200),
        "Applications": (480, 200),
    }


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
    # "sha256sum $ARTIFACTS" as a substring says nothing about what happens
    # to SHA256SUMS afterward -- a step that computes real hashes and then
    # rewrites or zeroes the file still contains that exact substring and
    # passes the assertion above. The legitimate script touches the name
    # SHA256SUMS exactly twice: once to create it (the redirect), once to
    # display it (cat). Anything else touching the file adds a third mention.
    assert checksum.count("SHA256SUMS") == 2, (
        f"SHA256SUMS is referenced an unexpected number of times in the "
        f"checksum step -- something besides create-then-display touches "
        f"it:\n{checksum}"
    )


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


def test_exactly_one_step_can_create_a_release():
    # _step() returns the FIRST step matching a name -- every test above that
    # reads "Create the draft release" (the main-only guard, GH_REPO, the
    # --target pin) only ever sees that one step. A second step added later in
    # the same job that also invokes `gh release create`, without the
    # main-only guard, would create an unreviewed release from any branch and
    # none of the tests above would notice: they never look past the first
    # match.
    steps = _workflow("release.yml")["jobs"]["release"]["steps"]
    release_creating = [s for s in steps if "gh release create" in _script(s)]
    assert len(release_creating) == 1, (
        f"expected exactly one step invoking `gh release create`, found "
        f"{len(release_creating)}: {[s.get('name') for s in release_creating]}"
    )


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
    # The case statement's mere presence doesn't say the two branches build
    # different things -- both arms could set the same `source=` and publish
    # the app's own tree under the engine's name (or vice versa) while this
    # assertion stays green. Pull out each branch's source and require they
    # differ, one per declared option.
    sources = dict(re.findall(r'(\S+)\)\s+source=(\S+)\s*;;', _script(build)))
    assert sources == {"trimitdown": ".", "trimitdown-pdf": "packages/trimitdown-pdf"}, (
        f"the two package branches must build from different source trees: {sources}"
    )


# Инвариант «ноль скипов» стоял только в tests.yml, то есть ровно там, где
# ошибка обратима, и был снят в release.yml и publish-pypi.yml, где она уже нет.
# Проверка держит его на всех прогонах сюиты сразу, а не перечисляет workflow
# поимённо: новый workflow с той же дырой должен ронять этот тест, а не
# проходить мимо списка.
PORTABLE_SUITE = re.compile(r'pytest\s+-m\s+"not corpus"')


def _run_blocks(document):
    for job in (document.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            if isinstance(step.get("run"), str):
                yield step.get("name", "<unnamed>"), step["run"]


def test_every_portable_suite_run_asserts_zero_skips():
    """`pytest` exits 0 on a run that skipped everything it was meant to check.

    Weakened to "tests.yml contains check_no_skips", this passes with the
    release and publish workflows back on a bare `pytest -q` -- the state that
    let a green gate stand immediately before creating a release and before
    burning a PyPI version number.
    """
    offenders = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for name, block in _run_blocks(_workflow(path.name)):
            if PORTABLE_SUITE.search(block) and "check_no_skips.py" not in block:
                offenders.append(f"{path.name}::{name}")
    assert not offenders, \
        f"these run the portable suite without asserting zero skips: {offenders}"


def test_the_skip_check_is_not_a_no_op(tmp_path):
    """The guard itself has to fail on the three states it exists to catch."""
    import subprocess

    def verdict(xml: str) -> int:
        report = tmp_path / "report.xml"
        report.write_text(xml, encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "check_no_skips.py"), str(report)],
            capture_output=True).returncode

    clean = '<testsuites><testsuite tests="2"><testcase classname="a" name="b"/>' \
            '<testcase classname="a" name="c"/></testsuite></testsuites>'
    skipped = '<testsuites><testsuite tests="2"><testcase classname="a" name="b"/>' \
              '<testcase classname="a" name="c"><skipped/></testcase></testsuite></testsuites>'
    empty = '<testsuites><testsuite tests="0"></testsuite></testsuites>'

    assert verdict(clean) == 0
    assert verdict(skipped) == 1, "a skipped test passed the skip check"
    assert verdict(empty) == 1, "a run of zero tests passed the skip check"


def test_unmounting_the_image_cannot_overrule_a_passing_check():
    """Cleanup must not decide the verdict.

    The release run failed with `hdiutil: couldn't eject "disk2" - Resource
    busy` after the smoke check had already printed `smoke ok`: the app can
    still hold the volume for a moment after it exits, and a bare detach inside
    an EXIT trap under `set -e` returns 16 as the step's status. Remove the
    tolerance and this test fails; the check it guards would go red for a reason
    that has nothing to do with the artifact.
    """
    for step_name in ("Verify image contents", "Smoke-launch the mounted image"):
        run = _script(_step("build-macos.yml", "build", step_name))
        detach = next(line for line in run.splitlines() if "hdiutil detach" in line)
        assert "|| true" in detach, f"{step_name}: teardown can fail the step"
