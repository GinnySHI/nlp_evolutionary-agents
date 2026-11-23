# Software-2 delivery provenance

These seven files are unchanged copies of the model-produced artifacts at the
120-turn checkpoint of `course-software`, task
`12c9c6be49894f2a994698bdb0f1b313`:

- `booking.py`, `server.py`, `index.html`, `dashboard.html`, `selftest.py`
- `README.md` from the release role and `NOTES-dashboard.md` from the developer

Use `NOTES-dashboard.md` for dashboard launch instructions. The original
`README.md` describes the preceding booking-system delivery and is retained
verbatim; neither document was rewritten by the independent reviewer.

The copied artifacts passed **7/7 independent artifact criteria**. Python and
real HTTP handler dispatch were exercised in macOS Seatbelt without a network
listener; the unmodified dashboard was also exercised in Chromium with responses
captured from those handlers. The browser checks cover date selection, metrics,
sorting, empty/error states, calendar boundaries, and a 390px mobile viewport.

The original engine run ended as **`budget_exhausted` at 120 turns**. Passing the
artifact checks does not mean that the agent team completed its workflow within
that budget. The separate continuation subsequently reached `completed` at turn 198.
All five source/UI files and the dashboard notes still match the tested hashes.
`DELIVERY.md` is the model coordinator's final handoff note, copied unchanged
after completion; its hash and session status are recorded in
`reports/course-deepseek-20261123/software-2/final-session.json`.

Source locations, exact hashes, review scripts, raw results and screenshots are
retained under `reports/course-deepseek-20261123/software-2/` in this repository.
`artifact-manifest.json` identifies the copied delivery. Independent review did
not edit generated source, HTML, documentation, or the generated self-test.
