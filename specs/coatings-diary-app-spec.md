# Coatings Diary App — Build Spec for Claude Code

## Context
Orams Marine currently uses paper "Coatings Diary" sheets (International Paint style) for painters to log climate and coating data per coat, per job. This is slow, error-prone, and creates re-typing work. This app replaces the paper form with a simple mobile web form painters fill in directly, feeding into the existing Paint Acceptance sign-off workflow.

This is a companion tool to the existing `create_orams_estimate.py` estimate generator — keep it as a **separate folder/repo** (e.g. `coatings-diary/`), not merged into the estimate generator codebase. Same GitHub account, own folder.

## Goal
A dead-simple phone-first web app where a painter:
1. Selects the Vessel and Job/Area they're working on
2. Logs one coat's data in as few taps as possible
3. Optionally attaches a photo of the paint tin (for batch traceability instead of typing batch numbers)
4. Submits — data is stored and ready to feed the Paint Acceptance sign-off later

## Tech stack (keep minimal)
- **Backend:** Python + Flask
- **Database:** SQLite (single file, no server setup needed)
- **Frontend:** Plain HTML + CSS, mobile-first, large tap targets, no JS framework needed
- **Photo upload:** simple file input, store image in a local `/uploads` folder, filename linked to the diary entry in the database

## Data model

### `vessels` table
- id
- name (e.g. Pangaea, Fidelis, Aegle, Bundalong)

### `jobs` table
- id
- vessel_id (FK)
- job_number (Orams job number)
- area (e.g. "Transducers", "Topsides")

### `coating_entries` table
- id
- job_id (FK)
- created_at (auto, defaults to now — painter shouldn't need to type this)
- humidity (number, %)
- air_temp (number, °C)
- surface_temp (number, °C)
- dew_point (number, °C, optional — calculate/display if possible, else leave blank)
- product_name (text, free text or dropdown of common products)
- wft (number — wet film thickness)
- tin_photo_filename (text, nullable — path to uploaded photo)
- coat_number (integer — Coat 1, 2, 3, 4)

## Screens

### 1. Start screen
- Dropdown: select Vessel
- Dropdown: select Job (filtered by vessel, shows job number + area)
- Button: "Log a coat"

### 2. Log Coat screen (the core screen — keep this to ONE scroll, no tabs/menus)
Fields, top to bottom:
- Coat number (simple stepper or dropdown: 1/2/3/4)
- Humidity (%)
- Air Temp (°C)
- Surface Temp (°C)
- Product name (text input, or dropdown if a fixed product list is provided later)
- WFT (wet film thickness)
- Photo of tin (camera/file input — optional, big clear button)
- Submit button (large, bottom of screen, sticky if possible)

Date/time should NOT be a field the painter has to fill in — capture automatically on submit.

Leave batch number, thinning %, induction time, recoat time OFF this form for now (MVP) — these are lower-priority fields from the paper form and can be added later if needed.

### 3. Confirmation
- Simple "Coat logged ✓" message
- Button to log another coat (same job) or return to start screen

## What NOT to build yet
- No login/auth system (assume trusted internal use for now — can add later)
- No admin/reporting dashboard yet (that's a separate future piece tying into Paint Acceptance sign-off)
- No integration with Smartsheet yet (future step — for now just get local data capture working)

## Instructions to Claude Code
1. Scaffold a new folder `coatings-diary/` with a Flask app (`app.py`), templates folder, and a `requirements.txt`
2. Initialize the SQLite database with the schema above, with a small seed script to add the known vessels (Pangaea, Fidelis, Aegle, Bundalong) and a couple of test jobs
3. Build the three screens above, mobile-first CSS (large buttons, big readable text, minimal typing)
4. Make sure it runs locally with `python app.py` and is testable on a phone browser on the same wifi network (bind to `0.0.0.0`)
5. Keep the code simple and well-commented — this will likely be extended later (batch number OCR from tin photo, Smartsheet sync, tie-in to Paint Acceptance sign-off)

## Next steps after this MVP works (not part of this build)
- Tie completed coat logs to the Paint Acceptance sign-off form (pre-fill DFT/appearance data)
- Push data to Smartsheet instead of/alongside local SQLite
- Deploy to the Google Cloud VM alongside the estimate generator tool
