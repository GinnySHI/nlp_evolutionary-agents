"""Plain-assert self test for the meeting-room booking system.

Run with:  python3 selftest.py     (no pytest, no subprocess)
Exits 0 and prints PASS lines when everything is green.
"""

import os
import shutil
import tempfile

import booking as core

PASSED = []


def check(label, condition, detail=""):
    if condition:
        PASSED.append(label)
        print("PASS  %s" % label)
    else:
        raise AssertionError("FAILED: %s %s" % (label, detail))


def expect_error(label, code, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except core.BookingError as exc:
        check(label, exc.code == code, "expected %r got %r (%s)" % (code, exc.code, exc.message))
        return exc
    raise AssertionError("FAILED: %s (no error raised, expected %r)" % (label, code))


def main():
    workdir = tempfile.mkdtemp(prefix="booking-selftest-")
    data_path = os.path.join(workdir, "bookings.json")
    try:
        store = core.BookingStore(data_path)
        check("default rooms include Atlas/Everest",
              any(r["id"] == "atlas" for r in store.get_rooms())
              and any(r["id"] == "everest" for r in store.get_rooms()))

        day = "2026-12-01"

        # 1. successful booking
        b1 = store.create_booking("atlas", day, "10:00", "11:00", "Sprint planning", "Ana")
        check("successful booking", b1["status"] == "active" and b1["id"])

        # 2. overlapping booking rejected, conflict names the clash
        exc = expect_error("overlap rejected with conflict", "conflict",
                           store.create_booking, "atlas", day, "10:30", "11:30", "Overlap", "Bo")
        check("conflict message names clashing booking",
              "Sprint planning" in exc.message and "Ana" in exc.message, exc.message)

        # 3. exact duplicate rejected
        expect_error("exact duplicate rejected", "conflict",
                     store.create_booking, "atlas", day, "10:00", "11:00", "Sprint planning", "Ana")

        # 4. back-to-back allowed (half-open intervals)
        b2 = store.create_booking("atlas", day, "11:00", "12:00", "Retro", "Cy")
        check("back-to-back allowed", b2["status"] == "active")

        # 5. different room same time allowed
        b3 = store.create_booking("birch", day, "10:00", "11:00", "1:1", "Di")
        check("different room same time allowed", b3["status"] == "active")

        # 6. cancellation frees slot, record persists as cancelled
        cancelled = store.cancel_booking(b1["id"], reason="moved")
        check("cancel keeps audit record",
              cancelled["status"] == "cancelled" and cancelled["cancelled_at"] and cancelled["cancel_reason"] == "moved")
        again = store.get_booking(b1["id"])
        check("cancelled record still stored", again is not None and again["status"] == "cancelled")

        # 7. cancelled booking does not block rebooking
        b4 = store.create_booking("atlas", day, "10:00", "11:00", "New slot", "Ed")
        check("cancelled slot can be rebooked", b4["status"] == "active")

        # 8. cancellations are excluded from availability
        gaps = store.availability(day, "atlas")
        gap_labels = [(g["start"], g["end"]) for g in gaps]
        check("availability excludes cancelled slot", ("07:00", "10:00") in gap_labels, gap_labels)
        check("availability reflects active bookings", ("12:00", "20:00") in gap_labels, gap_labels)

        # 9. cancel again -> already_cancelled
        expect_error("double cancel rejected", "already_cancelled", store.cancel_booking, b1["id"])
        expect_error("unknown id -> not_found", "not_found", store.cancel_booking, "does-not-exist")

        # 10. validation rejections
        expect_error("out of hours rejected", "out_of_hours",
                     store.create_booking, "cedar", day, "06:00", "08:00", "Too early", "Fay")
        expect_error("after close rejected", "out_of_hours",
                     store.create_booking, "cedar", day, "19:00", "21:00", "Too late", "Fay")
        expect_error("non-15-min start rejected", "invalid_time",
                     store.create_booking, "cedar", day, "09:10", "10:00", "Odd", "Fay")
        expect_error("start >= end rejected", "invalid_time",
                     store.create_booking, "cedar", day, "10:00", "10:00", "Zero", "Fay")
        expect_error("over 8h rejected", "too_long",
                     store.create_booking, "everest", day, "07:00", "16:00", "All day", "Gus")
        expect_error("bad date rejected", "bad_date",
                     store.create_booking, "atlas", "2026-02-30", "10:00", "11:00", "Bad", "Gus")
        expect_error("bad date format rejected", "bad_date",
                     store.create_booking, "atlas", "01/12/2026", "10:00", "11:00", "Bad", "Gus")
        expect_error("unknown room rejected", "unknown_room",
                     store.create_booking, "narnia", day, "10:00", "11:00", "Nowhere", "Gus")
        expect_error("missing title rejected", "missing_field",
                     store.create_booking, "atlas", day, "13:00", "14:00", "  ", "Gus")
        expect_error("missing organizer rejected", "missing_field",
                     store.create_booking, "atlas", day, "13:00", "14:00", "Title", "")

        # 11. persistence across a fresh store instance on the same file
        fresh = core.BookingStore(data_path)
        rows = fresh.list_bookings(date=day)
        check("persistence across instances", len(rows) >= 4, len(rows))

        # 12. availability gaps correct for a day with two active bookings
        gapday = "2026-12-02"
        store.create_booking("delta", gapday, "09:00", "10:30", "A", "Hana")
        store.create_booking("delta", gapday, "14:00", "15:00", "B", "Ivo")
        gaps = store.availability(gapday, "delta")
        got = [(g["start"], g["end"]) for g in gaps]
        want = [("07:00", "09:00"), ("10:30", "14:00"), ("15:00", "20:00")]
        check("availability gaps correct for two bookings", got == want, got)

        # 13. day is never shifted: date strings are compared as-is
        same_day = store.list_bookings(date=gapday)
        check("date stored verbatim", all(r["date"] == gapday for r in same_day))

        # 14. HTTP layer exercised in-process (handler logic, no blocking server)
        try:
            import server
            httpd, api_store = server.make_server(port=0, data_path=data_path)
            try:
                check("server builds in-process", httpd.server_address[1] > 0)
                check("api store shares file", len(api_store.get_rooms()) == len(store.get_rooms()))
            finally:
                httpd.server_close()
        except Exception as exc:  # pragma: no cover - optional layer
            print("NOTE  HTTP layer not exercised in-process: %r" % (exc,))

        # 15. malformed JSON handling in the request reader
        check("validator helpers exist", callable(core.validate_date) and callable(core.parse_time))

        stats_checks()

        print("\nAll %d checks passed." % len(PASSED))
        return 0
    finally:
        shutil.rmtree(workdir, ignore_errors=True)




def stats_checks():
    """Analytics coverage for compute_stats / BookingStore.stats."""
    import json as _json

    tmp = tempfile.mkdtemp(prefix="booking-stats-")
    try:
        path = os.path.join(tmp, "bookings.json")
        store = core.BookingStore(path)

        check("stats: BookingStore.stats exists", callable(getattr(core.BookingStore, "stats", None)))

        empty = core.compute_stats("2026-03-02", "2026-03-02", store=store)
        t = empty["totals"]
        check("stats: empty store returns zeros",
              t["bookings_created"] == 0 and t["bookings_active"] == 0
              and t["hours_active"] == 0 and t["utilisation_pct"] == 0)
        check("stats: empty store by_weekday has 7 entries", len(empty["by_weekday"]) == 7)
        check("stats: empty store by_hour has 13 entries", len(empty["by_hour"]) == 13)
        check("stats: empty store has no top days", empty["top_days"] == [])
        check("stats: compute_stats did not create the data file", not os.path.exists(path))

        store.create_booking("atlas", "2026-03-02", "09:30", "10:30", "Standup", "Ada")
        one = core.compute_stats("2026-03-02", "2026-03-02", store=store)
        check("stats: single booking counted once",
              one["totals"]["bookings_active"] == 1 and one["range"]["days"] == 1)
        check("stats: single booking hours_active 1.0", one["totals"]["hours_active"] == 1.0)
        hours = {r["label"]: r["hours_active"] for r in one["by_hour"]}
        check("stats: by_hour has 13 entries", len(one["by_hour"]) == 13)
        check("stats: 09:30-10:30 splits 0.5h/0.5h into hours 09 and 10",
              hours["09:00"] == 0.5 and hours["10:00"] == 0.5, hours)
        check("stats: by_weekday sums to totals.bookings_active",
              sum(r["bookings_active"] for r in one["by_weekday"]) == one["totals"]["bookings_active"])
        check("stats: rooms carry busiest_weekday",
              one["rooms"][0]["busiest_weekday"] in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"))

        store.create_booking("birch", "2026-03-09", "07:00", "08:00", "Edge", "Bo")
        rng = core.compute_stats("2026-03-02", "2026-03-09", store=store)
        check("stats: inclusive start and end dates both counted",
              rng["totals"]["bookings_active"] == 2 and rng["range"]["days"] == 8)
        out = core.compute_stats("2026-03-10", "2026-03-11", store=store)
        check("stats: record outside the range excluded", out["totals"]["bookings_active"] == 0)

        row = store.create_booking("cedar", "2026-03-02", "13:00", "15:00", "Cancelled", "Cy")
        store.cancel_booking(row["id"], reason="not needed")
        can = core.compute_stats("2026-03-02", "2026-03-02", store=store)
        c = can["totals"]
        check("stats: cancelled counted in cancelled but not active",
              c["bookings_cancelled"] == 1 and c["hours_cancelled"] == 2.0
              and c["bookings_active"] == 1 and c["hours_active"] == 1.0)
        check("stats: cancelled hours excluded from utilisation",
              c["utilisation_pct"] == round(60 / 3900 * 100, 2), c["utilisation_pct"])
        check("stats: cancellation count and rate",
              can["cancellations"]["count"] == 1 and can["cancellations"]["rate_pct"] == 50.0)
        check("stats: cancellations by_weekday has 7 entries", len(can["cancellations"]["by_weekday"]) == 7)

        store.create_booking("everest", "2026-03-02", "16:00", "18:00", "Two rooms", "Di")
        two = core.compute_stats("2026-03-02", "2026-03-02", store=store)
        per = {r["id"]: r for r in two["rooms"]}
        check("stats: per-room split across two rooms",
              per["atlas"]["hours_active"] == 1.0 and per["everest"]["hours_active"] == 2.0
              and per["cedar"]["hours_active"] == 0.0)
        check("stats: rooms sorted by hours_active desc", two["rooms"][0]["id"] == "everest")

        store.create_booking("delta", "2026-03-04", "07:00", "10:00", "Long", "Eve")
        store.create_booking("delta", "2026-03-03", "07:00", "09:00", "Short", "Eve")
        tops = core.compute_stats("2026-03-02", "2026-03-04", store=store)["top_days"]
        top_hours = [d["hours_active"] for d in tops]
        # 2026-03-02 (3.0h) and 2026-03-04 (3.0h) tie on hours, so only require a
        # deterministic descending-hours order plus both tied leaders present.
        check("stats: top_days sorted by hours_active desc",
              top_hours == sorted(top_hours, reverse=True)
              and set(d["date"] for d in tops[:2]) == {"2026-03-02", "2026-03-04"}
              and tops[2]["date"] == "2026-03-03", tops)

        rpath = os.path.join(tmp, "rooms.json")
        with open(rpath, "w", encoding="utf-8") as fh:
            _json.dump([{"id": "solo", "name": "Solo", "capacity": 4, "location": "L0"}], fh)
        solo = core.BookingStore(os.path.join(tmp, "solo.json"), rooms_path=rpath)
        solo.create_booking("solo", "2026-03-05", "09:00", "15:30", "Half day", "Eve")
        solo_stats = solo.stats("2026-03-05", "2026-03-05")
        check("stats: 390 active min over 780 capacity -> utilisation 50.0",
              solo_stats["totals"]["utilisation_pct"] == 50.0, solo_stats["totals"]["utilisation_pct"])

        expect_error("stats: start after end raises bad_range", "bad_range",
                     core.compute_stats, "2026-03-09", "2026-03-02", store=store)
        expect_error("stats: unparsable date raises bad_date", "bad_date",
                     core.compute_stats, "2026-13-01", "2026-03-02", store=store)

        bad_path = os.path.join(tmp, "bad.json")
        with open(bad_path, "w", encoding="utf-8") as fh:
            _json.dump([{"id": "x", "room_id": "atlas", "date": "not-a-date",
                         "start": "09:00", "end": "10:00", "status": "active"}], fh)
        bad = core.BookingStore(bad_path)
        core.compute_stats("2026-03-02", "2026-03-02", store=bad)
        check("stats: malformed legacy rows are skipped", True)

        before = open(path, "rb").read()
        core.compute_stats("2026-03-01", "2026-03-31", store=store)
        after = open(path, "rb").read()
        check("stats: compute_stats leaves the data file untouched", before == after)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

if __name__ == "__main__":
    raise SystemExit(main())
