"""Token-based text chunking with sliding window overlap."""

import tiktoken
from typing import List
from dataclasses import dataclass


@dataclass
class TextChunk:
    """A single chunk of text with metadata."""
    content: str
    section_label: str
    start_idx: int
    end_idx: int
    token_count: int


class TokenChunker:
    """
    Chunks text by token count using tiktoken for accurate tokenization.
    
    Uses CL100K encoding (same as nomic-embed-text) to ensure consistency
    between chunking and embedding token counts.
    """
    
    def __init__(self, chunk_size: int = 600, overlap: int = 100):
        """
        Initialize chunker with token-based splitting.
        
        Args:
            chunk_size: Target chunk size in tokens (default 600)
            overlap: Token overlap between chunks (default 100)
        """
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.encoding = tiktoken.get_encoding("cl100k_base")
        self.stride = chunk_size - overlap
    
    def count_tokens(self, text: str) -> int:
        """Count tokens in text using cl100k_base encoding."""
        return len(self.encoding.encode(text))
    
    def chunk_section(self, section_text: str, section_label: str) -> List[TextChunk]:
        """
        Split a section into chunks with sliding window overlap.
        
        Args:
            section_text: Full text of the section
            section_label: Label/title of the section (e.g., "Introduction")
            
        Returns:
            List of TextChunk objects
        """
        if not section_text or not section_text.strip():
            return []
        
        # Encode entire text
        tokens = self.encoding.encode(section_text)
        
        if len(tokens) <= self.chunk_size:
            # Text fits in one chunk
            return [
                TextChunk(
                    content=section_text,
                    section_label=section_label,
                    start_idx=0,
                    end_idx=len(tokens),
                    token_count=len(tokens),
                )
            ]
        
        # Split with sliding window
        chunks = []
        start = 0
        
        while start < len(tokens):
            # Calculate end position
            end = min(start + self.chunk_size, len(tokens))
            
            # Decode chunk back to text
            chunk_tokens = tokens[start:end]
            chunk_text = self.encoding.decode(chunk_tokens)
            
            chunks.append(
                TextChunk(
                    content=chunk_text,
                    section_label=section_label,
                    start_idx=start,
                    end_idx=end,
                    token_count=len(chunk_tokens),
                )
            )
            
            # Move to next chunk start (with overlap)
            start += self.stride
            
            # Break if we've covered all tokens
            if end == len(tokens):
                break
        
        return chunks
    
    def chunk_sections(self, sections: List[str], section_labels: List[str] = None) -> List[TextChunk]:
        """
        Chunk multiple sections.
        
        Args:
            sections: List of section texts
            section_labels: Optional labels for sections (defaults to Section 1, 2, etc.)
            
        Returns:
            List of all TextChunk objects across all sections
        """
        if section_labels is None:
            section_labels = [f"Section {i+1}" for i in range(len(sections))]
        
        all_chunks = []
        for section_text, label in zip(sections, section_labels):
            chunks = self.chunk_section(section_text, label)
            all_chunks.extend(chunks)
        
        return all_chunks
