#!/usr/bin/env python3
"""Shared meeting-room booking server (Python standard library only).

Usage:
    python3 server.py [--port 8080] [--data bookings.json] [--rooms rooms.json]

Serves index.html at / and a small JSON API.  Binds 0.0.0.0 so colleagues on
 the LAN can use it.  No third-party packages, no subprocess, no network
calls out (it only listens).
"""

import argparse
import json
import os
import socket
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import booking as core

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX_PATH = os.path.join(HERE, "index.html")
DASHBOARD_PATH = os.path.join(HERE, "dashboard.html")


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "MeetingRoomBookings/1.0"
    store = None  # injected by make_server()

    # ---------- helpers ----------
    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        """Return (dict, error).  Never raises on malformed input."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            return {}, ("invalid", "Content-Length header is not a number")
        if length < 0 or length > 1_000_000:
            return {}, ("invalid_json", "Request body is too large")
        raw = self.rfile.read(length) if length else b""
        if not raw.strip():
            return {}, None
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}, ("invalid_json", "Request body is not valid JSON")
        if not isinstance(data, dict):
            return {}, ("invalid_json", "Request body must be a JSON object")
        return data, None

    # ---------- GET ----------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        try:
            if path in ("/", "/index.html"):
                self._serve_index()
            elif path in ("/dashboard", "/dashboard.html"):
                self._serve_dashboard()
            elif path == "/api/rooms":
                self._send_json(200, {"rooms": self.store.get_rooms()})
            elif path == "/api/bookings":
                self._get_bookings(query)
            elif path == "/api/availability":
                self._get_availability(query)
            elif path == "/api/stats":
                self._get_stats(query)
            elif path == "/api/health":
                self._send_json(200, {"ok": True})
            else:
                self._send_json(404, {"error": "not_found", "message": "Unknown path: %s" % parsed.path})
        except Exception as exc:  # never crash the worker
            self._send_json(500, {"error": "server_error", "message": str(exc)})

    def _serve_index(self):
        if not os.path.exists(INDEX_PATH):
            self._send_json(500, {"error": "missing_file", "message": "index.html not found next to server.py"})
            return
        with open(INDEX_PATH, "rb") as fh:
            body = fh.read()
        self._send_bytes(200, body, "text/html; charset=utf-8")

    def _get_bookings(self, query):
        date = (query.get("date") or [None])[0]
        room = (query.get("room") or [None])[0]
        include_cancelled = (query.get("include_cancelled") or ["1"])[0] not in ("0", "false", "no")
        if date:
            try:
                core.validate_date(date)
            except core.BookingError as exc:
                self._send_json(400, exc.to_dict())
                return
        rows = self.store.list_bookings(date=date, room_id=room, include_cancelled=include_cancelled)
        self._send_json(200, {"bookings": rows, "count": len(rows)})

    def _get_availability(self, query):
        date = (query.get("date") or [None])[0]
        room = (query.get("room") or [None])[0]
        if not date or not room:
            self._send_json(400, {"error": "missing_field", "message": "Both date and room are required"})
            return
        try:
            gaps = self.store.availability(date, room)
        except core.BookingError as exc:
            status = 404 if exc.code == "unknown_room" else 400
            self._send_json(status, exc.to_dict())
            return
        self._send_json(200, {"date": date, "room_id": room, "gaps": gaps})

    def _serve_dashboard(self):
        if not os.path.exists(DASHBOARD_PATH):
            self._send_json(500, {"error": "missing_file", "message": "dashboard.html not found next to server.py"})
            return
        with open(DASHBOARD_PATH, "rb") as fh:
            body = fh.read()
        self._send_bytes(200, body, "text/html; charset=utf-8")

    def _get_stats(self, query):
        start = (query.get("start") or [""])[0].strip()
        end = (query.get("end") or [""])[0].strip()
        if not start or not end:
            self._send_json(400, {"error": "bad_request",
                                  "message": "Both start and end query parameters are required (YYYY-MM-DD)."})
            return
        try:
            stats = self.store.stats(start, end)
        except core.BookingError as exc:
            if exc.code == "bad_range":
                self._send_json(400, {"error": "bad_range", "message": exc.message})
            else:
                self._send_json(400, {"error": "bad_date", "message": exc.message})
            return
        except Exception as exc:  # never crash on odd data
            self._send_json(500, {"error": "server_error", "message": str(exc)})
            return
        self._send_json(200, stats)

    # ---------- POST ----------
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        try:
            if path == "/api/bookings":
                self._create_booking()
            elif path.startswith("/api/bookings/"):
                parts = [p for p in parsed.path.split("/") if p]
                # ['api', 'bookings', '<id>', 'cancel']
                if len(parts) == 4 and parts[3] == "cancel":
                    self._cancel_booking(parts[2])
                else:
                    self._send_json(404, {"error": "not_found", "message": "Unknown path: %s" % parsed.path})
            else:
                self._send_json(404, {"error": "not_found", "message": "Unknown path: %s" % parsed.path})
        except Exception as exc:
            self._send_json(500, {"error": "server_error", "message": str(exc)})

    def _create_booking(self):
        data, err = self._read_json_body()
        if err:
            self._send_json(400, {"error": err[0], "message": err[1]})
            return
        try:
            row = self.store.create_booking(
                room_id=data.get("room_id") or data.get("room"),
                date=data.get("date"),
                start=data.get("start"),
                end=data.get("end"),
                title=data.get("title"),
                organizer=data.get("organizer"),
                attendees=data.get("attendees") or "",
                notes=data.get("notes") or "",
            )
        except core.BookingError as exc:
            status = 409 if exc.code == "conflict" else 400
            self._send_json(status, exc.to_dict())
            return
        self._send_json(201, {"booking": row})

    def _cancel_booking(self, booking_id):
        data, err = self._read_json_body()
        if err:
            self._send_json(400, {"error": err[0], "message": err[1]})
            return
        reason = data.get("reason") or ""
        try:
            row = self.store.cancel_booking(booking_id, reason=reason)
        except core.BookingError as exc:
            status = 404 if exc.code == "not_found" else 400
            self._send_json(status, exc.to_dict())
            return
        self._send_json(200, {"booking": row})

    def do_PUT(self):
        self._send_json(405, {"error": "method_not_allowed", "message": "Use GET or POST"})

    do_DELETE = do_PUT
    do_PATCH = do_PUT

    def log_message(self, fmt, *args):  # quiet-ish logging
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))


def make_server(port=8080, data_path="bookings.json", rooms_path=None):
    """Create (but do not start) a server.  Usable from tests in-process."""
    store = core.BookingStore(path=data_path, rooms_path=rooms_path)
    handler = type("BoundApiHandler", (ApiHandler,), {"store": store})
    httpd = ThreadingHTTPServer(("0.0.0.0", port), handler)
    httpd.daemon_threads = True
    return httpd, store


def lan_urls(port):
    urls = ["http://localhost:%d/" % port]
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127.") and ("http://%s:%d/" % (ip, port)) not in urls:
                urls.append("http://%s:%d/" % (ip, port))
    except OSError:
        pass
    try:
        # Fallback: discover the primary LAN address without sending packets.
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127.") and ("http://%s:%d/" % (ip, port)) not in urls:
                urls.append("http://%s:%d/" % (ip, port))
        finally:
            s.close()
    except OSError:
        pass
    return urls


def main(argv=None):
    parser = argparse.ArgumentParser(description="Shared meeting-room booking server")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--data", default=os.path.join(HERE, "bookings.json"))
    parser.add_argument("--rooms", default=None, help="optional rooms.json override")
    args = parser.parse_args(argv)

    httpd, store = make_server(port=args.port, data_path=args.data, rooms_path=args.rooms)
    print("Meeting-room booking server running.")
    print("Data file: %s" % os.path.abspath(args.data))
    print("Rooms: %s" % ", ".join(r["id"] for r in store.get_rooms()))
    print("Open one of these URLs (share the LAN one with colleagues):")
    for url in lan_urls(httpd.server_address[1]):
        print("  %s" % url)
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
