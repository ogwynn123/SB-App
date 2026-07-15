import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tomas_pipeline  # noqa: E402


class TomasPipelinePreflightTests(unittest.TestCase):
    def test_preflight_skips_module_probe_in_frozen_runtime(self) -> None:
        with mock.patch.object(tomas_pipeline.sys, "frozen", True, create=True):
            with mock.patch.object(tomas_pipeline, "_missing_modules_for_python") as missing_probe:
                tomas_pipeline._preflight_runtime_dependencies("fake-worker.exe")
        missing_probe.assert_not_called()

    def test_preflight_uses_probe_in_source_runtime(self) -> None:
        with mock.patch.object(tomas_pipeline.sys, "frozen", False, create=True):
            with mock.patch.object(tomas_pipeline, "_missing_modules_for_python", return_value=[]) as missing_probe:
                tomas_pipeline._preflight_runtime_dependencies("python.exe")
        missing_probe.assert_called_once_with("python.exe", ["docx", "pdfplumber", "openai"])

    def test_parallel_delivery_consistency_reuses_preferred_body(self) -> None:
        phone_src = ["Now I will tell you about Shannon Bird.\n"]
        sms_src = ["Now you will read about Shannon Bird.\n"]
        phone_es = ["Ahora le voy a hablar de Shannon Bird.\n"]
        sms_es = ["Ahora leerá sobre la congresista Shannon Bird.\n"]

        report = tomas_pipeline._apply_parallel_delivery_consistency(
            phone_src_lines=phone_src,
            phone_es_lines=phone_es,
            sms_src_lines=sms_src,
            sms_es_lines=sms_es,
            prefer="phone",
        )

        self.assertEqual(phone_es[0], "Ahora le voy a hablar de Shannon Bird.\n")
        self.assertEqual(sms_es[0], "Ahora leerá sobre Shannon Bird.\n")
        self.assertEqual(report["shared_parallel_source_lines"], 1)
        self.assertEqual(report["harmonized_pairs"], 1)
        self.assertEqual(report["changed_sms_lines"], 1)

    def test_parallel_delivery_consistency_leaves_nonmatching_lines_alone(self) -> None:
        phone_src = ["Now I will tell you about Shannon Bird.\n"]
        sms_src = ["Now you will read about Gabe Evans.\n"]
        phone_es = ["Ahora le voy a hablar de Shannon Bird.\n"]
        sms_es = ["Ahora leerá sobre Gabe Evans.\n"]

        report = tomas_pipeline._apply_parallel_delivery_consistency(
            phone_src_lines=phone_src,
            phone_es_lines=phone_es,
            sms_src_lines=sms_src,
            sms_es_lines=sms_es,
            prefer="phone",
        )

        self.assertEqual(phone_es[0], "Ahora le voy a hablar de Shannon Bird.\n")
        self.assertEqual(sms_es[0], "Ahora leerá sobre Gabe Evans.\n")
        self.assertEqual(report["shared_parallel_source_lines"], 0)
        self.assertEqual(report["harmonized_pairs"], 0)


if __name__ == "__main__":
    unittest.main()
