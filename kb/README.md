# Paper KB Starter

This folder turns `md-batch/` into a searchable paper knowledge base.

## Build

```powershell
Set-Location -LiteralPath "C:\path\to\paper-kb-public"
$env:PAPERKB_TRANSLATION_PROVIDER = "none"
python .\kb\build_paper_kb.py
```

## Web

```powershell
.\start_web.ps1
```

## Notes

- The public repo defaults to offline mode.
- Set `PAPERKB_TRANSLATION_PROVIDER` to `argos`, `mymemory`, or `openai` if you want translated metadata.
- Keep the original PDFs outside the public repo.
