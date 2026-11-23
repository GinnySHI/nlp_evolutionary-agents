# Fund-2 evidence

- `original-artifact/semis_deck.html`: unchanged 19-slide model output, SHA-256 `2385d9adbcb0c9ba67d6a6a253c906beeb1666869adcfb069b7803c0ffc8cdb5`.
- `validate-file.json`: actual platform static validation of that original file.
- `sia-q3-2026-fetch.json`, `sia-ytd-august-2026-fetch.json`: complete official-page fetch results. These are repository copies of the absolute `raw_evidence` paths retained in the assessment.
- `fund-2-result.json`: original 4/4 fixed-rubric assessment, quality findings, and a separate revised-delivery assessment.
- `browser-original/browser-result.json`: browser navigation checks on the original.
- `browser-revised/`, `visual-review.json`, `revised-contact-sheet.jpg`: revised 17-slide browser and visual evidence.
- The revised delivery and its change log are in `../../../deliverables/course-deepseek-20261123/fund-2/`.
- The unchanged, predeclared rubric is `../rubrics/content-rubric.md`.

Re-run navigation with Node.js, `playwright-core`, and Chrome installed:

```bash
node scripts/review_html_deck.cjs reports/course-deepseek-20261123/fund-2/original-artifact/semis_deck.html /tmp/fund-original-review
node scripts/review_html_deck.cjs deliverables/course-deepseek-20261123/fund-2/semis_deck.html /tmp/fund-revised-review
```

Set `NODE_PATH` to the package directory and `CHROME_PATH` to the Chrome executable if they are not available at the script defaults. The scripts use a fresh headless browser and block external HTTP requests. Source verification and browser operation are separate checks.
