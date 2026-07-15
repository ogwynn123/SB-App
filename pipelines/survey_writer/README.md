# Survey Writer

Lightweight draft builder for questionnaire text. This is separate from the
active workspace flow and writes drafts under:

`SurveyPlatform/drafts/survey_writer/`

## Run

```powershell
py -3 SurveyPlatform\pipelines\survey_writer\survey_writer_app.py
```

Or double-click:

`SurveyPlatform\pipelines\survey_writer\open_survey_writer_gui.bat`

## V1 Scope

- Add questions from a small set of templates.
- Edit Q number, QID, question type, instructions, item text, and answer choices.
- Keep batteries as linked but separate questions, such as `Q15a`, `Q15b`, `Q15c`.
- Save and reopen draft JSON.
- Export questionnaire drafts to HTML and DOCX.
- Search the local question archive and add selected questions into the draft.

