# Tender Extractor AI 🚀

An agentic AI-powered document intelligence system designed for automated parameter extraction, cross-referencing, and reporting from complex technical and commercial tender documents (PEB / Structural Engineering focus).

---

## 🌟 Key Features

- **🤖 Multi-Agent Processing Architecture**: Runs parallel specialized AI agents (using Google Gemini 2.5 Flash) dedicated to specific domains:
  - **Document Metadata**: Ref numbers, dates, titles, client info.
  - **Project Scope**: Covered area, dimensions, spans, location.
  - **Structural Steel**: Primary/secondary steel specs, material grades.
  - **Design Parameters**: Load specifications, design codes, deflection limits, seismic/wind zones.
  - **Building Envelope**: Roof & wall cladding profiles, insulation, thickness.
  - **Accessories**: Gutters, downspouts, louvers, ridge monitors, dock levelers.
  - **Commercial Terms**: Payment schedules, EMD, validity, penalty clauses, bank guarantees.
  - **Quality & Safety**: EHS standards, ISO certifications, QAP hold points.
- **📡 Live Agent Execution Terminal (SSE)**: Real-time streaming of agent thinking logs and progress updates via Server-Sent Events (SSE).
- **📄 Multi-Format Ingestion Engine**:
  - **PDF Documents**: Native text extraction + PyMuPDF / pdfplumber table parsing + AI Vision fallback OCR for scanned pages.
  - **Word Documents (`.doc`, `.docx`)**: Auto-converted via LibreOffice / python-docx.
  - **Spreadsheets (`.xls`, `.xlsx`, `.csv`)**: Structural table parsing.
  - **Images (`.png`, `.jpg`, `.tiff`)**: High-accuracy vision OCR.
- **📊 Interactive Output Matrix**:
  - Summary metrics (Found, Inferred, Missing parameters).
  - Search and filter by parameter name, category, or values.
  - Accordion & matrix view modes.
- **📥 One-Click Export Engine**:
  - **PDF Technical Report**: Branded PDF generation using ReportLab with headers, footers, page numbers, and custom styled tables.
  - **CSV Matrix Export**: Clean formatted spreadsheet output.

---

## 🏗️ Project Architecture & Tech Stack

```text
├── api.py                      # FastAPI web server, SSE endpoints & route handlers
├── tender_extraction_workflow.py # Parallel agent execution logic & Gemini streaming integration
├── text_extraction_from_files.py # Document parsing pipeline (PDF, DOCX, XLSX, Images, OCR)
├── export_generator.py         # ReportLab PDF & CSV generation engine
├── logger.py                   # Rotating file logger setup
├── text.html                   # Upload frontend UI
├── extractor.html              # Live streaming agent terminal UI
├── results.html                # Extracted parameter matrix UI
└── requirements.txt            # Python dependencies
```

- **Backend Framework**: Python 3.11+, FastAPI, Uvicorn
- **AI / LLM Orchestration**: Google GenAI SDK (`google-genai`), Gemini 2.5 Flash with Thinking Mode
- **Document Processing**: PyMuPDF (`fitz`), `pdfplumber`, `python-docx`, `pandas`, `openpyxl`, `Pillow`
- **PDF Generation**: `reportlab`
- **Frontend**: Pure HTML5 / Modern CSS / Vanilla JavaScript (ES6+), Server-Sent Events, IndexedDB client storage

---

## ⚙️ Prerequisites

1. **Python**: Python 3.11 or higher installed.
2. **Google Gemini API Key**: API Key with access to `gemini-2.5-flash`.
3. **LibreOffice** *(Optional, required only for legacy `.doc` word document conversion to PDF)*.

---

## 🛠️ Setup & Installation

1. **Clone the repository**:

   ```bash
   git clone <repository-url>
   cd "PIS Agentic"
   ```
2. **Create and activate a Virtual Environment**:

   - **Windows (PowerShell)**:
     ```powershell
     python -m venv venv
     .\venv\Scripts\Activate.ps1
     ```
   - **Linux / macOS**:
     ```bash
     python3 -m venv venv
     source venv/bin/activate
     ```
3. **Install Dependencies**:

   ```bash
   pip install -r requirements.txt
   ```
4. **Environment Configuration**:
   Create a `.env` file in the project root directory with the following variables:

   ```env
   GEMINI_API_KEY=your_google_gemini_api_key_here
   GEMINI_EXTRACTION_MODEL=gemini-2.5-flash
   # LIBREOFFICE_PATH=C:\Program Files\LibreOffice\program\soffice.exe  # (Optional)
   ```

---

## 🚀 How to Run Frontend & Backend

### Option 1: Combined Execution (Recommended)

Since FastAPI serves the HTML pages directly, starting the backend server will automatically run both the frontend and backend on port `8800`:

```bash
uvicorn api:app --reload --host 0.0.0.0 --port 8800
```

Once started, open your web browser and navigate to:
👉 **[http://localhost:8800](http://localhost:8800)**

---

### Option 2: Running Backend & Standalone Frontend Separately

1. **Start the Backend API Server**:

   ```bash
   uvicorn api:app --reload --port 8800
   ```
2. **Serve / Open Frontend**:

   - **Via Python HTTP Server**:
     ```bash
     python -m http.server 8000
     ```

     Access at **[http://localhost:8000/text.html](http://localhost:8000/text.html)**
   - **Or Open Directly**: Open `text.html` in any web browser. The frontend automatically targets the API at `http://127.0.0.1:8800`.

---

## 📑 Application Workflow

1. **Upload Documents (`text.html`)**: Drag & drop PDF, Word, Excel, CSV, or scanned image files.
2. **Live Agent Execution (`extractor.html`)**: View live agent thinking terminals as parallel specialized agents parse and extract parameters in real time over Server-Sent Events.
3. **Parameter Matrix & Export (`results.html`)**: Review structured findings, search/filter fields, and download formatted PDF or CSV reports.

---

## 🔌 API Endpoints Summary

| Endpoint             | Method   | Description                                                        |
| :------------------- | :------- | :----------------------------------------------------------------- |
| `/`                | `GET`  | Serves the document upload page (`text.html`)                    |
| `/{filename}.html` | `GET`  | Serves frontend sub-pages (`extractor.html`, `results.html`)   |
| `/extract`         | `POST` | Uploads files and performs full parameter extraction (JSON output) |
| `/extract/stream`  | `POST` | Uploads files and streams real-time SSE agent events               |
| `/download/pdf`    | `POST` | Accepts extraction JSON payload and returns formatted PDF report   |
| `/download/csv`    | `POST` | Accepts extraction JSON payload and returns CSV export             |
