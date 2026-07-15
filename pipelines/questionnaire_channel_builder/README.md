# Questionnaire Channel Builder

Create reviewable Phone/SMS questionnaire DOCX drafts from a final DOCX.

The builder is intentionally JSON-oriented:

- it reads source DOCX formatting through the existing WinCross formatting sidecar model;
- it applies channel edits from `channel_rules.default.json`;
- it writes a transform report JSON and output `.formatting.json` sidecars;
- changed text is highlighted in yellow in the generated DOCX.

Example:

```powershell
py -3 SurveyPlatform\pipelines\questionnaire_channel_builder\channel_builder.py `
  --docx "C:\path\to\NPA0000 Final.docx" `
  --channels phone sms `
  --out-dir "C:\path\to\Qst\AUTOchannel" `
  --overwrite
```

The default Phone channel is a clean copy. The default SMS channel handles
mechanical edits such as the standard SMS intro marker, removing parentheses
around volunteered response options, and converting common interviewer-read
phrasing into self-administered select phrasing.

For project-specific items such as pronunciation guides, copy
`channel_rules.default.json` and add exact `regex_replace` rules. For example:

```json
{
  "id": "sms_add_candidate_pronunciation",
  "type": "regex_replace",
  "scope": "all_paragraphs",
  "match": "^Candidate Name(\\t)",
  "replacement": "Candidate Name [pronunciation]\\1",
  "highlight": "diff"
}
```
