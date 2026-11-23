# Test Results and Performance Report

Evolutionary Multi-Agent Collaboration System — HKUST NLP course mid test.

- **Run ID:** `course-deepseek-20261123`
- **Date:** 2026-11-23
- **Backbone:** DeepSeek `deepseek-flash` (DeepSeek-V4.1-Flash), `https://api.deepseek.com`
- **Original task budget:** 120 turns (software-2 received 80 extra turns and finished on turn 198), 16384 output tokens, 240 s request timeout, `reasoning_effort: low`
- **Sandbox:** macOS Seatbelt (no Docker daemon on this host)
- **Test set:** `Mid_Test/` — 3 scenarios × 2 tasks, role prompts and task text reproduced verbatim
- **Human requester:** answered live in the group chat, not from a prepared script

中文版见 [test-report-20261123.zh.md](test-report-20261123.zh.md)。

---

## 1. Headline result

**All six tasks are delivered and their sessions completed; all six artifacts meet the core independent criteria. software-2 finished on turn 198 after continuation. Completion within the original 120-turn budget remains 5/6.**

| # | Task | Engine status | Turns | Wall clock | Peer-accepted | Independent check |
|---|---|---|---|---|---|---|
| 1 | software-1 Meeting-room booking | completed | 116 | 1244.7 s | 3/3 | **7/7 criteria** |
| 2 | software-2 Usage dashboard | completed (continued) | 198 | 5605.3 s | 6/7; 1 superseded | **7/7 criteria** |
| 3 | newsroom-1 HKUST AI report | completed | 85 | 652.6 s | 3/3 | source + 2 claims |
| 4 | newsroom-2 AI-detector fact-check | completed | 81 | 644.9 s | 4/4 | 2 papers, exact figures |
| 5 | fund-1 Simulated proposal | completed | 93 | 1122.6 s | 3/3 | IRS threshold |
| 6 | fund-2 Semiconductor HTML deck | completed | 120 | 1089.2 s | 3/3 | **4/4; SIA and browser verified** |

The previous HKGAI baseline was 0/6. Final delivery is now 6/6, while completion within the common 120-turn budget is 5/6. Model changes, code revisions and operator interventions occurred together, so the difference cannot be attributed to one fix.

**software-2 completion:** resumed from turn 53, its dashboard route was repaired and the artifact passed independent review. Handoff was unfinished at turn 120. Separate extensions of 60 and 20 turns were used; HTTP 402 paused turn 152, and the user confirmed a top-up before the session resumed and reached `completed` on turn 198. Original pause and budget-boundary records were retained, not rewritten as an in-budget success.

---

## 2. Metrics

### 2.1 Per task

| Task | Turns | Elapsed | Active | Tool calls | Tool errors | Invalid actions | Recovered responses | Checkpoints |
|---|---|---|---|---|---|---|---|---|
| software-1 | 116 | 1244.7 s | 623.2 s | 73 | 3 | 22 | 5 | 8 |
| software-2 (continued) | 198 | 5605.3 s | 1450.1 s | 136 | 8 | 22 | 9 | 12 |
| newsroom-1 | 85 | 652.6 s | 569.7 s | 57 | 1 | 10 | 9 | 5 |
| newsroom-2 | 81 | 644.9 s | 644.9 s | 58 | 7 | 4 | 2 | 6 |
| fund-1 | 93 | 1122.6 s | 961.4 s | 58 | 4 | 14 | 6 | 4 |
| fund-2 | 120 | 1089.2 s | 1089.2 s | 95 | 2 | 8 | 16 | 5 |

`Elapsed` includes time waiting for the human; `Active` excludes it. The gap in software-1 (1244.7 vs 623.2 s) is human approval latency — this task required six separate `run_python` approvals.

**fund-2 consumed exactly its 120-turn budget** and still finished. It had no margin; a single extra protocol error would have exhausted it.

### 2.2 Completion rates

| Measure | Value | What it means |
|---|---|---|
| Final sessions completed | 6/6 (100%) | Includes extra turns for software-2 |
| Completed within 120 turns, independently verified afterward | 5/6 (83.3%) | software-2 exceeded the budget |
| Artifacts meeting core independent criteria | 6/6 (100%) | Distinct from in-budget completion; quality defects remain disclosed |
| Raw subtask acceptance count | 22/23 (95.7%) | Includes one superseded QA attempt; all 22 active leaf subtasks were accepted |

Subtask counts can overstate delivery. newsroom-1 accepted a transparent negative result with no artifact, and software-2 contains overlapping development subtasks. The raw denominator also retains a superseded QA task. Therefore 22/23 is not an independent task-success rate; the artifact checks establish delivery.

### 2.3 Cost

Token counters are recorded per CLI process. A session resumed across several `evo respond` invocations starts a fresh counter each time, so **per-task token totals are undercounts** — software-1 records only 25 calls against 116 turns. These usage counters do not establish the complete monetary cost; that requires billing or balance records covering the same period.

| Measure | Value |
|---|---|
| Historical operator cost note | ≈ CNY 20 after two top-ups; the original balance calculation has not been independently re-verified |
| Final total and per-task cost | Not established: the saved evidence lacks a complete billing ledger and includes retries; follow-up calls add further spend |
| Largest recorded token total among the six final task states | 4,740,251 (fund-2) |

The earlier CNY 1.6–2.0 per-task estimate has been withdrawn because its denominator was not documented and it cannot be reconciled with the historical total. Shared prompt prefixes may permit input caching, but the saved usage does not record cache-hit counts. This report therefore makes no measured cache-savings claim and does not derive cost from an unverified price schedule.

---

## 3. Independent verification

The grading rubrics (`software-rubric.md`, `content-rubric.md`) were fixed **before any output of this run was observed**, and were reused unchanged from the earlier HKGAI comparison so the standard was not loosened for a new provider. Independent scoring used unchanged artifact copies. The model repaired software-2 after logged external defect feedback; the operator-revised fund-2 copy is a separate delivery and does not replace the original model assessment.

### software-1 — 7/7 mandatory criteria

Run via `independent-review/software-1/review_software1.py` against a **copy** of the artifacts, implementing the rubric's deterministic fixture.

| Criterion | Evidence |
|---|---|
| Runnable delivery | all four code files documented in README; behaviour proven by importing the delivered module |
| Booking correctness | `atlas` 09:00–10:00 created and retrieved; `birch` accepted the same interval |
| Collision protection | overlap 09:30–10:30 and contained 09:15–09:45 rejected; adjacent 10:00–12:00 accepted (half-open) |
| Availability correctness | booked interval absent from availability; occupied slot rejected; slot reported free was accepted |
| Cancellation | record retained, slot immediately rebookable, other bookings untouched, double-cancel and unknown id rejected |
| Durable records | reloaded from disk: active booking present, cancellation retained, interval free again |
| Input integrity | unknown/empty room, zero-length, reversed, 2026-02-30 all rejected; saved data uncorrupted |

Artifact hashes: `booking.py` c7a208de…, `server.py` 0c2aecb4…, `index.html` d9f5e7fc…, `selftest.py` 7660e995…, `README.md` a4d8ed8a…

### software-2 — 7/7 artifact criteria; original 120-turn budget accounted separately

The saved approval at turn 53 was resumed. Independent checks then found a real 500 response on `/dashboard` caused by an undefined `DASHBOARD_PATH`; the operator fed that result back and the model fixed it. Reviewers did not rewrite the generated source.

| Criterion | Evidence |
|---|---|
| Runnable integration | Existing booking/cancellation works with real records; both dashboard paths return HTML; the real server entry point and CLI arguments were exercised with a no-network server adapter |
| Date interaction | Chrome date inputs and Apply produce 3 active bookings/4 hours across two days, then 2/3 hours and 1/1 hour for the individual days |
| Per-room counts | Atlas 2, Birch 1, three unused rooms explicitly zero |
| Per-room duration | Atlas 3 hours, Birch 1 hour; one cancelled hour excluded; inclusive endpoints verified |
| Busiest days/times | Day ranking, seven weekdays and 13 hourly bins match the fixture; cross-hour duration is split by minutes |
| Cancellation frequency | One cancellation / four created bookings = 25%; retained records and read-only aggregation verified |
| Charts and summaries | Room, weekday, hourly and cancellation charts have tables; sorting, empty/error states, Hong Kong midnight dates and mobile layout were exercised |

The model's self-test passed **54 checks**; independent artifact acceptance passed **7/7**. Real Python handlers ran in Seatbelt, while Chrome used their captured JSON responses. No network listener ran in the sandbox. Mobile hour labels are dense; the full values remain available in the data table.

At turn 120 the artifact met these requirements, but the engine was `budget_exhausted`, so this is not completion within the common budget. Separate continuations of 60 and 20 turns were granted for handoff and review. HTTP 402 paused turn 152; the user confirmed a top-up and the saved session resumed, completing on turn 198. Both boundary snapshots were preserved.

[Runnable delivery](../deliverables/course-deepseek-20261123/software-2/PROVENANCE.md) · [Review and reproduction](../reports/course-deepseek-20261123/software-2/README.md) · [7/7 result](../reports/course-deepseek-20261123/software-2/checkpoint-120/combined-software-2-result.json)

### newsroom-1 — source corroborated

The story cites an official HKUST item dated 2026-11-18. I fetched it myself. Every named detail matched: Founding Director YEUNG Sai-Kit, Associate Directors Rob SCHARFF and HU Wenqi, AI4Coral co-led by Yeung, David SUGGETT and Liz GOERGEN, plus both quantitative claims ("over 1,000 times faster"; "5,000 times as many classified image locations"). The article also carries its own "What we could not verify" section.

### newsroom-2 — both papers corroborated verbatim

| Cited claim | Independent check |
|---|---|
| Weber-Wulff et al., IJEI 19:26 — 14 tools (12 public + 2 commercial), "neither accurate nor reliable", bias toward human-written, obfuscation worsens performance | **Confirmed**, all elements |
| Liang et al., arXiv:2304.02819v3 — 61.22% average false-positive rate on 91 TOEFL essays, 7 detectors, vs 5.19% on 88 US 8th-grade essays | **Confirmed**, exact figures |

Verdict is appropriately hedged: "detector output is evidence of risk, not evidence of fact."

### fund-1 — central claim corroborated

Allocation reconciles exactly (35/12/8/45 = 100%, HKD 1,000,000). The US estate-tax claim — USD 60,000 exemption for non-US persons on US-situs assets — was confirmed against the IRS page the team cited, which states the Form 706-NA filing threshold as "$60,000". Unverifiable items (fund TERs, treaty rate, HKMA band, valuation) are labelled NOT VERIFIED throughout.

### fund-2 — original artifact 4/4; revised delivery provided separately

The actual `validate_file` call returned `valid=true`, no errors or warnings, and five unique IDs. The original SHA-256 is `2385d9ad…`; it was not edited during scoring.

All three requested figures were corroborated verbatim against freshly fetched official SIA bodies:

| Claim | Official corroboration |
|---|---|
| Q3 2026 sales USD 517.7bn, +24.1% QoQ | [November 3 release](https://www.semiconductors.org/global-semiconductor-sales-increase-24-1-from-q2-2026-to-q3-2026/): $517.7 billion and 24.1% |
| September sales USD 172.6bn, +146.8% YoY | Same release: $172.6 billion and 146.8% |
| Year-to-date through August exceeded USD 1tn | [October 5 release](https://www.semiconductors.org/year-to-date-global-semiconductor-sales-top-1-trillion-through-august/): through August, surpassed $1 trillion |

The three consecutive quarters above 20% QoQ are an actual SIA CEO statement, not three quarterly observations independently reconstructed by the team. SIA also confirms that monthly sales are three-month moving averages.

Chrome 144 loaded the unchanged original: all 28 button, keyboard, wraparound and counter checks passed, with no JavaScript errors. Together with substantive research, risks and the two official releases, this meets the fixed **4/4 essential criteria**. Quality defects remain: the 19-slide original retains two revisions of each of two topics, its static counter says 1/16, some evidence tags disagree with the errata, and wide tables overflow on mobile. The earlier report incorrectly described the repeated topics as byte-identical slides; they are different revisions.

A separate [17-slide revised delivery](../deliverables/course-deepseek-20261123/fund-2/semis_deck.html) resolves these defects and consistently marks the withdrawn GlobalFoundries figure. It passed 26 navigation checks; all 17 desktop slides were visually reviewed, and mobile tables can be scrolled without widening the page. The original session is preserved, and the revised copy is not counted as original model performance.

Evidence: [original and revised assessment](../reports/course-deepseek-20261123/fund-2/fund-2-result.json), [visual review](../reports/course-deepseek-20261123/fund-2/visual-review.json), [revision notes](../deliverables/course-deepseek-20261123/fund-2/CHANGES.md).

---

## 4. Failure modes

### 4.1 Platform defects found and fixed during this run

**Reasoning-token starvation — the most consequential.** Both approved backbones are reasoning models whose thinking tokens are billed inside `max_tokens`. At the configured 8192 limit, `deepseek-v4-pro` spent **all 8192 tokens on reasoning and returned no content at all** (`finish_reason: length`). The engine correctly executed nothing, and the turn was simply lost. This is an observed failure mechanism; no controlled rerun establishes that it explains all earlier turn-budget failures.

| Setting | Reasoning tokens | Content | Latency |
|---|---|---|---|
| default, 8192 cap | 8192 | none | — |
| default, 32768 cap | 16904 | 5101 chars | 166 s |
| `reasoning_effort: low`, 16384 cap | 1376 | 4754 chars | 23 s |

**Non-action responses.** Of 37 invalid responses sampled across the three sessions, **22 were a bare JSON array of data** (room records, search rows) returned instead of an action. A further group appended commentary after a valid object, or leaked internal `DSML` tool-call markup. The parser now takes the first complete object and discards non-JSON remainder — while still rejecting unterminated objects and still refusing to choose between two parseable objects. Recoveries are counted (`recovered_responses`) and audited. The five tasks completed before this follow-up recorded **38 recovered responses** (5 + 9 + 2 + 6 + 16); the earlier total of 24 omitted 14 fund-2 recoveries. Including software-2's nine recoveries, the final six-task total is **47**. Recovery avoids wasting these turns, but the count alone does not prove that every task would otherwise have failed. This follow-up also closed a parser ambiguity: malformed brace text in the remainder can no longer hide a second complete object.

**HTTP 402 treated as fatal.** A billing stop was classified as a configuration error and killed the task outright. This destroyed fund-2's first attempt *after* two subtasks had already been peer-accepted and paid for. It now routes to the same pause path as 429/5xx — accepted work survives, the human tops up and replies to resume — but is deliberately never retried, since a balance does not refill on its own. 401 remains a hard error.

### 4.2 Agent-level failure modes observed

| Mode | Where | Effect |
|---|---|---|
| Stale workspace carryover | newsroom-2 reporter | Its `research_notes.md` still held notes from newsroom-1; the agent entered a protocol loop and delivered nothing. Accepted as a transparent negative result; the evidence came from two fact-checker sprints instead. |
| Accepted subtask with no deliverable | newsroom-1 subtask-1 | Inflates `subtask_completion_rate`; see §2.2 |
| Nested inbox paths | software, fund | Agents chose destinations like `inbox/dev/booking.py`, producing `inbox/dev/inbox/dev/booking.py`. Cosmetic, but QA had to probe both paths. |
| Budget exhaustion risk | fund-2, software-2 | fund-2 used all 120 turns; repeated handoffs, QA harness errors and review extended software-2 to 198 turns |
| Internal inconsistency after late fix | fund-2 | Errata slide corrects a tag that slides 10/12 still carry |

### 4.3 What worked

The sandbox is real, not nominal: QA's attempt to bind a loopback socket was denied with `PermissionError: [Errno 1] Operation not permitted`, and QA adapted by dispatching handler methods with fake streams instead. The agents' own testing was substantive rather than ceremonial — dev's self-test caught a genuine `BookingStore.__init__()` signature bug in `server.py`, and a concurrency test showed 20 threads racing the same slot producing exactly 1 booking and 19 conflicts.

Peer review changed outputs rather than rubber-stamping them. In fund-2 the risk manager forced the withdrawal of an unsourceable "USD 21bn GlobalFoundries" figure and the addition of a concentration/crowding risk; the research analyst also retracted its own earlier "reconciliation gap" finding after realising SIA monthly prints are three-month moving averages that must not be summed.

---

## 5. Memory and evolution

Memory changes future prompts, not model weights. Record growth alone proves nothing, so the testable claim is cross-task: does task 2 reuse task 1's conventions and avoid repeating its reviewed failures?

**Memory volume** (group entries, end of task 2):

| Agent | Entries | Lessons | Successes | Failures |
|---|---|---|---|---|
| fund / research | 9 | 2 | 4 | 1 |
| fund / risk | 8 | 2 | 3 | 1 |
| fund / fund_manager | 5 | 2 | 0 | 1 |
| newsroom / reporter | 6 | 2 | — | — |
| newsroom / chief_editor | 4 | 2 | — | — |

**Evidence of carry-over:**

- The fund team's task-1 research used ad-hoc "NOT VERIFIED" labels. In task 2 the same analyst formalised this into a four-way tagging scheme (`[E]` evidence / `[J]` judgment / `[NV]` not verified / `[D]` derived) with a source ledger, and the tags propagated onto every slide of the deck. The discipline was inherited and strengthened.
- The newsroom's task-1 article introduced a "What we could not verify" section; task 2's fact-check carried the same convention, listing the OpenAI classifier page body and the Turnitin page (HTTP 403) as unverified rather than omitting them.
- The fund team retained its risk-review habit: task 1's risk manager re-checked drawdown arithmetic; task 2's forced two substantive corrections.

**Counter-evidence, stated plainly:** memory and workspace carry-over also *caused* a failure. The newsroom reporter's stale `research_notes.md` from task 1 contributed to its task-2 protocol loop. Persistence is not uniformly beneficial, and this run provides one clear instance of it hurting.

This is suggestive, not conclusive. With n=2 tasks per scenario and no controlled ablation (same tasks with memory disabled), these observations are consistent with memory helping, but do not isolate it from the model's own in-context reasoning.

---

## 6. Threats to validity

1. **The measured run spans multiple code revisions.** In-flight processes held the earlier parser while each new `evo respond` loaded the patched code. Earlier boundaries are recorded in `code-revision-B.json`. The follow-up parser change and configuration update are recorded with before/after SHA-256 hashes in [`revision-followup.json`](../reports/course-deepseek-20261123/revision-followup.json); software-2 was already running with the previous engine when that patch was saved.
2. **software-2 and fund-2 were not cold starts.** Their first attempts were killed by HTTP 402 and left `analytics.py` and `semis_research.md` in the team workspaces. These were retained — the course scenario explicitly has teams continue with existing context — so their turn counts understate a from-scratch run.
3. **Per-task token counts undercount** (§2.3).
4. **Browser and backend checks are separate.** This follow-up used bundled Node and Chrome 144 for real browser interaction. Python handlers ran in Seatbelt with in-memory requests; the dashboard browser consumed captured real handler responses, without a live HTTP listener. This does not establish deployment, multi-user networking, or cross-browser compatibility.
5. **Open-ended tasks need human judgment.** The rubric checks factual traceability and structural requirements; it cannot score editorial quality or investment reasoning.
6. **n=1 per task.** No repeated trials, so nothing here supports a confidence interval.

---

## 7. Reproduction

```bash
cp .env.example .env          # set DEEPSEEK_API_KEY, EVO_PROVIDER=deepseek
./run.sh doctor --live
./run.sh init course-software --scenario software
./run.sh run course-software --task-file scenarios/software_task1.md --interactive
./run.sh run course-software --task-file scenarios/software_task2.md --interactive
python scripts/collect_evidence.py .evoagents/sessions/course-software --output evidence/
```

Both tasks of a scenario must run in the **same** session so workspace, context and memory carry over.

**Evidence tree:** the repository's `reports/course-deepseek-20261123/` includes fixed rubrics, source bodies, original/revised deck evidence, software checks, final metrics and session summaries. The full local `../outputs/course-deepseek-20261123/` holds the run metadata, both fixed rubrics, per-file code hashes, snapshotted artifacts with SHA-256, the independent review script and its result, collected metrics including every human intervention, and the logs of the two discarded runs (credit exhaustion, pre-parser-fix).

**Automated tests:** the earlier suite had 296 passing tests. This follow-up added five response-ambiguity regressions; **301 tests passed in 4.35 seconds**. See the [test output](../reports/course-deepseek-20261123/unit-tests.txt) and [revision record](../reports/course-deepseek-20261123/revision-followup.json).

---

## 8. Follow-up outcome

| Item | Final state |
|---|---|
| software-2 dashboard | Delivered, independently 7/7; session completed on turn 198 |
| Three SIA figures | Fresh official bodies fetched and matched verbatim |
| Duplicate-ID check | Actual `validate_file` call passed, no duplicate IDs |
| Repeated topics and inconsistent tags | Original preserved; revised 17-slide copy corrected and visually checked |
| Browser verification | Chrome 144: 28 original-deck and 26 revised-deck navigation checks; eight dashboard interaction categories |
| Reports and evidence | Both languages synchronized; 301 automated tests passed |

[Machine-readable final summary](../reports/course-deepseek-20261123/summary.json) · [Run metadata](../reports/course-deepseek-20261123/run-metadata.md) · [Session snapshots](../reports/course-deepseek-20261123/evidence/all-sessions.json)

Final delivery is 6/6; the original fixed-budget result remains 5/6. Both are recorded separately.
