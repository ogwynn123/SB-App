from __future__ import annotations

import csv
import shutil
import sys
import unittest
import uuid
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import sample_append as sa  # noqa: E402


def _write(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerows(rows)


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class SampleAppendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = THIS_DIR.parents[1] / ".tmp_tests" / "sample_append" / uuid.uuid4().hex
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))
        self.data = self.root / "Data" / "NPA9999ts.csv"
        _write(self.data, [
            ["survnum", "voterbaseid", "timeseries", "CSM_2026", "zip"],
            ["1", "IA-1", "1", "0.50", "007"],
            ["2", "IA-2", "2", "", "010"],
            ["3", "IA-3", "2", "0.10", "020"],
            ["4", "IA-9", "2", "", "030"],
        ])
        self.sample = self.root / "Sample" / "sample.csv"
        _write(self.sample, [
            ["voterbase_id", "csm_score", "region"],
            ["IA-1", "0.99", "N"],
            ["IA-2", "0.123456789012", "S"],
            ["IA-3", "0.30", "E"],
            ["IA-7", "0.1", "W"],
            ["IA-7", "0.2", "W"],
        ])

    def test_fills_latest_wave_only_and_keeps_everything_else_exact(self) -> None:
        before = self.data.read_bytes()

        result = sa.append_sample_columns(self.data, self.sample, {"csm_score": "CSM_2026", "region": "REGION_NEW"})

        self.assertEqual(self.data.read_bytes(), before)
        self.assertEqual(result.output_path.name, "NPA9999ts_append.csv")
        self.assertEqual(result.waves, ["2"])
        self.assertEqual((result.matched, result.unmatched), (2, 1))
        self.assertEqual(result.created_columns, ["REGION_NEW"])
        rows = _read(result.output_path)
        self.assertEqual([r["CSM_2026"] for r in rows], ["0.50", "0.123456789012", "0.30", ""])
        self.assertEqual([r["REGION_NEW"] for r in rows], ["", "S", "E", ""])
        self.assertEqual([r["zip"] for r in rows], ["007", "010", "020", "030"])
        self.assertEqual(list(rows[0].keys()), ["survnum", "voterbaseid", "timeseries", "CSM_2026", "zip", "REGION_NEW"])
        self.assertEqual(result.replaced_nonblank["CSM_2026"], 1)
        self.assertEqual(result.sample_conflicts, ["IA-7"])
        report = result.report_path.read_text(encoding="utf-8")
        self.assertIn("matched 2; unmatched 1", report)
        self.assertIn("IA-9", report)
        self.assertIn("IA-7", report)

    def test_existing_output_is_moved_to_backups_not_overwritten(self) -> None:
        first = sa.append_sample_columns(self.data, self.sample, {"csm_score": "CSM_2026"})
        first.output_path.write_text("older run", encoding="utf-8")

        second = sa.append_sample_columns(self.data, self.sample, {"csm_score": "CSM_2026"})

        self.assertIsNotNone(second.backup_path)
        assert second.backup_path is not None
        self.assertEqual(second.backup_path.parent.name, "Backups")
        self.assertEqual(second.backup_path.read_text(encoding="utf-8"), "older run")
        self.assertNotEqual(second.output_path.read_text(encoding="utf-8"), "older run")

    def test_conflicting_duplicate_for_a_respondent_stops_before_writing(self) -> None:
        _write(self.sample, [["voterbase_id", "csm_score"], ["IA-2", "0.1"], ["IA-2", "0.2"]])

        with self.assertRaisesRegex(sa.AppendError, "IA-2"):
            sa.append_sample_columns(self.data, self.sample, {"csm_score": "CSM_2026"})
        self.assertFalse((self.data.parent / "NPA9999ts_append.csv").exists())

    def test_trended_ids_must_be_unique_within_each_filled_wave(self) -> None:
        _write(self.data, [
            ["survnum", "voterbaseid", "timeseries", "CSM_2026"],
            ["1", "IA-1", "1", ""],
            ["1", "IA-2", "2", ""],
            ["2", "IA-2", "2", ""],
        ])
        _write(self.sample, [["voterbase_id", "survnum", "csm_score"], ["IA-1", "1", "0.1"], ["IA-2", "2", "0.2"]])

        with self.assertRaisesRegex(sa.AppendError, "repeat within a wave.*timeseries 2 / IA-2"):
            sa.append_sample_columns(self.data, self.sample, {"csm_score": "CSM_2026"})
        with self.assertRaisesRegex(sa.AppendError, "restarts in every wave"):
            sa.append_sample_columns(
                self.data, self.sample, {"csm_score": "CSM_2026"},
                data_key="survnum", sample_key="survnum", waves="all",
            )
        # One wave at a time, survnum is a valid key.
        result = sa.append_sample_columns(
            self.data, self.sample, {"csm_score": "CSM_2026"},
            data_key="survnum", sample_key="survnum", waves=["1"],
        )
        self.assertEqual(result.matched, 1)

    def test_never_overwrites_input_and_checks_waves(self) -> None:
        with self.assertRaisesRegex(sa.AppendError, "overwrite the input"):
            sa.append_sample_columns(self.data, self.sample, {"csm_score": "CSM_2026"}, output_path=self.data)
        with self.assertRaisesRegex(sa.AppendError, "Wave"):
            sa.append_sample_columns(self.data, self.sample, {"csm_score": "CSM_2026"}, waves=["5"])

        result = sa.append_sample_columns(self.data, self.sample, {"csm_score": "CSM_2026"}, waves="all")
        self.assertEqual([r["CSM_2026"] for r in _read(result.output_path)][:1], ["0.99"])


if __name__ == "__main__":
    unittest.main()
