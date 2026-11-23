# Meeting Room Booking System v1.0.0

A small shared-calendar web app for booking meeting rooms. It replaces the
shared spreadsheet: everyone on the office network opens the same page, sees
which rooms are free, books a slot, and cancels when plans change — so no more
double bookings and no more records that stay booked after a cancellation.

## Requirements

- Python 3.8 or newer.
- Standard library only — nothing to install (`pip install` not needed).
- No internet connection needed. Works entirely on your local network.

Files that make up the system:

- `server.py` — the web server (start this).
- `booking.py` — core booking logic and data store.
- `index.html` — the web page you use in the browser.
- `selftest.py` — optional self-test of the booking logic.

## Quick start

1. Put `booking.py`, `server.py`, `index.html` and `selftest.py` in **one**
   folder on the machine that will host the calendar.
2. Start the server from that folder:

   ```
   python3 server.py
   ```

3. Open the address it prints. On the same machine:
   `http://localhost:8080` — colleagues on the LAN use the network URL that
   is printed at startup (e.g. `http://192.168.1.20:8080`).

Optional flags (defaults shown):

```
python3 server.py --port 8080 --data bookings.json --rooms rooms.json
```

`--rooms` is optional; if `rooms.json` is absent the built-in room list is
used (Atlas, Birch, Cedar, Delta, Everest).

## How to use it day to day

- **Pick a date** with the date picker (defaults to today) and optionally
  filter to one room.
- **Check availability** on the per-room timeline, 07:00–20:00. Free gaps are
  visible at a glance; booked blocks show the meeting title and organizer.
- **Book** by choosing room, date, start and end (15-minute steps), a meeting
  title and your name as organizer. Attendees and notes are optional.
- **Conflicts are refused.** If the slot overlaps an existing booking the
  booking is not saved and a message names the clashing booking (time,
  organizer, title) so you can pick another slot. Back-to-back meetings
  (e.g. 10:00–11:00 then 11:00–12:00) are allowed.
- **Cancel** with the cancel button on any active booking. You are asked to
  confirm and may give a reason. The slot becomes free immediately, and the
  booking stays in the list as a greyed-out, struck-through record (audit
  trail) behind the **show cancelled** toggle.

## Where the data lives

All bookings are stored in a single `bookings.json` file next to the server
(in the folder you started it from, unless you pass `--data`).

- To **back up**, copy that one file.
- Because there is one server, everyone shares one calendar — that is what
  prevents double bookings.
- Do not run two server processes against the same data file.

## Running the self-test

```
python3 selftest.py
```

It uses temporary files only, prints PASS/FAIL lines and a summary, and does
not touch your real `bookings.json`.

## Known limitations (v1)

- No login or passwords — anyone who can reach the server can book or cancel
  (intended for a trusted internal network).
- No recurring meetings; book each occurrence separately.
- No edit-in-place: cancel and rebook to change a booking.
- One server process per data file (no multi-server syncing).
