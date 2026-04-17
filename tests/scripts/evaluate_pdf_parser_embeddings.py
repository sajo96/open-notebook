#!/usr/bin/env python3
"""
Compare PDF parsing and embedding outcomes between PyMuPDF and PyMuPDF4LLM.

Examples:
  uv run python tests/scripts/evaluate_pdf_parser_embeddings.py test_papers/sample.pdf
  uv run python tests/scripts/evaluate_pdf_parser_embeddings.py test_papers --recursive
  uv run python tests/scripts/evaluate_pdf_parser_embeddings.py test_papers/sample.pdf --skip-embeddings
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from papermind.atoms.chunker import chunk_paper_into_atoms, get_token_count
from papermind.atoms.embedder import AtomEmbedder
from papermind.parsers.academic_pdf_parser import AcademicPDFParser, ParsedPaper


@dataclass
class BackendEvaluation:
    backend_requested: str
    backend_used: str
    parse_seconds: float
    is_ocr: bool
    text_chars: int
    text_words: int
    section_count: int
    atom_count: int
    atom_avg_tokens: float
    atom_median_tokens: float
    embedding_seconds: float | None = None
    embedding_chunks_used: int = 0
    embedding_pairwise_cosine_mean: float | None = None
    embedding_pairwise_cosine_std: float | None = None
    embedding_query_count: int = 0
    embedding_query_to_chunk_max_cosine_mean: float | None = None
    embedding_error: str | None = None


@dataclass
class PdfEvaluation:
    pdf_path: str
    backends: dict[str, BackendEvaluation]
    deltas: dict[str, float]


def _normalize_rows(vectors: list[np.ndarray]) -> np.ndarray:
    matrix = np.vstack([np.asarray(v, dtype=np.float32).reshape(-1) for v in vectors])
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    safe_norms = np.where(norms > 0.0, norms, 1.0)
    return matrix / safe_norms


def _sample_pairwise_cosines(normalized: np.ndarray, max_pairs: int) -> tuple[float | None, float | None]:
    n = normalized.shape[0]
    if n < 2:
        return None, None

    total_pairs = (n * (n - 1)) // 2
    rng = np.random.default_rng(42)
    scores: list[float] = []

    if total_pairs <= max_pairs:
        for i in range(n):
            row_i = normalized[i]
            for j in range(i + 1, n):
                scores.append(float(np.dot(row_i, normalized[j])))
    else:
        seen: set[tuple[int, int]] = set()
        while len(scores) < max_pairs:
            i = int(rng.integers(0, n))
            j = int(rng.integers(0, n))
            if i == j:
                continue
            a, b = (i, j) if i < j else (j, i)
            if (a, b) in seen:
                continue
            seen.add((a, b))
            scores.append(float(np.dot(normalized[a], normalized[b])))

    if not scores:
        return None, None

    if len(scores) == 1:
        return scores[0], 0.0

    return float(statistics.mean(scores)), float(statistics.pstdev(scores))


def _build_query_set(parsed: ParsedPaper) -> list[str]:
    queries: list[str] = []

    title = str(parsed.title or "").strip()
    if title and title.lower() not in {"unknown title", "unknown paper"}:
        queries.append(title)

    abstract = str(parsed.abstract or "").strip()
    if abstract:
        queries.append(abstract[:300])

    for key in parsed.sections.keys():
        section_name = str(key).strip().replace("_", " ")
        if not section_name or section_name in {"frontmatter", "full text", "full_text"}:
            continue
        queries.append(section_name)
        if len(queries) >= 8:
            break

    if not queries:
        queries.append("main findings and methods")

    deduped: list[str] = []
    seen: set[str] = set()
    for q in queries:
        normalized = q.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(q)

    return deduped


async def _evaluate_backend(
    pdf_path: Path,
    backend: str,
    max_chunks: int,
    max_pairs: int,
    include_embeddings: bool,
    embedder: AtomEmbedder | None,
) -> BackendEvaluation:
    parse_started = time.perf_counter()
    parser = AcademicPDFParser(file_path=str(pdf_path), parser_backend=backend)
    parsed = parser.parse()
    parse_seconds = time.perf_counter() - parse_started

    atoms = chunk_paper_into_atoms(parsed, paper_id="academic_paper:benchmark")
    atom_texts = [str(atom.content or "").strip() for atom in atoms if str(atom.content or "").strip()]
    token_counts = [get_token_count(text) for text in atom_texts]

    result = BackendEvaluation(
        backend_requested=backend,
        backend_used=parser.parser_backend_used,
        parse_seconds=parse_seconds,
        is_ocr=bool(parsed.is_ocr),
        text_chars=len(parsed.raw_text or ""),
        text_words=len((parsed.raw_text or "").split()),
        section_count=len(parsed.sections or {}),
        atom_count=len(atom_texts),
        atom_avg_tokens=float(statistics.mean(token_counts)) if token_counts else 0.0,
        atom_median_tokens=float(statistics.median(token_counts)) if token_counts else 0.0,
    )

    if not include_embeddings:
        return result

    if not embedder:
        result.embedding_error = "Embedding is enabled but embedder is not available"
        return result

    if not atom_texts:
        result.embedding_error = "No atoms were produced from parsed text"
        return result

    try:
        selected_chunks = atom_texts[:max_chunks]
        embed_started = time.perf_counter()
        chunk_vectors = await embedder.embed_batch(selected_chunks)
        result.embedding_seconds = time.perf_counter() - embed_started
        result.embedding_chunks_used = len(chunk_vectors)

        normalized_chunks = _normalize_rows(chunk_vectors)
        mean_cos, std_cos = _sample_pairwise_cosines(normalized_chunks, max_pairs=max_pairs)
        result.embedding_pairwise_cosine_mean = mean_cos
        result.embedding_pairwise_cosine_std = std_cos

        queries = _build_query_set(parsed)
        result.embedding_query_count = len(queries)
        if queries:
            query_vectors = await embedder.embed_batch(queries)
            normalized_queries = _normalize_rows(query_vectors)
            similarity_matrix = normalized_queries @ normalized_chunks.T
            best_per_query = np.max(similarity_matrix, axis=1)
            result.embedding_query_to_chunk_max_cosine_mean = float(np.mean(best_per_query))
    except Exception as exc:
        result.embedding_error = str(exc)

    return result


def _discover_pdf_files(inputs: list[str], recursive: bool) -> list[Path]:
    files: list[Path] = []
    for raw in inputs:
        path = Path(raw).expanduser().resolve()
        if path.is_file() and path.suffix.lower() == ".pdf":
            files.append(path)
            continue

        if path.is_dir():
            pattern = "**/*.pdf" if recursive else "*.pdf"
            files.extend(sorted(path.glob(pattern)))

    unique_files = sorted({p for p in files})
    return unique_files


def _compute_deltas(by_backend: dict[str, BackendEvaluation]) -> dict[str, float]:
    if "pymupdf" not in by_backend or "pymupdf4llm" not in by_backend:
        return {}

    base = by_backend["pymupdf"]
    alt = by_backend["pymupdf4llm"]
    deltas: dict[str, float] = {
        "delta_parse_seconds": alt.parse_seconds - base.parse_seconds,
        "delta_section_count": float(alt.section_count - base.section_count),
        "delta_atom_count": float(alt.atom_count - base.atom_count),
        "delta_atom_avg_tokens": alt.atom_avg_tokens - base.atom_avg_tokens,
    }

    if (
        base.embedding_query_to_chunk_max_cosine_mean is not None
        and alt.embedding_query_to_chunk_max_cosine_mean is not None
    ):
        deltas["delta_query_to_chunk_cosine_mean"] = (
            alt.embedding_query_to_chunk_max_cosine_mean - base.embedding_query_to_chunk_max_cosine_mean
        )

    return deltas


def _print_summary(result: PdfEvaluation) -> None:
    print(f"\n=== {result.pdf_path} ===")
    for backend_name, metrics in result.backends.items():
        print(
            f"[{backend_name}] used={metrics.backend_used} "
            f"parse={metrics.parse_seconds:.2f}s sections={metrics.section_count} "
            f"atoms={metrics.atom_count} avg_tokens={metrics.atom_avg_tokens:.1f}"
        )

        if metrics.embedding_error:
            print(f"  embeddings: skipped/error -> {metrics.embedding_error}")
        elif metrics.embedding_seconds is not None:
            query_score = (
                f"{metrics.embedding_query_to_chunk_max_cosine_mean:.4f}"
                if metrics.embedding_query_to_chunk_max_cosine_mean is not None
                else "n/a"
            )
            pairwise_mean = (
                f"{metrics.embedding_pairwise_cosine_mean:.4f}"
                if metrics.embedding_pairwise_cosine_mean is not None
                else "n/a"
            )
            print(
                f"  embeddings: {metrics.embedding_chunks_used} chunks in {metrics.embedding_seconds:.2f}s "
                f"pairwise_mean={pairwise_mean} query_to_chunk_mean={query_score}"
            )

    if result.deltas:
        print("deltas (pymupdf4llm - pymupdf):")
        for key, value in result.deltas.items():
            print(f"  {key}: {value:.4f}")


async def _run(args: argparse.Namespace) -> int:
    pdf_files = _discover_pdf_files(args.inputs, recursive=args.recursive)
    if not pdf_files:
        print("No PDF files found. Pass a PDF file path or directory containing PDFs.")
        return 1

    backends = [b.strip().lower() for b in args.backends.split(",") if b.strip()]
    include_embeddings = not args.skip_embeddings
    embedder = AtomEmbedder() if include_embeddings else None

    all_results: list[PdfEvaluation] = []

    for pdf_path in pdf_files:
        by_backend: dict[str, BackendEvaluation] = {}
        for backend in backends:
            metrics = await _evaluate_backend(
                pdf_path=pdf_path,
                backend=backend,
                max_chunks=args.max_chunks,
                max_pairs=args.max_pairs,
                include_embeddings=include_embeddings,
                embedder=embedder,
            )
            by_backend[backend] = metrics

        evaluation = PdfEvaluation(
            pdf_path=str(pdf_path),
            backends=by_backend,
            deltas=_compute_deltas(by_backend),
        )
        all_results.append(evaluation)
        _print_summary(evaluation)

    if args.json_out:
        payload = {
            "generated_at_epoch": time.time(),
            "backends": backends,
            "results": [
                {
                    "pdf_path": item.pdf_path,
                    "backends": {name: asdict(metrics) for name, metrics in item.backends.items()},
                    "deltas": item.deltas,
                }
                for item in all_results
            ],
        }
        output_path = Path(args.json_out).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nJSON report written to: {output_path}")

    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate parsing + embedding impact: PyMuPDF vs PyMuPDF4LLM"
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        help="PDF file(s) or directory path(s)",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Recursively search directories for PDFs",
    )
    parser.add_argument(
        "--backends",
        default="pymupdf,pymupdf4llm",
        help="Comma-separated parser backends to evaluate",
    )
    parser.add_argument(
        "--max-chunks",
        type=int,
        default=80,
        help="Max atom chunks per backend to embed",
    )
    parser.add_argument(
        "--max-pairs",
        type=int,
        default=2000,
        help="Max pairwise cosine comparisons for chunk diversity",
    )
    parser.add_argument(
        "--skip-embeddings",
        action="store_true",
        help="Run parse/chunk comparison only (no embedding calls)",
    )
    parser.add_argument(
        "--json-out",
        default="",
        help="Optional path to save JSON output",
    )
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
