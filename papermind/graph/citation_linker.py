import re
from difflib import SequenceMatcher
from typing import Optional

from open_notebook.database.repository import ensure_record_id, repo_query


def _rows_from_query_result(query_result):
    if not query_result:
        return []

    first = query_result[0]
    if isinstance(first, dict) and isinstance(first.get("result"), list):
        return first["result"]
    if isinstance(first, list):
        return first
    if isinstance(query_result, list):
        return [row for row in query_result if isinstance(row, dict)]
    return []


class CitationLinker:
    DOI_PATTERN = re.compile(r"10\.\d{4,}/[^\s]+", re.IGNORECASE)

    @staticmethod
    def _normalize_title(value: str) -> str:
        lowered = (value or "").lower()
        cleaned = re.sub(r"[^a-z0-9\s]", " ", lowered)
        return re.sub(r"\s+", " ", cleaned).strip()

    async def link_references(self, paper_id: str, raw_references: list[str]) -> int:
        if not raw_references:
            return 0

        candidate_rows = _rows_from_query_result(
            await repo_query(
                "SELECT id, title, doi FROM academic_paper WHERE id != $paper_id",
                {"paper_id": ensure_record_id(paper_id)},
            )
        )

        doi_index: dict[str, str] = {}
        title_index: list[tuple[str, str]] = []
        for row in candidate_rows:
            if not isinstance(row, dict):
                continue
            row_id = str(row.get("id"))
            doi = str(row.get("doi") or "").strip().lower()
            title = self._normalize_title(str(row.get("title") or ""))
            if doi:
                doi_index[doi] = row_id
            if title:
                title_index.append((title, row_id))

        linked_targets: set[str] = set()
        created = 0

        for ref in raw_references:
            ref_text = str(ref or "").strip()
            if not ref_text:
                continue

            doi_match = self.DOI_PATTERN.search(ref_text)
            if doi_match:
                ref_doi = doi_match.group(0).rstrip(".,;:)]}").lower()
                target_id = doi_index.get(ref_doi)
                if target_id and target_id not in linked_targets:
                    await repo_query(
                        "RELATE $in -> cites -> $out SET confidence = 1.0",
                        {
                            "in": ensure_record_id(paper_id),
                            "out": ensure_record_id(target_id),
                        },
                    )
                    linked_targets.add(target_id)
                    created += 1
                    continue

            ref_norm = self._normalize_title(ref_text)
            if not ref_norm:
                continue

            best_ratio = 0.0
            best_target: Optional[str] = None
            for title_norm, target_id in title_index:
                ratio = SequenceMatcher(None, ref_norm, title_norm).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_target = target_id

            if best_target and best_ratio >= 0.88 and best_target not in linked_targets:
                await repo_query(
                    "RELATE $in -> cites -> $out SET confidence = $confidence",
                    {
                        "in": ensure_record_id(paper_id),
                        "out": ensure_record_id(best_target),
                        "confidence": float(best_ratio),
                    },
                )
                linked_targets.add(best_target)
                created += 1

        return created
