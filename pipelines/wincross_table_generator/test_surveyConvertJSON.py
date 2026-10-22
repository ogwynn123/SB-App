import sys
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from surveyConvertJSON import attach_source_formatting, normalize_text, parse_question_block, parse_survey  # noqa: E402


class SurveyConvertJSONTests(unittest.TestCase):
    def test_normalize_text_preserves_sentence_double_spaces(self) -> None:
        self.assertEqual(
            normalize_text("Sentence one.  Sentence two."),
            "Sentence one.  Sentence two.",
        )
        self.assertEqual(
            normalize_text("Sentence one.\t\tSentence two."),
            "Sentence one. Sentence two.",
        )

    def test_question_text_gets_double_spaces_between_sentences(self) -> None:
        elements = parse_question_block(
            "5",
            "Here is the first sentence. Here is the second sentence? Here is the third sentence about the U.S. Congress.",
            [
                "Yes ................................................................ 1",
                "No ................................................................ 2",
            ],
        )

        self.assertEqual(
            elements[0]["text"],
            "Here is the first sentence.  Here is the second sentence?  Here is the third sentence about the U.S. Congress.",
        )

    def test_question_text_keeps_abbreviation_spacing(self) -> None:
        elements = parse_question_block(
            "6",
            "Do you approve of the U.S. Congress? Now thinking about Dr. Smith, do you approve?",
            [
                "Yes ................................................................ 1",
                "No ................................................................ 2",
            ],
        )

        text = elements[0]["text"]
        self.assertIn("U.S. Congress?  Now", text)
        self.assertIn("Dr. Smith", text)
        self.assertNotIn("U.S.  Congress", text)
        self.assertNotIn("Dr.  Smith", text)

    def test_attach_source_formatting_preserves_bracketed_and_plain_bold_spans(self) -> None:
        source_text = "1. Do you support [PLAN] and health care?"
        parsed = parse_survey(
            [
                source_text,
                "Yes 1",
                "No 2",
            ],
            "unitRAW.txt",
        )
        payload = {
            "schema_version": 1,
            "source_docx": "unit.docx",
            "raw_order_source": "pdf",
            "summary": {
                "bold_span_count": 2,
                "non_bracketed_bold_span_count": 1,
                "highlight_span_count": 1,
                "non_bracketed_highlight_span_count": 1,
                "strikethrough_span_count": 1,
                "non_bracketed_strikethrough_span_count": 1,
            },
            "paragraphs": [
                {
                    "index": 0,
                    "text": source_text,
                    "bold_spans": [
                        {
                            "start": source_text.find("[PLAN]"),
                            "end": source_text.find("[PLAN]") + len("[PLAN]"),
                            "text": "[PLAN]",
                            "bold": True,
                            "bracketed": True,
                            "bold_coverage": "all",
                            "bracket_text": "[PLAN]",
                        },
                        {
                            "start": source_text.find("health care"),
                            "end": source_text.find("health care") + len("health care"),
                            "text": "health care",
                            "bold": True,
                            "bracketed": False,
                            "bold_coverage": "all",
                        },
                    ],
                    "highlight_spans": [
                        {
                            "start": source_text.find("health care"),
                            "end": source_text.find("health care") + len("health care"),
                            "text": "health care",
                            "highlight": True,
                            "highlight_color": "yellow",
                            "bracketed": False,
                            "highlight_coverage": "all",
                        },
                    ],
                    "strikethrough_spans": [
                        {
                            "start": source_text.find("health care"),
                            "end": source_text.find("health care") + len("health care"),
                            "text": "health care",
                            "strikethrough": True,
                            "strikethrough_style": "single",
                            "bracketed": False,
                            "strikethrough_coverage": "all",
                        },
                    ],
                }
            ],
        }

        attach_source_formatting(parsed, payload)

        question = parsed["elements"][0]
        formatting = question["source_formatting"]
        spans = formatting["bold_spans"]
        self.assertEqual(formatting["bold_span_count"], 2)
        self.assertEqual(formatting["non_bracketed_bold_span_count"], 1)
        highlight_spans = formatting["highlight_spans"]
        self.assertEqual(formatting["highlight_span_count"], 1)
        self.assertEqual(formatting["non_bracketed_highlight_span_count"], 1)
        strikethrough_spans = formatting["strikethrough_spans"]
        self.assertEqual(formatting["strikethrough_span_count"], 1)
        self.assertEqual(formatting["non_bracketed_strikethrough_span_count"], 1)
        self.assertIn(
            {
                "field": "instructions[0]",
                "start": question["instructions"][0].find("[PLAN]"),
                "end": question["instructions"][0].find("[PLAN]") + len("[PLAN]"),
                "text": "[PLAN]",
                "bold": True,
                "bracketed": True,
                "bold_coverage": "all",
                "source_paragraph_index": 0,
                "bracket_text": "[PLAN]",
            },
            spans,
        )
        self.assertTrue(any(span["text"] == "health care" and not span["bracketed"] for span in spans))
        self.assertIn(
            {
                "field": "text",
                "start": question["text"].find("health care"),
                "end": question["text"].find("health care") + len("health care"),
                "text": "health care",
                "highlight": True,
                "bracketed": False,
                "highlight_coverage": "all",
                "source_paragraph_index": 0,
                "highlight_color": "yellow",
            },
            highlight_spans,
        )
        self.assertIn(
            {
                "field": "text",
                "start": question["text"].find("health care"),
                "end": question["text"].find("health care") + len("health care"),
                "text": "health care",
                "strikethrough": True,
                "bracketed": False,
                "strikethrough_coverage": "all",
                "source_paragraph_index": 0,
                "strikethrough_style": "single",
            },
            strikethrough_spans,
        )
        self.assertEqual(
            parsed["survey_level_metadata"]["source_formatting"]["attached_non_bracketed_bold_span_count"],
            1,
        )
        self.assertEqual(
            parsed["survey_level_metadata"]["source_formatting"]["attached_highlight_span_count"],
            1,
        )
        self.assertEqual(
            parsed["survey_level_metadata"]["source_formatting"]["attached_non_bracketed_highlight_span_count"],
            1,
        )
        self.assertEqual(
            parsed["survey_level_metadata"]["source_formatting"]["attached_strikethrough_span_count"],
            1,
        )
        self.assertEqual(
            parsed["survey_level_metadata"]["source_formatting"]["attached_non_bracketed_strikethrough_span_count"],
            1,
        )

    def test_repairs_party_leaner_prompt(self) -> None:
        elements = parse_question_block(
            "3",
            "[IF Q1=2,4] Do you think of yourself as closer to the [RANDOMIZE 1 and 2]?",
            [
                "Democratic Party ................................................ 1",
                "Republican Party ............................. TERMINATE",
                "Neither ................................................................ 3",
            ],
        )

        question = elements[0]
        self.assertEqual(
            question["text"],
            "Do you think of yourself as closer to the Democratic Party or the Republican Party?",
        )

    def test_mixed_case_favorability_scale_headers_stay_out_of_stem(self) -> None:
        elements = parse_question_block(
            "7",
            "Now, please read a list of public figures and organizations and select whether you have a favorable or unfavorable",
            [
                "opinion of each person or group using a scale that runs from 0 to 10.",
                "A 0 on this scale means you have a very low or very unfavorable opinion of that person or group.",
                "A 10 on this scale means you have a very high or very favorable opinion of that person or group.",
                "You can use any number between 0 and 10 to rate your opinion. If you have never heard of a name, or don't know",
                "enough to rate them, please just say so.",
                "Can't Never",
                "[RANDOMIZE] Unfavorable Favorable rate heard",
                "a. Donald Trump ....................................................... 0 1 2 3 4 5 6 7 8 9 10 11 12",
            ],
        )

        question = elements[0]
        self.assertNotIn("rate heard", question["text"].lower())
        self.assertEqual(question["instructions"], ["[RANDOMIZE]"])
        self.assertEqual(question["response_options"][11]["text"], "Can't rate")
        self.assertEqual(question["response_options"][12]["text"], "Never heard")

    def test_single_question_favorability_scale_row_uses_numeric_codes(self) -> None:
        elements = parse_question_block(
            "11",
            "[SPLIT A] Kim Ahern spent nine years as a prosecutor in the Attorney General's office. She prosecuted over a",
            [
                "thousand felonies including putting domestic abusers and child predators behind bars. Supporters say Kim Ahern",
                "is the most experienced prosecutor and Trump fighter in the race.",
                "[SPLIT B] Kim Ahern is a former prosecutor in the Attorney General's office. She will prosecute hate crimes",
                "against L-G-B-T-Q people and will protect abortion rights from the Trump Administration. Supporters say Kim",
                "Ahern is the progressive leader we need.",
                "Having heard this, tell me whether you have a favorable or unfavorable opinion of Kim Ahern using a scale that runs",
                "from 0 to 10.",
                "Kim Ahern ...................................................... 0 1 2 3 4 5 6 7 8 9 10 11",
            ],
        )

        self.assertEqual(len(elements), 1)
        question = elements[0]
        self.assertEqual(question["qid"], "11")
        self.assertEqual(question["question_type"], "favorability_0_10")
        self.assertIn("from 0 to 10.", question["text"])
        self.assertEqual(
            [option["value"] for option in question["response_options"]],
            [str(value) for value in range(12)],
        )
        self.assertEqual(question["response_options"][11]["text"], "Can't rate")

    def test_unlabeled_favorability_battery_rows_expand_to_items(self) -> None:
        elements = parse_question_block(
            "6",
            "Now, I'm going to read you a list of public figures and I'd like you to tell me whether you have a favorable or unfavorable opinion of each person using a scale that runs from 0 to 10.",
            [
                "A 0 on this scale means you have a very low or very unfavorable opinion of that person.",
                "A 10 on this scale means you have a very high or very favorable opinion of that person.",
                "CAN'T NEVER",
                "[RANDOMIZE] UNFAVORABLE FAVORABLE RATE HEARD",
                "Donald Trump 0 1 2 3 4 5 6 7 8 9 10 11 12",
                "Dan McKee 0 1 2 3 4 5 6 7 8 9 10 11 12",
                "Helena Foulkes [huh-LEE-nuh FOLKS] 0 1 2 3 4 5 6 7 8 9 10 11 12",
            ],
        )

        self.assertEqual([q["qid"] for q in elements], ["6a", "6b", "6c"])
        self.assertEqual(elements[0]["item_text"], "a. Donald Trump")
        self.assertEqual(elements[2]["item_text"], "c. Helena Foulkes")
        self.assertEqual(elements[0]["question_type"], "favorability_0_10")
        self.assertEqual(elements[0]["response_options"][11]["text"], "Can't rate")
        self.assertEqual(elements[0]["response_options"][12]["text"], "Never heard")

    def test_labeled_items_with_repeated_option_blocks_do_not_share_all_options(self) -> None:
        elements = parse_question_block(
            "10",
            "Now, I'm going to read you the names of some public figures. For each one, please tell me whether you have a VERY FAVORABLE, SOMEWHAT FAVORABLE, SOMEWHAT UNFAVORABLE or VERY UNFAVORABLE opinion of that person.",
            [
                "[RANDOMIZE]",
                "a. Donald Trump?",
                "Very favorable .................................................... 1",
                "Somewhat favorable ........................................... 2",
                "(Mixed) ............................................................... 3",
                "Somewhat unfavorable ....................................... 4",
                "Very unfavorable ................................................ 5",
                "Can't rate/Never heard ....................................... 6",
                "b. Dean Heller?",
                "Very favorable .................................................... 1",
                "Somewhat favorable ........................................... 2",
                "(Mixed) ............................................................... 3",
                "Somewhat unfavorable ....................................... 4",
                "Very unfavorable ................................................ 5",
                "Can't rate/Never heard ....................................... 6",
            ],
        )

        self.assertEqual([q["qid"] for q in elements], ["10a", "10b"])
        self.assertEqual(elements[0]["item_text"], "a. Donald Trump?")
        self.assertEqual(elements[1]["item_text"], "b. Dean Heller?")
        self.assertEqual(len(elements[0]["response_options"]), 6)
        self.assertEqual(len(elements[1]["response_options"]), 6)
        self.assertEqual(
            [option["text"] for option in elements[0]["response_options"]],
            [
                "Very favorable",
                "Somewhat favorable",
                "(Mixed)",
                "Somewhat unfavorable",
                "Very unfavorable",
                "Can't rate/Never heard",
            ],
        )

    def test_wrapped_paired_statements_stay_with_their_labeled_items(self) -> None:
        elements = parse_question_block(
            "15",
            "Which of the following statements is closer to your view? Choose one, even if neither is exactly right.",
            [
                "[RANDOMIZE ORDER, RANDOMIZE PAIRS]",
                "a. The cryptocurrency industry is a vital new part of our economy. It breaks the stranglehold of the big",
                "banks and gives all of us more financial freedom ........................................................ 1",
                "Cryptocurrency is how criminals, scammers, terrorists, and drug cartels operate. It needs strong new",
                "regulations ....................................................................................................................... 2",
                "(Don't know) ................................................................................................................... 3",
                "b. [SPLIT C] Israel is our most important ally in the Middle East. We should continue to sell them the",
                "weapons they need to defend themselves ....................................................................................... 1",
                "We should stop selling them weapons because we are contributing to atrocities ................................. 2",
                "(Don't know) ................................................................................................................... 3",
            ],
        )

        self.assertEqual([element["qid"] for element in elements], ["15a", "15b"])
        self.assertEqual([len(element["response_options"]) for element in elements], [3, 3])
        self.assertEqual(
            [option["text"] for option in elements[0]["response_options"]],
            [
                "The cryptocurrency industry is a vital new part of our economy.  It breaks the stranglehold of the big banks and gives all of us more financial freedom",
                "Cryptocurrency is how criminals, scammers, terrorists, and drug cartels operate.  It needs strong new regulations",
                "(Don't know)",
            ],
        )
        self.assertEqual(
            [option["value"] for option in elements[1]["response_options"]],
            ["1", "2", "3"],
        )
        self.assertEqual(
            elements[1]["response_options"][0]["text"],
            "Israel is our most important ally in the Middle East.  We should continue to sell them the weapons they need to defend themselves",
        )

    def test_labeled_items_without_terminal_punctuation_do_not_absorb_first_option(self) -> None:
        elements = parse_question_block(
            "7",
            "Now, you are going to see a list of people. Please tell me if you have a very favorable view of them, somewhat favorable view, somewhat unfavorable view or very unfavorable view of them.",
            [
                "a. Donald Trump?",
                "VERY FAVORABLE ........................................... 1",
                "SOMEWHAT FAVORABLE ................................ 2",
                "SOMEWHAT UNFAVORABLE ........................... 3",
                "VERY UNFAVORABLE ...................................... 4",
                "HAVEN'T HEARD ............................................... 5",
                "b. Dan Schwartz",
                "VERY FAVORABLE ........................................... 1",
                "SOMEWHAT FAVORABLE ................................ 2",
                "SOMEWHAT UNFAVORABLE ........................... 3",
                "VERY UNFAVORABLE ...................................... 4",
                "HAVEN'T HEARD ............................................... 5",
            ],
        )

        self.assertEqual([q["qid"] for q in elements], ["7a", "7b"])
        self.assertEqual(elements[1]["item_text"], "b. Dan Schwartz")
        self.assertEqual(len(elements[0]["response_options"]), 5)
        self.assertEqual(len(elements[1]["response_options"]), 5)
        self.assertEqual(
            [option["text"] for option in elements[1]["response_options"]],
            [
                "VERY FAVORABLE",
                "SOMEWHAT FAVORABLE",
                "SOMEWHAT UNFAVORABLE",
                "VERY UNFAVORABLE",
                "HAVEN'T HEARD",
            ],
        )

    def test_unlabeled_approval_battery_rows_expand_to_items(self) -> None:
        elements = parse_question_block(
            "9",
            "Do you strongly approve, somewhat approve, somewhat disapprove, or strongly disapprove of the job:",
            [
                "STRG SMWT SMWT STRG",
                "[RANDOMIZE] APP APP DIS DIS [DK]",
                "Dan McKee is doing as Governor 1 2 3 4 5",
                "Brett Smiley is doing as Mayor 1 2 3 4 5",
                "The Providence City Council is doing 1 2 3 4 5",
                "David Morales is doing as State Representative 1 2 3 4 5",
            ],
        )

        self.assertEqual([q["qid"] for q in elements], ["9a", "9b", "9c", "9d"])
        self.assertEqual(elements[0]["item_text"], "a. Dan McKee is doing as Governor")
        self.assertEqual(elements[3]["item_text"], "d. David Morales is doing as State Representative")
        self.assertEqual(elements[0]["question_type"], "approve_disapprove_4pt")
        self.assertEqual(
            [option["text"] for option in elements[0]["response_options"]],
            [
                "Strongly approve",
                "Somewhat approve",
                "Somewhat disapprove",
                "Strongly disapprove",
                "(Don't know)",
            ],
        )

    def test_unlabeled_job_rating_battery_classifies_as_job_approval(self) -> None:
        elements = parse_question_block(
            "13",
            "How would you rate the job being done by - EXCELLENT, GOOD, NOT SO GOOD or POOR?",
            [
                "EXCELLENT GOOD NOT SO GOOD POOR [DK]",
                "Donald Trump as President 1 2 3 4 5",
                "Joe Biden as President 1 2 3 4 5",
            ],
        )

        self.assertEqual([q["qid"] for q in elements], ["13a", "13b"])
        self.assertEqual(elements[0]["question_type"], "job_approval")
        self.assertEqual(elements[0]["question_group"], "job_approval")
        self.assertEqual(
            [option["text"] for option in elements[0]["response_options"]],
            ["Excellent", "Good", "Not so good", "Poor", "(Don't know)"],
        )

    def test_unlabeled_describes_well_battery_uses_numeric_scale_labels(self) -> None:
        elements = parse_question_block(
            "12",
            "I'm going to read you some qualities people might use to describe Brett Smiley. For each, please tell me how well it describes him on a 1 to 5 scale, where 5 means it describes him extremely well and 1 means that it does not describe him at all.",
            [
                "NOT EXTREMELY",
                "[RANDOMIZE] AT ALL WELL [DK]",
                "Cares about people like you 1 2 3 4 5 6",
                "Shares your values 1 2 3 4 5 6",
            ],
        )

        self.assertEqual([q["qid"] for q in elements], ["12a", "12b"])
        self.assertEqual(elements[0]["question_type"], "candidate_trait_well_4pt")
        self.assertEqual(
            [option["text"] for option in elements[0]["response_options"]],
            ["1", "2", "3", "4", "5", "(Don't know)"],
        )

    def test_maps_more_less_favorable_scale_labels(self) -> None:
        elements = parse_question_block(
            "17",
            "Opponents of the cryptocurrency industry have made statements on this topic. For each one, select if knowing that makes you more or less favorable towards a candidate who is supported by the cryptocurrency industry. If you do not think the statement is true, just say so.",
            [
                "Much more Somewhat Somewhat Much less Not",
                "[RANDOMIZE, THEN MAX DIFF] favorable more favorable less favorable favorable true",
                "a. Crypto mining has pushed up Americans' electric bills ........................................ 1 2 3 4 5",
            ],
        )

        question = elements[0]
        self.assertNotIn("much more somewhat", question["text"].lower())
        self.assertEqual(
            [option["text"] for option in question["response_options"]],
            [
                "Much more favorable",
                "Somewhat more favorable",
                "Somewhat less favorable",
                "Much less favorable",
                "Not true",
            ],
        )

    def test_maps_more_likely_battery_with_not_true_before_less_likely(self) -> None:
        elements = parse_question_block(
            "16",
            "Now, you will read a little more about one of the candidates for mayor. You have been selected to read about Brett Smiley. Other people will read about David Morales. For each one, please select if that statement makes you much more likely to vote for Brett Smiley or somewhat more likely to vote for him. If the statement makes no difference to you or you do not think it is true, just say so.",
            [
                "Much more Somewhat No Not Less Don't",
                "[RANDOMIZE, ONE AT A TIME] likely more likely difference true likely know",
                "a. [SERVICES] Smiley is improving city services ........................................ 1 2 3 4 5 6",
            ],
        )

        question = elements[0]
        self.assertEqual(question["question_type"], "persuasion_likelihood")
        self.assertEqual(question["question_group"], "persuasion")
        self.assertEqual(
            [option["text"] for option in question["response_options"]],
            [
                "Much more likely",
                "Somewhat more likely",
                "No difference",
                "Not true",
                "Less likely",
                "(Don't know)",
            ],
        )

    def test_maps_more_likely_battery_with_less_and_dk(self) -> None:
        elements = parse_question_block(
            "19",
            "For each, please tell me if that statement makes you much more likely to vote for Frank Mrvan, somewhat more likely to vote for him, or whether the statement makes no difference to you either way.",
            [
                "MUCH SMWT NO",
                "[RANDOMIZE] MORE MORE DIFF [LESS] [DK]",
                "a. [INFRASTRUCTURE] Mrvan helped pass infrastructure projects ........................ 1 2 3 4 5",
            ],
        )

        question = elements[0]
        self.assertEqual(question["question_type"], "persuasion_likelihood")
        self.assertEqual(
            [option["text"] for option in question["response_options"]],
            [
                "Much more likely",
                "Somewhat more likely",
                "No difference",
                "Less likely",
                "(Don't know)",
            ],
        )

    def test_merges_wrapped_battery_item_with_embedded_number_before_codes(self) -> None:
        elements = parse_question_block(
            "16",
            "Now, you will read a little more about one of the candidates for mayor. You have been selected to read about Brett Smiley. Other people will read about David Morales. For each one, please select if that statement makes you much more likely to vote for Brett Smiley or somewhat more likely to vote for him. If the statement makes no difference to you or you do not think it is true, just say so.",
            [
                "Much more Somewhat No Not Less Don't",
                "[RANDOMIZE, ONE AT A TIME] likely more likely difference true likely know",
                "d. [ECON DEV] Smiley is focusing on economic",
                "development. He has expanded assistance for",
                "small businesses that are the backbone of our",
                "economy. Under his leadership, more than 35",
                "new life science businesses have come to",
                "Providence ....................................................... 1 2 3 4 5 6",
            ],
        )

        question = elements[0]
        self.assertIn("more than 35 new life science businesses have come to Providence", question["item_text"])
        self.assertIn("development.  He has expanded assistance", question["item_text"])
        self.assertIn("economy.  Under his leadership", question["item_text"])
        self.assertEqual(
            [option["text"] for option in question["response_options"]],
            [
                "Much more likely",
                "Somewhat more likely",
                "No difference",
                "Not true",
                "Less likely",
                "(Don't know)",
            ],
        )

    def test_merges_wrapped_focus_item_with_multiple_numeric_facts(self) -> None:
        elements = parse_question_block(
            "14",
            (
                "Think about the following issues and please tell me how important you think it is "
                "for Rosa DeLauro to focus on that issue in Congress. Use a 0 to 10 scale, where a 0 "
                "means she should NOT focus on that issue at all and a 10 means that it should be the "
                "issue she focuses on the most. You may use any number from 0 to 10."
            ),
            [
                "NOT AT FOCUS",
                "[RANDOMIZE] ALL IMP THE MOST [DK]",
                "n. Passing a monthly child tax credit again that gives parents 360 dollars a month for each",
                "child under 6 and 300 dollars for each child",
                "aged 6 to 17 ........................................ 0 1 2 3 4 5 6 7 8 9 10 11",
                "o. Passing the Paycheck Fairness Act ................ 0 1 2 3 4 5 6 7 8 9 10 11",
            ],
        )

        self.assertEqual(len(elements), 2)
        self.assertEqual(elements[0]["qid"], "14n")
        self.assertEqual(
            elements[0]["item_text"],
            (
                "n. Passing a monthly child tax credit again that gives parents 360 dollars a month "
                "for each child under 6 and 300 dollars for each child aged 6 to 17"
            ),
        )
        self.assertEqual(
            [option["value"] for option in elements[0]["response_options"]],
            [str(value) for value in range(12)],
        )
        self.assertEqual(elements[1]["qid"], "14o")

    def test_merges_wrapped_long_option_text_in_single_choice_question(self) -> None:
        elements = parse_question_block(
            "24",
            "Critics of candidates who take money from Cryptocurrency or AI suggest that there might be many reasons why these candidates might take their money. Which one of these reasons sounds right to you? [RANDOMIZE]",
            [
                "These candidates are willing to say or do anything to get elected, even if it means blocking",
                "important safeguards against the cryptocurrency and AI industries ......................................................... 1",
                "These candidates are more likely to pay attention to the cryptocurrency and AI industries",
                "than they are the needs of everyday people back home .......................................................................... 2",
                "These candidates do not stand up to powerful special interests in Washington. They can",
                "be bought ................................................................................................................................................. 3",
                "These candidates are willing to go against their Democratic values and take support from",
                "MAGA billionaires and Trump supporters if it helps them get elected ...................................................... 4",
                "We can't trust these candidates to fight for our shared progressive values .............................................. 5",
            ],
        )

        question = elements[0]
        self.assertEqual(
            question["response_options"][2]["text"],
            "These candidates do not stand up to powerful special interests in Washington. They can be bought",
        )
        self.assertEqual(
            question["response_options"][3]["text"],
            "These candidates are willing to go against their Democratic values and take support from MAGA billionaires and Trump supporters if it helps them get elected",
        )

    def test_station_numbers_in_dot_leader_options_stay_in_labels(self) -> None:
        elements = parse_question_block(
            "109",
            "Which local Providence television news station is the one you watch the most often ... [READ LIST AND",
            [
                "RANDOMIZE]",
                "NBC 10 WJAR .................................................... 1",
                "WPRI 12 News ................................................... 2",
                "WNAC Fox.......................................................... 3",
                "ABC 6 WLNE ...................................................... 4",
                "(Don't know) ....................................................... 5",
            ],
        )

        question = elements[0]
        self.assertEqual(
            question["response_options"],
            [
                {"value": "1", "text": "NBC 10 WJAR"},
                {"value": "2", "text": "WPRI 12 News"},
                {"value": "3", "text": "WNAC Fox"},
                {"value": "4", "text": "ABC 6 WLNE"},
                {"value": "5", "text": "(Don't know)"},
            ],
        )

    def test_split_counterpunch_prose_does_not_create_candidate_options(self) -> None:
        elements = parse_question_block(
            "21",
            "Here is what Luke Bronin has to say in response.",
            [
                "[COUNTERPUNCH - SPLIT A] Luke Bronin says that it is sad that after 28 years in Congress that John Larson",
                "cannot stand on his own record and that all he does is attack. Luke Bronin says it is John Larson who has taken",
                "more than four million dollars from corporate special interests and hundreds of thousands from Trump donors. It is",
                "Luke Bronin who is a progressive new voice who is taking on Trump and refuses to take corporate PAC money.",
                "[REBUTTAL - SPLIT B] Luke Bronin says that these attacks are flat out false. he says that it is sad that after 28",
                "years in Congress that John Larson cannot stand on his own record and that all he does is attack. He refuses to",
                "take corporate PAC money and Bronin is proud to be a progressive new voice with a record of getting illegal guns",
                "off the streets of Hartford and his plans to take on Trump, abolish ICE, and tax corporations.",
                "Having heard that, even if you are not entirely sure, are you more likely to believe [RANDOMIZE] John Larson or",
                "Luke Bronin? [PUSH FOR ANSWER]",
                "John Larson ........................................................ 1",
                "Luke Bronin ........................................................ 2",
                "(Don't know) ....................................................... 3",
            ],
        )

        self.assertEqual(len(elements), 1)
        question = elements[0]
        self.assertIn("more likely to believe", question["text"])
        self.assertEqual(
            question["response_options"],
            [
                {"value": "1", "text": "John Larson"},
                {"value": "2", "text": "Luke Bronin"},
                {"value": "3", "text": "(Don't know)"},
            ],
        )

    def test_two_row_grid_header_with_party_columns_becomes_option_labels(self) -> None:
        elements = parse_question_block(
            "13",
            "Please select whether you trust [RANDOMIZE] the Democrats in Congress or the",
            [
                "Republicans in Congress more to handle each one?",
                "Democrats Democrats Republicans Republicans Don't",
                "[RANDOMIZE, GRID] much more somewhat more somewhat more much more know",
                "a. The economy ..........................................1 2 3 4 5",
                "b. Health care .............................................1 2 3 4 5",
            ],
        )

        self.assertEqual(len(elements), 2)
        self.assertEqual(
            elements[0]["text"],
            "Please select whether you trust the Democrats in Congress or the Republicans in Congress more to handle each one?",
        )
        self.assertEqual(
            [option["text"] for option in elements[0]["response_options"]],
            [
                "Democrats much more",
                "Democrats somewhat more",
                "Republicans somewhat more",
                "Republicans much more",
                "Don't know",
            ],
        )

    def test_number_at_end_of_option_label_is_not_the_code(self) -> None:
        vote = parse_question_block(
            "33",
            "In the 2024 race for President, did you vote for Donald Trump or Kamala Harris?",
            [
                "Trump ................................................................. 1",
                "Harris .................................................................. 2",
                "Other [TEXT BOX] ............................................. 3",
                "I did not vote in 2024 .......................................... 4",
            ],
        )
        stations = parse_question_block(
            "106",
            "Which local television news station is the one you watch the most often?",
            [
                "WLWT News 5 .................................................... 1",
                "WCPO ABC 9 ..................................................... 2",
                "WKRC Local 12 .................................................. 3",
                "Fox 19 ................................................................ 4",
                "(Don't know) ....................................................... 5",
            ],
        )

        self.assertEqual(
            [(o["value"], o["text"]) for o in vote[0]["response_options"]][-1],
            ("4", "I did not vote in 2024"),
        )
        self.assertEqual(
            [(o["value"], o["text"]) for o in stations[0]["response_options"]],
            [
                ("1", "WLWT News 5"),
                ("2", "WCPO ABC 9"),
                ("3", "WKRC Local 12"),
                ("4", "Fox 19"),
                ("5", "(Don't know)"),
            ],
        )

    def test_two_row_grid_header_rejoins_word_hyphenated_across_rows(self) -> None:
        elements = parse_question_block(
            "11",
            "Please select whether you trust [RANDOMIZE] Democrats or Republicans more to handle each one?",
            [
                "Democrats Democrats Nei- Republicans Republicans Don't",
                "[RANDOMIZE, GRID] much more somewhat more ther somewhat more much more know",
                "a. The economy .................................. 1 2 3 4 5 6",
                "b. Inflation ........................................... 1 2 3 4 5 6",
            ],
        )

        self.assertEqual(
            [option["text"] for option in elements[0]["response_options"]],
            [
                "Democrats much more",
                "Democrats somewhat more",
                "Neither",
                "Republicans somewhat more",
                "Republicans much more",
                "Don't know",
            ],
        )
        self.assertNotIn("Nei-", elements[0]["text"])


if __name__ == "__main__":
    unittest.main()
