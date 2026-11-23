"""Core booking logic for the meeting-room booking system.

Pure standard library. No side effects at import time (no file is created until
the first write). Dates (YYYY-MM-DD) and times (HH:MM) are handled as plain
wall-clock strings / integer minutes; nothing is ever converted through UTC, so
no day can shift because of a timezone.
"""

import datetime
import json
import os
import tempfile
import threading
import uuid

# --- Policy constants -------------------------------------------------------
OPEN_MINUTES = 7 * 60          # 07:00
CLOSE_MINUTES = 20 * 60        # 20:00
STEP_MINUTES = 15
MAX_DURATION_MINUTES = 8 * 60  # 8 hours

STATUS_ACTIVE = "active"
STATUS_CANCELLED = "cancelled"

DEFAULT_ROOMS = [
    {"id": "atlas", "name": "Atlas", "capacity": 8, "location": "Level 1"},
    {"id": "birch", "name": "Birch", "capacity": 6, "location": "Level 1"},
    {"id": "cedar", "name": "Cedar", "capacity": 4, "location": "Level 2"},
    {"id": "delta", "name": "Delta", "capacity": 12, "location": "Level 2"},
    {"id": "everest", "name": "Everest", "capacity": 20, "location": "Level 3"},
]


class BookingError(Exception):
    """Error with a machine-readable ``code`` plus a human ``message``."""

    def __init__(self, code, message, existing=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.existing = existing

    def to_dict(self):
        payload = {"error": self.code, "message": self.message}
        if self.existing is not None:
            payload["existing"] = self.existing
        return payload


# --- Small helpers ----------------------------------------------------------
def _now_iso():
    return datetime.datetime.now().replace(microsecond=0).isoformat()


def validate_date(value):
    """Return the date string if it is a real calendar date in YYYY-MM-DD."""
    if not isinstance(value, str) or len(value) != 10 or value[4] != "-" or value[7] != "-":
        raise BookingError("bad_date", "Date must look like YYYY-MM-DD (e.g. 2026-11-24).")
    if not (value[:4] + value[5:7] + value[8:]).isdigit():
        raise BookingError("bad_date", "Date must look like YYYY-MM-DD (e.g. 2026-11-24).")
    try:
        datetime.date(int(value[:4]), int(value[5:7]), int(value[8:]))
    except ValueError:
        raise BookingError("bad_date", "%s is not a real calendar date." % value)
    return value


def parse_time(value, field="time"):
    """'HH:MM' -> minutes since midnight. Enforces 24h clock and 15-min steps."""
    if not isinstance(value, str):
        raise BookingError("invalid_time", "%s must be a HH:MM string." % field)
    value = value.strip()
    parts = value.split(":")
    if len(parts) != 2 or len(parts[0]) != 2 or len(parts[1]) != 2:
        raise BookingError("invalid_time", "%s must be HH:MM (e.g. 09:30), got %r." % (field, value))
    if not parts[0].isdigit() or not parts[1].isdigit():
        raise BookingError("invalid_time", "%s must be HH:MM (e.g. 09:30), got %r." % (field, value))
    hours, minutes = int(parts[0]), int(parts[1])
    if hours > 23 or minutes > 59:
        raise BookingError("invalid_time", "%s %r is not a valid time of day." % (field, value))
    if minutes % STEP_MINUTES:
        raise BookingError("invalid_time", "%s %r must be on a %d-minute step (00:00, 00:15, 00:30, 00:45)." % (field, value, STEP_MINUTES))
    return hours * 60 + minutes


def format_minutes(total):
    return "%02d:%02d" % (total // 60, total % 60)


def _text(value):
    if value is None:
        return ""
    return str(value).strip()


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open interval overlap: 10:00-11:00 and 11:00-12:00 do NOT clash."""
    return a_start < b_end and a_end > b_start


def _atomic_write_json(path, payload):
    """Write JSON to ``path`` atomically (temp file in same dir + os.replace)."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".booking-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def load_rooms(rooms_path=None):
    """DEFAULT_ROOMS, overridable by an optional rooms.json."""
    if rooms_path and os.path.exists(rooms_path):
        try:
            with open(rooms_path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
            rooms = raw.get("rooms", raw) if isinstance(raw, dict) else raw
            cleaned = []
            for item in rooms:
                room_id = _text(item.get("id") or item.get("name")).lower()
                name = _text(item.get("name")) or room_id.title()
                if not room_id:
                    continue
                cleaned.append({
                    "id": room_id,
                    "name": name,
                    "capacity": int(item.get("capacity") or 0),
                    "location": _text(item.get("location")) or "",
                })
            if cleaned:
                return cleaned
        except (OSError, ValueError, AttributeError, TypeError):
            pass  # fall through to defaults; a broken rooms.json must not stop the app
    return [dict(room) for room in DEFAULT_ROOMS]


# --- Store ------------------------------------------------------------------
class BookingStore:
    """JSON-file backed store; every read-modify-write runs under one lock."""

    def __init__(self, path="bookings.json", rooms_path=None):
        self.path = path
        self.rooms = load_rooms(rooms_path)
        self._lock = threading.Lock()

    # -- persistence --
    def _read_all(self):
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except (OSError, ValueError):
            return []
        bookings = raw.get("bookings", []) if isinstance(raw, dict) else raw
        return [b for b in bookings if isinstance(b, dict)] if isinstance(bookings, list) else []

    def _write_all(self, bookings):
        _atomic_write_json(self.path, {"bookings": bookings})

    # -- rooms --
    def get_rooms(self):
        return [dict(room) for room in self.rooms]

    def get_room(self, room_id):
        wanted = _text(room_id).lower()
        for room in self.rooms:
            if room["id"] == wanted:
                return room
        for room in self.rooms:
            if room["name"].lower() == wanted:
                return room
        return None

    # -- reads --
    def list_bookings(self, date=None, room_id=None, include_cancelled=True, include_all_dates=False):
        bookings = self._read_all()
        if date is not None:
            date = validate_date(date)
        wanted_room = _text(room_id).lower() if room_id else ""
        result = []
        for booking in bookings:
            if date is not None and booking.get("date") != date and not include_all_dates:
                continue
            if wanted_room and booking.get("room_id") != wanted_room:
                continue
            if not include_cancelled and booking.get("status") != STATUS_ACTIVE:
                continue
            result.append(booking)
        order = {room["id"]: index for index, room in enumerate(self.rooms)}
        result.sort(key=lambda b: (b.get("date", ""), order.get(b.get("room_id"), 99), b.get("start", "")))
        return result

    def get_booking(self, booking_id):
        for booking in self._read_all():
            if booking.get("id") == booking_id:
                return booking
        return None

    def availability(self, date, room_id):
        """Free gaps between 07:00 and 20:00 for one room on one day."""
        date = validate_date(date)
        room = self.get_room(room_id)
        if room is None:
            raise BookingError("unknown_room", "Unknown room %r." % room_id)
        busy = []
        for booking in self.list_bookings(date=date, room_id=room["id"], include_cancelled=False):
            busy.append((parse_time(booking["start"], "start"), parse_time(booking["end"], "end")))
        busy.sort()
        gaps = []
        cursor = OPEN_MINUTES
        for start, end in busy:
            if start > cursor:
                gaps.append({"start": format_minutes(cursor), "end": format_minutes(min(start, CLOSE_MINUTES))})
            cursor = max(cursor, end)
        if cursor < CLOSE_MINUTES:
            gaps.append({"start": format_minutes(cursor), "end": format_minutes(CLOSE_MINUTES)})
        return [gap for gap in gaps if gap["start"] < gap["end"]]

    def day_summary(self, date):
        """Rooms plus their active bookings and free gaps for one day."""
        date = validate_date(date)
        output = []
        for room in self.get_rooms():
            active = self.list_bookings(date=date, room_id=room["id"], include_cancelled=False)
            output.append({
                "room": room,
                "bookings": active,
                "free": self.availability(date, room["id"]),
            })
        return output

    def stats(self, start_date, end_date):
        """Read-only aggregate statistics for the inclusive date range."""
        return compute_stats(start_date, end_date, self)

    # -- writes (lock held across check-and-insert) --
    def create_booking(self, room_id, date, start, end, title, organizer,
                       attendees="", notes=""):
        room = self.get_room(room_id)
        if room is None:
            raise BookingError("unknown_room", "Unknown room %r." % room_id)
        date = validate_date(date)
        start_minutes = parse_time(start, "start")
        end_minutes = parse_time(end, "end")
        title = _text(title)
        organizer = _text(organizer)
        if not title:
            raise BookingError("missing_field", "Please give the meeting a title.")
        if not organizer:
            raise BookingError("missing_field", "Please say who is organising the meeting.")
        if start_minutes >= end_minutes:
            raise BookingError("invalid_time", "End time must be after start time.")
        if start_minutes < OPEN_MINUTES or end_minutes > CLOSE_MINUTES:
            raise BookingError("out_of_hours", "Rooms can only be booked between 07:00 and 20:00.")
        if end_minutes - start_minutes > MAX_DURATION_MINUTES:
            raise BookingError("too_long", "A single booking may be at most 8 hours long.")

        start_text = format_minutes(start_minutes)
        end_text = format_minutes(end_minutes)
        record = {
            "id": uuid.uuid4().hex[:10],
            "room_id": room["id"],
            "room_name": room["name"],
            "date": date,
            "start": start_text,
            "end": end_text,
            "title": title,
            "organizer": organizer,
            "attendees": _text(attendees),
            "notes": _text(notes),
            "status": STATUS_ACTIVE,
            "created_at": _now_iso(),
            "cancelled_at": None,
            "cancel_reason": "",
        }

        with self._lock:
            bookings = self._read_all()
            for other in bookings:
                if other.get("status") != STATUS_ACTIVE:
                    continue
                if other.get("room_id") != room["id"] or other.get("date") != date:
                    continue
                other_start = parse_time(other["start"], "start")
                other_end = parse_time(other["end"], "end")
                if _overlaps(start_minutes, end_minutes, other_start, other_end):
                    message = (
                        "%s is already booked on %s from %s to %s by %s (\"%s\")."
                        % (room["name"], date, other["start"], other["end"],
                           other.get("organizer", "someone"), other.get("title", "a meeting"))
                    )
                    raise BookingError("conflict", message, existing=other)
            bookings.append(record)
            self._write_all(bookings)
        return dict(record)

    def cancel_booking(self, booking_id, reason=""):
        booking_id = _text(booking_id)
        if not booking_id:
            raise BookingError("not_found", "Booking id is required.")
        with self._lock:
            bookings = self._read_all()
            target = None
            for booking in bookings:
                if booking.get("id") == booking_id:
                    target = booking
                    break
            if target is None:
                raise BookingError("not_found", "No booking with id %r." % booking_id)
            if target.get("status") == STATUS_CANCELLED:
                raise BookingError("already_cancelled", "That booking was already cancelled.")
            target["status"] = STATUS_CANCELLED
            target["cancelled_at"] = _now_iso()
            target["cancel_reason"] = _text(reason)
            self._write_all(bookings)
            return dict(target)

    # -- read-only analytics --
    def stats(self, start_date, end_date):
        """Read-only aggregate statistics for the inclusive date range."""
        return compute_stats(start_date, end_date, store=self)


# --- Module-level default store --------------------------------------------
_default_lock = threading.Lock()
_default_store = None


def configure(data_path="bookings.json", rooms_path=None):
    """Point the module-level helper functions at a data file."""
    global _default_store
    with _default_lock:
        _default_store = BookingStore(data_path, rooms_path)
        return _default_store


def default_store():
    global _default_store
    with _default_lock:
        if _default_store is None:
            _default_store = BookingStore("bookings.json")
        return _default_store


def _store(store):
    return store if store is not None else default_store()


# --- Convenience API --------------------------------------------------------
def get_rooms(store=None):
    return _store(store).get_rooms()


def create_booking(room_id, date, start, end, title, organizer="", attendees="",
                   notes="", store=None):
    return _store(store).create_booking(room_id, date, start, end, title,
                                        organizer, attendees, notes)


def cancel_booking(booking_id, reason="", store=None):
    return _store(store).cancel_booking(booking_id, reason)


def list_bookings(date=None, room_id=None, include_cancelled=True, store=None):
    return _store(store).list_bookings(date=date, room_id=room_id,
                                       include_cancelled=include_cancelled)


def availability(date, room_id, store=None):
    return _store(store).availability(date, room_id)


# --- Analytics (read-only aggregates) --------------------------------------
DAY_CAPACITY_MINUTES = CLOSE_MINUTES - OPEN_MINUTES          # 780 per room-day
WEEKDAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
HOUR_BUCKETS = list(range(OPEN_MINUTES // 60, CLOSE_MINUTES // 60))   # 7..19


def _date_arg(value, field):
    try:
        return validate_date(value)
    except BookingError:
        raise BookingError('bad_date', '%s must be a real calendar date in YYYY-MM-DD, got %r.' % (field, value))


def _pct(part, whole):
    if not whole:
        return 0.0
    return round(float(part) / float(whole) * 100.0, 2)


def _hours(minutes):
    return round(float(minutes) / 60.0, 2)


def _weekday_index(day):
    return datetime.date(int(day[:4]), int(day[5:7]), int(day[8:])).weekday()


def _hour_parts(start_text, end_text):
    '''Split a wall-clock span into (clock_hour, minutes) pieces at hour edges.'''
    start = parse_time(start_text, 'start')
    end = parse_time(end_text, 'end')
    parts = []
    cursor = start
    while cursor < end:
        hour = cursor // 60
        edge = min(end, (hour + 1) * 60)
        parts.append((hour, edge - cursor))
        cursor = edge
    return parts


def compute_stats(start_date, end_date, store=None):
    '''Read-only statistics for the inclusive wall-clock range [start, end].

    Dates are compared as YYYY-MM-DD strings and times as integer minutes, so
    nothing can shift a booking to another day.  Cancelled bookings keep their
    booked duration in hours_cancelled but never add to hours_active or to
    utilisation.
    '''
    start = _date_arg(start_date, 'start')
    end = _date_arg(end_date, 'end')
    if start > end:
        raise BookingError('bad_range', 'Start date %s is after end date %s.' % (start, end))
    first = datetime.date(int(start[:4]), int(start[5:7]), int(start[8:]))
    last = datetime.date(int(end[:4]), int(end[5:7]), int(end[8:]))
    days = (last - first).days + 1
    store = _store(store)
    rooms = [dict(room) for room in store.get_rooms()]
    room_pos = {room['id']: index for index, room in enumerate(rooms)}
    per_room = []
    for _room in rooms:
        per_room.append({
            'bookings_created': 0,
            'bookings_active': 0,
            'bookings_cancelled': 0,
            'minutes_active': 0,
            'minutes_cancelled': 0,
            'weekday_minutes': [0] * 7,
        })
    weekday_active = [0] * 7
    weekday_minutes = [0] * 7
    hour_active = [0] * len(HOUR_BUCKETS)
    hour_minutes = [0] * len(HOUR_BUCKETS)
    cancel_weekday = [0] * 7
    cancel_room = [0] * len(rooms)
    per_day = {}
    total_created = total_active = total_cancelled = 0
    active_minutes = cancelled_minutes = 0

    for row in store.list_bookings(include_cancelled=True):
        if not isinstance(row, dict):
            continue
        try:
            day = validate_date(row.get('date'))
            start_min = parse_time(row.get('start'), 'start')
            end_min = parse_time(row.get('end'), 'end')
        except (BookingError, TypeError):
            continue          # malformed legacy row: skip, never raise
        if day < start or day > end or end_min <= start_min:
            continue
        status = row.get('status')
        if status not in (STATUS_ACTIVE, STATUS_CANCELLED):
            continue
        duration = end_min - start_min
        weekday = _weekday_index(day)
        index = room_pos.get(row.get('room_id'))
        total_created += 1
        if index is not None:
            per_room[index]['bookings_created'] += 1
        if status == STATUS_CANCELLED:
            total_cancelled += 1
            cancelled_minutes += duration
            cancel_weekday[weekday] += 1
            if index is not None:
                per_room[index]['bookings_cancelled'] += 1
                per_room[index]['minutes_cancelled'] += duration
                cancel_room[index] += 1
            continue
        total_active += 1
        active_minutes += duration
        weekday_active[weekday] += 1
        weekday_minutes[weekday] += duration
        if index is not None:
            per_room[index]['bookings_active'] += 1
            per_room[index]['minutes_active'] += duration
            per_room[index]['weekday_minutes'][weekday] += duration
        day_bucket = per_day.setdefault(day, {'bookings_active': 0, 'minutes': 0})
        day_bucket['bookings_active'] += 1
        day_bucket['minutes'] += duration
        for clock_hour, minutes in _hour_parts(row.get('start'), row.get('end')):
            slot = clock_hour - HOUR_BUCKETS[0]
            if 0 <= slot < len(HOUR_BUCKETS):
                hour_active[slot] += 1
                hour_minutes[slot] += minutes

    capacity_minutes = len(rooms) * days * DAY_CAPACITY_MINUTES
    room_rows = []
    for index, room in enumerate(rooms):
        data = per_room[index]
        room_capacity = days * DAY_CAPACITY_MINUTES
        busiest = ''
        best = 0
        for slot, minutes in enumerate(data['weekday_minutes']):
            if minutes > best:
                best = minutes
                busiest = WEEKDAY_LABELS[slot]
        room_rows.append({
            'id': room['id'],
            'name': room['name'],
            'capacity': room['capacity'],
            'location': room['location'],
            'bookings_created': data['bookings_created'],
            'bookings_active': data['bookings_active'],
            'bookings_cancelled': data['bookings_cancelled'],
            'hours_active': _hours(data['minutes_active']),
            'hours_cancelled': _hours(data['minutes_cancelled']),
            'utilisation_pct': _pct(data['minutes_active'], room_capacity),
            'busiest_weekday': busiest,
        })
    room_rows.sort(key=lambda item: (-item['hours_active'], item['name']))

    top_days = []
    for day, info in per_day.items():
        if info['bookings_active']:
            top_days.append({'date': day,
                             'bookings_active': info['bookings_active'],
                             'hours_active': _hours(info['minutes'])})
    top_days.sort(key=lambda item: (-item['hours_active'], item['date']))

    cancel_by_room = []
    for index, count in enumerate(cancel_room):
        if count:
            cancel_by_room.append({'room_id': rooms[index]['id'],
                                   'name': rooms[index]['name'],
                                   'count': count})
    cancel_by_room.sort(key=lambda item: (-item['count'], item['name']))

    return {
        'range': {'start': start, 'end': end, 'days': days},
        'totals': {
            'bookings_created': total_created,
            'bookings_active': total_active,
            'bookings_cancelled': total_cancelled,
            'hours_active': _hours(active_minutes),
            'hours_cancelled': _hours(cancelled_minutes),
            'utilisation_pct': _pct(active_minutes, capacity_minutes),
            'cancellation_rate_pct': _pct(total_cancelled, total_active + total_cancelled),
        },
        'rooms': room_rows,
        'by_weekday': [{'weekday': slot, 'label': WEEKDAY_LABELS[slot],
                        'bookings_active': weekday_active[slot],
                        'hours_active': _hours(weekday_minutes[slot])}
                       for slot in range(7)],
        'by_hour': [{'hour': clock_hour, 'label': '%02d:00' % clock_hour,
                     'bookings_active': hour_active[index],
                     'hours_active': _hours(hour_minutes[index])}
                    for index, clock_hour in enumerate(HOUR_BUCKETS)],
        'top_days': top_days[:5],
        'cancellations': {
            'count': total_cancelled,
            'rate_pct': _pct(total_cancelled, total_active + total_cancelled),
            'by_room': cancel_by_room,
            'by_weekday': [{'weekday': slot, 'label': WEEKDAY_LABELS[slot],
                            'count': cancel_weekday[slot]} for slot in range(7)],
        },
    }
