"""Simplified Tender Parameter Extraction Workflow with Individual Agents."""

from __future__ import annotations

import json
import os
import time
from asyncio import Queue, gather
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google.genai import Client, types
from logger import app_logger
from text_extraction_from_files import extract_documents_to_raw_text

load_dotenv()

# Schema field definitions
FIELD_GROUPS = {
    "project": [
        "tender_reference", "tender_title", "owner", "end_user", "sector",
        "location", "contract_type", "tender_value", "completion_period_days",
        "maintenance_period",
    ],
    "building": [
        "building_count", "usage", "length_m", "width_m", "height_m",
        "roof_slope", "frame_type", "bay_spacing_m", "intermediate_columns",
    ],
    "design": [
        "design_code", "wind_standard", "seismic_standard", "live_load_kn_m2",
        "collateral_load_kn_m2", "snow_load_kn_m2", "deflection_standard",
    ],
    "envelope": [
        "roof_type", "roof_thickness", "roof_profile", "roof_finish",
        "wall_profile", "wall_thickness", "wall_finish", "polycarbonate",
        "louvers", "bird_mesh",
    ],
    "accessories": [
        "canopy", "gutters", "downspouts", "roof_monitor", "wall_lights",
        "skylights", "cage_ladders", "roll_up_doors",
    ],
    "commercial": [
        "emd", "bid_validity_days", "pre_bid_date", "submission_deadline",
        "tender_authority",
    ],
    "internal": [
        "quote_number", "revision", "crm_code", "eto_type", "complexity_score",
    ],
}

METADATA_FIELDS = [
    "document_title", "document_type", "issuing_organization", "tender_number",
    "tender_id", "revision_number", "publication_date", "corrigendum_date",
    "number_of_pages", "ocr_errors_present", "drawings_referenced_unavailable",
    "boq_referenced_unavailable", "document_language", "currency",
]

# Dedicated agent prompts
AGENT_PROMPTS = {
    "document_metadata": """You are the document metadata agent.
Extract ONLY document metadata parameters explicitly present in the source text.
Return ONLY valid JSON: {"document_metadata": {<field>: {"value": "...", "extraction_status": "EXPLICIT"|"NOT_FOUND", ...}}}
Assigned fields: document_title, document_type, issuing_organization, tender_number, tender_id, revision_number, publication_date, corrigendum_date, number_of_pages, ocr_errors_present, drawings_referenced_unavailable, boq_referenced_unavailable, document_language, currency.""",

    "project": """You are the project parameters agent.
Extract ONLY project parameters explicitly present in the source text.
Return ONLY valid JSON: {"project": {<field>: {"value": "...", "extraction_status": "EXPLICIT"|"NOT_FOUND", ...}}}
Assigned fields: tender_reference, tender_title, owner, end_user, sector, location, contract_type, tender_value, completion_period_days, maintenance_period.""",

    "building": """You are the building parameters agent.
Extract ONLY building dimensions and layout parameters explicitly present in the source text.
Return ONLY valid JSON: {"building": {<field>: {"value": "...", "extraction_status": "EXPLICIT"|"NOT_FOUND", ...}}}
Assigned fields: building_count, usage, length_m, width_m, height_m, roof_slope, frame_type, bay_spacing_m, intermediate_columns.""",

    "design": """You are the design parameters agent.
Extract ONLY design codes and load specifications explicitly present in the source text.
Return ONLY valid JSON: {"design": {<field>: {"value": "...", "extraction_status": "EXPLICIT"|"NOT_FOUND", ...}}}
Assigned fields: design_code, wind_standard, seismic_standard, live_load_kn_m2, collateral_load_kn_m2, snow_load_kn_m2, deflection_standard.""",

    "envelope": """You are the building envelope agent.
Extract ONLY roof and wall cladding specifications explicitly present in the source text.
Return ONLY valid JSON: {"envelope": {<field>: {"value": "...", "extraction_status": "EXPLICIT"|"NOT_FOUND", ...}}}
Assigned fields: roof_type, roof_thickness, roof_profile, roof_finish, wall_profile, wall_thickness, wall_finish, polycarbonate, louvers, bird_mesh.""",

    "accessories": """You are the building accessories agent.
Extract ONLY accessory specifications explicitly present in the source text.
Return ONLY valid JSON: {"accessories": {<field>: {"value": "...", "extraction_status": "EXPLICIT"|"NOT_FOUND", ...}}}
Assigned fields: canopy, gutters, downspouts, roof_monitor, wall_lights, skylights, cage_ladders, roll_up_doors.""",

    "commercial": """You are the commercial parameters agent.
Extract ONLY commercial and bidding terms explicitly present in the source text.
Return ONLY valid JSON: {"commercial": {<field>: {"value": "...", "extraction_status": "EXPLICIT"|"NOT_FOUND", ...}}}
Assigned fields: emd, bid_validity_days, pre_bid_date, submission_deadline, tender_authority.""",

    "internal": """You are the internal parameters agent.
Extract ONLY internal reference parameters if explicitly present in the source text.
Return ONLY valid JSON: {"internal": {<field>: {"value": "...", "extraction_status": "EXPLICIT"|"NOT_FOUND", ...}}}
Assigned fields: quote_number, revision, crm_code, eto_type, complexity_score.""",
}


def _empty_field() -> dict[str, Any]:
    return {
        "value": "", "normalized_value": "", "unit": "", "source_reference": "",
        "reference_text": "", "page": "", "section": "", "confidence": "LOW",
        "extraction_status": "NOT_FOUND", "notes": "", "alternatives": [],
    }


def empty_result() -> dict[str, Any]:
    result: dict[str, Any] = {
        "document_metadata": {field: _empty_field() for field in METADATA_FIELDS},
        "extraction_summary": {"fields_found": 0, "fields_not_found": 0, "notes": ""},
        "unresolved_items": [], "conflicts": [], "calculation_log": [],
    }
    for group, fields in FIELD_GROUPS.items():
        result[group] = {field: _empty_field() for field in fields}
    return result


def parse_json_safely(text: str) -> dict[str, Any]:
    """Parse JSON string safely without exceptions."""
    if not text:
        return {}
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        cleaned = cleaned.rsplit("```", 1)[0].strip()
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(cleaned[start:end + 1])
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
    return {}


async def run_agent(agent_name: str, system_prompt: str, raw_text: str, event_queue: Queue = None) -> dict[str, Any]:
    """Execute an individual agent with its dedicated prompt and stream thinking/output."""
    started = time.perf_counter()
    app_logger.info("[agent:%s] Starting processing", agent_name)

    if event_queue:
        await event_queue.put({
            "agent": agent_name,
            "event": "started",
            "message": f"Analyzing {agent_name.replace('_', ' ')} parameters."
        })

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY environment variable is missing")

    client = Client(api_key=api_key)
    full_prompt = f"{system_prompt}\n\nSource Text:\n{raw_text}"

    try:
        stream = await client.aio.models.generate_content_stream(
            model=os.getenv("GEMINI_EXTRACTION_MODEL", "gemini-2.5-flash"),
            contents=full_prompt,
            config=types.GenerateContentConfig(
                responseMimeType="application/json",
                thinkingConfig=types.ThinkingConfig(includeThoughts=True),
            ),
        )

        output_text = ""
        async for chunk in stream:
            for candidate in getattr(chunk, "candidates", []) or []:
                content = getattr(candidate, "content", None)
                for part in getattr(content, "parts", []) or []:
                    text = getattr(part, "text", "") or ""
                    is_thought = bool(getattr(part, "thought", False))
                    if is_thought:
                        if text and event_queue:
                            await event_queue.put({"agent": agent_name, "event": "thinking", "message": text})
                    else:
                        output_text += text
                        if text and event_queue:
                            await event_queue.put({"agent": agent_name, "event": "output", "message": text})

        parsed = parse_json_safely(output_text)
        group_data = parsed.get(agent_name, {}) if isinstance(parsed, dict) else {}

        fields = METADATA_FIELDS if agent_name == "document_metadata" else FIELD_GROUPS.get(agent_name, [])
        found_count = sum(
            isinstance(group_data.get(f), dict) and group_data[f].get("extraction_status") not in {"NOT_FOUND", "NOT_APPLICABLE"}
            for f in fields
        )

        if event_queue:
            await event_queue.put({
                "agent": agent_name,
                "event": "completed",
                "message": f"Completed {agent_name} extraction.",
                "fields_found": found_count
            })

        app_logger.info("[agent:%s] Completed in %.2fs", agent_name, time.perf_counter() - started)
        return {agent_name: group_data}

    except Exception as exc:
        app_logger.exception("[agent:%s] Failed", agent_name)
        if event_queue:
            await event_queue.put({"agent": agent_name, "event": "failed", "message": str(exc)})
        return {agent_name: {}}


def merge_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge and normalize all agent results into the standardized response structure."""
    merged = empty_result()
    combined: dict[str, Any] = {}
    for item in results:
        combined.update(item)

    all_groups = ["document_metadata"] + list(FIELD_GROUPS.keys())
    for group in all_groups:
        group_data = combined.get(group, {})
        if isinstance(group_data, dict):
            for field in merged[group]:
                if isinstance(group_data.get(field), dict):
                    merged[group][field].update(group_data[field])

    fields_found = sum(
        field.get("extraction_status") not in {"NOT_FOUND", "NOT_APPLICABLE"}
        for group in all_groups
        for field in merged[group].values()
    )
    fields_not_found = sum(
        field.get("extraction_status") in {"NOT_FOUND", "NOT_APPLICABLE"}
        for group in all_groups
        for field in merged[group].values()
    )

    merged["extraction_summary"]["fields_found"] = fields_found
    merged["extraction_summary"]["fields_not_found"] = fields_not_found
    return merged


async def extract_tender_parameters(file_paths: list[Any], event_queue: Queue = None) -> dict[str, Any]:
    """1. Text extraction done FIRST using existing text extraction code.
       2. Send text to all agents in parallel.
       3. Merge and return final result."""
    if event_queue:
        await event_queue.put({"agent": "ingest", "event": "started", "message": "Reading and extracting text from documents."})

    # Step 1: Text extraction done FIRST
    raw_text, page_count = await extract_documents_to_raw_text(file_paths, Path("."))

    if event_queue:
        await event_queue.put({
            "agent": "ingest",
            "event": "completed",
            "message": f"Extracted {len(raw_text)} characters from {page_count} page(s)."
        })

    # Step 2: Send text to all agents in parallel
    tasks = [
        run_agent(agent_name, prompt, raw_text, event_queue)
        for agent_name, prompt in AGENT_PROMPTS.items()
    ]
    results = await gather(*tasks)

    # Step 3: Merge and normalize final response
    return merge_results(results)


async def extract_tender_text(raw_text: str) -> dict[str, Any]:
    """Run extraction directly on raw text."""
    tasks = [
        run_agent(agent_name, prompt, raw_text, None)
        for agent_name, prompt in AGENT_PROMPTS.items()
    ]
    results = await gather(*tasks)
    return merge_results(results)


if __name__ == "__main__":
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(description="Extract tender parameters from documents")
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(extract_tender_parameters([(f, "pdf") for f in args.files])), indent=2))
