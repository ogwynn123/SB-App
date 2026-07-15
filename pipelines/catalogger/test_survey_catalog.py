import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
WINCROSS_DIR = ROOT.parent / "wincross_table_generator"
MODULE_PATH = ROOT / "survey_catalog.py"


def _load_catalog_module():
    if str(WINCROSS_DIR) not in sys.path:
        sys.path.insert(0, str(WINCROSS_DIR))
    spec = importlib.util.spec_from_file_location("catalogger_survey_catalog_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


catalog = _load_catalog_module()


class SurveyCatalogKeyTests(unittest.TestCase):
    def test_unique_question_key_skips_exact_duplicate_signature(self) -> None:
        seen_signatures: set[tuple[object, ...]] = set()
        assigned_keys: set[str] = set()
        duplicate_counts: dict[str, int] = {}

        first = catalog._unique_question_key(
            "base-key",
            signature=("json", "2628", "11a", "title", "item", (("1", "Yes"),)),
            seen_signatures=seen_signatures,
            assigned_keys=assigned_keys,
            duplicate_counts=duplicate_counts,
        )
        second = catalog._unique_question_key(
            "base-key",
            signature=("json", "2628", "11a", "title", "item", (("1", "Yes"),)),
            seen_signatures=seen_signatures,
            assigned_keys=assigned_keys,
            duplicate_counts=duplicate_counts,
        )

        self.assertEqual(first, "base-key")
        self.assertIsNone(second)

    def test_unique_question_key_disambiguates_distinct_collisions(self) -> None:
        seen_signatures: set[tuple[object, ...]] = set()
        assigned_keys: set[str] = set()
        duplicate_counts: dict[str, int] = {}

        first = catalog._unique_question_key(
            "base-key",
            signature=("json", "2628", "11a", "title", "item", (("1", "Yes"),)),
            seen_signatures=seen_signatures,
            assigned_keys=assigned_keys,
            duplicate_counts=duplicate_counts,
        )
        second = catalog._unique_question_key(
            "base-key",
            signature=("json", "2628", "11a", "title", "item", (("1", "No"),)),
            seen_signatures=seen_signatures,
            assigned_keys=assigned_keys,
            duplicate_counts=duplicate_counts,
        )

        self.assertEqual(first, "base-key")
        self.assertIsNotNone(second)
        self.assertNotEqual(second, "base-key")


if __name__ == "__main__":
    unittest.main()
