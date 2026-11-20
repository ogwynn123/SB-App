---
name: oe-review
description: Code a job's open ends the way an experienced survey coder would. Day 1 reviews the drafted code list and recodes every response; each later day in the field codes only the new responses against the job's existing (or preliminary) code list, adding codes but never renumbering. Hands back a workbook the Open-End Coder imports. Use when the user asks to review, finalise, recode, continue or "do the qualitative pass" on a job's open ends, or runs /oe-review with a job folder, workbook or coder session.
---

# /oe-review: qualitative pass on drafted open ends

You are doing the review that used to be done by hand in the browser: turn the
local drafter's code list into one an analyst would sign off, then code every
response against it. The scripts handle files and checks; you do the reading
and coding. Everything here runs inside this Claude Code session, so the
verbatims you read are sent to Anthropic as part of the session, as they were
in the browser pass. Read only what the export gives you (survnum, verbatim,
lead-in answer, draft codes); do not open the job's data file to read other
columns.

Scripts live in `pipelines/open_end_coder/` (run them from there with `py -3`).
The house rules are in `pipelines/open_end_coder/oe_review_rules.md`. **Read
that file in full before coding anything**; it is the brief, and it wins over
anything below if they differ.

## Prepared by the Open-End Coder

If you are given a folder that contains a `job.json` (the coder's **Prepare
Claude Review** button makes one), the export is already done. Read `job.json`:

- `mode` is `"scratch"` (go to step 3, then 4, 5 and 6) or `"continue"` (go to
  Continue step 2 onward).
- `session` is the coder session to import into at the end (step 6 /
  Continue step 6), always with `--session`.
- `unused_codes` lists codes the job does not use: pass them to `build` and
  the importer as `--unused-codes` (leave the option out if the list is empty).

Write the TSV files into that same folder. Do not ask the user for anything
the folder already answers. When run without anyone watching, never use
`--accept-changes`: leave a wanted label change in the notes instead.

## 0. Day 1 or a later day?

- **Day 1 (from scratch):** the job has no code list yet. Follow steps 1-8.
- **Day 2 onward (continue):** the job's Open-End Coder session already holds
  the code list (from Day 1, or from a preliminary list an analyst made by hand,
  for example for a new wave of a track) and today's cumulative data has been
  imported into it. Follow "Continue" at the end instead. If the user gives a
  preliminary list file and no session list exists yet, that is also Continue
  (it is loaded with `--codelist`).

If unsure which, ask. Never treat a new wave of a track specially; the user
makes its preliminary list by hand.

## 1. Find the inputs

The user gives a job folder, an Open Ends folder or a draft workbook.

- Use the newest `* Draft Code Lists*.xlsx` there. If there is none, and a
  drafting spec (`oe_draft_spec.json`) is beside it, run
  `py -3 oe_draft_codelist.py "<spec>"` first; otherwise ask the user.
- The review folder is `llm_review` beside the draft workbook. Keep every
  output in it; never write into the job's Data folder or change the data file.
- Find out whether this job uses 96. On the Stelson tracks it does not (97 is
  "Nothing" and 96 is free for a theme). If the user, the spec's
  `"not_heard"` option, or the job's working code list does not settle it, ask.

## 2. Export

```bash
py -3 oe_llm_review.py export "<draft workbook>" --out "<folder>/llm_review"
```

This writes `q14 draft.md` (one per question) and `job.json`. Read each
question's `draft.md` in full: the draft code list with its QA flags, then every
response with its lead-in answer, draft codes and QA check.

## 3. Review each question (concept pass)

Work one question at a time. Following the rules file:

1. Read every response. For each draft code, decide the one proposition it
   stands for; split codes with more than one (the QA flags suggest splits),
   merge duplicates, and note which draft codes were wrong.
2. Read every draft-98 response against the whole list. Recurring ideas (3+)
   become codes.
3. Write the frozen list to `llm_review/q14 list.tsv`: `code<TAB>label<TAB>NET`,
   theme codes only, numbered from 1 with codes of a NET next to each other. A
   code with no better-fitting NET may go under `OTHER` (98 "Other" always sits
   there). Do not list 96-99; they are added automatically. (Day 1 only: numbering may
   still be tidied before the import; after it, numbers are fixed.)
4. Write `llm_review/q14 changes.tsv`: `codes<TAB>action<TAB>new label<TAB>reason`
   for the main changes from the draft (rename, merge, split, new code, delete).

## 4. Recode every response (from scratch)

Against the frozen list only, code every respondent in `q14 draft.md`:
`llm_review/q14 recode.tsv` with rows `survnum<TAB>codes<TAB>note`, codes as
`31,4` (most important first, at most 3). Use the note for a lead-in
contradiction you kept on purpose or a doubtful call. For long questions write
the rows in parts (`q14 recode 1.tsv`, `q14 recode 2.tsv`, ...) of about 150
responses each, so no respondent is skipped; every survnum must appear exactly
once across the parts.

Code what each verbatim says, not what its draft code or lead-in answer
suggests. If while recoding you find the list is missing an idea that recurs,
add the code to `list.tsv` and recode the responses that need it.

## 5. Build and check

```bash
py -3 oe_llm_review.py build "<folder>/llm_review" --unused-codes 96
```

(leave out `--unused-codes 96` on jobs that use 96). The build checks that
every respondent is coded once, codes are on the list, at most 3 per response,
non-answers alone, unused codes unused. It refuses to write the workbook while
problems remain: fix the TSV files and run it again.

It also prints QA lines: how much is left in 98, large codes, codes never used
or used once, and responses whose lead-in is on the other side from their
code's NET. Do one QA pass on those: re-read the flagged responses, split a
large code that hides sub-themes, rescue 98, drop unused codes, and keep a code
against the lead-in only when the verbatim says so. Rebuild after changes.

Then write `llm_review/notes.md`: a few `Item: finding` lines on the draft's
quality and its most common mistakes (for improving the drafter), and rebuild
so the notes land in the workbook.

## 6. Import

```bash
py -3 oe_review_import.py "<folder>/llm_review/<stem> Claude review.xlsx" --out "<folder>/llm_review" --unused-codes 96
```

Add `--session "<path>.oe_session.sqlite"` to write the codes into the job's
Open-End Coder session (responses already coded there are kept unless the user
asks for `--overwrite-coded`). On Day 1 this is how the list becomes the job's
code list for the following days, so use it whenever the job has a session;
ask the user for its path if it is not in the job's Open Ends folder.

## 7. Score (only when analysts' codes exist)

On a test job whose analysts' coding is in a data file (for example the
original `Data/NPA3887PT.csv` next to a blanked test copy):

```bash
py -3 oe_llm_review.py score "<analyst-coded data file>" "<folder>/llm_review/<stem> Claude review.xlsx"
```

This reports how many of the analysts' main themes were found and how many of
your codes match one of theirs. Never read the analysts' codes before or
during the review; score only at the end.

## 8. Report

Tell the user: the workbook written, codes and NETs per question, how many
responses are in 98, problems the importer found (should be 0), the score if
run, and the main kinds of change you made to the draft. Keep the report short;
the details are in the workbook's changes and notes sheets.

## Continue: Day 2 onward

The code list is now the job's own: tables and earlier days depend on its
numbers. **Never remove, renumber or reuse a code.** New codes go after the
highest existing theme code (skipping 96-99). Do not renumber to close gaps.

1. Export the current list and only today's uncoded responses (latest wave):

   ```bash
   py -3 oe_llm_review.py continue "<session>.oe_session.sqlite" --out "<Open Ends folder>/llm_review <YYYY-MM-DD>" --spec "<oe_draft_spec.json>"
   ```

   Add `--codelist "<preliminary list>.xlsx"` when an analyst's preliminary
   or working list should be loaded into the session first (the coder's own
   code-list import; labels already in the session are kept). `--spec` only
   adds each response's lead-in answer; leave it out if there is no spec.
   Read the notes it prints (for example coded responses whose source changed:
   tell the user to check those in the Open-End Coder).
2. Read `q14 draft.md`: the current list with how often each code has been used
   and two examples, then today's responses. Read the rules file as on Day 1.
3. Write `q14 list.tsv` with **every existing code, number, label and NET
   unchanged**, plus any new codes. A new code needs an idea recurring in 3+ of
   today's responses (or today's plus earlier 98s); otherwise use the closest
   existing code or 98. Give a new code an existing NET where it fits, else
   `OTHER`. If an existing label or NET is wrong, do not change it
   yourself: ask the user, and only then rebuild with `--accept-changes`.
4. Write `q14 recode.tsv` for today's responses, as on Day 1, and
   `q14 changes.tsv` for new codes (and any agreed label changes).
   If `draft.md` has a **Responses to recheck** section, those earlier
   responses go in `recode.tsv` too (every one of them):
   - **98**: give the response a code if one now fits (an existing code, or
     one you added today: a new code may draw on today's responses and these
     98s together for its 3+); otherwise write `98` again.
   - **flagged**: the user asked for another look; read their note, recode
     the verbatim from scratch, and say in the note column what changed (or
     why the codes stay). A note "Code N was split" means the response kept
     N after an earlier split: give it N only if it fits N's new label,
     otherwise one of the codes split from N (or another code).
   - **split N**: code N is in **Codes flagged for review** (the user thinks
     it is too broad, or its note starts "Auto:" because it holds more than 9%
     of respondents; a large code may still be one clear idea). If its responses hold more than one idea, keep N for
     the part that fits best (you may narrow its label; no `--accept-changes`
     needed for a flagged code) and add new codes after the highest number,
     same NET, for the rest; recode each of these responses with the result.
     If N is fine as it is, keep the codes and say why in `notes.md`.
   The import replaces their codes only if they are still unedited (98, split)
   or still flagged; anything changed by hand since is left alone.
5. Build (`build "<folder>" --unused-codes 96`, plus `--accept-changes` only
   after the user agreed). It refuses a missing, renumbered or misnumbered code.
   Do the QA pass on what it prints.
6. Import with `--session` (step 6 above). Only today's responses are written;
   earlier days' coding is untouched.
7. Report: responses coded today, new codes added, 98 count, any changes the
   user agreed to, and responses the export flagged for checking.
