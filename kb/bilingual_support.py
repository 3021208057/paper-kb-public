from __future__ import annotations

import hashlib
import json
import os
import re
from html import unescape
from pathlib import Path
from typing import Any

import httpx


CACHE_FILENAME = "paper_bilingual_cache.json"
DEFAULT_HF_MODEL = os.environ.get("PAPERKB_TRANSLATION_HF_MODEL", "Helsinki-NLP/opus-mt-en-zh")
DEFAULT_OPENAI_MODEL = os.environ.get("PAPERKB_TRANSLATION_MODEL", os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"))
DEFAULT_PROVIDER = os.environ.get("PAPERKB_TRANSLATION_PROVIDER", "auto").strip().lower() or "auto"
DEFAULT_BATCH_SIZE = max(1, int(os.environ.get("PAPERKB_TRANSLATION_BATCH_SIZE", "8")))
DEFAULT_CHUNK_SIZE = min(360, max(180, int(os.environ.get("PAPERKB_TRANSLATION_CHUNK_SIZE", "320"))))
TRANSLATION_CACHE_VERSION = 3
MYMEMORY_URL = "https://api.mymemory.translated.net/get"

WHITESPACE_RE = re.compile(r"\s+")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+")


def compact_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return WHITESPACE_RE.sub(" ", value).strip()
    return WHITESPACE_RE.sub(" ", str(value)).strip()


def bilingual_label(english: str, chinese: str, separator: str = " / ") -> str:
    english = compact_text(english)
    chinese = compact_text(chinese)
    if english and chinese and english != chinese:
        return f"{english}{separator}{chinese}"
    return english or chinese


def record_title(record: dict[str, Any]) -> str:
    return bilingual_label(str(record.get("title", "")), str(record.get("title_zh", "")))


def record_preview(record: dict[str, Any]) -> tuple[str, str]:
    english = compact_text(record.get("abstract_snippet", ""))
    chinese = compact_text(record.get("abstract_zh_snippet", ""))
    if not english:
        english = compact_text(record.get("abstract", ""))
    return english, chinese


def cache_path(output_dir: Path) -> Path:
    return output_dir / CACHE_FILENAME


def load_cache(path: Path) -> tuple[dict[str, str], dict[str, Any]]:
    if not path.exists():
        return {}, {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}, {}
    if isinstance(payload, dict):
        entries = payload.get("entries", {})
        if isinstance(entries, dict):
            cache = {
                str(key): compact_text(value)
                for key, value in entries.items()
                if compact_text(value)
            }
            meta = {str(key): value for key, value in payload.items() if key != "entries"}
            return cache, meta
    return {}, {}


def save_cache(path: Path, cache: dict[str, str], *, provider: str) -> None:
    payload = {
        "version": TRANSLATION_CACHE_VERSION,
        "provider": provider,
        "entries": cache,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def cache_key(provider: str, kind: str, text: str) -> str:
    digest = hashlib.sha256(compact_text(text).encode("utf-8")).hexdigest()
    return f"v{TRANSLATION_CACHE_VERSION}:{provider}:{kind}:{digest}"


def split_for_translation(text: str, limit: int = DEFAULT_CHUNK_SIZE) -> list[str]:
    text = compact_text(text)
    if not text:
        return []
    chunks: list[str] = []
    current = ""
    for part in SENTENCE_SPLIT_RE.split(text):
        part = compact_text(part)
        if not part:
            continue
        if len(part) > limit:
            if current:
                chunks.append(current)
                current = ""
            start = 0
            while start < len(part):
                end = min(len(part), start + limit)
                if end < len(part):
                    space = part.rfind(" ", start, end)
                    if space > start + 40:
                        end = space
                piece = compact_text(part[start:end])
                if piece:
                    chunks.append(piece)
                start = end
            continue
        if not current:
            current = part
            continue
        if len(current) + 1 + len(part) <= limit:
            current = f"{current} {part}"
            continue
        chunks.append(current)
        current = part
    if current:
        chunks.append(current)
    return chunks or [text]


class TranslationEngine:
    def __init__(self, provider: str = DEFAULT_PROVIDER, model_name: str | None = None) -> None:
        self.requested_provider = (provider or DEFAULT_PROVIDER).strip().lower() or "auto"
        self.model_name = compact_text(model_name) or DEFAULT_HF_MODEL
        self._resolved_provider: str | None = None
        self._hf_tokenizer: Any = None
        self._hf_model: Any = None
        self._hf_device: Any = None
        self._openai_client: Any = None
        self._argos_translation: Any = None

    @property
    def provider_name(self) -> str:
        if self._resolved_provider is None:
            self._resolved_provider = self._resolve_provider()
        return self._resolved_provider

    def _resolve_provider(self) -> str:
        if self.requested_provider in {"none", "off", "skip"}:
            return "none"
        if self.requested_provider == "openai":
            return "openai"
        if self.requested_provider in {"argos", "argostranslate"}:
            return "argos" if self._has_argos_package() else "mymemory"
        if self.requested_provider == "hf":
            return "hf"
        if self._has_argos_package():
            return "argos"
        if os.environ.get("OPENAI_API_KEY"):
            return "openai"
        return "mymemory"

    def _has_argos_package(self) -> bool:
        try:
            from argostranslate import package as argos_package
        except Exception:
            return False
        try:
            for pkg in argos_package.get_installed_packages():
                if getattr(pkg, "from_code", "") == "en" and getattr(pkg, "to_code", "") == "zh":
                    return True
        except Exception:
            return False
        return False

    def _translate_openai(self, texts: list[str]) -> list[str]:
        from openai import OpenAI

        if self._openai_client is None:
            self._openai_client = OpenAI()

        results: list[str] = []
        for text in texts:
            prompt = (
                "Translate the following academic paper metadata into Simplified Chinese. "
                "Keep technical terms accurate, preserve names and formulas, and return only the translation."
            )
            response = self._openai_client.chat.completions.create(
                model=DEFAULT_OPENAI_MODEL,
                temperature=0,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": text},
                ],
            )
            translated = ""
            if response.choices:
                translated = compact_text(response.choices[0].message.content or "")
            results.append(translated)
        return results

    def _load_hf(self) -> None:
        if self._hf_tokenizer is not None and self._hf_model is not None:
            return
        try:
            import torch
            from transformers import MarianMTModel, MarianTokenizer
        except Exception as exc:  # pragma: no cover - environment dependent
            raise RuntimeError("transformers translation backend is unavailable") from exc

        tokenizer = MarianTokenizer.from_pretrained(self.model_name)
        model = MarianMTModel.from_pretrained(self.model_name)
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model.to(device)
        model.eval()
        self._hf_tokenizer = tokenizer
        self._hf_model = model
        self._hf_device = device

    def _translate_hf(self, texts: list[str]) -> list[str]:
        import torch

        self._load_hf()
        tokenizer = self._hf_tokenizer
        model = self._hf_model
        device = self._hf_device
        if tokenizer is None or model is None or device is None:
            raise RuntimeError("translation backend did not initialize")

        results: list[str] = []
        batch_size = DEFAULT_BATCH_SIZE
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            inputs = tokenizer(batch, return_tensors="pt", padding=True, truncation=True, max_length=512)
            inputs = {key: value.to(device) for key, value in inputs.items()}
            with torch.inference_mode():
                outputs = model.generate(**inputs, max_new_tokens=256)
            results.extend(tokenizer.batch_decode(outputs, skip_special_tokens=True))
        return [compact_text(item) for item in results]

    def _load_argos(self) -> Any:
        if self._argos_translation is not None:
            return self._argos_translation

        import re

        from argostranslate import translate as argos_translate

        class SimpleSentenceSplitter:
            def split_sentences(self, text: str) -> list[str]:
                chunks = [piece.strip() for piece in re.split(r"(?<=[.!?。！？；;])\s+|\n+", text.strip()) if piece.strip()]
                return chunks or [text.strip()]

        translation = argos_translate.get_translation_from_codes("en", "zh")
        if hasattr(translation, "underlying") and getattr(translation, "underlying", None) is not None:
            try:
                translation.underlying.sentencizer = SimpleSentenceSplitter()
            except Exception:
                pass
        self._argos_translation = translation
        return translation

    def _split_title_chunks(self, text: str) -> list[str]:
        title = compact_text(text)
        if not title:
            return []
        lowered = title.lower()
        connectors = [
            " for ",
            " using ",
            " based on ",
            " with ",
            " incorporating ",
            " of ",
            " via ",
        ]
        for connector in connectors:
            index = lowered.rfind(connector)
            if index <= 0:
                continue
            left = compact_text(title[:index])
            right = compact_text(title[index:])
            if len(left.split()) >= 4 and len(right.split()) >= 3:
                return [left, right]
        words = title.split()
        if len(words) > 12:
            midpoint = max(4, len(words) // 2)
            return [" ".join(words[:midpoint]), " ".join(words[midpoint:])]
        return [title]

    def _translate_argos(self, texts: list[str]) -> list[str]:
        translation = self._load_argos()
        results: list[str] = []
        for text in texts:
            try:
                candidate = compact_text(text)
                if candidate and len(candidate) < 220 and not re.search(r"[.!?。！？]", candidate):
                    parts = self._split_title_chunks(candidate)
                    translated_parts = [compact_text(translation.translate(part)) for part in parts if part]
                    translated = "。".join(part for part in translated_parts if part)
                else:
                    translated = compact_text(translation.translate(text))
            except Exception:
                translated = ""
            results.append(translated)
        return results

    def _translate_mymemory(self, texts: list[str]) -> list[str]:
        results: list[str] = []
        headers = {"User-Agent": "Codex paper KB bilingual translator"}
        for text in texts:
            chunks = split_for_translation(text)
            translated_chunks: list[str] = []
            for chunk in chunks:
                if not chunk:
                    continue
                translated = ""
                try:
                    response = httpx.get(
                        MYMEMORY_URL,
                        params={"q": chunk, "langpair": "en|zh-CN"},
                        headers=headers,
                        timeout=30,
                    )
                    response.raise_for_status()
                    payload = response.json()
                    if isinstance(payload, dict):
                        response_data = payload.get("responseData", {})
                        if isinstance(response_data, dict):
                            translated = compact_text(unescape(str(response_data.get("translatedText", ""))))
                except Exception:
                    translated = ""
                translated_chunks.append(translated)
            results.append(compact_text(" ".join(part for part in translated_chunks if part)))
        return results

    def translate_many(self, texts: list[str]) -> list[str]:
        if not texts:
            return []
        provider = self.provider_name
        if provider == "none":
            return ["" for _ in texts]
        if provider == "openai":
            return self._translate_openai(texts)
        if provider == "argos":
            return self._translate_argos(texts)
        if provider == "mymemory":
            return self._translate_mymemory(texts)
        return self._translate_hf(texts)


def enrich_bilingual_records(
    records: list[dict[str, Any]],
    output_dir: Path,
    *,
    provider: str = DEFAULT_PROVIDER,
    model_name: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, str], str, list[str]]:
    engine = TranslationEngine(provider=provider, model_name=model_name)
    cache_file = cache_path(output_dir)
    cache, meta = load_cache(cache_file)
    resolved_provider = engine.provider_name
    if resolved_provider == "none":
        for record in records:
            record["title_zh"] = ""
            record["abstract_zh"] = ""
            record["abstract_zh_snippet"] = ""
        return records, cache, resolved_provider, []

    pending: list[tuple[str, str, dict[str, Any], str]] = []
    for record in records:
        title = compact_text(record.get("title", ""))
        abstract = compact_text(record.get("abstract", ""))
        title_key = cache_key(resolved_provider, "title", title) if title else ""
        abstract_key = cache_key(resolved_provider, "abstract", abstract) if abstract else ""
        if title:
            if title_key in cache:
                record["title_zh"] = cache[title_key]
            else:
                pending.append((title_key, "title", record, title))
        else:
            record["title_zh"] = ""
        if abstract:
            if abstract_key in cache:
                record["abstract_zh"] = cache[abstract_key]
            else:
                pending.append((abstract_key, "abstract", record, abstract))
        else:
            record["abstract_zh"] = ""
        record["abstract_zh_snippet"] = compact_text(record.get("abstract_zh", ""))[:260]

    warnings: list[str] = []
    if pending:
        texts = [text for _, _, _, text in pending]
        try:
            translations = engine.translate_many(texts)
        except Exception as exc:  # pragma: no cover - depends on model/network
            warnings.append(f"Translation disabled: {exc}")
            translations = ["" for _ in texts]
        if pending and not any(translations):
            warnings.append("Translation provider returned empty results.")
        for (key, kind, record, _), translated in zip(pending, translations):
            translated = compact_text(translated)
            if translated:
                cache[key] = translated
                record[f"{kind}_zh"] = translated
                if kind == "abstract":
                    record["abstract_zh_snippet"] = translated[:260]
            else:
                record.setdefault(f"{kind}_zh", "")
        for record in records:
            if "abstract_zh" in record and not record.get("abstract_zh_snippet"):
                record["abstract_zh_snippet"] = compact_text(record.get("abstract_zh", ""))[:260]
        save_cache(cache_file, cache, provider=resolved_provider)
    elif meta.get("provider") != resolved_provider:
        save_cache(cache_file, cache, provider=resolved_provider)
    return records, cache, resolved_provider, warnings
