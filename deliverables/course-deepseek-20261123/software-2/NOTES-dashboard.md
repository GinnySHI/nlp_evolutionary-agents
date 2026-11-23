# Meeting-room analytics dashboard — run notes

Files (all flat, next to each other):
  booking.py     core booking logic + compute_stats / BookingStore.stats
  server.py      HTTP server: booking UI, JSON API, analytics API
  index.html     booking page (header links to the dashboard)
  dashboard.html manager analytics dashboard
  selftest.py    plain-assert test suite

Start the app:
  python3 server.py --port 8080
Then open:
  http://localhost:8080/            booking page
  http://localhost:8080/dashboard   analytics dashboard

Endpoints added for the dashboard:
  GET /api/stats?start=YYYY-MM-DD&end=YYYY-MM-DD
      200 JSON stats; 400 {error:'bad_request'} when a param is missing,
      400 {error:'bad_date'} for an unparsable date, 400 {error:'bad_range'}
      when start > end.
  GET /dashboard and /dashboard.html serve dashboard.html from disk.

Assumptions used by the numbers: date range is inclusive; capacity is
rooms x calendar days x 13h (07:00-20:00); bookings are counted on their
booking date; cancelled bookings only count towards cancelled/cancelled
hours; all calendar days including weekends are in the capacity.
