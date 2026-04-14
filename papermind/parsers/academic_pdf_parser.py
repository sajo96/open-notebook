import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

import crossref_commons.retrieval
import fitz  # PyMuPDF
import pytesseract
import scholarly
from PIL import Image
from langchain_core.messages import HumanMessage, SystemMessage

from open_notebook.ai.provision import provision_langchain_model

logger = logging.getLogger(__name__)


SECTION_PATTERN = re.compile(
    r"^(abstract|introduction|background|methods?|materials and methods|results?|discussion|conclusion|references)\s*$",
    re.IGNORECASE,
)


@dataclass
class ParsedPaper:
    title: str
    authors: list[str]
    abstract: str | None
    doi: str | None
    year: int | None
    keywords: list[str]
    sections: dict[str, str]
    raw_references: list[str]
    raw_text: str
    is_ocr: bool


def find_doi(text: str) -> str | None:
    match = re.search(r"10\.\d{4,}/[^\s]+", text)
    if match:
        return match.group(0).rstrip(".")
    return None


def _clean_response_text(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def _normalize_section_name(name: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return normalized or "section"


def _is_bold_span(span: dict[str, Any]) -> bool:
    font_name = str(span.get("font", "")).lower()
    flags = int(span.get("flags", 0) or 0)
    return "bold" in font_name or bool(flags & 16) or bool(flags & 2)


def _extract_line_records(page: fitz.Page) -> list[tuple[str, bool]]:
    try:
        page_dict = page.get_text("dict")
    except Exception:
        return []

    lines: list[tuple[str, bool]] = []
    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = "".join(span.get("text", "") for span in spans).strip()
            if not text:
                continue
            is_bold = any(_is_bold_span(span) for span in spans)
            lines.append((text, is_bold))
    return lines


def _extract_page_text(page: fitz.Page) -> str:
    structured_lines = _extract_line_records(page)
    if not structured_lines:
        return page.get_text("text")

    output_lines: list[str] = []
    for text, is_bold in structured_lines:
        cleaned = text.strip()
        if not cleaned:
            continue
        if SECTION_PATTERN.match(cleaned) or (cleaned.isupper() and 3 < len(cleaned) < 80) or (is_bold and len(cleaned) < 120):
            output_lines.append("")
            output_lines.append(cleaned)
            output_lines.append("")
        else:
            output_lines.append(cleaned)
    return "\n".join(output_lines)


def _extract_references(text: str) -> list[str]:
    lines = [line.rstrip() for line in text.splitlines()]
    reference_start = None
    for index, line in enumerate(lines):
        if re.match(r"^references?$", line.strip(), re.IGNORECASE):
            reference_start = index + 1
            break

    if reference_start is None:
        for index, line in enumerate(lines):
            if re.match(r"^bibliography$", line.strip(), re.IGNORECASE):
                reference_start = index + 1
                break

    if reference_start is None:
        return []

    reference_lines = [line.strip() for line in lines[reference_start:] if line.strip()]
    if not reference_lines:
        return []

    references: list[str] = []
    current: list[str] = []
    for line in reference_lines:
        if re.match(r"^\[?\d+\]?\.?\s+", line) and current:
            references.append(" ".join(current).strip())
            current = [line]
        elif line and current and (line[:1].isupper() or line.startswith("-")):
            references.append(" ".join(current).strip())
            current = [line]
        else:
            current.append(line)

    if current:
        references.append(" ".join(current).strip())

    return [reference for reference in references if len(reference) > 20]


def _title_from_raw_text(raw_text: str) -> str:
    candidate_lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if not candidate_lines:
        return "Unknown Title"
    return " ".join(candidate_lines[:3])[:250]


def _scholarly_lookup(title: str) -> dict[str, Any]:
    try:
        try:
            pub = scholarly.scholarly.search_single_pub(title, filled=True)
            if pub:
                return pub
        except Exception:
            pass

        search_query = scholarly.scholarly.search_pubs(title)
        pub = next(search_query, None)
        return pub or {}
    except Exception as exc:
        logger.warning(f"Scholarly lookup failed for {title}: {exc}")
        return {}


def _apply_scholarly_metadata(
    title: str,
    authors: list[str],
    abstract: str | None,
    year: int | None,
    scholarly_pub: dict[str, Any],
) -> tuple[str, list[str], str | None, int | None]:
    if not scholarly_pub:
        return title, authors, abstract, year

    bib = scholarly_pub.get("bib", {}) if isinstance(scholarly_pub, dict) else {}
    title = title if title != "Unknown Title" else bib.get("title", title)

    if not authors:
        raw_authors = bib.get("author", [])
        if isinstance(raw_authors, str):
            authors = [part.strip() for part in raw_authors.split(" and ") if part.strip()]
        elif isinstance(raw_authors, list):
            authors = [str(author).strip() for author in raw_authors if str(author).strip()]

    if abstract is None:
        abstract = bib.get("abstract") or abstract

    if year is None:
        year_value = bib.get("pub_year") or bib.get("year")
        try:
            year = int(year_value) if year_value and str(year_value).isdigit() else year
        except Exception:
            pass

    return title, authors, abstract, year


def _sections_from_boundaries(raw_text: str, boundaries: dict[str, int]) -> dict[str, str]:
    if not boundaries:
        return {"full_text": raw_text}

    ordered = sorted(
        ((name, index) for name, index in boundaries.items() if isinstance(index, int) and index >= 0),
        key=lambda item: item[1],
    )
    if not ordered:
        return {"full_text": raw_text}

    sections: dict[str, str] = {}
    for position, (name, start_index) in enumerate(ordered):
        end_index = ordered[position + 1][1] if position + 1 < len(ordered) else len(raw_text)
        section_text = raw_text[start_index:end_index].strip()
        if section_text:
            sections[_normalize_section_name(name)] = section_text

    return sections if sections else {"full_text": raw_text}


async def _detect_sections_with_llm(raw_text: str) -> dict[str, int]:
    prompt_text = (
        "Identify the section boundaries in this academic paper text. "
        "Return JSON only in the form {\"section_name\": start_character_index}. "
        "Use the first occurrence of each section heading. Text:\n\n"
        f"{raw_text[:3000]}"
    )
    llm = await provision_langchain_model(prompt_text, None, "transformation", max_tokens=800)
    response = await llm.ainvoke([SystemMessage(content="Return valid JSON only."), HumanMessage(content=prompt_text)])
    response_text = getattr(response, "content", str(response))
    cleaned = _clean_response_text(response_text)
    parsed = json.loads(cleaned)
    if isinstance(parsed, dict):
        normalized: dict[str, int] = {}
        for key, value in parsed.items():
            if isinstance(value, int):
                normalized[str(key)] = value
            elif isinstance(value, str) and value.isdigit():
                normalized[str(key)] = int(value)
        return normalized
    return {}


class AcademicPDFParser:
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.is_ocr = False

    def parse(self) -> ParsedPaper:
        raw_text = ""

        try:
            doc = fitz.open(self.file_path)
            for page in doc:
                page_text = _extract_page_text(page)
                if len(page_text.strip()) < 200 and os.environ.get("PAPERMIND_ENABLE_OCR", "true").lower() == "true":
                    self.is_ocr = True
                    pix = page.get_pixmap()
                    if pix.alpha:
                        img = Image.frombytes("RGBA", [pix.width, pix.height], pix.samples)
                    else:
                        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    page_text = pytesseract.image_to_string(img)
                raw_text += page_text + "\n"
        except Exception as e:
            logger.error(f"Failed to extract text from PDF {self.file_path}: {e}")

        doi = find_doi(raw_text)
        title: str = "Unknown Title"
        authors: list[str] = []
        year: int | None = None
        abstract: str | None = None

        if doi:
            try:
                pub = crossref_commons.retrieval.get_publication_as_json(doi)
                if pub:
                    title = (pub.get("title") or [title])[0]
                    authors_list = pub.get("author", [])
                    authors = [f"{a.get('given', '')} {a.get('family', '')}".strip() for a in authors_list if isinstance(a, dict)]
                    published = pub.get("published-print") or pub.get("published-online")
                    if isinstance(published, dict):
                        date_parts = published.get("date-parts", [])
                        if date_parts and date_parts[0] and len(date_parts[0]) > 0:
                            year = date_parts[0][0]
                    abstract = pub.get("abstract", None)
            except Exception as e:
                logger.error(f"Crossref lookup failed for DOI {doi}: {e}")

        if title == "Unknown Title" or not authors or year is None or abstract is None:
            fallback_title = title if title != "Unknown Title" else _title_from_raw_text(raw_text)
            scholarly_pub = _scholarly_lookup(fallback_title) if fallback_title else {}
            title, authors, abstract, year = _apply_scholarly_metadata(
                title,
                authors,
                abstract,
                year,
                scholarly_pub,
            )

        sections = self._extract_sections(raw_text)
        raw_references = _extract_references(raw_text)

        return ParsedPaper(
            title=title or "Unknown Title",
            authors=authors,
            abstract=abstract,
            doi=doi,
            year=year,
            keywords=[],
            sections=sections,
            raw_references=raw_references,
            raw_text=raw_text,
            is_ocr=self.is_ocr,
        )

    def _extract_sections(self, text: str) -> dict[str, str]:
        sections: dict[str, str] = {}
        current_section = "frontmatter"
        current_text: list[str] = []

        for line in text.split("\n"):
            line_clean = line.strip()
            if not line_clean:
                current_text.append(line)
                continue

            if SECTION_PATTERN.match(line_clean) or (line_clean.isupper() and 3 < len(line_clean) < 80):
                if current_text:
                    sections[_normalize_section_name(current_section)] = "\n".join(current_text).strip()
                current_section = line_clean
                current_text = []
            else:
                current_text.append(line)

        if current_text:
            sections[_normalize_section_name(current_section)] = "\n".join(current_text).strip()

        sections = {key: value for key, value in sections.items() if value}
        if len(sections) >= 3:
            return sections

        try:
            boundaries = asyncio.run(_detect_sections_with_llm(text))
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                boundaries = loop.run_until_complete(_detect_sections_with_llm(text))
            except Exception as exc:
                logger.warning(f"LLM section detection failed for {self.file_path}: {exc}")
                boundaries = {}
            finally:
                loop.close()
        except Exception as exc:
            logger.warning(f"LLM section detection failed for {self.file_path}: {exc}")
            boundaries = {}

        llm_sections = _sections_from_boundaries(text, boundaries)
        if len(llm_sections) >= 1 and llm_sections != {"full_text": text}:
            return llm_sections

        return {"full_text": text}