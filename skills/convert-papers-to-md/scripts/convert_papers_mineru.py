import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path


IMAGE_RE = re.compile(r"^!\[(?P<alt>[^\]]*)\]\((?P<src>images/[^)]+)\)(?P<trail>\s*)$")
FIG_CAPTION_RE = re.compile(r"^Figure\s+\d+\s*:\s*(?P<caption>.*)$", re.IGNORECASE)
TABLE_CAPTION_RE = re.compile(r"^Table\s+\d+\s*:\s*(?P<caption>.*)$", re.IGNORECASE)


def eprint(message: str) -> None:
    print(message, flush=True)


def bool_text(value: bool) -> str:
    return "true" if value else "false"


def markdown_link(path: str) -> str:
    safe = path.replace("\\", "/")
    return f"<{safe}>"


def find_executable(name: str, explicit: str | None = None, beside: Path | None = None) -> Path | None:
    if explicit:
        return Path(explicit).expanduser().resolve()

    candidates: list[Path] = []
    if beside:
        suffix = ".exe" if os.name == "nt" else ""
        candidates.append(beside.parent / f"{name}{suffix}")

    found = shutil.which(name)
    if found:
        candidates.append(Path(found))
    if os.name == "nt" and not name.endswith(".exe"):
        found_exe = shutil.which(f"{name}.exe")
        if found_exe:
            candidates.append(Path(found_exe))
        candidates.extend(
            [
                Path(r"D:\mineru\Scripts") / f"{name}.exe",
                Path(r"C:\mineru\Scripts") / f"{name}.exe",
            ]
        )

    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


def find_config(pdf_dir: Path, explicit: str | None = None) -> Path | None:
    if explicit:
        return Path(explicit).expanduser().resolve()

    env_config = os.environ.get("MINERU_TOOLS_CONFIG_JSON")
    candidates = []
    if env_config:
        candidates.append(Path(env_config))
    candidates.extend(
        [
            pdf_dir / "mineru-local.json",
            Path.cwd() / "mineru-local.json",
            Path.home() / ".mineru" / "mineru-local.json",
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


def default_work_root(pdf_dir: Path) -> Path:
    if os.name == "nt":
        drive = pdf_dir.drive or Path.cwd().drive
        if drive:
            return Path(drive + r"\t\mineru-batch")
    return Path(tempfile.gettempdir()) / "mineru-batch"


def ensure_paths(
    pdf_dir: Path,
    out_root: Path,
    report_path: Path,
    progress_path: Path,
    run_log_dir: Path,
    work_root: Path,
    config_path: Path | None,
    mineru_exe: Path,
    mineru_api_exe: Path,
) -> None:
    required = [pdf_dir, mineru_exe, mineru_api_exe]
    if config_path:
        required.append(config_path)
    for path in required:
        if not path.exists():
            raise FileNotFoundError(str(path))
    out_root.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    run_log_dir.mkdir(parents=True, exist_ok=True)
    (work_root / "tmp").mkdir(parents=True, exist_ok=True)


def list_pdfs(pdf_dir: Path, pattern: str, recursive: bool, sort: str) -> list[Path]:
    iterator = pdf_dir.rglob(pattern) if recursive else pdf_dir.glob(pattern)
    pdfs = [path for path in iterator if path.is_file() and path.suffix.lower() == ".pdf"]
    if sort == "mtime":
        return sorted(pdfs, key=lambda path: (path.stat().st_mtime, path.name.lower()))
    return sorted(pdfs, key=lambda path: str(path.relative_to(pdf_dir)).lower())


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for_port(port: int, timeout_s: int) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            try:
                sock.connect(("127.0.0.1", port))
                return
            except OSError:
                time.sleep(1)
    raise TimeoutError(f"MinerU API did not open port {port} within {timeout_s}s")


def create_env(config_path: Path | None, work_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    if config_path:
        env["MINERU_TOOLS_CONFIG_JSON"] = str(config_path)
    env["MINERU_FORMULA_CH_SUPPORT"] = "True"
    env["TEMP"] = str(work_root / "tmp")
    env["TMP"] = str(work_root / "tmp")
    env.setdefault("PYTHONUTF8", "1")
    return env


def start_api(
    mineru_api_exe: Path,
    env: dict[str, str],
    run_log_dir: Path,
    work_root: Path,
    timeout_s: int,
) -> tuple[subprocess.Popen, str, Path, object]:
    port = get_free_port()
    log_path = run_log_dir / "mineru-api.log"
    log_file = log_path.open("ab")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(
        [str(mineru_api_exe), "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(work_root),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
    )
    try:
        wait_for_port(port, timeout_s)
    except Exception:
        kill_api(proc, log_file)
        raise
    return proc, f"http://127.0.0.1:{port}", log_path, log_file


def kill_api(proc: subprocess.Popen | None, log_file: object | None = None) -> None:
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=15)
    if log_file:
        try:
            log_file.close()
        except Exception:
            pass


def load_content_items(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def find_mineru_markdown(job_out: Path, short_name: str) -> tuple[Path, Path, Path]:
    preferred_dir = job_out / short_name / "txt"
    preferred_md = preferred_dir / f"{short_name}.md"
    if preferred_md.exists():
        return preferred_md, preferred_dir, preferred_dir / f"{short_name}_content_list.json"

    matches = sorted(job_out.rglob(f"{short_name}.md"), key=lambda path: len(str(path)))
    if not matches:
        raise FileNotFoundError(f"MinerU markdown not found under {job_out}")
    source_md = matches[0]
    source_dir = source_md.parent
    return source_md, source_dir, source_dir / f"{short_name}_content_list.json"


def clean_asset_dir(asset_dir: Path) -> None:
    asset_dir.mkdir(parents=True, exist_ok=True)
    for child in asset_dir.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def normalize_outputs(pdf: Path, short_name: str, job_out: Path, out_root: Path) -> dict:
    source_md, source_dir, content_list = find_mineru_markdown(job_out, short_name)
    stem = pdf.stem
    target_md = out_root / f"{stem}.md"
    asset_dir = out_root / stem
    clean_asset_dir(asset_dir)

    lines = source_md.read_text(encoding="utf-8", errors="replace").splitlines()
    new_lines: list[str] = []
    entries: list[dict] = []
    figure_count = 0
    table_count = 0

    for idx, line in enumerate(lines):
        image_match = IMAGE_RE.match(line)
        if image_match:
            figure_count += 1
            src_rel = image_match.group("src").replace("\\", "/")
            src_path = source_dir / src_rel
            ext = src_path.suffix.lower() or ".jpg"
            new_name = f"fig-{figure_count:03d}{ext}"
            dst_path = asset_dir / new_name
            if src_path.exists():
                shutil.copy2(src_path, dst_path)

            caption = ""
            if idx + 1 < len(lines):
                next_line = lines[idx + 1].strip()
                cap_match = FIG_CAPTION_RE.match(next_line)
                caption = cap_match.group("caption").strip() if cap_match else next_line

            anchor = f"figure-{figure_count:03d}"
            new_lines.append(f'<a id="{anchor}"></a>')
            new_lines.append(f"![]({markdown_link(f'{stem}/{new_name}')}){image_match.group('trail')}")
            entries.append(
                {
                    "kind": "figure",
                    "id": anchor,
                    "image": new_name if dst_path.exists() else "",
                    "source_image": src_rel,
                    "caption": caption,
                }
            )
            continue

        table_match = TABLE_CAPTION_RE.match(line.strip())
        if table_match:
            table_count += 1
            table_id = f"table-{table_count:03d}"
            new_lines.append(f'<a id="{table_id}"></a>')
            new_lines.append(line)
            entries.append(
                {
                    "kind": "table",
                    "id": table_id,
                    "image": "",
                    "source_image": "",
                    "caption": table_match.group("caption").strip(),
                }
            )
            continue

        new_lines.append(line)

    table_items = [item for item in load_content_items(content_list) if item.get("type") == "table"]
    table_image_index = 0
    for entry in [item for item in entries if item["kind"] == "table"]:
        if table_image_index >= len(table_items):
            continue
        table_item = table_items[table_image_index]
        image_src = (
            table_item.get("img_path")
            or table_item.get("image_path")
            or (table_item.get("image_source") or {}).get("path")
        )
        table_image_index += 1
        if not image_src:
            continue
        src_path = source_dir / str(image_src)
        if not src_path.exists():
            continue
        ext = src_path.suffix.lower() or ".jpg"
        table_number = entry["id"].split("-")[-1]
        new_name = f"table-{table_number}{ext}"
        shutil.copy2(src_path, asset_dir / new_name)
        entry["image"] = new_name
        entry["source_image"] = str(image_src)

    target_md.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    write_figure_index(pdf, target_md, asset_dir, entries)

    return {
        "markdown": str(target_md),
        "asset_dir": str(asset_dir),
        "figures": sum(1 for item in entries if item["kind"] == "figure"),
        "tables": sum(1 for item in entries if item["kind"] == "table"),
    }


def write_figure_index(pdf: Path, target_md: Path, asset_dir: Path, entries: list[dict]) -> None:
    md_name = target_md.name
    rows = [
        "# Figure/Table Index",
        "",
        f"- Source PDF: `{pdf.name}`",
        f"- Markdown: [{md_name}]({markdown_link('../' + md_name)})",
        f"- Assets folder: `{asset_dir.name}`",
        "",
    ]

    if not entries:
        rows.extend(["No figure or table images were detected.", ""])
    for item in entries:
        rows.extend(
            [
                f"## {item['id']}",
                f"- Jump: [{md_name}#{item['id']}]({markdown_link('../' + md_name + '#' + item['id'])})",
            ]
        )
        if item.get("image"):
            rows.append(f"- Image: [{item['image']}]({markdown_link(item['image'])})")
        rows.append(f"- Caption: {item.get('caption') or '(no caption detected)'}")
        if item.get("image"):
            rows.extend(["", f"![]({markdown_link(item['image'])})"])
        rows.append("")

    (asset_dir / "figure_index.md").write_text("\n".join(rows), encoding="utf-8")


def run_mineru_for_pdf(
    pdf: Path,
    index: int,
    total: int,
    mineru_exe: Path,
    out_root: Path,
    work_root: Path,
    run_log_dir: Path,
    env: dict[str, str],
    api_url: str | None,
    force: bool,
    args: argparse.Namespace,
) -> dict:
    target_md = out_root / f"{pdf.stem}.md"
    if target_md.exists() and not force:
        eprint(f"[{index}/{total}] SKIP existing: {pdf.name}")
        return {"pdf": str(pdf), "status": "skipped", "markdown": str(target_md)}

    short_name = f"p{index:03d}"
    job_root = work_root / "job"
    if job_root.exists():
        shutil.rmtree(job_root)
    job_in = job_root / "in"
    job_out = job_root / "out"
    job_in.mkdir(parents=True, exist_ok=True)
    job_out.mkdir(parents=True, exist_ok=True)
    short_pdf = job_in / f"{short_name}.pdf"
    shutil.copy2(pdf, short_pdf)

    log_path = run_log_dir / f"{short_name}.log"
    cmd = [
        str(mineru_exe),
        "-p",
        str(short_pdf),
        "-o",
        str(job_out),
        "-b",
        args.backend,
        "-m",
        args.method,
        "-f",
        bool_text(args.formula),
        "-t",
        bool_text(args.table),
        "--image-analysis",
        bool_text(args.image_analysis),
        "--client-side-output-generation",
        "true",
    ]
    if args.lang:
        cmd.extend(["--lang", args.lang])
    if api_url:
        cmd.extend(["--api-url", api_url])

    eprint(f"[{index}/{total}] RUN {pdf.name}")
    started = time.time()
    with log_path.open("w", encoding="utf-8", errors="replace") as log_file:
        result = subprocess.run(
            cmd,
            cwd=str(work_root),
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )

    if result.returncode != 0:
        eprint(f"[{index}/{total}] FAIL {pdf.name}")
        return {
            "pdf": str(pdf),
            "status": "failed",
            "returncode": result.returncode,
            "seconds": round(time.time() - started, 1),
            "log": str(log_path),
        }

    info = normalize_outputs(pdf, short_name, job_out, out_root)
    info.update(
        {
            "pdf": str(pdf),
            "status": "converted",
            "seconds": round(time.time() - started, 1),
            "log": str(log_path),
        }
    )
    eprint(
        f"[{index}/{total}] OK {pdf.name} | figures={info['figures']} "
        f"tables={info['tables']} | {info['seconds']}s"
    )
    return info


def select_pdfs(pdfs: list[Path], args: argparse.Namespace) -> list[tuple[int, Path]]:
    indexed = list(enumerate(pdfs, start=1))
    selected = indexed
    if args.start > 1:
        selected = [pair for pair in selected if pair[0] >= args.start]
    for needle in args.match:
        selected = [pair for pair in selected if needle.lower() in pair[1].name.lower()]
    if args.only_longest:
        return [max(selected, key=lambda pair: len(pair[1].stem))] if selected else []
    if args.limit:
        return selected[: args.limit]
    return selected


def write_report(results: list[dict], all_count: int, selected_count: int, paths: dict[str, Path]) -> None:
    report = {
        "input_dir": str(paths["pdf_dir"]),
        "output_root": str(paths["out_root"]),
        "work_root": str(paths["work_root"]),
        "total_pdfs": all_count,
        "selected_pdfs": selected_count,
        "converted": sum(1 for item in results if item["status"] == "converted"),
        "skipped": sum(1 for item in results if item["status"] == "skipped"),
        "failed": [item for item in results if item["status"] == "failed"],
        "results": results,
    }
    paths["report_path"].write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def write_progress(
    results: list[dict],
    all_count: int,
    selected_count: int,
    current_index: int | None,
    current_pdf: Path | None,
    phase: str,
    paths: dict[str, Path],
) -> None:
    converted = sum(1 for item in results if item["status"] == "converted")
    skipped = sum(1 for item in results if item["status"] == "skipped")
    failed = sum(1 for item in results if item["status"] == "failed")
    completed = converted + skipped + failed
    current_line = "Current: none"
    if current_index is not None and current_pdf is not None:
        current_line = f"Current: {current_index}/{all_count} {current_pdf.name}"
    lines = [
        f"Phase: {phase}",
        f"Completed selected: {completed}/{selected_count}",
        f"Total PDFs in folder: {all_count}",
        f"Converted: {converted}",
        f"Skipped existing: {skipped}",
        f"Failed: {failed}",
        current_line,
        f"Updated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Output root: {paths['out_root']}",
        f"Report: {paths['report_path']}",
        f"Log dir: {paths['run_log_dir']}",
    ]
    paths["progress_path"].write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch convert scholarly PDFs to Markdown with MinerU.")
    parser.add_argument("pdf_dir", nargs="?", default=".", help="Folder containing PDF files.")
    parser.add_argument("--out-root", default="", help="Output folder. Default: <pdf_dir>/md-batch.")
    parser.add_argument("--report-path", default="", help="JSON report path. Default: <pdf_dir>/md-batch-report.json.")
    parser.add_argument("--progress-path", default="", help="Progress text path. Default: <pdf_dir>/md-batch-progress.txt.")
    parser.add_argument("--log-dir", default="", help="Log folder. Default: <pdf_dir>/md-batch-logs.")
    parser.add_argument("--work-root", default="", help="Short temporary work folder. Default: <drive>:\\t\\mineru-batch on Windows.")
    parser.add_argument("--config", default="", help="MinerU config JSON path. Defaults to env or mineru-local.json.")
    parser.add_argument("--mineru-exe", default="", help="Path to mineru executable.")
    parser.add_argument("--mineru-api-exe", default="", help="Path to mineru-api executable.")
    parser.add_argument("--pattern", default="*.pdf", help="PDF filename glob. Default: *.pdf.")
    parser.add_argument("--recursive", action="store_true", help="Search PDFs recursively.")
    parser.add_argument("--sort", choices=["name", "mtime"], default="name", help="PDF order.")
    parser.add_argument("--start", type=int, default=1, help="Start from this 1-based sorted PDF index.")
    parser.add_argument("--limit", type=int, default=0, help="Convert first N selected PDFs.")
    parser.add_argument("--match", action="append", default=[], help="Only convert PDFs whose filename contains this text. Repeatable.")
    parser.add_argument("--only-longest", action="store_true", help="Convert only the PDF with the longest filename.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing Markdown/assets.")
    parser.add_argument("--dry-run", action="store_true", help="Print selected PDFs without running MinerU.")
    parser.add_argument("--no-api", action="store_true", help="Do not reuse a shared MinerU API process.")
    parser.add_argument("--api-timeout", type=int, default=120, help="Seconds to wait for shared MinerU API startup.")
    parser.add_argument("--backend", default="pipeline", help="MinerU backend. Default: pipeline.")
    parser.add_argument("--method", choices=["auto", "txt", "ocr"], default="txt", help="MinerU parse method.")
    parser.add_argument("--lang", default="", help="OCR language hint for pipeline backend.")
    parser.add_argument("--no-formula", dest="formula", action="store_false", help="Disable formula parsing.")
    parser.add_argument("--no-table", dest="table", action="store_false", help="Disable table parsing.")
    parser.add_argument("--no-image-analysis", dest="image_analysis", action="store_false", help="Disable image/chart analysis.")
    parser.set_defaults(formula=True, table=True, image_analysis=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    pdf_dir = Path(args.pdf_dir).expanduser().resolve()
    out_root = Path(args.out_root).expanduser().resolve() if args.out_root else pdf_dir / "md-batch"
    report_path = Path(args.report_path).expanduser().resolve() if args.report_path else pdf_dir / "md-batch-report.json"
    progress_path = Path(args.progress_path).expanduser().resolve() if args.progress_path else pdf_dir / "md-batch-progress.txt"
    run_log_dir = Path(args.log_dir).expanduser().resolve() if args.log_dir else pdf_dir / "md-batch-logs"
    work_root = Path(args.work_root).expanduser().resolve() if args.work_root else default_work_root(pdf_dir)
    config_path = find_config(pdf_dir, args.config or None)
    mineru_exe = find_executable("mineru", args.mineru_exe or None)
    mineru_api_exe = find_executable("mineru-api", args.mineru_api_exe or None, beside=mineru_exe)

    if not mineru_exe:
        raise FileNotFoundError("mineru executable not found. Pass --mineru-exe or run setup_mineru_windows.ps1.")
    if not mineru_api_exe:
        raise FileNotFoundError("mineru-api executable not found. Pass --mineru-api-exe or run setup_mineru_windows.ps1.")

    paths = {
        "pdf_dir": pdf_dir,
        "out_root": out_root,
        "report_path": report_path,
        "progress_path": progress_path,
        "run_log_dir": run_log_dir,
        "work_root": work_root,
    }
    ensure_paths(pdf_dir, out_root, report_path, progress_path, run_log_dir, work_root, config_path, mineru_exe, mineru_api_exe)

    pdfs = list_pdfs(pdf_dir, args.pattern, args.recursive, args.sort)
    if not pdfs:
        raise RuntimeError(f"No PDFs found in {pdf_dir}")
    selected = select_pdfs(pdfs, args)
    if not selected:
        raise RuntimeError("No PDFs matched the selection arguments.")

    eprint(f"Found {len(pdfs)} PDFs. Selected {len(selected)} for this run.")
    eprint(f"Output root: {out_root}")
    eprint(f"Work root: {work_root}")
    eprint(f"MinerU: {mineru_exe}")
    if config_path:
        eprint(f"Config: {config_path}")
    else:
        eprint("Config: none found; MinerU defaults will be used.")

    if args.dry_run:
        for original_index, pdf in selected:
            eprint(f"[{original_index}/{len(pdfs)}] {pdf}")
        return 0

    env = create_env(config_path, work_root)
    api_proc = None
    api_log_file = None
    api_url = None
    results: list[dict] = []
    try:
        if not args.no_api:
            eprint("Starting shared MinerU API process...")
            api_proc, api_url, api_log, api_log_file = start_api(
                mineru_api_exe, env, run_log_dir, work_root, args.api_timeout
            )
            eprint(f"MinerU API ready: {api_url} | log={api_log}")

        for original_index, pdf in selected:
            write_progress(results, len(pdfs), len(selected), original_index, pdf, "running", paths)
            try:
                results.append(
                    run_mineru_for_pdf(
                        pdf=pdf,
                        index=original_index,
                        total=len(pdfs),
                        mineru_exe=mineru_exe,
                        out_root=out_root,
                        work_root=work_root,
                        run_log_dir=run_log_dir,
                        env=env,
                        api_url=api_url,
                        force=args.force,
                        args=args,
                    )
                )
            except Exception as exc:
                eprint(f"[{original_index}/{len(pdfs)}] ERROR {pdf.name}: {exc}")
                results.append({"pdf": str(pdf), "status": "failed", "error": repr(exc)})
            write_report(results, len(pdfs), len(selected), paths)
            write_progress(results, len(pdfs), len(selected), original_index, pdf, "running", paths)
    finally:
        kill_api(api_proc, api_log_file)

    failed = [item for item in results if item["status"] == "failed"]
    write_progress(results, len(pdfs), len(selected), None, None, "finished", paths)
    eprint(
        f"Done. converted={sum(1 for item in results if item['status'] == 'converted')} "
        f"skipped={sum(1 for item in results if item['status'] == 'skipped')} failed={len(failed)}"
    )
    eprint(f"Report: {report_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
