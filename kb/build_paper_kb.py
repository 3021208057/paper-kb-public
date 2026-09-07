from __future__ import annotations

import argparse
import csv
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

import bilingual_support


TITLE_RE = re.compile(r"^#\s+(?P<title>.+?)\s*$")
HEADING_RE = re.compile(r"^#{2,6}\s+(.+?)\s*$")
WORD_RE = re.compile(r"\b[\w\-]+\b", re.UNICODE)

TAG_RULES: list[tuple[str, list[str]]] = [
    ("macromodeling", ["macromodel", "macromodeling", "time-domain", "time domain", "behavioral modeling"]),
    ("neuro-TF", ["neuro-tf", "transfer function", "pole-residue", "pole residue"]),
    ("space-mapping", ["space mapping", "mesh space mapping", "mapping"]),
    ("surrogate", ["surrogate", "surrogate-assisted"]),
    ("topology-optimization", ["topology optimization", "topology-optimization"]),
    ("simulation-inserted-optimization", ["simulation-inserted optimization", "simulation inserted optimization", "augmented lagrangian", "quasi-newton"]),
    ("physics-informed", ["physics-informed", "pinn"]),
    ("neural-network", ["neural network", "deep learning", "gru", "lstm", "ann"]),
    ("MOR", ["model order reduction", "model-order reduction", "reduced-order", "reduced order", "mpvl", "arnoldi"]),
    ("waveguide-filter", ["waveguide filter", "cavity waveguide", "microwave filter", "waveguide", "filter"]),
    ("coupling-matrix", ["coupling matrix", "multiplexer", "coupled cavity", "coupling"]),
    ("sensitivity-analysis", ["sensitivity analysis", "sensitivity"]),
    ("yield-estimation", ["yield estimation", "yield"]),
    ("GaN-HEMT", ["gan hemt", "hemt"]),
    ("metasurface", ["metasurface", "terahertz", "lens"]),
    ("quantum", ["quantum"]),
]

TOPIC_NOTES: dict[str, str] = {
    "macromodeling": "Time-domain and behavioral circuit modeling.",
    "neuro-TF": "Transfer-function / pole-residue modeling for microwave structures.",
    "space-mapping": "Coarse-model guided optimization and mapping methods.",
    "surrogate": "Surrogate-assisted optimization and response approximation.",
    "topology-optimization": "Topology search and structure reshaping for EM devices.",
    "simulation-inserted-optimization": "Coupled simulation and optimization loops.",
    "physics-informed": "Physics-informed neural modeling and hybrid solvers.",
    "neural-network": "Neural-network based EM and circuit modeling.",
    "MOR": "Model order reduction for faster FEM / EM analysis.",
    "waveguide-filter": "Waveguide and microwave filter design and optimization.",
    "coupling-matrix": "Coupling-matrix synthesis and multiplexer design.",
    "sensitivity-analysis": "Sensitivity analysis and gradient acceleration.",
    "yield-estimation": "Yield, tolerance, and statistical design analysis.",
    "GaN-HEMT": "GaN HEMT device modeling and compact models.",
    "metasurface": "Metasurface, lens, and THz beam-steering designs.",
    "quantum": "Quantum or hybrid quantum-classical EM methods.",
}

REPRESENTATIVE_HINTS: dict[str, list[str]] = {
    "macromodeling": ["macromodel", "macromodeling", "deep gru", "rnn", "lstm"],
    "neuro-TF": ["neuro-tf", "transfer function", "pole-residue", "pole residue"],
    "space-mapping": ["space mapping", "mesh space mapping", "coarse model"],
    "surrogate": ["surrogate", "surrogate-assisted"],
    "topology-optimization": ["topology optimization", "topology-optimization"],
    "simulation-inserted-optimization": ["simulation-inserted optimization", "augmented lagrangian", "quasi-newton"],
    "physics-informed": ["physics-informed", "pinn"],
    "neural-network": ["neural network", "deep learning", "ann", "gru", "lstm"],
    "MOR": ["model order reduction", "mor", "arnoldi", "mpvl"],
    "waveguide-filter": ["waveguide filter", "waveguide", "filter"],
    "coupling-matrix": ["coupling matrix", "multiplexer", "coupled cavity"],
    "sensitivity-analysis": ["sensitivity analysis", "sensitivity"],
    "yield-estimation": ["yield estimation", "yield", "polynomial chaos"],
    "GaN-HEMT": ["gan hemt", "hemt", "trapping", "self-heating"],
    "metasurface": ["metasurface", "terahertz", "lens"],
    "quantum": ["quantum", "hhl", "block-encoding"],
}

QUESTION_TEMPLATES: list[dict[str, str]] = [
    {
        "topic": "waveguide-filter",
        "question": "Which papers focus on waveguide filter design or optimization, and what modeling or optimization methods do they use?",
        "intent": "overview",
    },
    {
        "topic": "MOR",
        "question": "Which papers use model order reduction to speed up EM simulation or optimization?",
        "intent": "methods",
    },
    {
        "topic": "neuro-TF",
        "question": "Which papers model EM responses with transfer functions, pole-residue models, or neuro-TF methods?",
        "intent": "methods",
    },
    {
        "topic": "space-mapping",
        "question": "Which papers use space mapping or mesh-based coarse models, and how are they coupled to the fine model?",
        "intent": "methods",
    },
    {
        "topic": "surrogate",
        "question": "Which papers are surrogate-assisted, and what surrogate features or response models are used?",
        "intent": "methods",
    },
    {
        "topic": "simulation-inserted-optimization",
        "question": "Which papers use simulation-inserted optimization, and how is the optimizer coupled to the simulator?",
        "intent": "methods",
    },
    {
        "topic": "topology-optimization",
        "question": "Which papers are about EM topology optimization, and what acceleration strategy do they rely on?",
        "intent": "methods",
    },
    {
        "topic": "macromodeling",
        "question": "Which papers study nonlinear circuit macromodeling, and which recurrent or deep learning models are used?",
        "intent": "methods",
    },
    {
        "topic": "neural-network",
        "question": "Which papers use neural networks for EM or circuit modeling, and what architecture or training trick stands out?",
        "intent": "methods",
    },
    {
        "topic": "sensitivity-analysis",
        "question": "Which papers focus on EM sensitivity analysis, and what reduces the computational cost?",
        "intent": "methods",
    },
    {
        "topic": "yield-estimation",
        "question": "Which papers estimate manufacturing yield or tolerance robustness, and how is uncertainty handled?",
        "intent": "methods",
    },
    {
        "topic": "GaN-HEMT",
        "question": "Which papers model GaN HEMTs, and what physical effects are explicitly included?",
        "intent": "device",
    },
    {
        "topic": "metasurface",
        "question": "Which papers cover metasurface or terahertz lens design, and what makes the method scalable?",
        "intent": "device",
    },
    {
        "topic": "quantum",
        "question": "Which papers explore quantum or hybrid quantum-classical methods for EM problems?",
        "intent": "special",
    },
]

COMPARE_GROUPS: list[tuple[str, list[str]]] = [
    ("Modeling", ["neuro-TF", "macromodeling", "neural-network", "physics-informed"]),
    ("Acceleration", ["MOR", "space-mapping", "surrogate", "simulation-inserted-optimization", "sensitivity-analysis"]),
    ("Design", ["waveguide-filter", "topology-optimization", "coupling-matrix", "yield-estimation"]),
    ("Devices and Special Topics", ["GaN-HEMT", "metasurface", "quantum"]),
]


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def strip_markdown(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"\[[^\]]+\]\([^)]+\)", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[`*_>#]", " ", text)
    return normalize_text(text)


def parse_title(lines: list[str], fallback: str) -> str:
    for line in lines:
        m = TITLE_RE.match(line)
        if m:
            return m.group("title").strip()
    return fallback


def parse_authors(lines: list[str]) -> str:
    seen_title = False
    for line in lines:
        if TITLE_RE.match(line):
            seen_title = True
            continue
        if not seen_title:
            continue
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.lower().startswith("abstract"):
            break
        if stripped.startswith("#"):
            break
        return normalize_text(re.sub(r"<[^>]+>", " ", stripped))
    return ""


def parse_abstract(lines: list[str]) -> str:
    abstract_lines: list[str] = []
    in_abstract = False
    for line in lines:
        if TITLE_RE.match(line):
            continue
        stripped = line.strip()
        if not stripped:
            if in_abstract and abstract_lines:
                abstract_lines.append("")
            continue
        if stripped.startswith("##"):
            if in_abstract:
                break
            continue
        if stripped.lower().startswith("abstract"):
            in_abstract = True
            cleaned = re.sub(r"^abstract[^A-Za-z0-9]+", "", stripped, flags=re.I)
            cleaned = cleaned.replace("Abstract", "", 1).strip()
            if cleaned:
                abstract_lines.append(cleaned)
            continue
        if in_abstract:
            abstract_lines.append(stripped)
    return normalize_text(" ".join(abstract_lines))


def parse_headings(lines: list[str]) -> list[str]:
    headings: list[str] = []
    for line in lines:
        m = HEADING_RE.match(line.strip())
        if m:
            headings.append(normalize_text(m.group(1)))
    return headings


def assign_tags(text: str) -> list[str]:
    lowered = text.lower()
    tags: list[str] = []
    for tag, keywords in TAG_RULES:
        if any(keyword.lower() in lowered for keyword in keywords):
            tags.append(tag)
    return tags


def extract_record(path: Path, source_dir: Path) -> dict[str, object]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    lines = raw.splitlines()
    title = parse_title(lines, path.stem)
    authors = parse_authors(lines)
    abstract = parse_abstract(lines)
    headings = parse_headings(lines)
    body_text = strip_markdown(raw)
    word_count = len(WORD_RE.findall(body_text))
    section_count = sum(1 for line in lines if line.lstrip().startswith("##"))
    tag_input = " ".join(part for part in [title, authors, abstract, " ".join(headings[:8])] if part)
    tags = assign_tags(tag_input)
    primary_tag = tags[0] if tags else "uncategorized"

    return {
        "file_location": path.relative_to(source_dir).as_posix(),
        "title": title,
        "authors": authors,
        "doi": "",
        "year": "",
        "primary_tag": primary_tag,
        "tags": tags,
        "section_count": section_count,
        "word_count": word_count,
        "abstract": abstract,
        "abstract_snippet": abstract[:260],
        "title_zh": "",
        "abstract_zh": "",
        "abstract_zh_snippet": "",
        "headings": headings[:8],
    }


def normalize_record(record: dict[str, object]) -> dict[str, object]:
    tags = record.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    headings = record.get("headings", [])
    if not isinstance(headings, list):
        headings = []
    return {
        "file_location": str(record.get("file_location", "")),
        "title": str(record.get("title", "")),
        "title_zh": str(record.get("title_zh", "")),
        "authors": str(record.get("authors", "")),
        "doi": str(record.get("doi", "")),
        "year": str(record.get("year", "")),
        "primary_tag": str(record.get("primary_tag", "uncategorized")),
        "tags": tags,
        "section_count": int(record.get("section_count", 0) or 0),
        "word_count": int(record.get("word_count", 0) or 0),
        "abstract": str(record.get("abstract", "")),
        "abstract_snippet": str(record.get("abstract_snippet", "")),
        "abstract_zh": str(record.get("abstract_zh", "")),
        "abstract_zh_snippet": str(record.get("abstract_zh_snippet", "")),
        "headings": headings,
    }


def display_title(record: dict[str, object]) -> str:
    return bilingual_support.bilingual_label(str(record.get("title", "")), str(record.get("title_zh", "")))


def build_tag_index(records: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for record in records:
        normalized = normalize_record(record)
        tags = normalized.get("tags", [])
        if not tags:
            grouped["uncategorized"].append(normalized)
            continue
        for tag in tags:
            grouped[str(tag)].append(normalized)
    return grouped


def representative_titles(records: list[dict[str, object]], limit: int = 3, tag: str | None = None) -> list[str]:
    hints = REPRESENTATIVE_HINTS.get(tag or "", [])

    def relevance(item: dict[str, object]) -> tuple[int, int, str]:
        text = " ".join(
            [
                str(item.get("title", "")),
                str(item.get("authors", "")),
                str(item.get("abstract_snippet", "")),
                " ".join(str(value) for value in item.get("headings", []) if value),
            ]
        ).lower()
        score = 0
        for hint in hints:
            if hint.lower() in text:
                score += 3
        if tag and str(item.get("primary_tag", "")).lower() == tag.lower():
            score += 2
        review_penalty = 1 if any(term in text for term in ["state of the art", "recent advances", "review"]) else 0
        title = str(item.get("title", ""))
        noise_penalty = 0
        for token in re.findall(r"\S+", title):
            if any(ch.isdigit() for ch in token):
                noise_penalty += 1
            if len(token) >= 6 and token.isupper():
                noise_penalty += 1
        noise_penalty += title.count("\ufffd")
        return (-score, review_penalty, noise_penalty, title.lower())

    ordered = sorted(records, key=relevance)
    titles: list[str] = []
    seen: set[str] = set()
    for record in ordered[:limit]:
        title = display_title(record).strip()
        if title and title.lower() not in seen:
            titles.append(title)
            seen.add(title.lower())
    return titles


def generate_topic_summary(records: list[dict[str, object]]) -> str:
    grouped = build_tag_index(records)
    counter = Counter()
    for tag, items in grouped.items():
        counter[tag] = len(items)

    lines = [
        "# Paper KB Summary",
        "",
        f"Total papers: {len(records)}",
        "",
        "## Tag Counts",
    ]
    for tag, count in counter.most_common():
        lines.append(f"- {tag}: {count}")

    lines.extend(["", "## Representative Papers"])
    for tag, count in counter.most_common():
        examples = representative_titles(grouped[tag], limit=3, tag=tag)
        if not examples:
            continue
        lines.append(f"### {tag}")
        for title in examples:
            lines.append(f"- {title}")
    return "\n".join(lines) + "\n"


def generate_question_bank(records: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped = build_tag_index(records)
    questions: list[dict[str, object]] = []
    for idx, template in enumerate(QUESTION_TEMPLATES, start=1):
        tag = template["topic"]
        if tag not in grouped or not grouped[tag]:
            continue
        questions.append(
            {
                "id": f"Q{idx:02d}",
                "topic": tag,
                "intent": template["intent"],
                "question": template["question"],
                "sample_titles": representative_titles(grouped[tag], limit=3, tag=tag),
            }
        )

    if grouped.get("waveguide-filter") and grouped.get("MOR"):
        questions.append(
            {
                "id": f"Q{len(questions)+1:02d}",
                "topic": "waveguide-filter+MOR",
                "intent": "compare",
                "question": "Which papers combine waveguide filter design with MOR-based acceleration?",
                "sample_titles": representative_titles(grouped["waveguide-filter"] + grouped["MOR"], limit=3),
            }
        )
    if grouped.get("neuro-TF") and grouped.get("space-mapping"):
        questions.append(
            {
                "id": f"Q{len(questions)+1:02d}",
                "topic": "neuro-TF+space-mapping",
                "intent": "compare",
                "question": "Which papers compare neuro-TF modeling and space-mapping style coarse models?",
                "sample_titles": representative_titles(grouped["neuro-TF"] + grouped["space-mapping"], limit=3),
            }
        )
    if grouped.get("surrogate") and grouped.get("simulation-inserted-optimization"):
        questions.append(
            {
                "id": f"Q{len(questions)+1:02d}",
                "topic": "surrogate+simulation-inserted-optimization",
                "intent": "compare",
                "question": "Which papers use surrogate models together with simulation-inserted optimization?",
                "sample_titles": representative_titles(grouped["surrogate"] + grouped["simulation-inserted-optimization"], limit=3),
            }
        )
    return questions


def generate_compare_matrix(records: list[dict[str, object]]) -> str:
    grouped = build_tag_index(records)
    lines = [
        "# Corpus Comparison Matrix",
        "",
    ]
    for section_title, tags in COMPARE_GROUPS:
        lines.extend(
            [
                f"## {section_title}",
                "",
                "| Topic | Count | Main angle | Representative papers |",
                "|---|---:|---|---|",
            ]
        )
        for tag in tags:
            items = grouped.get(tag, [])
            examples = representative_titles(items, limit=3, tag=tag)
            if not items:
                continue
            lines.append(f"| {tag} | {len(items)} | {TOPIC_NOTES.get(tag, '')} | {'<br>'.join(examples)} |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_manifest(records: list[dict[str, object]], output_dir: Path) -> Path:
    manifest_path = output_dir / "paperqa_manifest.csv"
    with manifest_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["file_location", "title", "doi"])
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "file_location": record["file_location"],
                    "title": record["title"],
                    "doi": record["doi"],
                }
            )
    return manifest_path


def write_catalog(records: list[dict[str, object]], output_dir: Path) -> Path:
    catalog_path = output_dir / "paper_catalog.jsonl"
    with catalog_path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(normalize_record(record), ensure_ascii=False) + "\n")
    return catalog_path


def write_summary(records: list[dict[str, object]], output_dir: Path) -> Path:
    summary_path = output_dir / "topic_summary.md"
    summary_path.write_text(generate_topic_summary(records), encoding="utf-8")
    return summary_path


def write_question_bank(records: list[dict[str, object]], output_dir: Path) -> Path:
    bank_path = output_dir / "question_bank.jsonl"
    questions = generate_question_bank(records)
    with bank_path.open("w", encoding="utf-8") as fh:
        for question in questions:
            fh.write(json.dumps(question, ensure_ascii=False) + "\n")
    return bank_path


def write_question_bank_markdown(records: list[dict[str, object]], output_dir: Path) -> Path:
    md_path = output_dir / "question_bank.md"
    questions = generate_question_bank(records)
    lines = [
        "# Paper KB Question Bank",
        "",
        "## Suggested Questions",
    ]
    for item in questions:
        titles = item.get("sample_titles", [])
        if not isinstance(titles, list):
            titles = []
        lines.append(f"- [{item['id']}] {item['question']}")
        if titles:
            lines.append(f"  - Samples: {', '.join(str(title) for title in titles)}")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path


def write_compare_matrix_file(records: list[dict[str, object]], output_dir: Path) -> Path:
    matrix_path = output_dir / "compare_matrix.md"
    matrix_path.write_text(generate_compare_matrix(records), encoding="utf-8")
    return matrix_path


def write_knowledge_rag_config(source_dir: Path, output_dir: Path) -> Path:
    config_path = output_dir / "knowledge-rag-config.yaml"
    alias_path = output_dir / "config.yaml"
    relative_documents_dir = Path("..") / source_dir.name
    config = f"""paths:
  documents_dir: "{relative_documents_dir.as_posix()}"
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
    config_path.write_text(config, encoding="utf-8")
    alias_path.write_text(config, encoding="utf-8")
    return config_path


def build(source_dir: Path, output_dir: Path) -> None:
    if not source_dir.exists():
        raise FileNotFoundError(source_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    md_files = sorted(source_dir.glob("*.md"), key=lambda p: p.name.lower())
    records = [extract_record(path, source_dir) for path in md_files]
    records, _, provider, warnings = bilingual_support.enrich_bilingual_records(
        records,
        output_dir,
        provider=os.environ.get("PAPERKB_TRANSLATION_PROVIDER", "none"),
    )
    if provider != "none":
        print(f"Translated bilingual metadata with provider: {provider}")
    for warning in warnings:
        print(f"Warning: {warning}")

    write_manifest(records, output_dir)
    write_catalog(records, output_dir)
    write_summary(records, output_dir)
    write_question_bank(records, output_dir)
    write_question_bank_markdown(records, output_dir)
    write_compare_matrix_file(records, output_dir)
    write_knowledge_rag_config(source_dir, output_dir)

    print(f"Indexed {len(records)} markdown files from {source_dir}")
    print(
        "Wrote paperqa_manifest.csv, paper_catalog.jsonl, topic_summary.md, "
        "question_bank.jsonl, question_bank.md, compare_matrix.md, knowledge-rag-config.yaml, and config.yaml "
        f"to {output_dir}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a paper knowledge-base catalog from Markdown papers.")
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "md-batch",
        help="Folder containing the converted Markdown papers.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Folder to write KB artifacts into.",
    )
    args = parser.parse_args()
    build(args.source, args.output)


if __name__ == "__main__":
    main()
