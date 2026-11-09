"""Festival dates (optional "festivals" pack).

Data: config/festivals.json, a list of {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "name": "..."}
(see packs/festivals_*.example.json). Lunar dates vary by a day by tradition; confirm locally.
Shown in the weekly digest ("Festivals, next 30 days") and on the dashboard. Empty when the pack is off.
"""
import datetime as dt

import config


def _load():
    if not config.pack("festivals"):
        return []
    out = []
    for r in (config.data_file("festivals.json") or []):
        try:
            out.append((dt.date.fromisoformat(r["start"]), dt.date.fromisoformat(r.get("end") or r["start"]), r["name"]))
        except (KeyError, ValueError, TypeError):
            continue
    return sorted(out)


FESTIVALS = _load()


def upcoming(today, days=30):
    """[(start, end, name)] overlapping today..today+days."""
    end = today + dt.timedelta(days=days)
    return [f for f in FESTIVALS if f[1] >= today and f[0] <= end]
