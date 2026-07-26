"""
Coatings Diary - phone-first web form for painters to log coating data per coat.
Replaces the paper "Coatings Diary" sheet. See coatings-diary-app-spec.md for the full spec.

Run locally with: python app.py
Then open http://<your-laptop-ip>:5000 on a phone on the same wifi network.
"""
import math
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for
from werkzeug.utils import secure_filename

import db

app = Flask(__name__)

UPLOAD_FOLDER = Path(__file__).parent / "uploads"
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


@app.route("/")
def start():
    """Screen 1: pick a vessel, then a job for that vessel."""
    conn = db.get_db()
    vessels = conn.execute("SELECT * FROM vessels ORDER BY name").fetchall()

    selected_vessel_id = request.args.get("vessel_id", type=int)
    jobs = []
    if selected_vessel_id:
        jobs = conn.execute(
            "SELECT * FROM jobs WHERE vessel_id = ? ORDER BY job_number, area",
            (selected_vessel_id,),
        ).fetchall()
    conn.close()

    return render_template(
        "start.html",
        vessels=vessels,
        jobs=jobs,
        selected_vessel_id=selected_vessel_id,
    )


@app.route("/log-coat/<int:job_id>")
def log_coat_form(job_id):
    """Screen 2: the core coat-logging form for a given job."""
    conn = db.get_db()
    job = conn.execute(
        """SELECT jobs.*, vessels.name AS vessel_name
           FROM jobs JOIN vessels ON jobs.vessel_id = vessels.id
           WHERE jobs.id = ?""",
        (job_id,),
    ).fetchone()
    conn.close()

    if job is None:
        return redirect(url_for("start"))

    return render_template("log_coat.html", job=job)


@app.route("/log-coat/<int:job_id>", methods=["POST"])
def submit_coat(job_id):
    """Handle the coat form submission: save data + optional tin photo."""
    conn = db.get_db()
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if job is None:
        conn.close()
        return redirect(url_for("start"))

    def to_float(field):
        value = request.form.get(field, "").strip()
        return float(value) if value else None

    coat_number = request.form.get("coat_number", type=int)
    humidity = to_float("humidity")
    air_temp = to_float("air_temp")
    surface_temp = to_float("surface_temp")
    product_name = request.form.get("product_name", "").strip()
    wft = to_float("wft")
    dew_point = calculate_dew_point(air_temp, humidity)

    tin_photo_filename = None
    photo = request.files.get("tin_photo")
    if photo and photo.filename and allowed_file(photo.filename):
        app.config["UPLOAD_FOLDER"].mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        safe_name = secure_filename(photo.filename)
        tin_photo_filename = f"job{job_id}_{timestamp}_{safe_name}"
        photo.save(app.config["UPLOAD_FOLDER"] / tin_photo_filename)

    conn.execute(
        """INSERT INTO coating_entries
           (job_id, humidity, air_temp, surface_temp, dew_point, product_name, wft,
            tin_photo_filename, coat_number)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (job_id, humidity, air_temp, surface_temp, dew_point, product_name, wft,
         tin_photo_filename, coat_number),
    )
    conn.commit()
    conn.close()

    return redirect(url_for("confirmation", job_id=job_id))


@app.route("/confirmation/<int:job_id>")
def confirmation(job_id):
    """Screen 3: simple success message with next-action buttons."""
    conn = db.get_db()
    job = conn.execute(
        """SELECT jobs.*, vessels.name AS vessel_name
           FROM jobs JOIN vessels ON jobs.vessel_id = vessels.id
           WHERE jobs.id = ?""",
        (job_id,),
    ).fetchone()
    conn.close()

    if job is None:
        return redirect(url_for("start"))

    return render_template("confirmation.html", job=job)


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


if __name__ == "__main__":
    db.setup()
    app.run(host="0.0.0.0", port=5000, debug=True)
