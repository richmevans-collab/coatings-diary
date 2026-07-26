# Boat Builder Estimate Module Spec

## Goal
Give Orams' internal boat builders (fabrication/finishing team) a formal way to submit an estimate for a job — labor and materials — the same way external contractors do. This gives PMs visibility into expected workload (workers x days) per job, feeding into staffing/workload prediction, and gives a cost estimate where previously there was none.

This is a separate entry point from the contractor estimate flow — boat builders aren't submitting a PDF invoice, they're filling in a structured form.

---

## Why This Matters
- Boat builder jobs currently have no formal estimate — PMs can't predict cost or staffing needs
- By having boat builders estimate workers/days per job, PMs (and management) can see workload building up across vessels and plan staffing/capacity ahead of time
- This estimate becomes a data point for the future workload/staffing dashboard (per COO's ask for worker-days per job)

---

## Screens

### 1. Boat Builder Estimate Form (boat builder-facing)
**Purpose:** boat builder fills this in when quoting a job (new job or scope change already in the Request Work queue).

**Fields:**
- Vessel (dropdown)
- Job (dropdown — filtered to that vessel's jobs; must already exist, i.e. approved via Request Work)
- Estimate description (text area — what's being built/done)
- Labor breakdown (repeatable rows):
  - Trade/role (dropdown or text, e.g. "Boat Builder", "Apprentice")
  - Number of workers
  - Number of days
  - (system auto-calculates worker-days = workers × days per row)
- Materials cost (optional number — lump sum, or itemized if needed later)
- Total estimated cost (auto-calculated: labor rate × worker-days + materials, OR manual override if rates aren't set up yet)
- Submitted by (name, auto-filled if logged in)
- Submit button

**Confirmation:** "Estimate submitted — PM will review."

### 2. Boat Builder Estimate Review (PM-facing)
**Purpose:** PM reviews the submitted estimate before it's approved/locked in.

**Display:**
- Vessel, job, submitted-by, date
- Labor breakdown table (trade, workers, days, worker-days)
- Materials cost
- Total estimated cost
- Approve / Request Revision / Reject buttons (with notes field)

On approval: estimate is locked to the job, worker-days data becomes available for the workload dashboard (future).

### 3. Boat Builder Estimate History (read-only)
**Purpose:** see all boat builder estimates across vessels — useful for workload planning.

**Display:**
- Filterable by vessel, date range, status
- Table: Vessel, Job, Total Worker-Days, Total Cost, Status
- Summary: total worker-days across filtered estimates (early building block for workload/staffing dashboard)

---

## Data Model

**boat_builder_estimates table:**
- estimate_id (primary key)
- job_id (foreign key — jobs)
- vessel_id (foreign key — vessels)
- description (text)
- materials_cost (decimal, nullable)
- total_cost (decimal)
- status (Submitted / Approved / Revision Requested / Rejected)
- submitted_by (name)
- submitted_date (timestamp)
- reviewed_by (PM name, nullable)
- review_notes (text, nullable)
- review_date (timestamp, nullable)

**boat_builder_labor_lines table:**
- line_id (primary key)
- estimate_id (foreign key — boat_builder_estimates)
- trade_role (string, e.g. "Boat Builder", "Apprentice")
- num_workers (integer)
- num_days (integer)
- worker_days (integer, auto-calculated: num_workers × num_days)

---

## What NOT to Build Yet
- No automatic labor rate lookup (materials/labor costed manually or as lump sum for now, since labor rates per trade may not be standardized yet — confirm before building this in)
- No Smartsheet sync (feeds into internal workload view only, for now)
- No login/auth (internal use only)
- No automatic workload dashboard yet — this module just captures the data; the dashboard that visualizes it (per-vessel and yard-wide worker-day totals) is a Phase 3/4 item, not part of this build

---

## Access Control & Visibility (Phase 3 Dashboard)
- **Visible to:** Boat Builders (submit only), PM (review + full history), Manager (history/reporting only)
- **Visible on:** All vessels where boat building jobs exist
- **Triggers in dashboard:** Boat builder logs in → sees "Submit Estimate" for jobs assigned to them; PM logs in → sees "Boat Builder Estimates" in pending review queue

---

## Instructions to Claude Code
1. Extend the existing Flask app — add `boat_builder_estimates` and `boat_builder_labor_lines` tables to SQLite
2. Build the three screens: Boat Builder Estimate Form (with repeatable labor line rows), Review screen (PM approve/reject/revise), History (filterable, with worker-days summary)
3. Auto-calculate worker-days per labor line and total cost on submit
4. Test locally: submit an estimate with 2-3 labor lines for a job, review/approve it, confirm history shows correct worker-days totals

## Next Steps After This Works
- Standardize labor rates per trade (once confirmed) to auto-calculate labor cost, not just worker-days
- Feed worker-days data into the Phase 3/4 workload & staffing dashboard (per COO's original ask — compare demand against known crew size/headcount baseline)
- Smartsheet sync if useful for PM visibility
