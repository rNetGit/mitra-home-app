"""The app (FastAPI + Jinja2 + HTMX), the only front end since 0.99.0.

    app.py        routes, security headers, sign-in, role checks
    sessions.py   in-memory sessions and CSRF tokens
    templates/    Jinja2 pages (autoescaped); static/ has the CSS, JS, PWA files and vendored ECharts/HTMX

Start it with `python data/web_app.py` (see that file for --port and --lan).
"""
