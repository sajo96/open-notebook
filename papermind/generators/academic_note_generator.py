import yaml
import json
import re
from pathlib import Path
from loguru import logger
from dataclasses import dataclass
from typing import List, Optional, Any, Dict
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from open_notebook.ai.provision import provision_langchain_model
from open_notebook.database.repository import repo_query, ensure_record_id
from open_notebook.domain.notebook import Note
from papermind.models import AcademicPaper, Concept
from papermind.utils import _rows_from_query_result

@dataclass
class GeneratedNote:
    one_line_summary: str
    key_findings: List[str]
    methodology: str
    limitations: List[str]
    concepts: List[str]
    note_id: Optional[str] = None

class AcademicNoteGenerator:
    """
    Uses the existing Open Notebook LangChain integration.
    Reads prompts from prompts/academic_note.yaml.
    """
    def __init__(self, prompts_path: str = "prompts/academic_note.yaml"):
        # Resolve path relative to project root
        base_dir = Path(__file__).parent.parent.parent
        self.prompts_path = base_dir / prompts_path
        self._load_prompts()

    def _load_prompts(self):
        with open(self.prompts_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self.system_prompt = data.get("system", "")
        self.sections = data.get("sections", {})

    @staticmethod
    def _normalize_key(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")

    @staticmethod
    def _ensure_str_list(value: Any, fallback: Optional[List[str]] = None, max_items: int = 8) -> List[str]:
        items = []
        if isinstance(value, list):
            items = [str(item).strip() for item in value if str(item).strip()]
        elif isinstance(value, dict):
            for v in value.values():
                if isinstance(v, list):
                    items.extend([str(item).strip() for item in v if str(item).strip()])
        elif isinstance(value, str) and value.strip():
            items = [value.strip()]
            
        if items:
            return items[:max_items]
        return list(fallback or [])[:max_items]

    async def _resolve_notebook_id_for_source(self, source_id: str) -> str:
        try:
            relation_rows_raw = await repo_query(
                "SELECT VALUE out FROM reference WHERE in = $source_id LIMIT 1",
                {"source_id": ensure_record_id(source_id)},
            )
            # SELECT VALUE returns a flat list of scalars, not dicts
            if relation_rows_raw and isinstance(relation_rows_raw[0], str):
                candidate = relation_rows_raw[0]
                if candidate:
                    return str(candidate)
            relation_rows = _rows_from_query_result(relation_rows_raw)
            if relation_rows:
                candidate = relation_rows[0]
                if candidate:
                    return str(candidate)

            source_rows_raw = await repo_query(
                "SELECT notebook_id FROM source WHERE id = $source_id LIMIT 1",
                {"source_id": ensure_record_id(source_id)},
            )
            source_rows = _rows_from_query_result(source_rows_raw)
            if source_rows and isinstance(source_rows[0], dict):
                candidate = source_rows[0].get("notebook_id")
                if candidate:
                    return str(candidate)
        except Exception:
            return ""
        return ""

    def _section_text(self, paper: AcademicPaper, *aliases: str, limit: int = 4000) -> str:
        sections = paper.sections if isinstance(paper.sections, dict) else {}
        if not sections:
            return ""

        normalized = {
            self._normalize_key(str(k)): str(v or "").strip()
            for k, v in sections.items()
            if str(v or "").strip()
        }

        for alias in aliases:
            key = self._normalize_key(alias)
            value = normalized.get(key, "")
            if value:
                return value[:limit]

        # Fallback to full text sections when explicit headings are unavailable.
        for key in ("full_text", "summary", "frontmatter"):
            value = normalized.get(key, "")
            if value:
                return value[:limit]
        return ""

    @staticmethod
    def _clean_llm_text(text: str) -> str:
        cleaned = (text or "").strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        return cleaned.strip()

    @staticmethod
    def _is_reasoning_model(llm: Any) -> bool:
        model_name = str(
            getattr(llm, "model_name", "")
            or getattr(llm, "model", "")
            or ""
        ).lower()
        return bool(re.match(r"^(o1|o3|o4)(-|$)", model_name))

    @staticmethod
    def _json_array_guard_instruction() -> str:
        return (
            "Output ONLY a valid raw JSON array. "
            "No markdown, no explanation, no preamble, no reasoning text. "
            "Your entire response must start with [ and end with ]. "
            "Do not write anything before or after the JSON."
        )

    @staticmethod
    def _is_placeholder_text(text: str) -> bool:
        raw = (text or "").strip().lower()
        if not raw:
            return True
        if raw in {"n/a", "none", "not available"}:
            return True
        return (
            "unavailable" in raw
            or "not explicitly stated" in raw
            or "details unavailable" in raw
        )

    @staticmethod
    def _split_sentences(text: str) -> List[str]:
        parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
        return [p.strip() for p in parts if p and len(p.strip()) > 20]

    def _fallback_output(self, section_name: str, text: str, title: str) -> Any:
        text = (text or "").strip()
        sentences = self._split_sentences(text)

        if section_name == "one_line_summary":
            if sentences:
                return " ".join(sentences[0].split()[:30])
            return title or "Summary unavailable."

        if section_name == "key_findings":
            if sentences:
                return sentences[: min(5, len(sentences))]
            return ["No key findings available."]

        if section_name == "methodology":
            method_hits = [
                s for s in sentences
                if re.search(r"\b(method|dataset|experiment|evaluate|approach|model)\b", s, re.IGNORECASE)
            ]
            if method_hits:
                return " ".join(method_hits[:2])
            if sentences:
                return " ".join(sentences[:2])
            return "Methodology details unavailable."

        if section_name == "limitations":
            limitation_hits = [
                s for s in sentences
                if re.search(r"\b(limit|future work|constraint|weakness)\b", s, re.IGNORECASE)
            ]
            if limitation_hits:
                return limitation_hits[:3]
            return ["Limitations not explicitly stated in source text."]

        if section_name == "concepts":
            tokens = re.findall(r"[A-Za-z][A-Za-z0-9\-]{3,}", text)
            concepts: List[str] = []
            seen = set()
            stop = {
                "this", "that", "with", "from", "have", "were", "their", "paper", "study",
                "using", "results", "method", "methods", "introduction", "conclusion",
            }
            for tok in tokens:
                key = tok.lower()
                if key in stop or key in seen:
                    continue
                seen.add(key)
                concepts.append(tok)
                if len(concepts) >= 8:
                    break
            return concepts

        return ""

    def _paper_fallback_text(self, paper: AcademicPaper, limit: int = 4000) -> str:
        sections = paper.sections if isinstance(paper.sections, dict) else {}
        joined_sections = "\n".join(
            str(v or "").strip() for v in sections.values() if str(v or "").strip()
        )
        candidate = "\n".join([paper.abstract or "", joined_sections]).strip()
        return candidate[:limit]

    def _derive_methodology_from_text(self, text: str) -> str:
        sentences = self._split_sentences(text)
        method_hits = [
            s for s in sentences
            if re.search(
                r"\b(method|methodology|dataset|experiment|evaluate|evaluation|approach|model|protocol|simulation)\b",
                s,
                re.IGNORECASE,
            )
        ]
        if method_hits:
            return " ".join(method_hits[:2]).strip()
        return ""

    def _derive_limitations_from_text(self, text: str) -> List[str]:
        sentences = self._split_sentences(text)
        limitation_hits = [
            s for s in sentences
            if re.search(
                r"\b(limit|limitations|future work|constraint|weakness|caveat|shortcoming|however|although|may|might|could|tradeoff|error|uncertain)\b",
                s,
                re.IGNORECASE,
            )
        ]
        if limitation_hits:
            return limitation_hits[:5]

        # Fallback: return one long sentence from the tail where limitations are often discussed.
        tail = sentences[-20:]
        for sentence in tail:
            cleaned = sentence.strip()
            if len(cleaned) > 80:
                return [cleaned]
        return []

    async def _call_llm_for_section(
        self,
        section_name: str,
        paper: AcademicPaper,
        section_config: dict,
        supplemental_text: str,
    ) -> Any:
        system_prompt = self.system_prompt
        if section_name in {"key_findings", "limitations", "concepts"}:
            system_prompt = (
                f"{system_prompt}\n\nJSON ARRAY MODE:\n"
                f"{self._json_array_guard_instruction()}"
            )

        prompt_template = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("user", section_config["prompt"])
        ])

        # Prepare variables based on the section
        variables = {}
        target_content = ""
        if section_name == "one_line_summary":
            intro = self._section_text(paper, "introduction", "background", limit=2000)
            abstract = (paper.abstract or self._section_text(paper, "abstract", limit=2000)).strip()
            target_content = intro + abstract
            variables = {
                "abstract": abstract,
                "introduction_excerpt": intro
            }
        elif section_name == "key_findings":
            results = self._section_text(paper, "results", limit=3000)
            conclusion = self._section_text(paper, "conclusion", limit=1500)
            target_content = results + conclusion
            variables = {
                "results_and_conclusion": target_content[:4000]
            }
        elif section_name == "methodology":
            methods = self._section_text(
                paper,
                "methods",
                "methodology",
                "materials and methods",
                limit=4000,
            )
            target_content = methods
            variables = {
                "methods": target_content[:4000]
            }
        elif section_name == "limitations":
            discussion = self._section_text(paper, "discussion", limit=3000)
            conclusion = self._section_text(paper, "conclusion", limit=1500)
            target_content = discussion + conclusion
            variables = {
                "discussion_and_conclusion": target_content[:4000]
            }
        elif section_name == "concepts":
            # Extract a broad excerpt for concept extraction
            excerpt_parts = [
                (paper.abstract or self._section_text(paper, "abstract", limit=1000)),
                self._section_text(paper, "introduction", "background", limit=1000),
                self._section_text(paper, "methods", "methodology", limit=1000),
                self._section_text(paper, "conclusion", limit=1000),
            ]
            target_content = "\n".join(excerpt_parts)
            variables = {
                "full_text_excerpt": target_content
            }
        else:
            raise ValueError(f"Unknown section: {section_name}")

        if not target_content.strip():
            target_content = (supplemental_text or self._paper_fallback_text(paper, limit=4000)).strip()
            if section_name == "one_line_summary":
                variables = {
                    "abstract": target_content[:1800],
                    "introduction_excerpt": target_content[:1800],
                }
            elif section_name == "key_findings":
                variables = {"results_and_conclusion": target_content[:4000]}
            elif section_name == "methodology":
                variables = {"methods": target_content[:4000]}
            elif section_name == "limitations":
                variables = {"discussion_and_conclusion": target_content[:4000]}
            elif section_name == "concepts":
                variables = {"full_text_excerpt": target_content[:4000]}

            if not target_content:
                logger.warning(f"[LLM] No content available for section '{section_name}', using fallback")
                return self._fallback_output(section_name, "", paper.title or "")

        # Provision LLM using open notebook's native mechanism
        try:
            llm = await provision_langchain_model(
                target_content,
                model_id=None,
                default_type="chat",
                temperature=0.1,
            )
            logger.info(f"[LLM] Provisioned model for section '{section_name}': {type(llm).__name__}")
            # Reduce extra reasoning tokens only on OpenAI reasoning models.
            if self._is_reasoning_model(llm) and hasattr(llm, "model_kwargs"):
                current_kwargs = dict(getattr(llm, "model_kwargs", {}) or {})
                llm.model_kwargs = {**current_kwargs, "reasoning_effort": "low"}
                logger.debug(f"[LLM] Applied reasoning_effort=low for section '{section_name}'")
        except Exception as e:
            logger.error(
                f"Failed to provision LLM model for section '{section_name}'. "
                f"This usually means no default chat model is configured or the "
                f"API key is missing. Error: {e}. "
                f"Visit /api/papermind/diagnostics/llm for details."
            )
            return self._fallback_output(section_name, target_content, paper.title or "")

        chain = prompt_template | llm | JsonOutputParser()
        try:
            logger.info(f"[LLM] Invoking chain for section '{section_name}' (content length: {len(target_content)} chars)")
            result = await chain.ainvoke(variables)
            logger.info(f"[LLM] Section '{section_name}' generated successfully via LLM")
            return result
        except Exception as e:
            logger.debug(f"Chain parser failed for '{section_name}', using regex fallback: {e}")
            # Retry once without strict JSON parsing and recover best-effort output.
            try:
                messages = prompt_template.format_messages(**variables)
                raw_response = await llm.ainvoke(messages)
                raw_text = self._clean_llm_text(getattr(raw_response, "content", str(raw_response)))

                # Reasoning models (o1, o3, etc.) output thinking before JSON.
                # Find the LAST JSON structure in the response.
                # Look for [ ... ] or { ... } that is properly balanced.
                json_result = self._extract_json_from_text(raw_text)
                if json_result is not None:
                    return json_result

                # Try parsing the entire cleaned text as JSON
                try:
                    return json.loads(raw_text)
                except Exception:
                    pass

                if section_name in ["key_findings", "limitations", "concepts"]:
                    bullet_lines = [
                        re.sub(r"^[-*\d\.)\s]+", "", line).strip()
                        for line in raw_text.splitlines()
                        if line.strip() and not line.strip().startswith("**")
                    ]
                    if bullet_lines:
                        return bullet_lines[:10]
                elif raw_text:
                    return raw_text

                logger.warning(
                    f"Parser fallback failed for section '{section_name}'; using heuristic fallback output"
                )
            except Exception as retry_err:
                logger.warning(
                    f"Parser fallback failed for section '{section_name}' during retry: {retry_err}"
                )

            return self._fallback_output(section_name, target_content, paper.title or "")

    @staticmethod
    def _extract_json_from_text(text: str):
        """Extract the last balanced JSON structure from text.

        Reasoning models (o1, o3, DeepSeek-R1, etc.) output thinking
        before the actual JSON response.  This scans for the last
        ``[`` or ``{`` that starts a balanced JSON value and returns it.
        """
        if not text:
            return None

        # Collect candidate start positions for [ and {
        # Process from the END so we find the last JSON block (after reasoning).
        candidates: list[tuple[int, str]] = []
        for i in range(len(text) - 1, -1, -1):
            ch = text[i]
            if ch in ("[", "{"):
                candidates.append((i, ch))
                if len(candidates) >= 20:
                    break  # safety limit

        for start_pos, bracket in reversed(candidates):
            substr = text[start_pos:].strip()
            try:
                result = json.loads(substr)
                if isinstance(result, (dict, list)):
                    return result
            except json.JSONDecodeError:
                # Try to find the balanced closing bracket manually
                depth = 0
                in_string = False
                escape_next = False
                end = -1
                open_ch = bracket
                close_ch = "]" if open_ch == "[" else "}"
                for j in range(start_pos, len(text)):
                    c = text[j]
                    if escape_next:
                        escape_next = False
                        continue
                    if c == "\\":
                        escape_next = True
                        continue
                    if c == '"':
                        in_string = not in_string
                        continue
                    if in_string:
                        continue
                    if c == open_ch:
                        depth += 1
                    elif c == close_ch:
                        depth -= 1
                        if depth == 0:
                            end = j + 1
                            break
                if end > start_pos:
                    try:
                        result = json.loads(text[start_pos:end])
                        if isinstance(result, (dict, list)):
                            return result
                    except json.JSONDecodeError:
                        continue

        return None

    async def _source_full_text(self, paper: AcademicPaper) -> str:
        try:
            source_id = getattr(paper, "source_id", None)
            if not source_id:
                return ""
            rows_raw = await repo_query("SELECT full_text FROM $id", {"id": ensure_record_id(str(source_id))})
            rows = _rows_from_query_result(rows_raw)
            if rows and isinstance(rows[0], dict):
                return str(rows[0].get("full_text") or "").strip()
            return ""
        except Exception:
            return ""

    async def generate_note(self, paper: AcademicPaper, raw_text: str = "") -> GeneratedNote:
        """
        Process:
        1. Load prompts from YAML (already done in init)
        2. For each section prompt, substitute variables from paper data
        3. Call LLM via existing Open Notebook LangChain chain
        4. Parse JSON responses
        5. Return GeneratedNote dataclass
        6. Save note to the existing Open Notebook `note` table, linked to the source
        7. Create/link Concept records for extracted concepts
        """
        # Run generations in parallel or sequentially. We will do sequentially to respect rate limits if any
        supplemental_text = self._paper_fallback_text(paper, limit=4000)

        # Prefer raw_text passed directly from the parser (most reliable source)
        if raw_text and raw_text.strip():
            supplemental_text = (supplemental_text + "\n\n" + raw_text[:12000]).strip() if supplemental_text else raw_text[:12000]
        else:
            source_full_text = await self._source_full_text(paper)
            if source_full_text:
                supplemental_text = (supplemental_text + "\n\n" + source_full_text[:12000]).strip()
            elif not supplemental_text:
                supplemental_text = source_full_text

        if not supplemental_text:
            logger.error(
                f"No content available for note generation. "
                f"paper.abstract={bool(paper.abstract)}, "
                f"paper.sections={list(paper.sections.keys()) if paper.sections else 'empty'}, "
                f"raw_text={len(raw_text) if raw_text else 0} chars"
            )

        one_line_summary = await self._call_llm_for_section(
            "one_line_summary", paper, self.sections["one_line_summary"], supplemental_text
        )
        key_findings = await self._call_llm_for_section(
            "key_findings", paper, self.sections["key_findings"], supplemental_text
        )
        methodology = await self._call_llm_for_section(
            "methodology", paper, self.sections["methodology"], supplemental_text
        )
        limitations = await self._call_llm_for_section(
            "limitations", paper, self.sections["limitations"], supplemental_text
        )
        concepts = await self._call_llm_for_section(
            "concepts", paper, self.sections["concepts"], supplemental_text
        )

        # Ensure types are correct
        if isinstance(one_line_summary, dict) and "one_line_summary" in one_line_summary:
            one_line_summary = one_line_summary["one_line_summary"]
        if isinstance(methodology, dict) and "methodology" in methodology:
            methodology = methodology["methodology"]
        key_findings = self._ensure_str_list(key_findings, fallback=["No key findings available."])
        limitations = self._ensure_str_list(
            limitations,
            fallback=["Limitations not explicitly stated in source text."],
        )
        concepts = self._ensure_str_list(concepts, fallback=[], max_items=15)

        methodology = str(methodology or "").strip()
        if self._is_placeholder_text(methodology):
            methodology = self._derive_methodology_from_text(supplemental_text)

        filtered_limitations = [
            item for item in limitations
            if not self._is_placeholder_text(str(item))
        ]
        if not filtered_limitations:
            filtered_limitations = self._derive_limitations_from_text(supplemental_text)
        limitations = filtered_limitations

        # 6. Save note to Open Notebook note table
        content_md = f"# Note for {paper.title}\n\n"
        content_md += f"**Summary**: {one_line_summary}\n\n"
        
        content_md += "## Key Findings\n"
        for finding in key_findings:
            content_md += f"- {finding}\n"
        content_md += "\n"

        content_md += f"## Methodology\n{methodology}\n\n"
        
        content_md += "## Limitations\n"
        for lim in limitations:
            content_md += f"- {lim}\n"
        content_md += "\n"

        content_md += "**Concepts**: " + ", ".join(concepts)

        note = Note(
            title=f"Academic Note: {paper.title}",
            note_type="ai",
            content=content_md
        )
        _ = await note.save()
        note_id = str(note.id) if note.id else None
        if not note_id:
            raise RuntimeError("Failed to persist generated note record")
        
        # Link note to the notebook and paper using reference edges
        notebook_id = await self._resolve_notebook_id_for_source(str(paper.source_id))
        if notebook_id:
            await note.add_to_notebook(str(notebook_id))
        
        if paper.id:
            await repo_query(
                "RELATE $in -> refer -> $out",
                {
                    "in": ensure_record_id(str(paper.id)),
                    "out": ensure_record_id(note_id),
                },
            )

        # 7. Return generated note (concept persistence handled by save_concepts in ingest)
        generated = GeneratedNote(
            one_line_summary=str(one_line_summary),
            key_findings=list(key_findings),
            methodology=str(methodology),
            limitations=list(limitations),
            concepts=list(concepts),
            note_id=note_id
        )
        return generated
