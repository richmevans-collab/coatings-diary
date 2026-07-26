"""
Branded Coatings Diary PDF - same colour system/logo as the estimate tool's
cover sheet (see create_cover in ../Estimate Generator/estimate_engine.py),
adapted for a Section x Stage grid plus a photo appendix instead of a quote.
"""
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white
from reportlab.pdfgen import canvas

import db

LOGO_FILE = str(Path(__file__).parent / "Orams Logo Horizontal.png")

NAVY = HexColor("#071B46")
RED = HexColor("#C8313A")
DARK = HexColor("#1A1F2E")
MID_GREY = HexColor("#8A8F9A")
GREY_LINE = HexColor("#DDE0E5")

# (section title, [(field label, stage_entries column), ...])
FIELD_SECTIONS = [
    ("Climate Data", [
        ("Date/Time", "date_time"),
        ("Conditions", "conditions"),
        ("RH %", "rh_percent"),
        ("Air Temp °C", "air_temp"),
        ("Dew Point °C", "dew_point"),
        ("Surface Temp °C", "surface_temp"),
        ("OK to Paint", "paint_yes_no"),
    ]),
    ("Surface Preparation", [
        ("Prep Date/Time", "prep_date_time"),
        ("Cleanliness", "cleanliness"),
        ("Profile/Sanding", "profile_sanding"),
    ]),
    ("Paint / Application", [
        ("Date/Time", "paint_date_time"),
        ("Product", "product_name"),
        ("Batch No. A", "batch_no_a"),
        ("Batch No. B", "batch_no_b"),
        ("Thinning %", "thinning_percent"),
        ("Thinning Product", "thinning_product"),
        ("Volume (L)", "volume_litres"),
        ("Induction Time", "induction_time"),
        ("Recoat Time Min", "recoat_time_min"),
        ("Recoat Time Max", "recoat_time_max"),
        ("WFT", "wft"),
    ]),
    ("DFT & Inspection", [
        ("Date/Time", "dft_date_time"),
        ("Readings", "dft_readings"),
        ("Min", "dft_min"),
        ("Max", "dft_max"),
        ("Average", "dft_average"),
        ("Std Dev", "dft_std_dev"),
        ("Appearance", "appearance"),
        ("Pass/Fail/Repair", "pass_fail_repair"),
    ]),
]


def _fmt(value):
    if value is None or value == "":
        return "-"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _fit_text(c, text, max_width, font_name="Helvetica", font_size=7.2):
    """Truncates text (with an ellipsis) so it fits max_width points -
    avoids cutting a value off mid-character like a fixed [:22] slice would
    (e.g. a DFT readings list ending "...140, 13" instead of "140, 130")."""
    if c.stringWidth(text, font_name, font_size) <= max_width:
        return text
    while text and c.stringWidth(text + "…", font_name, font_size) > max_width:
        text = text[:-1]
    return (text + "…") if text else "…"


def hairline(c, x1, y, x2, color=None, lw=0.35):
    c.setStrokeColor(color or GREY_LINE)
    c.setLineWidth(lw)
    c.line(x1, y, x2, y)


def build_coatings_diary_pdf(output_path, job, entries_by_stage, photos_by_stage, upload_folder):
    stages_with_data = [s for s in db.STAGES if s in entries_by_stage]

    c = canvas.Canvas(output_path, pagesize=A4)
    W, H = A4
    L = 14 * mm
    R = W - 14 * mm

    # ── HEADER ──────────────────────────────────────────────────────────
    y = H - 15 * mm
    LOGO_H = 16 * mm
    LOGO_W = LOGO_H * (1615 / 473)
    logo_bottom = y - LOGO_H

    if Path(LOGO_FILE).exists():
        c.drawImage(LOGO_FILE, L, logo_bottom, width=LOGO_W, height=LOGO_H,
                    preserveAspectRatio=True, mask="auto")
    else:
        c.setFillColor(NAVY); c.setFont("Helvetica-Bold", 15)
        c.drawString(L, logo_bottom + 3 * mm, "ORAMS MARINE")

    c.setFillColor(NAVY); c.setFont("Helvetica-Bold", 18)
    c.drawRightString(R, logo_bottom + LOGO_H / 2 - 3 * mm, "COATINGS DIARY")

    y = logo_bottom - 5 * mm
    hairline(c, L, y, R)

    # ── VESSEL / JOB METADATA ───────────────────────────────────────────
    band_top = y - 7 * mm
    c.setFillColor(MID_GREY); c.setFont("Helvetica", 6.8)
    c.drawString(L, band_top, "VESSEL")
    c.setFillColor(NAVY); c.setFont("Helvetica-Bold", 14)
    c.drawString(L, band_top - 6.5 * mm, job["vessel_name"])

    meta_pairs = [
        ("Job Number", job["job_number"]),
        ("Area / Description", job["area"] or job["description"] or ""),
    ]
    m_y = band_top
    for label, value in meta_pairs:
        c.setFillColor(MID_GREY); c.setFont("Helvetica", 6.8)
        c.drawString(120 * mm, m_y, label.upper())
        c.setFillColor(DARK); c.setFont("Helvetica-Bold", 8.2)
        c.drawRightString(R, m_y, str(value)[:55])
        m_y -= 6.4 * mm

    y = band_top - 13 * mm

    extra_meta = [(l, job[k]) for l, k in
                  [("Client", "client"), ("Painter", "painter"),
                   ("Inspector", "inspector"), ("Reference Documents", "reference_documents")]
                  if job[k]]
    if extra_meta:
        col_w = (R - L) / max(len(extra_meta), 1)
        for i, (label, value) in enumerate(extra_meta):
            x = L + i * col_w
            c.setFillColor(MID_GREY); c.setFont("Helvetica", 6.5)
            c.drawString(x, y, label.upper())
            c.setFillColor(DARK); c.setFont("Helvetica", 8)
            c.drawString(x, y - 5 * mm, str(value)[:28])
        y -= 10 * mm

    hairline(c, L, y, R)
    y -= 6 * mm

    if not stages_with_data:
        c.setFillColor(MID_GREY); c.setFont("Helvetica-Oblique", 9)
        c.drawString(L, y, "No stages logged yet.")
        c.save()
        return

    # ── SECTION x STAGE GRID ─────────────────────────────────────────────
    label_col_w = 34 * mm
    stage_col_w = (R - L - label_col_w) / len(stages_with_data)

    def stage_col_x(i):
        return L + label_col_w + i * stage_col_w

    def draw_stage_header(y):
        c.setFillColor(NAVY); c.setFont("Helvetica-Bold", 7)
        for i, stage in enumerate(stages_with_data):
            c.drawString(stage_col_x(i) + 2, y, db.STAGE_LABELS[stage].upper())
        hairline(c, L, y - 2 * mm, R, color=NAVY, lw=0.6)
        return y - 7 * mm

    def new_page_if_needed(y, needed=12 * mm):
        if y < needed:
            c.showPage()
            y = H - 15 * mm
            y = draw_stage_header(y)
        return y

    y = draw_stage_header(y)

    for section_title, fields in FIELD_SECTIONS:
        y = new_page_if_needed(y, 20 * mm)
        c.setFillColor(RED); c.setFont("Helvetica-Bold", 7.2)
        c.drawString(L, y, section_title.upper())
        y -= 5.5 * mm

        for field_label, column in fields:
            y = new_page_if_needed(y)
            c.setFillColor(DARK); c.setFont("Helvetica", 7.2)
            c.drawString(L, y, field_label)
            for i, stage in enumerate(stages_with_data):
                entry = entries_by_stage[stage]
                c.setFont("Helvetica", 7.2)
                text = _fit_text(c, _fmt(entry[column]), stage_col_w - 4)
                c.drawString(stage_col_x(i) + 2, y, text)
            y -= 5 * mm
        y -= 2 * mm
        hairline(c, L, y, R)
        y -= 5 * mm

    # ── PHOTO APPENDIX ───────────────────────────────────────────────────
    any_photos = any(photos_by_stage.get(stage) for stage in stages_with_data)
    if any_photos:
        c.showPage()
        y = H - 15 * mm
        c.setFillColor(NAVY); c.setFont("Helvetica-Bold", 14)
        c.drawString(L, y, "Photos")
        y -= 8 * mm
        hairline(c, L, y, R)
        y -= 8 * mm

        thumb = 40 * mm
        gap = 6 * mm
        per_row = max(int((R - L) / (thumb + gap)), 1)

        for stage in stages_with_data:
            photos = photos_by_stage.get(stage) or []
            if not photos:
                continue
            if y < thumb + 14 * mm:
                c.showPage()
                y = H - 15 * mm
            c.setFillColor(RED); c.setFont("Helvetica-Bold", 8)
            c.drawString(L, y, db.STAGE_LABELS[stage].upper())
            y -= 6 * mm

            x = L
            col = 0
            for photo in photos:
                path = Path(upload_folder) / photo["filename"]
                if y < thumb:
                    c.showPage()
                    y = H - 15 * mm
                    x = L
                    col = 0
                if path.exists():
                    try:
                        c.drawImage(str(path), x, y - thumb, width=thumb, height=thumb,
                                    preserveAspectRatio=True, mask="auto")
                    except Exception:
                        c.setFillColor(MID_GREY); c.rect(x, y - thumb, thumb, thumb, stroke=1, fill=0)
                col += 1
                x += thumb + gap
                if col >= per_row:
                    col = 0
                    x = L
                    y -= thumb + gap
            y -= thumb + 8 * mm

    c.save()
