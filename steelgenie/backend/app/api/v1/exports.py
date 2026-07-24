"""
API router for downloading estimations in KISS and Tekla EPM file formats.
"""
from __future__ import annotations

import csv
import io
import logging
from uuid import UUID
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse

from app.core.tenancy import AuthUser
from app.services.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/exports", tags=["exports"])


def _generate_kiss_content(project_name: str, items: list[dict]) -> str:
    lines = [
        "*KISS",
        "*HEADING",
        f"PROJECT NAME: {project_name}",
        "*MEMBER",
    ]
    for item in items:
        piecemark = item.get("piecemark", "UNK")
        category = (item.get("category") or "BEAM").upper()

        # Simple structural kind classification
        if "COLUMN" in category:
            cat = "COLUMN"
        elif "BRACE" in category:
            cat = "BRACE"
        else:
            cat = "BEAM"

        section = item.get("section", "UNK")
        grade = item.get("grade", "A992")
        length_in = item.get("length_in") or 0.0
        qty = item.get("qty", 1)

        lines.append(f"{piecemark},{cat},{section},{grade},{length_in},{qty}")

    lines.append("*MATERIAL")
    lines.append("*PLATE")
    lines.append("*BOLT")
    lines.append("*WELD")
    return "\n".join(lines)


def _generate_epm_csv_content(items: list[dict]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["SHAPE", "SIZE", "LENGTH", "QTY", "GRADE", "PIECEMARK", "CATEGORY"])
    for item in items:
        section = item.get("section", "")
        # Extract shape prefix (W, C, L, HSS etc.)
        shape = "W"
        if section:
            import re
            m = re.match(r"^([A-Z]+)", section.upper())
            if m:
                shape = m.group(1)
        writer.writerow([
            shape,
            section,
            item.get("length_in", 0),
            item.get("qty", 1),
            item.get("grade", "A992"),
            item.get("piecemark", ""),
            item.get("category", "")
        ])
    return output.getvalue()


@router.get("/projects/{project_id}/kiss")
async def export_kiss(project_id: UUID, user: AuthUser):
    """Export the project Bill of Materials in standard fabrication KISS format."""
    db = get_db()

    # Get project name
    p_resp = db.table("projects").select("name").eq("id", str(project_id)).maybe_single().execute()
    if not p_resp or not p_resp.data:
        raise HTTPException(status_code=404, detail="Project not found")

    project_name = p_resp.data.get("name", "Project")

    # Get BOM items
    bom_resp = db.table("bom_items").select("*").eq("project_id", str(project_id)).execute()
    items = bom_resp.data or []

    kiss_content = _generate_kiss_content(project_name, items)

    return Response(
        content=kiss_content,
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="bom_{project_id}.kss"'}
    )


@router.get("/projects/{project_id}/epm")
async def export_epm(project_id: UUID, user: AuthUser):
    """Export the project Bill of Materials in Tekla EPM compatible spreadsheet format."""
    db = get_db()

    # Get BOM items
    bom_resp = db.table("bom_items").select("*").eq("project_id", str(project_id)).execute()
    items = bom_resp.data or []

    epm_csv = _generate_epm_csv_content(items)

    return Response(
        content=epm_csv,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="epm_{project_id}.csv"'}
    )
