import csv
import shutil
import sys
import csv
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
TMP_ROOT = THIS_DIR / ".tmp_tests_record_coder"
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import oe_record_coder_core as core  # noqa: E402


@contextmanager
def local_tmp():
    path = TMP_ROOT / f"run_{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def write_csv(path: Path, rows: list[dict[str, str]]) -> Path:
    headers = list(rows[0])
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
    return path


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sample_rows() -> list[dict[str, str]]:
    return [
        {
            "Survnum": "1001",
            "district": "A",
            "q16": "Health care costs",
            "c16_1": "98",
            "c16_2": "",
            "c16_3": "",
        },
        {
            "Survnum": "1002",
            "district": "B",
            "q16": "Health care costs",
            "c16_1": "98",
            "c16_2": "",
            "c16_3": "",
        },
    ]


def timeseries_rows() -> list[dict[str, str]]:
    rows = [dict(row) for row in sample_rows()]
    rows[0]["Timeseries"] = "1"
    rows[0]["c16_1"] = "10"
    rows[1]["Timeseries"] = "2"
    rows[1]["c16_1"] = "20"
    rows.append(
        {
            "Survnum": "1003",
            "district": "C",
            "q16": "Roads",
            "c16_1": "30",
            "c16_2": "",
            "c16_3": "",
            "Timeseries": "2",
        }
    )
    return rows


class RecordCoderCoreTests(unittest.TestCase):
    def test_detects_key_and_open_end_question(self) -> None:
        headers = ["Survnum", "q16", "c16_1", "c16_2", "other"]

        self.assertEqual(core.suggest_key_column(headers), "Survnum")
        specs = core.detect_open_end_questions(headers)

        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0].name, "q16")
        self.assertEqual(specs[0].companion_columns, ("c16_1", "c16_2"))
        self.assertEqual(core.normalize_record_key("1001.0"), "1001")
        self.assertEqual(core.normalize_record_key("001001"), "001001")

    def test_rejects_duplicate_record_keys(self) -> None:
        with local_tmp() as temp:
            source = write_csv(temp / "data.csv", sample_rows() + [dict(sample_rows()[0])])
            with core.CodingSession(temp / "coding.sqlite") as session:
                with self.assertRaisesRegex(ValueError, "not unique"):
                    session.import_data(source)

    def test_specific_rows_can_receive_different_codes_for_same_verbatim(self) -> None:
        with local_tmp() as temp:
            source = write_csv(temp / "data.csv", sample_rows())
            output = temp / "data.OE-coded.csv"
            with core.CodingSession(temp / "coding.sqlite", survey_id="NPA9999") as session:
                summary = session.import_data(source)
                question = session.questions()[0]
                responses = session.list_responses(question.id)
                by_key = {response.record_key: response for response in responses}

                session.set_assignment(by_key["1001"].id, ["500", "7"])
                session.set_assignment(by_key["1002"].id, ["9"])
                exported = session.export_coded_csv(output)

            rows = read_csv(output)
            self.assertEqual(summary.key_column, "Survnum")
            self.assertEqual((rows[0]["c16_1"], rows[0]["c16_2"], rows[0]["c16_3"]), ("500", "7", ""))
            self.assertEqual((rows[1]["c16_1"], rows[1]["c16_2"], rows[1]["c16_3"]), ("9", "", ""))
            self.assertEqual(rows[0]["district"], "A")
            self.assertEqual(read_csv(source)[0]["c16_1"], "98")
            self.assertEqual(exported.modified_records, 2)

    def test_responses_filter_by_original_final_or_blank_code(self) -> None:
        with local_tmp() as temp:
            source = write_csv(temp / "data.csv", sample_rows())
            with core.CodingSession(temp / "coding.sqlite") as session:
                session.import_data(source)
                question = session.questions()[0]
                responses = session.list_responses(question.id)
                session.set_assignment(responses[0].id, ["500"])
                session.set_assignment(responses[1].id, [])

                original_98 = session.list_responses(
                    question.id,
                    code_filter="98",
                    code_scope="original",
                )
                final_500 = session.list_responses(
                    question.id,
                    code_filter="500",
                    code_scope="final",
                )
                final_blank = session.list_responses(
                    question.id,
                    status="coded",
                    code_filter="(blank)",
                    code_scope="final",
                )
                either_98 = session.list_responses(
                    question.id,
                    code_filter="98",
                    code_scope="either",
                )

            self.assertEqual({item.record_key for item in original_98}, {"1001", "1002"})
            self.assertEqual([item.record_key for item in final_500], ["1001"])
            self.assertEqual([item.record_key for item in final_blank], ["1002"])
            self.assertEqual({item.record_key for item in either_98}, {"1001", "1002"})

    def test_timeseries_scope_uses_dataset_maximum(self) -> None:
        with local_tmp() as temp:
            source = write_csv(temp / "data.csv", timeseries_rows())
            with core.CodingSession(temp / "coding.sqlite") as session:
                session.import_data(source)
                question = session.questions()[0]
                latest = session.max_timeseries()
                responses = session.list_responses(question.id, timeseries=latest)

            self.assertEqual(latest, 2)
            # Trended data is keyed by the (Timeseries, Survnum) pair.
            self.assertEqual([item.record_key for item in responses], ["2|1002", "2|1003"])
            self.assertTrue(all(item.timeseries == 2 for item in responses))

    def test_timeseries_maximum_includes_rows_without_open_end_answers(self) -> None:
        with local_tmp() as temp:
            rows = timeseries_rows()
            rows.append(
                {
                    "Survnum": "1004",
                    "district": "D",
                    "q16": "",
                    "c16_1": "",
                    "c16_2": "",
                    "c16_3": "",
                    "Timeseries": "3",
                }
            )
            source = write_csv(temp / "data.csv", rows)
            with core.CodingSession(temp / "coding.sqlite") as session:
                session.import_data(source)
                question = session.questions()[0]

                self.assertEqual(session.max_timeseries(), 3)
                self.assertEqual(session.list_responses(question.id, timeseries=3), [])

    def test_timeseries_requires_integer_values(self) -> None:
        with local_tmp() as temp:
            rows = timeseries_rows()
            rows[1]["Timeseries"] = "wave 2"
            source = write_csv(temp / "data.csv", rows)
            with core.CodingSession(temp / "coding.sqlite") as session:
                with self.assertRaisesRegex(ValueError, "Timeseries must contain integers"):
                    session.import_data(source)

    def test_matching_text_can_be_limited_to_latest_timeseries(self) -> None:
        with local_tmp() as temp:
            source = write_csv(temp / "data.csv", timeseries_rows())
            with core.CodingSession(temp / "coding.sqlite") as session:
                session.import_data(source)
                question = session.questions()[0]
                responses = {item.record_key.split("|")[-1]: item for item in session.list_responses(question.id)}

                changed = session.apply_to_matching_text(
                    responses["1002"].id,
                    ["500"],
                    timeseries=session.max_timeseries(),
                )
                old_wave = session.response(responses["1001"].id)
                latest_wave = session.response(responses["1002"].id)

            self.assertEqual(changed, 1)
            self.assertFalse(old_wave.override_active)
            self.assertEqual(old_wave.final_codes, ("10",))
            self.assertTrue(latest_wave.override_active)
            self.assertEqual(latest_wave.final_codes, ("500",))

    def test_redundant_code_cleanup_removes_code_only_when_other_final_codes_exist(self) -> None:
        with local_tmp() as temp:
            rows = [
                {
                    "Survnum": "1001",
                    "Timeseries": "1",
                    "q16": "Older wave",
                    "c16_1": "98",
                    "c16_2": "14",
                    "c16_3": "",
                },
                {
                    "Survnum": "1002",
                    "Timeseries": "2",
                    "q16": "Multiple codes",
                    "c16_1": "98",
                    "c16_2": "14",
                    "c16_3": "15",
                },
                {
                    "Survnum": "1003",
                    "Timeseries": "2",
                    "q16": "Other only",
                    "c16_1": "98",
                    "c16_2": "",
                    "c16_3": "",
                },
                {
                    "Survnum": "1004",
                    "Timeseries": "2",
                    "q16": "No other code",
                    "c16_1": "14",
                    "c16_2": "",
                    "c16_3": "",
                },
            ]
            source = write_csv(temp / "data.csv", rows)
            with core.CodingSession(temp / "coding.sqlite") as session:
                session.import_data(source)
                question = session.questions()[0]
                responses = {item.record_key.split("|")[-1]: item for item in session.list_responses(question.id)}
                session.set_assignment(
                    responses["1002"].id,
                    ["98", "14", "15"],
                    flagged=True,
                    note="Keep this note",
                )

                preview = session.preview_redundant_code_cleanup(
                    question.id,
                    "98",
                    timeseries=2,
                )
                summary = session.cleanup_redundant_code(
                    question.id,
                    "98",
                    timeseries=2,
                )
                updated = {
                    key: session.response(response.id)
                    for key, response in responses.items()
                }

            self.assertEqual(preview.matching_response_count, 2)
            self.assertEqual(preview.changed_response_count, 1)
            self.assertEqual(preview.retained_only_code_count, 1)
            self.assertEqual(summary.changed_response_count, 1)
            self.assertEqual(updated["1001"].final_codes, ("98", "14"))
            self.assertFalse(updated["1001"].override_active)
            self.assertEqual(updated["1002"].final_codes, ("14", "15"))
            self.assertTrue(updated["1002"].flagged)
            self.assertEqual(updated["1002"].note, "Keep this note")
            self.assertEqual(updated["1003"].final_codes, ("98",))
            self.assertFalse(updated["1003"].override_active)
            self.assertEqual(updated["1004"].final_codes, ("14",))

    def test_reimport_preserves_overrides_and_adds_new_records(self) -> None:
        with local_tmp() as temp:
            source1 = write_csv(temp / "day1.csv", sample_rows())
            day2_rows = sample_rows() + [
                {
                    "Survnum": "1003",
                    "district": "C",
                    "q16": "Roads",
                    "c16_1": "98",
                    "c16_2": "",
                    "c16_3": "",
                }
            ]
            source2 = write_csv(temp / "day2.csv", day2_rows)
            with core.CodingSession(temp / "coding.sqlite") as session:
                session.import_data(source1)
                question = session.questions()[0]
                self.assertEqual(
                    {item.record_key for item in session.list_responses(question.id, import_scope="new_or_changed")},
                    {"1001", "1002"},
                )
                first = session.list_responses(question.id)[0]
                session.set_assignment(first.id, ["500"])

                summary = session.import_data(source2)
                responses = {item.record_key: item for item in session.list_responses(question.id)}

                self.assertEqual(responses["1001"].final_codes, ("500",))
                self.assertTrue(responses["1001"].override_active)
                self.assertFalse(responses["1003"].override_active)
                self.assertEqual(summary.preserved_override_count, 1)
                self.assertEqual(summary.changed_override_count, 0)
                self.assertEqual(summary.new_response_count, 1)
                self.assertEqual(summary.source_changed_response_count, 0)
                self.assertEqual(responses["1001"].import_status, "Existing")
                self.assertEqual(responses["1003"].import_status, "New")
                self.assertEqual(
                    [item.record_key for item in session.list_responses(question.id, import_scope="new")],
                    ["1003"],
                )
                self.assertEqual(
                    [item.record_key for item in session.list_responses(question.id, import_scope="new_or_changed")],
                    ["1003"],
                )
                self.assertEqual(
                    session.list_responses(question.id, import_scope="changed"),
                    [],
                )

    def test_reimport_flags_preserved_override_when_source_response_changes(self) -> None:
        with local_tmp() as temp:
            source1 = write_csv(temp / "day1.csv", sample_rows())
            changed = sample_rows()
            changed[0]["q16"] = "A materially different response"
            source2 = write_csv(temp / "day2.csv", changed)
            with core.CodingSession(temp / "coding.sqlite") as session:
                session.import_data(source1)
                question = session.questions()[0]
                first = session.list_responses(question.id)[0]
                session.set_assignment(first.id, ["500"])

                summary = session.import_data(source2)
                updated = session.response(first.id)
                changed_responses = session.list_responses(question.id, import_scope="changed")

            self.assertEqual(summary.changed_override_count, 1)
            self.assertEqual(summary.source_changed_response_count, 1)
            self.assertTrue(updated.override_active)
            self.assertTrue(updated.flagged)
            self.assertEqual(updated.review_status, "flagged")
            self.assertEqual(updated.import_status, "Source changed")
            self.assertIn("Source response changed", updated.note)
            self.assertEqual([item.record_key for item in changed_responses], ["1001"])

    def test_reimport_tracks_source_code_changes_without_an_override(self) -> None:
        with local_tmp() as temp:
            source1 = write_csv(temp / "day1.csv", sample_rows())
            changed = sample_rows()
            changed[1]["c16_1"] = "7"
            changed[1]["c16_2"] = ""
            source2 = write_csv(temp / "day2.csv", changed)
            with core.CodingSession(temp / "coding.sqlite") as session:
                session.import_data(source1)
                question = session.questions()[0]

                summary = session.import_data(source2)
                changed_responses = session.list_responses(question.id, import_scope="changed")

            self.assertEqual(summary.source_changed_response_count, 1)
            self.assertEqual(summary.changed_override_count, 0)
            self.assertEqual([item.record_key for item in changed_responses], ["1002"])
            self.assertEqual(changed_responses[0].original_codes, ("7",))
            self.assertEqual(changed_responses[0].final_codes, ("7",))
            self.assertFalse(changed_responses[0].override_active)
            self.assertEqual(changed_responses[0].import_status, "Source changed")

    def test_rejects_unknown_import_scope(self) -> None:
        with local_tmp() as temp:
            source = write_csv(temp / "data.csv", sample_rows())
            with core.CodingSession(temp / "coding.sqlite") as session:
                session.import_data(source)
                question = session.questions()[0]

                with self.assertRaisesRegex(ValueError, "Import filter"):
                    session.list_responses(question.id, import_scope="not-a-scope")

    def test_codebook_metadata_is_independent_from_assignments(self) -> None:
        with local_tmp() as temp:
            source = write_csv(temp / "data.csv", sample_rows())
            with core.CodingSession(temp / "coding.sqlite") as session:
                session.import_data(source)
                question = session.questions()[0]
                response = session.list_responses(question.id)[0]
                session.set_assignment(response.id, ["500"])

                session.upsert_code(
                    question.id,
                    "500",
                    label="Health care costs",
                    supercategory="Health Care",
                    direction="-",
                )
                session.upsert_code(
                    question.id,
                    "500",
                    label="Medical affordability",
                    supercategory="Economic Concerns",
                    direction="-",
                )

                updated_response = session.response(response.id)
                code = session.get_code(question.id, "500")

            self.assertEqual(updated_response.final_codes, ("500",))
            self.assertEqual(code.label, "Medical affordability")
            self.assertEqual(code.supercategory, "Economic Concerns")

    def test_assignment_cannot_exceed_available_slots(self) -> None:
        with local_tmp() as temp:
            rows = sample_rows()
            for row in rows:
                row.pop("c16_3")
            source = write_csv(temp / "data.csv", rows)
            with core.CodingSession(temp / "coding.sqlite") as session:
                session.import_data(source)
                question = session.questions()[0]
                response = session.list_responses(question.id)[0]

                with self.assertRaisesRegex(ValueError, "2 code slot"):
                    session.set_assignment(response.id, ["1", "2", "3"])

    def test_export_refuses_changed_source_and_original_path(self) -> None:
        with local_tmp() as temp:
            source = write_csv(temp / "data.csv", sample_rows())
            with core.CodingSession(temp / "coding.sqlite") as session:
                session.import_data(source)
                response = session.list_responses(session.questions()[0].id)[0]
                session.set_assignment(response.id, ["500"])

                with self.assertRaisesRegex(ValueError, "cannot overwrite"):
                    session.export_coded_csv(source)

                changed_rows = sample_rows()
                changed_rows[0]["district"] = "Changed"
                write_csv(source, changed_rows)
                with self.assertRaisesRegex(ValueError, "changed after import"):
                    session.export_coded_csv(temp / "coded.csv")

    def test_codelist_csv_loads_secondary_metadata(self) -> None:
        with local_tmp() as temp:
            source = write_csv(temp / "data.csv", sample_rows())
            codelist = write_csv(
                temp / "codes.csv",
                [
                    {
                        "question_col": "q16",
                        "code": "500",
                        "label": "Health care costs",
                        "supercategory": "Health Care",
                        "direction": "-",
                    }
                ],
            )
            with core.CodingSession(temp / "coding.sqlite") as session:
                session.import_data(source)
                summary = session.load_codelist(codelist)
                question = session.questions()[0]
                item = session.get_code(question.id, "500")

            self.assertEqual(summary.parsed_code_count, 1)
            self.assertEqual(summary.added_code_count, 1)
            self.assertEqual(summary.updated_code_count, 0)
            self.assertEqual(summary.conflicts, ())
            self.assertEqual(summary.overwrites, ())
            self.assertEqual(item.label, "Health care costs")
            self.assertEqual(item.supercategory, "Health Care")
            self.assertEqual(item.direction, "-")

    def test_codelist_preserves_conflicts_by_default_and_can_overwrite(self) -> None:
        with local_tmp() as temp:
            source = write_csv(temp / "data.csv", sample_rows())
            codelist = write_csv(
                temp / "codes.csv",
                [
                    {
                        "question_col": "q16",
                        "code": "98",
                        "label": "Delivered label",
                        "supercategory": "Delivered group",
                        "direction": "-",
                    }
                ],
            )
            with core.CodingSession(temp / "coding.sqlite") as session:
                session.import_data(source)
                question = session.questions()[0]

                initial = session.load_codelist(codelist)
                session.upsert_code(
                    question.id,
                    "98",
                    label="User label",
                    supercategory="User group",
                    direction="+",
                    source="user",
                )
                preserved = session.load_codelist(codelist)
                preserved_item = session.get_code(question.id, "98")
                overwritten = session.load_codelist(codelist, overwrite_existing=True)
                overwritten_item = session.get_code(question.id, "98")

            self.assertEqual(initial.updated_code_count, 1)
            self.assertEqual(initial.filled_label_count, 1)
            self.assertEqual(initial.filled_supercategory_count, 1)
            self.assertEqual(initial.filled_direction_count, 1)
            self.assertEqual(len(preserved.conflicts), 3)
            self.assertEqual(preserved.overwrites, ())
            self.assertEqual(preserved_item.label, "User label")
            self.assertEqual(preserved_item.supercategory, "User group")
            self.assertEqual(preserved_item.direction, "+")
            self.assertEqual(overwritten.conflicts, ())
            self.assertEqual(len(overwritten.overwrites), 3)
            self.assertEqual(overwritten.updated_code_count, 1)
            self.assertEqual(overwritten_item.label, "Delivered label")
            self.assertEqual(overwritten_item.supercategory, "Delivered group")
            self.assertEqual(overwritten_item.direction, "-")

    def test_parses_flattened_wincross_net_groups_and_multi_code_rows(self) -> None:
        text = (
            "ECONOMY/JOBS^NET 4^NS,SK "
            "Economy^c13_1 S3(1)^NS,SK "
            "Worker\u00e2\u20ac\u2122s rights^(21)^NS,SK "
            "^ ^NS,DV "
            "PRO-CHOICE^NET 2^NS,SK "
            "Reproductive rights^(103,104)^NS,SK "
            "hidden^(1-999)^HR "
            "^ ^NS,RL,DV "
            "None^(96)^NS,SK,RL "
            "Don't know^(99,97)^NS,SK,RL"
        )

        entries = core.parse_wincross_codebook(text)
        by_code = {item.code: item for item in entries}

        self.assertEqual(set(by_code), {"1", "21", "96", "97", "99", "103", "104"})
        self.assertEqual(by_code["1"].label, "Economy")
        self.assertEqual(by_code["21"].label, "Worker\u2019s rights")
        self.assertEqual(by_code["21"].supercategory, "ECONOMY/JOBS")
        self.assertEqual(by_code["104"].supercategory, "PRO-CHOICE")
        self.assertEqual(by_code["96"].supercategory, "")
        self.assertEqual(by_code["99"].supercategory, "")

    def test_wincross_codebook_import_preserves_existing_metadata_and_reports_conflicts(self) -> None:
        with local_tmp() as temp:
            source = write_csv(temp / "data.csv", sample_rows())
            wincross = temp / "prior_tables.txt"
            wincross.write_text(
                "\n".join(
                    [
                        "ECONOMY/JOBS^NET 3^NS,SK",
                        "Imported banking label^(14)^NS,SK",
                        "New reusable category^(500)^NS,SK",
                        " ^ ^NS,DV",
                        "OTHER^NET 2^NS,SK,RL",
                        "Imported other label^(98)^NS,SK,RL",
                    ]
                ),
                encoding="utf-8",
            )
            with core.CodingSession(temp / "coding.sqlite") as session:
                session.import_data(source)
                question = session.questions()[0]
                session.upsert_code(
                    question.id,
                    "14",
                    label="Current banking label",
                    supercategory="CURRENT ECONOMY",
                )
                session.upsert_code(question.id, "98", label="Current other label")
                original_response = session.list_responses(question.id)[0]

                summary = session.import_wincross_codebook(wincross, question.id)
                banking = session.get_code(question.id, "14")
                other = session.get_code(question.id, "98")
                added = session.get_code(question.id, "500")
                unchanged_response = session.response(original_response.id)

            self.assertEqual(summary.parsed_code_count, 3)
            self.assertEqual(summary.added_code_count, 1)
            self.assertEqual(summary.updated_code_count, 1)
            self.assertEqual(summary.filled_supercategory_count, 1)
            self.assertEqual(len(summary.conflicts), 3)
            self.assertEqual(banking.label, "Current banking label")
            self.assertEqual(banking.supercategory, "CURRENT ECONOMY")
            self.assertEqual(other.label, "Current other label")
            self.assertEqual(other.supercategory, "OTHER")
            self.assertEqual(added.label, "New reusable category")
            self.assertEqual(added.supercategory, "ECONOMY/JOBS")
            self.assertFalse(unchanged_response.override_active)
            self.assertEqual(unchanged_response.final_codes, ("98",))

    def test_wincross_codebook_import_can_overwrite_existing_metadata(self) -> None:
        with local_tmp() as temp:
            source = write_csv(temp / "data.csv", sample_rows())
            wincross = temp / "prior_tables.txt"
            wincross.write_text(
                "OTHER^NET 2^NS,SK,RL\nImported other label^(98)^NS,SK,RL\n",
                encoding="utf-8",
            )
            with core.CodingSession(temp / "coding.sqlite") as session:
                session.import_data(source)
                question = session.questions()[0]
                session.upsert_code(
                    question.id,
                    "98",
                    label="Current other label",
                    supercategory="CURRENT OTHER",
                    direction="-",
                    active=False,
                )
                original_response = session.list_responses(question.id)[0]

                summary = session.import_wincross_codebook(
                    wincross,
                    question.id,
                    overwrite_existing=True,
                )
                updated = session.get_code(question.id, "98")
                unchanged_response = session.response(original_response.id)

            self.assertTrue(summary.overwrite_existing)
            self.assertEqual(summary.updated_code_count, 1)
            self.assertEqual(len(summary.overwrites), 2)
            self.assertEqual(summary.conflicts, ())
            self.assertEqual(updated.label, "Imported other label")
            self.assertEqual(updated.supercategory, "OTHER")
            self.assertEqual(updated.direction, "-")
            self.assertFalse(updated.active)
            self.assertFalse(unchanged_response.override_active)
            self.assertEqual(unchanged_response.final_codes, ("98",))

    def test_wincross_export_uses_final_assignments_and_codebook_metadata(self) -> None:
        with local_tmp() as temp:
            source = write_csv(temp / "data.csv", sample_rows())
            output = temp / "open_ends.wincross.txt"
            with core.CodingSession(temp / "coding.sqlite") as session:
                session.import_data(source)
                question = session.questions()[0]
                responses = session.list_responses(question.id)
                session.set_assignment(responses[0].id, ["500", "7"])
                session.set_assignment(responses[1].id, ["500"])
                session.upsert_code(
                    question.id,
                    "500",
                    label="Health care costs",
                    supercategory="HEALTH CARE",
                    direction="-",
                )
                session.upsert_code(
                    question.id,
                    "7",
                    label="Prescription drugs",
                    supercategory="HEALTH CARE",
                    direction="-",
                )

                summary = session.export_wincross_tables(output)

            text = output.read_text(encoding="utf-8")
            self.assertIn("ABLE TO MENTION^c16_1 S3 (7,500)^NS,RH", text)
            self.assertIn("NEGATIVE MENTIONS^(7,500)^NS,RH", text)
            self.assertIn("HEALTH CARE^NET 3^NS,SK", text)
            self.assertIn("Prescription drugs^(7)^NS,SK", text)
            self.assertIn("Health care costs^(500)^NS,SK", text)
            self.assertEqual(summary.question_count, 1)
            self.assertEqual(summary.code_count, 2)
            self.assertEqual(summary.unlabeled_codes, ())

    def test_wincross_export_combines_compatible_codes_with_the_same_label(self) -> None:
        with local_tmp() as temp:
            source = write_csv(temp / "data.csv", sample_rows())
            with core.CodingSession(temp / "coding.sqlite") as session:
                session.import_data(source)
                question = session.questions()[0]
                session.upsert_code(
                    question.id,
                    "103",
                    label="Reproductive rights",
                    supercategory="PRO-CHOICE",
                )
                session.upsert_code(
                    question.id,
                    "104",
                    label="Reproductive rights",
                    supercategory="PRO-CHOICE",
                )

                shared = session.codes_sharing_label(question.id, "Reproductive rights")
                text, _unlabeled, _code_count = session.render_wincross_tables()

            self.assertEqual([item.code for item in shared], ["103", "104"])
            self.assertIn("PRO-CHOICE^NET 2^NS,SK", text)
            self.assertIn("Reproductive rights^(103,104)^NS,SK", text)
            self.assertEqual(text.count("Reproductive rights^("), 1)

    def test_wincross_export_flags_used_codes_without_labels(self) -> None:
        with local_tmp() as temp:
            source = write_csv(temp / "data.csv", sample_rows())
            with core.CodingSession(temp / "coding.sqlite") as session:
                session.import_data(source)

                text, unlabeled, code_count = session.render_wincross_tables()

            self.assertIn("(Label not set - code 98)^(98)^NS,SK", text)
            self.assertEqual(unlabeled, ("q16:98",))
            self.assertEqual(code_count, 1)

    def test_wincross_export_places_other_none_and_dont_know_at_end_with_rl(self) -> None:
        with local_tmp() as temp:
            source = write_csv(temp / "data.csv", sample_rows())
            with core.CodingSession(temp / "coding.sqlite") as session:
                session.import_data(source)
                question = session.questions()[0]
                session.upsert_code(question.id, "1", label="Economy", supercategory="ECONOMY")
                session.upsert_code(question.id, "2", label="Other", supercategory="OTHER")
                session.upsert_code(question.id, "3", label="Miscellaneous", supercategory="")
                session.upsert_code(question.id, "4", label="Other detail", supercategory="OTHER")
                session.upsert_code(question.id, "96", label="None", supercategory="OTHER")
                session.upsert_code(question.id, "99", label="Don't know", supercategory="OTHER")

                text, _unlabeled, _code_count = session.render_wincross_tables()

            economy_at = text.index("ECONOMY^NET")
            ungrouped_at = text.index("Miscellaneous^(3)")
            other_at = text.index("OTHER^NET")
            none_at = text.index("None^(96)")
            dont_know_at = text.index("Don't know^(99)")
            self.assertLess(economy_at, ungrouped_at)
            self.assertLess(ungrouped_at, other_at)
            self.assertLess(other_at, none_at)
            self.assertLess(none_at, dont_know_at)
            self.assertIn("OTHER^NET 3^NS,SK,RL", text)
            self.assertIn("Other^(2)^NS,SK,RL", text)
            self.assertIn("Other detail^(4)^NS,SK", text)
            self.assertIn("None^(96)^NS,SK,RL", text)
            self.assertIn("Don't know^(99)^NS,SK,RL", text)
            able_to_mention = next(line for line in text.splitlines() if line.startswith("ABLE TO MENTION^"))
            self.assertNotIn("96", able_to_mention)
            self.assertNotIn("99", able_to_mention)


    def _repeated_survnum_rows(self) -> list[dict[str, str]]:
        return [
            {"Survnum": "1001", "Timeseries": "1", "q16": "Older answer", "c16_1": "10", "c16_2": "", "c16_3": ""},
            {"Survnum": "1001", "Timeseries": "2", "q16": "Newer answer", "c16_1": "98", "c16_2": "", "c16_3": ""},
            {"Survnum": "1002", "Timeseries": "2", "q16": "Another", "c16_1": "98", "c16_2": "", "c16_3": ""},
        ]

    def test_trended_data_keys_records_by_timeseries_and_survnum(self) -> None:
        with local_tmp() as temp:
            source = write_csv(temp / "data.csv", self._repeated_survnum_rows())
            with core.CodingSession(temp / "coding.sqlite") as session:
                summary = session.import_data(source, key_column="Survnum")
                question = session.questions()[0]
                responses = {item.record_key: item for item in session.list_responses(question.id)}
                session.set_assignment(responses["2|1001"].id, ["500"])
                session.upsert_code(question.id, "500", label="New code")
                session.export_coded_csv(temp / "coded.csv")

            self.assertEqual(summary.key_column, "Timeseries + Survnum")
            self.assertEqual(set(responses), {"1|1001", "2|1001", "2|1002"})
            with (temp / "coded.csv").open(encoding="utf-8-sig", newline="") as handle:
                exported = [(row["Timeseries"], row["Survnum"], row["c16_1"]) for row in csv.DictReader(handle)]
            self.assertEqual(exported, [("1", "1001", "10"), ("2", "1001", "500"), ("2", "1002", "98")])

    def test_trended_data_rejects_repeated_pair_within_a_wave(self) -> None:
        rows = self._repeated_survnum_rows()
        rows[2]["Survnum"] = "1001"
        with local_tmp() as temp:
            source = write_csv(temp / "data.csv", rows)
            with core.CodingSession(temp / "coding.sqlite") as session:
                with self.assertRaisesRegex(ValueError, r"Timeseries \+ Survnum is not unique: 2\|1001"):
                    session.import_data(source)

    def test_single_key_session_is_converted_to_pairs_with_overrides_kept(self) -> None:
        rows = [row for row in self._repeated_survnum_rows() if row["Survnum"] == "1002" or row["Timeseries"] == "1"]
        with local_tmp() as temp:
            database = temp / "coding.sqlite"
            source = write_csv(temp / "data.csv", rows)
            with core.CodingSession(database) as session:
                session.import_data(source)
                question = session.questions()[0]
                # Simulate a session saved before pair keys: plain Survnum keys.
                session.connection.execute("UPDATE responses SET record_key = substr(record_key, instr(record_key, '|') + 1)")
                session.connection.execute("UPDATE datasets SET key_column='Survnum'")
                session.connection.commit()
                old = {item.record_key: item for item in session.list_responses(question.id)}
                self.assertEqual(set(old), {"1001", "1002"})
                session.set_assignment(old["1002"].id, ["500"])

            source = write_csv(temp / "data2.csv", self._repeated_survnum_rows())
            with core.CodingSession(database) as session:
                summary = session.import_data(source, key_column="Survnum")
                question = session.questions()[0]
                responses = {item.record_key: item for item in session.list_responses(question.id)}

            self.assertEqual(set(responses), {"1|1001", "2|1001", "2|1002"})
            self.assertEqual(summary.new_response_count, 1)
            self.assertEqual(summary.preserved_override_count, 1)
            self.assertEqual(responses["2|1002"].final_codes, ("500",))
            self.assertFalse(responses["2|1001"].override_active)


if __name__ == "__main__":
    unittest.main()
