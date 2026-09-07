# MinerU Paper-to-Markdown Workflow

Use this reference when installing the workflow on a new machine, changing paths, or debugging failed conversions.

## New Machine Checklist

1. Copy the `convert-papers-to-md` skill folder into `$HOME\.codex\skills\convert-papers-to-md`.
2. Install Python 3.12 or a compatible Python available as `python`.
3. Run `scripts/setup_mineru_windows.ps1` to create a MinerU virtual environment, install `mineru==3.4.5`, download models, and write `mineru-local.json`.
4. Put PDFs into one flat folder when possible. Long nested paths make Windows failures more likely.
5. Run a one-paper pilot with `--limit 1`.
6. Inspect the Markdown, image folder, `figure_index.md`, logs, and report before batch conversion.

## Recommended Defaults

- Virtual environment: `D:\mineru` or `C:\mineru`
- Work root: `D:\t\mineru-batch` or `C:\t\mineru-batch`
- Model source: `modelscope` when available; use `huggingface` if ModelScope is blocked.
- MinerU backend: `pipeline`
- MinerU method: `txt` for born-digital papers, `ocr` for scanned PDFs.
- Formula parsing: enabled
- Table parsing: enabled
- Image analysis: enabled
- Client-side output generation: enabled

## Typical Commands

Install:

```powershell
& "$HOME\.codex\skills\convert-papers-to-md\scripts\setup_mineru_windows.ps1" -VenvPath "D:\mineru" -ModelSource modelscope
```

Dry-run selection:

```powershell
& "$HOME\.codex\skills\convert-papers-to-md\scripts\run_mineru_batch.ps1" -PdfDir "D:\papers" -DryRun -Limit 3
```

Pilot:

```powershell
& "$HOME\.codex\skills\convert-papers-to-md\scripts\run_mineru_batch.ps1" -PdfDir "D:\papers" -Limit 1
```

Batch or resume:

```powershell
& "$HOME\.codex\skills\convert-papers-to-md\scripts\run_mineru_batch.ps1" -PdfDir "D:\papers"
```

Force rebuild:

```powershell
& "$HOME\.codex\skills\convert-papers-to-md\scripts\run_mineru_batch.ps1" -PdfDir "D:\papers" -Force
```

## Output Shape

For each `Paper.pdf`, expect:

- `md-batch\Paper.md`
- `md-batch\Paper\fig-001.jpg`
- `md-batch\Paper\table-001.jpg` when table images are detected
- `md-batch\Paper\figure_index.md`

Batch-level files:

- `md-batch-report.json`
- `md-batch-progress.txt`
- `md-batch-logs\mineru-api.log`
- `md-batch-logs\p001.log`, `p002.log`, etc.

## Troubleshooting

- If conversion fails before parsing starts, check `mineru-api.log`, the selected config path, and whether `models-dir.pipeline` exists.
- If paths are very long, pass `--work-root D:\t\mineru-batch` or move PDFs into a shorter folder.
- If a batch stops midway, rerun the same command. Existing Markdown is skipped by default.
- If only one PDF fails, rerun it with `--match "part of filename" --no-api` to isolate logs.
- If image links are broken, inspect MinerU's raw output folder in the short work root before deleting or rerunning.
- If scanned PDFs produce weak output, rerun selected files with `--method ocr`.
- If formulas are missing, keep formula parsing enabled and confirm `MINERU_FORMULA_CH_SUPPORT=True` is set in the environment.
