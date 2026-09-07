from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote


ROOT_DIR = Path(__file__).resolve().parents[1]
KB_DIR = ROOT_DIR / "kb"
SOURCE_DIR = ROOT_DIR / "md-batch"

if str(KB_DIR) not in sys.path:
    sys.path.insert(0, str(KB_DIR))

import build_paper_kb  # type: ignore  # noqa: E402
import bilingual_support  # type: ignore  # noqa: E402
import paper_kb_cli  # type: ignore  # noqa: E402


BASE_CATALOG_PATH = KB_DIR / "paper_catalog.jsonl"
ENRICHED_CATALOG_PATH = KB_DIR / "paper_catalog_enriched.jsonl"
BASE_MANIFEST_PATH = KB_DIR / "paperqa_manifest.csv"
ENRICHED_MANIFEST_PATH = KB_DIR / "paperqa_manifest_enriched.csv"
QUESTION_BANK_PATH = KB_DIR / "question_bank.jsonl"
QUESTION_BANK_MD_PATH = KB_DIR / "question_bank.md"
COMPARE_MATRIX_PATH = KB_DIR / "compare_matrix.md"
TOPIC_SUMMARY_PATH = KB_DIR / "topic_summary.md"
KNOWLEDGE_RAG_CONFIG_PATH = KB_DIR / "knowledge-rag-config.yaml"
CONFIG_PATH = KB_DIR / "config.yaml"

QUERY_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
SCHEMA_VERSION = 2


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        records.append(json.loads(line))
    return records


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_manifest(path: Path, records: Iterable[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["file_location", "title", "doi"])
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "file_location": record.get("file_location", ""),
                    "title": record.get("title", ""),
                    "doi": record.get("doi", ""),
                }
            )


def compact_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def ensure_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def normalize_tags_text(tags: Iterable[str]) -> str:
    items = [compact_text(tag).lower() for tag in tags if compact_text(tag)]
    return " " + " ".join(items) + " " if items else " "


def normalize_loaded_record(record: dict[str, Any]) -> dict[str, Any]:
    merged = dict(record)
    merged["file_location"] = compact_text(record.get("file_location", ""))
    merged["title"] = compact_text(record.get("title", ""))
    merged["title_zh"] = compact_text(record.get("title_zh", ""))
    merged["authors"] = compact_text(record.get("authors", ""))
    merged["doi"] = compact_text(record.get("doi", ""))
    merged["year"] = compact_text(record.get("year", ""))
    merged["primary_tag"] = compact_text(record.get("primary_tag", "uncategorized")) or "uncategorized"
    merged["tags"] = [compact_text(item) for item in ensure_list(record.get("tags", [])) if compact_text(item)]
    merged["headings"] = [compact_text(item) for item in ensure_list(record.get("headings", [])) if compact_text(item)]
    merged["section_count"] = int(record.get("section_count", 0) or 0)
    merged["word_count"] = int(record.get("word_count", 0) or 0)
    merged["abstract"] = compact_text(record.get("abstract", ""))
    merged["abstract_snippet"] = compact_text(record.get("abstract_snippet", ""))
    merged["abstract_zh"] = compact_text(record.get("abstract_zh", ""))
    merged["abstract_zh_snippet"] = compact_text(record.get("abstract_zh_snippet", ""))
    return merged


def record_export_view(record: dict[str, Any]) -> dict[str, Any]:
    exported = build_paper_kb.normalize_record(record)
    exported["year"] = compact_text(record.get("year", exported.get("year", "")))
    exported["doi"] = compact_text(record.get("doi", exported.get("doi", "")))
    exported["docname"] = compact_text(record.get("docname", ""))
    exported["metadata_source"] = compact_text(record.get("metadata_source", "markdown")) or "markdown"
    exported["crossref_title"] = compact_text(record.get("crossref_title", ""))
    exported["crossref_score"] = record.get("crossref_score")
    exported["primary_tag"] = compact_text(record.get("primary_tag", exported.get("primary_tag", "uncategorized"))) or "uncategorized"
    return exported


def source_signature(record: dict[str, Any]) -> str:
    digest = hashlib.sha256()
    digest.update(json.dumps(record_export_view(record), ensure_ascii=False, sort_keys=True).encode("utf-8"))
    digest.update(b"\0")
    digest.update(compact_text(record.get("content_hash", "")).encode("utf-8"))
    return digest.hexdigest()


def query_tokens(query: str) -> list[str]:
    return [token for token in QUERY_TOKEN_RE.findall(query.lower()) if len(token) > 1]


def preview_from_text(text: str, query: str, width: int = 2) -> str:
    if not text:
        return ""
    lines = text.splitlines()
    if not lines:
        return ""
    tokens = query_tokens(query)
    best_index = 0
    best_score = -1
    for index, line in enumerate(lines):
        lowered = line.lower()
        score = sum(lowered.count(token) for token in tokens)
        if score > best_score:
            best_score = score
            best_index = index
    start = max(0, best_index - width)
    end = min(len(lines), best_index + width + 1)
    pieces: list[str] = []
    for i in range(start, end):
        line = build_paper_kb.normalize_text(lines[i])
        if line:
            pieces.append(f"{i + 1}: {line}")
    return " | ".join(pieces)


def evidence_urls(file_location: str) -> dict[str, str]:
    relpath = Path(file_location).as_posix().strip()
    if not relpath:
        return {"paper_url": "", "raw_url": ""}
    encoded = quote(relpath, safe="/")
    return {"paper_url": f"/paper/{encoded}", "raw_url": f"/raw/{encoded}"}


def local_relevance_score(rank: Any) -> float:
    try:
        value = abs(float(rank or 0.0))
    except (TypeError, ValueError):
        value = 0.0
    return round(100.0 / (1.0 + value), 2)


def export_question_bank(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    questions = build_paper_kb.generate_question_bank(records)
    write_jsonl(QUESTION_BANK_PATH, questions)
    lines = ["# Paper KB Question Bank", "", "## Suggested Questions"]
    for item in questions:
        lines.append(f"- [{item['id']}] {item['question']}")
        titles = item.get("sample_titles", [])
        if isinstance(titles, list) and titles:
            lines.append(f"  - Samples: {', '.join(str(title) for title in titles)}")
    QUESTION_BANK_MD_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return questions


def export_compare_matrix(records: list[dict[str, Any]]) -> str:
    matrix = build_paper_kb.generate_compare_matrix(records)
    COMPARE_MATRIX_PATH.write_text(matrix, encoding="utf-8")
    return matrix


def export_topic_summary(records: list[dict[str, Any]]) -> str:
    summary = build_paper_kb.generate_topic_summary(records)
    TOPIC_SUMMARY_PATH.write_text(summary, encoding="utf-8")
    return summary


def export_knowledge_rag_config() -> None:
    config_text = """paths:
  documents_dir: "../md-batch"
  data_dir: "./data"

documents:
  supported_formats: [".md"]

models:
  embedding:
    profile: "compact"
    gpu: "auto"
  reranker:
    enabled: true

search:
  default_results: 5
  max_results: 25

server:
  transport: "stdio"
"""
    KNOWLEDGE_RAG_CONFIG_PATH.write_text(config_text, encoding="utf-8")
    CONFIG_PATH.write_text(config_text, encoding="utf-8")


@dataclass
class SearchFilters:
    query: str = ""
    tag: str = ""
    year: str = ""
    author: str = ""
    title: str = ""
    limit: int = 40


class PaperStore:
    def __init__(self, root: Path = ROOT_DIR) -> None:
        self.root = root
        self.kb_dir = root / "kb"
        self.source_dir = root / "md-batch"
        self.db_path = self.kb_dir / "paper_kb_web.sqlite3"
        self._metadata_map: dict[str, dict[str, Any]] | None = None

    def ensure_bootstrap(self) -> None:
        self.kb_dir.mkdir(parents=True, exist_ok=True)
        if not BASE_CATALOG_PATH.exists() or not QUESTION_BANK_PATH.exists() or not COMPARE_MATRIX_PATH.exists():
            build_paper_kb.build(self.source_dir, self.kb_dir)
        if not KNOWLEDGE_RAG_CONFIG_PATH.exists() or not CONFIG_PATH.exists():
            export_knowledge_rag_config()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def table_columns(self, conn: sqlite3.Connection, table_name: str) -> set[str]:
        try:
            rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        except sqlite3.OperationalError:
            return set()
        return {str(row["name"]) for row in rows}

    def rebuild_paper_fts(self, conn: sqlite3.Connection) -> None:
        conn.execute("DROP TABLE IF EXISTS paper_fts")
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS paper_fts USING fts5(
                file_location,
                docname,
                title,
                title_zh,
                authors,
                year,
                primary_tag,
                tags,
                abstract,
                abstract_zh,
                headings,
                body,
                tokenize='unicode61'
            )
            """
        )
        rows = conn.execute(
            """
            SELECT
                id, file_location, docname, title, title_zh, authors, year, primary_tag, tags_json,
                abstract, abstract_zh, headings_json, body
            FROM papers
            ORDER BY id
            """
        ).fetchall()
        for row in rows:
            record = dict(row)
            tags = " ".join(json.loads(record.get("tags_json", "[]") or "[]"))
            headings = " ".join(json.loads(record.get("headings_json", "[]") or "[]"))
            conn.execute(
                """
                INSERT INTO paper_fts (
                    rowid, file_location, docname, title, title_zh, authors, year, primary_tag, tags, abstract, abstract_zh, headings, body
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(record["id"]),
                    compact_text(record.get("file_location", "")),
                    compact_text(record.get("docname", "")),
                    compact_text(record.get("title", "")),
                    compact_text(record.get("title_zh", "")),
                    compact_text(record.get("authors", "")),
                    compact_text(record.get("year", "")),
                    compact_text(record.get("primary_tag", "uncategorized")) or "uncategorized",
                    tags,
                    compact_text(record.get("abstract", "")),
                    compact_text(record.get("abstract_zh", "")),
                    headings,
                    compact_text(record.get("body", "")),
                ),
            )

    def migrate_schema(self, conn: sqlite3.Connection) -> None:
        existing_columns = self.table_columns(conn, "papers")
        if not existing_columns:
            return
        column_defs = {
            "abstract": "TEXT NOT NULL DEFAULT ''",
            "title_zh": "TEXT NOT NULL DEFAULT ''",
            "abstract_zh": "TEXT NOT NULL DEFAULT ''",
            "abstract_zh_snippet": "TEXT NOT NULL DEFAULT ''",
        }
        for column, definition in column_defs.items():
            if column not in existing_columns:
                conn.execute(f"ALTER TABLE papers ADD COLUMN {column} {definition}")
        user_version = int(conn.execute("PRAGMA user_version").fetchone()[0] or 0)
        if user_version < SCHEMA_VERSION or not self.table_columns(conn, "paper_fts"):
            self.rebuild_paper_fts(conn)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def init_db(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS papers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_location TEXT NOT NULL UNIQUE,
                docname TEXT NOT NULL DEFAULT '',
                paper_stem TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                title_zh TEXT NOT NULL DEFAULT '',
                authors TEXT NOT NULL DEFAULT '',
                year TEXT NOT NULL DEFAULT '',
                doi TEXT NOT NULL DEFAULT '',
                primary_tag TEXT NOT NULL DEFAULT 'uncategorized',
                tags_json TEXT NOT NULL DEFAULT '[]',
                tags_text TEXT NOT NULL DEFAULT ' ',
                section_count INTEGER NOT NULL DEFAULT 0,
                word_count INTEGER NOT NULL DEFAULT 0,
                abstract TEXT NOT NULL DEFAULT '',
                abstract_snippet TEXT NOT NULL DEFAULT '',
                abstract_zh TEXT NOT NULL DEFAULT '',
                abstract_zh_snippet TEXT NOT NULL DEFAULT '',
                headings_json TEXT NOT NULL DEFAULT '[]',
                crossref_title TEXT NOT NULL DEFAULT '',
                crossref_score REAL,
                metadata_source TEXT NOT NULL DEFAULT 'markdown',
                source_mtime_ns INTEGER NOT NULL DEFAULT 0,
                source_size INTEGER NOT NULL DEFAULT 0,
                content_hash TEXT NOT NULL DEFAULT '',
                record_signature TEXT NOT NULL DEFAULT '',
                body TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_papers_year ON papers(year);
            CREATE INDEX IF NOT EXISTS idx_papers_tag ON papers(primary_tag);
            CREATE INDEX IF NOT EXISTS idx_papers_title ON papers(title);
            CREATE INDEX IF NOT EXISTS idx_papers_docname ON papers(docname);

            CREATE VIRTUAL TABLE IF NOT EXISTS paper_fts USING fts5(
                file_location,
                docname,
                title,
                title_zh,
                authors,
                year,
                primary_tag,
                tags,
                abstract,
                abstract_zh,
                headings,
                body,
                tokenize='unicode61'
            );

            CREATE TABLE IF NOT EXISTS sync_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                last_sync_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                total_papers INTEGER NOT NULL DEFAULT 0,
                added INTEGER NOT NULL DEFAULT 0,
                updated INTEGER NOT NULL DEFAULT 0,
                unchanged INTEGER NOT NULL DEFAULT 0,
                deleted INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        self.migrate_schema(conn)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_title_zh ON papers(title_zh)")
        conn.commit()

    def load_metadata_map(self) -> dict[str, dict[str, Any]]:
        if self._metadata_map is not None:
            return self._metadata_map
        source_path = ENRICHED_CATALOG_PATH if ENRICHED_CATALOG_PATH.exists() else BASE_CATALOG_PATH
        records = load_jsonl(source_path)
        self._metadata_map = {
            compact_text(record.get("file_location")): record
            for record in records
            if compact_text(record.get("file_location"))
        }
        return self._metadata_map

    def iter_source_files(self) -> list[Path]:
        if not self.source_dir.exists():
            return []
        return sorted(self.source_dir.glob("*.md"), key=lambda item: item.name.lower())

    def scan_source_records(self) -> list[dict[str, Any]]:
        metadata_map = self.load_metadata_map()
        records: list[dict[str, Any]] = []
        for index, path in enumerate(self.iter_source_files(), start=1):
            raw = path.read_text(encoding="utf-8", errors="replace")
            base_record = build_paper_kb.extract_record(path, self.source_dir)
            merged = dict(base_record)
            meta = metadata_map.get(base_record["file_location"], {})
            for key, value in meta.items():
                if key in {"body", "source_mtime_ns", "source_size", "content_hash", "record_signature"}:
                    continue
                if value is None:
                    continue
                if isinstance(value, str) and not value.strip():
                    continue
                if isinstance(value, (list, dict)) and not value:
                    continue
                merged[key] = value
            merged = normalize_loaded_record(merged)
            stat = path.stat()
            merged["body"] = raw
            merged["paper_stem"] = path.stem
            merged["source_mtime_ns"] = stat.st_mtime_ns
            merged["source_size"] = stat.st_size
            merged["content_hash"] = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()
            merged["docname"] = paper_kb_cli.build_paperqa_docname(merged, index)
            merged["tags_text"] = normalize_tags_text(merged.get("tags", []))
            merged["record_signature"] = source_signature(merged)
            records.append(merged)
        records, _, _, _ = bilingual_support.enrich_bilingual_records(
            records,
            self.kb_dir,
            provider=os.environ.get("PAPERKB_TRANSLATION_PROVIDER", "none"),
        )
        for record in records:
            record["record_signature"] = source_signature(record)
        return records

    def upsert_record(self, conn: sqlite3.Connection, record: dict[str, Any], paper_id: int | None = None) -> int:
        normalized = normalize_loaded_record(record)
        tags_json = json.dumps(normalized.get("tags", []), ensure_ascii=False)
        headings_json = json.dumps(normalized.get("headings", []), ensure_ascii=False)
        crossref_score = record.get("crossref_score")
        if crossref_score in ("", None):
            crossref_score = None
        row_values = (
            normalized.get("file_location", ""),
            compact_text(record.get("docname", "")),
            compact_text(record.get("paper_stem", "")),
            normalized.get("title", ""),
            normalized.get("title_zh", ""),
            normalized.get("authors", ""),
            normalized.get("year", ""),
            normalized.get("doi", ""),
            normalized.get("primary_tag", "uncategorized"),
            tags_json,
            normalize_tags_text(normalized.get("tags", [])),
            normalized.get("section_count", 0),
            normalized.get("word_count", 0),
            normalized.get("abstract", ""),
            normalized.get("abstract_snippet", ""),
            normalized.get("abstract_zh", ""),
            normalized.get("abstract_zh_snippet", ""),
            headings_json,
            compact_text(record.get("crossref_title", "")),
            crossref_score,
            compact_text(record.get("metadata_source", "markdown")) or "markdown",
            int(record.get("source_mtime_ns", 0) or 0),
            int(record.get("source_size", 0) or 0),
            compact_text(record.get("content_hash", "")),
            compact_text(record.get("record_signature", "")),
            compact_text(record.get("body", "")),
        )
        columns = (
            "file_location",
            "docname",
            "paper_stem",
            "title",
            "title_zh",
            "authors",
            "year",
            "doi",
            "primary_tag",
            "tags_json",
            "tags_text",
            "section_count",
            "word_count",
            "abstract",
            "abstract_snippet",
            "abstract_zh",
            "abstract_zh_snippet",
            "headings_json",
            "crossref_title",
            "crossref_score",
            "metadata_source",
            "source_mtime_ns",
            "source_size",
            "content_hash",
            "record_signature",
            "body",
        )

        if paper_id is None:
            existing = conn.execute(
                "SELECT id FROM papers WHERE file_location = ?",
                (normalized.get("file_location", ""),),
            ).fetchone()
            if existing:
                paper_id = int(existing["id"])

        if paper_id is None:
            placeholders = ", ".join("?" for _ in columns)
            cursor = conn.execute(
                f"INSERT INTO papers ({', '.join(columns)}) VALUES ({placeholders})",
                row_values,
            )
            paper_id = int(cursor.lastrowid)
        else:
            update_columns = ", ".join(f"{column} = ?" for column in columns)
            conn.execute(
                f"UPDATE papers SET {update_columns}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                row_values + (paper_id,),
            )
            conn.execute("DELETE FROM paper_fts WHERE rowid = ?", (paper_id,))

        conn.execute(
            """
            INSERT INTO paper_fts (
                rowid, file_location, docname, title, title_zh, authors, year, primary_tag, tags, abstract, abstract_zh, headings, body
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                paper_id,
                normalized.get("file_location", ""),
                compact_text(record.get("docname", "")),
                normalized.get("title", ""),
                normalized.get("title_zh", ""),
                normalized.get("authors", ""),
                normalized.get("year", ""),
                normalized.get("primary_tag", "uncategorized"),
                " ".join(normalized.get("tags", [])),
                normalized.get("abstract", ""),
                normalized.get("abstract_zh", ""),
                " ".join(normalized.get("headings", [])),
                compact_text(record.get("body", "")),
            ),
        )
        return paper_id

    def row_to_record(self, row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        record = dict(row)
        try:
            record["tags"] = json.loads(record.get("tags_json", "[]") or "[]")
        except Exception:
            record["tags"] = []
        try:
            record["headings"] = json.loads(record.get("headings_json", "[]") or "[]")
        except Exception:
            record["headings"] = []
        record["section_count"] = int(record.get("section_count", 0) or 0)
        record["word_count"] = int(record.get("word_count", 0) or 0)
        return record

    def all_records(self, order: str = "file_location") -> list[dict[str, Any]]:
        conn = self.connect()
        self.init_db(conn)
        order_by = {
            "file_location": "file_location COLLATE NOCASE ASC",
            "title": "title COLLATE NOCASE ASC",
            "year": "CASE WHEN year GLOB '[0-9]*' THEN CAST(year AS INTEGER) ELSE 0 END DESC, title COLLATE NOCASE ASC",
        }.get(order, "file_location COLLATE NOCASE ASC")
        rows = conn.execute(f"SELECT * FROM papers ORDER BY {order_by}").fetchall()
        conn.close()
        return [self.row_to_record(row) for row in rows]

    def paper_by_location(self, file_location: str) -> dict[str, Any] | None:
        conn = self.connect()
        self.init_db(conn)
        row = conn.execute("SELECT * FROM papers WHERE file_location = ?", (file_location,)).fetchone()
        conn.close()
        return self.row_to_record(row) if row else None

    def paper_by_docname(self, docname: str) -> dict[str, Any] | None:
        conn = self.connect()
        self.init_db(conn)
        row = conn.execute("SELECT * FROM papers WHERE docname = ?", (docname,)).fetchone()
        conn.close()
        return self.row_to_record(row) if row else None

    def stats(self) -> dict[str, Any]:
        conn = self.connect()
        self.init_db(conn)
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS paper_count,
                COALESCE(SUM(word_count), 0) AS word_count,
                MAX(updated_at) AS last_sync_at
            FROM papers
            """
        ).fetchone()
        state = conn.execute("SELECT * FROM sync_state WHERE id = 1").fetchone()
        conn.close()
        result = dict(row) if row else {"paper_count": 0, "word_count": 0, "last_sync_at": ""}
        if state:
            result.update(
                {
                    "last_sync_at": state["last_sync_at"],
                    "added": state["added"],
                    "updated": state["updated"],
                    "unchanged": state["unchanged"],
                    "deleted": state["deleted"],
                }
            )
        else:
            result.update({"added": 0, "updated": 0, "unchanged": 0, "deleted": 0})
        return result

    def facets(self) -> dict[str, list[dict[str, Any]]]:
        conn = self.connect()
        self.init_db(conn)
        tags = [
            {"name": row["primary_tag"], "count": int(row["count"])}
            for row in conn.execute(
                """
                SELECT primary_tag, COUNT(*) AS count
                FROM papers
                GROUP BY primary_tag
                ORDER BY count DESC, primary_tag COLLATE NOCASE ASC
                """
            ).fetchall()
        ]
        years = [
            {"name": row["year"], "count": int(row["count"])}
            for row in conn.execute(
                """
                SELECT year, COUNT(*) AS count
                FROM papers
                WHERE year != ''
                GROUP BY year
                ORDER BY CASE WHEN year GLOB '[0-9]*' THEN CAST(year AS INTEGER) ELSE 0 END DESC, year DESC
                """
            ).fetchall()
        ]
        conn.close()
        return {"tags": tags, "years": years}

    def sync(self, force: bool = False) -> dict[str, int]:
        self.ensure_bootstrap()
        source_records = self.scan_source_records()
        conn = self.connect()
        self.init_db(conn)
        existing_rows = conn.execute("SELECT id, file_location, record_signature FROM papers").fetchall()
        existing_map = {row["file_location"]: row for row in existing_rows}
        keep_locations: set[str] = set()
        counts = {"added": 0, "updated": 0, "unchanged": 0, "deleted": 0}

        for record in source_records:
            file_location = compact_text(record.get("file_location", ""))
            keep_locations.add(file_location)
            existing = existing_map.get(file_location)
            if existing and not force and compact_text(existing["record_signature"]) == compact_text(record.get("record_signature", "")):
                counts["unchanged"] += 1
                continue
            self.upsert_record(conn, record, int(existing["id"]) if existing else None)
            if existing:
                counts["updated"] += 1
            else:
                counts["added"] += 1

        deleted_ids = [int(row["id"]) for row in existing_rows if row["file_location"] not in keep_locations]
        if deleted_ids:
            placeholders = ", ".join("?" for _ in deleted_ids)
            conn.execute(f"DELETE FROM paper_fts WHERE rowid IN ({placeholders})", deleted_ids)
            conn.execute(f"DELETE FROM papers WHERE id IN ({placeholders})", deleted_ids)
            counts["deleted"] = len(deleted_ids)

        conn.execute(
            """
            INSERT INTO sync_state (id, last_sync_at, total_papers, added, updated, unchanged, deleted)
            VALUES (1, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                last_sync_at = excluded.last_sync_at,
                total_papers = excluded.total_papers,
                added = excluded.added,
                updated = excluded.updated,
                unchanged = excluded.unchanged,
                deleted = excluded.deleted
            """,
            (len(source_records), counts["added"], counts["updated"], counts["unchanged"], counts["deleted"]),
        )
        conn.commit()
        conn.close()

        records = self.all_records(order="file_location")
        self.export_generated_outputs(records)
        self._metadata_map = None
        return counts | {"total": len(records)}

    def export_generated_outputs(self, records: list[dict[str, Any]]) -> None:
        export_records = [record_export_view(record) for record in records]
        write_jsonl(ENRICHED_CATALOG_PATH, export_records)
        write_jsonl(BASE_CATALOG_PATH, export_records)
        write_manifest(ENRICHED_MANIFEST_PATH, export_records)
        write_manifest(BASE_MANIFEST_PATH, export_records)
        export_question_bank(export_records)
        export_compare_matrix(export_records)
        export_topic_summary(export_records)
        export_knowledge_rag_config()

    def ensure_index(self) -> dict[str, int]:
        self.ensure_bootstrap()
        conn = self.connect()
        self.init_db(conn)
        row = conn.execute("SELECT COUNT(*) AS count FROM papers").fetchone()
        bilingual_row = conn.execute(
            "SELECT COUNT(*) AS count FROM papers WHERE title_zh != '' OR abstract_zh != ''"
        ).fetchone()
        conn.close()
        if row and int(row["count"] or 0) > 0:
            if not bilingual_row or int(bilingual_row["count"] or 0) == 0:
                return self.sync(force=True)
            self.export_generated_outputs(self.all_records(order="file_location"))
            return {"total": int(row["count"]), "added": 0, "updated": 0, "unchanged": int(row["count"]), "deleted": 0}
        return self.sync(force=False)

    def search(self, filters: SearchFilters, *, use_fulltext: bool = True) -> list[dict[str, Any]]:
        conn = self.connect()
        self.init_db(conn)
        clauses: list[str] = []
        params: list[Any] = []

        if filters.tag:
            clauses.append("instr(lower(tags_text), lower(?)) > 0")
            params.append(f" {filters.tag.strip().lower()} ")
        if filters.year:
            clauses.append("year = ?")
            params.append(filters.year.strip())
        if filters.author:
            clauses.append("lower(authors) LIKE '%' || lower(?) || '%'")
            params.append(filters.author.strip())
        if filters.title:
            clauses.append("(lower(title) LIKE '%' || lower(?) || '%' OR lower(title_zh) LIKE '%' || lower(?) || '%')")
            params.extend([filters.title.strip(), filters.title.strip()])

        rows: list[sqlite3.Row] = []
        query = filters.query.strip()
        if query:
            tokens = query_tokens(query)
            if tokens and use_fulltext:
                search_queries = [" AND ".join(f'"{token}"' for token in tokens)]
                if len(tokens) > 1:
                    search_queries.append(" OR ".join(f'"{token}"' for token in tokens))
                for match_query in search_queries:
                    search_sql = """
                        SELECT
                            p.*,
                            bm25(paper_fts, 0.5, 0.5, 8.0, 8.0, 1.0, 0.5, 2.0, 3.0, 4.0, 4.0, 2.5, 1.0) AS rank,
                            snippet(paper_fts, 11, '<mark>', '</mark>', '...', 18) AS body_snippet
                        FROM paper_fts
                        JOIN papers p ON p.id = paper_fts.rowid
                        WHERE paper_fts MATCH ?
                    """
                    if clauses:
                        search_sql += " AND " + " AND ".join(clauses)
                    search_sql += " ORDER BY rank ASC, p.year DESC, p.title COLLATE NOCASE ASC"
                    rows = conn.execute(search_sql, [match_query, *params]).fetchall()
                    if rows:
                        break
                if not rows:
                    text_expr = (
                        "lower("
                        "title || ' ' || authors || ' ' || year || ' ' || doi || ' ' || primary_tag || ' ' "
                        "|| title_zh || ' ' || tags_text || ' ' || abstract || ' ' || abstract_snippet || ' ' "
                        "|| abstract_zh || ' ' || abstract_zh_snippet || ' ' || headings_json || ' ' || body"
                        ")"
                    )
                    search_sql = "SELECT p.*, 0.0 AS rank, '' AS body_snippet FROM papers p"
                    where_parts = list(clauses)
                    where_parts.append(f"{text_expr} LIKE '%' || lower(?) || '%'")
                    search_sql += " WHERE " + " AND ".join(where_parts)
                    rows = conn.execute(search_sql, [*params, query]).fetchall()
            else:
                text_expr = (
                    "lower("
                    "title || ' ' || authors || ' ' || year || ' ' || doi || ' ' || primary_tag || ' ' "
                    "|| title_zh || ' ' || tags_text || ' ' || abstract || ' ' || abstract_snippet || ' ' "
                    "|| abstract_zh || ' ' || abstract_zh_snippet || ' ' || headings_json || ' ' || body"
                    ")"
                )
                search_sql = "SELECT p.*, 0.0 AS rank, '' AS body_snippet FROM papers p"
                where_parts = list(clauses)
                where_parts.append(f"{text_expr} LIKE '%' || lower(?) || '%'")
                search_sql += " WHERE " + " AND ".join(where_parts)
                params.append(query)
                search_sql += " ORDER BY CASE WHEN year GLOB '[0-9]*' THEN CAST(year AS INTEGER) ELSE 0 END DESC, title COLLATE NOCASE ASC"
                rows = conn.execute(search_sql, params).fetchall()
        else:
            search_sql = "SELECT p.*, 0.0 AS rank, '' AS body_snippet FROM papers p"
            if clauses:
                search_sql += " WHERE " + " AND ".join(clauses)
            search_sql += " ORDER BY CASE WHEN year GLOB '[0-9]*' THEN CAST(year AS INTEGER) ELSE 0 END DESC, title COLLATE NOCASE ASC"
            rows = conn.execute(search_sql, params).fetchall()

        conn.close()

        results: list[dict[str, Any]] = []
        for row in rows:
            record = self.row_to_record(row)
            preview = compact_text(record.get("abstract_snippet", ""))
            if not preview and query:
                preview = compact_text(row["body_snippet"])
            if not preview:
                preview = preview_from_text(compact_text(record.get("body", "")), query)
            if not preview:
                body = compact_text(record.get("body", ""))
                preview = build_paper_kb.normalize_text(body.splitlines()[0]) if body else ""
            record["preview"] = preview
            record["preview_zh"] = compact_text(record.get("abstract_zh_snippet", ""))
            record["rank"] = float(row["rank"]) if row["rank"] is not None else 0.0
            results.append(record)
        return results

    def question_bank(self) -> list[dict[str, Any]]:
        records = self.all_records(order="file_location")
        questions = build_paper_kb.generate_question_bank(records)
        write_jsonl(QUESTION_BANK_PATH, questions)
        return questions

    def compare_records(self) -> list[dict[str, Any]]:
        return self.all_records(order="file_location")

    def build_paperqa_docs(
        self,
        records: list[dict[str, Any]],
        llm_model: str,
        summary_model: str,
        embedding_model: str,
        rebuild: bool = False,
    ) -> tuple[Any, list[str], int, bool]:
        return paper_kb_cli.get_paperqa_docs(
            records=records,
            source_dir=self.source_dir,
            llm_model_name=llm_model,
            summary_llm_name=summary_model,
            embedding_model_name=embedding_model,
            rebuild=rebuild,
        )

    def local_answer(self, question: str, limit: int = 5) -> dict[str, Any]:
        results = self.search(SearchFilters(query=question, limit=max(limit, 1)))
        top = results[0] if results else None
        answer = top.get("preview") if top else "No strong local match."
        if not compact_text(answer) and top:
            answer = compact_text(top.get("abstract_snippet", ""))
        evidence: list[dict[str, Any]] = []
        for item in results[:limit]:
            record = dict(item)
            links = evidence_urls(str(record.get("file_location", "")))
            context = compact_text(record.get("preview", "")) or compact_text(record.get("abstract_snippet", ""))
            evidence.append(
                {
                    "docname": compact_text(record.get("docname", "")),
                    "citation": paper_kb_cli.build_paperqa_citation(record),
                    "context": context,
                    "score": local_relevance_score(record.get("rank", 0.0)),
                    "title": record.get("title", ""),
                    "title_zh": record.get("title_zh", ""),
                    "file_location": record.get("file_location", ""),
                    "year": record.get("year", ""),
                    **links,
                }
            )
        return {"mode": "local", "answer": compact_text(answer), "evidence": evidence}

    def ask(
        self,
        question: str,
        *,
        mode: str = "auto",
        limit: int = 5,
        k: int = 10,
        max_sources: int = 5,
        length: str = "about 150 words",
        llm_model: str | None = None,
        summary_model: str | None = None,
        embedding_model: str | None = None,
        rebuild: bool = False,
    ) -> dict[str, Any]:
        question = question.strip()
        if not question:
            return {"mode": mode, "answer": "", "evidence": [], "error": "请输入问题。"}

        chosen_mode = mode
        if chosen_mode == "auto":
            chosen_mode = "paperqa" if paper_kb_cli.has_openai_key() else "local"

        if chosen_mode == "paperqa":
            if not paper_kb_cli.has_openai_key():
                return {"mode": "paperqa", "answer": "", "evidence": [], "error": "OPENAI_API_KEY is not set."}
            records = self.all_records(order="file_location")
            llm_model = llm_model or paper_kb_cli.DEFAULT_PAPERQA_LLM
            summary_model = summary_model or os.environ.get("PAPERQA_SUMMARY_MODEL") or llm_model
            embedding_model = embedding_model or paper_kb_cli.DEFAULT_PAPERQA_EMBEDDING
            docs, skipped, loaded, from_cache = self.build_paperqa_docs(
                records=records,
                llm_model=llm_model,
                summary_model=summary_model,
                embedding_model=embedding_model,
                rebuild=rebuild,
            )
            if loaded == 0:
                return {"mode": "paperqa", "answer": "", "evidence": [], "error": "No documents were indexed for PaperQA."}
            answer = docs.query(
                question,
                k=max(k, max_sources),
                max_sources=max_sources,
                length_prompt=length,
            )
            formatted = compact_text(getattr(answer, "formatted_answer", "")) or compact_text(getattr(answer, "answer", ""))
            evidence = self.paperqa_evidence(answer, records, limit=limit)
            return {
                "mode": "paperqa",
                "answer": formatted or "I cannot answer this question due to insufficient information.",
                "evidence": evidence,
                "skipped": skipped,
                "loaded": loaded,
                "from_cache": from_cache,
                "question": question,
                "references": compact_text(getattr(answer, "references", "")),
            }

        local = self.local_answer(question, limit=limit)
        local["question"] = question
        return local

    def paperqa_evidence(self, answer: Any, records: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
        docname_map: dict[str, dict[str, Any]] = {}
        for index, record in enumerate(records, start=1):
            docname = paper_kb_cli.build_paperqa_docname(record, index)
            docname_map[docname] = record

        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        contexts = list(getattr(answer, "contexts", []) or [])
        contexts.sort(key=lambda context: int(getattr(context, "score", 0) or 0), reverse=True)
        for context in contexts:
            doc = getattr(getattr(context, "text", None), "doc", None)
            if doc is None:
                continue
            docname = compact_text(getattr(doc, "docname", ""))
            if not docname or docname in seen:
                continue
            seen.add(docname)
            record = docname_map.get(docname)
            if not record:
                continue
            relpath = Path(str(record.get("file_location", ""))).as_posix()
            items.append(
                {
                    "docname": docname,
                    "citation": compact_text(getattr(doc, "citation", "")),
                    "context": compact_text(getattr(context, "context", "")),
                    "score": int(getattr(context, "score", 0) or 0),
                    "title": record.get("title", ""),
                    "title_zh": record.get("title_zh", ""),
                    "file_location": record.get("file_location", ""),
                    "paper_url": f"/paper/{quote(relpath, safe='/')}",
                    "raw_url": f"/raw/{quote(relpath, safe='/')}",
                }
            )
            if len(items) >= limit:
                break
        return items


STORE = PaperStore()
