# Equipment & Consumables Log Module Spec

## Goal
PMs log rentals and consumables used during a project (scissor lifts, forklifts, storage, electrical boxes, power leads, etc.) with standard rates. Weekly, you pull a report grouped by vessel to invoice the boat owner.

No real-time cost tracking or Smartsheet sync — just a clear log so you know what to charge each week.

---

## Equipment/Consumables Catalog (standard rates, editable by admin)
Predefined list with categories:
- **Daily Rentals:** Scissor Lift, Forklift, Scaffolding, Confined Space Equipment
- **Storage:** On-Site Storage (per sqm/day), Off-Site Storage (per sqm/day)
- **Electrical & Power:** Electrical Box Rental, Power Lead Rental, Generator
- **Other Consumables:** (extensible)

Each has:
- Equipment name (e.g. "Scissor Lift")
- Category
- Unit (day, week, per item, per sqm, etc.)
- Standard rate (e.g. $150/day)
- Notes (e.g. "large", "diesel", optional for variants)

---

## Screens

### 1. Log Equipment/Consumable Use (PM entry point)
**Purpose:** quickly record when something is rented/used.

**Fields:**
- Vessel (dropdown)
- Equipment name (searchable dropdown, filtered by category or all)
- Start date (date picker, defaults to today)
- End date (date picker, optional — if blank, assumes single-day use)
- Quantity (number, defaults to 1)
- Unit (auto-filled from equipment catalog, e.g. "day", "sqm")
- Cost per unit (auto-filled from standard rate, can override if negotiated differently)
- Notes (optional — e.g. "for scaffolding area near mast", "returned early")
- Submit button

**Confirmation:** "Logged — [equipment name] for [vessel] from [start] to [end]"

This creates a `consumables_log` row with auto-calculated total cost = quantity × cost per unit × duration (in days).

### 2. Consumables History (searchable list, PM-facing)
**Purpose:** review all logged usage, search/filter, and generate weekly reports.

**Display:**
- Filters: Vessel (dropdown), Date range (week/month picker), Equipment name (searchable)
- Table: Date (start-end), Equipment, Quantity, Rate, Total, Notes, Edit/Delete buttons
- Summary at bottom: total cost for the filtered period, grouped by equipment
- **Weekly Report button:** generates a list by vessel for all usage in the selected week, ready to invoice

### 3. Weekly Report (export/print-friendly)
**Purpose:** one-sheet invoice breakout per vessel.

**Display:**
- Vessel name, report week (e.g. "Week of July 26, 2026")
- Table: Equipment, Dates Used, Quantity, Rate, Total
- **Grand total for the week**
- Print-friendly styling (no colors, fits on one page per vessel)

---

## Data Model

**consumables_log table:**
- log_id (primary key)
- vessel_id (foreign key — vessels)
- equipment_name (string, e.g. "Scissor Lift")
- start_date (date)
- end_date (date, nullable — if null, same as start_date)
- quantity (number)
- unit (string, e.g. "day", "sqm")
- cost_per_unit (decimal, in NZD)
- total_cost (decimal, auto-calculated: quantity × cost_per_unit × num_days)
- notes (text, optional)
- logged_by (PM name, auto-filled)
- logged_date (timestamp)

**equipment_catalog table:**
- equipment_id (primary key)
- equipment_name (string)
- category (string)
- unit (string)
- standard_rate (decimal)
- active (boolean, for soft-delete)

---

## What NOT to Build Yet
- No approval workflow (PMs can log freely; you spot-check during invoicing)
- No real-time dashboard or cost trending (weekly report is enough for now)
- No Smartsheet sync (invoice happens weekly, separate from job status tracking)
- No login/auth (internal use only)

---

## Access Control & Visibility (Phase 3 Dashboard)
- **Visible to:** PMs only
- **Visible on:** All vessels (global access — PMs can log for any vessel)
- **Triggers in dashboard:** When logged in as a PM and filtering by vessel, "Log Consumables" button appears in the quick-actions menu

---

## Instructions to Claude Code
1. Extend the `coatings-diary/` Flask app — add `equipment_catalog` and `consumables_log` tables to SQLite
2. Build the three screens: Log Equipment/Consumable Use, Consumables History (with filters and summary), Weekly Report (grouped by vessel)
3. Auto-calculate total cost on submit (quantity × rate × duration in days)
4. Implement search/filter on history (by vessel, date range, equipment name)
5. Test locally: log a few rentals/consumables for a vessel over a week, generate a weekly report, confirm totals are correct

## Next Steps After This Works
- Equipment catalog admin screen (add/edit rates, manage active list)
- Email or PDF export of weekly report
- Tie into Phase 3 dashboard (PMs see "Log Consumables" button per vessel)
