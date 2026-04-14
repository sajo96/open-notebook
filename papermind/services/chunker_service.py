"""Service for orchestrating the chunking pipeline (Step 4)."""

import asyncio
from typing import List
from loguru import logger

from papermind.models import AcademicPaper, Atom
from papermind.atoms.chunker import chunk_paper_into_atoms
from papermind.parsers.academic_pdf_parser import AcademicPDFParser
from open_notebook.domain.notebook import Source
from open_notebook.database.repository import ensure_record_id
from pathlib import Path


class ChunkerService:
    """
    Orchestrates the chunking pipeline:
    ParsedPaper (from parser) → chunks via TokenChunker → Atom records → persist to DB
    """
    
    async def atomize_paper(self, paper_id: str) -> int:
        """
        Chunk a parsed academic paper into atoms and persist to database.
        
        Args:
            paper_id: ID of the AcademicPaper to atomize
            
        Returns:
            Count of atoms created
            
        Raises:
            ValueError: If paper not found or cannot be chunked
        """
        try:
            # 1. Fetch the academic paper
            paper = await AcademicPaper.get(paper_id)
            if not paper:
                raise ValueError(f"Paper {paper_id} not found")
            
            logger.info(f"Atomizing paper {paper_id}: {paper.title}")
            
            # 2. Use paper's sections if available, otherwise re-parse from source file
            chunk_input = paper
            sections = getattr(paper, "sections", None)
            
            if not isinstance(sections, dict) or len(sections) == 0:
                logger.debug(f"No sections in paper {paper_id}, attempting re-parse")
                try:
                    source = await Source.get(str(paper.source_id))
                    file_path = source.asset.file_path if source and source.asset else None
                    
                    if not file_path or not Path(file_path).exists():
                        raise ValueError(f"Source file not found: {file_path}")
                    
                    # Parse synchronously in executor to avoid blocking
                    parser = AcademicPDFParser(file_path=file_path)
                    loop = asyncio.get_event_loop()
                    chunk_input = await loop.run_in_executor(None, parser.parse)
                    logger.debug(f"Re-parsed source file for {paper_id}")
                    
                except Exception as e:
                    logger.warning(f"Fallback parse for atomization failed for {paper_id}: {e}")
                    raise ValueError(f"Cannot atomize paper without sections or source file: {e}")
            
            # 3. Chunk the parsed paper into atoms
            atoms = chunk_paper_into_atoms(chunk_input, paper.id)
            if not atoms:
                logger.warning(f"No atoms created from paper {paper_id}")
                return 0
            
            logger.info(f"Chunked paper {paper_id} into {len(atoms)} atoms")
            
            # 4. Persist atoms to database
            saved_atoms = []
            for atom in atoms:
                # Ensure paper_id is a proper record ID
                atom.paper_id = ensure_record_id(str(atom.paper_id))
                try:
                    await atom.save()
                    saved_atoms.append(atom)
                    logger.debug(f"Saved atom: {atom.id} ({atom.section_label})")
                except Exception as e:
                    logger.error(f"Failed to save atom: {e}")
                    raise
            
            logger.info(f"Successfully created and persisted {len(saved_atoms)} atoms for paper {paper_id}")
            return len(saved_atoms)
            
        except Exception as e:
            logger.exception(f"Error in atomize_paper for {paper_id}: {e}")
            raise
