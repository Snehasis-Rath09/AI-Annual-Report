# Annual Report Disclosure Analysis: Technical Project Report

## Abstract

This project implements a reproducible natural language processing system for
analyzing artificial intelligence, automation, analytics, digital transformation,
research, patent, and innovation disclosures in annual reports of Indian listed
companies. The system converts heterogeneous PDF reports into structured text,
detects relevant sections, counts terms from a governed innovation dictionary,
calculates transparent disclosure metrics, produces a weighted disclosure score,
and exports results for analysis and manual validation. Native PDF extraction is
supplemented by OCR for scanned documents. A Streamlit dashboard provides
portfolio, company, and comparative views of generated outputs without coupling
the user interface to extraction. The design emphasizes traceability,
configuration, modularity, robust failure handling, and human verification.

## Problem Statement

Annual reports are a primary channel through which listed companies communicate
strategy, investment priorities, operational capabilities, risk, and future
plans. References to AI and innovation can appear across hundreds of pages and in
different sections, terminology, layouts, and PDF encodings. A purely manual
review is time-consuming and difficult to reproduce at portfolio scale. Simple
document-wide string search is faster but can miss scanned text, section context,
multi-word phrases, spelling variants, and reporting structure.

The research problem is therefore to create a scalable and auditable method that:

1. obtains usable text from both digital and scanned annual reports;
2. focuses analysis on disclosure-relevant sections;
3. measures governed terms consistently across companies and years;
4. converts measurements into explainable summary indicators; and
5. supports comparison with manually verified observations.

The system measures disclosure language. It does not claim to measure actual AI
capability, innovation expenditure, implementation maturity, or business impact.

## Objectives

The project objectives are to:

- automate extraction from annual report PDFs with OCR fallback;
- remove common document artifacts while retaining analytical meaning;
- identify report sections related to technology and innovation;
- maintain a configurable, category-based keyword dictionary;
- count exact words and phrases using reproducible matching rules;
- calculate count, density, coverage, diversity, and contribution metrics;
- create a transparent disclosure score from explicit formulas;
- compare automated counts with manual review data;
- generate analyst-friendly Excel and Markdown outputs;
- visualize portfolio and company results through a read-only dashboard; and
- isolate errors so one failed report does not terminate an entire batch.

## Dataset Description

### Annual Reports

The primary documents are annual report PDFs for Indian listed companies. Each
Company Master record associates a company name, ticker, industry, reporting year,
local PDF path, and HTTP(S) source URL. Reports may be digitally generated,
image-based, or a mixture of text and scanned pages.

### Company Master

`data/metadata/Company_Master.xlsx` is the processing manifest. Required logical
fields are:

- company name;
- ticker;
- industry;
- report year;
- report path; and
- source URL.

Column aliases are normalized during loading. Duplicate ticker/year records are
ignored after the first valid occurrence to prevent artifact collisions.

### Innovation Dictionary

`data/dictionaries/Innovation_Dictionary.xlsx` contains at least `Category` and
`Keyword`, with optional `Rationale`. Terms are normalized for case, whitespace,
dashes, quotation marks, ampersands, and slashes. Duplicate normalized pairs are
removed. The dictionary is an explicit research instrument and should be versioned
when terms or category definitions change.

### Manual Validation Data

`data/validation/Validation.xlsx` stores manually verified keyword counts when a
validation sample is available. The validator also accepts CSV, JSON, pandas
DataFrames, and mappings in long or wide form.

No empirical company-level results are asserted in this report because the
repository distribution does not include a completed research sample. Numerical
findings should be reported only after input provenance and manual validation are
documented.

## Methodology

### 1. Metadata and Dictionary Loading

The pipeline validates Company Master rows and loads the innovation dictionary
before processing begins. Invalid schemas, missing files, empty tables, malformed
URLs, and invalid years fail early with descriptive errors.

### 2. PDF Validation and Text Extraction

The PDF extractor verifies that a report exists, has a `.pdf` suffix, can be
opened, is not password-protected, and has at least one page. PyMuPDF is the
primary native parser. pdfplumber is the secondary parser when primary extraction
fails.

### 3. Scanned-document Detection and OCR

Native extraction output is evaluated using total character count and the ratio
of pages below a minimum text length. Text-sparse reports trigger OCR when enabled.
The OCR path renders PDF pages as images and passes them to Tesseract. If OCR
fails but sparse native text exists, the native text is retained with a warning;
otherwise extraction fails.

### 4. Text Cleaning and Normalization

Cleaning removes page numbers, repeated headers and footers, duplicated lines,
table-of-contents artifacts, non-printable characters, and excessive whitespace.
Normalization standardizes Unicode, quotation marks, hyphens, bullets, line
endings, spaces, and heading presentation while preserving known acronyms.

### 5. Heading Detection and Section Extraction

The heading detector applies canonical heading patterns and fuzzy matching to
candidate lines. Each match records a canonical heading, source text, character
span, pattern, and confidence. The section extractor takes the text between one
detected heading and the next, removes empty or short sections, and merges repeated
canonical sections.

Target sections include MD&A, Innovation, Digital Transformation, AI, Machine
Learning, Automation, Technology, Patents, Future Strategy, and Research &
Development. If none is found, the orchestrator analyzes the normalized full
report and marks the fallback in the processing result.

### 6. Keyword and Category Analysis

Dictionary keywords are counted independently within each analysis section.
Matching is case-insensitive and respects whole-word or whole-phrase boundaries.
Multi-word terms are normalized consistently between dictionary and report text.
Optional fuzzy keyword matching is available but disabled by default to protect
precision.

Section counts are aggregated for category statistics:

- raw category count;
- density per 1,000 analyzed words;
- presence or absence;
- percentage contribution to all matched terms; and
- total matched terms and analyzed words.

### 7. Metrics, Scoring, and Export

The scoring layer calculates document metrics, normalizes four components, and
combines them with configured weights. Outputs include the normalized text,
company Markdown report, validation-ready rows, and a four-sheet Excel workbook.

## System Architecture

The system uses a layered architecture:

```text
Configuration and Inputs
        │
        ▼
Extraction (native PDF and OCR)
        │
        ▼
Preprocessing (cleaning and normalization)
        │
        ▼
Section Detection and Extraction
        │
        ▼
Keyword and Category Analysis
        │
        ▼
Metrics and Disclosure Scoring
        │
        ├── Validation
        ├── Excel and Markdown Export
        └── Streamlit Visualization
```

`AnnualReportPipeline` is the application service that coordinates these layers.
Analytical modules do not import the dashboard, and the dashboard reads generated
files instead of executing the pipeline.

## Workflow

For each selected Company Master record, the pipeline:

1. validates company metadata and the local report path;
2. validates and loads the PDF;
3. extracts native text or invokes OCR fallback;
4. cleans the extracted text;
5. normalizes textual representation;
6. detects relevant headings;
7. extracts target sections;
8. falls back to whole-report analysis when necessary;
9. counts dictionary keywords by section;
10. calculates category statistics;
11. calculates disclosure metrics;
12. calculates the weighted disclosure score;
13. saves normalized extracted text;
14. creates validation-ready keyword rows;
15. exports the Excel workbook;
16. generates the Markdown report;
17. optionally compares results with manual validation data; and
18. returns a structured success or failure record.

Batch processing executes records sequentially and captures errors per company.

## Modules

### Configuration and Utilities

`config/settings.py` centralizes paths, extraction thresholds, dictionary
categories, validation thresholds, dashboard defaults, and logging configuration.
`src/utils/` provides constants, file operations, and rotating logging.

### Models

`src/models/company.py` defines a validated dataclass for company metadata and
computed results. It supports path conversion, serialization, deserialization,
and optional existence validation.

### Extraction

`src/extraction/pdf_extractor.py` handles PDF validation, native parsing,
scanned-document inference, and OCR delegation. `ocr_extractor.py` performs image
conversion and page-level OCR.

### Preprocessing

`src/preprocessing/clean_text.py` removes extraction noise.
`normalize_text.py` creates a consistent textual representation for heading and
keyword analysis.

### Section Extraction

`heading_detector.py` maps observed headings to canonical research sections.
`section_extractor.py` extracts, filters, and merges section text.

### Keyword Analysis

`dictionary_loader.py` validates and normalizes the research dictionary.
`keyword_counter.py` counts exact and optionally fuzzy terms.
`category_counter.py` creates category-level statistics.

### Scoring

`metrics.py` calculates totals, density, presence, percentage, diversity, and
section coverage. `disclosure_score.py` normalizes and combines score components.

### Validation

`validator.py` compares automated occurrence counts with manual counts and
produces structured company-level validation reports.

### Export and Services

`excel_exporter.py` creates multi-sheet workbooks. `pipeline.py` coordinates all
backend stages. `scripts/run_pipeline.py` provides the command-line interface.

### Dashboard

`dashboard/app.py` loads and caches generated workbooks. Overview, company, and
comparison pages provide interactive Plotly charts, tables, expandable section
previews, recommendations, and Markdown downloads.

## Technology Stack

| Area | Technology |
|---|---|
| Language | Python 3.12 |
| Data processing | pandas |
| PDF extraction | PyMuPDF, pdfplumber |
| OCR | Tesseract, pytesseract, pdf2image, Pillow |
| Text matching | regex, RapidFuzz |
| Excel | openpyxl |
| Visualization | Streamlit, Plotly |
| Testing | pytest, unittest.mock |
| Core design | dataclasses, pathlib, typed modular services |

## Scoring Methodology

The disclosure score is deterministic and ranges from 0 to 100. Four component
scores are normalized to this range.

### Keyword Density Component

Keyword density per 1,000 words is:

```text
density = (matched keyword occurrences / analyzed words) × 1,000
```

The density score is capped against a configurable benchmark:

```text
keyword_density_score = min(max(density / benchmark, 0), 1) × 100
```

### Category Coverage Component

```text
category_coverage_score =
    categories with at least one match / configured categories × 100
```

### Section Coverage Component

```text
section_coverage_score =
    detected expected sections / expected sections × 100
```

### Keyword Diversity Component

```text
keyword_diversity_score =
    unique matched keywords / known dictionary keywords × 100
```

### Weighted Score

```text
overall_score =
    0.40 × keyword_density_score
  + 0.30 × category_coverage_score
  + 0.20 × section_coverage_score
  + 0.10 × keyword_diversity_score
```

The benchmark and weights are explicit configuration or typed score settings.
They should be fixed before comparative research and disclosed with published
results.

## Validation

Validation compares automated and manual occurrence counts for each keyword. For
a keyword with automated count `A` and manual count `M`:

```text
true positives  = min(A, M)
false positives = max(A - M, 0)
false negatives = max(M - A, 0)
```

Metrics are calculated as:

```text
precision = TP / (TP + FP)
recall    = TP / (TP + FN)
F1        = 2 × precision × recall / (precision + recall)
```

When no explicit true-negative universe exists, accuracy is occurrence-level
Jaccard agreement:

```text
accuracy = TP / (TP + FP + FN)
```

If true negatives are supplied, standard classification accuracy is used. The
validation output also lists under-counted keywords, excess automated matches,
and threshold-based observations. Manual reviewers should verify keyword context,
not only counts, when ambiguous terms are present.

## Results

The implemented system produces the following technical outcomes:

- repeatable processing of one or multiple company reports;
- structured failure results without terminating a batch;
- section-level keyword counts and aggregated category measures;
- an explainable 0–100 score with visible components;
- validation-ready automated counts;
- Excel, plain-text, and Markdown artifacts; and
- cached, interactive visualization of generated workbooks.

The automated tests cover initialization, successful processing, multiple-company
execution, missing and invalid PDFs, missing dictionaries, empty extraction,
OCR fallback, artifact generation, exception capture, dictionary normalization,
duplicates, phrase matching, case handling, word boundaries, density, and category
statistics.

Research results such as average disclosure scores, rankings, industry effects,
precision, and recall must be calculated from a populated dataset. They are not
fabricated in this report. The dashboard computes portfolio summaries after valid
workbooks are generated.

## Limitations

- Keyword frequency measures disclosure volume, not implementation quality.
- Exact matching cannot fully resolve polysemy or negation.
- Optional fuzzy matching may introduce false positives if thresholds are low.
- OCR accuracy depends on scan resolution, layout, font, language, and system
  installation.
- Heading-driven extraction may miss relevant narrative under unusual headings.
- Whole-report fallback improves recall but may reduce contextual precision.
- Category overlap can cause one term to contribute to more than one research
  concept if the dictionary is designed that way.
- Scores depend on dictionary coverage, expected sections, and normalization
  benchmarks.
- Industry metadata quality depends on the Company Master.
- Cross-company comparisons require consistent report years, dictionary versions,
  and scoring configuration.

## Future Scope

- Add sentence-level contextual classifiers for relevance and negation.
- Record matched passages and page references for reviewer traceability.
- Add annotation workflows and inter-reviewer agreement measurement.
- Calibrate dictionary terms and weights using a larger manually labeled sample.
- Add multilingual OCR and analysis for Indian languages.
- Add longitudinal company panels and statistical significance testing.
- Introduce document-layout models for tables and complex multi-column reports.
- Publish data lineage manifests and checksums for research reproducibility.
- Add continuous integration, coverage reporting, type checking, and security
  scanning.
- Package OCR dependencies in reproducible containers.

## Conclusion

The Annual Report Disclosure Analysis project provides a complete, modular
foundation for scalable research into AI and innovation language in company
reporting. It integrates robust extraction, governed dictionary analysis,
transparent scoring, manual validation, structured export, and interactive
visualization. Its principal strength is auditability: the measured text,
dictionary terms, formulas, workbook rows, reports, and validation differences
remain inspectable. Used with a documented sample and disciplined manual review,
the system can reduce repetitive analysis effort while preserving the controls
needed for credible research.
