# Paper KB Public

Local-first paper-to-Markdown workflow, corpus browser, and reusable Codex skill.

## What is public

- conversion and indexing code
- the Codex skill for PDF-to-Markdown reuse
- a tiny synthetic sample corpus
- a profile README template
- setup notes and manifests

## What stays private

- the original PDFs
- the full converted corpus
- local caches, SQLite indexes, logs, and machine-specific config

## Quick Start

```powershell
Set-Location -LiteralPath "C:\path\to\paper-kb-public"
py -3.12 -m pip install -r .\requirements.txt
$env:PAPERKB_TRANSLATION_PROVIDER = "none"
.\start_web.ps1
```

The sample corpus is synthetic and only exists to show the shape of the workflow.
To use your own papers, copy Markdown files into `md-batch\` and rerun the build.

## Convert PDFs

The reusable skill lives in `skills\convert-papers-to-md\`.
For a fresh Windows machine, start with:

```powershell
& .\skills\convert-papers-to-md\scripts\setup_mineru_windows.ps1 -VenvPath "D:\mineru" -ModelSource modelscope
```

Then run a pilot or batch conversion:

```powershell
& .\skills\convert-papers-to-md\scripts\run_mineru_batch.ps1 -PdfDir "D:\your-pdfs" -Limit 1
```

## GitHub Layout

- `profile-readme\README.md` is the template for your username-named profile repo.
- Pin this repo to your GitHub profile after publishing.
- Keep the real PDFs and the full corpus outside the public repo.

## Publish

```powershell
git remote add origin https://github.com/YOUR_USERNAME/paper-kb-public.git
git push -u origin main
```

Create a second repository named exactly like your GitHub username, copy
`profile-readme\README.md` into its root as `README.md`, then pin the main repo
from your profile page.
