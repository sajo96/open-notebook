-- Title quality metadata for parsed academic papers
DEFINE FIELD IF NOT EXISTS title_source ON academic_paper TYPE option<string>;
DEFINE FIELD IF NOT EXISTS title_confidence ON academic_paper TYPE option<float>;
