import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tomas_translate import build_browser_gpt_packet, normalize_existing_translation  # noqa: E402


class TomasTranslateBrowserFlowTests(unittest.TestCase):
    def test_build_browser_gpt_packet_includes_line_tags(self) -> None:
        src = "[IF Q7=1-6] And who is your second choice?\n1 Somewhat favorable 1\n"
        packet = build_browser_gpt_packet(src, mode="cati", locale="es-US", register="usted")
        self.assertIn("<<<L00001>>>", packet)
        self.assertIn("<<<L00002>>>", packet)
        self.assertIn(
            "Keep anything inside square brackets [] in English, unchanged, and in the same position",
            packet,
        )
        self.assertIn(
            "keep the Spanish substantive body identical and vary only the minimal delivery-wrapper wording",
            packet,
        )

    def test_normalize_existing_translation_reconstructs_line_tags(self) -> None:
        src = "[IF Q7=1-6] And who is your second choice?\n1 Somewhat favorable 1\n"
        candidate = """```text
<<<L00001>>>[IF Q7=1-6] ¿Y quién es su segunda opción?
<<<L00002>>>1 Algo favorable 1
```"""
        normalized = normalize_existing_translation(src, candidate, strict=True)
        self.assertEqual(
            normalized,
            "[IF Q7=1-6] ¿Y quién es su segunda opción?\n1 Algo favorable 1\n",
        )


if __name__ == "__main__":
    unittest.main()
