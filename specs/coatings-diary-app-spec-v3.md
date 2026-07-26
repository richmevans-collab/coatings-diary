# Coatings Diary App — Build Spec v3 (for Claude Code)

Supersedes v2. Two changes from v2:

1. **This is a browser-based web app**, not a standalone mobile-only tool —
   it shares a visual identity and nav shell with the Orams estimate tool
   (same navy/red/hairline-grey brand, same top nav bar with an
   Estimates / Coatings Diary tab switcher).
2. **Photo attachments are general-purpose**, not tied to the paint tin
   specifically — a stage entry can have any number of attached photos
   (tin, surface condition, defects, general progress shots, etc.), not a
   single `tin_photo_filename` field.

Everything else from v2 (data model sections, PDF generation, Smartsheet
filing) carries forward as described below, updated for these two changes.

Keep this in its own folder (`coatings-diary/`), separate from the
estimate generator — same GitHub account, own repo, but sharing the same
top-level nav shell/brand assets so the two feel like one product.

## Data model

### `vessels`
- id
- name (Pangaea, Fidelis, Aegle, Bundalong)

### `jobs`
- id
- vessel_id (FK)
- job_number
- area
- client (optional)
- painter (optional)
- inspector (optional)
- reference_documents (optional)
- created_at

### `stage_entries`
One row per stage per job. `stage` is one of: `substrate`, `coat_1`,
`coat_2`, `coat_3`, `coat_4`.

- id
- job_id (FK)
- stage (enum)
- created_at

**Climate Data**
- date_time, conditions, rh_percent, air_temp, dew_point, surface_temp,
  paint_yes_no

**Surface Preparation** (typically only filled at Substrate stage; leave
skippable for coat stages)
- prep_date_time, cleanliness, profile_sanding
- *(placeholder fields — swap in your exact list before build)*

**Paint / Application**
- paint_date_time, product_name, batch_no_a, batch_no_b, thinning_percent,
  thinning_product, volume_litres, induction_time, recoat_time_min,
  recoat_time_max, wft

**DFT & Inspection**
- dft_date_time, dft_readings (comma-separated spot readings) — computed
  dft_number, dft_min, dft_max, dft_average, dft_std_dev
- appearance, pass_fail_repair

### `stage_photos` (new — replaces `tin_photo_filename`)
- id
- stage_entry_id (FK)
- filename
- uploaded_at

A stage entry can have zero or more attached photos. No categorisation
required for the MVP — just a simple multi-photo attachment.

## Screens

Shared top nav bar across both tools: Orams wordmark/logo on the left,
tab switcher on the right (**Estimates** / **Coatings Diary**), navy
background, red underline on the active tab.

### 1. Start screen
- Vessel picker (Pangaea / Fidelis / Aegle / Bundalong)
- Job list for the selected vessel, each showing job number, area, and a
  stage-progress indicator (dot per stage: Substrate, Coat 1–4)
- Selecting a job with an incomplete stage goes to Log Stage; a fully
  logged job goes to the Job Summary screen

### 2. Log Stage screen
One scroll, four section cards in order: **Climate Data — Surface
Preparation (skippable) — Paint / Application — DFT & Inspection**, each
with its own header and a light grey background so sections read as
distinct blocks. Below the sections: an **"Add photos"** control
(multiple files, no cropping/labelling required). Sticky submit bar at
the bottom.

Date/time fields auto-capture on load but stay editable.

### 3. Job Summary screen
- Compiled read-only grid (Section × Substrate/Coat 1–4), matching the
  paper form's shape, with a checkmark per completed cell
- **Generate PDF** button
- **Submit to Smartsheet** button (disabled until a PDF has been
  generated)
- Status confirmation once each action completes

## PDF generation

- One PDF per job, generated on demand from the Job Summary screen
- Same Orams branded house style used elsewhere (navy/red/hairline-grey
  cover + data grid, same logo asset)
- Include attached photos as an appendix (thumbnail grid or one per
  page) rather than a single tin-photo callout, since photos are now
  general-purpose
- Filename: `{Job Number} - Coatings Diary - {Area}.pdf`

## Submit to Smartsheet

- Attaches the generated PDF to the job's existing Smartsheet row
  (matched on job number) — reuse the attach pattern already built for
  `create_orams_estimate.py` rather than a new integration path
- On success: confirmation showing which sheet/row it filed against
- No two-way sync for now — this is a one-way file/attach action

## What NOT to build yet
- No login/auth system (trusted internal use for now)
- No admin/reporting dashboard
- No photo categorisation, batch-number OCR, or Paint Acceptance tie-in
  yet

## Tech stack
- Backend: Python + Flask
- Database: SQLite
- Frontend: HTML/CSS matching the estimate tool's brand (navy `#152744`,
  red `#C8262E`, hairline grey `#E4E7EC`), shared nav shell component if
  practical, mobile-responsive but no longer mobile-only
- Photo upload: local `/uploads` folder, one or more files per stage
  entry linked via `stage_photos`

## Instructions to Claude Code
1. Scaffold `coatings-diary/` with `app.py`, `templates/`, `requirements.txt`
2. Initialize SQLite with the schema above (including `stage_photos`);
   seed the four vessels and a couple of test jobs
3. Build the shared nav shell + three screens above
4. Support multiple photo uploads per stage entry
5. Build PDF generation reusing the branded template/logo from
   `create_orams_estimate.py`, with a photo appendix
6. Build the Smartsheet attach step reusing that script's existing
   attach-to-row logic/credentials
7. Keep code simple and well-commented — two-way Smartsheet sync and
   Paint Acceptance tie-in are future steps, not part of this build

## Addendum (as-built): live job pull from Smartsheet

Beyond this spec, the Start screen's job list (job number + description)
is pulled live from each vessel's Sign Off & Changes sheet in Smartsheet,
not locally seeded. This required:
- A new read-only `getPainterJobs` action added to the shared Apps Script
  webapp (`smartsheet_accept_webapp.gs`), reusing the existing
  `getVesselConfig_` sheet lookup and the same TOOL_SECRET auth as the
  estimate tool.
- `smartsheet_client.py` (mirrors `webapp_client.py`) to call it, with a
  local disk cache fallback so job selection still works if Smartsheet is
  briefly unreachable.
- `jobs.description`/`sheet_id`/`sheet_row_id` columns, upserted on each
  Start-screen visit; `sheet_id`/`sheet_row_id` are what "Submit to
  Smartsheet" attaches the generated PDF to.
