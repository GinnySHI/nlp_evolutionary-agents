# Revised fund-2 delivery

This is an operator-revised delivery made after the original model run. It is not the original model output and must not be counted as an unassisted benchmark success. The original session artifact and its audit log were not changed.

- Original: `.evoagents/sessions/course-fund/agents/fund_manager/workspace/semis_deck.html`
- Original SHA-256: `2385d9adbcb0c9ba67d6a6a253c906beeb1666869adcfb069b7803c0ffc8cdb5`
- Revised file: `semis_deck.html` in this directory.
- Source verification: `reports/course-deepseek-20261123/fund-2/` contains fresh official SIA fetch results, exact claim matches and the original `validate_file` result.

## Changes

1. Reduced 19 slides to 17 by retaining the later, fuller revisions of “Economics and valuation” and “Investment implications.” The repeated topics were different revisions, not byte-identical slides. Moved the retained versions before “Key risks.”
2. Numbered every slide, including the cover, from 1 to 17 and corrected the static counter to 1 / 17. The runtime counter still uses the actual slide count.
3. Consistently attributed the claim of three consecutive quarters above 20% quarter-on-quarter growth to the SIA statement. The official release contains that quotation; the deck does not independently reconstruct all three quarters.
4. Changed “3 hard prints” to “3 reported measures” and added working links to the two official SIA releases. The three sales claims match the official release bodies; their values were retained.
5. Applied the GlobalFoundries USD 21bn withdrawal directly to the China/policy slide, removing its conflicting green evidence tag. Replaced the inaccurate “cosmetic ordering defect” note with the scope of the available source evidence. Updated internal references to section names.
6. Relabelled the illustrative USD 1.6–1.75 trillion full-year range as judgment, because a year-to-date lower bound and assumed remaining months do not determine a unique observed total. The annualised Q3 figure remains derived arithmetic.
7. Wrapped tables in focusable horizontal-scroll regions. Wide tables retain readable columns on small screens without widening the whole slide. Fixed one duplicate `style` attribute.

Static validation passes with no errors or warnings. All 17 slides were rendered and visually inspected at 1280 × 800. Navigation and keyboard checks pass in Chrome 144.0.7559.133 without JavaScript errors. At 390 × 844, no slide has horizontal overflow; all columns and rows of the three wide tables remain accessible through internal horizontal scrolling. Browser and visual evidence are recorded in `reports/course-deepseek-20261123/fund-2/`. The original 19-slide evaluation remains separate from this revised delivery.
