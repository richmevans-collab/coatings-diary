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


if __name__ == "__main__":
    db.setup()
    app.run(host="0.0.0.0", port=5000, debug=True)
