from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from asyncio import Queue
from pathlib import Path

from fastapi import Body, FastAPI, File, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from export_generator import generate_csv_report, generate_pdf_report
from tender_extraction_workflow import extract_tender_parameters

app = FastAPI(title="Tender Parameter Extraction API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def frontend() -> FileResponse:
    return FileResponse(Path(__file__).with_name("text.html"))


@app.get("/image.png")
@app.get("/favicon.ico")
async def get_logo() -> FileResponse:
    logo_path = Path(__file__).with_name("image.png")
    if not logo_path.exists():
        raise HTTPException(status_code=404, detail="Logo not found")
    return FileResponse(logo_path, media_type="image/png")


@app.get("/{filename}.html")
async def serve_html(filename: str) -> FileResponse:
    html_path = Path(__file__).with_name(f"{filename}.html")
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="Page not found")
    return FileResponse(html_path, media_type="text/html")


@app.post("/download/pdf")
async def download_pdf(data: dict = Body(...)) -> Response:
    """Generate and return a beautifully formatted PDF report with logo, headers, and tables."""
    try:
        pdf_bytes = generate_pdf_report(data)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": "attachment; filename=Tender_Extraction_Report.pdf"
            },
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {str(exc)}") from exc


@app.post("/download/csv")
async def download_csv(data: dict = Body(...)) -> Response:
    """Generate and return a cleanly formatted CSV export with headers."""
    try:
        csv_content = generate_csv_report(data)
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=Tender_Extraction_Report.csv"
            },
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"CSV generation failed: {str(exc)}") from exc


@app.post("/extract")
async def extract(files: list[UploadFile] = File(...)) -> dict:
    """Extract tender parameters from one or more PDF, Excel, or image files."""
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required")

    allowed_extensions = {
        ".pdf", ".xls", ".xlsx", ".xlsm", ".csv", ".doc", ".docx",
        ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp",
    }
    invalid = [file.filename or "unnamed file" for file in files
               if Path(file.filename or "").suffix.lower() not in allowed_extensions]
    if invalid:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {', '.join(invalid)}")

    file_types = {
        ".pdf": "pdf", ".xls": "excel", ".xlsx": "excel", ".xlsm": "excel",
        ".csv": "csv", ".doc": "document", ".docx": "document",
        ".png": "image", ".jpg": "image", ".jpeg": "image", ".tif": "image",
        ".tiff": "image", ".bmp": "image", ".webp": "image",
    }

    with tempfile.TemporaryDirectory(prefix="tender_upload_") as temp_dir:
        paths = []
        for index, upload in enumerate(files):
            suffix = Path(upload.filename or "").suffix.lower()
            destination = Path(temp_dir) / f"upload_{index}{suffix}"
            with destination.open("wb") as output:
                shutil.copyfileobj(upload.file, output)
            paths.append((destination, file_types[suffix]))

        try:
            return await extract_tender_parameters(paths)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        finally:
            for upload in files:
                await upload.close()


@app.post("/extract/stream")
async def extract_stream(files: list[UploadFile] = File(...)) -> StreamingResponse:
    """Stream live agent progress and final extraction as Server-Sent Events."""
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required")
    allowed_extensions = {
        ".pdf", ".xls", ".xlsx", ".xlsm", ".csv", ".doc", ".docx",
        ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp",
    }
    invalid = [file.filename or "unnamed file" for file in files
               if Path(file.filename or "").suffix.lower() not in allowed_extensions]
    if invalid:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {', '.join(invalid)}")

    temp_dir = Path(tempfile.mkdtemp(prefix="tender_stream_"))
    paths = []
    file_types = {
        ".pdf": "pdf", ".xls": "excel", ".xlsx": "excel", ".xlsm": "excel",
        ".csv": "csv", ".doc": "document", ".docx": "document",
        ".png": "image", ".jpg": "image", ".jpeg": "image", ".tif": "image",
        ".tiff": "image", ".bmp": "image", ".webp": "image",
    }
    try:
        for index, upload in enumerate(files):
            suffix = Path(upload.filename or "").suffix.lower()
            destination = temp_dir / f"upload_{index}{suffix}"
            with destination.open("wb") as output:
                shutil.copyfileobj(upload.file, output)
            paths.append((destination, file_types[suffix]))
    finally:
        for upload in files:
            await upload.close()

    async def events():
        queue: Queue = Queue()
        task = asyncio.create_task(extract_tender_parameters(paths, queue))
        try:
            while not task.done() or not queue.empty():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.1)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    continue
            result = await task
            yield f"data: {json.dumps({'agent': 'workflow', 'event': 'complete', 'message': 'Extraction complete.', 'extraction': result})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'agent': 'workflow', 'event': 'failed', 'message': str(exc)})}\n\n"
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


if __name__ == "__main__":
    import os
    import uvicorn

    port = int(os.environ.get("PORT", 8800))
    uvicorn.run("api:app", host="0.0.0.0", port=port, reload=True)

