from __future__ import annotations

import argparse
import csv
import json
import re
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen


KB_DIR = Path(__file__).resolve().parent
BASE_CATALOG = KB_DIR / "paper_catalog.jsonl"
BASE_MANIFEST = KB_DIR / "paperqa_manifest.csv"
ENRICHED_CATALOG = KB_DIR / "paper_catalog_enriched.jsonl"
ENRICHED_MANIFEST = KB_DIR / "paperqa_manifest_enriched.csv"
REPORT_PATH = KB_DIR / "metadata_enrichment_report.json"
CACHE_PATH = KB_DIR / "crossref_cache.json"

STOPWORDS = {
    "a",
    "an",
    "and",
    "the",
    "of",
    "for",
    "to",
    "with",
    "using",
    "based",
    "method",
    "methodology",
    "approach",
    "technique",
    "paper",
    "design",
    "model",
    "models",
    "modeling",
    "analysis",
    "optimization",
    "fast",
    "new",
    "novel",
    "advanced",
    "recent",
    "study",
    "toward",
    "towards",
    "on",
    "in",
    "from",
    "by",
    "via",
}


def load_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    records: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokenize(text: str) -> set[str]:
    return {token for token in normalize(text).split() if token and token not in STOPWORDS}


def year_from_item(item: dict[str, object]) -> str:
    for key in ("published-print", "published-online", "issued", "created"):
        value = item.get(key)
        if isinstance(value, dict):
            parts = value.get("date-parts")
            if isinstance(parts, list) and parts:
                first = parts[0]
                if isinstance(first, list) and first:
                    year = first[0]
                    if isinstance(year, int):
                        return str(year)
                    if isinstance(year, str) and year.isdigit():
                        return year
    return ""


def item_title(item: dict[str, object]) -> str:
    titles = item.get("title")
    if isinstance(titles, list) and titles:
        return str(titles[0]).strip()
    if isinstance(titles, str):
        return titles.strip()
    return ""


def candidate_score(query_title: str, candidate_title: str) -> float:
    q_tokens = tokenize(query_title)
    c_tokens = tokenize(candidate_title)
    if not q_tokens or not c_tokens:
        return 0.0
    overlap = len(q_tokens & c_tokens)
    if not overlap:
        return 0.0
    score = overlap / max(len(q_tokens), len(c_tokens))
    q_norm = normalize(query_title)
    c_norm = normalize(candidate_title)
    if q_norm and q_norm in c_norm:
        score += 0.5
    if c_norm and c_norm in q_norm:
        score += 0.25
    return score


def fetch_crossref(title: str) -> list[dict[str, object]]:
    url = f"https://api.crossref.org/works?query.title={quote_plus(title)}&rows=5"
    request = Request(url, headers={"User-Agent": "Codex paper kb metadata enricher"})
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))
    message = payload.get("message", {})
    items = message.get("items", [])
    return items if isinstance(items, list) else []


def best_crossref_match(title: str, cache: dict[str, object]) -> dict[str, object] | None:
    if title in cache:
        cached = cache[title]
        return cached if isinstance(cached, dict) and cached else None

    try:
        items = fetch_crossref(title)
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
        cache[title] = None
        return None

    best_item: dict[str, object] | None = None
    best_score = 0.0
    for item in items:
        if not isinstance(item, dict):
            continue
        candidate = item_title(item)
        score = candidate_score(title, candidate)
        if score > best_score:
            best_score = score
            best_item = item

    if best_item and best_score >= 0.35:
        cache[title] = best_item
        return best_item

    cache[title] = None
    return None


def update_records(records: list[dict[str, object]]) -> tuple[list[dict[str, object]], dict[str, object]]:
    if CACHE_PATH.exists():
        try:
            cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            cache = {}
    else:
        cache = {}

    updated: list[dict[str, object]] = []
    stats = {
        "records": len(records),
        "matched": 0,
        "updated_year": 0,
        "updated_doi": 0,
        "failed": 0,
    }

    for record in records:
        title = str(record.get("title", "")).strip()
        if not title:
            updated.append(record)
            continue
        match = best_crossref_match(title, cache)
        if not match:
            updated.append(record)
            stats["failed"] += 1
            continue

        new_record = dict(record)
        stats["matched"] += 1
        year = year_from_item(match)
        doi = str(match.get("DOI", "")).strip()
        if year and not str(new_record.get("year", "")).strip():
            new_record["year"] = year
            stats["updated_year"] += 1
        if doi and not str(new_record.get("doi", "")).strip():
            new_record["doi"] = doi
            stats["updated_doi"] += 1
        new_record["crossref_title"] = item_title(match)
        new_record["crossref_score"] = round(candidate_score(title, new_record["crossref_title"]), 3)
        new_record["metadata_source"] = "crossref" if year or doi else "markdown"
        updated.append(new_record)
        time.sleep(0.15)

    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    return updated, stats


def write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_manifest(path: Path, records: list[dict[str, object]]) -> None:
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Enrich the paper catalog with Crossref metadata.")
    parser.add_argument("--apply", action="store_true", help="Write enriched outputs to disk.")
    args = parser.parse_args()

    records = load_jsonl(BASE_CATALOG)
    if not records:
        raise FileNotFoundError(BASE_CATALOG)

    updated, stats = update_records(records)
    if args.apply:
        write_jsonl(ENRICHED_CATALOG, updated)
        write_manifest(ENRICHED_MANIFEST, updated)
        REPORT_PATH.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote {ENRICHED_CATALOG}")
        print(f"Wrote {ENRICHED_MANIFEST}")
        print(f"Wrote {REPORT_PATH}")
    else:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
