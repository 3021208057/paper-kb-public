from __future__ import annotations

import html
import re
from pathlib import Path
from urllib.parse import quote

from markdown import Markdown


LINK_RE = re.compile(r"(!?)\[([^\]\n]*)\]\(([^)\n]*)\)")
DISPLAY_DOLLAR_RE = re.compile(r"(?<!\\)\$\$(.*?)(?<!\\)\$\$", re.DOTALL)
DISPLAY_BRACKET_RE = re.compile(r"\\\[(.*?)\\\]", re.DOTALL)
INLINE_PAREN_RE = re.compile(r"\\\(((?:\\.|[^\n])+?)\\\)")
INLINE_DOLLAR_RE = re.compile(r"(?<!\\)(?<!\$)\$(?!\$)((?:\\.|[^\n$])+?)(?<!\\)\$(?!\$)")


def unwrap_target(target: str) -> str:
    target = target.strip()
    if len(target) >= 2 and ((target[0] == "<" and target[-1] == ">") or (target[0] == '"' and target[-1] == '"') or (target[0] == "'" and target[-1] == "'")):
        target = target[1:-1].strip()
    return target


def resolve_relative_target(
    target: str,
    current_file: Path,
    source_root: Path,
    base_dirs: list[Path],
) -> Path | None:
    if not target:
        return None
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target):
        return None

    candidate_paths: list[Path] = []
    target_path = Path(target)
    if target_path.is_absolute():
        candidate_paths.append(target_path)
    else:
        candidate_paths.append((current_file.parent / target_path).resolve())
        for base_dir in base_dirs:
            candidate_paths.append((base_dir / target_path).resolve())
        candidate_paths.append((source_root / target_path).resolve())

    for candidate in candidate_paths:
        try:
            candidate.relative_to(source_root)
        except ValueError:
            continue
        if candidate.exists():
            return candidate
    return None


def rewrite_local_links(raw: str, current_file: Path, source_root: Path) -> str:
    base_dirs = [current_file.parent]
    if current_file.parent == source_root:
        asset_dir = source_root / current_file.stem
        if asset_dir.exists() and asset_dir not in base_dirs:
            base_dirs.append(asset_dir)

    def repl(match: re.Match[str]) -> str:
        bang = match.group(1)
        label = match.group(2)
        target = unwrap_target(match.group(3))
        if not target or target.startswith("#"):
            return match.group(0)
        if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target):
            return match.group(0)

        path_part, fragment = target.split("#", 1) if "#" in target else (target, "")
        resolved = resolve_relative_target(path_part, current_file, source_root, base_dirs)
        if resolved is None:
            return match.group(0)

        rel = resolved.relative_to(source_root).as_posix()
        if resolved.suffix.lower() == ".md":
            url = f"/paper/{quote(rel, safe='/')}"
        else:
            url = f"/file/{quote(rel, safe='/')}"
        if fragment:
            url += "#" + quote(fragment, safe="-_.~")
        return f"{bang}[{label}]({url})"

    return "\n".join(LINK_RE.sub(repl, line) for line in raw.splitlines())


def protect_math(raw: str) -> tuple[str, dict[str, str]]:
    replacements: dict[str, str] = {}

    def token() -> str:
        return f"@@PAPERKBMATH{len(replacements)}@@"

    def store(fragment: str, *, display: bool) -> str:
        placeholder = token()
        escaped = html.escape(fragment, quote=False)
        if display:
            replacements[placeholder] = escaped
            return f'\n\n<div class="math-display">{placeholder}</div>\n\n'
        replacements[placeholder] = f'<span class="math-inline">{escaped}</span>'
        return placeholder

    def display_repl(match: re.Match[str]) -> str:
        return store(match.group(0), display=True)

    protected = DISPLAY_DOLLAR_RE.sub(display_repl, raw)
    protected = DISPLAY_BRACKET_RE.sub(display_repl, protected)
    protected = INLINE_PAREN_RE.sub(lambda match: store(match.group(0), display=False), protected)
    protected = INLINE_DOLLAR_RE.sub(lambda match: store(match.group(0), display=False), protected)
    return protected, replacements


def restore_math(rendered: str, replacements: dict[str, str]) -> str:
    for placeholder, fragment in replacements.items():
        rendered = rendered.replace(placeholder, fragment)
    return rendered


def render_markdown(raw: str, current_file: Path, source_root: Path) -> tuple[str, str]:
    rewritten = rewrite_local_links(raw, current_file, source_root)
    protected, math_replacements = protect_math(rewritten)
    markdown = Markdown(
        extensions=[
            "extra",
            "toc",
            "footnotes",
            "sane_lists",
            "tables",
            "attr_list",
        ],
        extension_configs={
            "toc": {
                "toc_depth": "2-4",
            }
        },
        output_format="html5",
    )
    body_html = restore_math(markdown.convert(protected), math_replacements)
    toc_html = restore_math(getattr(markdown, "toc", "") or "", math_replacements)
    return body_html, toc_html
