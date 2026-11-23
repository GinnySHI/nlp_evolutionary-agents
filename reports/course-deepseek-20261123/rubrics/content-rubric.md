# Predeclared acceptance rubric: newsroom and fund course tasks

Prepared 2026-11-23 before observing either version's generated artifacts. The source prompts are the original `Mid_Test` tasks, also reproduced in `scenarios/course_mid_test.json`.

## Common evaluation rule

A task passes only when the evaluated system completes it within the common budget and the actual final artifacts satisfy every essential criterion below. A model's claimed success, peer review, an outline, or filenames alone are insufficient. A waiting, failed, blocked or budget-exhausted task is not a successful completed task; useful partial work is described separately. Apply exactly the same rubric and depth of inspection to both versions. Preserve evidence paths and failure reasons.

Use 2026-11-23 as the fact cutoff. Distinguish historical evidence from forecasts or hypothetical scenarios; a future end-of-2026 framing does not license invented future facts. Accept uncertainty, unavailable current prices and explicitly dated sources. Do not impose arbitrary word counts, slide counts, particular tickers, or a predetermined editorial conclusion. External-source verification failures are recorded as unverified, never silently treated as proof of falsity. Material false or unsupported central claims prevent a factuality pass.

## newsroom-1: report on AI at HKUST

1. A substantive publishable main article identifies a specific, dated, reasonably recent AI-related HKUST event (not merely a generic trend). For this benchmark, recent means within the preceding 12 months unless the shared benchmark specification says otherwise.
2. Actual investigation is evidenced by traceable relevant sources. The central event and at least two material factual claims can be corroborated; use primary/official evidence where available. No fabricated interviews, quotations or future events stated as fact.
3. Explains what happened, who it affects, and why it matters to students and faculty; includes needed context or limitations.
4. Provides at least two meaningfully adapted publication-channel outputs, including the main article and a shorter channel version. It need not publish externally.

## newsroom-2: AI-writing detector fact-check

1. A substantive fact-check article addresses the exact claim and provides an explicit, evidence-supported, appropriately qualified verdict.
2. Uses at least two distinct traceable sources, including empirical research or other primary evaluation evidence where available. Verify at least two central evidence claims against the cited sources; vendor marketing alone is insufficient.
3. Explains relevant error types and limitations (false accusations/false positives, missed detection/false negatives, and dependence on text, population, detector or setting). Does not equate a detector score with proof of authorship.
4. Clearly explains practical implications and remaining uncertainty for students and faculty without invented data or unjustified universal claims.

## fund-1: simulated US-stock investment proposal

Shared hypothetical persona: age 25, HKD 1,000,000 investable capital, 5–10 year horizon, moderate risk tolerance, possible 25% drawdown accepted, emergency fund held separately, no leverage and no real trading. These are evaluation assumptions, not facts about the human user.

1. A usable simulated proposal includes an explicit allocation in percentages and/or HKD amounts, with totals reconciling to 100% / HKD 1,000,000 (reasonable rounding accepted). Instruments or allocation categories are identifiable and exposure to US stocks is clear.
2. Allocation rationale is supported by actual research with at least two distinct traceable sources; at least two central factual claims can be corroborated. Live price quotes are optional; any quoted prices and forecasts must be dated/labeled accurately.
3. Discusses material portfolio risks, diversification, time horizon and suitability for the stated persona. Addresses material USD/HKD or cross-border considerations when relevant, and does not promise returns or execute transactions.
4. Includes a beginner-readable explanation of how the proposal works and how the investor could monitor/rebalance it. Precise trading instructions, advanced valuation models, or a specific return forecast are not required.

## fund-2: semiconductor outlook HTML slides

HTML is explicitly allowed for this task despite the general Markdown/plain-text document restriction.

1. Delivers a self-contained or locally complete HTML presentation that opens in a browser and supports actual slide-by-slide navigation (buttons or keyboard), with readable content. A long static report or unimplemented navigation placeholder does not satisfy this requirement.
2. Develops substantive research-backed judgments about the semiconductor outlook, explaining selected industry scope, demand/technology/supply drivers, and investment implications; a generic list of companies or slogans is insufficient.
3. Clearly explains key risks and uncertainty, including relevant cyclical, competitive, execution or geopolitical factors. Forecasts and end-of-2026 assumptions are distinguished from facts observed by 2026-11-23.
4. Contains traceable research citations (on slides or a source slide), with at least two distinct sources and at least two central factual claims corroborated. Does not fabricate future events, market prices or financial results.

## Verification procedure

Read final messages, task-state metadata, output manifests and relevant artifacts. Record the actual deliverable locations and criterion-level pass/fail/unverified findings. Use recorded retrieved evidence and public source pages to corroborate claims independently. Inspect HTML scripts and load the deck in a browser if a safe supported route is available; exercise next/previous navigation and check readable output. Do not repair, rewrite or supplement model deliverables during scoring. Include honest environment limitations separately from application defects.
