from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import pickle
import re
import sys
from pathlib import Path

import build_paper_kb

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


KB_DIR = Path(__file__).resolve().parent
DEFAULT_SOURCE = KB_DIR.parent / "md-batch"
DEFAULT_OUTPUT = KB_DIR
CATALOG_PATH = KB_DIR / "paper_catalog.jsonl"
ENRICHED_CATALOG_PATH = KB_DIR / "paper_catalog_enriched.jsonl"
MANIFEST_PATH = KB_DIR / "paperqa_manifest.csv"
ENRICHED_MANIFEST_PATH = KB_DIR / "paperqa_manifest_enriched.csv"
QUESTION_BANK_PATH = KB_DIR / "question_bank.jsonl"
COMPARE_MATRIX_PATH = KB_DIR / "compare_matrix.md"
PAPERQA_CACHE_PATH = KB_DIR / "paperqa_docs_cache.pkl"
PAPERQA_CACHE_META_PATH = KB_DIR / "paperqa_docs_cache.json"
DEFAULT_ASK_LIMIT = 5
DEFAULT_ASK_LENGTH = "about 150 words"
DEFAULT_PAPERQA_LLM = os.environ.get(
    "PAPERQA_LLM_MODEL", os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
)
DEFAULT_PAPERQA_EMBEDDING = os.environ.get(
    "PAPERQA_EMBEDDING_MODEL", "text-embedding-3-small"
)


def load_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    records: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        records.append(json.loads(line))
    return records


def load_catalog() -> list[dict[str, object]]:
    path = ENRICHED_CATALOG_PATH if ENRICHED_CATALOG_PATH.exists() else CATALOG_PATH
    return load_jsonl(path)


def load_question_bank() -> list[dict[str, object]]:
    return load_jsonl(QUESTION_BANK_PATH)


def load_manifest() -> list[dict[str, str]]:
    path = ENRICHED_MANIFEST_PATH if ENRICHED_MANIFEST_PATH.exists() else MANIFEST_PATH
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def md_path(source_dir: Path, record: dict[str, object]) -> Path:
    return source_dir / str(record.get("file_location", ""))


def ensure_records(args: argparse.Namespace) -> list[dict[str, object]]:
    records = load_catalog()
    if not records:
        build_paper_kb.build(args.source, args.output)
        records = load_catalog()
    return records


def has_openai_key() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


def slugify_docname(text: str, fallback: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", text.lower()).strip("-")
    if not slug:
        slug = fallback
    return slug[:100].strip("-") or fallback


def build_paperqa_citation(record: dict[str, object]) -> str:
    title = build_paper_kb.normalize_text(str(record.get("title", "")).strip())
    if not title:
        title = Path(str(record.get("file_location", "")).strip()).stem or "Untitled paper"
    year = str(record.get("year", "")).strip()
    doi = str(record.get("doi", "")).strip()
    citation = title
    if year:
        citation = f"{citation} ({year})"
    if doi:
        citation = f"{citation}. DOI: {doi}"
    return citation


def build_paperqa_docname(record: dict[str, object], index: int) -> str:
    title = str(record.get("title", "")).strip()
    if not title:
        title = Path(str(record.get("file_location", "")).strip()).stem or f"paper-{index:03d}"
    year = str(record.get("year", "")).strip()
    docname = slugify_docname(title, f"paper-{index:03d}")
    if year and year not in docname:
        docname = f"{docname}-{year}"
    return docname[:120].strip("-") or f"paper-{index:03d}"


def paperqa_cache_signature(
    records: list[dict[str, object]],
    source_dir: Path,
    llm_model_name: str,
    summary_llm_name: str,
    embedding_model_name: str,
) -> str:
    hasher = hashlib.sha256()
    hasher.update(f"source={source_dir.resolve().as_posix()}".encode("utf-8"))
    hasher.update(f"|llm={llm_model_name}".encode("utf-8"))
    hasher.update(f"|summary={summary_llm_name}".encode("utf-8"))
    hasher.update(f"|embedding={embedding_model_name}".encode("utf-8"))
    hasher.update(f"|records={len(records)}".encode("utf-8"))
    for record in sorted(records, key=lambda item: str(item.get("file_location", ""))):
        rel = str(record.get("file_location", ""))
        path = md_path(source_dir, record)
        hasher.update(rel.encode("utf-8", errors="ignore"))
        for field in ("title", "year", "doi", "primary_tag"):
            hasher.update(b"\0")
            hasher.update(str(record.get(field, "")).encode("utf-8", errors="ignore"))
        if path.exists():
            stat = path.stat()
            hasher.update(f"|{stat.st_size}|{stat.st_mtime_ns}".encode("utf-8"))
        else:
            hasher.update(b"|missing")
    return hasher.hexdigest()


def load_paperqa_cache(signature: str) -> tuple[object | None, dict[str, object]]:
    if not PAPERQA_CACHE_PATH.exists() or not PAPERQA_CACHE_META_PATH.exists():
        return None, {}
    try:
        meta = json.loads(PAPERQA_CACHE_META_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None, {}
    if meta.get("signature") != signature:
        return None, meta if isinstance(meta, dict) else {}
    try:
        with PAPERQA_CACHE_PATH.open("rb") as fh:
            docs = pickle.load(fh)
    except Exception:
        return None, meta if isinstance(meta, dict) else {}
    return docs, meta if isinstance(meta, dict) else {}


def save_paperqa_cache(signature: str, docs: object, skipped: list[str]) -> None:
    meta = {
        "signature": signature,
        "doc_count": len(getattr(docs, "docs", {})),
        "text_count": len(getattr(docs, "texts", [])),
        "skipped_count": len(skipped),
        "skipped": skipped[:25],
    }
    PAPERQA_CACHE_META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    with PAPERQA_CACHE_PATH.open("wb") as fh:
        pickle.dump(docs, fh, protocol=pickle.HIGHEST_PROTOCOL)


def get_paperqa_docs(
    records: list[dict[str, object]],
    source_dir: Path,
    llm_model_name: str,
    summary_llm_name: str,
    embedding_model_name: str,
    rebuild: bool = False,
) -> tuple[object, list[str], int, bool]:
    signature = paperqa_cache_signature(
        records=records,
        source_dir=source_dir,
        llm_model_name=llm_model_name,
        summary_llm_name=summary_llm_name,
        embedding_model_name=embedding_model_name,
    )
    if not rebuild:
        cached_docs, meta = load_paperqa_cache(signature)
        if cached_docs is not None:
            try:
                cached_docs.set_client()
            except Exception:
                cached_docs = None
            else:
                skipped = list(meta.get("skipped", [])) if isinstance(meta.get("skipped", []), list) else []
                loaded = int(meta.get("doc_count", len(getattr(cached_docs, "docs", {}))) or 0)
                return cached_docs, skipped, loaded, True

    docs, skipped, loaded = build_paperqa_docs(
        records=records,
        source_dir=source_dir,
        llm_model_name=llm_model_name,
        summary_llm_name=summary_llm_name,
        embedding_model_name=embedding_model_name,
    )
    if loaded > 0:
        try:
            save_paperqa_cache(signature, docs, skipped)
        except Exception as exc:
            print(f"Warning: could not write PaperQA cache: {exc}", file=sys.stderr)
    return docs, skipped, loaded, False


def tokenize(query: str) -> list[str]:
    return [token for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]+", query.lower()) if len(token) > 1]


def snippet_from_file(path: Path, query: str, width: int = 2) -> str:
    if not path.exists():
        return ""
    terms = tokenize(query)
    if not terms:
        return ""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    best_index = 0
    best_score = -1
    for index, line in enumerate(lines):
        lowered = line.lower()
        score = sum(lowered.count(term) for term in terms)
        if score > best_score:
            best_score = score
            best_index = index
    start = max(0, best_index - width)
    end = min(len(lines), best_index + width + 1)
    snippet_lines = []
    for i in range(start, end):
        line = build_paper_kb.normalize_text(lines[i])
        if line:
            snippet_lines.append(f"{i + 1}: {line}")
    return " | ".join(snippet_lines)


def score_record(record: dict[str, object], query: str, fulltext: bool, source_dir: Path) -> float:
    lowered = query.lower()
    tokens = tokenize(query)
    title = str(record.get("title", "")).lower()
    authors = str(record.get("authors", "")).lower()
    abstract = str(record.get("abstract_snippet", "")).lower()
    headings = " ".join(str(item) for item in record.get("headings", []) if item).lower()
    tags = " ".join(str(item) for item in record.get("tags", []) if item).lower()
    body = ""
    if fulltext:
        path = md_path(source_dir, record)
        if path.exists():
            body = path.read_text(encoding="utf-8", errors="replace").lower()

    score = 0.0
    if lowered and lowered in title:
        score += 20
    if lowered and lowered in abstract:
        score += 10
    if lowered and lowered in headings:
        score += 8
    for token in tokens:
        if token in title:
            score += 8
        elif token in authors:
            score += 2
        elif token in abstract:
            score += 5
        elif token in headings:
            score += 4
        elif token in tags:
            score += 6
        if fulltext and body:
            occurrences = body.count(token)
            if occurrences:
                score += min(occurrences, 8) * 1.25
    primary_tag = str(record.get("primary_tag", "")).lower()
    if tokens and primary_tag and primary_tag in tokens:
        score += 8
    return score


def filter_record(
    record: dict[str, object],
    tags: list[str],
    author: str,
    year: str,
    title: str,
) -> bool:
    if tags:
        record_tags = {str(item).lower() for item in record.get("tags", []) if item}
        if not set(tag.lower() for tag in tags).issubset(record_tags):
            return False
    if author and author.lower() not in str(record.get("authors", "")).lower():
        return False
    if year and str(record.get("year", "")) != year:
        return False
    if title and title.lower() not in str(record.get("title", "")).lower():
        return False
    return True


def search_records(
    records: list[dict[str, object]],
    query: str,
    tags: list[str],
    author: str,
    year: str,
    title: str,
    limit: int,
    fulltext: bool,
    source_dir: Path,
    require_match: bool = True,
) -> list[dict[str, object]]:
    matches: list[dict[str, object]] = []
    for record in records:
        if not filter_record(record, tags, author, year, title):
            continue
        score = score_record(record, query, fulltext, source_dir)
        if (
            require_match
            and query
            and score <= 0
            and not tags
            and not author
            and not year
            and not title
        ):
            continue
        path = md_path(source_dir, record)
        matches.append(
            {
                "score": score,
                "record": record,
                "path": path,
                "snippet": snippet_from_file(path, query),
            }
        )
    matches.sort(key=lambda item: (-float(item["score"]), str(item["record"].get("title", "")).lower()))
    return matches[:limit]


def print_search_results(results: list[dict[str, object]], query: str) -> None:
    if not results:
        print("No matches.")
        return
    for idx, item in enumerate(results, start=1):
        record = item["record"]
        tags = ", ".join(str(tag) for tag in record.get("tags", []))
        print(f"{idx}. {record.get('title', '')}")
        print(f"   tags: {tags or '-'}")
        year = str(record.get("year", "")).strip()
        doi = str(record.get("doi", "")).strip()
        if year:
            print(f"   year: {year}")
        if doi:
            print(f"   doi: {doi}")
        print(f"   file: {item['path']}")
        if item["score"]:
            print(f"   score: {item['score']:.2f}")
        snippet = item["snippet"]
        if snippet:
            print(f"   snippet: {snippet}")
        else:
            print(f"   snippet: {record.get('abstract_snippet', '')[:240]}")
        print("")


def build_paperqa_docs(
    records: list[dict[str, object]],
    source_dir: Path,
    llm_model_name: str,
    summary_llm_name: str,
    embedding_model_name: str,
) -> tuple[object, list[str], int]:
    try:
        from paperqa import Docs, OpenAILLMModel
    except ImportError as exc:  # pragma: no cover - defensive fallback
        raise RuntimeError("paperqa is not installed.") from exc

    docs = Docs(
        name="paperkb",
        llm_model=OpenAILLMModel(config={"model": llm_model_name, "temperature": 0.1}),
        summary_llm_model=OpenAILLMModel(
            config={"model": summary_llm_name, "temperature": 0.1}
        ),
        embedding=embedding_model_name,
    )

    skipped: list[str] = []
    loaded = 0
    for index, record in enumerate(records, start=1):
        path = md_path(source_dir, record)
        if not path.exists():
            skipped.append(f"Missing file: {path}")
            continue
        try:
            docs.add(
                path,
                citation=build_paperqa_citation(record),
                docname=build_paperqa_docname(record, index),
                disable_check=True,
            )
            loaded += 1
        except Exception as exc:  # pragma: no cover - data-dependent fallback
            skipped.append(f"{path.name}: {exc}")
    return docs, skipped, loaded


def print_local_ask_results(question: str, results: list[dict[str, object]], limit: int) -> None:
    print("Local retrieval mode.")
    print(f"Question: {question}")
    print("")
    if not results:
        print("No strong local match.")
        print("Use --mode paperqa with OPENAI_API_KEY for cited answers.")
        return

    top = results[0]
    top_record = top["record"]
    top_snippet = top["snippet"] or str(top_record.get("abstract_snippet", ""))
    print("Likely answer:")
    if top_snippet:
        print(f"- {top_snippet}")
    else:
        print("- No snippet available.")
    print("")
    print("Evidence:")
    for idx, item in enumerate(results[:limit], start=1):
        record = item["record"]
        print(f"{idx}. {record.get('title', '')}")
        year = str(record.get("year", "")).strip()
        doi = str(record.get("doi", "")).strip()
        if year:
            print(f"   year: {year}")
        if doi:
            print(f"   doi: {doi}")
        print(f"   file: {item['path']}")
        if item["score"]:
            print(f"   score: {item['score']:.2f}")
        snippet = item["snippet"] or str(record.get("abstract_snippet", ""))
        if snippet:
            print(f"   snippet: {snippet}")
        print("")


def cmd_build(args: argparse.Namespace) -> int:
    build_paper_kb.build(args.source, args.output)
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    records = ensure_records(args)
    results = search_records(
        records=records,
        query=args.query or "",
        tags=args.tag or [],
        author=args.author or "",
        year=args.year or "",
        title=args.title or "",
        limit=args.limit,
        fulltext=args.fulltext,
        source_dir=args.source,
    )
    print_search_results(results, args.query or "")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    records = ensure_records(args)
    matches = search_records(
        records=records,
        query=args.query or args.title or "",
        tags=args.tag or [],
        author=args.author or "",
        year=args.year or "",
        title=args.title or "",
        limit=1,
        fulltext=True,
        source_dir=args.source,
    )
    if not matches:
        print("No match.")
        return 1
    record = matches[0]["record"]
    path = matches[0]["path"]
    print(f"Title: {record.get('title', '')}")
    print(f"Authors: {record.get('authors', '')}")
    print(f"Tags: {', '.join(str(tag) for tag in record.get('tags', [])) or '-'}")
    print(f"Primary tag: {record.get('primary_tag', '')}")
    print(f"Word count: {record.get('word_count', 0)}")
    print(f"Sections: {record.get('section_count', 0)}")
    print(f"Year: {record.get('year', '') or '-'}")
    print(f"DOI: {record.get('doi', '') or '-'}")
    print(f"File: {path}")
    print("")
    snippet = snippet_from_file(path, args.query or record.get("title", ""))
    if snippet:
        print(snippet)
    else:
        print(str(record.get("abstract_snippet", "")))
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    question = args.query or " ".join(args.question or [])
    question = question.strip()
    if not question:
        print("No question provided.")
        return 1

    records = ensure_records(args)
    mode = args.mode
    if mode == "auto":
        mode = "paperqa" if has_openai_key() else "local"

    if mode == "paperqa":
        if not has_openai_key():
            print("OPENAI_API_KEY is not set.", file=sys.stderr)
            print("Use --mode local or set OPENAI_API_KEY.", file=sys.stderr)
            return 2
        try:
            summary_model = args.summary_model or os.environ.get("PAPERQA_SUMMARY_MODEL") or args.llm_model
            docs, skipped, loaded, from_cache = get_paperqa_docs(
                records=records,
                source_dir=args.source,
                llm_model_name=args.llm_model,
                summary_llm_name=summary_model,
                embedding_model_name=args.embedding_model,
                rebuild=args.rebuild,
            )
            if loaded == 0:
                print("No documents were indexed for PaperQA.")
                return 1
            answer = docs.query(
                question,
                k=max(args.k, args.max_sources),
                max_sources=args.max_sources,
                length_prompt=args.length,
            )
            text = str(getattr(answer, "formatted_answer", "")).strip()
            if not text:
                text = str(getattr(answer, "answer", "")).strip()
            if not text:
                text = "I cannot answer this question due to insufficient information."
            print(text)
            if skipped:
                print("")
                print(f"Warnings: skipped {len(skipped)} file(s) while indexing.", file=sys.stderr)
                for item in skipped[:5]:
                    print(f"- {item}", file=sys.stderr)
            if from_cache and args.verbose:
                print(f"Loaded PaperQA cache with {loaded} docs.", file=sys.stderr)
            return 0
        except Exception as exc:
            if args.mode == "paperqa":
                print(f"PaperQA failed: {exc}", file=sys.stderr)
                return 2
            print(f"PaperQA failed: {exc}", file=sys.stderr)
            print("Falling back to local retrieval.", file=sys.stderr)

    results = search_records(
        records=records,
        query=question,
        tags=[],
        author="",
        year="",
        title="",
        limit=args.limit,
        fulltext=True,
        source_dir=args.source,
        require_match=False,
    )
    print_local_ask_results(question, results, args.limit)
    return 0


def compare_table(records: list[dict[str, object]], tags: list[str] | None = None) -> str:
    grouped = build_paper_kb.build_tag_index(records)
    sections = build_paper_kb.COMPARE_GROUPS
    if tags:
        sections = [("Selected topics", tags)]
    lines = ["# Corpus Comparison Matrix", ""]
    for section_title, section_tags in sections:
        lines.extend([f"## {section_title}", "", "| Topic | Count | Main angle | Representative papers |", "|---|---:|---|---|"])
        for tag in section_tags:
            items = grouped.get(tag, [])
            if not items:
                continue
            examples = build_paper_kb.representative_titles(items, limit=3, tag=tag)
            lines.append(
                f"| {tag} | {len(items)} | {build_paper_kb.TOPIC_NOTES.get(tag, '')} | {'<br>'.join(examples)} |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def cmd_compare(args: argparse.Namespace) -> int:
    records = ensure_records(args)
    if args.tag:
        print(compare_table(records, tags=args.tag))
        return 0
    if COMPARE_MATRIX_PATH.exists():
        print(COMPARE_MATRIX_PATH.read_text(encoding="utf-8"))
        return 0
    print(compare_table(records))
    return 0


def cmd_questions(args: argparse.Namespace) -> int:
    questions = load_question_bank()
    if not questions:
        records = ensure_records(args)
        questions = build_paper_kb.generate_question_bank(records)
    if args.format == "json":
        print(json.dumps(questions, ensure_ascii=False, indent=2))
        return 0
    print("# Paper KB Question Bank")
    print("")
    for item in questions:
        print(f"- [{item['id']}] {item['question']}")
        samples = item.get("sample_titles", [])
        if isinstance(samples, list) and samples:
            print(f"  - Samples: {', '.join(str(sample) for sample in samples)}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    problems: list[str] = []
    warnings: list[str] = []

    if not args.source.exists():
        problems.append(f"Missing source folder: {args.source}")
    records = load_catalog()
    manifest = load_manifest()
    if not records:
        problems.append(f"Missing or empty catalog: {CATALOG_PATH}")
    if not manifest:
        problems.append(f"Missing or empty manifest: {MANIFEST_PATH}")

    if records and manifest and len(records) != len(manifest):
        problems.append(f"Record count mismatch: catalog={len(records)} manifest={len(manifest)}")

    missing_paths = []
    for row in manifest:
        rel = row.get("file_location", "")
        if not rel:
            problems.append("Manifest contains an empty file_location")
            continue
        path = args.source / rel
        if not path.exists():
            missing_paths.append(rel)
    if missing_paths:
        problems.append(f"Missing markdown files: {len(missing_paths)}")

    if records:
        uncategorized = [record for record in records if not record.get("tags")]
        if uncategorized:
            warnings.append(f"{len(uncategorized)} record(s) still have no tags")
        empty_titles = [record for record in records if not str(record.get("title", "")).strip()]
        if empty_titles:
            problems.append(f"{len(empty_titles)} record(s) have empty titles")

    questions = load_question_bank()
    if not questions:
        problems.append(f"Missing question bank: {QUESTION_BANK_PATH}")
    elif len(questions) < 5:
        warnings.append(f"Question bank is small: {len(questions)} items")

    if COMPARE_MATRIX_PATH.exists() and COMPARE_MATRIX_PATH.stat().st_size == 0:
        problems.append(f"Empty compare matrix: {COMPARE_MATRIX_PATH}")

    if problems:
        print("Validation failed:")
        for item in problems:
            print(f"- {item}")
        if warnings:
            print("")
            print("Warnings:")
            for item in warnings:
                print(f"- {item}")
        return 1

    print("Validation passed.")
    print(f"- papers: {len(records)}")
    print(f"- manifest rows: {len(manifest)}")
    print(f"- questions: {len(questions)}")
    if warnings:
        print("")
        print("Warnings:")
        for item in warnings:
            print(f"- {item}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tools for the paper knowledge base.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="Markdown corpus folder.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Knowledge-base output folder.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser_cmd = subparsers.add_parser("build", help="Rebuild the catalog and companion files.")
    build_parser_cmd.set_defaults(func=cmd_build)

    search_parser = subparsers.add_parser("search", help="Search the paper catalog and corpus.")
    search_parser.add_argument("--query", default="", help="Free-text query.")
    search_parser.add_argument("--tag", action="append", help="Filter by tag. Can be repeated.")
    search_parser.add_argument("--author", default="", help="Filter by author substring.")
    search_parser.add_argument("--year", default="", help="Filter by year.")
    search_parser.add_argument("--title", default="", help="Filter by title substring.")
    search_parser.add_argument("--limit", type=int, default=10, help="Maximum number of results.")
    search_parser.add_argument("--fulltext", action="store_true", help="Score using the full markdown text.")
    search_parser.set_defaults(func=cmd_search)

    show_parser = subparsers.add_parser("show", help="Show one paper record and a snippet.")
    show_parser.add_argument("--query", default="", help="Fuzzy query.")
    show_parser.add_argument("--title", default="", help="Title substring.")
    show_parser.add_argument("--tag", action="append", help="Filter by tag.")
    show_parser.add_argument("--author", default="", help="Filter by author substring.")
    show_parser.add_argument("--year", default="", help="Filter by year.")
    show_parser.set_defaults(func=cmd_show)

    ask_parser = subparsers.add_parser("ask", help="Ask PaperQA2 or local retrieval about the corpus.")
    ask_parser.add_argument("question", nargs="*", help="Question to ask.")
    ask_parser.add_argument("--query", default="", help="Question to ask.")
    ask_parser.add_argument(
        "--mode",
        choices=["auto", "paperqa", "local"],
        default="auto",
        help="Answer mode.",
    )
    ask_parser.add_argument("--k", type=int, default=10, help="PaperQA evidence chunks to retrieve.")
    ask_parser.add_argument(
        "--max-sources",
        type=int,
        default=5,
        help="Maximum sources to keep in the final PaperQA answer.",
    )
    ask_parser.add_argument(
        "--length",
        default=DEFAULT_ASK_LENGTH,
        help="Target answer length for PaperQA.",
    )
    ask_parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_ASK_LIMIT,
        help="Number of local evidence items to show.",
    )
    ask_parser.add_argument(
        "--llm-model",
        default=DEFAULT_PAPERQA_LLM,
        help="PaperQA chat model.",
    )
    ask_parser.add_argument(
        "--summary-model",
        default="",
        help="PaperQA summary model. Defaults to --llm-model.",
    )
    ask_parser.add_argument(
        "--embedding-model",
        default=DEFAULT_PAPERQA_EMBEDDING,
        help="PaperQA embedding model.",
    )
    ask_parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Rebuild the PaperQA cache before answering.",
    )
    ask_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print cache status while answering.",
    )
    ask_parser.set_defaults(func=cmd_ask)

    compare_parser = subparsers.add_parser("compare", help="Print the topic comparison matrix.")
    compare_parser.add_argument("--tag", action="append", help="Only include specific tags.")
    compare_parser.set_defaults(func=cmd_compare)

    questions_parser = subparsers.add_parser("questions", help="Print the standard question bank.")
    questions_parser.add_argument("--format", choices=["md", "json"], default="md", help="Output format.")
    questions_parser.set_defaults(func=cmd_questions)

    validate_parser = subparsers.add_parser("validate", help="Validate the generated KB outputs.")
    validate_parser.set_defaults(func=cmd_validate)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
