# Software-2 independent evidence

The unmodified delivery in `deliverables/course-deepseek-20261123/software-2/`
passes 7/7 fixed artifact criteria. At the checkpoint documented here, the engine
had exhausted its original 120-turn budget; that workflow result remains
separate from the artifact result. The engine later completed on turn 198; `final-session.json` records the
actual state and confirms that the tested source hashes are unchanged.

## Evidence

- `artifact-manifest.json`: hashes of the seven delivered files.
- `checkpoint-101/`: preserved failed check; `/dashboard` returned HTTP 500
  because `DASHBOARD_PATH` was undefined. Its browser subdirectory contains the
  successful independent UI check and desktop/mobile screenshots.
- `checkpoint-120/sandbox-result.json`: raw Seatbelt execution output after the
  agent corrected the missing path and supplied launch notes.
- `checkpoint-120/software-2-result.json`: Python and static results alone;
  frontend interaction/appearance remain explicitly unverified in this file.
- `checkpoint-120/combined-software-2-result.json`: 7/7 artifact verdict combining
  the Python checks with the browser evidence. Reuse is justified by exact
  dashboard-byte equality and equal response fixtures across both checkpoints.
- `checkpoint-120/fixture-records.json`, `fixture-stats.json`, and
  `fixture-responses.json`: actual booking/cancellation records and actual handler
  responses for the fixed fixture. No fabricated mock statistics were used.

The original source manifests retain the machine paths used for acquisition.
Their copied file hashes can be verified with `artifact-manifest.json`; those
paths are provenance, not required runtime locations.

## Reproduce from the repository root

With the project virtual environment installed, run:

```bash
.venv/bin/python reports/course-deepseek-20261123/software-2/run_independent_review.py --output reports/private/software-2-recheck
```

The output directory must be new. The runner first checks the delivered hashes,
copies the files, then invokes the real project `Sandbox` with no network or
credentials. It never edits the delivered files. macOS Seatbelt or the project's
supported Docker environment is required. The script exercises the actual
`server.py` entrypoint using a no-network HTTP server adapter; it does not claim
to have tested a live listening socket.

For frontend reproduction, install `playwright-core` in the Node environment and
make Chrome available (`CHROME_PATH` can override the default macOS application):

```bash
node scripts/review_dashboard.cjs deliverables/course-deepseek-20261123/software-2 reports/private/software-2-recheck/fixture-responses.json reports/private/software-2-recheck/browser
```

This opens an isolated headless Chromium instance. It loads the unchanged HTML
and intercepts requests with the captured real handler JSON. All other network
requests are blocked. It checks the Hong Kong local date at 00:30, date changes,
the fixed metric values, sorting, empty/error states, preset boundaries, and
390px mobile overflow. Raw output and screenshots are written separately.

The retained screenshots were reviewed visually. Hour labels are dense on a
phone, with all values also available in the accompanying scrollable table.
