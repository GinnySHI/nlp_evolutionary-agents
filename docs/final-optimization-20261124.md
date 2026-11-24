# Final low-risk optimization (2026-11-24)

## Motivation
The Mid-Test report identified nested transfer paths such as `inbox/dev/inbox/dev/booking.py`, which required reviewers/QA to probe multiple paths. This is a handoff usability defect, not a task-planning or protocol redesign.

## Change
- `ToolRunner._send()` now removes one exact, sender-owned `inbox/<sender>/` prefix from the supplied destination before applying the existing path validation and transfer logic.
- The engine prompt clarifies that `send_file` destinations are relative to the tool-managed inbox prefix.
- Added regression test `test_send_file_normalizes_duplicate_owned_inbox_prefix`.

## Compatibility and safety
- Normal destinations remain unchanged (`report.md` -> `inbox/<sender>/report.md`).
- Only the exact redundant prefix matching the sender is normalized; path validation, exclusive write behavior, and transfer audit remain in place.
- No task lifecycle, action schema, session persistence, model settings, approval behavior, memory behavior, or sandbox policy was changed.

## Verification
- Full test suite: 302 tests collected.
- 296 passed; 6 macOS Seatbelt integration tests skipped in this environment (they require `sandbox-exec`).
- The added regression test verifies the normalized destination, transferred content, and absence of the duplicate nested path.
