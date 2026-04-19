"""
Offer Agent Backend — FastAPI server
====================================

Exposes the three MVP modules over HTTP so the front-screen + voice layer
can call them from a browser or phone.

Run locally:
    pip install fastapi uvicorn pypdf --break-system-packages
    python3 backend_server.py
    # or: uvicorn backend_server:app --host 0.0.0.0 --port 8000 --reload

Endpoints
---------
POST /api/fill              -> fill Form 400 PDF from offer JSON, return PDF bytes
POST /api/validate_closing  -> closing-date weekend/holiday check + alternatives
GET  /api/clients           -> list all clients
GET  /api/clients/search    -> fuzzy name search (?q=smith)
GET  /api/clients/{id}      -> get one client
POST /api/clients           -> create client
PUT  /api/clients/{id}      -> update client
DELETE /api/clients/{id}    -> delete client
GET  /health                -> liveness check

Serves the front-screen mockup at /   (AI_Front_Screen_Mockup.html)

CORS is wide open by default for MVP. Lock down before production.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

# Local modules
import sys
sys.path.insert(0, str(Path(__file__).parent))
from form_400_filler import fill_form_400
from closing_date_validator import validate_closing
from client_store import ClientStore


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

HERE = Path(__file__).parent
# Production layout: the blank Form 400 PDF sits next to this file.
# Dev fallback: look in ../uploads/ under the original upload filename.
DEFAULT_SOURCE_PDF = HERE / "Form_400_blank.pdf"
if not DEFAULT_SOURCE_PDF.exists():
    DEFAULT_SOURCE_PDF = HERE.parent / "uploads" / "Edible version.pdf"
DEFAULT_CLIENTS_DB = HERE / "clients.json"
DEFAULT_FRONT_SCREEN = HERE / "AI_Front_Screen_Mockup.html"
FILLED_DIR = HERE / "filled"
FILLED_DIR.mkdir(exist_ok=True)

SOURCE_PDF = Path(os.environ.get("FORM_400_SOURCE", str(DEFAULT_SOURCE_PDF)))
CLIENTS_DB = Path(os.environ.get("CLIENTS_DB", str(DEFAULT_CLIENTS_DB)))


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Estevan Offer Agent — Backend",
    version="0.1.0",
    description="HTTP layer on top of form_400_filler, closing_date_validator, client_store.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TIGHTEN before prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

store = ClientStore(CLIENTS_DB)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ClosingCheck(BaseModel):
    date: str = Field(..., description="ISO date, e.g. '2026-06-22'")


class ClientIn(BaseModel):
    name_line1: str
    name_line2: str = ""
    address_streetnum: str = ""
    address_street: str = ""
    address_unit: str = ""
    address_city: str = ""
    address_state: str = "Nova Scotia"
    address_zipcode: str = ""
    emails: list[str] = []
    phones: list[str] = []
    first_met: str = ""
    referral: str = ""


class ClientUpdate(BaseModel):
    name_line1: str | None = None
    name_line2: str | None = None
    address_streetnum: str | None = None
    address_street: str | None = None
    address_unit: str | None = None
    address_city: str | None = None
    address_state: str | None = None
    address_zipcode: str | None = None
    emails: list[str] | None = None
    phones: list[str] | None = None
    first_met: str | None = None
    referral: str | None = None


# ---------------------------------------------------------------------------
# Routes — health + front screen
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "source_pdf_exists": SOURCE_PDF.exists(),
        "clients_db_path": str(CLIENTS_DB),
        "client_count": len(store.list()),
    }


@app.get("/", response_class=HTMLResponse)
def front_screen() -> HTMLResponse:
    """Serve the front-screen mockup at the root."""
    if DEFAULT_FRONT_SCREEN.exists():
        return HTMLResponse(DEFAULT_FRONT_SCREEN.read_text())
    return HTMLResponse(
        "<h1>Offer Agent backend running</h1>"
        "<p>Front screen file not found. Visit /docs for the API.</p>"
    )


# ---------------------------------------------------------------------------
# Routes — fill Form 400
# ---------------------------------------------------------------------------

@app.post("/api/fill")
def fill(offer: dict[str, Any]) -> FileResponse:
    """
    Fill Form 400 from the offer JSON produced by the voice conversation.

    Request body: the JSON matching System_Prompt_Offer_Agent.md.
    Response:     the filled PDF as an attachment.
    """
    if not SOURCE_PDF.exists():
        raise HTTPException(
            status_code=500,
            detail=f"Source PDF not found at {SOURCE_PDF}. Set FORM_400_SOURCE env var.",
        )

    # Pick a file name based on buyer last name + MLS # if present
    buyer_line = (offer.get("buyers") or {}).get("names_line1", "offer")
    mls = offer.get("mls_number", "")
    safe = "_".join(
        w for w in buyer_line.replace(",", " ").split()
        if w.isalnum()
    ) or "offer"
    name = f"Form400_{safe}"
    if mls:
        name += f"_MLS{mls}"
    name += ".pdf"
    out_path = FILLED_DIR / name

    try:
        fill_form_400(offer, str(SOURCE_PDF), str(out_path))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fill failed: {e!r}")

    return FileResponse(
        out_path,
        media_type="application/pdf",
        filename=name,
    )


@app.post("/api/preview")
def preview(offer: dict[str, Any]) -> JSONResponse:
    """
    Same as /fill but returns a URL to preview the filled PDF instead of the
    bytes. Useful when the client wants to show it in an <iframe>.
    """
    resp = fill(offer)
    # FileResponse.path is set internally; retrieve it
    filename = Path(resp.path).name
    return JSONResponse({
        "filename": filename,
        "url": f"/filled/{filename}",
    })


@app.get("/filled/{filename}")
def download_filled(filename: str) -> FileResponse:
    path = FILLED_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Filled PDF not found")
    return FileResponse(path, media_type="application/pdf", filename=filename)


# ---------------------------------------------------------------------------
# Routes — closing-date validation
# ---------------------------------------------------------------------------

@app.post("/api/validate_closing")
def validate_closing_endpoint(body: ClosingCheck) -> dict:
    try:
        d = date.fromisoformat(body.date)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid date '{body.date}'. Use ISO format YYYY-MM-DD.",
        )
    return validate_closing(d)


# ---------------------------------------------------------------------------
# Routes — client store
# ---------------------------------------------------------------------------

@app.get("/api/clients")
def clients_list() -> list[dict]:
    return store.list()


@app.get("/api/clients/search")
def clients_search(q: str = Query(..., min_length=1)) -> list[dict]:
    return store.find(q)


@app.get("/api/clients/{client_id}")
def clients_get(client_id: str) -> dict:
    c = store.get(client_id)
    if not c:
        raise HTTPException(status_code=404, detail="Client not found")
    return c


@app.post("/api/clients")
def clients_add(body: ClientIn) -> dict:
    return store.add(body.model_dump())


@app.put("/api/clients/{client_id}")
def clients_update(client_id: str, body: ClientUpdate) -> dict:
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    updated = store.update(client_id, fields)
    if not updated:
        raise HTTPException(status_code=404, detail="Client not found")
    return updated


@app.delete("/api/clients/{client_id}")
def clients_delete(client_id: str) -> dict:
    ok = store.delete(client_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Client not found")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend_server:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
        reload=bool(os.environ.get("RELOAD")),
    )
