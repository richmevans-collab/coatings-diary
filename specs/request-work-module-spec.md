# Request Work Module — Build Spec for Claude Code
## (Combined Job Creation + Scope Change)

## Context
New job requests and scope changes on existing jobs are really the same underlying pattern: someone wants work added or changed, and it needs a PM decision before anything moves forward. The only real difference is whether it results in a brand new Orams job number or just logs against an existing job.

For now, skip the standalone contractor-facing intake form (email is fine for how a request reaches you) — this spec is about **your side**: a place where you log incoming requests, decide new-job vs scope-change, and approve/reject with a clear record, rather than it all living in your inbox and memory.

This extends the existing `coatings-diary/` Flask app — same SQLite database, same GitHub repo, same UI patterns.

## Goal
A tool with two entry points feeding the same queue:
1. **Contractor-facing form** — contractors can submit a request directly (new job or scope change) instead of emailing
2. **PM quick-log screen** — for requests that still come in by phone/email/in person, you log them yourself in under a minute
3. You approve or reject from one combined queue regardless of how the request arrived
4. On approval:
   - If new job → system generates a job number (JOB-YYYY-NNN)
   - If scope change → it's logged against the existing job, no new number
5. Keep a running history of all requests and decisions per vessel/job

Both entry points write to the same `work_requests` table, so nothing about the approval/history side changes based on how the request came in.

## Data Model

Extend the existing SQLite schema:

### `vessels` table (already exists from Coatings Diary)
- id, name

### `jobs` table (NEW if not already present)
- id (primary key)
- vessel_id (FK to vessels)
- orams_job_number (text, unique, e.g. "JOB-2026-001")
- job_title (text)
- scope (text)
- status (text — Open, Estimated, Approved, In Progress, Complete, Signed Off)
- created_at (timestamp)
- updated_at (timestamp)

### `work_requests` table (NEW — combined job creation + scope change log)
- id (primary key)
- vessel_id (FK to vessels)
- request_type (text — "New Job" or "Scope Change")
- job_id (FK to jobs, nullable — set if this is a scope change against an existing job; null if new job until approved)
- job_title (text — used if New Job; can be blank if Scope Change, since it inherits the existing job's title)
- description (text — what's being requested/changed)
- requested_by (text — contractor/person name)
- requested_by_contact (text, nullable — email or phone)
- reason (text — dropdown: New Work, Design Change, Damage Found, Clarification, Other)
- estimated_cost (decimal, nullable)
- status (text — Pending, Approved, Rejected)
- pm_notes (text, nullable)
- created_at (timestamp — when you logged it)
- reviewed_at (timestamp, nullable — when you approved/rejected)

## Screens

### 1. Request Work Form (shared — contractor-facing AND PM quick-log)
**Purpose:** the single form used both by contractors submitting directly and by you logging a request that came in another way. Same fields either way — just accessed via a shared link (contractors) or from your own dashboard (you).

**Fields:**
- Vessel (dropdown)
- Type: "New Job" or "Scope Change" (toggle/radio buttons)
  - If "Scope Change" selected → Job dropdown appears, filtered to that vessel's existing jobs
  - If "New Job" selected → Job Title text field appears instead
- Description (text area — what's being asked for)
- Requested by (text — contractor/person name)
- Contact (optional — email/phone, useful for following up)
- Reason (dropdown: New Work, Design Change, Damage Found, Clarification, Other)
- Estimated cost (optional number)
- Submit button

**Confirmation screen (contractor-facing use):**
- "Request submitted — We'll review it and get back to you."

This creates a `work_requests` row with status = Pending either way. You can log it and decide later, or approve immediately (see below).

### 2. Pending Requests Queue
**Purpose:** see everything awaiting your decision, approve or reject.

**Display:**
- List of pending requests: vessel, type (New Job/Scope Change), title or existing job reference, description preview, requested by, date logged
- Click a row for full detail

**Detail view:**
- Full description, reason, requester contact, estimated cost
- PM notes field (free text — approval notes or rejection reason)
- Approve button
- Reject button

**On Approve:**
- If "New Job": generate job number (JOB-YYYY-NNN format, sequential per year), create row in `jobs` table (status = Open), link back to the work_request
- If "Scope Change": no new job number — just mark the request Approved, and optionally append the description to that job's scope/notes
- Mark `work_requests` row as Approved, set reviewed_at

**On Reject:**
- Mark `work_requests` row as Rejected, set reviewed_at, save PM notes (reason)

### 3. Request & Job History (read-only)
**Purpose:** look back at everything — approved, rejected, new jobs, scope changes — per vessel or overall.

**Display:**
- Filterable list (by vessel, by type, by status)
- Each row: vessel, type, title/job reference, requested by, date, status, decision date
- Click through to see full detail including PM notes

## Job Number Generation Logic
Same as before: `JOB-YYYY-NNN`, sequential per calendar year, only generated on approval of a "New Job" request. Query max NNN for the current year in `jobs`, increment by 1, or start at 001.

## What NOT to Build Yet
- No automated email notifications to contractors on approval/rejection (manual for now — you email them the job number or decision yourself)
- No Smartsheet/MYOB sync yet (manual for now, same as before)
- No login/auth (internal use only — contractors access the form via a shared link, no accounts)

## Success Criteria
- You can log any incoming request (new job or scope change) in under a minute
- You have one queue to work through instead of scattered emails
- Approving a new job generates a clean sequential job number automatically
- Approving a scope change logs it against the right existing job with no confusion
- You've got a searchable history of every request/decision, per vessel

## Instructions to Claude Code
1. Extend the existing `coatings-diary/` Flask app — add the `jobs` and `work_requests` tables to the SQLite schema
2. Build the three screens: Request Work Form (shared contractor/PM entry point), Pending Requests Queue (with approve/reject + detail view), and Request & Job History
3. Implement job number generation (JOB-YYYY-NNN) on approval of New Job requests only
4. Keep the UI consistent with the Coatings Diary app's style (simple, mobile-friendly, large buttons)
5. Test locally: submit a few New Job and Scope Change requests through the form, approve/reject some, confirm job numbers generate correctly and history shows everything

## Next Steps After This Works
- Automated email notifications to contractors on approval/rejection
- Smartsheet sync on approval (write job number/status back to the vessel's Refit sheet)
- Tie into Commissioning module (approved jobs feed into sign-off tracking)
