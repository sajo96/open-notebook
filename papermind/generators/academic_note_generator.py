import yaml
import json
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional, Any, Dict
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from open_notebook.ai.provision import provision_langchain_model
from open_notebook.database.repository import repo_query
from open_notebook.domain.notebook import Note
from papermind.models import AcademicPaper, Concept

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

    async def _call_llm_for_section(self, section_name: str, paper: AcademicPaper, section_config: dict) -> Any:
        prompt_template = ChatPromptTemplate.from_messages([
            ("system", self.system_prompt),
            ("user", section_config["prompt"])
        ])

        # Prepare variables based on the section
        variables = {}
        target_content = ""
        if section_name == "one_line_summary":
            intro = paper.sections.get("Introduction", "")[:2000]
            abstract = paper.abstract or ""
            target_content = intro + abstract
            variables = {
                "abstract": abstract,
                "introduction_excerpt": intro
            }
        elif section_name == "key_findings":
            results = paper.sections.get("Results", "")
            conclusion = paper.sections.get("Conclusion", "")
            target_content = results + conclusion
            variables = {
                "results_and_conclusion": target_content[:4000]
            }
        elif section_name == "methodology":
            methods = paper.sections.get("Methods", "")
            if not methods:
                methods = paper.sections.get("Methodology", "")
            target_content = methods
            variables = {
                "methods": target_content[:4000]
            }
        elif section_name == "limitations":
            discussion = paper.sections.get("Discussion", "")
            conclusion = paper.sections.get("Conclusion", "")
            target_content = discussion + conclusion
            variables = {
                "discussion_and_conclusion": target_content[:4000]
            }
        elif section_name == "concepts":
            # Extract a broad excerpt for concept extraction
            excerpt_parts = [
                paper.abstract or "",
                paper.sections.get("Introduction", "")[:1000],
                paper.sections.get("Methods", "")[:1000],
                paper.sections.get("Conclusion", "")[:1000]
            ]
            target_content = "\n".join(excerpt_parts)
            variables = {
                "full_text_excerpt": target_content
            }
        else:
            raise ValueError(f"Unknown section: {section_name}")

        # Provision LLM using open notebook's native mechanism
        llm = await provision_langchain_model(
            target_content, 
            model_id=None, 
            default_type="chat", 
            temperature=0.1
        )

        chain = prompt_template | llm | JsonOutputParser()
        try:
            result = await chain.ainvoke(variables)
            return result
        except Exception as e:
            print(f"Failed to generate section {section_name}: {str(e)}")
            # Return fallback empty state
            if section_name in ["key_findings", "limitations", "concepts"]:
                return []
            return ""

    async def generate_note(self, paper: AcademicPaper) -> GeneratedNote:
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
        one_line_summary = await self._call_llm_for_section("one_line_summary", paper, self.sections["one_line_summary"])
        key_findings = await self._call_llm_for_section("key_findings", paper, self.sections["key_findings"])
        methodology = await self._call_llm_for_section("methodology", paper, self.sections["methodology"])
        limitations = await self._call_llm_for_section("limitations", paper, self.sections["limitations"])
        concepts = await self._call_llm_for_section("concepts", paper, self.sections["concepts"])

        # Ensure types are correct
        if isinstance(one_line_summary, dict) and "one_line_summary" in one_line_summary:
            one_line_summary = one_line_summary["one_line_summary"]
        if isinstance(methodology, dict) and "methodology" in methodology:
            methodology = methodology["methodology"]

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
        note_id = await note.save()
        
        # Link note to the notebook and paper using reference edges
        notebook_id = getattr(paper.source_id, "notebook_id", "") if hasattr(paper.source_id, "notebook_id") else ""
        if notebook_id:
            await repo_query("RELATE type::thing($in) -> reference -> type::thing($out)", {"in": notebook_id, "out": note_id})
        
        if paper.id:
             await repo_query("RELATE type::thing($in) -> refer -> type::thing($out)", {"in": paper.id, "out": note_id})

        # 7. Create/link Concept records
        for concept_label in concepts:
            # Check if concept exists, or create it. We can UPSERT by label natively but let's query first
            slug = concept_label.strip().lower().replace(" ", "_")
            concept_id = f"concept:{slug}"
            try:
                await repo_query(
                    "UPDATE type::thing($id) SET label = $label, created_at = time::now()", 
                    {"id": concept_id, "label": concept_label.strip()}
                )
                if paper.id:
                    await repo_query(
                        "RELATE type::thing($in) -> tagged_with -> type::thing($out)",
                        {"in": paper.id, "out": concept_id}
                    )
            except Exception as e:
                print(f"Failed linking concept {concept_label}: {e}")

        # Return generated note object
        generated = GeneratedNote(
            one_line_summary=str(one_line_summary),
            key_findings=list(key_findings),
            methodology=str(methodology),
            limitations=list(limitations),
            concepts=list(concepts),
            note_id=note_id
        )
        return generated
