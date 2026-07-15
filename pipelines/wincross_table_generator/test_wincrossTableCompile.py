import sys
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from wincrossTableCompile import (  # noqa: E402
    Question,
    ResponseOption,
    Table,
    LIKELY_SUMMARY_BANNER,
    build_battery_summary_tables,
    build_branch_pid_summary_full_additive,
    build_branch_pid_summary_partial,
    build_tables,
    clean_text,
    default_table,
    is_age_bucket_10,
    parse_survey,
    rule_describes_well_5pt,
    rule_candidate_battery_header,
    rule_country_mood_summary,
    rule_favorability_0_10,
    rule_more_less_favorability_4pt,
    rule_persuasion_summary,
    rule_past_presidential_vote,
    rule_race_on_file,
    rule_right_direction_us,
    rule_vote_choice_split_table,
    rule_vote_choice_with_leans,
)


class WincrossTableCompileTests(unittest.TestCase):
    def test_clean_text_preserves_sentence_double_spaces(self) -> None:
        self.assertEqual(
            clean_text("Sentence one.  Sentence two."),
            "Sentence one.  Sentence two.",
        )
        self.assertEqual(
            clean_text("Sentence one.\nSentence two."),
            "Sentence one. Sentence two.",
        )

    def test_default_table_title_gets_double_spaces_between_sentences(self) -> None:
        q = Question(
            qid="5",
            qnum="5",
            title="Do you approve of the U.S. Congress? Now thinking about Dr. Smith, do you approve.",
            options=[
                ResponseOption("1", "Yes"),
                ResponseOption("2", "No"),
            ],
        )

        table = default_table(q, "TQ5^9005")

        self.assertEqual(
            table.header,
            "Q5. Do you approve of the U.S. Congress?  Now thinking about Dr. Smith, do you approve.",
        )
        self.assertNotIn("U.S.  Congress", table.header)
        self.assertNotIn("Dr.  Smith", table.header)

    def test_candidate_battery_header_gets_double_spaces_between_sentences(self) -> None:
        q = Question(
            qid="16a",
            qnum="16",
            title="Now you are going to hear some reasons to vote against Eric Conroy.",
            item_text=(
                "a. [TRUMP - SPLIT C] Conroy called himself the MAGA candidate and is endorsed by "
                "Donald Trump. He supported Trump's plan. Conroy will be a rubberstamp."
            ),
            options=[
                ResponseOption("1", "Much less likely"),
                ResponseOption("2", "Somewhat less likely"),
                ResponseOption("3", "No difference"),
                ResponseOption("4", "More likely"),
                ResponseOption("5", "Not true"),
                ResponseOption("6", "(Don't know)"),
            ],
        )
        setattr(q, "_stem_common", True)
        table = default_table(q, "TQ16a^9024")

        rule_candidate_battery_header(table, q)

        self.assertIn("Donald Trump.  He supported", table.header)
        self.assertIn("plan.  Conroy will", table.header)
        self.assertNotIn("Q16a.  Conroy", table.header)

    def test_local_mood_scale_gets_positive_negative_summary_lines(self) -> None:
        q = Question(
            qid="4",
            qnum="4",
            title="And how do you feel about the way things are going in Providence today?",
            options=[
                ResponseOption("1", "Enthusiastic"),
                ResponseOption("2", "Satisfied, but not enthusiastic"),
                ResponseOption("3", "Dissatisfied, but not angry"),
                ResponseOption("4", "Angry"),
                ResponseOption("5", "(Don't know)"),
            ],
        )
        table = default_table(q, "TQ4^9004")

        rule_country_mood_summary(table, q)

        self.assertIn(" TOTAL POSITIVE^(1,2)^NS", table.lines)
        self.assertIn(" TOTAL NEGATIVE^(3,4)^NS", table.lines)

    def test_digital_and_mail_questions_get_communication_summary(self) -> None:
        q14 = Question(
            qid="14",
            qnum="14",
            title=(
                "In the last few weeks, have you seen any ads on television, your phone, "
                "or your computer about Brett Smiley?"
            ),
            options=[
                ResponseOption("1", "Yes"),
                ResponseOption("2", "No"),
                ResponseOption("3", "(Don't know)"),
            ],
        )
        q15 = Question(
            qid="15",
            qnum="15",
            title="In the last few weeks, have you gotten anything in the mail about Brett Smiley?",
            options=[
                ResponseOption("1", "Yes"),
                ResponseOption("2", "No"),
                ResponseOption("3", "(Don't know)"),
            ],
        )

        tables = build_tables([q14, q15], [])
        summary = next(t for t in tables if t.header == "Summary Table - Smiley Communication")

        self.assertTrue(summary.table_id.startswith("TQ15sum^"))
        self.assertEqual(summary.banner, "OV,OI2,O%,BR,RV,S2,P0,SA,SP")
        self.assertEqual(
            summary.lines,
            [
                " TOTAL ANSWERING^TN^1",
                " Digital^Q14(1)^NS",
                " Mail^Q15(1)^NS",
                " Any^Q14(1) OR Q15(1)^NS",
                " None^NOT Q14(1) AND NOT Q15(1)^NS",
            ],
        )

    def test_second_choice_question_appends_first_choice_combo_sections(self) -> None:
        q5 = Question(
            qid="5",
            qnum="5",
            title="Democratic Primary Vote for Governor",
            options=[
                ResponseOption("1", "Rodriguez"),
                ResponseOption("2", "(Lean Rodriguez)"),
                ResponseOption("3", "Barnes"),
                ResponseOption("4", "(Lean Barnes)"),
                ResponseOption("5", "Brennan"),
                ResponseOption("6", "(Lean Brennan)"),
                ResponseOption("7", "Crowley"),
                ResponseOption("8", "(Lean Crowley)"),
                ResponseOption("9", "Hong"),
                ResponseOption("10", "(Lean Hong)"),
                ResponseOption("13", "Roys"),
                ResponseOption("14", "(Lean Roys)"),
                ResponseOption("16", "(Undecided)"),
            ],
        )
        q6 = Question(
            qid="6",
            qnum="6",
            title=(
                "Sometimes the field of candidates changes. If your first-choice candidate "
                "was not available, who would be your second choice in the Democratic primary "
                "for Governor?"
            ),
            options=[
                ResponseOption("1", "Rodriguez"),
                ResponseOption("2", "Barnes"),
                ResponseOption("3", "Brennan"),
                ResponseOption("4", "Crowley"),
                ResponseOption("5", "Hong"),
                ResponseOption("7", "Roys"),
                ResponseOption("8", "No second choice"),
            ],
        )

        tables = build_tables([q5, q6], [])
        table = next(t for t in tables if t.table_id.startswith("TQ6^"))

        self.assertIn(" RODRIGUEZ VOTERS^Q5(1,2)^NS,SK", table.lines)
        self.assertIn(" Barnes^Q6(2) AND Q5(1,2)^NS", table.lines)
        self.assertIn(" Roys^Q6(7) AND Q5(1,2)^NS", table.lines)
        self.assertIn(" No second choice^Q6(8) AND Q5(1,2)^NS", table.lines)
        self.assertNotIn(" Rodriguez^Q6(1) AND Q5(1,2)^NS", table.lines)
        self.assertIn(" BARNES VOTERS^Q5(3,4)^NS,SK", table.lines)
        self.assertIn(" Rodriguez^Q6(1) AND Q5(3,4)^NS", table.lines)
        self.assertNotIn(" Barnes^Q6(2) AND Q5(3,4)^NS", table.lines)
        self.assertIn(" ROYS VOTERS^Q5(13,14)^NS,SK", table.lines)
        self.assertIn(" Hong^Q6(5) AND Q5(13,14)^NS", table.lines)
        self.assertNotIn(" Roys^Q6(7) AND Q5(13,14)^NS", table.lines)

    def test_second_choice_question_matches_choice_from_q_instruction_and_name_variants(self) -> None:
        q15 = Question(
            qid="15",
            qnum="15",
            title=(
                "Thinking again, if the Democratic primary for Attorney General was held today "
                "and the candidates were: Kim Ahern Keith Hoffmann Jason Knight Joe Solomon Junior "
                "for whom would you vote? well, toward whom do you lean?"
            ),
            options=[
                ResponseOption("1", "Ahern"),
                ResponseOption("2", "(Lean Ahern)"),
                ResponseOption("3", "Hoffmann"),
                ResponseOption("4", "(Lean Hoffmann)"),
                ResponseOption("5", "Knight"),
                ResponseOption("6", "(Lean Knight)"),
                ResponseOption("7", "Solomon"),
                ResponseOption("8", "(Lean Solomon)"),
                ResponseOption("9", "(Undecided)"),
            ],
        )
        q16 = Question(
            qid="16",
            qnum="16",
            title="And who would be your second choice in the Democratic primary for Attorney General?",
            instructions=["[IF Q15=1-8]", "[RANDOMIZE, DO NOT READ CHOICE FROM Q15]"],
            options=[
                ResponseOption("1", "Kim Ahern"),
                ResponseOption("2", "Keith Hoffman"),
                ResponseOption("3", "Jason Knight"),
                ResponseOption("4", "Joe Solomon"),
                ResponseOption("8", "(Undecided)"),
            ],
        )

        tables = build_tables([q15, q16], [])
        table = next(t for t in tables if t.table_id.startswith("TQ16^"))

        self.assertIn(" AHERN VOTERS^Q15(1,2)^NS,SK", table.lines)
        self.assertIn(" Keith Hoffman^Q16(2) AND Q15(1,2)^NS", table.lines)
        self.assertNotIn(" Kim Ahern^Q16(1) AND Q15(1,2)^NS", table.lines)
        self.assertIn(" HOFFMANN VOTERS^Q15(3,4)^NS,SK", table.lines)
        self.assertIn(" Kim Ahern^Q16(1) AND Q15(3,4)^NS", table.lines)
        self.assertNotIn(" Keith Hoffman^Q16(2) AND Q15(3,4)^NS", table.lines)
        self.assertIn(" SOLOMON VOTERS^Q15(7,8)^NS,SK", table.lines)
        self.assertIn(" (Undecided)^Q16(8) AND Q15(7,8)^NS", table.lines)

    def test_partial_branch_pid_splits_independent_and_another_party(self) -> None:
        q1 = Question(
            qid="1",
            qnum="1",
            title="Party registration",
            options=[
                ResponseOption("1", "Democrat"),
                ResponseOption("2", "Independent"),
                ResponseOption("3", "Republican"),
                ResponseOption("4", "Another party"),
            ],
        )
        q2 = Question(
            qid="2",
            qnum="2",
            title="Democratic strength",
            instructions=["[IF Q1=1]"],
            options=[
                ResponseOption("1", "Strong Democrat"),
                ResponseOption("2", "Not so strong Democrat"),
            ],
        )
        q3 = Question(
            qid="3",
            qnum="3",
            title="Party lean",
            instructions=["[IF Q1=2,4]"],
            options=[
                ResponseOption("1", "Democratic Party"),
                ResponseOption("TERMINATE", "Republican Party"),
                ResponseOption("3", "Neither"),
            ],
        )

        table, _ = build_branch_pid_summary_partial(q1, q2, q3, 9003)

        self.assertEqual(table.header, "Q1/Q2/Q3. Party Identification")
        self.assertIn(" Weak Democrat^Q2(2)^NS", table.lines)
        self.assertIn(" Ind/Lean Democrat^Q3(1)^NS", table.lines)
        self.assertIn(" Independent^Q1(2) AND Q3(3)^NS", table.lines)
        self.assertIn(" Another Party^Q1(4) AND Q3(3)^NS", table.lines)
        self.assertIn(" Ind/Lean Republican^Q3(2)^NS,SK", table.lines)
        self.assertIn(" Republican^Q1(3)^NS", table.lines)
        self.assertNotIn(" Not so strong Democrat^Q2(2)^NS", table.lines)
        self.assertNotIn(" Closer to Democratic Party^Q3(1)^NS", table.lines)
        self.assertNotIn(" Neither^Q3(3)^NS", table.lines)

    def test_full_additive_branch_pid_uses_canonical_labels(self) -> None:
        q1 = Question(
            qid="1",
            qnum="1",
            title="Party registration",
            options=[
                ResponseOption("1", "Democrat"),
                ResponseOption("2", "Independent"),
                ResponseOption("3", "Republican"),
                ResponseOption("4", "Another party"),
            ],
        )
        q2 = Question(
            qid="2",
            qnum="2",
            title="Democratic strength",
            instructions=["[IF Q1=1]"],
            options=[
                ResponseOption("1", "Strong Democrat"),
                ResponseOption("2", "Not so strong Democrat"),
            ],
        )
        q3 = Question(
            qid="3",
            qnum="3",
            title="Republican strength",
            instructions=["[IF Q1=3]"],
            options=[
                ResponseOption("1", "Strong Republican"),
                ResponseOption("2", "Not so strong Republican"),
            ],
        )
        q4 = Question(
            qid="4",
            qnum="4",
            title="Party lean",
            instructions=["[IF Q1=2]"],
            options=[
                ResponseOption("1", "Democratic Party"),
                ResponseOption("2", "Republican Party"),
                ResponseOption("3", "Neither"),
            ],
        )

        table, _ = build_branch_pid_summary_full_additive(q1, q2, q3, q4, 9003)

        self.assertIn(" Weak Democrat^Q2(2)^NS", table.lines)
        self.assertIn(" Ind/Lean Democrat^Q4(1)^NS", table.lines)
        self.assertIn(" Independent^Q4(3)^NS", table.lines)
        self.assertIn(" Ind/Lean Republican^Q4(2)^NS", table.lines)
        self.assertIn(" Weak Republican^Q3(2)^NS", table.lines)
        self.assertIn(" Strong Republican^Q3(1)^NS", table.lines)
        self.assertIn(" Another Party^Q1(4)^NS", table.lines)

    def test_favorability_0_10_uses_cant_rate_then_never_heard(self) -> None:
        q = Question(
            qid="7a",
            qnum="7",
            title="favorability battery",
            item_text="a. Donald Trump",
            options=[ResponseOption(str(i), str(i)) for i in range(11)]
            + [
                ResponseOption("11", "Can't rate"),
                ResponseOption("12", "Never heard"),
            ],
            question_type="favorability_0_10",
            question_group="favorability",
            classification_groups=["favorability"],
        )
        table = Table(table_id="TQ7a^9009", banner="", header="", lines=[])

        rule_favorability_0_10(table, q)

        self.assertIn(" Can't rate^(11)^NS", table.lines)
        self.assertIn(" Never heard^(12)^NS", table.lines)
        self.assertNotIn(" Never heard^(11)^NS", table.lines)
        self.assertNotIn(" Don't know^(12)^NS", table.lines)

    def test_favorability_0_10_battery_gets_extremely_unfavorable_summary_table(self) -> None:
        def fav_item(qid: str, item_text: str) -> Question:
            return Question(
                qid=qid,
                qnum="7",
                title="Now, please read a list of public figures and organizations and select whether you have a favorable or unfavorable opinion of each person or group using a scale that runs from 0 to 10.",
                item_text=item_text,
                options=[ResponseOption(str(i), str(i)) for i in range(11)]
                + [
                    ResponseOption("11", "Can't rate"),
                    ResponseOption("12", "Never heard"),
                ],
                question_type="favorability_0_10",
                question_group="favorability",
                classification_groups=["favorability"],
            )

        items = [
            fav_item("7a", "a. Donald Trump"),
            fav_item("7d", "d. Immigration and Customs Enforcement or ICE"),
            fav_item("7e", "e. The National Rifle Association or NRA"),
            fav_item("7l", "l. The cryptocurrency industry"),
        ]

        tables, _ = build_battery_summary_tables("7", items, 9128)

        self.assertEqual(len(tables), 1)
        table = tables[0]
        self.assertEqual(table.table_id, "TQ7^9129")
        self.assertEqual(table.banner, "OV,OD,OI2,O%,R%,BR,RV,S2,P0,SA,SP")
        self.assertEqual(table.header, "Q7. Summary Table - Extremely Unfavorable (0)")
        self.assertEqual(table.lines[0], " TOTAL ANSWERING^TN^1")
        self.assertIn(" a. Donald Trump^Q7a(0)^NS", table.lines)
        self.assertIn(" d. ICE^Q7d(0)^NS", table.lines)
        self.assertIn(" e. The NRA^Q7e(0)^NS", table.lines)
        self.assertIn(" l. Cryptocurrency industry^Q7l(0)^NS", table.lines)
        self.assertEqual(table.lines[-1], " hidden^Q7a(0-12)^HR,NS")

    def test_describes_well_battery_gets_summary_tables(self) -> None:
        def item(qid: str, item_text: str) -> Question:
            return Question(
                qid=qid,
                qnum="15",
                title=(
                    "Please tell me how well it describes Brett Smiley on a 1 to 5 scale, "
                    "where 5 means it describes him extremely well and 1 means that it does not describe him at all."
                ),
                item_text=item_text,
                options=[
                    ResponseOption("1", "1 - Not at all"),
                    ResponseOption("2", "2"),
                    ResponseOption("3", "3"),
                    ResponseOption("4", "4"),
                    ResponseOption("5", "5 - Extremely well"),
                    ResponseOption("6", "(Don't know)"),
                ],
                question_type="candidate_trait_well_4pt",
            )

        tables, _ = build_battery_summary_tables(
            "15",
            [
                item("15a", "a. Cares about people like you"),
                item("15b", "b. Shares your values"),
            ],
            9016,
        )

        self.assertEqual(len(tables), 3)
        self.assertEqual(tables[0].header, "Q15. Summary Table - Extremely Well")
        self.assertIn(" a. Cares about people like you^Q15a(5)^NS", tables[0].lines)
        self.assertEqual(tables[1].header, "Q15. Summary Table - Total Well")
        self.assertIn(" b. Shares your values^Q15b(4,5)^NS", tables[1].lines)
        self.assertEqual(tables[2].header, "Q15. Summary Table - Total Well minus Not Well")
        self.assertIn(" a. Cares about people like you^CALC V1 - V3^NS", tables[2].lines)
        self.assertEqual(tables[2].lines[-1], " ^Q15a(1-5)^HR,NS")

    def test_four_point_describes_well_battery_gets_summary_tables(self) -> None:
        def item(qid: str, item_text: str) -> Question:
            return Question(
                qid=qid,
                qnum="15",
                title=(
                    "Now you will hear some descriptions and I'd like to know how well you think each one "
                    "describes Frank Mrvan.  Here's the first one.  Does that describe him very well, "
                    "somewhat well, or not well?"
                ),
                item_text=item_text,
                options=[
                    ResponseOption("1", "1"),
                    ResponseOption("2", "2"),
                    ResponseOption("3", "3"),
                    ResponseOption("4", "4"),
                ],
            )

        q1 = item("15a", "a. Works hard for the people of the district")
        q2 = item("15b", "b. Stays in touch with the people")
        tables, _ = build_battery_summary_tables("15", [q1, q2], 9026)

        self.assertEqual(len(tables), 3)
        self.assertEqual(tables[0].header, "Q15. Summary Table - Very Well")
        self.assertIn(" a. Works hard for the people of the district^Q15a(1)^NS", tables[0].lines)
        self.assertEqual(tables[1].header, "Q15. Summary Table - Total Well")
        self.assertIn(" b. Stays in touch with the people^Q15b(1,2)^NS", tables[1].lines)
        self.assertEqual(tables[2].header, "Q15. Summary Table - Total Well minus Not Well")
        self.assertIn(" a. Works hard for the people of the district^Q15a(3)^HR,NS", tables[2].lines)
        self.assertEqual(tables[2].lines[-1], " ^Q15a(1-3)^HR,NS")

    def test_four_point_describes_well_item_renders_labels(self) -> None:
        q = Question(
            qid="15a",
            qnum="15",
            title=(
                "Now you will hear some descriptions and I'd like to know how well you think each one "
                "describes Frank Mrvan.  Does that describe him very well, somewhat well, or not well?"
            ),
            item_text="a. Works hard for the people of the district",
            options=[
                ResponseOption("1", "1"),
                ResponseOption("2", "2"),
                ResponseOption("3", "3"),
                ResponseOption("4", "4"),
            ],
        )
        table = default_table(q, "TQ15a^9021")

        rule_describes_well_5pt(table, q)

        self.assertEqual(table.header, "Q15a. Describes Mrvan - Works hard for the people of the district")
        self.assertIn(" Very well^Q15a(1)^NS", table.lines)
        self.assertIn(" Somewhat well^(2)^NS", table.lines)
        self.assertIn(" Not well^(3)^NS", table.lines)
        self.assertIn(" (Don't know)^(4)^NS", table.lines)
        self.assertIn(" TOTAL WELL^(1-2)^NS", table.lines)

    def test_compact_describes_well_matrix_expands_to_items(self) -> None:
        survey = {
            "elements": [
                {
                    "type": "question",
                    "qnum": "12",
                    "qid": "12",
                    "text": (
                        "Please tell me how well it describes Brett Smiley on a 1 to 5 scale, "
                        "where 5 means it describes him extremely well and 1 means that it does not describe him at all."
                    ),
                    "response_options": [
                        {"value": "1", "text": "Cares about people like you"},
                        {"value": "3", "text": "2"},
                        {"value": "6", "text": "4 5"},
                        {"value": "1", "text": "Shares your values"},
                        {"value": "3", "text": "2"},
                        {"value": "6", "text": "4 5"},
                    ],
                    "question_type": "candidate_trait_well_4pt",
                }
            ]
        }

        questions = parse_survey(survey)
        self.assertEqual([q.qid for q in questions], ["12a", "12b"])
        self.assertEqual(questions[0].item_text, "a. Cares about people like you")
        self.assertEqual([opt.value for opt in questions[0].options], ["1", "2", "3", "4", "5", "6"])

    def test_more_less_favorability_5pt_with_not_true_gets_total_lines(self) -> None:
        q = Question(
            qid="17a",
            qnum="17",
            title="More or less favorable battery item",
            options=[
                ResponseOption("1", "Much more favorable"),
                ResponseOption("2", "Somewhat more favorable"),
                ResponseOption("3", "Somewhat less favorable"),
                ResponseOption("4", "Much less favorable"),
                ResponseOption("5", "Not true"),
            ],
        )
        table = Table(table_id="TQ17a^9031", banner="", header="", lines=[])

        rule_more_less_favorability_4pt(table, q)

        self.assertIn(" Not true^(5)^NS", table.lines)
        self.assertIn(" TOTAL MORE FAVORABLE^(1,2)^NS", table.lines)
        self.assertIn(" TOTAL LESS FAVORABLE^(3,4)^NS", table.lines)

    def test_more_likely_battery_with_not_true_before_less_likely_gets_total_line(self) -> None:
        q = Question(
            qid="16a",
            qnum="16",
            title="Now, you will read a little more about one of the candidates for mayor.",
            item_text="a. [SERVICES] Smiley is improving city services",
            options=[
                ResponseOption("1", "Much more likely"),
                ResponseOption("2", "Somewhat more likely"),
                ResponseOption("3", "No difference"),
                ResponseOption("4", "Not true"),
                ResponseOption("5", "Less likely"),
                ResponseOption("6", "(Don't know)"),
            ],
        )
        table = default_table(q, "TQ16a^9040")

        rule_persuasion_summary(table, q)

        self.assertIn(" Much more likely^Q16a(1)^NS", table.lines)
        self.assertIn(" Somewhat more likely^(2)^NS", table.lines)
        self.assertIn(" No difference^(3)^NS", table.lines)
        self.assertIn(" Not true^(4)^NS", table.lines)
        self.assertIn(" Less likely^(5)^NS", table.lines)
        self.assertIn(" TOTAL MORE LIKELY^(1-2)^NS", table.lines)

    def test_more_likely_battery_summary_uses_bare_less_likely_as_opposite(self) -> None:
        def item(qid: str, item_text: str) -> Question:
            return Question(
                qid=qid,
                qnum="16",
                title=(
                    "Now, you will read a little more about one of the candidates for mayor. "
                    "For each one, please select if that statement makes you much more likely to vote for Brett Smiley "
                    "or somewhat more likely to vote for him."
                ),
                item_text=item_text,
                options=[
                    ResponseOption("1", "Much more likely"),
                    ResponseOption("2", "Somewhat more likely"),
                    ResponseOption("3", "No difference"),
                    ResponseOption("4", "Not true"),
                    ResponseOption("5", "Less likely"),
                    ResponseOption("6", "(Don't know)"),
                ],
            )

        tables, _ = build_battery_summary_tables(
            "16",
            [
                item("16a", "a. [SERVICES] Smiley is improving city services"),
                item("16b", "b. [SAFETY] Smiley is improving public safety"),
            ],
            9039,
        )

        self.assertEqual(len(tables), 3)
        self.assertTrue(all(t.banner == LIKELY_SUMMARY_BANNER for t in tables))
        self.assertEqual(tables[0].header, "Q16. Summary Table - Smiley Much More Likely")
        self.assertIn(" a. Services^Q16a(1)^NS", tables[0].lines)
        self.assertEqual(tables[1].header, "Q16. Summary Table - Smiley Total More Likely")
        self.assertIn(" a. Services^Q16a(1,2)^NS", tables[1].lines)
        self.assertEqual(tables[2].header, "Q16. Summary Table - Smiley Total More Likely minus Less Likely")
        self.assertIn(" a. Services^Q16a(5)^HR,NS", tables[2].lines)

    def test_numeric_placeholder_more_likely_battery_gets_summary_tables(self) -> None:
        def item(qid: str, item_text: str) -> Question:
            return Question(
                qid=qid,
                qnum="19",
                title=(
                    "For each, please tell me if that statement makes you much more likely to vote for "
                    "Frank Mrvan, somewhat more likely to vote for him, or whether the statement makes "
                    "no difference to you either way."
                ),
                item_text=item_text,
                options=[
                    ResponseOption("1", "1"),
                    ResponseOption("2", "2"),
                    ResponseOption("3", "3"),
                    ResponseOption("4", "4"),
                    ResponseOption("5", "5"),
                ],
            )

        q1 = item("19a", "a. [INFRASTRUCTURE] Mrvan helped pass infrastructure projects along the Calumet [CAL-you-MET] river")
        q2 = item("19b", "b. [STEEL] Mrvan is endorsed by the United Steelworkers")

        table = default_table(q1, "TQ19a^9033")
        rule_persuasion_summary(table, q1)
        self.assertIn(" Much more likely^Q19a(1)^NS", table.lines)
        self.assertIn(" Somewhat more likely^(2)^NS", table.lines)
        self.assertIn(" No difference^(3)^NS", table.lines)
        self.assertIn(" Less likely^(4)^NS", table.lines)
        self.assertIn(" (Don't know)^(5)^NS", table.lines)
        self.assertIn(" TOTAL MORE LIKELY^(1-2)^NS", table.lines)

        tables, _ = build_battery_summary_tables("19", [q1, q2], 9038)
        self.assertEqual(len(tables), 3)
        self.assertTrue(all(t.banner == LIKELY_SUMMARY_BANNER for t in tables))
        self.assertEqual(tables[0].header, "Q19. Summary Table - Mrvan Much More Likely")
        self.assertIn(" a. Infrastructure^Q19a(1)^NS", tables[0].lines)
        self.assertEqual(tables[1].header, "Q19. Summary Table - Mrvan Total More Likely")
        self.assertIn(" b. Steel^Q19b(1,2)^NS", tables[1].lines)
        self.assertEqual(tables[2].header, "Q19. Summary Table - Mrvan Total More Likely minus Less Likely")
        self.assertIn(" a. Infrastructure^Q19a(4)^HR,NS", tables[2].lines)
        self.assertEqual(tables[2].lines[-1], " ^Q19a(1-4)^HR,NS")

    def test_battery_summary_bracket_tags_use_sentence_case(self) -> None:
        def item(qid: str, item_text: str, title_extra: str = "") -> Question:
            return Question(
                qid=qid,
                qnum="11",
                title=(
                    "Now, I'd like to tell you a little more about one of the candidates for Congress. "
                    "For each one, please tell me if that statement makes you much more likely to vote for Dorothy McAuliffe, "
                    "somewhat more likely to vote for her, or if the statement makes no difference to you. "
                    f"{title_extra}"
                ),
                item_text=item_text,
                options=[
                    ResponseOption("1", "Much more likely"),
                    ResponseOption("2", "Somewhat more likely"),
                    ResponseOption("3", "No difference"),
                    ResponseOption("4", "Less likely"),
                    ResponseOption("5", "Not true"),
                    ResponseOption("6", "(Don't know)"),
                ],
            )

        tables, _ = build_battery_summary_tables(
            "11",
            [
                item("11a", "a. [HUNGER - SPLIT A] Test item"),
                item("11b", "b. [HEALTH CARE] Another item"),
                item("11c", "c. [ICE - COSTS] Another item", "ICE is mentioned outside the bracket."),
            ],
            9020,
        )

        self.assertIn(" a. Hunger - A^Q11a(1)^NS", tables[0].lines)
        self.assertIn(" b. Health care^Q11b(1)^NS", tables[0].lines)
        self.assertIn(" c. ICE - Costs^Q11c(1)^NS", tables[0].lines)

    def test_less_likely_battery_summary_adds_much_less_minus_not_true_more_likely(self) -> None:
        def item(qid: str, item_text: str) -> Question:
            return Question(
                qid=qid,
                qnum="19",
                title=(
                    "For each one, please tell me if that statement makes you much less likely "
                    "to support Abdul El-Sayed."
                ),
                item_text=item_text,
                options=[
                    ResponseOption("1", "Much less likely"),
                    ResponseOption("2", "Somewhat less likely"),
                    ResponseOption("3", "No difference"),
                    ResponseOption("4", "More likely"),
                    ResponseOption("5", "Not true"),
                    ResponseOption("6", "(Don't know)"),
                ],
            )

        tables, _ = build_battery_summary_tables(
            "19",
            [
                item("19a", "a. [MM - LIAR] Test item"),
                item("19f", "f. [AES - LAWSUIT] Another item"),
            ],
            9044,
        )

        self.assertEqual(len(tables), 4)
        self.assertTrue(all(t.banner == LIKELY_SUMMARY_BANNER for t in tables))
        self.assertEqual(tables[3].header, "Q19. Summary Table - Much Less Likely minus Not True/More Likely")
        self.assertIn(" a. MM - Liar^Q19a(1)^HR,NS", tables[3].lines)
        self.assertIn(" f. AES - Lawsuit^Q19f(4,5)^HR,NS", tables[3].lines)
        self.assertIn(" a. MM - Liar^CALC V1 - V3^NS", tables[3].lines)
        self.assertEqual(tables[3].lines[-1], " ^Q19a(1-5)^HR,NS")

    def test_split_argument_battery_summary_adds_split_conditions_and_combo(self) -> None:
        def item(qid: str, item_text: str) -> Question:
            return Question(
                qid=qid,
                qnum="16",
                title=(
                    "Now you are going to hear some reasons to vote against Eric Conroy. "
                    "After each one, tell me if that statement makes you much less likely "
                    "to vote for him, somewhat less likely to vote for him, or whether the "
                    "statement makes no difference to you either way."
                ),
                item_text=item_text,
                options=[
                    ResponseOption("1", "Much less likely"),
                    ResponseOption("2", "Somewhat less likely"),
                    ResponseOption("3", "No difference"),
                    ResponseOption("4", "More likely"),
                    ResponseOption("5", "Not true"),
                    ResponseOption("6", "(Don't know)"),
                ],
            )

        tables, _ = build_battery_summary_tables(
            "16",
            [
                item("16a", "a. [TRUMP - SPLIT C] Conroy called himself the MAGA candidate"),
                item("16b", "b. [GOP - SPLIT D] Conroy is backed by the Republican establishment"),
                item("16c", "c. [OBBB] Conroy supports Trump's economic agenda"),
                item("16d", "d. [HEALTH CARE] Conroy supported policies"),
                item("16e", "e. [TARIFFS] Conroy called Trump's tariffs needed"),
                item("16f", "f. [RICH KID] Conroy says he grew up blue collar"),
                item("16g", "g. [CRYPTO] Conroy's campaign was bankrolled"),
                item("16h", "h. [SURVEILLANCE] Conroy called for more spending"),
                item("16i", "i. [DATA CENTERS] Conroy supports artificial intelligence"),
                item("16j", "j. [SNAP] Conroy supported tax cuts"),
            ],
            9033,
        )

        self.assertIn(" a. Trump - C^Q16a(1) and num_cd(1)^NS,11", tables[0].lines)
        self.assertIn(" b. GOP - D^Q16b(1) and num_cd(2)^NS,12", tables[0].lines)
        self.assertIn(" c. OBBB^Q16c(1)^NS", tables[0].lines)
        self.assertIn(" f. Rich Kid^Q16f(1)^NS", tables[0].lines)
        self.assertIn(" HIDE^num_cd(1)^hr", tables[0].lines)
        self.assertIn(" HIDE^num_cd(2)^hr", tables[0].lines)
        self.assertIn(
            " a/b. Combo^{Q16a(1) and num_cd(1)} OR {Q16b(1) and num_cd(2)}^NS",
            tables[0].lines,
        )
        self.assertIn(" a. Trump - C^Q16a(1,2) and num_cd(1)^NS,11", tables[1].lines)
        self.assertIn(" b. GOP - D^Q16b(1,2) and num_cd(2)^NS,12", tables[1].lines)
        self.assertIn(
            " a/b. Combo^{Q16a(1,2) and num_cd(1)} OR {Q16b(1,2) and num_cd(2)}^NS",
            tables[1].lines,
        )

    def test_vote_against_title_names_less_likely_battery_from_target_last_name(self) -> None:
        q = Question(
            qid="22a",
            qnum="22",
            title=(
                "Now you are going to hear some reasons to vote against Barb Regnitz. "
                "After each one, tell me if that statement makes you much less likely to vote for her."
            ),
            item_text="a. [CHOICE] Regnitz praised Indiana Right to Life",
            options=[
                ResponseOption("1", "Much less likely"),
                ResponseOption("2", "Somewhat less likely"),
                ResponseOption("3", "No difference"),
                ResponseOption("4", "More likely"),
                ResponseOption("5", "Not true"),
                ResponseOption("6", "(Don't know)"),
            ],
        )
        setattr(q, "_stem_common", True)
        table = default_table(q, "TQ22a^9044")

        rule_candidate_battery_header(table, q)

        self.assertEqual(
            table.header,
            "Q22a. Regnitz Less Likely - [CHOICE] Regnitz praised Indiana Right to Life",
        )

    def test_numeric_placeholder_less_likely_battery_gets_labels_and_header(self) -> None:
        q = Question(
            qid="12a",
            qnum="12",
            title=(
                "Now, I'd like to tell you a little more about the candidates for Congress. "
                "After each one, please tell me if that statement makes you much less likely "
                "to vote for them, somewhat less likely to vote for them, or if the statement "
                "makes no difference to you."
            ),
            item_text="a. [ML - WITH GOP] Time and again, Matt Little sided with Republicans",
            options=[
                ResponseOption("1", "1"),
                ResponseOption("2", "2"),
                ResponseOption("3", "3"),
                ResponseOption("4", "4"),
                ResponseOption("5", "5"),
            ],
        )
        setattr(q, "_stem_common", True)
        table = default_table(q, "TQ12a^9025")

        rule_persuasion_summary(table, q)
        rule_candidate_battery_header(table, q)

        self.assertEqual(
            table.header,
            "Q12a. Little Less Likely - [ML - WITH GOP] Time and again, Matt Little sided with Republicans",
        )
        self.assertIn(" Much less likely^Q12a(1)^NS", table.lines)
        self.assertIn(" Somewhat less likely^(2)^NS", table.lines)
        self.assertIn(" No difference^(3)^NS", table.lines)
        self.assertIn(" More likely^(4)^NS", table.lines)
        self.assertIn(" TOTAL LESS LIKELY^(1-2)^NS", table.lines)

    def test_six_code_numeric_placeholder_less_likely_battery_gets_labels(self) -> None:
        q = Question(
            qid="23a",
            qnum="23",
            title=(
                "Now I'd like to tell you a little bit about what the critics say about one of the candidates "
                "for Mayor. You will hear about [PAUSE] David Morales. Others will hear about Brett Smiley. "
                "For each one, please tell me if that statement makes you much less likely to vote for that "
                "candidate, somewhat less likely to vote for them, or if the statement makes no difference to you. "
                "If you do not think the statement is true, please just say so."
            ),
            item_text="a. Morales has never worked in city government",
            options=[
                ResponseOption("1", "1"),
                ResponseOption("2", "2"),
                ResponseOption("3", "3"),
                ResponseOption("4", "4"),
                ResponseOption("5", "5"),
                ResponseOption("6", "6"),
            ],
        )
        table = default_table(q, "TQ23a^9050")

        rule_persuasion_summary(table, q)

        self.assertEqual(
            table.lines,
            [
                " TOTAL ANSWERING^TN^1",
                " Much less likely^Q23a(1)^NS",
                " Somewhat less likely^(2)^NS",
                " No difference^(3)^NS",
                " More likely^(4)^NS",
                " Not true^(5)^NS",
                " (Don't know)^(6)^NS",
                " ^ ^NS,DV",
                " TOTAL LESS LIKELY^(1-2)^NS",
            ],
        )

    def test_numeric_placeholder_less_likely_battery_summary_tables(self) -> None:
        def item(qid: str, item_text: str) -> Question:
            q = Question(
                qid=qid,
                qnum="12",
                title=(
                    "Now, I'd like to tell you a little more about the candidates for Congress. "
                    "After each one, please tell me if that statement makes you much less likely "
                    "to vote for them, somewhat less likely to vote for them, or if the statement "
                    "makes no difference to you."
                ),
                item_text=item_text,
                options=[
                    ResponseOption("1", "1"),
                    ResponseOption("2", "2"),
                    ResponseOption("3", "3"),
                    ResponseOption("4", "4"),
                    ResponseOption("5", "5"),
                ],
            )
            setattr(q, "_stem_common", True)
            return q

        tables, _ = build_battery_summary_tables(
            "12",
            [
                item("12a", "a. [ML - WITH GOP] Time and again, Matt Little sided with Republicans"),
                item("12b", "b. [MK - CON] Matt Klein started the conservative Blue Dog Coalition"),
                item("12c", "c. [KB - WEAK] Kaela Berg is running such a weak campaign"),
            ],
            9027,
        )

        self.assertEqual(len(tables), 3)
        self.assertTrue(all(t.banner == LIKELY_SUMMARY_BANNER for t in tables))
        self.assertEqual(tables[0].header, "Q12. Summary Table - Much Less Likely")
        self.assertEqual(tables[1].header, "Q12. Summary Table - Total Less Likely")
        self.assertEqual(tables[2].header, "Q12. Summary Table - Total Less Likely minus More Likely")
        self.assertIn(" a. ML - With GOP^Q12a(1)^NS", tables[0].lines)
        self.assertIn(" b. MK - CON^Q12b(1,2)^NS", tables[1].lines)
        self.assertIn(" c. KB - Weak^Q12c(4)^HR,NS", tables[2].lines)
        self.assertIn(" c. KB - Weak^CALC V3 - V6^NS", tables[2].lines)

    def test_six_code_numeric_placeholder_less_likely_battery_summary_tables(self) -> None:
        def item(qid: str, item_text: str) -> Question:
            return Question(
                qid=qid,
                qnum="23",
                title=(
                    "Now I'd like to tell you a little bit about what the critics say about one of the candidates "
                    "for Mayor. You will hear about [PAUSE] David Morales. Others will hear about Brett Smiley. "
                    "For each one, please tell me if that statement makes you much less likely to vote for that "
                    "candidate, somewhat less likely to vote for them, or if the statement makes no difference to you. "
                    "If you do not think the statement is true, please just say so."
                ),
                item_text=item_text,
                options=[
                    ResponseOption("1", "1"),
                    ResponseOption("2", "2"),
                    ResponseOption("3", "3"),
                    ResponseOption("4", "4"),
                    ResponseOption("5", "5"),
                    ResponseOption("6", "6"),
                ],
            )

        tables, _ = build_battery_summary_tables(
            "23",
            [
                item("23a", "a. Morales has never worked in city government"),
                item("23b", "b. Morales skipped 185 votes"),
                item("23c", "c. Morales has only lived in Rhode Island for seven years"),
            ],
            9057,
        )

        self.assertEqual(len(tables), 4)
        self.assertTrue(all(t.banner == LIKELY_SUMMARY_BANNER for t in tables))
        self.assertEqual(tables[0].header, "Q23. Summary Table - Much Less Likely")
        self.assertEqual(tables[1].header, "Q23. Summary Table - Total Less Likely")
        self.assertEqual(tables[2].header, "Q23. Summary Table - Total Less Likely minus More Likely")
        self.assertEqual(tables[3].header, "Q23. Summary Table - Much Less Likely minus Not True/More Likely")
        self.assertIn(" a. Morales has never worked in city government^Q23a(1)^NS", tables[0].lines)
        self.assertIn(" b. Morales skipped 185 votes^Q23b(1,2)^NS", tables[1].lines)
        self.assertIn(" c. Morales has only lived in Rhode Island for seven years^Q23c(4)^HR,NS", tables[2].lines)
        self.assertIn(" c. Morales has only lived in Rhode Island for seven years^Q23c(4,5)^HR,NS", tables[3].lines)
        self.assertEqual(tables[2].lines[-1], " ^Q23a(1-5)^HR,NS")
        self.assertEqual(tables[3].lines[-1], " ^Q23a(1-5)^HR,NS")

    def test_race_tables_canonicalize_aapi_label(self) -> None:
        q = Question(
            qid="27",
            qnum="27",
            title="Race",
            options=[
                ResponseOption("1", "White"),
                ResponseOption("2", "Black"),
                ResponseOption("3", "Hispanic"),
                ResponseOption("4", "Asian or Pacific Islander"),
                ResponseOption("5", "Arab"),
                ResponseOption("6", "Other"),
            ],
        )
        table = default_table(q, "TQ27^9069")

        rule_race_on_file(table, q)

        self.assertIn(" AAPI^(4)^NS", table.lines)
        self.assertIn(" AAPI^RACE (4)^NS", table.lines)
        self.assertNotIn(" Asian or Pacific Islander^(4)^NS", table.lines)
        self.assertNotIn(" Asian or Pacific Islander^RACE (4)^NS", table.lines)

    def test_race_tables_canonicalize_black_african_american_label(self) -> None:
        q = Question(
            qid="27",
            qnum="27",
            title="Race",
            options=[
                ResponseOption("1", "White"),
                ResponseOption("2", "Black or African American"),
                ResponseOption("3", "Hispanic"),
                ResponseOption("4", "Asian"),
                ResponseOption("5", "Other"),
                ResponseOption("6", "Refused"),
            ],
        )
        table = default_table(q, "TQ27^9069")

        rule_race_on_file(table, q)

        self.assertIn(" Black^(2)^NS", table.lines)
        self.assertIn(" Black^(B)^NS", table.lines)
        self.assertNotIn(" Black or African American^(2)^NS", table.lines)
        self.assertIn(" AAPI^(4)^NS", table.lines)
        self.assertIn(" AAPI^(A)^NS", table.lines)
        self.assertNotIn(" Asian^(A)^NS", table.lines)

    def test_us_right_direction_header_accepts_not_sure_variant(self) -> None:
        q = Question(
            qid="5",
            qnum="5",
            title="Would you say things in the United States are generally headed in the right direction or would you say things are off on wrong track?",
            options=[
                ResponseOption("1", "Right direction"),
                ResponseOption("2", "Wrong track"),
                ResponseOption("3", "Not sure"),
            ],
        )
        table = default_table(q, "TQ5^9006")

        rule_right_direction_us(table, q)

        self.assertEqual(table.header, "Q5. Right Direction/Wrong Track - UNITED STATES")

    def test_past_presidential_vote_adds_among_voters_block(self) -> None:
        q = Question(
            qid="107",
            qnum="107",
            title="In the 2024 race for President, did you vote for Donald Trump, the Republican or Kamala Harris, the Democrat?",
            options=[
                ResponseOption("1", "Trump"),
                ResponseOption("2", "Harris"),
                ResponseOption("3", "(Other, specify: ______)"),
                ResponseOption("4", "(I did not vote in 2024)"),
                ResponseOption("5", "(Refused)"),
            ],
            question_type="past_vote_recall",
        )
        table = default_table(q, "TQ107^9061")

        rule_past_presidential_vote(table, q)

        self.assertEqual(table.header, "Q107. 2024 Vote for President")
        self.assertEqual(
            table.lines,
            [
                " Trump^Q107 (1)^NS",
                " Harris^(2)^NS",
                " Other^(3)^NS",
                " Didn't vote^(4)^NS",
                " (Refused)^(5)^NS,SK",
                " ^ ^NS,DV",
                " AMONG 2024 VOTERS^Q107(1-3)^NS,DV",
                " Trump^Q107 (1)^7,NS",
                " Harris^(2)^7,NS",
                " Other^(3)^7,NS",
            ],
        )

    def test_repeated_vote_with_leans_adds_vote_stack_table(self) -> None:
        def vote_q(qid: str, title: str) -> Question:
            return Question(
                qid=qid,
                qnum=qid,
                title=title,
                options=[
                    ResponseOption("1", "McMorrow"),
                    ResponseOption("2", "(Lean McMorrow)"),
                    ResponseOption("3", "Stevens"),
                    ResponseOption("4", "(Lean Stevens)"),
                    ResponseOption("5", "El-Sayed"),
                    ResponseOption("6", "(Lean El-Sayed)"),
                    ResponseOption("7", "(Undecided)"),
                ],
            )

        tables = build_tables(
            [
                vote_q("6", "Initial vote"),
                vote_q("12", "Thinking again, informed vote"),
                vote_q("18", "Thinking again after positives"),
                vote_q("20", "Thinking one last time after negatives"),
            ],
            [],
        )

        stack = next((table for table in tables if table.header == "Q6/12/18/20. Vote Stack"), None)
        self.assertIsNotNone(stack)
        assert stack is not None
        self.assertIs(stack, tables[-1])
        self.assertRegex(stack.table_id, r"^TQ6-12-18-20stack\^\d+$")
        self.assertEqual(stack.lines[0], "FIRST VOTE^ ^NS,DV")
        self.assertEqual(stack.lines[1], "McMorrow^Q6(1-2)^NS")
        self.assertIn("SECOND VOTE^ ^NS,DV", stack.lines)
        self.assertIn("THIRD VOTE^ ^NS,DV", stack.lines)
        self.assertIn("FOURTH VOTE^ ^NS,DV", stack.lines)
        self.assertIn("McMorrow^CALC V8 - V2^NS", stack.lines)
        self.assertIn("Stevens^CALC V9 - V3^NS", stack.lines)
        self.assertIn("El-Sayed^CALC V10 - V4^NS", stack.lines)
        self.assertIn("Undecided^CALC V11 - V5^NS", stack.lines)
        self.assertIn("McMorrow^CALC V20 - V8^NS", stack.lines)
        self.assertIn("McMorrow^CALC V20 - V2^NS", stack.lines)
        self.assertIn("McMorrow^CALC V38 - V20^NS", stack.lines)
        self.assertIn("McMorrow^CALC V38 - V8^NS", stack.lines)
        self.assertIn("McMorrow^CALC V38 - V2^NS", stack.lines)
        self.assertEqual(stack.lines[-1], "Undecided^CALC V41 - V5^NS")

        idx_23 = stack.lines.index("NET CHANGE 2-3^ ^NS,DV")
        self.assertEqual(stack.lines[idx_23 + 5], " ^ ^NS,DV")
        self.assertEqual(stack.lines[idx_23 + 6], "NET CHANGE 1-3^ ^NS,DV")
        idx_34 = stack.lines.index("NET CHANGE 3-4^ ^NS,DV")
        self.assertEqual(stack.lines[idx_34 + 5], " ^ ^NS,DV")
        self.assertEqual(stack.lines[idx_34 + 6], "NET CHANGE 2-4^ ^NS,DV")
        idx_24 = stack.lines.index("NET CHANGE 2-4^ ^NS,DV")
        self.assertEqual(stack.lines[idx_24 + 5], " ^ ^NS,DV")
        self.assertEqual(stack.lines[idx_24 + 6], "NET CHANGE 1-4^ ^NS,DV")

    def test_split_vote_with_leans_stacks_split_tables_and_combined(self) -> None:
        q = Question(
            qid="14",
            qnum="14",
            title="If the election were held today, who would you vote for?",
            instructions=[
                "[RANDOMIZE]",
                "[CORE - SPLIT A]",
                "[BROAD - SPLIT B]",
                "[IF UNDECIDED]",
            ],
            options=[
                ResponseOption("1", "Landsman"),
                ResponseOption("2", "(Lean Landsman)"),
                ResponseOption("3", "Conroy"),
                ResponseOption("4", "(Lean Conroy)"),
                ResponseOption("5", "(Undecided)"),
            ],
        )

        tables = build_tables(
            [q],
            [rule_vote_choice_split_table, rule_vote_choice_with_leans],
        )

        self.assertEqual(
            tables[0].lines,
            [
                " TOTAL ANSWERING^TN^1",
                " SPLIT A - CORE^num_ab(1)^NS,DV",
                " Landsman^Q14(1)and num_ab(1)^1,NS",
                " (Lean Landsman)^Q14(2)and num_ab(1)^1,NS",
                " Conroy^Q14(3)and num_ab(1)^1,NS",
                " (Lean Conroy)^Q14(4)and num_ab(1)^1,NS",
                " (Undecided)^Q14(5)and num_ab(1)^1,NS",
                " ^ ^NS,DV",
                " TOTAL LANDSMAN^Q14(1,2)and num_ab(1)^1,NS",
                " TOTAL CONROY^Q14(3,4)and num_ab(1)^1,NS",
                " ^ ^NS,DV",
                " SPLIT B - BROAD^num_ab(2)^NS,DV",
                " Landsman^Q14(1)and num_ab(2)^11,NS",
                " (Lean Landsman)^Q14(2)and num_ab(2)^11,NS",
                " Conroy^Q14(3)and num_ab(2)^11,NS",
                " (Lean Conroy)^Q14(4)and num_ab(2)^11,NS",
                " (Undecided)^Q14(5)and num_ab(2)^11,NS",
                " ^ ^NS,DV",
                " TOTAL LANDSMAN^Q14(1,2)and num_ab(2)^11,NS",
                " TOTAL CONROY^Q14(3,4)and num_ab(2)^11,NS",
                " ^ ^NS,DV",
                " COMBINED^ ^NS,DV",
                " Landsman^Q14(1)^NS",
                " (Lean Landsman)^(2)^NS",
                " Conroy^(3)^NS",
                " (Lean Conroy)^(4)^NS",
                " (Undecided)^(5)^NS",
                " ^ ^NS",
                " TOTAL LANDSMAN^(1,2)^NS",
                " TOTAL CONROY^(3,4)^NS",
            ],
        )

    def test_vote_table_headers_are_standardized_and_number_repeated_contests(self) -> None:
        def vote_q(qid: str, title: str, options: list[ResponseOption]) -> Question:
            return Question(
                qid=qid,
                qnum=qid,
                title=title,
                options=options,
                question_type="head_to_head_ballot",
            )

        two_way = [
            ResponseOption("1", "Landsman"),
            ResponseOption("2", "(Lean Landsman)"),
            ResponseOption("3", "Conroy"),
            ResponseOption("4", "(Lean Conroy)"),
            ResponseOption("5", "(Undecided)"),
        ]
        tables = build_tables(
            [
                Question(
                    qid="5",
                    qnum="5",
                    title="If the election for U.S. Congress were held today, would you vote for the Democrat or the Republican?",
                    options=[
                        ResponseOption("1", "Democrat"),
                        ResponseOption("2", "Republican"),
                        ResponseOption("3", "(Undecided)"),
                    ],
                    question_type="generic_ballot_party",
                ),
                vote_q(
                    "8",
                    "If the election for Governor was held today and the candidates were Amy Acton and Vivek Ramaswamy, for whom would you vote?",
                    [
                        ResponseOption("1", "Acton"),
                        ResponseOption("2", "(Lean Acton)"),
                        ResponseOption("3", "Ramaswamy"),
                        ResponseOption("4", "(Lean Ramaswamy)"),
                        ResponseOption("5", "(Undecided)"),
                    ],
                ),
                vote_q(
                    "9",
                    "If the election for U.S. Senate was held today and the candidates were Sherrod Brown and Jon Husted, for whom would you vote?",
                    [
                        ResponseOption("1", "Brown"),
                        ResponseOption("2", "(Lean Brown)"),
                        ResponseOption("3", "Husted"),
                        ResponseOption("4", "(Lean Husted)"),
                        ResponseOption("5", "(Undecided)"),
                    ],
                ),
                vote_q(
                    "10",
                    "If the election for Congress was held today and the candidates were Landsman, Conroy, and Hancock, for whom would you vote?",
                    [
                        ResponseOption("1", "Landsman"),
                        ResponseOption("2", "(Lean Landsman)"),
                        ResponseOption("3", "Conroy"),
                        ResponseOption("4", "(Lean Conroy)"),
                        ResponseOption("5", "Hancock"),
                        ResponseOption("6", "(Lean Hancock)"),
                        ResponseOption("7", "(Undecided)"),
                    ],
                ),
                vote_q(
                    "11",
                    "And what if the candidates were Landsman and Conroy, for whom would you vote?",
                    two_way,
                ),
                vote_q(
                    "14",
                    "Thinking again, if the election for Congress was held today and the candidates were Landsman and Conroy, for whom would you vote?",
                    two_way,
                ),
                vote_q(
                    "15",
                    "Having heard this, if the Democratic primary for Attorney General was held today, for whom would you vote?",
                    [
                        ResponseOption("1", "Smith"),
                        ResponseOption("2", "(Lean Smith)"),
                        ResponseOption("3", "Jones"),
                        ResponseOption("4", "(Lean Jones)"),
                        ResponseOption("5", "(Undecided)"),
                    ],
                ),
            ],
            [],
        )

        self.assertEqual(tables[0].header, "Q5. Generic Ballot for Congress")
        self.assertEqual(tables[1].header, "Q8. Vote for Governor")
        self.assertEqual(tables[2].header, "Q9. Vote for U.S. Senate")
        self.assertEqual(tables[3].header, "Q10. Vote for Congress - Three Way")
        self.assertEqual(tables[4].header, "Q11. Vote for Congress")
        self.assertEqual(tables[5].header, "Q14. Vote for Congress II")
        self.assertEqual(tables[6].header, "Q15. Democratic Primary Vote for Attorney General")

    def test_vote_table_headers_omit_three_way_when_all_votes_for_office_are_three_way(self) -> None:
        def vote_q(qid: str, title: str) -> Question:
            return Question(
                qid=qid,
                qnum=qid,
                title=title,
                options=[
                    ResponseOption("1", "Berg"),
                    ResponseOption("2", "(Lean Berg)"),
                    ResponseOption("3", "Klein"),
                    ResponseOption("4", "(Lean Klein)"),
                    ResponseOption("5", "Little"),
                    ResponseOption("6", "(Lean Little)"),
                    ResponseOption("7", "(Undecided)"),
                ],
                question_type="head_to_head_ballot",
            )

        tables = build_tables(
            [
                vote_q(
                    "6",
                    "If the Democratic primary for Congress was held today and the candidates were Berg, Klein, and Little, for whom would you vote?",
                ),
                vote_q(
                    "10",
                    "Thinking again, if the Democratic primary for U.S. Congress was held today and the candidates were Berg, Klein, and Little, for whom would you vote?",
                ),
                vote_q(
                    "13",
                    "Thinking one last time, if the Democratic primary for U.S. Congress was held today and the candidates were Berg, Klein, and Little, for whom would you vote?",
                ),
            ],
            [],
        )

        self.assertEqual(tables[0].header, "Q6. Democratic Primary Vote for Congress")
        self.assertEqual(tables[1].header, "Q10. Democratic Primary Vote for Congress II")
        self.assertEqual(tables[2].header, "Q13. Democratic Primary Vote for Congress III")

    def test_build_tables_adds_combined_demographics_for_10_bucket_age(self) -> None:
        gender_q = Question(
            qid="25",
            qnum="25",
            title="What is your sex?",
            options=[
                ResponseOption("1", "Male"),
                ResponseOption("2", "Female"),
            ],
        )
        age_q = Question(
            qid="26",
            qnum="26",
            title="What is your age?",
            options=[
                ResponseOption("1", "18-29"),
                ResponseOption("2", "30-34"),
                ResponseOption("3", "35-39"),
                ResponseOption("4", "40-44"),
                ResponseOption("5", "45-49"),
                ResponseOption("6", "50-54"),
                ResponseOption("7", "55-59"),
                ResponseOption("8", "60-64"),
                ResponseOption("9", "65-69"),
                ResponseOption("10", "70+"),
            ],
        )
        edu_q = Question(
            qid="30",
            qnum="30",
            title="What is the highest level of education you completed?",
            options=[
                ResponseOption("1", "Some grade school"),
                ResponseOption("2", "Some high school"),
                ResponseOption("3", "Graduated high school"),
                ResponseOption("4", "Technical/Vocational"),
                ResponseOption("5", "Some college but no degree"),
                ResponseOption("6", "Associates degree"),
                ResponseOption("7", "Bachelors degree"),
                ResponseOption("8", "Graduate/Professional"),
            ],
        )
        ideology_q = Question(
            qid="31",
            qnum="31",
            title="Ideology",
            options=[
                ResponseOption("1", "Very liberal"),
                ResponseOption("2", "Somewhat liberal"),
                ResponseOption("3", "Moderate"),
                ResponseOption("4", "Somewhat conservative"),
                ResponseOption("5", "Very conservative"),
                ResponseOption("6", "Not sure"),
            ],
        )
        race_q = Question(
            qid="27",
            qnum="27",
            title="Race",
            options=[
                ResponseOption("1", "White"),
                ResponseOption("2", "Black"),
                ResponseOption("3", "Hispanic"),
                ResponseOption("4", "Asian or Pacific Islander"),
                ResponseOption("5", "Arab"),
                ResponseOption("6", "Other"),
            ],
        )

        self.assertTrue(is_age_bucket_10(age_q))

        tables = build_tables([gender_q, age_q, edu_q, ideology_q, race_q], [])

        combined = next((table for table in tables if table.header == "Combined Demographics"), None)
        self.assertIsNotNone(combined)
        self.assertIn(" Men 18-54^Q25(1) AND Q26(1-6)^NS", combined.lines)
        self.assertIn(" Women 18-59^Q25(2) AND Q26(1-7)^NS", combined.lines)
        self.assertIn(" White 18-44^RACE (1) AND Q26 (1-4)^NS", combined.lines)
        self.assertIn(" Black 18-49^RACE (2) AND Q26 (1-5)^NS", combined.lines)
        self.assertIn(" Men No degree^Q25(1) AND Q30(1-6)^NS", combined.lines)
        self.assertIn(" Men Coll grad^Q25(1) AND Q30(7-8)^NS", combined.lines)
        self.assertIn(" Women No degree^Q25(2) AND Q30(1-6)^NS", combined.lines)
        self.assertIn(" Women Coll grad^Q25(2) AND Q30(7-8)^NS", combined.lines)
        self.assertIn(" Men Liberal^Q25(1) AND Q31(1-2)^NS", combined.lines)
        self.assertIn(" Women Liberal^Q25(2) AND Q31(1-2)^NS", combined.lines)
        self.assertIn(" Men Mod/Con^Q25(1) AND Q31(3-6)^NS", combined.lines)
        self.assertIn(" Women Mod/Con^Q25(2) AND Q31(3-6)^NS", combined.lines)
        self.assertNotIn(" Men <55^Q25(1) AND Q26(1-6)^NS", combined.lines)
        self.assertNotIn(" Women <60^Q25(2) AND Q26(1-7)^NS", combined.lines)
        self.assertNotIn(" White <45^RACE (1) AND Q26 (1-4)^NS", combined.lines)
        self.assertNotIn(" Black <50^RACE (2) AND Q26 (1-5)^NS", combined.lines)
        self.assertNotIn(" Men/No degree^Q25(1) AND Q30(1-6)^NS", combined.lines)
        self.assertNotIn(" Women/Coll grad^Q25(2) AND Q30(7-8)^NS", combined.lines)
        self.assertNotIn(" Men/Liberal^Q25(1) AND Q31(1-2)^NS", combined.lines)
        self.assertNotIn(" Women/Moderate+Conservative^Q25(2) AND Q31(3-6)^NS", combined.lines)
        self.assertIn(" White Women^RACE (1) AND Q25(2)^NS", combined.lines)
        self.assertIn(" Hispanic Men^RACE (3) AND Q25(1)^NS", combined.lines)


if __name__ == "__main__":
    unittest.main()
