# Installation Guide

This guide explains how to install, configure, run, test, and troubleshoot the
Annual Report Disclosure Analysis project.

## System Requirements

### Supported Operating Systems

- Windows 10 or Windows 11
- Recent Ubuntu, Debian, Fedora, or compatible Linux distribution
- macOS with current security updates

### Hardware Guidance

Native PDF processing works on a typical development workstation. OCR is more
resource-intensive. For processing long reports, the following is recommended:

- 4 or more CPU cores;
- 8 GB RAM minimum, 16 GB recommended for batch OCR;
- sufficient free storage for source PDFs, rendered page images, logs, and
  generated workbooks; and
- an SSD for faster batch processing.

No GPU is required.

## Python Version

Python 3.12 is the supported runtime. Confirm the active interpreter:

```bash
python --version
```

The output should begin with `Python 3.12`. On systems where multiple Python
versions are installed, use the platform launcher explicitly:

```powershell
py -3.12 --version
```

Do not use a system Python environment shared with unrelated applications.

## Obtain the Project

Clone the repository using its Git hosting page, or extract the provided source
archive. Open a terminal in the resulting `AI-Annual-Report` root directory.

Verify the root contains `config`, `src`, `dashboard`, `scripts`, `tests`, and
`requirements.txt`.

## Virtual Environment Setup

### Windows PowerShell

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
```

If PowerShell blocks local activation scripts, open PowerShell as the same user
and run:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Review the policy change with your organization's security requirements before
applying it. Alternatively, use Command Prompt activation:

```bat
.venv\Scripts\activate.bat
```

### Linux or macOS

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
```

The shell prompt normally displays `(.venv)` after successful activation.

## Installing Dependencies

Install the declared project dependencies:

```bash
pip install -r requirements.txt
```

The application requires these package groups:

```bash
pip install pandas pymupdf pdfplumber openpyxl
pip install regex rapidfuzz
pip install pytesseract pdf2image pillow
pip install streamlit plotly
pip install pytest
```

Verify key imports:

```bash
python -c "import pandas, fitz, pdfplumber, openpyxl"
python -c "import streamlit, plotly, pytest"
```

### Tesseract OCR

OCR fallback requires the Tesseract executable in addition to the Python package.

#### Windows

Install a current Tesseract distribution and add its installation directory to
the user or system `PATH`. Open a new terminal and verify:

```powershell
tesseract --version
```

#### Ubuntu or Debian

```bash
sudo apt update
sudo apt install tesseract-ocr
tesseract --version
```

#### macOS with Homebrew

```bash
brew install tesseract
tesseract --version
```

The default OCR language is English (`eng`). Install additional Tesseract language
packs only when the project configuration is updated to use them.

### Poppler

`pdf2image` uses Poppler utilities to render PDF pages for OCR.

#### Windows

Install a Windows Poppler build, add its `bin` directory to `PATH`, reopen the
terminal, and verify:

```powershell
pdftoppm -v
```

#### Ubuntu or Debian

```bash
sudo apt install poppler-utils
pdftoppm -v
```

#### macOS with Homebrew

```bash
brew install poppler
pdftoppm -v
```

Native-text PDFs can be processed without invoking OCR, but a missing OCR system
dependency will prevent recovery of scanned reports.

## Required Folder Structure

The configured default structure is:

```text
AI-Annual-Report/
├── config/
│   └── settings.py
├── dashboard/
│   ├── app.py
│   └── pages/
├── data/
│   ├── dictionaries/
│   │   └── Innovation_Dictionary.xlsx
│   ├── metadata/
│   │   └── Company_Master.xlsx
│   ├── raw/
│   │   └── annual_reports/
│   └── validation/
│       └── Validation.xlsx
├── documentation/
├── logs/
├── outputs/
│   ├── excel/
│   ├── extracted_text/
│   └── reports/
├── scripts/
├── src/
├── tests/
└── tmp/
```

The application creates configured output and log directories when possible. The
input workbooks and annual report PDFs must be prepared by the user.

## Preparing Input Files

### 1. Company Master

Create `data/metadata/Company_Master.xlsx` with one row per company/report. The
recommended headers are:

| Company Name | Ticker | Industry | Report Year | Report Path | Source URL |
|---|---|---|---:|---|---|
| Tata Consultancy Services | TCS | Information Technology | 2024 | `data/raw/annual_reports/tcs_2024.pdf` | `https://example.com/reports/tcs-2024.pdf` |

Requirements:

- `Company Name`, `Ticker`, and `Industry` must be non-empty.
- `Report Year` must resolve to a year from 1900 through the next calendar year.
- `Report Path` must point to a readable `.pdf` when processing begins.
- `Source URL` must be a valid HTTP or HTTPS URL.
- A ticker/year pair should be unique.

Supported header aliases include `Company`, `Name`, `Symbol`, `Sector`, `Year`,
`Financial Year`, `PDF Path`, `File Path`, `URL`, and `Report URL`.

### 2. Innovation Dictionary

Create `data/dictionaries/Innovation_Dictionary.xlsx`:

| Category | Keyword | Rationale |
|---|---|---|
| Artificial Intelligence | artificial intelligence | Core AI disclosure |
| Artificial Intelligence | machine learning | AI technique |
| Innovation | research and development | Innovation investment |

`Category` and `Keyword` are required. Blank rows are ignored. Duplicate
normalized keywords within the same category are ignored with a log warning.

### 3. Annual Report PDFs

Copy reports to `data/raw/annual_reports/` or use another stable location listed
in the Company Master. Confirm that each file:

- has a `.pdf` extension;
- opens without a password;
- contains at least one page; and
- is not still downloading or synchronized as an online-only file.

### 4. Optional Validation Data

Manual validation is optional. The default file is
`data/validation/Validation.xlsx`. A long-form layout can use:

| company | keyword | manual_count |
|---|---|---:|
| Tata Consultancy Services | artificial intelligence | 18 |

A wide layout can place one company on each row and one keyword in each numeric
column. Manual counts must be finite, non-negative integers.

## Running the Pipeline

Run commands from the project root with the virtual environment active.

### Process All Records

```bash
python scripts/run_pipeline.py
```

or:

```bash
python scripts/run_pipeline.py --all
```

### Filter by Company

```bash
python scripts/run_pipeline.py --company TCS
```

The filter matches the ticker or company name case-insensitively.

### Filter by Year

```bash
python scripts/run_pipeline.py --year 2024
```

### Combine Company and Year

```bash
python scripts/run_pipeline.py --company TCS --year 2024
```

### Select an Output Directory

```bash
python scripts/run_pipeline.py --all --output output/
```

### Override Input Workbooks

```bash
python scripts/run_pipeline.py \
  --company-master data/metadata/Company_Master.xlsx \
  --dictionary data/dictionaries/Innovation_Dictionary.xlsx
```

On Windows PowerShell, place the command on one line or use the PowerShell
backtick continuation character instead of the Unix backslash.

### Verify Outputs

A successful report produces:

```text
outputs/excel/<ticker>_<year>_analysis.xlsx
outputs/extracted_text/<ticker>_<year>_extracted.txt
outputs/reports/<ticker>_<year>_report.md
```

Review `logs/ai_annual_report.log` for processing stages, OCR decisions, warnings,
and errors.

## Launching the Dashboard

Generate at least one Excel workbook before launching the dashboard:

```bash
streamlit run dashboard/app.py
```

Streamlit prints a local URL, normally `http://localhost:8501`. Open that URL in a
browser. The dashboard scans both `outputs/excel/` and `output/excel/`, caches
loaded workbooks using file modification signatures, and provides a **Refresh
data** button.

The dashboard does not process PDFs. If no workbooks appear, run the pipeline or
confirm that generated files are in one of the scanned Excel directories.

To use another port:

```bash
streamlit run dashboard/app.py --server.port 8502
```

## Running Tests

Run the full suite:

```bash
python -m pytest -q
```

Run a specific suite:

```bash
python -m pytest tests/test_pipeline.py -q
python -m pytest tests/test_keyword_analysis.py -q
```

Display detailed test names:

```bash
python -m pytest -v
```

Stop after the first failure:

```bash
python -m pytest -x
```

The new pipeline and keyword tests use temporary directories and mocks. They do
not require production PDFs or modify source datasets.

## Troubleshooting

### `No module named ...`

Confirm the virtual environment is active and install dependencies with the same
interpreter used to run the command:

```bash
python -m pip install -r requirements.txt
python -m pip --version
python --version
```

### `No module named openpyxl`

Install the Excel engine:

```bash
python -m pip install openpyxl
```

Without it, Excel reading and writing cannot complete.

### Company Master or Dictionary Is Empty

Zero-byte files are not valid Excel workbooks. Open each workbook in
Excel or LibreOffice, add the required headers and data, and save it as `.xlsx`.

### Company Master Missing a Required Column

Use the recommended headers or a supported alias. Remove merged header cells and
ensure the first row contains the column labels.

### PDF Does Not Exist

Check the resolved path in the error message. For relative paths, prefer paths
from the project root such as:

```text
data/raw/annual_reports/tcs_2024.pdf
```

On cloud-synchronized folders, ensure the PDF is downloaded locally.

### PDF Is Encrypted or Corrupted

Open the PDF manually. Obtain an unencrypted report from the official source and
replace the local file. The pipeline does not bypass PDF passwords.

### Tesseract Is Not Found

Run:

```bash
tesseract --version
```

If the command fails, install Tesseract or add its executable directory to
`PATH`, then restart the terminal.

### Poppler Is Not Found

Run:

```bash
pdftoppm -v
```

Install Poppler and ensure its binary directory is on `PATH`.

### OCR Is Slow

OCR processes rendered page images and is expected to be slower than native text
extraction. Confirm the PDF is genuinely scanned, process fewer reports per run,
use local SSD storage, and close memory-intensive applications.

### No Sections Are Detected

Inspect the normalized text output and heading styles. The pipeline logs a warning
and analyzes the full report when no target sections are found, so keyword results
can still be produced. Consider extending heading patterns only through a governed
source-code change and corresponding tests.

### Dashboard Shows No Data

1. Confirm at least one `.xlsx` workbook exists in `outputs/excel/` or
   `output/excel/`.
2. Confirm `openpyxl` is installed.
3. Expand **Load warnings** in the dashboard sidebar.
4. Select **Refresh data** after pipeline execution.
5. Check that the workbook contains the expected `Disclosure Scores`, `Category
   Counts`, `Section Summary`, and `Validation Ready` sheets.

### Log File Cannot Be Written

Confirm that the user running Python can create and write files in `logs/`. Avoid
installing or running the repository from a protected operating-system directory.

### Tests Are Not Discovered

Run pytest from the repository root:

```bash
python -m pytest tests -v
```

Confirm test filenames begin with `test_` and that pytest is installed in the
active environment.
