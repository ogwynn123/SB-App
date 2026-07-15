# Empty Results Generator

`empty_results_generator.py` creates an `EMPTY.docx` template by replacing
response-value numerics with placeholders:

- numeric value slots -> `!!`
- percent value slots -> `!!%`

It uses WinCross schema labels (from `TABLES.autogen.txt` and/or JSON) so
structural numbers in question text are not blindly replaced.

## Quick Start

From repo root:

```powershell
.\launch_empty_results_generator.bat --docx "C:\path\NPA3789 Bean IL-08 Primary Final.docx"
```

From `pipelines\auto_results`:

```powershell
.\open_empty_results_generator.bat --docx "C:\path\NPA3789 Bean IL-08 Primary Final.docx"
```

If `TABLES.autogen.txt` and `JSON.json` are next to the DOCX, they are
auto-detected.

## Explicit Inputs

```powershell
py -3 .\empty_results_generator.py `
  --docx "C:\path\Report Final.docx" `
  --tables "C:\path\NPA3789TABLES.autogen.txt" `
  --json "C:\path\NPA3789JSON.json" `
  --output "C:\path\Report Final EMPTY.docx"
```

## Notes

- `--tables` and/or `--json` should be provided (or auto-detected) for
  schema-aware replacements.
- If both are provided, labels are merged for coverage.
- Missing schema rows can be inserted automatically (default behavior).
- Use `--no-insert-missing` to disable row insertion and only transform
  existing value slots.
- If layout fidelity is more important than row synthesis, use the Word macro
  fallback in [`word_macro/`](./word_macro/README.md).
