"""Regression checks for the platform-specific icon renderings."""
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parent.parent


def _generate_iconset(tmp_path: Path) -> Path:
    mac_build = tmp_path / "mac-build"
    mac_build.mkdir()
    shutil.copy2(REPO_ROOT / "mac-build" / "icon_master_1024.png", mac_build)
    shutil.copy2(REPO_ROOT / "icon.ico", tmp_path / "icon.ico")
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "generate_iconset.py")],
        cwd=tmp_path,
        check=True,
    )
    return tmp_path


def test_generate_iconset_insets_macos_artwork_with_transparent_corners(tmp_path):
    """Removing the alpha composition makes the full canvas opaque again."""
    output = _generate_iconset(tmp_path)
    icon = Image.open(output / "mac-build" / "AppIcon_composed_1024.png").convert(
        "RGBA"
    )
    assert icon.size == (1024, 1024)
    alpha = icon.getchannel("A")

    for corner in ((0, 0), (1023, 0), (0, 1023), (1023, 1023)):
        assert alpha.getpixel(corner) == 0
    assert alpha.getpixel((512, 512)) == 255
    assert alpha.getbbox() == (100, 100, 924, 924)


def test_generate_iconset_keeps_windows_ico_unchanged(tmp_path):
    """Routing the ICO through the masked macOS image changes Windows artwork.

    Compared image by image rather than byte by byte. Re-encoding the same
    pixels does not reproduce the committed file byte for byte -- measured: all
    seven sizes identical, the files different -- so a bytes comparison fails on
    a correct run and says nothing about the artwork. Windows icons are
    full-bleed squares; masking them would be a regression on the one platform
    nobody reported a problem with, and that is what this asserts.
    """
    output = _generate_iconset(tmp_path)

    original = Image.open(REPO_ROOT / "icon.ico")
    regenerated = Image.open(output / "icon.ico")
    assert sorted(regenerated.ico.sizes()) == sorted(original.ico.sizes())

    for size in sorted(original.ico.sizes()):
        before = Image.open(REPO_ROOT / "icon.ico")
        before.size = size
        after = Image.open(output / "icon.ico")
        after.size = size
        assert before.convert("RGBA").tobytes() == after.convert("RGBA").tobytes(), \
            f"the {size[0]}px Windows icon changed"
