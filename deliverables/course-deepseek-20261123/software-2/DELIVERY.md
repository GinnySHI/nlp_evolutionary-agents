# Meeting Room Booking System v2 — Analytics Dashboard for Room Managers

Status: assembled, peer-reviewed and delivered. All six deliverables are flat in one folder.

## 1. What you get

The v1 booking system (book / check availability / cancel, no double bookings) plus a
manager analytics dashboard:

| File | Role | Size | sha256 (first 8) |
|---|---|---|---|
| `booking.py` | Core logic + new `compute_stats(start, end, store=None)` / `BookingStore.stats(start, end)` | 23,122 B | `41c966fa` |
| `server.py` | HTTP server: v1 API + `GET /api/stats` + `GET /dashboard` | 11,223 B | `5a249b9d` |
| `index.html` | Booking page, now with an "Analytics dashboard" header link | 24,576 B | `077fe7a3` |
| `dashboard.html` | Self-contained offline dashboard (inline CSS/JS, no CDN) | 21,361 B | `f66d0fcc` |
| `selftest.py` | Plain-assert test suite incl. all stats cases | 13,480 B | `22a1f458` |
| `README.md` | Short user guide (v1 wording; see section 5 for the dashboard) | 3,463 B | — |

## 2. How to run it

1. Put all five code files (`booking.py`, `server.py`, `index.html`, `dashboard.html`,
   `selftest.py`) in ONE folder, next to `bookings.json`.
2. Start the server:

       python3 server.py

3. Open the booking page: `http://localhost:8080/` (or the LAN URL printed at startup).
4. Open the manager dashboard: `http://localhost:8080/dashboard` — or click
   "Analytics dashboard" in the header of the booking page.

Optional flags: `--port 8080 --data bookings.json --rooms rooms.json`.
Python 3.8+, standard library only, no internet, no CDN, no third-party packages.

Running the tests: `python3 selftest.py` (or run it in-process with runpy).

## 3. What the dashboard shows

- Date range controls: start/end `type=date` inputs defaulting to the last 30 days ending
  today (today built from local date parts — no UTC day shift), presets **Last 7 days**,
  **Last 30 days**, **This month**, **Last month**, plus **Apply**.
- Summary cards: active bookings, cancelled bookings, cancellation rate %,
  total reserved hours, utilisation % of available room-hours, days in range.
- **Hours reserved per room**: horizontal bar chart coloured by utilisation, plus a
  sortable per-room table (room, capacity, location, bookings, hours reserved, cancelled,
  utilisation %, verdict **heavily used** ≥60% / **underused** ≤20% / **balanced**).
- **Bookings by weekday** (Mon..Sun) vertical bar chart.
- **Reserved hours by hour of day** (07:00..19:00) bar chart, showing peak times.
- **Top 5 busiest days** table and a **cancellation summary** (count, rate, per-room bars).
- Every chart carries axis labels, value labels and a table/list fallback so the numbers
  are readable without hovering; layout is responsive at ~1000 px and phone width.
- Visible assumptions note, empty-range message, and inline error message on a failed or
  non-200 `/api/stats` call (never a blank page).

Counting rules used by the dashboard: range is inclusive of both dates; capacity =
rooms x days in range x 13 h (07:00-20:00 = 780 min per room-day); all calendar days
counted including weekends (a weekday breakdown is also returned); bookings are counted on
their booking date; cancelled bookings still record their reserved hours as cancelled but
never contribute to active hours or utilisation.

## 4. API

    GET /api/stats?start=YYYY-MM-DD&end=YYYY-MM-DD

200 -> the stats JSON (keys: `range`, `totals`, `rooms`, `by_weekday` (7), `by_hour` (13),
`top_days` (≤5), `cancellations`). Errors, all JSON: 400 `bad_request` (missing/empty
param), 400 `bad_date`, 400 `bad_range` (start > end). Unknown path -> 404. The handler
never lets an exception escape. `compute_stats` is read-only: it never creates or modifies
`bookings.json`.

## 5. Verification evidence (actually observed)

- **selftest.py v2, run in-process by QA** on the delivered files: 57 stdout lines,
  **54 PASS, 0 FAIL, exit code 0**; final line verbatim `All 54 checks passed.`
  Covers: empty store zeros, single booking counted once, inclusive start/end, out-of-range
  exclusion, cancelled counted only as cancelled/hours_cancelled, two-room split,
  `by_weekday` 7 entries summing to active, `by_hour` 13 entries with a 09:30-10:30
  booking split 0.5 h / 0.5 h, `top_days` ordering, 390/780 min -> `utilisation_pct` 50.0,
  `bad_range`/`bad_date`, and the data file left untouched.
- **`/api/stats` exercised in-process** (no socket): missing params -> 400 `bad_request`;
  empty params -> 400 `bad_request`; `2026-13-01` -> 400 `bad_date`; start>end ->
  400 `bad_range`; valid one-day range -> 200 with `totals.bookings_active = 1`.
- **Routing**: `server.DASHBOARD_PATH` exists and basenames to `dashboard.html`;
  `do_GET` dispatch contains `/dashboard` and `/dashboard.html`.
- **validate_file**: valid with no errors/warnings on `index.html`, `dashboard.html`
  (author's run), and on `booking.py` and `index.html` (QA's run).
- **dashboard.html static checks**: no `<script src>`, no `http://`/`https://` URLs, no CDN,
  two `type="date"` inputs, the four presets, `/api/stats` fetch, weekday and hour charts,
  per-room table with heavily used/underused verdicts, top days, cancellation summary,
  assumptions note and error/empty-state text.

Disclosed open risks (not claimed as tested):
- No socket-level HTTP round trip was ever executed — the sandbox blocks binding a port
  (`PermissionError 1, 'Operation not permitted'`). Handler logic was tested in-process;
  please confirm `python3 server.py` + `http://localhost:8080/dashboard` on your machine.
- Browser JavaScript execution of `dashboard.html` was not run by QA or by me; it was
  checked statically and, per the operator's earlier report, renders correctly in Chrome.
- QA's own scratch harness had two wrong 50 % utilisation fixtures (1 h over 5 rooms x 13 h
  = 1.54 %; 50 % needs 390 of 780 min) and earlier `BookingStore` keyword mismatches —
  all QA harness errors, not application defects; no application defect was observed.

## 6. Assembly note

If you received the files with `final_` prefixes in a transfer folder, rename them:

    final_booking.py -> booking.py
    final_server.py  -> server.py
    final_index.html -> index.html
    final_dashboard.html -> dashboard.html
    final_selftest.py -> selftest.py

All five must sit in the same folder as `server.py`, otherwise `/` and `/dashboard` return
404 `not_found`.
