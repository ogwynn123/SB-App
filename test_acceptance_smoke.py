from __future__ import annotations

import shutil
import subprocess
import sys
import time
import unittest
import uuid
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent

from acceptance_smoke import FIXTURE_DIR, _pid_running, _stop_process_tree, run_acceptance  # noqa: E402

# Stands in for a one-file EXE: the launched process starts the real app as a
# child, reports the child's PID, then waits.
BOOTLOADER_SCRIPT = (
    "import subprocess, sys, time\n"
    "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
    "print(child.pid, flush=True)\n"
    "time.sleep(120)\n"
)


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

    def test_gui_smoke_stops_child_process_left_by_bootloader(self) -> None:
        process = subprocess.Popen(
            [sys.executable, "-c", BOOTLOADER_SCRIPT],
            stdout=subprocess.PIPE,
            text=True,
        )
        child_pid = int(process.stdout.readline())
        self.addCleanup(process.stdout.close)
        self.addCleanup(lambda: subprocess.run(["taskkill", "/PID", str(child_pid), "/F"], capture_output=True))
        time.sleep(0.5)
        self.assertTrue(_pid_running(child_pid))

        remaining = _stop_process_tree(process, timeout=3)

        self.assertEqual(remaining, [])
        self.assertIsNotNone(process.poll())
        self.assertFalse(_pid_running(child_pid))


if __name__ == "__main__":
    unittest.main()
