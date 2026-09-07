---
name: convert-papers-to-md
description: Convert scholarly PDF papers or article corpora into readable Markdown with MinerU, preserving formulas, figure/table images, per-paper asset folders, figure indexes, progress logs, and resumable batch reports. Use when Codex needs to turn PDFs into Markdown for literature review, knowledge-base ingestion, full-text paper reading, or batch corpus preparation, especially on Windows where short work paths and local MinerU model configuration matter.
---

# Convert Papers To MD

## Overview

Use the bundled MinerU workflow when the user wants high-quality Markdown from papers, not a title-only skim. Prefer a one-paper pilot first, then batch conversion after the user approves the output.

## Workflow

1. Inspect the target folder directly for PDFs. If the user names a parent folder, check the requested target folder before saying files are missing.
2. If MinerU is not available, run `scripts/setup_mineru_windows.ps1` or adapt its steps for the local OS.
3. Run a visible pilot first unless the user explicitly asks for immediate batch conversion.
4. Batch convert with `scripts/convert_papers_mineru.py`, keeping outputs next to the PDFs by default.
5. Review `md-batch-report.json`, `md-batch-progress.txt`, logs, and one or two generated Markdown files before reporting success.

## Commands

Pilot one paper from a folder:

```powershell
python "$HOME\.codex\skills\convert-papers-to-md\scripts\convert_papers_mineru.py" "D:\path\to\pdfs" --limit 1
```

Batch convert or resume:

```powershell
python "$HOME\.codex\skills\convert-papers-to-md\scripts\convert_papers_mineru.py" "D:\path\to\pdfs"
```

Install MinerU on a new Windows machine:

```powershell
& "$HOME\.codex\skills\convert-papers-to-md\scripts\setup_mineru_windows.ps1" -VenvPath "D:\mineru" -ModelSource modelscope
```

If `CODEX_HOME` is unset, use `$HOME\.codex` in the paths above.

## Output Contract

By default, for a PDF folder such as `D:\papers`, the converter writes:

- `D:\papers\md-batch\Paper Title.md`
- `D:\papers\md-batch\Paper Title\fig-001.jpg` and table images
- `D:\papers\md-batch\Paper Title\figure_index.md`
- `D:\papers\md-batch-report.json`
- `D:\papers\md-batch-progress.txt`
- `D:\papers\md-batch-logs\*.log`

The script skips existing Markdown unless `--force` is passed, so interrupted batches are resumable.

## Operating Notes

- Use MinerU as the default parser for scholarly PDFs with formulas, figures, and tables.
- Use `--method txt` for text-based papers; use `--method ocr` only for scanned/image PDFs.
- Keep `--backend pipeline`, formula parsing, table parsing, image analysis, and client-side output generation enabled unless debugging.
- On Windows, use a short work path such as `D:\t\mineru-batch` or `C:\t\mineru-batch` to avoid path-length issues.
- Use a shared `mineru-api` process for batches; pass `--no-api` only when isolating failures.
- Do not summarize a corpus from filenames or titles only. Read generated Markdown full text, especially abstracts, introductions, methods, conclusions, captions, and formulas.

## Resources

- `scripts/convert_papers_mineru.py`: portable batch converter.
- `scripts/setup_mineru_windows.ps1`: Windows setup helper for a MinerU virtual environment, model download, and local config.
- `scripts/run_mineru_batch.ps1`: PowerShell wrapper for common conversion runs.
- `references/mineru-workflow.md`: setup details, troubleshooting, and migration checklist. Read it when installing on a new machine, changing model paths, or diagnosing MinerU failures.

**Appropriate for:** In-depth documentation, API references, database schemas, comprehensive guides, or any detailed information that Codex should reference while working.

### assets/
Files not intended to be loaded into context, but rather used within the output Codex produces.

**Examples from other skills:**
- Brand styling: PowerPoint template files (.pptx), logo files
- Frontend builder: HTML/React boilerplate project directories
- Typography: Font files (.ttf, .woff2)

**Appropriate for:** Templates, boilerplate code, document templates, images, icons, fonts, or any files meant to be copied or used in the final output.

---

**Not every skill requires all three types of resources.**
