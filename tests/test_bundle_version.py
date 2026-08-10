import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_macos_bundle_versions_come_from_package_version():
    tree = ast.parse((REPO_ROOT / "main.spec").read_text(encoding="utf-8"))

    bundle_call = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "BUNDLE"
    )
    info_plist = next(
        keyword.value
        for keyword in bundle_call.keywords
        if keyword.arg == "info_plist"
    )
    fields = {
        key.value: value
        for key, value in zip(info_plist.keys, info_plist.values)
        if isinstance(key, ast.Constant)
    }

    assert isinstance(fields["CFBundleShortVersionString"], ast.Name)
    assert isinstance(fields["CFBundleVersion"], ast.Name)
    assert fields["CFBundleShortVersionString"].id == "__version__"
    assert fields["CFBundleVersion"].id == "__version__"

    assert any(
        isinstance(node, ast.ImportFrom)
        and node.module == "trimitdown"
        and any(alias.name == "__version__" for alias in node.names)
        for node in ast.walk(tree)
    )
