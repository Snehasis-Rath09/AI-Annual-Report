# AI Annual Report Disclosure Analysis Dashboard

An end-to-end Python application for analyzing **AI and Innovation disclosures** in annual reports of Indian listed companies. The project extracts information from PDF reports, applies a transparent rule-based scoring methodology, generates structured Excel reports, and visualizes insights through an interactive Streamlit dashboard.

## Live Demo

https://ai-annual-report-disclosure.streamlit.app/

## Key Features

- Automated PDF text extraction and preprocessing
- AI & Innovation keyword detection
- Transparent disclosure scoring
- Excel report generation
- Interactive Streamlit dashboard
- Company-wise analysis and comparison
- Validation-ready outputs

## Technology Stack

- Python
- Streamlit
- Pandas
- Plotly
- PyMuPDF
- OpenPyXL
- Git & GitHub

## Project Structure

```text
AI-Annual-Report/
├── config/
├── dashboard/
├── data/
├── documentation/
├── outputs/
├── scripts/
├── src/
├── tests/
├── requirements.txt
└── README.md
```

## Installation

Clone the repository and navigate to the project folder.

```bash
git clone <GitHub Repository URL>
cd AI-Annual-Report
```

Create and activate a virtual environment.

**Windows**

```bash
python -m venv .venv
.venv\Scripts\activate
```

**Linux/macOS**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install the required dependencies.

```bash
pip install -r requirements.txt
```

## Usage

Run the complete analysis pipeline.

```bash
python scripts/run_pipeline.py
```

Launch the Streamlit dashboard.

```bash
streamlit run dashboard/app.py
```

Open the dashboard locally:

```text
http://localhost:8501
```

Or use the deployed application:

https://ai-annual-report-disclosure.streamlit.app/

## Output

The pipeline generates:

- Excel analysis workbooks
- Extracted text files
- Markdown reports
- Interactive dashboard visualizations

## Future Scope

- NLP-based semantic analysis
- Machine Learning-based disclosure scoring
- Multi-year trend analysis
- Support for additional companies
- Cloud integration

## Author

Developed as an internship project on AI-based Annual Report Disclosure Analysis using Python and Streamlit.