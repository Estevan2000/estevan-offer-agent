"""
Form 400 PDF Filler — v1 (packaged from v10 fill logic)
=======================================================

Single entry point:

    fill_form_400(offer_json: dict, source_pdf: str, output_path: str) -> str

Takes the JSON produced by the voice agent (schema documented in
System_Prompt_Offer_Agent.md) and writes a filled NSAR Form 400 PDF to
output_path. Returns output_path on success.

Dependencies: pypdf, qpdf (CLI).

Install:
    pip install pypdf --break-system-packages
    apt-get install -y qpdf   # or brew install qpdf
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    DictionaryObject,
    FloatObject,
    NameObject,
    StreamObject,
    TextStringObject,
)


# Font used by every /Tx field in Form 400 (Courier-Bold Type1 WinAnsiEncoding)
FONT_NAME = "/564737a1-7d14-4eb9-ab10-bda962900e49"


# ---------------------------------------------------------------------------
# JSON -> flat Form 400 field dicts
# ---------------------------------------------------------------------------

def _money_words_no_dollars(s: str | None) -> str:
    """Strip trailing 'Dollars' — form shows 'dollars' after the field."""
    if not s:
        return ""
    out = s.strip()
    for suffix in (" Dollars", " dollars", "Dollars", "dollars"):
        if out.endswith(suffix):
            out = out[: -len(suffix)].rstrip()
            break
    return out


def _d(date_obj: dict | None, key: str, default: str = "") -> str:
    if not date_obj:
        return default
    return str(date_obj.get(key, default) or "")


def offer_json_to_fields(offer: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    """
    Convert voice-agent JSON -> (text_fields, checkbox_fields).

    The structure follows System_Prompt_Offer_Agent.md.
    """
    prop = offer.get("property", {}) or {}
    buyers = offer.get("buyers", {}) or {}
    sellers = offer.get("sellers", {}) or {}
    fin = offer.get("financial", {}) or {}
    dates = offer.get("dates", {}) or {}
    s3 = offer.get("section_3_seller_obligations", {}) or {}
    s4 = offer.get("section_4_buyer_conditions", {}) or {}
    s62 = offer.get("section_6_2_chattels", {}) or {}
    s7 = offer.get("section_7_additional", "")
    agency = offer.get("agency", {}) or {}

    text_fields: dict[str, str] = {
        # Page counter
        "txtTotalPages": str(offer.get("total_pages", "3")),

        # Property header (appears on all 3 pages via parent-with-kids)
        "txtp_streetnum": prop.get("streetnum", ""),
        "txtp_street": prop.get("street", ""),
        "txtp_unitNumber": prop.get("unit", ""),
        "txtp_city": prop.get("city", ""),
        "txtp_state": prop.get("state", "Nova Scotia"),
        "txtp_zipcode": prop.get("zipcode", ""),
        "txtp_county": prop.get("county", ""),
        "txtp_TaxID": prop.get("pid", ""),

        # Buyer name header (parent-with-kids)
        "txtbuyer1": buyers.get("names_line1", ""),
        "txtbuyer2": buyers.get("names_line2", ""),

        # Buyer's current address (page-1 "of ___" line)
        "txtb_streetnum": buyers.get("address_streetnum", ""),
        "txtb_street": buyers.get("address_street", ""),
        "txtb_city": buyers.get("address_city", ""),
        "txtb_state": buyers.get("address_state", "Nova Scotia"),
        "txtb_zipcode": buyers.get("address_zipcode", ""),

        # Seller
        "txtseller1": sellers.get("names_line1", ""),
        "txtseller2": sellers.get("names_line2", ""),

        # Financial
        "txtp_price": fin.get("price_amount", ""),
        "txtp_pricewords": _money_words_no_dollars(fin.get("price_words", "")),
        "txtp_Deposit": fin.get("deposit_amount", ""),
        "txtp_DepositWords": _money_words_no_dollars(fin.get("deposit_words", "")),
        "txtDepositPayable": fin.get("deposit_payable_to", ""),

        # Section 2.2 pre-closing viewing (default 8:00 a.m.)
        "txtVacantTime": offer.get("section_2_2_viewing_time", "8:00"),

        # Section 2.5 deed type (default Warranty)
        "txtConveyanceBy": offer.get("section_2_5_deed_type", "Warranty"),

        # Dates — deposit (Section 2.1)
        "txtDepositDate_d": _d(fin.get("deposit_date"), "d"),
        "txtDepositDate_m": _d(fin.get("deposit_date"), "m"),
        "txtDepositDate_yy": _d(fin.get("deposit_date"), "yy"),

        # Dates — offer date (header)
        "txtp_OfferDate_d": _d(dates.get("offer_date"), "d"),
        "txtp_OfferDate_m": _d(dates.get("offer_date"), "m"),
        "txtp_OfferDate_yyyy": _d(dates.get("offer_date"), "yyyy"),

        # Dates — closing (Section 2.2)
        "txtp_closedate_d": _d(dates.get("closing"), "d"),
        "txtp_closedate_mmmm": _d(dates.get("closing"), "m"),
        "txtp_closedate_yy": _d(dates.get("closing"), "yy"),

        # Dates — seller obligations (Section 3)
        "txtSellObligationDate_d": _d(dates.get("seller_obligations"), "d"),
        "txtSellObligationDate_m": _d(dates.get("seller_obligations"), "m"),
        "txtSellObligationDate_yy": _d(dates.get("seller_obligations"), "yy"),

        # Dates — buyer conditions/obligations (Section 4) + waiver time
        # Time default: 7:00 p.m. — Buyer's Waiver form (NSAR Form 408) is due by 7 p.m.
        "txtBuyObligationDate_d": _d(dates.get("buyer_conditions"), "d"),
        "txtBuyObligationDate_m": _d(dates.get("buyer_conditions"), "m"),
        "txtBuyObligationDate_yy": _d(dates.get("buyer_conditions"), "yy"),
        "txtCondTime": _d(dates.get("buyer_conditions"), "time", "7:00"),

        # Dates — fixtures viewing (Section 6.1)
        "txtFixtureDate_d": _d(dates.get("fixtures_viewing"), "d"),
        "txtFixtureDate_m": _d(dates.get("fixtures_viewing"), "m"),
        "txtFixtureDate_yy": _d(dates.get("fixtures_viewing"), "yy"),

        # Dates — lawyer review (Section 8 — defaults to Section 4 date)
        "txtLawyerDate_d": _d(dates.get("lawyer_review"), "d") or _d(dates.get("buyer_conditions"), "d"),
        "txtLawyerDate_m": _d(dates.get("lawyer_review"), "m") or _d(dates.get("buyer_conditions"), "m"),
        "txtLawyerDate_yy": _d(dates.get("lawyer_review"), "yy") or _d(dates.get("buyer_conditions"), "yy"),

        # Dates — irrevocable / acceptance (Section 13) — ALWAYS ASKED, NO DEFAULT
        # The AI must collect this from Estevan every time; never assume a time.
        "txtp_OfferAcceptanceDate_d": _d(dates.get("irrevocable"), "d"),
        "txtp_OfferAcceptanceDate_mmmm": _d(dates.get("irrevocable"), "m"),
        "txtp_OfferAcceptanceDate_yy": _d(dates.get("irrevocable"), "yy"),
        "txtAcceptanceTime": _d(dates.get("irrevocable"), "time"),  # no default

        # Section 3 seller obligations "Other" slots (4 available)
        "txtSellerObligationOther1": s3.get("other_1", ""),
        "txtSellerObligationOther2": s3.get("other_2", ""),
        "txtSellerObligationOther3": s3.get("other_3", ""),
        "txtSellerObligationOther4": s3.get("other_4", ""),

        # Section 4 buyer obligations "Other" slots
        "txtBuyerObligationOther1": s4.get("other_1", ""),
        "txtBuyerObligationOther2": s4.get("other_2", ""),

        # Section 6.2 chattels "Other" slots (3 available)
        "txtFixtureOther1": s62.get("other_1", ""),
        "txtFixtureOther2": s62.get("other_2", ""),
        "txtFixtureOther3": s62.get("other_3", ""),

        # Section 7 additional clauses — EMPTY by default, only filled when explicitly provided
        "txtAddConditions": s7 or "",  # s7 comes from offer_json; AI must only set it when Estevan adds a clause

        # Section 12 agency — fixed mapping (12.1 = seller/listing, 12.2 = buyer)
        "txtl_broker": agency.get("section_12_1_listing_brokerage", ""),
        "txtl_brkagent": agency.get("section_12_1_listing_agent", ""),
        "txtl2_brkagent": agency.get("section_12_1_team_partner", ""),
        "txts_broker": agency.get("section_12_2_buyer_brokerage", "RE/MAX Nova"),
        "txts_brkagent": agency.get("section_12_2_buyer_agent", "Estevan Ouellet"),
        "txts2_brkagent": agency.get("section_12_2_team_partner", ""),

        # Section 12.3 — always blank when 12.1 + 12.2 used
        "txtAgreementBroker": "",
        "txtAgreementAgent": "",
        "txtAgreementAgent2": "",
    }

    # Strip None/nulls to empty string
    text_fields = {k: (v if v is not None else "") for k, v in text_fields.items()}

    # AM/PM hidden fields (defaults)
    text_fields["hidAMPM"] = offer.get("section_2_2_viewing_ampm", "a.m.")   # Section 2.2 vacant viewing (a.m.)
    text_fields["hidAMPM3"] = _d(dates.get("buyer_conditions"), "ampm", "p.m.")  # Section 4 waiver time default p.m.
    text_fields["hidAMPM2"] = _d(dates.get("irrevocable"), "ampm")  # Section 13 — no default, always ask

    # ----- checkboxes -----
    # Every chkOpt_* checkbox in Form 400 uses "/1" as the ON state (not "/Yes").
    # Radio groups (HST, Migration, agency, Viewed) also use /1, /2, /3...
    def chk(val: bool) -> str:
        return "/1" if val else "/Off"

    # Silent defaults from Estevan_Rules_v7
    checkboxes: dict[str, str] = {
        # Buyer personally viewed
        "chkOpt_Viewed": "/1",  # "personally viewed" (radio: /1 or /2)

        # HST exempt (radio /1 = exempt, /2 = included, /3 = extra)
        "chkOpt_HST": "/1",

        # Property migration (a) Migrated to Land Registration System
        "chkOpt_Migration": "/1",

        # Agency "do have" (12.1 + 12.2)
        "chkOpt_SellAgency": "/1",
        "chkOpt_BuyAgency": "/1",

        # Section 3 seller obligations
        # NOTE: Form 400 has 6 SellObligation checkboxes + 4 "Other" text slots.
        # Pre-labeled items: 1=PDS, 2=Restrictive Covenants, 3=Equipment Schedule, 4=Location Certificate.
        # 5 and 6 are the "Other" checkboxes; any extra text goes into txtSellerObligationOther3/4 (uncommon).
        "chkOpt_SellObligation1": chk(bool(s3.get("pds"))),                   # PDS
        "chkOpt_SellObligation2": chk(bool(s3.get("restrictive_covenants"))),  # Restrictive covenants
        "chkOpt_SellObligation3": chk(bool(s3.get("equipment_schedule"))),    # Equipment schedule
        "chkOpt_SellObligation4": chk(bool(s3.get("location_certificate"))),  # Location certificate
        "chkOpt_SellObligation5": chk(bool(s3.get("other_1"))),                # Other 1 (utility bills)
        "chkOpt_SellObligation6": chk(bool(s3.get("other_2"))),                # Other 2 (tax bill)

        # Section 4 buyer conditions (Financing + Inspection + Insurance default)
        "chkOpt_BuyObligation1": chk(bool(s4.get("pds"))),
        "chkOpt_BuyObligation2": chk(bool(s4.get("restrictive_covenants"))),
        "chkOpt_BuyObligation3": chk(bool(s4.get("equipment_schedule"))),
        "chkOpt_BuyObligation4": chk(s4.get("financing", True)),
        "chkOpt_BuyObligation5": chk(s4.get("inspection", True)),
        "chkOpt_BuyObligation6": chk(s4.get("insurance", True)),
        "chkOpt_BuyObligation7": chk(bool(s4.get("other_1"))),
        "chkOpt_BuyObligation8": chk(bool(s4.get("other_2"))),

        # Section 6.2 fixtures / chattels
        "chkOpt_Fixture1": chk(bool(s62.get("fridge"))),
        "chkOpt_Fixture2": chk(bool(s62.get("stove"))),
        "chkOpt_Fixture3": chk(bool(s62.get("washer"))),
        "chkOpt_Fixture4": chk(bool(s62.get("dryer"))),
        "chkOpt_Fixture5": chk(bool(s62.get("freezer"))),
        "chkOpt_Fixture6": chk(bool(s62.get("microwave"))),
        "chkOpt_Fixture7": chk(bool(s62.get("dishwasher"))),
        "chkOpt_Fixture8": chk(bool(s62.get("other_1"))),
        "chkOpt_Fixture9": chk(bool(s62.get("other_2"))),
        "chkOpt_Fixture10": chk(bool(s62.get("other_3"))),
    }

    return text_fields, checkboxes


# ---------------------------------------------------------------------------
# Parent-with-kids /AP rebuild (the v10 trick)
# ---------------------------------------------------------------------------

def _pdf_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _build_ap_stream(text: str, width: float, height: float, font_ref: Any) -> StreamObject:
    """Manually build the /AP/N Form XObject for a /Tx widget."""
    inner_w = width - 1.4
    inner_h = height - 1
    content = (
        f"q\n/Tx BMC \nq\n1 1 {inner_w} {inner_h} re\nW\n"
        f"BT\n{FONT_NAME} 9 Tf 0.003922 0.003922 0.003922 rg\r\n\n"
        f"2 2.0757 Td\n({_pdf_escape(text)}) Tj\nET\nQ\nEMC\nQ\n"
    ).encode("latin-1", errors="replace")

    stream = StreamObject()
    stream[NameObject("/Type")] = NameObject("/XObject")
    stream[NameObject("/Subtype")] = NameObject("/Form")
    stream[NameObject("/BBox")] = ArrayObject(
        [FloatObject(0), FloatObject(0), FloatObject(width), FloatObject(height)]
    )
    res = DictionaryObject()
    fonts = DictionaryObject()
    fonts[NameObject(FONT_NAME)] = font_ref
    res[NameObject("/Font")] = fonts
    stream[NameObject("/Resources")] = res
    stream.set_data(content)
    return stream


def _resolve(obj):
    """Dereference IndirectObject → underlying dict/array."""
    try:
        return obj.get_object() if hasattr(obj, "get_object") else obj
    except Exception:
        return obj


def _find_font_ref(writer: PdfWriter) -> Any | None:
    """Walk AcroForm tree + pages to find the Form 400 font object."""
    root = _resolve(writer._root_object)
    acro = _resolve(root.get("/AcroForm")) if root else None
    if acro:
        dr = _resolve(acro.get("/DR"))
        if dr:
            fonts = _resolve(dr.get("/Font"))
            if fonts and FONT_NAME in fonts:
                return fonts[FONT_NAME]
    # Fallback: scan page resources
    for page in writer.pages:
        res = _resolve(page.get("/Resources"))
        if not res:
            continue
        fonts = _resolve(res.get("/Font"))
        if fonts and FONT_NAME in fonts:
            return fonts[FONT_NAME]
    return None


def _fix_parent_kids(writer: PdfWriter, values: dict[str, str]) -> None:
    """For every parent-with-kids Tx field, set /V on each widget and build /AP/N."""
    font_ref = _find_font_ref(writer)
    if font_ref is None:
        # No font found — widgets will rely on /DA inheritance; may still render via qpdf
        return

    root = _resolve(writer._root_object)
    acro = _resolve(root.get("/AcroForm")) if root else None
    if not acro:
        return
    fields = _resolve(acro.get("/Fields"))
    if not fields:
        return

    def walk(field_refs):
        for f_ref in field_refs:
            f = f_ref.get_object()
            name = str(f.get("/T", ""))
            ft = f.get("/FT")
            if name in values and str(ft) == "/Tx" and "/Kids" in f:
                val = values[name]
                if val:
                    for k_ref in f["/Kids"]:
                        k = k_ref.get_object()
                        rect = k.get("/Rect")
                        if not rect:
                            continue
                        try:
                            w = float(rect[2]) - float(rect[0])
                            h = float(rect[3]) - float(rect[1])
                        except Exception:
                            continue
                        k[NameObject("/V")] = TextStringObject(val)
                        ap_stream = _build_ap_stream(val, w, h, font_ref)
                        ap_dict = DictionaryObject()
                        ap_dict[NameObject("/N")] = writer._add_object(ap_stream)
                        k[NameObject("/AP")] = ap_dict
                    f[NameObject("/V")] = TextStringObject(val)
            if "/Kids" in f:
                for k_ref in f["/Kids"]:
                    k = k_ref.get_object()
                    if k.get("/Subtype") != "/Widget":
                        walk([k_ref])

    walk(fields)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def fill_form_400(
    offer_json: dict[str, Any],
    source_pdf: str,
    output_path: str,
    qpdf_binary: str = "qpdf",
) -> str:
    """
    Fill Form 400 from the voice-agent JSON output.

    Parameters
    ----------
    offer_json
        Dict matching the System_Prompt_Offer_Agent.md schema.
    source_pdf
        Path to the blank fillable Form 400 ("Edible version.pdf").
    output_path
        Where to write the filled PDF.
    qpdf_binary
        Override if qpdf isn't on $PATH.

    Returns the output path.
    """
    text_fields, checkboxes = offer_json_to_fields(offer_json)

    reader = PdfReader(source_pdf)
    writer = PdfWriter(clone_from=reader)

    # Step 1 — page-level update (handles non-parent fields + checkboxes, builds /AP)
    for page in writer.pages:
        try:
            writer.update_page_form_field_values(page, text_fields)
        except Exception:
            pass
        try:
            writer.update_page_form_field_values(page, checkboxes)
        except Exception:
            pass

    # Force NeedAppearances for viewer regeneration fallback
    try:
        root = _resolve(writer._root_object)
        acro = _resolve(root.get("/AcroForm")) if root else None
        if acro:
            acro[NameObject("/NeedAppearances")] = NameObject("/true")
    except Exception:
        pass

    # Step 2 — manually build /AP/N for parent-with-kids text fields
    _fix_parent_kids(writer, text_fields)

    # Write intermediate, then qpdf-normalize to finalize
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        with open(tmp_path, "wb") as f:
            writer.write(f)

        # qpdf finalize — linearize only (we built appearances ourselves)
        try:
            subprocess.run(
                [qpdf_binary, "--warning-exit-0", "--linearize", tmp_path, output_path],
                check=True,
                capture_output=True,
            )
        except FileNotFoundError:
            # qpdf not installed — fall back to raw pypdf output
            Path(output_path).write_bytes(Path(tmp_path).read_bytes())
    finally:
        try:
            Path(tmp_path).unlink()
        except Exception:
            pass

    return output_path


# ---------------------------------------------------------------------------
# Self-test (Sample_Offer_Transcript scenario)
# ---------------------------------------------------------------------------

SAMPLE_OFFER = {
    "property": {
        "streetnum": "123", "street": "Oak Street", "unit": "",
        "city": "Halifax", "state": "Nova Scotia", "zipcode": "B3H 1A1",
        "county": "Halifax", "pid": "00012345",
    },
    "buyers": {
        "names_line1": "John Smith and Jane Smith", "names_line2": "",
        "address_streetnum": "45", "address_street": "Maple Avenue",
        "address_city": "Dartmouth", "address_state": "Nova Scotia",
        "address_zipcode": "B2Y 3Z1",
    },
    "sellers": {
        "names_line1": "Robert Johnson and Mary Johnson", "names_line2": "",
    },
    "financial": {
        "price_amount": "$650,000.00",
        "price_words": "Six Hundred Fifty Thousand",
        "deposit_amount": "$10,000.00",
        "deposit_words": "Ten Thousand",
        "deposit_date": {"d": "20", "m": "April", "yy": "26"},
        "deposit_payable_to": "Royal LePage Atlantic in Trust",
    },
    "dates": {
        "offer_date": {"d": "19", "m": "April", "yyyy": "2026"},
        "closing": {"d": "22", "m": "June", "yy": "26"},  # Mon — validated
        "seller_obligations": {"d": "29", "m": "April", "yy": "26"},
        "buyer_conditions": {"d": "29", "m": "April", "yy": "26", "time": "7:00", "ampm": "p.m."},
        "fixtures_viewing": {"d": "14", "m": "April", "yy": "26"},
        "lawyer_review": {"d": "29", "m": "April", "yy": "26"},
        "irrevocable": {"d": "20", "m": "April", "yy": "26", "time": "6:00", "ampm": "p.m."},
    },
    "section_3_seller_obligations": {
        "pds": True, "restrictive_covenants": False,
        "equipment_schedule": False, "location_certificate": True,
        "other_1": "Last 24 months of utility bills",
        "other_2": "Most recent property tax bill",
    },
    "section_4_buyer_conditions": {
        # Other slots are BLANK by default — only populated when Estevan explicitly names a condition.
        "pds": False, "financing": True, "inspection": True, "insurance": True,
        "other_1": "", "other_2": "",
    },
    "section_6_2_chattels": {
        "fridge": True, "stove": True, "washer": True, "dryer": True,
        "freezer": True, "microwave": True, "dishwasher": True,
        "other_1": "", "other_2": "", "other_3": "",
    },
    "section_7_additional": "",  # Section 7 is blank by default; only populated when Estevan explicitly adds a clause
    "agency": {
        "section_12_1_listing_brokerage": "Royal LePage Atlantic",
        "section_12_1_listing_agent": "Sarah Thompson",
        "section_12_1_team_partner": "",
        "section_12_2_buyer_brokerage": "RE/MAX Nova",
        "section_12_2_buyer_agent": "Estevan Ouellet",
        "section_12_2_team_partner": "",
    },
}


if __name__ == "__main__":
    import sys

    source = sys.argv[1] if len(sys.argv) > 1 else "/sessions/fervent-gracious-turing/mnt/uploads/Edible version.pdf"
    out = sys.argv[2] if len(sys.argv) > 2 else "/sessions/fervent-gracious-turing/mnt/outputs/Form_400_FILLED_from_module.pdf"
    result = fill_form_400(SAMPLE_OFFER, source, out)
    print(f"Wrote: {result}")
