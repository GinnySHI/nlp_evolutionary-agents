# Run metadata: course-deepseek-20261123

- Date: 2026-11-23
- Provider: DeepSeek (`EVO_PROVIDER=deepseek`), model `deepseek-v4-pro`, base `https://api.deepseek.com`
- Budget per task: `EVO_MAX_STEPS=120`, `EVO_MAX_OUTPUT_TOKENS=8192`, `EVO_REQUEST_TIMEOUT=240`
- Sandbox: `auto` (macOS Seatbelt; no Docker daemon on this host)
- Sessions: `course-software`, `course-newsroom`, `course-fund` under `.evoagents/sessions/`
- Task text: reproduced verbatim from `Mid_Test/scenario_*/0{2,3}_task_*.md`
- Role prompts: reproduced verbatim from `Mid_Test/scenario_*/01_role_initialization.md`
- Human requester: responses given live in the group chat, not from a prepared script
- Grading rubrics: `software-rubric.md` and `content-rubric.md`, both fixed on 2026-11-23
  before any output of this run was observed (reused unchanged from the earlier
  HKGAI comparison so the standard is not loosened for the new provider).

Both tasks of a scenario run in the SAME session so that collaboration context,
workspace files and per-agent memory carry over, as the course test set requires.


## Follow-up configuration and accounting (2026-11-23)

The settings above record the initial attempt, not the final DeepSeek configuration. The resumed course sessions used `deepseek-flash`, `EVO_MAX_OUTPUT_TOKENS=16384`, `EVO_REASONING_EFFORT=low`, and a 240-second timeout. The original 120-turn task budget was retained for the benchmark boundary.

software-2 was resumed from its saved approval at turn 53. Its artifact met the fixed rubric at turn 120, but the engine had not finished review and reached `budget_exhausted`. Explicitly recorded extensions of 60 and 20 turns were then used for completion. The session reached `completed` at turn 198, with six accepted subtasks and one superseded QA attempt. Turn 152 paused on HTTP 402; the human user confirmed an account top-up before it was resumed. The report distinguishes the original-budget result from the final handoff.

The operator approved reviewed workspace-only sandbox operations and provided concrete failure feedback. Original model artifacts were not rewritten by the independent reviewer. The separately revised fund-2 HTML is identified as an operator revision, with its original retained for scoring.

Final session snapshots and exact measured metrics are in `evidence/` and the repository's `reports/course-deepseek-20261123/`. Original snapshots predating this refresh are retained in `completion-20261123/evidence-before-refresh/`. Charges for this continuation were not independently reconciled against the account bill.
