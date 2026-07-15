import sys
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from wincrossBannerCompile import build_banners  # noqa: E402
from wincrossTableCompile import Question, ResponseOption  # noqa: E402


def vote_q(qid: str, title: str, options: list[ResponseOption] | None = None) -> Question:
    return Question(
        qid=qid,
        qnum="".join(ch for ch in qid if ch.isdigit()) or qid,
        title=title,
        instructions=["[RANDOMIZE]", "[IF UNDECIDED]"],
        options=options
        or [
            ResponseOption("1", "Landsman"),
            ResponseOption("2", "(Lean Landsman)"),
            ResponseOption("3", "Conroy"),
            ResponseOption("4", "(Lean Conroy)"),
            ResponseOption("5", "(Undecided)"),
        ],
        question_type="head_to_head_ballot",
    )


class WincrossBannerCompileTests(unittest.TestCase):
    def test_banner_generation_uses_dynamic_demo_vars_and_vote_movers(self) -> None:
        questions = [
            Question(
                qid="4",
                qnum="4",
                title="How likely are you to vote?",
                options=[ResponseOption("1", "Definitely vote")],
                question_type="likelihood_vote",
            ),
            Question(qid="13", qnum="13", title="What is the most important issue?", question_type="open_end"),
            Question(qid="100", qnum="100", title="Sex", question_type="gender_binary"),
            Question(qid="101", qnum="101", title="Education", question_type="demographics_education"),
            Question(qid="102", qnum="102", title="Age", question_type="demographics_age"),
            Question(qid="108", qnum="108", title="2024 vote for President", question_type="past_vote_recall"),
            Question(qid="1", qnum="1", title="Party ID", question_type="party_id"),
            Question(qid="103", qnum="103", title="Ideology", question_type="ideology_5pt"),
            Question(
                qid="12a",
                qnum="12",
                title="Do you approve or disapprove?",
                item_text="a. Donald Trump is doing as President",
                question_type="approve_disapprove_4pt",
            ),
            Question(
                qid="12b",
                qnum="12",
                title="Do you approve or disapprove?",
                item_text="b. Mike DeWine is doing as Governor",
                question_type="approve_disapprove_4pt",
            ),
            Question(
                qid="12d",
                qnum="12",
                title="Do you approve or disapprove?",
                item_text="d. Greg Landsman is doing as your Member of Congress",
                question_type="approve_disapprove_4pt",
            ),
            Question(qid="7f", qnum="7", title="Favorability", item_text="f. Eric Conroy", question_type="favorability_0_10"),
            Question(qid="7g", qnum="7", title="Favorability", item_text="g. Greg Landsman", question_type="favorability_0_10"),
            vote_q(
                "8",
                "If the election for Governor was held today and the candidates were Amy Acton and Vivek Ramaswamy...",
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
                "If the election for U.S. Senate was held today and the candidates were Sherrod Brown and Jon Husted...",
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
                "If the election for Congress was held today and the candidates were Greg Landsman, Eric Conroy, and Jason Hancock...",
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
            vote_q("11", "And what if the candidates were Greg Landsman and Eric Conroy?"),
            Question(
                qid="14",
                qnum="14",
                title="Now, I'd like to tell you more. Thinking again, who would you vote for between Greg Landsman and Eric Conroy?",
                instructions=["[RANDOMIZE]", "[CORE - SPLIT A]", "[BROAD - SPLIT B]", "[IF UNDECIDED]"],
                options=vote_q("14", "").options,
                question_type="head_to_head_ballot",
            ),
            vote_q("15", "Opponents of Greg Landsman say... Having heard this, who would you vote for between Greg Landsman and Eric Conroy?"),
            Question(
                qid="16a",
                qnum="16",
                title="Reasons to vote against Conroy.",
                item_text="a. [TRUMP - SPLIT C] Trump message",
                question_type="persuasion_likelihood",
            ),
            Question(
                qid="16b",
                qnum="16",
                title="Reasons to vote against Conroy.",
                item_text="b. [GOP - SPLIT D] GOP message",
                question_type="persuasion_likelihood",
            ),
            vote_q("17", "Having heard that, who would you vote for between Greg Landsman and Eric Conroy?"),
        ]

        out = build_banners(questions)
        banner1, banner2 = out.split("*Banner2")

        self.assertIn("*Banner1", out)
        self.assertIn(" PT:22,1", banner1)
        self.assertIn("                      REGION        SEX      RACE            AGE", out)
        self.assertIn("        DEF  2022 CINC THE  REST MEN  WMN", out)
        self.assertNotIn(" Q13_c1 S3(88)^W", out)
        self.assertNotIn(" c13_1 S3(88)^W", banner1)
        self.assertEqual(banner2.count(" c13_1 S3(88)^W"), 4)
        self.assertIn("MOST IMPORTANT ISSU", banner2)
        self.assertIn(" Q102(1,2)^W48", out)
        self.assertIn(" Q101 (7-8)^W48", out)
        self.assertIn(" Q108 (1)^W48", out)
        self.assertIn("*Banner2", out)
        self.assertIn(" PT:41,1", banner2)
        self.assertIn("PID W/O LEANS", out)
        self.assertIn("LANDSMAN JOB", out)
        self.assertIn("AA", out)
        self.assertIn("VR", out)
        self.assertIn("GL", out)
        self.assertIn("EC", out)
        self.assertNotIn("VOTE FOR CONGR ", out)
        self.assertIn("TO GL", out)
        self.assertIn(" Q12D (1-2)^W58", out)
        self.assertNotIn(" Q12B (1-2)^W58", out)
        self.assertIn(" Q8 (1-2)^W48", out)
        self.assertIn(" Q10 (7)^W48", out)
        self.assertIn(" num_ab(1)^W48", out)
        self.assertIn(" num_cd(2)^W68", out)
        self.assertIn(" Q11(3-5) and Q14(1-2)^W70", out)
        self.assertIn(" Q14(3-5) and Q15(1-2)^W70", out)
        self.assertIn(" Q11(3-5) and Q15(1-2)^W70", out)
        self.assertIn(" Q15(3-5) and Q17(1-2)^W70", out)
        self.assertIn(" Q14(3-5) and Q17(1-2)^W70", out)
        self.assertIn(" Q11(3-5) and Q17(1-2)^W70", out)
        self.assertIn("1-2  2-3  1-3  3-4  2-4  1-4", out)
        self.assertNotIn(" Q14(1-2) and Q15(3-5)^W70", out)

    def test_primary_banner1_uses_house_primary_template(self) -> None:
        questions = [
            Question(
                qid="2",
                qnum="2",
                title="On September 9th there will be a Democratic Primary for Governor, Attorney General, and other offices. How likely are you to vote?",
                options=[ResponseOption("1", "Definitely vote")],
                question_type="likelihood_vote",
            ),
            Question(qid="100", qnum="100", title="Sex", question_type="gender_binary"),
            Question(qid="101", qnum="101", title="What is your age?", question_type="demographics_age"),
            Question(qid="102", qnum="102", title="What is the last grade you completed in school?", question_type="demographics_education"),
            Question(qid="103", qnum="103", title="Thinking in political terms, would you say that you are very liberal, somewhat liberal, moderate, somewhat conservative, or very conservative?", question_type="ideology_5pt"),
            vote_q(
                "7",
                "If the Democratic primary for Attorney General was held today and the candidates were Kim Ahern, Keith Hoffmann, Jason Knight, and Joe Solomon, for whom would you vote?",
                [
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
            ),
            Question(
                qid="10",
                qnum="10",
                title="Which of the following type of candidates for Attorney General are you most likely to support?",
                options=[
                    ResponseOption("1", "One with the most experience prosecuting serious crimes"),
                    ResponseOption("2", "One with the most experience running and managing a big state agency"),
                    ResponseOption("3", "One who is focused on protecting the right to abortion and civil rights"),
                    ResponseOption("4", "One who is focused on filing lawsuits to stop overreach from the Trump Administration"),
                    ResponseOption("5", "(Don't know)"),
                ],
                question_type="single_choice",
            ),
            vote_q("15", "Thinking again, if the Democratic primary for Attorney General was held today and the candidates were Kim Ahern, Keith Hoffmann, Jason Knight, and Joe Solomon, for whom would you vote?"),
            vote_q("18", "Thinking again, if the Democratic primary for Attorney General was held today and the candidates were Kim Ahern, Keith Hoffmann, Jason Knight, and Joe Solomon, for whom would you vote?"),
            vote_q("20", "Thinking one last time, if the Democratic primary for Attorney General was held today and the candidates were Kim Ahern, Keith Hoffmann, Jason Knight, and Joe Solomon, for whom would you vote?"),
        ]

        out = build_banners(questions)

        self.assertIn("*Banner 1", out)
        self.assertIn(" ID:3", out)
        self.assertIn(" CP:0,0", out)
        self.assertIn(" OP:1,W200", out)
        self.assertIn(" PT:29,1", out)
        self.assertIn(" SL:I,F,J,K,A,B,C,D,E,P,Q,G,H,L,S,T,U,V,W,X,Y,D1,E1,F1,G1,H1,I1,J1,K1", out)
        self.assertIn(" Q2(1)^W70", out)
        self.assertIn(" PVOTEHIST(3,4)^W70", out)
        self.assertIn(" REGIONCODE (5)^W70", out)
        self.assertIn(" Q101(9-10)^W70", out)
        self.assertIn(" Q102 (7-8) AND RACE(W)^W88", out)
        self.assertIn("  ..... .... ......... ........................ ......... ..............", out)
        self.assertIn("             VOTE HIST          REGION             SEX         RACE", out)
        self.assertIn("55+ NO   COLL ---MEN--- --WOMEN-- NO   COLL", out)
        self.assertIn("54       DEG  GRAD NDEG COLL NDEG COLL DEG  GRAD", out)
        self.assertIn("*Banner 2", out)
        self.assertIn(" ID:15", out)
        self.assertIn("VOTE FOR AG", out)
        self.assertIn(" Q7 (1-2)^W48", out)
        self.assertIn(" KA ", out)
        self.assertNotIn("TYPE OF AG", out)
        self.assertNotIn("TO AHERN", out)
        self.assertNotIn("PERSUADE", out)

    def test_primary_banner2_uses_actual_office_and_relaxed_leans(self) -> None:
        questions = [
            Question(
                qid="2",
                qnum="2",
                title="How likely are you to vote in the Democratic primary for U.S. Senate, Governor, Congress, and other offices?",
                options=[ResponseOption("1", "Definitely vote")],
                question_type="likelihood_vote",
            ),
            Question(qid="100", qnum="100", title="Sex", question_type="gender_binary"),
            Question(qid="101", qnum="101", title="What is your age?", question_type="demographics_age"),
            Question(qid="102", qnum="102", title="Education", question_type="demographics_education"),
            Question(qid="103", qnum="103", title="Ideology", question_type="ideology_5pt"),
            vote_q(
                "6",
                "If the Democratic primary for U.S. Senate was held today and the candidates were Ed Markey and Seth Moulton, for whom would you vote?",
                [
                    ResponseOption("1", "Markey"),
                    ResponseOption("2", "(Lean Markley)"),
                    ResponseOption("3", "Moulton"),
                    ResponseOption("4", "(Lean Moulton)"),
                    ResponseOption("5", "(Undecided)"),
                ],
            ),
            vote_q(
                "17",
                "Thinking again, if the Democratic primary for U.S. Senate was held today and the candidates were Ed Markey and Seth Moulton, for whom would you vote?",
                [
                    ResponseOption("1", "Markey"),
                    ResponseOption("2", "(Lean Markley)"),
                    ResponseOption("3", "Moulton"),
                    ResponseOption("4", "(Lean Moulton)"),
                    ResponseOption("5", "(Undecided)"),
                ],
            ),
        ]

        out = build_banners(questions)

        self.assertIn("*Banner 2", out)
        self.assertIn("VOTE FOR SEN", out)
        self.assertNotIn("SEN II", out)
        self.assertNotIn("VOTE FOR SEN I ", out)
        self.assertIn(" Q6 (1-2)^W48", out)
        self.assertNotIn(" Q17 (1-2)^W48", out)
        self.assertIn(" Q6(3-5) and Q17(1-2)^W70", out)
        self.assertIn(" EM ", out)
        self.assertIn(" SM", out)
        self.assertNotIn("ATTY", out)
        self.assertNotIn("AHERN", out)
        self.assertNotIn("PERSUADE", out)

    def test_primary_banner2_omits_three_way_when_all_waves_for_office_are_three_way(self) -> None:
        congress_options = [
            ResponseOption("1", "Berg"),
            ResponseOption("2", "(Lean Berg)"),
            ResponseOption("3", "Klein"),
            ResponseOption("4", "(Lean Klein)"),
            ResponseOption("5", "Little"),
            ResponseOption("6", "(Lean Little)"),
            ResponseOption("7", "(Undecided)"),
        ]
        questions = [
            Question(
                qid="2",
                qnum="2",
                title="How likely are you to vote in the Democratic primary for U.S. Senate, Governor, Congress, and other offices?",
                options=[ResponseOption("1", "Definitely vote")],
                question_type="likelihood_vote",
            ),
            Question(qid="102", qnum="102", title="Education", question_type="demographics_education"),
            Question(qid="104", qnum="104", title="Ideology", question_type="ideology_5pt"),
            vote_q(
                "5",
                "If the Democratic primary for U.S. Senate was held today and the candidates were Angie Craig and Peggy Flanagan, for whom would you vote?",
                [
                    ResponseOption("1", "Craig"),
                    ResponseOption("2", "(Lean Craig)"),
                    ResponseOption("3", "Flanagan"),
                    ResponseOption("4", "(Lean Flanagan)"),
                    ResponseOption("5", "(Undecided)"),
                ],
            ),
            vote_q(
                "6",
                "If the Democratic primary for Congress was held today and the candidates were Kaela Berg, Matt Klein, and Matt Little, for whom would you vote?",
                congress_options,
            ),
            Question(
                qid="9",
                qnum="9",
                title="What would you say is the most important issue that you want your member of Congress to do something about?",
                question_type="open_end",
            ),
            vote_q(
                "10",
                "Kaela Berg is a state representative. Matt Klein is a state senator. Thinking again, if the Democratic primary for U.S. Congress was held today and the candidates were Kaela Berg, Matt Klein, and Matt Little, for whom would you vote?",
                congress_options,
            ),
            vote_q(
                "13",
                "Thinking again, if the Democratic primary for U.S. Congress was held today and the candidates were Kaela Berg, Matt Klein, and Matt Little, for whom would you vote?",
                congress_options,
            ),
            vote_q(
                "15",
                "Thinking one last time, if the Democratic primary for U.S. Congress was held today and the candidates were Kaela Berg, Matt Klein, and Matt Little, for whom would you vote?",
                congress_options,
            ),
        ]

        out = build_banners(questions)

        self.assertIn("VOTE FOR CONGRESS", out)
        self.assertNotIn("CONG II", out)
        self.assertNotIn("CONG III", out)
        self.assertNotIn("CONG IV", out)
        self.assertNotIn("3-WAY", out)
        self.assertNotIn(" Q9_c1 S3(88)^W", out)
        self.assertEqual(out.count(" c9_1 S3(88)^W"), 4)
        self.assertIn("MOST IMPORTANT ISSU", out)
        self.assertIn("=================== WHT  ==============", out)
        self.assertNotIn(" Q10 (1-2)^W48", out)
        self.assertIn(" Q6(3-7) and Q10(1-2)^W70", out)
        self.assertIn(" Q10(3-7) and Q13(1-2)^W70", out)
        self.assertIn(" Q6(3-7) and Q13(1-2)^W70", out)
        self.assertIn(" Q13(3-7) and Q15(1-2)^W70", out)
        self.assertIn(" Q10(3-7) and Q15(1-2)^W70", out)
        self.assertIn(" Q6(3-7) and Q15(1-2)^W70", out)
        self.assertIn("1-2  2-3  1-3  3-4  2-4  1-4", out)
        self.assertNotIn("KB   KB   KB", out)
        self.assertNotIn("STATE SEN", out.upper())


if __name__ == "__main__":
    unittest.main()
