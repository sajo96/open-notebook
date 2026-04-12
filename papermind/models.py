from datetime import datetime
from typing import ClassVar, Dict, List, Optional

from open_notebook.domain.base import ObjectModel


class AcademicPaper(ObjectModel):
    table_name: ClassVar[str] = 'academic_paper'
    
    source_id: str
    title: str
    authors: List[str] = []
    abstract: Optional[str] = None
    doi: Optional[str] = None
    year: Optional[int] = None
    keywords: List[str] = []
    sections: Dict[str, str] = {}
    raw_references: List[str] = []
    created_at: Optional[datetime] = None


class Atom(ObjectModel):
    table_name: ClassVar[str] = 'atom'
    
    paper_id: str
    section_label: str
    content: str
    embedding: Optional[List[float]] = None
    created_at: Optional[datetime] = None


class Concept(ObjectModel):
    table_name: ClassVar[str] = 'concept'
    
    label: str
    description: Optional[str] = None
    created_at: Optional[datetime] = None


class WatchedFolder(ObjectModel):
    table_name: ClassVar[str] = 'watched_folder'
    
    path: str
    notebook_id: str
    recursive: bool = False
    active: bool = True
    created_at: Optional[datetime] = None
