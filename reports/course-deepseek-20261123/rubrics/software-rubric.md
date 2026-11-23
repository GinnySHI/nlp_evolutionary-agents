# Software evaluation rubric (fixed before reviewing run outputs)

Source: the original two Software Engineering course tasks in `Mid_Test`, also copied in `scenarios/course_mid_test.json`.

Apply the same requirements and verification effort to both versions. Do not repair generated code. Run only inside the available execution sandbox, without network or credentials. External dependencies or services are not automatic failures, but a deliverable whose documented execution cannot be reproduced in the benchmark environment is not counted as independently verified. Record the specific blocker.

The binary artifact-success result requires every mandatory item below. Report partial criteria separately so that a failure does not hide improvements. A complete course-task success additionally requires the engine to end in `completed`; internally claimed or peer-reviewed success alone is insufficient. Human waiting, turn-budget exhaustion, crashes, and blocked follow-ups must be reported distinctly from artifact defects.

## software-1: usable meeting-room booking system

1. **Runnable delivery and instructions:** actual executable source plus accurate launch/use instructions demonstrate checking availability, booking, and cancellation. A prose-only design or placeholder is insufficient. CLI, browser, and other usable local interfaces are acceptable.
2. **Booking correctness:** create a booking for an existing room and valid interval and retrieve it through the system. Distinct rooms can be booked for the same interval.
3. **Collision protection:** reject an overlapping reservation of the same room, including a contained interval. An adjacent nonoverlapping reservation remains possible. Evaluate the documented boundary convention consistently; half-open intervals are the default if no convention is specified.
4. **Availability correctness:** occupied intervals are shown as unavailable; a free room/time is shown as available. Reported availability must agree with booking validation.
5. **Cancellation correctness:** cancelling an existing booking immediately releases the room/time and does not affect another booking. Unknown or already-cancelled bookings are handled without corrupting records.
6. **Durable records:** bookings and cancellations survive a normal process restart/reload. The task replaces a shared spreadsheet; an ephemeral demo alone does not meet that intended use.
7. **Basic input integrity:** reject a missing/unknown room and an end time not later than its start, without corrupting saved data.

Do not require production authentication, distributed locking, cloud deployment, a particular database, or a particular user interface: these were not specified in the course task.

## software-2: interactive room-usage dashboard

1. **Works with the existing system:** delivered source is runnable and consumes actual booking/cancellation records from software-1; a standalone mock-data presentation is insufficient. Existing booking/cancellation functionality remains usable.
2. **Interactive date selection:** a manager can change the start/end date, rerun or interactively refresh the view, and observe metrics calculated for the selected range. A single hard-coded date range does not qualify.
3. **Per-room booking count:** correct for a known test fixture; unused configured rooms appear with zero use or are clearly represented.
4. **Per-room reserved duration:** correct totals for the same fixture, with duration units and cancellation policy clear. Reservations crossing a range boundary must be handled consistently with a disclosed policy (overlap-clipped versus start-within-range are acceptable if clearly stated and consistent).
5. **Busiest days and times:** both day and time-of-day usage are represented, derived from records and consistent with the fixture.
6. **Cancellation frequency:** count or rate derived from retained cancellation data, with its denominator/time-window meaning understandable. Deleting cancellations so that history cannot be calculated fails this requirement.
7. **Clear charts and summaries:** at least one meaningful chart plus readable summaries allow comparison of heavily used and underused rooms. An interactive CLI may use legible text/bar charts; a graphical frontend is not mandatory.

## Deterministic verification fixture

Use configured rooms A and B (or two existing room IDs), with no prior records. Example same-month dates in a future period are acceptable to avoid past-date restrictions:

- A: day 1, 09:00–10:00, confirmed.
- A: day 1, 10:00–12:00, confirmed (adjacent).
- B: day 2, 09:00–10:00, confirmed.
- A: day 2, 14:00–15:00, cancelled, retaining the cancellation record.
- B: day 3, 16:00–18:00, confirmed, outside the selected two-day range.

Also attempt A day 1 09:30–10:30 and A day 1 09:15–09:45; both must fail. A same-time request for B should be allowed, then remove/cancel the probe cleanly or rebuild the fixture before dashboard checks.

For the selected day-1/day-2 range, active booking counts are A=2, B=1 and active reserved durations A=3h, B=1h; total created count includes A's cancelled booking if the dashboard explicitly defines its count that way. Cancellation count is A=1, B=0; a cancellation rate among all created in-range bookings is A=1/3 and overall=1/4. Day 1 is busiest under booking count and active reserved hours. The 09:00–10:00 hour totals 2 room-hours; the 10:00–11:00 and 11:00–12:00 hours each total 1 room-hour. Aggregation bins may differ if clearly labelled and numerically consistent.

Adjust dates and identifiers only to fit documented interfaces. Preserve the same logical fixture and expectations. For software-1 cancellation checks, use separate data so the dashboard fixture remains unambiguous.

## Evidence to retain

- Run/version IDs, final engine status, generated artifact paths and hashes.
- Exact commands or UI steps, relevant stdout/stderr, and test fixture/state.
- Criterion-by-criterion pass/fail/unverified with concrete evidence.
- No code repair or extra implementation by the reviewer; environment-only setup must be disclosed.
- Separate independent artifact verification from the agents' own tests and self-assessments.
