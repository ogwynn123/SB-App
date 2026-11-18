"""Each app has its icon files, and every icon key is used by an app."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import brand

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
ICON_CALL = re.compile(r"""set_app_icon\([^,]+,\s*["']([a-z_]+)["']\)""")


class AppIconTests(unittest.TestCase):
    def test_every_key_has_png_and_ico(self) -> None:
        for key in brand.APP_ICONS:
            with self.subTest(key=key):
                self.assertTrue((HERE / "icons" / f"{key}.ico").is_file())
                for size in brand.ICON_PNG_SIZES:
                    self.assertTrue((HERE / "icons" / f"{key}_{size}.png").is_file())

    def test_every_key_is_used_and_every_use_is_known(self) -> None:
        sources = [*REPO.glob("*.py"), *REPO.glob("pipelines/*/*.py")]
        used = set()
        for path in sources:
            if path.name.startswith("test_"):
                continue
            used.update(ICON_CALL.findall(path.read_text(encoding="utf-8", errors="replace")))
        self.assertEqual(used, set(brand.APP_ICONS))

    def test_unknown_key_is_ignored(self) -> None:
        self.assertFalse(brand.set_app_icon(object(), "no_such_app"))


if __name__ == "__main__":
    unittest.main()
