import json
import os
import re
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from open_notebook.ai.provision import provision_langchain_model
from open_notebook.database.repository import ensure_record_id, repo_query
from papermind.parsers.academic_pdf_parser import ParsedPaper


class AutoTagger:
    """Generate concept tags via spaCy NER plus an LLM topic pass."""

    def __init__(self) -> None:
        self._spacy_nlp = None
        self._spacy_attempted = False

    def _canonical_concept_id(self, value: str) -> Optional[str]:
        cleaned = re.sub(r"[^a-z0-9\s]+", " ", (value or "").strip().lower())
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if len(cleaned) < 3:
            return None
        return f"concept:{cleaned.replace(' ', '_')}"

    def _load_spacy(self):
        if self._spacy_attempted:
            return self._spacy_nlp

        self._spacy_attempted = True
        model_name = os.getenv("PAPERMIND_SPACY_MODEL", "en_core_web_sm")
        try:
            import spacy  # type: ignore

            self._spacy_nlp = spacy.load(model_name)
            logger.info(f"Loaded spaCy model for auto-tagging: {model_name}")
        except Exception as exc:
            logger.warning(
                "spaCy model unavailable for auto-tagging; "
                f"continuing with LLM-only tags ({exc})"
            )
            self._spacy_nlp = None

        return self._spacy_nlp

    def _extract_spacy_tags(self, parsed: ParsedPaper) -> list[str]:
        nlp = self._load_spacy()
        if not nlp:
            return []

        text = "\n".join(
            [
                parsed.title or "",
                parsed.abstract or "",
                "\n".join(parsed.sections.values())[:12000] if isinstance(parsed.sections, dict) else "",
            ]
        )

        if not text.strip():
            return []

        doc = nlp(text)
        keep_labels = {
            "ORG",
            "PRODUCT",
            "EVENT",
            "WORK_OF_ART",
            "LAW",
            "LANGUAGE",
            "FAC",
            "GPE",
            "NORP",
        }

        tags: list[str] = []
        seen: set[str] = set()
        for ent in doc.ents:
            if ent.label_ not in keep_labels:
                continue
            label = ent.text.strip()
            key = label.lower()
            if len(label) < 3 or key in seen:
                continue
            seen.add(key)
            tags.append(label)
            if len(tags) >= 20:
                break

        return tags

    async def _extract_llm_tags(self, parsed: ParsedPaper) -> list[str]:
        excerpt = "\n\n".join(
            [
                f"Title: {parsed.title or ''}",
                f"Abstract: {parsed.abstract or ''}",
                "Sections:\n" + (
                    "\n".join(
                        f"{k}: {str(v)[:600]}" for k, v in (parsed.sections or {}).items()
                    )[:5000]
                    if isinstance(parsed.sections, dict)
                    else ""
                ),
            ]
        ).strip()

        if not excerpt:
            return []

        prompt = (
            "Extract up to 12 concise topic tags for this academic paper. "
            "Return strict JSON only in this format: {\"tags\": [\"tag1\", \"tag2\"]}. "
            "Prefer technical concepts and methods, avoid generic words."
        )

        try:
            llm = await provision_langchain_model(
                excerpt,
                model_id=None,
                default_type="chat",
                temperature=0.1,
                max_tokens=300,
            )
            response = await llm.ainvoke(
                [
                    SystemMessage(content="Return valid JSON only."),
                    HumanMessage(content=f"{prompt}\n\n{excerpt}"),
                ]
            )
            raw = getattr(response, "content", str(response)).strip()
            raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
            raw = re.sub(r"\s*```$", "", raw)
            payload = json.loads(raw)
            tags = payload.get("tags", []) if isinstance(payload, dict) else []
            if not isinstance(tags, list):
                return []
            return [str(tag).strip() for tag in tags if str(tag).strip()][:12]
        except Exception as exc:
            logger.warning(f"LLM topic extraction failed during auto-tagging: {exc}")
            return []

    async def tag_paper(
        self,
        paper_id: str,
        parsed: ParsedPaper,
        note_concepts: Optional[list[str]] = None,
    ) -> list[str]:
        spacy_tags = self._extract_spacy_tags(parsed)
        llm_tags = await self._extract_llm_tags(parsed)
        note_tags = list(note_concepts or [])
        keyword_tags = list(parsed.keywords or [])

        candidate_labels = [*keyword_tags, *note_tags, *spacy_tags, *llm_tags]
        dedup: dict[str, str] = {}
        for raw in candidate_labels:
            label = str(raw or "").strip()
            concept_id = self._canonical_concept_id(label)
            if not concept_id:
                continue
            dedup[concept_id] = label

        labels: list[str] = []
        for concept_id, label in dedup.items():
            await repo_query(
                "UPDATE $id SET label = $label, created_at = time::now()",
                {
                    "id": ensure_record_id(concept_id),
                    "label": label,
                },
            )
            await repo_query(
                "RELATE $in -> tagged_with -> $out",
                {
                    "in": ensure_record_id(paper_id),
                    "out": ensure_record_id(concept_id),
                },
            )
            labels.append(label)

        return labels
