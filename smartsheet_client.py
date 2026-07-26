"""
Orams Marine — Coatings Diary Smartsheet client
------------------------------------------------
Same TOOL_SECRET-authenticated webapp used by the estimate tool
(see ../Estimate Generator/webapp_client.py and smartsheet_accept_webapp.gs).
This file never holds the real Smartsheet API token — only TOOL_SECRET,
which can create pending rows, attach PDFs, or read the painter job list,
but grants no broader Smartsheet account access.
"""

import json
import os
import time
import base64
import urllib.request
import urllib.error
from pathlib import Path

WEBAPP_BASE_URL = "https://script.google.com/macros/s/AKfycbyViRlH0IzZNQEyxQnOVWhKnOVdbnfyyhUfCEkoe6pihp0rM1AbkRjzcrmArXiSKhtwLA/exec"
# Same TOOL_SECRET as the estimate tool - one shared secret for both tools,
# rather than a second one to issue/rotate. ORAMS_TOOL_SECRET env var
# overrides this when set (see deploy notes in the estimate tool's BUILD.md).
TOOL_SECRET = os.environ.get("ORAMS_TOOL_SECRET", "8f14e45f-ceea-467e-adcd-fce1cd456a67")

PAINTER_JOBS_CACHE_TTL_SECONDS = 300  # matches the webapp's own 5-min cache
PAINTER_JOBS_CACHE_FILE = Path(__file__).parent / "painter_jobs_cache.json"


def _tool_request(action, body=None, timeout=15):
    """POST to a TOOL_SECRET-authenticated webapp endpoint. Raises on failure."""
    payload = dict(body or {})
    payload["secret"] = TOOL_SECRET
    data = json.dumps(payload).encode()
    url = f"{WEBAPP_BASE_URL}?action={action}"
    req = urllib.request.Request(url, data=data, method="POST",
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode())
    except urllib.error.URLError as e:
        raise RuntimeError(f"Could not reach the webapp ({action}): {e}")

    if not result.get("ok"):
        raise RuntimeError(f"Webapp rejected {action}: {result.get('reason', 'unknown error')}")
    return result


def get_painter_jobs(force_refresh=False):
    """
    Returns {vessel_name: [{job_number, description, row_id, sheet_id,
    department}, ...]}, read from each vessel's Sign Off & Changes sheet.
    Falls back to the last-known-good local cache if the webapp is
    unreachable, so job selection still works offline / mid-outage.
    """
    if not force_refresh:
        cached = _read_cache()
        if cached is not None and (time.time() - cached["fetched_at"]) < PAINTER_JOBS_CACHE_TTL_SECONDS:
            return cached["jobs"]

    try:
        result = _tool_request("getPainterJobs", {"forceRefresh": force_refresh})
        jobs = result["jobs"]
        _write_cache(jobs)
        return jobs
    except Exception as e:
        cached = _read_cache()
        if cached is not None:
            print(f"  Could not refresh painter jobs from server ({e}) - using last-known copy "
                  f"from {time.strftime('%d %b %Y %H:%M', time.localtime(cached['fetched_at']))}.")
            return cached["jobs"]
        raise RuntimeError(
            f"Could not load painter jobs from the server, and no local cache exists yet: {e}"
        )


def _read_cache():
    if not PAINTER_JOBS_CACHE_FILE.exists():
        return None
    try:
        with open(PAINTER_JOBS_CACHE_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _write_cache(jobs):
    try:
        with open(PAINTER_JOBS_CACHE_FILE, "w") as f:
            json.dump({"fetched_at": time.time(), "jobs": jobs}, f, indent=2)
    except OSError:
        pass  # cache is best-effort - don't block on a write failure


def attach_pdf_to_row(sheet_id, row_id, file_path):
    """Uploads file_path as an attachment on the job's existing Smartsheet row."""
    with open(file_path, "rb") as f:
        file_bytes = f.read()
    _tool_request("attachPdf", {
        "sheetId": sheet_id,
        "rowId": row_id,
        "filename": os.path.basename(file_path),
        "fileBase64": base64.b64encode(file_bytes).decode(),
    })
