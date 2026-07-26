"""
Coatings Diary - Orams Marine web app for painters/PMs to log stage-by-stage
coating data per job (Substrate, Coat 1-4), replacing the paper "Coatings
Diary" sheet, plus the Request Work, Boat Builder Estimate, and Equipment
Log modules that extend the same SQLite database. See specs/ for each
module's build spec.

Run locally with: python app.py
Then open http://<your-laptop-ip>:5000 on a phone/laptop on the same wifi.
"""
import math
import statistics
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, send_file, send_from_directory
from werkzeug.utils import secure_filename

import db
import smartsheet_client
import pdf_generator

app = Flask(__name__)

UPLOAD_FOLDER = Path(__file__).parent / "uploads"
GENERATED_PDF_FOLDER = Path(__file__).parent / "generated_pdfs"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "heic", "webp"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB, plenty for a phone photo


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def calculate_dew_point(air_temp, humidity):
    """Magnus formula approximation. Returns None if inputs are missing/invalid."""
    if air_temp is None or humidity is None or humidity <= 0:
        return None
    a, b = 17.27, 237.7
    alpha = ((a * air_temp) / (b + air_temp)) + math.log(humidity / 100.0)
    return round((b * alpha) / (a - alpha), 1)


def calc_dft_stats(dft_readings_raw):
    """Parses a comma/semicolon-separated list of spot DFT readings into
    (min, max, average, std_dev). Returns all-None if nothing parses."""
    if not dft_readings_raw:
        return None, None, None, None
    values = []
    for piece in dft_readings_raw.replace(";", ",").split(","):
        piece = piece.strip()
        if not piece:
            continue
        try:
            values.append(float(piece))
        except ValueError:
            continue
    if not values:
        return None, None, None, None
    dft_average = round(sum(values) / len(values), 1)
    dft_std_dev = round(statistics.stdev(values), 1) if len(values) > 1 else 0.0
    return min(values), max(values), dft_average, dft_std_dev


def sync_jobs_from_smartsheet(conn, force_refresh=False):
    """Upserts the local jobs table from the live painter job list on
    Smartsheet (job number + description + which row a PDF should attach
    to later). Returns an error message string on failure, None on
    success - the Start screen shows the error as a banner but still
    renders whatever is already in the local jobs table."""
    try:
        jobs_by_vessel = smartsheet_client.get_painter_jobs(force_refresh=force_refresh)
    except Exception as e:
        return str(e)

    vessel_rows = conn.execute("SELECT id, name FROM vessels").fetchall()
    vessel_id_by_name = {v["name"]: v["id"] for v in vessel_rows}

    for vessel_name, job_list in jobs_by_vessel.items():
        vessel_id = vessel_id_by_name.get(vessel_name)
        if vessel_id is None:
            continue  # a vessel in Smartsheet that isn't set up locally yet

        for job in job_list:
            existing = conn.execute(
                "SELECT id FROM jobs WHERE vessel_id = ? AND job_number = ?",
                (vessel_id, job["job_number"]),
            ).fetchone()
            if existing:
                conn.execute(
                    """UPDATE jobs SET description = ?, sheet_id = ?, sheet_row_id = ?,
                       updated_at = datetime('now', 'localtime') WHERE id = ?""",
                    (job.get("description"), str(job.get("sheet_id")), str(job.get("row_id")), existing["id"]),
                )
            else:
                conn.execute(
                    """INSERT INTO jobs (vessel_id, job_number, description, sheet_id, sheet_row_id)
                       VALUES (?, ?, ?, ?, ?)""",
                    (vessel_id, job["job_number"], job.get("description"),
                     str(job.get("sheet_id")), str(job.get("row_id"))),
                )
    conn.commit()
    return None


def _job_stage_progress(conn, job_id):
    """Returns {stage: True/False} for whether that stage has a logged entry."""
    done = {row["stage"] for row in conn.execute(
        "SELECT stage FROM stage_entries WHERE job_id = ?", (job_id,)
    ).fetchall()}
    return {stage: (stage in done) for stage in db.STAGES}


@app.route("/")
def start():
    """Screen 1: pick a vessel, then see its jobs (live from Smartsheet) with stage progress."""
    conn = db.get_db()
    vessels = conn.execute("SELECT * FROM vessels ORDER BY name").fetchall()

    selected_vessel_id = request.args.get("vessel_id", type=int)
    sync_error = None
    jobs = []
    if selected_vessel_id:
        sync_error = sync_jobs_from_smartsheet(conn, force_refresh=request.args.get("refresh") == "1")
        job_rows = conn.execute(
            "SELECT * FROM jobs WHERE vessel_id = ? ORDER BY job_number",
            (selected_vessel_id,),
        ).fetchall()
        jobs = [dict(job, stage_progress=_job_stage_progress(conn, job["id"])) for job in job_rows]
    conn.close()

    return render_template(
        "start.html",
        vessels=vessels,
        jobs=jobs,
        selected_vessel_id=selected_vessel_id,
        sync_error=sync_error,
        stages=db.STAGES,
    )


@app.route("/jobs/<int:job_id>")
def job_router(job_id):
    """Selecting a job: jump to its first incomplete stage, or the summary if all are logged."""
    conn = db.get_db()
    progress = _job_stage_progress(conn, job_id)
    conn.close()

    for stage in db.STAGES:
        if not progress[stage]:
            return redirect(url_for("log_stage_form", job_id=job_id, stage=stage))
    return redirect(url_for("job_summary", job_id=job_id))


@app.route("/jobs/<int:job_id>/stage/<stage>")
def log_stage_form(job_id, stage):
    """Screen 2: the Log Stage form - Climate / Surface Prep / Paint / DFT section cards."""
    if stage not in db.STAGES:
        return redirect(url_for("start"))

    conn = db.get_db()
    job = conn.execute(
        """SELECT jobs.*, vessels.name AS vessel_name
           FROM jobs JOIN vessels ON jobs.vessel_id = vessels.id
           WHERE jobs.id = ?""",
        (job_id,),
    ).fetchone()
    if job is None:
        conn.close()
        return redirect(url_for("start"))

    entry = conn.execute(
        "SELECT * FROM stage_entries WHERE job_id = ? AND stage = ?", (job_id, stage)
    ).fetchone()
    photos = []
    if entry:
        photos = conn.execute(
            "SELECT * FROM stage_photos WHERE stage_entry_id = ? ORDER BY uploaded_at", (entry["id"],)
        ).fetchall()
    conn.close()

    return render_template(
        "log_stage.html",
        job=job,
        stage=stage,
        stage_label=db.STAGE_LABELS[stage],
        stages=db.STAGES,
        stage_labels=db.STAGE_LABELS,
        entry=entry,
        photos=photos,
        now=datetime.now().strftime("%Y-%m-%dT%H:%M"),
    )


@app.route("/jobs/<int:job_id>/stage/<stage>", methods=["POST"])
def submit_stage(job_id, stage):
    if stage not in db.STAGES:
        return redirect(url_for("start"))

    conn = db.get_db()
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if job is None:
        conn.close()
        return redirect(url_for("start"))

    def val(field):
        return request.form.get(field, "").strip() or None

    def num(field):
        raw = request.form.get(field, "").strip()
        return float(raw) if raw else None

    conn.execute(
        """UPDATE jobs SET client = ?, painter = ?, inspector = ?, reference_documents = ?,
           updated_at = datetime('now', 'localtime') WHERE id = ?""",
        (val("client"), val("painter"), val("inspector"), val("reference_documents"), job_id),
    )

    air_temp = num("air_temp")
    rh_percent = num("rh_percent")
    dew_point = calculate_dew_point(air_temp, rh_percent)
    dft_min, dft_max, dft_average, dft_std_dev = calc_dft_stats(val("dft_readings"))

    fields = dict(
        date_time=val("date_time"), conditions=val("conditions"), rh_percent=rh_percent,
        air_temp=air_temp, dew_point=dew_point, surface_temp=num("surface_temp"),
        paint_yes_no=val("paint_yes_no"),
        prep_date_time=val("prep_date_time"), cleanliness=val("cleanliness"),
        profile_sanding=val("profile_sanding"),
        paint_date_time=val("paint_date_time"), product_name=val("product_name"),
        batch_no_a=val("batch_no_a"), batch_no_b=val("batch_no_b"),
        thinning_percent=num("thinning_percent"), thinning_product=val("thinning_product"),
        volume_litres=num("volume_litres"), induction_time=val("induction_time"),
        recoat_time_min=val("recoat_time_min"), recoat_time_max=val("recoat_time_max"),
        wft=num("wft"),
        dft_date_time=val("dft_date_time"), dft_readings=val("dft_readings"),
        dft_min=dft_min, dft_max=dft_max, dft_average=dft_average, dft_std_dev=dft_std_dev,
        appearance=val("appearance"), pass_fail_repair=val("pass_fail_repair"),
    )

    existing = conn.execute(
        "SELECT id FROM stage_entries WHERE job_id = ? AND stage = ?", (job_id, stage)
    ).fetchone()
    if existing:
        entry_id = existing["id"]
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE stage_entries SET {set_clause} WHERE id = ?",
                     (*fields.values(), entry_id))
    else:
        columns = ", ".join(fields.keys())
        placeholders = ", ".join("?" for _ in fields)
        cur = conn.execute(
            f"INSERT INTO stage_entries (job_id, stage, {columns}) VALUES (?, ?, {placeholders})",
            (job_id, stage, *fields.values()),
        )
        entry_id = cur.lastrowid

    photos = request.files.getlist("photos")
    if photos:
        UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
    for photo in photos:
        if photo and photo.filename and allowed_file(photo.filename):
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
            safe_name = secure_filename(photo.filename)
            filename = f"job{job_id}_{stage}_{timestamp}_{safe_name}"
            photo.save(UPLOAD_FOLDER / filename)
            conn.execute(
                "INSERT INTO stage_photos (stage_entry_id, filename) VALUES (?, ?)",
                (entry_id, filename),
            )

    conn.commit()
    conn.close()

    return redirect(url_for("job_router", job_id=job_id))


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


@app.route("/jobs/<int:job_id>/summary")
def job_summary(job_id):
    """Screen 3: compiled read-only grid + Generate PDF / Submit to Smartsheet."""
    conn = db.get_db()
    job = conn.execute(
        """SELECT jobs.*, vessels.name AS vessel_name
           FROM jobs JOIN vessels ON jobs.vessel_id = vessels.id
           WHERE jobs.id = ?""",
        (job_id,),
    ).fetchone()
    if job is None:
        conn.close()
        return redirect(url_for("start"))

    entries_by_stage = {
        row["stage"]: row
        for row in conn.execute("SELECT * FROM stage_entries WHERE job_id = ?", (job_id,)).fetchall()
    }
    conn.close()

    pdf_exists = (GENERATED_PDF_FOLDER / f"job_{job_id}.pdf").exists()

    return render_template(
        "job_summary.html",
        job=job,
        stages=db.STAGES,
        stage_labels=db.STAGE_LABELS,
        field_sections=pdf_generator.FIELD_SECTIONS,
        entries_by_stage=entries_by_stage,
        pdf_exists=pdf_exists,
        submitted=request.args.get("submitted"),
        error=request.args.get("error"),
    )


@app.route("/jobs/<int:job_id>/summary/pdf")
def generate_job_pdf(job_id):
    conn = db.get_db()
    job = conn.execute(
        """SELECT jobs.*, vessels.name AS vessel_name
           FROM jobs JOIN vessels ON jobs.vessel_id = vessels.id
           WHERE jobs.id = ?""",
        (job_id,),
    ).fetchone()
    if job is None:
        conn.close()
        return redirect(url_for("start"))

    entries_by_stage = {
        row["stage"]: row
        for row in conn.execute("SELECT * FROM stage_entries WHERE job_id = ?", (job_id,)).fetchall()
    }
    photos_by_stage = {}
    for stage, entry in entries_by_stage.items():
        photos_by_stage[stage] = conn.execute(
            "SELECT * FROM stage_photos WHERE stage_entry_id = ? ORDER BY uploaded_at", (entry["id"],)
        ).fetchall()
    conn.close()

    GENERATED_PDF_FOLDER.mkdir(parents=True, exist_ok=True)
    download_name = f"{job['job_number']} - Coatings Diary - {job['area'] or job['job_title'] or ''}.pdf".strip()
    output_path = GENERATED_PDF_FOLDER / f"job_{job_id}.pdf"

    pdf_generator.build_coatings_diary_pdf(
        output_path=str(output_path),
        job=job,
        entries_by_stage=entries_by_stage,
        photos_by_stage=photos_by_stage,
        upload_folder=UPLOAD_FOLDER,
    )

    return send_file(output_path, as_attachment=True, download_name=download_name)


@app.route("/jobs/<int:job_id>/summary/submit-smartsheet", methods=["POST"])
def submit_job_to_smartsheet(job_id):
    conn = db.get_db()
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()

    if job is None:
        return redirect(url_for("start"))

    pdf_path = GENERATED_PDF_FOLDER / f"job_{job_id}.pdf"
    error = None
    if not pdf_path.exists():
        error = "Generate the PDF first, then submit it to Smartsheet."
    elif not job["sheet_id"] or not job["sheet_row_id"]:
        error = "This job isn't linked to a Smartsheet row yet - refresh the job list from the Start screen first."
    else:
        try:
            smartsheet_client.attach_pdf_to_row(job["sheet_id"], job["sheet_row_id"], str(pdf_path))
        except Exception as e:
            error = str(e)

    return redirect(url_for("job_summary", job_id=job_id,
                             submitted=("0" if error else "1"), error=error))


@app.route("/request-work")
def request_work_form():
    """Shared entry point: contractors submitting directly, or a PM quick-logging
    a request that came in by phone/email. Same form, same work_requests row."""
    conn = db.get_db()
    vessels = conn.execute("SELECT * FROM vessels ORDER BY name").fetchall()

    selected_vessel_id = request.args.get("vessel_id", type=int)
    jobs = []
    if selected_vessel_id:
        jobs = conn.execute(
            "SELECT * FROM jobs WHERE vessel_id = ? ORDER BY job_number",
            (selected_vessel_id,),
        ).fetchall()
    conn.close()

    return render_template(
        "request_work.html",
        vessels=vessels,
        jobs=jobs,
        selected_vessel_id=selected_vessel_id,
        reasons=db.REQUEST_REASONS,
    )


@app.route("/request-work", methods=["POST"])
def submit_work_request():
    vessel_id = request.form.get("vessel_id", type=int)
    request_type = request.form.get("request_type")
    job_id = request.form.get("job_id", type=int) if request_type == "Scope Change" else None
    job_title = request.form.get("job_title", "").strip() if request_type == "New Job" else None
    description = request.form.get("description", "").strip()
    requested_by = request.form.get("requested_by", "").strip()
    requested_by_contact = request.form.get("requested_by_contact", "").strip() or None
    reason = request.form.get("reason")
    cost_raw = request.form.get("estimated_cost", "").strip()
    estimated_cost = float(cost_raw) if cost_raw else None

    conn = db.get_db()
    cur = conn.execute(
        """INSERT INTO work_requests
           (vessel_id, request_type, job_id, job_title, description, requested_by,
            requested_by_contact, reason, estimated_cost)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (vessel_id, request_type, job_id, job_title, description, requested_by,
         requested_by_contact, reason, estimated_cost),
    )
    conn.commit()
    request_id = cur.lastrowid
    conn.close()

    return redirect(url_for("request_work_confirmation", request_id=request_id))


@app.route("/request-work/confirmation/<int:request_id>")
def request_work_confirmation(request_id):
    conn = db.get_db()
    work_request = conn.execute(
        """SELECT work_requests.*, vessels.name AS vessel_name
           FROM work_requests JOIN vessels ON work_requests.vessel_id = vessels.id
           WHERE work_requests.id = ?""",
        (request_id,),
    ).fetchone()
    conn.close()

    if work_request is None:
        return redirect(url_for("request_work_form"))

    return render_template("request_work_confirmation.html", req=work_request)


def _fetch_request_detail(conn, request_id):
    return conn.execute(
        """SELECT work_requests.*, vessels.name AS vessel_name,
                  jobs.job_number AS existing_job_number,
                  jobs.job_title AS existing_job_title
           FROM work_requests
           JOIN vessels ON work_requests.vessel_id = vessels.id
           LEFT JOIN jobs ON work_requests.job_id = jobs.id
           WHERE work_requests.id = ?""",
        (request_id,),
    ).fetchone()


@app.route("/requests/pending")
def pending_requests():
    conn = db.get_db()
    pending = conn.execute(
        """SELECT work_requests.*, vessels.name AS vessel_name,
                  jobs.job_number AS existing_job_number
           FROM work_requests
           JOIN vessels ON work_requests.vessel_id = vessels.id
           LEFT JOIN jobs ON work_requests.job_id = jobs.id
           WHERE work_requests.status = 'Pending'
           ORDER BY work_requests.created_at ASC"""
    ).fetchall()
    conn.close()
    return render_template("pending_queue.html", requests=pending)


@app.route("/requests/<int:request_id>")
def request_detail(request_id):
    conn = db.get_db()
    work_request = _fetch_request_detail(conn, request_id)
    conn.close()

    if work_request is None:
        return redirect(url_for("pending_requests"))

    return render_template("request_detail.html", req=work_request)


@app.route("/requests/<int:request_id>/approve", methods=["POST"])
def approve_request(request_id):
    conn = db.get_db()
    work_request = conn.execute("SELECT * FROM work_requests WHERE id = ?", (request_id,)).fetchone()
    if work_request is None:
        conn.close()
        return redirect(url_for("pending_requests"))

    pm_notes = request.form.get("pm_notes", "").strip() or None

    if work_request["request_type"] == "New Job":
        job_number = db.generate_job_number(conn)
        cur = conn.execute(
            """INSERT INTO jobs (vessel_id, job_number, job_title, scope, status)
               VALUES (?, ?, ?, ?, 'Open')""",
            (work_request["vessel_id"], job_number, work_request["job_title"],
             work_request["description"]),
        )
        new_job_id = cur.lastrowid
        conn.execute(
            """UPDATE work_requests
               SET status = 'Approved', job_id = ?, pm_notes = ?, reviewed_at = datetime('now', 'localtime')
               WHERE id = ?""",
            (new_job_id, pm_notes, request_id),
        )
    else:  # Scope Change
        job = conn.execute("SELECT * FROM jobs WHERE id = ?", (work_request["job_id"],)).fetchone()
        if job is not None:
            updated_scope = f"{job['scope']}\n---\n{work_request['description']}" if job["scope"] else work_request["description"]
            conn.execute(
                "UPDATE jobs SET scope = ?, updated_at = datetime('now', 'localtime') WHERE id = ?",
                (updated_scope, job["id"]),
            )
        conn.execute(
            """UPDATE work_requests
               SET status = 'Approved', pm_notes = ?, reviewed_at = datetime('now', 'localtime')
               WHERE id = ?""",
            (pm_notes, request_id),
        )

    conn.commit()
    conn.close()
    return redirect(url_for("request_detail", request_id=request_id))


@app.route("/requests/<int:request_id>/reject", methods=["POST"])
def reject_request(request_id):
    pm_notes = request.form.get("pm_notes", "").strip() or None
    conn = db.get_db()
    conn.execute(
        """UPDATE work_requests
           SET status = 'Rejected', pm_notes = ?, reviewed_at = datetime('now', 'localtime')
           WHERE id = ?""",
        (pm_notes, request_id),
    )
    conn.commit()
    conn.close()
    return redirect(url_for("request_detail", request_id=request_id))


@app.route("/requests/history")
def request_history():
    vessel_id = request.args.get("vessel_id", type=int)
    request_type = request.args.get("request_type") or None
    status = request.args.get("status") or None

    query = """SELECT work_requests.*, vessels.name AS vessel_name,
                      jobs.job_number AS existing_job_number
               FROM work_requests
               JOIN vessels ON work_requests.vessel_id = vessels.id
               LEFT JOIN jobs ON work_requests.job_id = jobs.id
               WHERE 1=1"""
    params = []
    if vessel_id:
        query += " AND work_requests.vessel_id = ?"
        params.append(vessel_id)
    if request_type:
        query += " AND work_requests.request_type = ?"
        params.append(request_type)
    if status:
        query += " AND work_requests.status = ?"
        params.append(status)
    query += " ORDER BY work_requests.created_at DESC"

    conn = db.get_db()
    vessels = conn.execute("SELECT * FROM vessels ORDER BY name").fetchall()
    results = conn.execute(query, params).fetchall()
    conn.close()

    return render_template(
        "request_history.html",
        requests=results,
        vessels=vessels,
        selected_vessel_id=vessel_id,
        selected_request_type=request_type,
        selected_status=status,
    )


@app.route("/boat-builder/estimate")
def boat_builder_estimate_form():
    """Boat builder-facing: submit a labor/materials estimate against an existing job."""
    conn = db.get_db()
    vessels = conn.execute("SELECT * FROM vessels ORDER BY name").fetchall()

    selected_vessel_id = request.args.get("vessel_id", type=int)
    jobs = []
    if selected_vessel_id:
        jobs = conn.execute(
            "SELECT * FROM jobs WHERE vessel_id = ? ORDER BY job_number",
            (selected_vessel_id,),
        ).fetchall()
    conn.close()

    return render_template(
        "boat_builder_form.html",
        vessels=vessels,
        jobs=jobs,
        selected_vessel_id=selected_vessel_id,
        trade_roles=db.TRADE_ROLES,
    )


@app.route("/boat-builder/estimate", methods=["POST"])
def submit_boat_builder_estimate():
    vessel_id = request.form.get("vessel_id", type=int)
    job_id = request.form.get("job_id", type=int)
    description = request.form.get("description", "").strip()
    submitted_by = request.form.get("submitted_by", "").strip()
    materials_raw = request.form.get("materials_cost", "").strip()
    materials_cost = float(materials_raw) if materials_raw else None
    total_cost = float(request.form.get("total_cost", "0") or 0)

    trade_roles = request.form.getlist("trade_role[]")
    num_workers_list = request.form.getlist("num_workers[]")
    num_days_list = request.form.getlist("num_days[]")

    conn = db.get_db()
    cur = conn.execute(
        """INSERT INTO boat_builder_estimates
           (job_id, vessel_id, description, materials_cost, total_cost, submitted_by)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (job_id, vessel_id, description, materials_cost, total_cost, submitted_by),
    )
    estimate_id = cur.lastrowid

    for trade_role, workers_raw, days_raw in zip(trade_roles, num_workers_list, num_days_list):
        trade_role = trade_role.strip()
        if not trade_role or not workers_raw or not days_raw:
            continue
        num_workers = int(workers_raw)
        num_days = int(days_raw)
        conn.execute(
            """INSERT INTO boat_builder_labor_lines
               (estimate_id, trade_role, num_workers, num_days, worker_days)
               VALUES (?, ?, ?, ?, ?)""",
            (estimate_id, trade_role, num_workers, num_days, num_workers * num_days),
        )

    conn.commit()
    conn.close()

    return redirect(url_for("boat_builder_confirmation", estimate_id=estimate_id))


@app.route("/boat-builder/estimate/confirmation/<int:estimate_id>")
def boat_builder_confirmation(estimate_id):
    conn = db.get_db()
    estimate = conn.execute(
        """SELECT boat_builder_estimates.*, vessels.name AS vessel_name, jobs.job_number
           FROM boat_builder_estimates
           JOIN vessels ON boat_builder_estimates.vessel_id = vessels.id
           JOIN jobs ON boat_builder_estimates.job_id = jobs.id
           WHERE boat_builder_estimates.id = ?""",
        (estimate_id,),
    ).fetchone()
    conn.close()

    if estimate is None:
        return redirect(url_for("boat_builder_estimate_form"))

    return render_template("boat_builder_confirmation.html", estimate=estimate)


def _fetch_boat_builder_estimate(conn, estimate_id):
    estimate = conn.execute(
        """SELECT boat_builder_estimates.*, vessels.name AS vessel_name, jobs.job_number,
                  jobs.job_title AS job_title
           FROM boat_builder_estimates
           JOIN vessels ON boat_builder_estimates.vessel_id = vessels.id
           JOIN jobs ON boat_builder_estimates.job_id = jobs.id
           WHERE boat_builder_estimates.id = ?""",
        (estimate_id,),
    ).fetchone()
    labor_lines = conn.execute(
        "SELECT * FROM boat_builder_labor_lines WHERE estimate_id = ?", (estimate_id,)
    ).fetchall()
    return estimate, labor_lines


@app.route("/boat-builder/review")
def boat_builder_review_queue():
    conn = db.get_db()
    submitted = conn.execute(
        """SELECT boat_builder_estimates.*, vessels.name AS vessel_name, jobs.job_number
           FROM boat_builder_estimates
           JOIN vessels ON boat_builder_estimates.vessel_id = vessels.id
           JOIN jobs ON boat_builder_estimates.job_id = jobs.id
           WHERE boat_builder_estimates.status = 'Submitted'
           ORDER BY boat_builder_estimates.submitted_date ASC"""
    ).fetchall()
    conn.close()
    return render_template("boat_builder_review_queue.html", estimates=submitted)


@app.route("/boat-builder/review/<int:estimate_id>")
def boat_builder_review_detail(estimate_id):
    conn = db.get_db()
    estimate, labor_lines = _fetch_boat_builder_estimate(conn, estimate_id)
    conn.close()

    if estimate is None:
        return redirect(url_for("boat_builder_review_queue"))

    total_worker_days = sum(line["worker_days"] for line in labor_lines)

    return render_template(
        "boat_builder_review_detail.html",
        estimate=estimate,
        labor_lines=labor_lines,
        total_worker_days=total_worker_days,
    )


@app.route("/boat-builder/review/<int:estimate_id>/decision", methods=["POST"])
def boat_builder_review_decision(estimate_id):
    decision = request.form.get("decision")  # Approved / Revision Requested / Rejected
    reviewed_by = request.form.get("reviewed_by", "").strip() or None
    review_notes = request.form.get("review_notes", "").strip() or None

    conn = db.get_db()
    conn.execute(
        """UPDATE boat_builder_estimates
           SET status = ?, reviewed_by = ?, review_notes = ?, review_date = datetime('now', 'localtime')
           WHERE id = ?""",
        (decision, reviewed_by, review_notes, estimate_id),
    )
    conn.commit()
    conn.close()
    return redirect(url_for("boat_builder_review_detail", estimate_id=estimate_id))


@app.route("/boat-builder/history")
def boat_builder_history():
    vessel_id = request.args.get("vessel_id", type=int)
    status = request.args.get("status") or None
    start_date = request.args.get("start_date") or None
    end_date = request.args.get("end_date") or None

    query = """SELECT boat_builder_estimates.*, vessels.name AS vessel_name, jobs.job_number,
                      (SELECT COALESCE(SUM(worker_days), 0) FROM boat_builder_labor_lines
                       WHERE boat_builder_labor_lines.estimate_id = boat_builder_estimates.id) AS total_worker_days
               FROM boat_builder_estimates
               JOIN vessels ON boat_builder_estimates.vessel_id = vessels.id
               JOIN jobs ON boat_builder_estimates.job_id = jobs.id
               WHERE 1=1"""
    params = []
    if vessel_id:
        query += " AND boat_builder_estimates.vessel_id = ?"
        params.append(vessel_id)
    if status:
        query += " AND boat_builder_estimates.status = ?"
        params.append(status)
    if start_date:
        query += " AND date(boat_builder_estimates.submitted_date) >= date(?)"
        params.append(start_date)
    if end_date:
        query += " AND date(boat_builder_estimates.submitted_date) <= date(?)"
        params.append(end_date)
    query += " ORDER BY boat_builder_estimates.submitted_date DESC"

    conn = db.get_db()
    vessels = conn.execute("SELECT * FROM vessels ORDER BY name").fetchall()
    results = conn.execute(query, params).fetchall()
    conn.close()

    total_worker_days = sum(row["total_worker_days"] for row in results)

    return render_template(
        "boat_builder_history.html",
        estimates=results,
        vessels=vessels,
        selected_vessel_id=vessel_id,
        selected_status=status,
        start_date=start_date,
        end_date=end_date,
        total_worker_days=total_worker_days,
    )


def group_equipment_by_category(rows):
    grouped = {}
    for row in rows:
        grouped.setdefault(row["category"], []).append(row)
    return grouped


def calc_consumable_cost(quantity, cost_per_unit, start_date_str, end_date_str):
    """duration in days is inclusive of both start and end date; a blank end
    date means single-day use, per the spec."""
    start = date.fromisoformat(start_date_str)
    end = date.fromisoformat(end_date_str) if end_date_str else start
    num_days = max((end - start).days + 1, 1)
    return round(quantity * cost_per_unit * num_days, 2)


@app.route("/equipment/log")
def equipment_log_form():
    conn = db.get_db()
    vessels = conn.execute("SELECT * FROM vessels ORDER BY name").fetchall()
    equipment_rows = conn.execute(
        "SELECT * FROM equipment_catalog WHERE active = 1 ORDER BY category, equipment_name"
    ).fetchall()
    conn.close()

    return render_template(
        "equipment_log_form.html",
        vessels=vessels,
        equipment_by_category=group_equipment_by_category(equipment_rows),
        entry=None,
        today=date.today().isoformat(),
    )


@app.route("/equipment/log", methods=["POST"])
def submit_equipment_log():
    vessel_id = request.form.get("vessel_id", type=int)
    equipment_name = request.form.get("equipment_name", "").strip()
    start_date = request.form.get("start_date")
    end_date = request.form.get("end_date") or None
    quantity = float(request.form.get("quantity") or 1)
    unit = request.form.get("unit", "").strip()
    cost_per_unit = float(request.form.get("cost_per_unit") or 0)
    notes = request.form.get("notes", "").strip() or None
    logged_by = request.form.get("logged_by", "").strip() or None

    total_cost = calc_consumable_cost(quantity, cost_per_unit, start_date, end_date)

    conn = db.get_db()
    cur = conn.execute(
        """INSERT INTO consumables_log
           (vessel_id, equipment_name, start_date, end_date, quantity, unit,
            cost_per_unit, total_cost, notes, logged_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (vessel_id, equipment_name, start_date, end_date, quantity, unit,
         cost_per_unit, total_cost, notes, logged_by),
    )
    conn.commit()
    log_id = cur.lastrowid
    conn.close()

    return redirect(url_for("equipment_log_confirmation", log_id=log_id))


@app.route("/equipment/log/confirmation/<int:log_id>")
def equipment_log_confirmation(log_id):
    conn = db.get_db()
    entry = conn.execute(
        """SELECT consumables_log.*, vessels.name AS vessel_name
           FROM consumables_log JOIN vessels ON consumables_log.vessel_id = vessels.id
           WHERE consumables_log.id = ?""",
        (log_id,),
    ).fetchone()
    conn.close()

    if entry is None:
        return redirect(url_for("equipment_log_form"))

    return render_template("equipment_log_confirmation.html", entry=entry)


@app.route("/equipment/log/<int:log_id>/edit")
def edit_equipment_log_form(log_id):
    conn = db.get_db()
    entry = conn.execute("SELECT * FROM consumables_log WHERE id = ?", (log_id,)).fetchone()
    vessels = conn.execute("SELECT * FROM vessels ORDER BY name").fetchall()
    equipment_rows = conn.execute(
        "SELECT * FROM equipment_catalog WHERE active = 1 ORDER BY category, equipment_name"
    ).fetchall()
    conn.close()

    if entry is None:
        return redirect(url_for("equipment_history"))

    return render_template(
        "equipment_log_form.html",
        vessels=vessels,
        equipment_by_category=group_equipment_by_category(equipment_rows),
        entry=entry,
        today=date.today().isoformat(),
    )


@app.route("/equipment/log/<int:log_id>/edit", methods=["POST"])
def update_equipment_log(log_id):
    vessel_id = request.form.get("vessel_id", type=int)
    equipment_name = request.form.get("equipment_name", "").strip()
    start_date = request.form.get("start_date")
    end_date = request.form.get("end_date") or None
    quantity = float(request.form.get("quantity") or 1)
    unit = request.form.get("unit", "").strip()
    cost_per_unit = float(request.form.get("cost_per_unit") or 0)
    notes = request.form.get("notes", "").strip() or None
    logged_by = request.form.get("logged_by", "").strip() or None

    total_cost = calc_consumable_cost(quantity, cost_per_unit, start_date, end_date)

    conn = db.get_db()
    conn.execute(
        """UPDATE consumables_log
           SET vessel_id = ?, equipment_name = ?, start_date = ?, end_date = ?, quantity = ?,
               unit = ?, cost_per_unit = ?, total_cost = ?, notes = ?, logged_by = ?
           WHERE id = ?""",
        (vessel_id, equipment_name, start_date, end_date, quantity, unit,
         cost_per_unit, total_cost, notes, logged_by, log_id),
    )
    conn.commit()
    conn.close()

    return redirect(url_for("equipment_history"))


@app.route("/equipment/log/<int:log_id>/delete", methods=["POST"])
def delete_equipment_log(log_id):
    conn = db.get_db()
    conn.execute("DELETE FROM consumables_log WHERE id = ?", (log_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("equipment_history"))


@app.route("/equipment/history")
def equipment_history():
    vessel_id = request.args.get("vessel_id", type=int)
    start_date = request.args.get("start_date") or None
    end_date = request.args.get("end_date") or None
    equipment_search = request.args.get("equipment") or None

    query = """SELECT consumables_log.*, vessels.name AS vessel_name
               FROM consumables_log JOIN vessels ON consumables_log.vessel_id = vessels.id
               WHERE 1=1"""
    params = []
    if vessel_id:
        query += " AND consumables_log.vessel_id = ?"
        params.append(vessel_id)
    if start_date:
        query += " AND date(consumables_log.start_date) >= date(?)"
        params.append(start_date)
    if end_date:
        query += " AND date(consumables_log.start_date) <= date(?)"
        params.append(end_date)
    if equipment_search:
        query += " AND consumables_log.equipment_name LIKE ?"
        params.append(f"%{equipment_search}%")
    query += " ORDER BY consumables_log.start_date DESC"

    conn = db.get_db()
    vessels = conn.execute("SELECT * FROM vessels ORDER BY name").fetchall()
    entries = conn.execute(query, params).fetchall()
    conn.close()

    summary = {}
    grand_total = 0.0
    for entry in entries:
        summary[entry["equipment_name"]] = summary.get(entry["equipment_name"], 0.0) + entry["total_cost"]
        grand_total += entry["total_cost"]

    return render_template(
        "equipment_history.html",
        entries=entries,
        vessels=vessels,
        selected_vessel_id=vessel_id,
        start_date=start_date,
        end_date=end_date,
        equipment_search=equipment_search or "",
        summary=sorted(summary.items(), key=lambda item: -item[1]),
        grand_total=grand_total,
    )


@app.route("/equipment/report")
def equipment_weekly_report():
    vessel_id = request.args.get("vessel_id", type=int)
    week_start_str = request.args.get("week_start")
    if week_start_str:
        week_start = date.fromisoformat(week_start_str)
    else:
        today = date.today()
        week_start = today - timedelta(days=today.weekday())  # Monday of this week
    week_end = week_start + timedelta(days=6)

    query = """SELECT consumables_log.*, vessels.id AS v_id, vessels.name AS vessel_name
               FROM consumables_log JOIN vessels ON consumables_log.vessel_id = vessels.id
               WHERE date(consumables_log.start_date) BETWEEN date(?) AND date(?)"""
    params = [week_start.isoformat(), week_end.isoformat()]
    if vessel_id:
        query += " AND consumables_log.vessel_id = ?"
        params.append(vessel_id)
    query += " ORDER BY vessels.name, consumables_log.start_date"

    conn = db.get_db()
    vessels = conn.execute("SELECT * FROM vessels ORDER BY name").fetchall()
    entries = conn.execute(query, params).fetchall()
    conn.close()

    vessel_groups = {}
    for entry in entries:
        group = vessel_groups.setdefault(entry["vessel_name"], {"entries": [], "total": 0.0})
        group["entries"].append(entry)
        group["total"] += entry["total_cost"]

    return render_template(
        "equipment_weekly_report.html",
        vessel_groups=vessel_groups,
        vessels=vessels,
        selected_vessel_id=vessel_id,
        week_start=week_start.isoformat(),
        week_end=week_end.isoformat(),
    )


if __name__ == "__main__":
    db.setup()
    app.run(host="0.0.0.0", port=5000, debug=True)
