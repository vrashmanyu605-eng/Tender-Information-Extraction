import gc
import re
import os
import io
import json
import shutil
import asyncio
import requests
import tempfile
import pdfplumber
import subprocess
import pandas as pd
from PIL import Image
try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from openpyxl import load_workbook
from logger import logger
from google.genai import Client, types
from docx import Document as DocxDocument
from litellm import completion_cost

# Prevent tokenizer parallelism issues
os.environ["TOKENIZERS_PARALLELISM"] = "false"

load_dotenv()

_models_lock = asyncio.Lock()
_models_initialized = False
VISION_MODEL = None

async def initialize_models():
    """Initialize AI models once per process with thread safety"""
    
    global VISION_MODEL, _models_initialized

    async with _models_lock:
        if _models_initialized:
            return
        try:
            GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
            client = Client(api_key=GEMINI_API_KEY)
            VISION_MODEL = client
            _models_initialized = True
            logger.info("✅ AI Vision model initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize models: {e}")
            raise

def find_libreoffice() -> str:
    path = os.getenv("LIBREOFFICE_PATH")
    if not path:
        # Default for Windows if not set
        common_paths = [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"
        ]
        for p in common_paths:
            if Path(p).exists():
                return p
        raise RuntimeError("LIBREOFFICE_PATH not set and not found in common locations")
    if not Path(path).exists():
        raise RuntimeError(f"LibreOffice not found at: {path}")
    return path

def convert_to_pdf(file_path: Path) -> Path:
    if not file_path.exists():
        raise FileNotFoundError(file_path)
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        return file_path
    if suffix not in [".doc", ".docx"]:
        raise ValueError(f"Unsupported file type: {suffix}")
    soffice = find_libreoffice()
    temp_dir = Path(tempfile.mkdtemp(prefix="doc_convert_"))
    try:
        cmd = [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(temp_dir), str(file_path)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(result.stderr)
        pdf_path = temp_dir / (file_path.stem + ".pdf")
        if not pdf_path.exists():
            raise RuntimeError("LibreOffice did not generate PDF.")
        return pdf_path
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise RuntimeError(f"LibreOffice conversion failed: {e}")

def is_cid_garbage(text: str) -> bool:
    cid_hits = len(re.findall(r"\(cid:\d+\)", text))
    total_tokens = len(text.split())
    if total_tokens == 0:
        return True
    return (cid_hits / max(total_tokens, 1)) > 0.2

def are_tables_garbage(tables: list) -> bool:
    if not tables:
        return False
    all_cell_text = []
    for table in tables:
        all_cell_text.extend(table.get("headers", []))
        for row in table.get("rows", []):
            all_cell_text.extend(row if isinstance(row, list) else [row])
    combined = " ".join(str(c) for c in all_cell_text)
    return is_cid_garbage(combined)

def is_usable_text(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 100:
        return False
    if is_cid_garbage(stripped):
        return False
    return True

def extract_with_fitz(pdf_path: str, page_index: int) -> str:
    if fitz is None:
        return ""
    with fitz.open(pdf_path) as doc:
        page = doc.load_page(page_index)
        return page.get_text().strip()
    
def extract_with_pdfplumber(pdf_path: str, page_index: int):
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_index]

        text = page.extract_text() or ""

        tables = page.extract_tables({
            "vertical_strategy": "lines",
            "horizontal_strategy": "lines"
        })

        if not tables:
            tables = page.extract_tables({
                "vertical_strategy": "text",
                "horizontal_strategy": "text",
                "snap_tolerance": 3,
                "join_tolerance": 3
            })

        cleaned_tables = []
        for table in tables or []:

            cleaned_rows = [
                [(cell or "").replace("\n", " ").strip() for cell in row]
                for row in table
                if row  # skip empty rows
            ]
            
            if cleaned_rows:
                cleaned_tables.append({
                    "title": f"Page {page_index + 1} Table",
                    "headers": cleaned_rows[0],
                    "rows": cleaned_rows[1:]
                })

        return text, cleaned_tables
    
def get_page_image(pdf_path: str, page_index: int):
    if fitz is None:
        raise RuntimeError("PyMuPDF is unavailable for image-based PDF OCR")
    with fitz.open(pdf_path) as doc:
        page = doc.load_page(page_index)
        pix = page.get_pixmap(dpi=150)
        return Image.open(io.BytesIO(pix.tobytes("png")))

async def extract_text_from_image(file_path_with_page: tuple[Path, int], semaphore: asyncio.Semaphore, filename: str = "N/A", token_usage: dict = None) -> tuple[int, str]:
    async with semaphore:
        await initialize_models()
        file_path, page_index = file_path_with_page
        
        # We assume the file_path is already a PDF if called from the pdf section
        # or it's been converted. For safety, we keep it, but it should be fast for PDFs.
        pdf_path = convert_to_pdf(file_path)
        
        combined_output = {"text_lines": [], "tables": []}
        
        try:
            fitz_text = await asyncio.to_thread(extract_with_fitz, pdf_path, page_index)
            
            # If fitz gives us usable text, we use it
            if fitz_text and is_usable_text(fitz_text):
                combined_output["text_lines"].append(fitz_text)
            
            # Use pdfplumber for tables or if fitz fails/gives garbage
            if not combined_output["text_lines"] or is_cid_garbage(fitz_text):

                plumber_text, plumber_tables = await asyncio.to_thread(extract_with_pdfplumber, file_path, page_index)
                
                if plumber_text.strip():
                    combined_output["text_lines"].append(plumber_text.strip())
                if plumber_tables:
                    combined_output["tables"].extend(plumber_tables)

        except Exception as e:
            logger.warning(f"Text/Table extraction failed on page {page_index+1}: {e}")

        joined_text = " ".join(combined_output["text_lines"]).strip()
        
        # Cleanup garbage
        if is_cid_garbage(joined_text):
            combined_output["text_lines"] = []
            joined_text = ""
        if are_tables_garbage(combined_output["tables"]):
            combined_output["tables"] = []

        # Vision fallback if still no usable text
        if not combined_output["tables"] and not is_usable_text(joined_text):
            img = None
            try:
                img = await asyncio.to_thread(get_page_image, pdf_path, page_index)
                vision_prompt = "Extract ALL visible text exactly. Do NOT summarize. Preserve numbers. Return plain text only."
                
                # Gemini call is already async-friendly if using the right client, 
                # but generate_content is blocking in this SDK version (sync client).
                # Actually, Client is sync, but we can wrap it.
                def call_vision():
                    return VISION_MODEL.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=[vision_prompt, img],
                        config=types.GenerateContentConfig(
                            http_options=types.HttpOptions(
                                timeout=36000
                            )
                        )
                    )
                
                response = await asyncio.to_thread(call_vision)

                if response and token_usage is not None:
                    usage = getattr(response, "usage_metadata", None)
                    if usage:
                        in_tok = getattr(usage, "prompt_token_count", 0) or 0
                        out_tok = getattr(usage, "candidates_token_count", 0) or 0
                        tot_tok = getattr(usage, "total_token_count", 0) or 0
                        
                        token_usage["input_tokens"] = token_usage.get("input_tokens", 0) + in_tok
                        token_usage["output_tokens"] = token_usage.get("output_tokens", 0) + out_tok
                        token_usage["total_tokens"] = token_usage.get("total_tokens", 0) + tot_tok
                        token_usage["resasoning_tokens"] = token_usage.get("resasoning_tokens", 0)

                        cost = (in_tok / 1000000.0) * 0.075 + (out_tok / 1000000.0) * 0.30
                        token_usage["cost"] = token_usage.get("cost", 0.0) + float(cost)

                if response and response.text:
                    combined_output["text_lines"].append(response.text.strip())
            except RuntimeError as e:
                logger.error(f"MuPDF image extraction failed on page {page_index+1} for {pdf_path.name}: {e}")
            except Exception as e:
                logger.error(f"Vision fallback failed on page {page_index+1} for {pdf_path.name}: {e}")
            finally:
                if img:
                    img.close()
                gc.collect()
        
        return page_index, json.dumps(combined_output)

async def extract_text_from_image_file(image_path: Path, semaphore: asyncio.Semaphore, filename: str = "N/A", token_usage: dict = None) -> str:
    async with semaphore:
        await initialize_models()
        try:
            img = Image.open(image_path)
            vision_prompt = "Extract ALL visible text exactly as it appears. Do NOT summarize. Preserve all numbers and technical terms. Return plain text only."
            def call_vision():
                return VISION_MODEL.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[vision_prompt, img],
                    config=types.GenerateContentConfig(
                        http_options=types.HttpOptions(
                            timeout=36000
                        )
                    )
                )
            response = await asyncio.to_thread(call_vision)
            img.close()
            gc.collect()

            if response and token_usage is not None:
                usage = getattr(response, "usage_metadata", None)
                if usage:
                    in_tok = getattr(usage, "prompt_token_count", 0) or 0
                    out_tok = getattr(usage, "candidates_token_count", 0) or 0
                    tot_tok = getattr(usage, "total_token_count", 0) or 0
                    
                    token_usage["input_tokens"] = token_usage.get("input_tokens", 0) + in_tok
                    token_usage["output_tokens"] = token_usage.get("output_tokens", 0) + out_tok
                    token_usage["total_tokens"] = token_usage.get("total_tokens", 0) + tot_tok
                    token_usage["resasoning_tokens"] = token_usage.get("resasoning_tokens", 0)

                    cost = (in_tok / 1000000.0) * 0.075 + (out_tok / 1000000.0) * 0.30
                    token_usage["cost"] = token_usage.get("cost", 0.0) + float(cost)

            if response and response.text:
                return response.text.strip()
            return ""
        except Exception as e:
            logger.error(f"Image extraction failed for {image_path.name}: {e}")
            return ""

async def convert_xls_to_xlsx(xls_path: str, filename: str = "N/A") -> str:
    try:
        xls_data = pd.read_excel(xls_path, sheet_name=None)
        xlsx_path = xls_path.rsplit('.', 1)[0] + '.xlsx'
        with pd.ExcelWriter(xlsx_path, engine='openpyxl') as writer:
            for sheet_name, df in xls_data.items():
                df.to_excel(writer, sheet_name=sheet_name, index=False)
        return xlsx_path
    except Exception as e:
        logger.error(f"XLS conversion failed: {e}", file_name=filename)
        raise

async def extract_excel_content(excel_path: str, filename: str = "N/A") -> str:
    wb = load_workbook(excel_path, read_only=True)
    sheet_names = wb.sheetnames
    wb.close()
    content_with_sheets = []
    for sheet_name in sheet_names:
        df = pd.read_excel(excel_path, sheet_name=sheet_name)
        if df.empty: continue
        lines = [" | ".join(str(c) for c in df.columns), "-" * 80]
        for _, row in df.iterrows():
            if row.isna().all(): continue
            row_text = " | ".join(str(v) for v in row if pd.notna(v) and str(v).strip())
            lines.append(row_text)
        sheet_text = "\n".join(lines)
        if sheet_text.strip():
            content_with_sheets.append(f"--- {sheet_name} ---\n{sheet_text}")
    return "\n\n".join(content_with_sheets)

async def extract_documents_to_raw_text(file_paths: list[tuple[Path, str]], processed_dir: Path, filename: str = "N/A", token_usage: dict = None) -> tuple[str, int]:
    all_raw_texts = []
    total_pdf_pages = 0
    try:
        for path, ftype in file_paths:
            if ftype == 'document':
                try:
                    doc = DocxDocument(path)
                    doc_text = "\n".join([p.text for p in doc.paragraphs])
                    if doc_text.strip():
                        all_raw_texts.append(doc_text)
                    logger.info(f"✅ Extracted text from Word document: {path.name}")
                except Exception as e:
                    logger.error(f"❌ Word extraction failed for {path.name}: {e}")
            
            elif ftype == 'pdf':
                if fitz is not None:
                    with fitz.open(path) as doc:
                        num_pages = len(doc)
                else:
                    with pdfplumber.open(path) as doc:
                        num_pages = len(doc.pages)
                    total_pdf_pages += num_pages
                    semaphore = asyncio.Semaphore(5)
                    tasks = [extract_text_from_image((path, i), semaphore, filename, token_usage=token_usage) for i in range(num_pages)]
                    page_results = await asyncio.gather(*tasks)
                    page_results.sort(key=lambda x: x[0])
                    texts = [text for _, text in page_results]
                    all_raw_texts.append("\n\n".join(texts))
            elif ftype == 'excel':
                excel_path_str = str(path)
                if path.suffix.lower() == '.xls':
                    excel_path_str = await convert_xls_to_xlsx(excel_path_str)
                excel_text = await extract_excel_content(excel_path_str)
                if excel_text.strip():
                    all_raw_texts.append(excel_text)
            elif ftype == 'csv':
                df = pd.read_csv(str(path))
                csv_text = df.to_string()
                if csv_text.strip():
                    all_raw_texts.append(csv_text)
            elif ftype == 'image':
                semaphore = asyncio.Semaphore(3)
                text = await extract_text_from_image_file(path, semaphore, filename, token_usage=token_usage)
                if text.strip():
                    all_raw_texts.append(text)
        
        full_raw_text = "\n\n".join(all_raw_texts)
        return full_raw_text, total_pdf_pages
    except Exception as e:
        logger.error(f"Extraction error: {e}")
        return "", 0
    finally:
        gc.collect()
