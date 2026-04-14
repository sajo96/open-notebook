-- AcademicPaper: extends the existing source record with structured metadata
DEFINE TABLE academic_paper SCHEMAFULL;
DEFINE FIELD source_id       ON academic_paper TYPE record(source);
DEFINE FIELD title           ON academic_paper TYPE string;
DEFINE FIELD authors         ON academic_paper TYPE array<string>;
DEFINE FIELD abstract        ON academic_paper TYPE option<string>;
DEFINE FIELD doi             ON academic_paper TYPE option<string>;
DEFINE FIELD year            ON academic_paper TYPE option<int>;
DEFINE FIELD keywords        ON academic_paper TYPE array<string>;
DEFINE FIELD sections        ON academic_paper TYPE object;  -- { abstract: str, intro: str, methods: str, results: str, discussion: str, conclusion: str }
DEFINE FIELD raw_references  ON academic_paper TYPE array<string>;
DEFINE FIELD created_at      ON academic_paper TYPE datetime DEFAULT time::now();

-- Atom: a small semantic unit (one section or chunk) from a paper
DEFINE TABLE atom SCHEMAFULL;
DEFINE FIELD paper_id        ON atom TYPE record(academic_paper);
DEFINE FIELD section_label   ON atom TYPE string;  -- "abstract" | "introduction" | "methods" | "results" | "discussion" | "conclusion" | "chunk_{n}"
DEFINE FIELD content         ON atom TYPE string;
DEFINE FIELD embedding       ON atom TYPE option<array<float>>;  -- stored as float array; also mirrored in sqlite-vec
DEFINE FIELD created_at      ON atom TYPE datetime DEFAULT time::now();

-- Concept: named entities and key themes extracted from papers
DEFINE TABLE concept SCHEMAFULL;
DEFINE FIELD label           ON concept TYPE string;
DEFINE FIELD description     ON concept TYPE option<string>;
DEFINE FIELD created_at      ON concept TYPE datetime DEFAULT time::now();
DEFINE INDEX concept_label_unique ON concept FIELDS label UNIQUE;

-- Graph edges: paper cites paper (explicit)
DEFINE TABLE cites SCHEMAFULL TYPE RELATION FROM academic_paper TO academic_paper;
DEFINE FIELD confidence      ON cites TYPE float DEFAULT 1.0;  -- 1.0 = confirmed DOI match, <1.0 = fuzzy title match

-- Graph edges: atom semantically similar to atom (auto-computed)
DEFINE TABLE similar_to SCHEMAFULL TYPE RELATION FROM atom TO atom;
DEFINE FIELD similarity_score ON similar_to TYPE float;  -- cosine similarity 0.0-1.0

-- Graph edges: paper tagged with concept
DEFINE TABLE tagged_with SCHEMAFULL TYPE RELATION FROM academic_paper TO concept;

-- WatchedFolder: config for folder watcher service
DEFINE TABLE watched_folder SCHEMAFULL;
DEFINE FIELD path            ON watched_folder TYPE string;
DEFINE FIELD notebook_id     ON watched_folder TYPE record(notebook);
DEFINE FIELD recursive       ON watched_folder TYPE bool DEFAULT false;
DEFINE FIELD active          ON watched_folder TYPE bool DEFAULT true;
DEFINE FIELD created_at      ON watched_folder TYPE datetime DEFAULT time::now();
DEFINE INDEX watched_folder_path_unique ON watched_folder FIELDS path UNIQUE;