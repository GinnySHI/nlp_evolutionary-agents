"""Independent fixed-rubric checks; run on unmodified delivery COPIES in Sandbox.

No sockets, external dependencies, credentials, or changes to delivered source.
The HTTP handlers are invoked directly with in-memory streams because Seatbelt
does not permit network listeners. Browser interaction is a separate check.
"""
import hashlib
import io
import json
from pathlib import Path
import re
import runpy
import sys
import tempfile
import traceback

import booking as core
import server as web

ROOT = Path(__file__).resolve().parent
RESULT = ROOT / "software-2-result.json"
D1, D2, D3 = "2026-12-01", "2026-12-02", "2026-12-03"
criteria = {}
supplementary = {}
artifacts = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
             for p in ROOT.iterdir()
             if p.is_file() and p.name in {"booking.py", "server.py", "index.html",
                                          "dashboard.html", "selftest.py", "README.md", "NOTES-dashboard.md"}}


def record(cid, fn):
    try:
        evidence = fn()
        criteria[cid] = {"id": cid, "status": "pass", "evidence": evidence}
    except Exception:
        criteria[cid] = {"id": cid, "status": "fail",
                         "evidence": traceback.format_exc(limit=5)}
    print(json.dumps(criteria[cid], ensure_ascii=False))


def make_store(tag):
    return core.BookingStore(str(Path(tempfile.mkdtemp(prefix=tag)) / "bookings.json"))


def book(store, room, day, start, end):
    return store.create_booking(room, day, start, end, "Independent fixture", "Reviewer")


def error_code(fn, *args):
    try:
        fn(*args)
    except core.BookingError as exc:
        return exc.code
    return None


class CaptureHandler(web.ApiHandler):
    """Exercise delivered dispatch/handler code without opening any socket."""
    def __init__(self, store, path, body=None):
        self.store = store
        self.path = path
        raw = json.dumps(body or {}).encode()
        self.headers = {"Content-Length": str(len(raw))}
        self.rfile = io.BytesIO(raw)
        self.response = None

    def _send_json(self, status, payload):
        self.response = status, payload, "application/json"

    def _send_bytes(self, status, body, content_type):
        self.response = status, body, content_type


def request(store, path, body=None):
    handler = CaptureHandler(store, path, body)
    (handler.do_GET if body is None else handler.do_POST)()
    assert handler.response is not None, "handler did not respond"
    return handler.response


def check_documented_entrypoint(data_path):
    """Exercise the real __main__ order with a no-network HTTP server adapter."""
    import http.server
    import socket
    responses = []

    class OfflineServer:
        def __init__(self, address, handler):
            self.server_address = address
            self.handler = handler

        def serve_forever(self):
            probe_class = type("OfflineHandler", (self.handler,), {
                "__init__": CaptureHandler.__init__,
                "_send_json": CaptureHandler._send_json,
                "_send_bytes": CaptureHandler._send_bytes,
            })
            probe = probe_class(self.handler.store, "/dashboard")
            probe.do_GET()
            responses.append(probe.response)

        def server_close(self):
            pass

    def unavailable_socket(*args, **kwargs):
        raise OSError("Independent reviewer disables network discovery")

    originals = http.server.ThreadingHTTPServer, socket.socket, socket.getaddrinfo, sys.argv
    try:
        http.server.ThreadingHTTPServer = OfflineServer
        socket.socket = unavailable_socket
        socket.getaddrinfo = lambda *a, **k: []
        sys.argv = [str(ROOT / "server.py"), "--data", data_path, "--port", "8080"]
        try:
            runpy.run_path(str(ROOT / "server.py"), run_name="__main__")
        except SystemExit as exc:
            assert exc.code == 0, exc.code
        assert responses and responses[0][0] == 200, responses
        assert responses[0][1] == (ROOT / "dashboard.html").read_bytes()
    finally:
        http.server.ThreadingHTTPServer, socket.socket, socket.getaddrinfo, sys.argv = originals
    return "server.py __main__ executed; no-network server adapter dispatched /dashboard successfully"


fixture = make_store("independent-dashboard-")
rooms = fixture.get_rooms()
A, B = rooms[0]["id"], rooms[1]["id"]
book(fixture, A, D1, "09:00", "10:00")
book(fixture, A, D1, "10:00", "12:00")
book(fixture, B, D2, "09:00", "10:00")
cancelled = book(fixture, A, D2, "14:00", "15:00")
fixture.cancel_booking(cancelled["id"], reason="Fixed rubric cancellation")
book(fixture, B, D3, "16:00", "18:00")
stats = core.compute_stats(D1, D2, store=fixture)
per_room = {r["id"]: r for r in stats["rooms"]}
fixture_rows = fixture.list_bookings()
(ROOT / "fixture-records.json").write_text(json.dumps(fixture_rows, indent=2))
(ROOT / "fixture-stats.json").write_text(json.dumps(stats, indent=2))


def existing_system():
    fresh = make_store("independent-existing-")
    body = {"room_id": A, "date": D1, "start": "09:00", "end": "10:00",
            "title": "HTTP creation", "organizer": "Reviewer"}
    status, payload, _ = request(fresh, "/api/bookings", body)
    assert status == 201, (status, payload)
    created = payload["booking"]
    assert fresh.get_booking(created["id"])["status"] == "active"
    assert error_code(book, fresh, A, D1, "09:30", "10:30") == "conflict"
    assert error_code(book, fresh, A, D1, "09:15", "09:45") == "conflict"
    book(fresh, A, D1, "10:00", "12:00")
    book(fresh, B, D1, "09:00", "10:00")
    status, payload, _ = request(fresh, "/api/bookings/" + created["id"] + "/cancel", {"reason": "test"})
    assert status == 200 and payload["booking"]["status"] == "cancelled"
    assert any(g["start"] <= "09:00" and g["end"] >= "10:00" for g in fresh.availability(D1, A))
    persisted = core.BookingStore(fresh.path)
    assert persisted.get_booking(created["id"])["status"] == "cancelled"
    assert persisted.stats(D1, D1)["totals"]["bookings_cancelled"] == 1
    before = Path(fixture.path).read_bytes()
    before_mtime = Path(fixture.path).stat().st_mtime_ns
    status, data, _ = request(fixture, "/api/stats?start=" + D1 + "&end=" + D2)
    assert status == 200 and data == stats, (status, data)
    assert Path(fixture.path).read_bytes() == before
    assert Path(fixture.path).stat().st_mtime_ns == before_mtime
    status, page, mime = request(fixture, "/dashboard")
    assert status == 200 and page == (ROOT / "dashboard.html").read_bytes(), (status, page)
    assert mime.startswith("text/html")
    assert request(fixture, "/dashboard.html")[0] == 200
    assert request(fixture, "/")[0] == 200
    documentation = {p.name: p.read_text() for p in [ROOT / "README.md", ROOT / "NOTES-dashboard.md"] if p.exists()}
    documented_text = "\n".join(documentation.values())
    assert "server.py" in documented_text and "dashboard" in documented_text.lower()
    launch_evidence = check_documented_entrypoint(fixture.path)
    return {"api_stats_equals_direct_aggregation": True, "dashboard_routes": ["/dashboard", "/dashboard.html"],
            "api_create_cancel": True, "overlap_containment_rejected": True,
            "adjacent_and_other_room_accepted": True, "cancellation_durable": True,
            "analytics_is_read_only": True, "documented_launch": "server.py",
            "documentation": list(documentation),
            "entrypoint": launch_evidence,
            "execution": "Seatbelt; actual handler dispatch, no network listener"}


def date_selection():
    responses = {}
    fixture_responses = {}
    for start, end, count, hours in [(D1, D1, 2, 3.0), (D2, D2, 1, 1.0), (D1, D2, 3, 4.0), (D3, D3, 1, 2.0),
                                    ("2026-11-01", "2026-11-30", 0, 0.0)]:
        status, data, _ = request(fixture, "/api/stats?start=" + start + "&end=" + end)
        assert status == 200
        assert data["range"]["start"] == start and data["range"]["end"] == end
        assert data["totals"]["bookings_active"] == count and data["totals"]["hours_active"] == hours
        responses[start + "/" + end] = {"bookings_active": count, "hours_active": hours}
        fixture_responses[start + "|" + end] = data
    (ROOT / "fixture-responses.json").write_text(json.dumps(fixture_responses, indent=2))
    for query, code in [("", "bad_request"), ("?start=" + D1, "bad_request"),
                        ("?start=2026-02-30&end=" + D2, "bad_date"),
                        ("?start=" + D3 + "&end=" + D1, "bad_range")]:
        status, data, _ = request(fixture, "/api/stats" + query)
        assert status == 400 and data["error"] == code, (status, data)
    assert request(fixture, "/api/no-such-route")[0] == 404
    return {"range_specific_responses": responses, "both_endpoints_included": True,
            "missing_invalid_reversed_rejected": True,
            "browser_interaction": "Requires separate browser evidence; this is backend verification."}


def room_count():
    assert per_room[A]["bookings_active"] == 2
    assert per_room[B]["bookings_active"] == 1
    assert len(per_room) == len(rooms)
    unused = [r["id"] for r in rooms[2:]]
    assert all(per_room[r]["bookings_active"] == 0 for r in unused)
    return {A: 2, B: 1, "unused_rooms_zero": unused,
            "total_active": stats["totals"]["bookings_active"]}


def room_hours():
    assert per_room[A]["hours_active"] == 3.0
    assert per_room[B]["hours_active"] == 1.0
    assert per_room[A]["hours_cancelled"] == 1.0
    assert stats["totals"]["hours_active"] == 4.0
    assert stats["totals"]["utilisation_pct"] == round(4 / (len(rooms) * 2 * 13) * 100, 2)
    assert all(per_room[r["id"]]["hours_active"] == 0 for r in rooms[2:])
    return {A: "3 active hours; 1 cancelled hour excluded", B: "1 active hour",
            "all_rooms_active_hours": 4.0, "outside_D3_excluded": True,
            "range_policy": "inclusive booking date; active reserved duration only",
            "utilisation_pct": stats["totals"]["utilisation_pct"]}


def busy_days_hours():
    top = stats["top_days"]
    assert top[0] == {"date": D1, "bookings_active": 2, "hours_active": 3.0}, top
    assert top[1] == {"date": D2, "bookings_active": 1, "hours_active": 1.0}, top
    hours = {r["label"]: r["hours_active"] for r in stats["by_hour"]}
    assert len(hours) == 13
    assert hours["09:00"] == 2.0 and hours["10:00"] == 1.0 and hours["11:00"] == 1.0
    assert sum(hours.values()) == 4.0
    weekdays = stats["by_weekday"]
    assert len(weekdays) == 7 and sum(r["bookings_active"] for r in weekdays) == 3
    assert sum(r["hours_active"] for r in weekdays) == 4.0
    fractional = make_store("independent-hour-split-")
    book(fractional, A, D1, "09:30", "10:30")
    split = {r["label"]: r["hours_active"] for r in fractional.stats(D1, D1)["by_hour"]}
    assert split["09:00"] == .5 and split["10:00"] == .5 and sum(split.values()) == 1.0
    return {"top_days": top, "hourly_active_hours": hours,
            "fractional_booking_0930_1030": {"09:00": .5, "10:00": .5},
            "weekday_totals_match": True}


def cancellations():
    assert stats["totals"]["bookings_created"] == 4
    assert stats["totals"]["bookings_cancelled"] == 1
    assert stats["totals"]["cancellation_rate_pct"] == 25.0
    assert per_room[A]["bookings_cancelled"] == 1 and per_room[B]["bookings_cancelled"] == 0
    assert stats["cancellations"]["count"] == 1 and stats["cancellations"]["rate_pct"] == 25.0
    assert fixture.get_booking(cancelled["id"])["status"] == "cancelled"
    assert stats["cancellations"]["by_room"] == [{"room_id": A, "name": rooms[0]["name"], "count": 1}]
    assert sum(r["count"] for r in stats["cancellations"]["by_weekday"]) == 1
    return {"retained_cancelled_records": 1, "overall_rate": "1 / 4 = 25%",
            "A_count": 1, "B_count": 0, "denominator": "all active and cancelled bookings with booked date in range"}


def charts():
    page = (ROOT / "dashboard.html").read_text()
    scripts = re.findall(r"<script\b[^>]*>(.*?)</script>", page, re.I | re.S)
    assert scripts, "No inline rendering/interaction script"
    assert not re.search(r"<script\b[^>]*\bsrc=", page, re.I)
    assert len(re.findall(r"type=[\"']date[\"']", page, re.I)) >= 2
    assert "/api/stats" in page, "No actual stats endpoint reference"
    assert "rooms" in page and "hours_active" in page
    assert "by_weekday" in page and "by_hour" in page
    assert "cancellation" in page.lower()
    return {"static": {"date_inputs": True, "actual_stats_endpoint": True,
                       "room_hours_weekday_hour_cancellation_rendering_references": True,
                       "self_contained_scripts": True},
            "browser_visual_and_interaction": "Not performed by this Python script."}


for cid, fn in [("existing_system", existing_system), ("date_selection", date_selection),
                ("per_room_count", room_count), ("per_room_duration", room_hours),
                ("busiest_days_times", busy_days_hours), ("cancellation_frequency", cancellations),
                ("clear_charts_summaries", charts)]:
    record(cid, fn)

empty = make_store("independent-empty-")
empty_result = empty.stats(D1, D2)
supplementary["empty_store"] = {
    "zero_counts_and_duration": empty_result["totals"]["bookings_created"] == 0 and empty_result["totals"]["hours_active"] == 0,
    "all_rooms_present": len(empty_result["rooms"]) == len(rooms),
    "read_did_not_create_data": not Path(empty.path).exists(),
}

# Backend pass and static evidence are not a substitute for frontend runtime QA.
for cid in ("date_selection", "clear_charts_summaries"):
    if criteria[cid]["status"] == "pass":
        criteria[cid]["backend_static_status"] = "pass"
        criteria[cid]["status"] = "unverified"
        criteria[cid]["pending"] = "Separate browser interaction/visual evidence."

result = {"task_id": "software-2", "rubric": "software-rubric.md",
          "artifact_hashes": artifacts, "rooms": {"A": A, "B": B},
          "fixture_dates": [D1, D2, D3], "criteria": list(criteria.values()),
          "mandatory_criteria_total": 7,
          "mandatory_criteria_passed": sum(c["status"] == "pass" for c in criteria.values()),
          "artifact_success": all(c["status"] == "pass" for c in criteria.values()),
          "supplementary": supplementary,
          "method": "Unmodified copies imported and executed in Seatbelt. HTTP handlers exercised with in-memory streams; no network listener or browser invoked.",
          "reviewer_repairs": False}
RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2))
print("RESULT", json.dumps({k: result[k] for k in ("mandatory_criteria_passed", "artifact_success")}))
