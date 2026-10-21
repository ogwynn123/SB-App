# Preliminary QC

`prelim_qc.py` runs the structural part of the QC guide (`docs\QC_GUIDE.md`)
before tab books and marginals exist. It reconciles three sources without
treating any of them as authoritative:

- the questionnaire JSON from Table Gen (`Job\Table Gen\*JSON.json`),
- the WinCross job (`Job\NPA####.job`, else the newest `TABLES.autogen.txt`),
- the respondent data (newest `Data\NPA####*.csv`, e.g. `NPA####tsSB.csv`).

Checks:

| Check | Severity | Status |
|---|---|---|
| Table, banner, or glossary variable missing from the data (glossary `DECLARE`d variables count as defined) | Critical | Confirmed error |
| Table code not among the questionnaire's codes (screener `TERMINATE` options keep their position code); evidence shows how many respondents have it | Major | Human review |
| Closed question not used by any table or glossary definition | Major | Human review |
| Response present in the latest wave but in no table row (skipped for tables that combine questions, such as generic ballot with leans) | Major | Human review |
| `TIMESERIES` code that is not a wave in the data | Major | Confirmed error |
| Data value not among the questionnaire's codes | Minor | Human review |
| `TOTAL`/`NET` row including codes no individual row shows | Minor | Human review |

Numerical validation (weighted percentages, bases, nets against the tab book,
SB marginals, and results) is listed as a limitation in every report.

```powershell
py -3 prelim_qc.py --project-root "C:\...\NPA3873 Track Week 5"
py -3 prelim_qc.py --tables NPA3873.job --questionnaire-json NPA3873JSON.json --data NPA3873tsSB.csv --out .\qc
```

Reports go to `<project>\Job\QC\<timestamp>\` (`prelim_qc_report.md` with an
executive summary and issue register, plus `prelim_qc_issues.csv`). Nothing
else in the project is changed.
