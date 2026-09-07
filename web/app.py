from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

import sys

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markdown import Markdown

from store import PaperStore, ROOT_DIR, SOURCE_DIR, SearchFilters, build_paper_kb
from rendering import render_markdown


WEB_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

@asynccontextmanager
async def lifespan(_: FastAPI):
    store.ensure_index()
    yield


app = FastAPI(title="Paper KB", lifespan=lifespan)
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

store = PaperStore(ROOT_DIR)


def markdown_to_html(text: str) -> str:
    renderer = Markdown(
        extensions=["extra", "sane_lists", "tables", "footnotes"],
        output_format="html5",
    )
    return renderer.convert(text or "")


def encode_relpath(relpath: str) -> str:
    return quote(Path(relpath).as_posix(), safe="/")


def decorate_record(record: dict[str, object], source_path: Path | None = None) -> dict[str, object]:
    decorated = dict(record)
    relpath = str(record.get("file_location", ""))
    decorated["paper_url"] = f"/paper/{encode_relpath(relpath)}"
    decorated["raw_url"] = f"/raw/{encode_relpath(relpath)}"
    decorated["file_url"] = f"/file/{encode_relpath(relpath)}"
    if source_path is not None and source_path.parent != SOURCE_DIR:
        paper_stem = source_path.parent.name
    elif source_path is not None:
        paper_stem = source_path.stem
    else:
        paper_stem = Path(relpath).stem
    asset_dir = SOURCE_DIR / paper_stem
    figure_index = asset_dir / "figure_index.md"
    if figure_index.exists():
        decorated["figure_index_url"] = f"/paper/{encode_relpath(figure_index.relative_to(SOURCE_DIR).as_posix())}"
    else:
        decorated["figure_index_url"] = ""
    figures = []
    if asset_dir.exists():
        for item in sorted(asset_dir.glob("fig-*")):
            if item.is_file():
                figures.append(
                    {
                        "name": item.name,
                        "url": f"/file/{encode_relpath(item.relative_to(SOURCE_DIR).as_posix())}",
                    }
                )
    decorated["figure_files"] = figures[:12]
    decorated["figure_count"] = len(figures)
    decorated["asset_dir_url"] = f"/file/{encode_relpath(asset_dir.relative_to(SOURCE_DIR).as_posix())}" if asset_dir.exists() else ""
    return decorated


def page_context(request: Request, *, title: str, active_tab: str, **extra: object) -> dict[str, object]:
    stats = store.stats()
    facets = store.facets()
    return {
        "request": request,
        "site_title": "Paper KB",
        "page_title": title,
        "active_tab": active_tab,
        "stats": stats,
        "facets": facets,
        **extra,
    }


def resolve_source_file(relpath: str) -> Path:
    candidate = (SOURCE_DIR / relpath).resolve()
    try:
        candidate.relative_to(SOURCE_DIR)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc
    if not candidate.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return candidate


@app.get("/", response_class=HTMLResponse)
@app.get("/search", response_class=HTMLResponse)
def search(request: Request) -> Response:
    query = request.query_params.get("q", "").strip()
    tag = request.query_params.get("tag", "").strip()
    year = request.query_params.get("year", "").strip()
    author = request.query_params.get("author", "").strip()
    title = request.query_params.get("title", "").strip()
    limit = int(request.query_params.get("limit", "40") or 40)
    filters = SearchFilters(query=query, tag=tag, year=year, author=author, title=title, limit=limit)
    results = [decorate_record(record) for record in store.search(filters)]
    context = page_context(
        request,
        title="Search",
        active_tab="search",
        filters=filters,
        results=results,
        result_count=len(results),
        query=query,
    )
    if request.headers.get("hx-request") == "true":
        return templates.TemplateResponse(request, "partials/results.html", context)
    return templates.TemplateResponse(request, "index.html", context)


@app.get("/paper/{paper_path:path}", response_class=HTMLResponse)
def paper_view(request: Request, paper_path: str) -> Response:
    source_file = resolve_source_file(paper_path)
    relpath = source_file.relative_to(SOURCE_DIR).as_posix()
    record = store.paper_by_location(relpath)
    if record is None:
        record = build_paper_kb.extract_record(source_file, SOURCE_DIR)
        record["file_location"] = relpath
        record["docname"] = source_file.stem
        record["year"] = ""
        record["doi"] = ""
        record["metadata_source"] = "markdown"
    decorated = decorate_record(record, source_file)
    raw = source_file.read_text(encoding="utf-8", errors="replace")
    body_html, toc_html = render_markdown(raw, source_file, SOURCE_DIR)
    context = page_context(
        request,
        title=decorated.get("title", source_file.stem),
        active_tab="search",
        paper=decorated,
        body_html=body_html,
        toc_html=toc_html,
        raw_text=raw,
    )
    return templates.TemplateResponse(request, "paper.html", context)


@app.get("/raw/{paper_path:path}")
def raw_markdown(paper_path: str) -> Response:
    source_file = resolve_source_file(paper_path)
    return Response(
        source_file.read_text(encoding="utf-8", errors="replace"),
        media_type="text/markdown; charset=utf-8",
    )


@app.get("/file/{file_path:path}")
def file_view(file_path: str) -> Response:
    source_file = resolve_source_file(file_path)
    if source_file.suffix.lower() == ".md":
        return RedirectResponse(url=f"/raw/{encode_relpath(file_path)}", status_code=302)
    return FileResponse(source_file)


@app.get("/compare", response_class=HTMLResponse)
def compare_page(request: Request) -> Response:
    records = store.compare_records()
    grouped = build_paper_kb.build_tag_index(records)
    sections: list[dict[str, object]] = []
    for section_title, tags in build_paper_kb.COMPARE_GROUPS:
        rows: list[dict[str, object]] = []
        for tag in tags:
            items = grouped.get(tag, [])
            if not items:
                continue
            rows.append(
                {
                    "tag": tag,
                    "count": len(items),
                    "angle": build_paper_kb.TOPIC_NOTES.get(tag, ""),
                    "examples": build_paper_kb.representative_titles(items, limit=3, tag=tag),
                }
            )
        sections.append({"title": section_title, "rows": rows})
    context = page_context(request, title="Compare", active_tab="compare", sections=sections)
    return templates.TemplateResponse(request, "compare.html", context)


@app.get("/questions", response_class=HTMLResponse)
def questions_page(request: Request) -> Response:
    questions = store.question_bank()
    context = page_context(request, title="Question Bank", active_tab="questions", questions=questions)
    return templates.TemplateResponse(request, "questions.html", context)


@app.get("/ask", response_class=HTMLResponse)
def ask_page(request: Request) -> Response:
    question = request.query_params.get("q", "").strip()
    mode = request.query_params.get("mode", "auto").strip() or "auto"
    limit = int(request.query_params.get("limit", "5") or 5)
    if not question:
        result = {"mode": mode, "answer": "", "evidence": [], "error": "请输入问题。", "question": question}
    else:
        try:
            result = store.ask(question, mode=mode, limit=limit)
        except Exception as exc:
            result = store.local_answer(question, limit=limit)
            result["error"] = f"PaperQA failed, showing local search instead: {exc}"
            result["question"] = question
    result_html = markdown_to_html(result.get("answer", "")) if result.get("answer") else ""
    context = page_context(
        request,
        title="Ask",
        active_tab="ask",
        question=question,
        mode=mode,
        limit=limit,
        result=result,
        result_html=result_html,
    )
    if request.headers.get("hx-request") == "true":
        return templates.TemplateResponse(request, "partials/ask_result.html", context)
    return templates.TemplateResponse(request, "ask.html", context)


@app.post("/sync", response_class=HTMLResponse)
def sync_index(request: Request) -> Response:
    counts = store.sync()
    context = page_context(request, title="Synced", active_tab="search", counts=counts)
    if request.headers.get("hx-request") == "true":
        return templates.TemplateResponse(request, "partials/sync_status.html", context)
    return RedirectResponse(url="/", status_code=303)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local paper knowledge base web app.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind.")
    args = parser.parse_args()
    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
