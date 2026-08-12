from __future__ import annotations

import shutil
import unittest
import uuid
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent

from acceptance_smoke import FIXTURE_DIR, run_acceptance  # noqa: E402


class AcceptanceSmokeTests(unittest.TestCase):
    def _fixture_snapshot(self) -> dict[str, bytes]:
        return {
            str(path.relative_to(FIXTURE_DIR)): path.read_bytes()
            for path in FIXTURE_DIR.rglob("*")
            if path.is_file()
        }

    def test_synthetic_acceptance_workflow_passes_without_modifying_fixture(self) -> None:
        output_root = BASE_DIR / ".tmp_tests" / "acceptance_smoke" / f"case_{uuid.uuid4().hex}"
        output_root.mkdir(parents=True)
        self.addCleanup(lambda: shutil.rmtree(output_root, ignore_errors=True))
        before = self._fixture_snapshot()

        report = run_acceptance(output_root=output_root)

        self.assertFalse(report.failed)
        self.assertEqual(len(report.steps), 10)
        self.assertTrue(all(step.status == "PASS" for step in report.steps))
        self.assertEqual(self._fixture_snapshot(), before)
        self.assertTrue((report.run_dir / "acceptance_report.txt").exists())
        self.assertTrue((report.run_dir / "acceptance_report.json").exists())


if __name__ == "__main__":
    unittest.main()
