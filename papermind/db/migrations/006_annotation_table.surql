-- Annotation table: stores user highlights, underlines, and notes on PDF sources
DEFINE TABLE IF NOT EXISTS annotation SCHEMAFULL;

DEFINE FIELD IF NOT EXISTS source_id       ON annotation TYPE record<source>;
DEFINE FIELD IF NOT EXISTS page_number     ON annotation TYPE int;
DEFINE FIELD IF NOT EXISTS annotation_type ON annotation TYPE string ASSERT $value IN ["highlight", "underline", "note"];
DEFINE FIELD IF NOT EXISTS selected_text   ON annotation TYPE string;
DEFINE FIELD IF NOT EXISTS bounding_boxes  ON annotation TYPE array;
DEFINE FIELD IF NOT EXISTS color           ON annotation TYPE option<string>;
DEFINE FIELD IF NOT EXISTS comment         ON annotation TYPE option<string>;
DEFINE FIELD IF NOT EXISTS created_at      ON annotation TYPE datetime DEFAULT time::now();
DEFINE FIELD IF NOT EXISTS updated_at      ON annotation TYPE datetime DEFAULT time::now();

DEFINE INDEX IF NOT EXISTS annotation_source_idx ON annotation FIELDS source_id;