"""Work hours for adults who bill their time (self-employed, consultants, contractors): profile, hybrid schedule,
work calendar, timesheet import and monthly billing. Tables: contracts (+ migration 031 columns), work_hours,
work_calendar, work_invoices.

  python data/work.py list
  python data/work.py add --client C [--vendor V] [--no N] [--person P] [--start D] [--end D] [--rate R]
  python data/work.py profile CONTRACT [--invoice weekly|biweekly|semimonthly|monthly] [--cycle weekly|biweekly]
                                       [--anchor D] [--hours-per-day H] [--schedule HOOOH--HOOOH--] [--calendar NAME]
                                       [--rate R] [--start D] [--end D] [--vendor V] [--person P]
  python data/work.py schedule CONTRACT [--from D] [--days N]      the plan: on site / off site / off, holidays
  python data/work.py import FILE --contract CONTRACT [--dates mdy|dmy] [--dry-run]     timesheet (PDF with text, CSV, TXT)
  python data/work.py hours CONTRACT DATE HOURS [--loc onsite|offsite]
  python data/work.py fill CONTRACT --from D --to D                 enter the planned hours on days that have none
  python data/work.py month CONTRACT YYYY-MM                         hours, amount, weeks, warnings
  python data/work.py invoice make CONTRACT (--month YYYY-MM | --from D --to D)
  python data/work.py invoice sent|paid ID [--on D]
  python data/work.py invoice list [CONTRACT]
  python data/work.py calendar import FILE --name NAME [--year Y] [--dry-run]    holidays / pay days from a PDF or text
  python data/work.py calendar add NAME DATE --kind holiday|floating|payday|closure [--title T]
  python data/work.py calendar paydays NAME --from D --to D (--every N | --monthly DAY | --semimonthly)
  python data/work.py calendar list NAME [--year Y]
  python data/work.py offsite YEAR                                   days on site / off site per contract (home-office record)

CONTRACT is the id, the contract number or a unique part of the client name.
Schedule: one letter per day of the timesheet cycle, starting on --anchor: O on site, H home / off site, W working (place
not set), - not working. A 14-letter schedule repeats every two weeks. Without one: Monday-Friday working.
Timesheets: only the date, the hours and on/off site are kept. Names, supervisors, IDs and times of day are not read
into the database. A timesheet that is a picture (no text layer) cannot be read here: print the page with the browser's
"Save as PDF" (keeps the text), export CSV, or type the hours on the dashboard grid (prefilled from the schedule).
Records only; nothing is sent to a client. Library functions raise ValueError on bad input; the dashboard goes through
data/edit_actions.py.
"""
import argparse
import calendar as _cal
import collections
import csv
import datetime as dt
import io
import pathlib
import re
import shutil
import sqlite3
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import dates  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402
import money as _money  # noqa: E402
import validators as v  # noqa: E402

DB = paths.DB
ROOT = HERE.parent
INVOICE_FREQS = ["weekly", "biweekly", "semimonthly", "monthly"]
CYCLES = {"weekly": 7, "biweekly": 14}
PLAN = {"O": "on site", "H": "off site", "W": "working", "-": "off"}
CAL_KINDS = ["holiday", "floating", "payday", "closure"]
DEFAULT_ANCHOR = dt.date(2024, 1, 1)  # a Monday
HOURS_LABELS = ["time worked", "hours worked", "regular hours", "total hours", "billable hours", "hours", "total time",
                "worked", "total"]
MONTHS = {m.lower(): i for i, m in enumerate(_cal.month_abbr) if m}
MONTHS["sept"] = 9
UNPAID_DAYS = 30


def _today():
    return dates.today()


def _d(s):
    try:
        return dt.date.fromisoformat(str(s)[:10]) if s else None
    except ValueError:
        return None


def _clean(validator, value, label):
    try:
        return validator(value)
    except (ValueError, TypeError) as e:
        raise ValueError(f"{label}: {e}") from None


def _opt(validator, value, label):
    return None if value is None or str(value).strip() == "" else _clean(validator, value, label)


def _rows(con, sql, params=()):
    """Dict rows without changing the caller's connection (row_factory is set on this cursor only)."""
    cur = con.cursor()
    cur.row_factory = sqlite3.Row
    return [dict(r) for r in cur.execute(sql, params)]


# ---------------------------------------------------------------- contracts and profile
def contracts(con, active=True):
    return _rows(con, "SELECT * FROM contracts" + (" WHERE status='active'" if active else "") + " ORDER BY client, id")


def get(con, key):
    """A contract by id, contract number or a unique part of the client name. ValueError when none or several match."""
    s = str(key or "").strip()
    if not s:
        raise ValueError("which contract? give the id, contract number or client")
    if s.isdigit():
        r = _rows(con, "SELECT * FROM contracts WHERE id=?", (int(s),))
        if r:
            return r[0]
    r = _rows(con, "SELECT * FROM contracts WHERE contract_no=?", (s,))
    if len(r) == 1:
        return r[0]
    r = _rows(con, "SELECT * FROM contracts WHERE LOWER(client) LIKE ? ORDER BY status='active' DESC", (f"%{s.lower()}%",))
    act = [x for x in r if x["status"] == "active"]
    if len(act) == 1 or len(r) == 1:
        return (act or r)[0]
    raise ValueError(f"no contract matches '{s}'" if not r else f"'{s}' matches {len(r)} contracts; use the id")


KINDS = ("employment", "contract", "business", "rental", "side")
KIND_LABEL = {"employment": "Employment", "contract": "Contract", "business": "Own business (LLC, S-corp, sole prop)",
              "rental": "Rental", "side": "Side business"}
RANKS = ("primary", "secondary")


def get_by_id(con, cid):
    """A job by its id only (the web pages): a stale or wrong id never falls back to a number or a name."""
    r = _rows(con, "SELECT * FROM contracts WHERE id=?", (int(cid),))
    if not r:
        raise ValueError("no such job")
    return r[0]


def add_contract(con, client, vendor=None, contract_no=None, person=None, start=None, end=None, rate=None, kind="employment",
                 rank="primary", needs_timesheets=False):
    """One job or business. `rate` is kept for the command line only; the web app no longer asks for it."""
    client = _clean(v.text(80), client, "client")
    kind = _clean(v.one_of(KINDS), kind or "employment", "kind")
    rank = _clean(v.one_of(RANKS), rank or "primary", "primary or secondary")
    vendor = _opt(v.text(80), vendor, "vendor")
    contract_no = _opt(v.text(40), contract_no, "contract number")
    person = _opt(v.text(60), person, "who")
    start = _opt(v.iso_date, start, "start date")
    end = _opt(v.iso_date, end, "end date")
    rate = _opt(v.money(0, 1e5), rate, "hourly rate")
    if start and end and end < start:
        raise ValueError("end date is before the start date")
    cur = con.execute("INSERT INTO contracts(person, client, vendor, contract_no, start_date, end_date, hourly_rate, status, kind, "
                      "rank, needs_timesheets) VALUES (?,?,?,?,?,?,?, 'active', ?,?,?)",
                      (person, client, vendor, contract_no, start, end, rate, kind, rank, 1 if needs_timesheets else 0))
    return cur.lastrowid


def check_schedule(s, cycle_days=None):
    s = str(s or "").strip().upper().replace(" ", "")
    if not s:
        return None
    if len(s) not in (7, 14) or any(ch not in PLAN for ch in s):
        raise ValueError("schedule: 7 or 14 letters, each O (on site), H (off site), W (working) or - (off)")
    if cycle_days and len(s) not in (7, cycle_days):
        raise ValueError(f"schedule: {len(s)} letters but the timesheet cycle is {cycle_days} days")
    return s


def set_profile(con, cid, **f):
    """f: invoice_freq, timesheet_cycle, cycle_anchor, hours_per_day, schedule, work_calendar, hourly_rate, start_date,
    end_date, vendor, person, client, contract_no, status. None = unchanged, "" = clear."""
    c = get_by_id(con, cid) if isinstance(cid, int) else get(con, cid)
    clean = {}
    rules = {"invoice_freq": v.one_of(INVOICE_FREQS), "timesheet_cycle": v.one_of(list(CYCLES)),
             "cycle_anchor": v.iso_date, "period_start": v.iso_date, "period_end": v.iso_date, "hours_per_day": v.num(0.25, 24), "work_calendar": v.text(60),
             "hourly_rate": v.money(0, 1e5), "start_date": v.iso_date, "end_date": v.iso_date, "vendor": v.text(80),
             "person": v.text(60), "client": v.text(80), "contract_no": v.text(40),
             "status": v.one_of(["active", "renewed", "ended"]), "kind": v.one_of(KINDS), "rank": v.one_of(RANKS),
             "needs_timesheets": v.one_of(("0", "1")), "show_on_calendar": v.one_of(("0", "1")),
             "visibility": v.one_of(("shared", "private"))}
    for k, val in f.items():
        if val is None:
            continue
        if k == "schedule":
            continue
        if k not in rules:
            raise ValueError(f"unknown field {k}")
        if str(val).strip() == "":
            if k in ("client", "status", "kind", "rank", "needs_timesheets", "show_on_calendar", "visibility"):
                raise ValueError(f"{k} cannot be empty")
            clean[k] = None
        else:
            clean[k] = _clean(rules[k], val, k.replace("_", " "))
    cycle = clean.get("timesheet_cycle", c.get("timesheet_cycle"))
    if f.get("schedule") is not None:
        clean["schedule"] = check_schedule(f["schedule"], CYCLES.get(cycle))
    elif "timesheet_cycle" in clean and c.get("schedule"):
        check_schedule(c["schedule"], CYCLES.get(cycle))
    s, e = clean.get("start_date", c.get("start_date")), clean.get("end_date", c.get("end_date"))
    if s and e and e < s:
        raise ValueError("end date is before the start date")
    if "period_start" in clean or "period_end" in clean:
        ps, pe = clean.get("period_start", c.get("period_start")), clean.get("period_end", c.get("period_end"))
        if bool(ps) != bool(pe):
            raise ValueError("pay period: give both its first and its last day, or neither")
        if ps and not 7 <= (_d(pe) - _d(ps)).days + 1 <= 31:
            raise ValueError("pay period: from 7 to 31 days (first day to last day)")
    if clean:
        con.execute(f"UPDATE contracts SET {', '.join(k + '=?' for k in clean)} WHERE id=?", (*clean.values(), c["id"]))
    return c["id"], sorted(clean)


# ---------------------------------------------------------------- schedule, calendar, periods
def _anchor(c):
    return _d(c.get("cycle_anchor")) or DEFAULT_ANCHOR


def schedule_of(c):
    s = (c.get("schedule") or "").strip().upper()
    if s and all(ch in PLAN for ch in s) and len(s) in (7, 14):
        return s
    a = _anchor(c)  # Monday-Friday working, counted from the anchor's weekday
    return "".join("W" if (a + dt.timedelta(days=i)).weekday() < 5 else "-" for i in range(7))


def plan_for(c, day):
    s = schedule_of(c)
    return s[(day - _anchor(c)).days % len(s)]


def calendar_days(con, name, d0, d1, kinds=None):
    if not name:
        return {}
    out = {}
    try:
        for day, kind, title in con.execute("SELECT day, kind, name FROM work_calendar WHERE calendar=? AND day BETWEEN ? AND ? "
                                            "ORDER BY day, kind", (name, d0.isoformat(), d1.isoformat())):
            if kinds is None or kind in kinds:
                out.setdefault(_d(day), []).append((kind, title))
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
    return out


def cycle_bounds(c, day):
    n = CYCLES.get(c.get("timesheet_cycle") or "", 7 if not c.get("schedule") else len(schedule_of(c)))
    k = (day - _anchor(c)).days // n
    s = _anchor(c) + dt.timedelta(days=k * n)
    return s, s + dt.timedelta(days=n - 1)


def pay_period(c, day):
    """The timesheet / pay period (first, last) that contains `day`: the job's own pay period when it has one
    (period_start .. period_end repeating), else the schedule cycle."""
    a, b = _d(c.get("period_start")), _d(c.get("period_end"))
    if a and b and b >= a:
        n = (b - a).days + 1
        s = a + dt.timedelta(days=((day - a).days // n) * n)
        return s, s + dt.timedelta(days=n - 1)
    return cycle_bounds(c, day)


def period_bounds(freq, anchor, day):
    """The invoice period that contains `day`."""
    if freq in (None, "", "monthly"):
        return day.replace(day=1), day.replace(day=_cal.monthrange(day.year, day.month)[1])
    if freq == "semimonthly":
        if day.day <= 15:
            return day.replace(day=1), day.replace(day=15)
        return day.replace(day=16), day.replace(day=_cal.monthrange(day.year, day.month)[1])
    n = 7 if freq == "weekly" else 14
    a = anchor or DEFAULT_ANCHOR
    k = (day - a).days // n
    s = a + dt.timedelta(days=k * n)
    return s, s + dt.timedelta(days=n - 1)


def _hours_rows(con, cid, d0, d1):
    return {_d(r["work_date"]): r for r in _rows(
        con, "SELECT * FROM work_hours WHERE contract_id=? AND work_date BETWEEN ? AND ?", (cid, d0.isoformat(), d1.isoformat()))}


def days(con, c, d0, d1):
    """One dict per day: date, plan letter, holiday (text or ''), payday, expected hours, recorded hours / location / source."""
    cal = calendar_days(con, c.get("work_calendar"), d0, d1)
    rec = _hours_rows(con, c["id"], d0, d1)
    hpd = c.get("hours_per_day") or 8
    out, day = [], d0
    while day <= d1:
        p = plan_for(c, day)
        kinds = cal.get(day, [])
        hol = "; ".join(t or k for k, t in kinds if k in ("holiday", "closure"))
        flo = "; ".join(t or k for k, t in kinds if k == "floating")
        r = rec.get(day)
        out.append({"date": day, "plan": p, "holiday": hol, "floating": flo,
                    "payday": any(k == "payday" for k, _ in kinds),
                    "expected": 0.0 if (p == "-" or hol) else float(hpd),
                    "hours": r["hours"] if r else None, "location": r["location"] if r else None,
                    "source": r["source"] if r else None})
        day += dt.timedelta(days=1)
    return out


def _loc_for(plan):
    return {"O": "onsite", "H": "offsite"}.get(plan)


def set_hours(con, cid, day, hours, location=None, source="manual", document_id=None):
    day = _clean(v.iso_date, day, "date")
    hours = _clean(v.num(0, 24), hours, "hours")
    location = _opt(v.one_of(["onsite", "offsite"]), location, "on/off site")
    if source not in ("timesheet", "manual", "schedule"):
        raise ValueError("bad source")
    con.execute("INSERT INTO work_hours(contract_id, work_date, hours, location, source, document_id, updated_at) "
                "VALUES (?,?,?,?,?,?,?) ON CONFLICT(contract_id, work_date) DO UPDATE SET hours=excluded.hours, "
                "location=COALESCE(excluded.location, work_hours.location), source=excluded.source, "
                "document_id=COALESCE(excluded.document_id, work_hours.document_id), updated_at=excluded.updated_at",
                (cid, day, round(hours, 2), location, source, document_id, dt.datetime.now().isoformat(timespec="seconds")))


def fill(con, c, d0, d1):
    """Enter the planned hours (schedule minus holidays) on days that have no row yet. Returns days written."""
    n = 0
    for r in days(con, c, d0, d1):
        if r["hours"] is None and r["expected"] > 0:
            set_hours(con, c["id"], r["date"].isoformat(), r["expected"], _loc_for(r["plan"]), "schedule")
            n += 1
    return n


# ---------------------------------------------------------------- month summary and invoices
def summary(con, c, d0, d1, today=None):
    today = today or _today()
    rows = days(con, c, d0, d1)
    hours = round(sum(r["hours"] or 0 for r in rows), 2)
    rate = c.get("hourly_rate")
    on = sum(1 for r in rows if (r["hours"] or 0) > 0 and (r["location"] or _loc_for(r["plan"])) == "onsite")
    off = sum(1 for r in rows if (r["hours"] or 0) > 0 and (r["location"] or _loc_for(r["plan"])) == "offsite")
    weeks = collections.OrderedDict()
    for r in rows:
        ws = r["date"] - dt.timedelta(days=r["date"].weekday())
        weeks.setdefault(ws, 0.0)
        weeks[ws] += r["hours"] or 0
    warn = []
    missing = [r["date"] for r in rows if r["expected"] > 0 and r["hours"] is None and r["date"] < today]
    if missing:
        warn.append(f"{len(missing)} scheduled day(s) with no hours entered: " + ", ".join(f"{d:%m/%d}" for d in missing[:10])
                    + (" ..." if len(missing) > 10 else ""))
    zero = [r["date"] for r in rows if r["expected"] > 0 and r["hours"] == 0]
    if zero:
        warn.append(f"{len(zero)} scheduled day(s) with 0 hours (time off?): " + ", ".join(f"{d:%m/%d}" for d in zero[:10]))
    hol = [r["date"] for r in rows if r["holiday"] and (r["hours"] or 0) > 0]
    if hol:
        warn.append("hours on a holiday: " + ", ".join(f"{d:%m/%d}" for d in hol))
    over = [r["date"] for r in rows if (r["hours"] or 0) > 12]
    if over:
        warn.append("more than 12 hours on: " + ", ".join(f"{d:%m/%d}" for d in over))
    return {"contract": c, "start": d0, "end": d1, "hours": hours, "rate": rate,
            "amount": _money.round2(hours * rate) if rate else None, "days_worked": sum(1 for r in rows if (r["hours"] or 0) > 0),
            "onsite": on, "offsite": off, "weeks": [(ws, max(ws, d0), min(ws + dt.timedelta(days=6), d1), round(h, 2))
                                                    for ws, h in weeks.items()],
            "expected": round(sum(r["expected"] for r in rows), 2), "warnings": warn, "rows": rows,
            "paydays": [r["date"] for r in rows if r["payday"]]}


def month_bounds(ym):
    m = re.match(r"^(\d{4})-(\d{2})$", str(ym or ""))
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise ValueError("month must be YYYY-MM")
    y, mo = int(m.group(1)), int(m.group(2))
    return dt.date(y, mo, 1), dt.date(y, mo, _cal.monthrange(y, mo)[1])


def invoice_make(con, c, d0, d1, today=None):
    """Record (or refresh a draft) invoice for the period: hours x rate. Returns (invoice_id, summary)."""
    if d1 < d0:
        raise ValueError("the period ends before it starts")
    s = summary(con, c, d0, d1, today)
    r = con.execute("SELECT id, status FROM work_invoices WHERE contract_id=? AND period_start=? AND period_end=?",
                    (c["id"], d0.isoformat(), d1.isoformat())).fetchone()
    if r and r[1] != "draft":
        raise ValueError(f"invoice {r[0]} for this period is already {r[1]}")
    if r:
        con.execute("UPDATE work_invoices SET hours=?, rate=?, amount=? WHERE id=?", (s["hours"], s["rate"], s["amount"], r[0]))
        return r[0], s
    cur = con.execute("INSERT INTO work_invoices(contract_id, period_start, period_end, hours, rate, amount, status, created_at) "
                      "VALUES (?,?,?,?,?,?, 'draft', ?)", (c["id"], d0.isoformat(), d1.isoformat(), s["hours"], s["rate"],
                                                           s["amount"], dt.datetime.now().isoformat(timespec="seconds")))
    return cur.lastrowid, s


def invoice_set(con, inv_id, status, on=None):
    status = _clean(v.one_of(["draft", "sent", "paid"]), status, "status")
    on = _opt(v.iso_date, on, "date") or _today().isoformat()
    r = con.execute("SELECT status, sent_on FROM work_invoices WHERE id=?", (int(inv_id),)).fetchone()
    if not r:
        raise ValueError(f"no invoice {inv_id}")
    if status == "sent":
        con.execute("UPDATE work_invoices SET status='sent', sent_on=?, paid_on=NULL WHERE id=?", (on, int(inv_id)))
    elif status == "paid":
        con.execute("UPDATE work_invoices SET status='paid', paid_on=?, sent_on=COALESCE(sent_on, ?) WHERE id=?",
                    (on, on, int(inv_id)))
    else:
        con.execute("UPDATE work_invoices SET status='draft', sent_on=NULL, paid_on=NULL WHERE id=?", (int(inv_id),))
    return int(inv_id)


def invoices(con, cid=None):
    sql = ("SELECT i.*, c.client, c.contract_no FROM work_invoices i JOIN contracts c ON c.id=i.contract_id"
           + (" WHERE i.contract_id=?" if cid else "") + " ORDER BY i.period_start DESC")
    return _rows(con, sql, (cid,) if cid else ())


def alerts(con, today):
    """A timesheet to send: the last finished timesheet period of a job that needs timesheets has no timesheet imported
    yet (days with hours from a timesheet) although it had days to work. One row per job, from the day the period ended,
    until the next period ends. A private job's row does not name the job. No money here: nothing about pay or invoices."""
    if not config.pack("contracts"):
        return []
    out = []
    try:
        for c in contracts(con):
            if not c.get("needs_timesheets"):
                continue
            cur0, _ = pay_period(c, today)
            p0, p1 = pay_period(c, cur0 - dt.timedelta(days=1))
            start, end = _d(c.get("start_date")), _d(c.get("end_date"))
            if (start and p1 < start) or (end and p0 > end):
                continue
            rows = days(con, c, max(p0, start or p0), min(p1, end or p1))
            if not any(r["expected"] > 0 and r["plan"] in ("O", "H", "W") for r in rows):
                continue  # a period with nothing to work (leave, holidays) needs no timesheet
            if any(r["source"] == "timesheet" for r in rows):
                continue
            who = f" ({c['person']})" if c.get("person") else ""
            name = "a timesheet" if c.get("visibility") == "private" else f"the {c['client']} timesheet"
            out.append({"date": p1 + dt.timedelta(days=1), "kind": "Work", "title": f"Send {name}: {p0:%b %d} - {p1:%b %d}{who}",
                        "detail": "No timesheet has been imported for this period yet. Upload it in Family > Work > Timesheets "
                                  "or drop it in the inbox.",
                        "amount": None, "ref": ("contracts", c["id"])})
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
    return out


PAPER_KINDS = {"offer_letter": "Offer letter", "contract": "Contract", "w2": "W-2", "form_1099": "1099", "timesheet": "Timesheet",
               "benefits": "Benefits", "other": "Other"}
PAPER_TYPE = {"w2": "tax", "form_1099": "tax", "timesheet": "timesheet"}  # documents.doc_type of an uploaded paper (else other)


def papers(con, cid):
    """[{document, kind, label, date, vendor, name}] kept with the job, newest first."""
    out = []
    for r in con.execute("SELECT p.document_id, p.kind, d.doc_date, d.vendor, d.filed_path FROM work_papers p "
                         "JOIN documents d ON d.id=p.document_id WHERE p.contract_id=? ORDER BY d.doc_date DESC, p.id DESC", (int(cid),)):
        out.append({"document": r[0], "kind": r[1], "label": PAPER_KINDS.get(r[1], r[1]), "date": r[2] or "", "vendor": r[3] or "",
                    "name": pathlib.PurePath(str(r[4])).name})
    return out


def paper_choices(con, cid, limit=60):
    """Filed papers that could be attached: recent tax / other / manual / timesheet papers not kept with this job yet."""
    return [{"document": r[0], "label": f"{r[1] or 'undated'} · {r[2] or 'paper'} ({r[3]})"} for r in con.execute(
        "SELECT id, doc_date, vendor, doc_type FROM documents WHERE doc_type IN ('tax','other','manual','timesheet') "
        "AND id NOT IN (SELECT document_id FROM work_papers WHERE contract_id=?) ORDER BY doc_date DESC, id DESC LIMIT ?",
        (int(cid), limit))]


def paper_add(con, cid, document_id, kind):
    c = get_by_id(con, cid)
    kind = _clean(v.one_of(tuple(PAPER_KINDS)), kind, "kind of paper")
    if not con.execute("SELECT 1 FROM documents WHERE id=?", (int(document_id),)).fetchone():
        raise ValueError("no such paper")
    con.execute("INSERT INTO work_papers(contract_id, document_id, kind, added_at) VALUES (?,?,?,?) "
                "ON CONFLICT(contract_id, document_id) DO UPDATE SET kind=excluded.kind",
                (c["id"], int(document_id), kind, dt.datetime.now().isoformat(timespec="seconds")))
    return c["client"]


def paper_remove(con, cid, document_id):
    """Unlink only: the filed paper stays in the archive."""
    n = con.execute("DELETE FROM work_papers WHERE contract_id=? AND document_id=?", (int(cid), int(document_id))).rowcount
    if not n:
        raise ValueError("that paper is not kept with this job")


def file_paper(con, path, cid, kind, day=None):
    """File an uploaded paper under archive/ (no AI: type from the kind, vendor = the job's name, date today unless given) and keep
    it with the job. Does not commit. Returns the job's name."""
    import ai_intake
    c = get_by_id(con, cid)
    kind = _clean(v.one_of(tuple(PAPER_KINDS)), kind, "kind of paper")
    day = day or dates.today().isoformat()
    vendor = c["client"] if kind == "other" else f"{c['client']} {PAPER_KINDS[kind]}"  # the filed name says which paper it is
    doc, _dest = ai_intake.file_document(con, pathlib.Path(path), PAPER_TYPE.get(kind, "other"), vendor, day,
                                         note=f"{PAPER_KINDS[kind].lower()} kept with the job {c['client']}")
    paper_add(con, c["id"], doc, kind)
    return c["client"]


def overloaded(con, contract_id, days_):
    """[date, ...] among `days_` on which the person of this job has more than 24 hours recorded across all their jobs."""
    c = get_by_id(con, contract_id)
    if not c.get("person"):
        return []
    out = []
    for d in sorted({str(x) for x in days_}):
        total = con.execute("SELECT COALESCE(SUM(h.hours), 0) FROM work_hours h JOIN contracts c ON c.id=h.contract_id "
                            "WHERE c.person=? AND h.work_date=?", (c["person"], d)).fetchone()[0]
        if total > 24:
            out.append(d)
    return out


def overload_note(con, contract_id, days_):
    bad = overloaded(con, contract_id, days_)
    if not bad:
        return ""
    c = get_by_id(con, contract_id)
    shown = ", ".join(bad[:3]) + (f" and {len(bad) - 3} more" if len(bad) > 3 else "")
    return f" Check: {c['person']} has more than 24 hours across jobs on {shown}."


def offsite_days(con, year):
    out = []
    for c in contracts(con, active=False):
        s = summary(con, c, dt.date(year, 1, 1), dt.date(year, 12, 31), dt.date(year + 1, 1, 1))
        if s["days_worked"]:
            out.append({"contract": c, "onsite": s["onsite"], "offsite": s["offsite"], "days": s["days_worked"], "hours": s["hours"]})
    return out


# ---------------------------------------------------------------- reading files
def read_text(path):
    """(text, status) with the page layout kept (columns line up). status: ok | scanned | unsupported | error."""
    p = pathlib.Path(path)
    ext = p.suffix.lower()
    try:
        if ext in (".csv", ".txt", ".tsv"):
            return p.read_text(encoding="utf-8-sig", errors="replace"), "ok"
        if ext != ".pdf":
            return "", "unsupported"
        text = ""
        if shutil.which("pdftotext"):
            r = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(p), "-"], capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            text = (r.stdout or "") if r.returncode == 0 else ""
        if not text.strip():
            from pypdf import PdfReader
            parts = []
            for pg in PdfReader(str(p)).pages:
                try:
                    parts.append(pg.extract_text(extraction_mode="layout") or "")
                except Exception:  # noqa: BLE001 (a page with no text objects, e.g. a scan)
                    parts.append("")
            text = "\n".join(parts)
        return text, ("ok" if len(text.strip()) >= 40 else "scanned")
    except Exception:  # noqa: BLE001 (a broken file must not stop the caller)
        return "", "error"


DATE_TOK = re.compile(r"(?<![\d/.-])(\d{1,2})/(\d{1,2})(?:/(\d{4}|\d{2}))?(?![\d/])|(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
NUM_TOK = re.compile(r"(?<![\w:/.,$-])(\d{1,2}(?:\.\d{1,2})?|\d{1,2}:\d{2})(?![\w:/.%])(?!\s*[AaPp]\.?[Mm]\b)")


def _tok_date(m, order, ref):
    """A date from a DATE_TOK match. Without a year: the year that puts it closest to `ref`."""
    if m.group(4):
        try:
            return dt.date(int(m.group(4)), int(m.group(5)), int(m.group(6)))
        except ValueError:
            return None
    a, b, y = int(m.group(1)), int(m.group(2)), m.group(3)
    mo, da = (b, a) if order == "dmy" else (a, b)
    if y:
        y = int(y) + (2000 if len(y) == 2 else 0)
        try:
            return dt.date(y, mo, da)
        except ValueError:
            return None
    best = None
    for yy in (ref.year - 1, ref.year, ref.year + 1):
        try:
            d = dt.date(yy, mo, da)
        except ValueError:
            continue
        if best is None or abs((d - ref).days) < abs((best - ref).days):
            best = d
    return best


def _ref_dates(lines, order, year=None):
    """Per line: the nearest full date (with a year) at or before it, else the first one after, else Jul 1 of a year."""
    full = []
    for i, ln in enumerate(lines):
        for m in DATE_TOK.finditer(ln):
            if m.group(3) or m.group(4):
                d = _tok_date(m, order, _today())
                if d:
                    full.append((i, d))
    if year or not full:
        years = collections.Counter(int(y) for y in re.findall(r"\b(20\d\d)\b", "\n".join(lines)))
        mid = dt.date(year or (years.most_common(1)[0][0] if years else _today().year), 7, 1)
        return lambda i: mid

    def ref(i):
        before = [d for j, d in full if j <= i]
        return before[-1] if before else full[0][1]
    return ref


def _hours_value(s):
    if ":" in s:
        h, m = s.split(":")
        if not 0 <= int(m) < 60:
            raise ValueError(f"minutes must be below 60 ({s})")
        return int(h) + int(m) / 60
    return float(s)


def _label(line):
    m = re.match(r"^\s*([A-Za-z][A-Za-z ./&+()-]*?)\s*(?=\d|$)", line)
    return " ".join(m.group(1).lower().split()) if m else ""


def parse_grid(text, order="mdy", year=None):
    """Grid timesheets: a line of 3+ dates (one column per day), then rows of numbers per day. The hours row is the
    first match of HOURS_LABELS by priority ('Time Worked' before 'Total Time'). Returns [(date, hours)]."""
    lines = text.splitlines()
    ref = _ref_dates(lines, order, year)
    out, i = {}, 0
    while i < len(lines):
        toks = [m for m in DATE_TOK.finditer(lines[i])]
        if len(toks) < 3:
            i += 1
            continue
        r = ref(i)
        cols, prev = [], None
        for m in toks:
            d = _tok_date(m, order, r)
            if d and prev and d < prev - dt.timedelta(days=180):
                d = dt.date(d.year + 1, 3, 1) if (d.month, d.day) == (2, 29) else d.replace(year=d.year + 1)
            if d:
                cols.append(((m.start() + m.end()) / 2, d))
                prev = d
        j, best = i + 1, None
        while j < len(lines) and len(list(DATE_TOK.finditer(lines[j]))) < 3:
            lab = _label(lines[j])
            raw = re.match(r"^\s*[A-Za-z][A-Za-z ./&+()-]*", lines[j])
            has_nums = bool(raw and NUM_TOK.search(lines[j][raw.end():]))
            for rank, key in enumerate(HOURS_LABELS if has_nums else []):
                if lab == key or (lab.startswith(key) and len(lab) <= len(key) + 12):
                    if best is None or rank < best[0]:
                        best = (rank, j)
                    break
            j += 1
        if best is not None and cols:
            ln = lines[best[1]]
            lab_end = len(re.match(r"^\s*[A-Za-z][A-Za-z ./&+()-]*", ln).group(0))
            vals = [((m.start() + m.end()) / 2, _hours_value(m.group(1))) for m in NUM_TOK.finditer(ln) if m.start() >= lab_end]
            if len(vals) == len(cols):
                pairs = [(cols[k][1], vals[k][1]) for k in range(len(cols))]
            else:
                gap = min((cols[k + 1][0] - cols[k][0] for k in range(len(cols) - 1)), default=10)
                pairs = []
                for x, h in vals:
                    near = min(cols, key=lambda c: abs(c[0] - x))
                    if abs(near[0] - x) <= max(gap * 0.75, 3):
                        pairs.append((near[1], h))
            for d, h in pairs:
                if 0 <= h <= 24:
                    out[d] = h
        i = j
    return sorted(out.items())


def parse_list(text, order="mdy", year=None):
    """One day per line: a date near the start of the line and the hours as the last number on it."""
    lines = text.splitlines()
    ref = _ref_dates(lines, order, year)
    out = {}
    for i, ln in enumerate(lines):
        m = DATE_TOK.search(ln)
        if not m or m.start() > 15:
            continue
        d = _tok_date(m, order, ref(i))
        nums = [x for x in NUM_TOK.finditer(ln) if x.start() >= m.end()]
        if d and nums:
            h = _hours_value(nums[-1].group(1))
            if 0 <= h <= 24:
                out[d] = h
    return sorted(out.items())


def parse_csv(text, order="mdy"):
    import import_statement as ist
    rows = list(csv.reader(io.StringIO(text)))
    for hi, hdr in enumerate(rows[:15]):
        low = [h.strip().lower() for h in hdr]
        dcol = next((k for k, h in enumerate(low) if h in ("date", "day", "work date", "work_date") or h.endswith(" date")), None)
        hcol = None
        for key in HOURS_LABELS + ["duration", "qty", "quantity"]:
            hcol = next((k for k, h in enumerate(low) if h == key or h.startswith(key)), None)
            if hcol is not None:
                break
        if dcol is None or hcol is None:
            continue
        lcol = next((k for k, h in enumerate(low) if h in ("location", "on site", "onsite", "site", "place")), None)
        out = []
        for r in rows[hi + 1:]:
            if len(r) <= max(dcol, hcol):
                continue
            d = ist.parse_date(r[dcol], order)
            try:
                h = _hours_value(r[hcol].strip()) if r[hcol].strip() else None
            except ValueError:
                h = None
            if d and h is not None and 0 <= h <= 24:
                loc = None
                if lcol is not None and lcol < len(r):
                    t = r[lcol].strip().lower()
                    loc = ("offsite" if re.search(r"off[- ]?site|home|remote|wfh|telework", t) else
                           "onsite" if re.search(r"on[- ]?site|office|client|in person", t) else None)
                out.append((d, h, loc))
        return out
    return []


def parse_timesheet(path, order="mdy", year=None):
    """-> (rows [(date, hours, location|None)], how, status). how: grid | list | csv."""
    path = pathlib.Path(path)
    text, status = read_text(path)
    if status != "ok":
        return [], "", status
    if path.suffix.lower() in (".csv", ".tsv"):
        return parse_csv(text if path.suffix.lower() == ".csv" else text.replace("\t", ","), order), "csv", "ok"
    g = parse_grid(text, order, year)
    if g:
        return [(d, h, None) for d, h in g], "grid", "ok"
    lst = parse_list(text, order, year)
    return [(d, h, None) for d, h in lst], "list", "ok"


def import_timesheet(con, c, path, order="mdy", dry_run=False, document_id=None):
    """Read a timesheet and write one work_hours row per day (the timesheet wins over typed or planned hours).
    Location comes from the file when it says, else from the schedule. Returns a report dict."""
    path = pathlib.Path(path)
    rows, how, status = parse_timesheet(path, order)
    if status == "scanned":
        raise ValueError("this file is a picture (no text layer). Print the timesheet page with the browser's "
                         "'Save as PDF', export CSV, or type the hours on the dashboard grid")
    if status != "ok":
        raise ValueError(f"could not read the file ({status})")
    if not rows:
        raise ValueError("no dates with hours found (expected a row of dates and a 'Time Worked' / 'Hours' row, "
                         "or one 'date ... hours' line per day)")
    start, end = _d(c.get("start_date")), _d(c.get("end_date"))
    outside = {d for d, _, _ in rows if (start and d < start) or (end and d > end)}
    changed = 0
    written = []
    if not dry_run:
        old = _hours_rows(con, c["id"], min(d for d, _, _ in rows), max(d for d, _, _ in rows))
        for d, h, loc in rows:
            if d in outside:  # a day outside the job's dates is reported, never written
                continue
            loc = loc or (_loc_for(plan_for(c, d)) if h > 0 else None)
            prev = old.get(d)
            if not prev or abs(prev["hours"] - h) > 1e-9:
                changed += 1
            set_hours(con, c["id"], d.isoformat(), h, loc, "timesheet", document_id)
            written.append(d.isoformat())
    return {"how": how, "days": len(rows), "first": min(d for d, _, _ in rows), "last": max(d for d, _, _ in rows),
            "hours": round(sum(h for _, h, _ in rows), 2), "changed": changed, "outside_contract": sorted(outside), "rows": rows, "written": written}


# ---------------------------------------------------------------- work calendar
_MON = r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
CAL_NAMED = re.compile(_MON + r"\s+(\d{1,2})(?:st|nd|rd|th)?(?:,\s*(20\d\d))?\s+(?P<name>[A-Za-z][^\n]*?)(?=\s+" + _MON + r"\s+\d{1,2}\b|\s{3,}|$)")
CAL_NUM = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?(?![\d/])\s+(?P<name>[A-Za-z][^\n]*?)(?=\s+\d{1,2}/\d{1,2}|\s{3,}|$)"
                     r"|(?<!\d)(20\d\d)-(\d\d)-(\d\d)(?!\d)\s+(?P<name2>[A-Za-z][^\n]*?)(?=\s+20\d\d-|\s{3,}|$)")


def _kind(name, section):
    n = (name or "").lower()
    if re.search(r"pay ?day|pay date|payday", n) or (section == "payday" and not re.search(r"holiday", n)):
        return "payday"
    if re.search(r"\bfloat", n):
        return "floating"
    if re.search(r"closed|closure", n) or section == "closure":
        return "closure"
    return "holiday"


def parse_calendar(text, year=None):
    """Holidays, floating holidays, pay days and closures from a work calendar's text -> [(date, kind, name)].
    Lines like 'Jan 19  Martin Luther King Day', 'Feb 12 Lincoln's Birthday (Float)', '05/25/2026 Memorial Day',
    and under a 'Pay days' heading plain dates. The year: the one on the page most often, unless given."""
    years = collections.Counter(int(y) for y in re.findall(r"\b(20\d\d)\b", text))
    y0 = year or (years.most_common(1)[0][0] if years else _today().year)
    out, section = {}, "holiday"
    for ln in text.splitlines():
        low = ln.lower()
        hits = list(CAL_NAMED.finditer(ln)) + list(CAL_NUM.finditer(ln))
        if not hits:
            if re.search(r"pay ?(day|date)s?|payday|pay schedule|pay period", low):
                section = "payday"
            elif re.search(r"holiday", low):
                section = "holiday"
            elif re.search(r"closed|closure", low):
                section = "closure"
            if section == "payday":
                for m in DATE_TOK.finditer(ln):
                    d = _tok_date(m, "mdy", dt.date(y0, 7, 1))
                    if d:
                        out[(d, "payday")] = "Pay day"
            continue
        for m in hits:
            g = m.groups()
            try:
                if m.re is CAL_NAMED:
                    d = dt.date(int(g[2] or y0), MONTHS[g[0].lower()[:3]], int(g[1]))
                    name = m.group("name")
                elif m.group(5):
                    d = dt.date(int(m.group(5)), int(m.group(6)), int(m.group(7)))
                    name = m.group("name2")
                else:
                    yy = m.group(3)
                    yy = int(yy) + (2000 if yy and len(yy) == 2 else 0) if yy else y0
                    d = dt.date(yy, int(m.group(1)), int(m.group(2)))
                    name = m.group("name")
            except (ValueError, KeyError):
                continue
            name = " ".join(name.replace("\ufffd", "'").split())[:80]
            kind = _kind(name, section)
            clean = re.sub(r"\s*\((float(ing)?|observed)\)", lambda x: " (observed)" if "observed" in x.group(0).lower() else "",
                           name, flags=re.I).strip()
            out[(d, kind)] = clean or kind
    return sorted(((d, k, n) for (d, k), n in out.items()), key=lambda x: (x[0], x[1]))


def calendar_import(con, name, path, year=None, dry_run=False, document_id=None):
    name = _clean(v.text(60), name, "calendar name")
    text, status = read_text(path)
    if status == "scanned":
        raise ValueError("this calendar is a picture (no text layer); add the holidays with 'calendar add' or on the dashboard")
    if status != "ok":
        raise ValueError(f"could not read the file ({status})")
    rows = parse_calendar(text, year)
    if not rows:
        raise ValueError("no holidays or pay days found")
    if not dry_run:
        for d, kind, title in rows:
            calendar_add(con, name, d.isoformat(), kind, title, document_id)
    return rows


def calendar_add(con, name, day, kind, title=None, document_id=None):
    name = _clean(v.text(60), name, "calendar name")
    day = _clean(v.iso_date, day, "date")
    kind = _clean(v.one_of(CAL_KINDS), kind, "kind")
    title = _opt(v.text(80), title, "name")
    con.execute("INSERT INTO work_calendar(calendar, day, kind, name, document_id) VALUES (?,?,?,?,?) "
                "ON CONFLICT(calendar, day, kind) DO UPDATE SET name=COALESCE(excluded.name, work_calendar.name), "
                "document_id=COALESCE(excluded.document_id, work_calendar.document_id)", (name, day, kind, title, document_id))


def calendar_paydays(con, name, d0, d1, every=None, monthly=None, semimonthly=False):
    """Pay days by rule: every N days from d0, a day of each month (31 = last day), or the 15th and last day."""
    out, n = [], 0
    if every:
        every = _clean(v.integer(1, 62), every, "every")
        d = d0
        while d <= d1:
            out.append(d)
            d += dt.timedelta(days=every)
    else:
        if not monthly and not semimonthly:
            raise ValueError("give --every N, --monthly DAY or --semimonthly")
        y, m = d0.year, d0.month
        while dt.date(y, m, 1) <= d1:
            last = _cal.monthrange(y, m)[1]
            for dd in ([15, last] if semimonthly else [min(_clean(v.integer(1, 31), monthly, "day"), last)]):
                d = dt.date(y, m, dd)
                if d0 <= d <= d1:
                    out.append(d)
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    for d in out:
        calendar_add(con, name, d.isoformat(), "payday", "Pay day")
        n += 1
    return n


def calendar_names(con):
    try:
        return [r[0] for r in con.execute("SELECT DISTINCT calendar FROM work_calendar ORDER BY calendar")]
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
        return []


# ---------------------------------------------------------------- filing (inbox / dashboard uploads)
def file_and_import(con, path, kind, contract=None, calendar=None, year=None, order="mdy"):
    """Import a timesheet (kind='timesheet', needs `contract`) or a work calendar (kind='work_calendar', needs `calendar`)
    and, when the file is inside this project, file it under archive/<year>/work/. Does not commit. Returns a message."""
    import ai_intake
    path = pathlib.Path(path)
    inside = ROOT.resolve() in path.resolve().parents
    if kind == "timesheet":
        c = get_by_id(con, contract) if isinstance(contract, int) else get(con, contract)
        rep = import_timesheet(con, c, path, order, dry_run=True)  # check it reads before anything moves
        doc = None
        if inside:
            doc, path = ai_intake.file_document(con, path, "timesheet", c["client"], rep["last"].isoformat(),
                                                note=f"timesheet {rep['first']} to {rep['last']}")
        rep = import_timesheet(con, c, path, order, document_id=doc)
        if doc:
            paper_add(con, c["id"], doc, "timesheet")
        msg = f"{rep['days']} days, {rep['hours']} h ({rep['first']} to {rep['last']}), {rep['changed']} changed"
        if rep["outside_contract"]:
            msg += f"; {len(rep['outside_contract'])} day(s) are outside the job's dates and were not saved"
        return msg + overload_note(con, c["id"], rep["written"])
    if kind == "work_calendar":
        rows = calendar_import(con, calendar, path, year, dry_run=True)
        doc = None
        if inside:
            doc, dest = ai_intake.file_document(con, path, "work_calendar", calendar, rows[0][0].replace(month=1, day=1).isoformat())
            path = dest
        calendar_import(con, calendar, path, year, document_id=doc)
        k = collections.Counter(kind for _, kind, _ in rows)
        return f"{calendar}: " + ", ".join(f"{n} {kd}" for kd, n in sorted(k.items()))
    raise ValueError("kind must be timesheet or work_calendar")


# ---------------------------------------------------------------- command line
def _print_summary(s):
    c = s["contract"]
    print(f"{c['client']} ({c.get('contract_no') or c['id']})  {s['start']} to {s['end']}")
    rate = f" x {_money.fmt(s['rate'])}/h = {_money.fmt(s['amount'])}" if s["rate"] else " (no hourly rate set)"
    print(f"  hours {s['hours']}{rate}   days worked {s['days_worked']} (on site {s['onsite']}, off site {s['offsite']})"
          f"   planned {s['expected']} h")
    for ws, a, b, h in s["weeks"]:
        print(f"  week of {ws}: {a:%m/%d}-{b:%m/%d}  {h} h")
    if s["paydays"]:
        print("  pay days: " + ", ".join(f"{d:%m/%d}" for d in s["paydays"]))
    for w in s["warnings"]:
        print("  ! " + w)


def main(argv=None):
    ap = argparse.ArgumentParser(description="work hours, schedule, calendar and invoices")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p = sub.add_parser("add")
    p.add_argument("--client", required=True), p.add_argument("--vendor"), p.add_argument("--no"), p.add_argument("--person")
    p.add_argument("--start"), p.add_argument("--end"), p.add_argument("--rate")
    p = sub.add_parser("profile")
    p.add_argument("contract")
    for o in ("invoice", "cycle", "anchor", "hours-per-day", "schedule", "calendar", "rate", "start", "end", "vendor", "person",
              "status"):
        p.add_argument("--" + o)
    p = sub.add_parser("schedule")
    p.add_argument("contract"), p.add_argument("--from", dest="frm"), p.add_argument("--days", type=int)
    p = sub.add_parser("import")
    p.add_argument("file"), p.add_argument("--contract", required=True), p.add_argument("--dates", default="mdy", choices=["mdy", "dmy"])
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("hours")
    p.add_argument("contract"), p.add_argument("date"), p.add_argument("hours"), p.add_argument("--loc", choices=["onsite", "offsite"])
    p = sub.add_parser("fill")
    p.add_argument("contract"), p.add_argument("--from", dest="frm", required=True), p.add_argument("--to", required=True)
    p = sub.add_parser("month")
    p.add_argument("contract"), p.add_argument("month")
    p = sub.add_parser("invoice")
    p.add_argument("action", choices=["make", "sent", "paid", "draft", "list"]), p.add_argument("target", nargs="?")
    p.add_argument("--month"), p.add_argument("--from", dest="frm"), p.add_argument("--to"), p.add_argument("--on")
    p = sub.add_parser("calendar")
    p.add_argument("action", choices=["import", "add", "paydays", "list"]), p.add_argument("a", nargs="?"), p.add_argument("b", nargs="?")
    p.add_argument("--name"), p.add_argument("--year", type=int), p.add_argument("--dry-run", action="store_true")
    p.add_argument("--kind", default="holiday"), p.add_argument("--title"), p.add_argument("--from", dest="frm"), p.add_argument("--to")
    p.add_argument("--every", type=int), p.add_argument("--monthly", type=int), p.add_argument("--semimonthly", action="store_true")
    p = sub.add_parser("offsite")
    p.add_argument("year", type=int)
    a = ap.parse_args(argv)
    con = db.connect(DB)
    today = _today()
    try:
        with con:
            if a.cmd == "list":
                for c in contracts(con, active=False):
                    prof = " ".join(f"{k}={c.get(k)}" for k in ("invoice_freq", "timesheet_cycle", "cycle_anchor", "hours_per_day",
                                                                "schedule", "work_calendar") if c.get(k))
                    print(f"{c['id']}: {c['client']} via {c.get('vendor') or '-'}  #{c.get('contract_no') or '-'}  {c['status']}  "
                          f"{c.get('start_date') or '?'} -> {c.get('end_date') or '?'}  rate {c.get('hourly_rate') or '-'}  {prof}")
            elif a.cmd == "add":
                cid = add_contract(con, a.client, a.vendor, a.no, a.person, a.start, a.end, a.rate)
                print(f"added contract {cid}; next: python data/work.py profile {cid} --invoice monthly --cycle biweekly --anchor YYYY-MM-DD")
            elif a.cmd == "profile":
                m = {"invoice": "invoice_freq", "cycle": "timesheet_cycle", "anchor": "cycle_anchor", "hours_per_day": "hours_per_day",
                     "schedule": "schedule", "calendar": "work_calendar", "rate": "hourly_rate", "start": "start_date",
                     "end": "end_date", "vendor": "vendor", "person": "person", "status": "status"}
                cid, changed = set_profile(con, a.contract, **{m[k]: val for k, val in vars(a).items() if k in m})
                print(f"contract {cid}: " + (", ".join(changed) + " updated" if changed else "nothing to change"))
            elif a.cmd == "schedule":
                c = get(con, a.contract)
                s0 = _d(a.frm) or cycle_bounds(c, today)[0]
                n = a.days or CYCLES.get(c.get("timesheet_cycle") or "", len(schedule_of(c)))
                for r in days(con, c, s0, s0 + dt.timedelta(days=n - 1)):
                    extra = " ".join(x for x in (r["holiday"] and f"HOLIDAY {r['holiday']}", r["floating"] and f"floating: {r['floating']}",
                                                 r["payday"] and "pay day") if x)
                    got = "" if r["hours"] is None else f"  recorded {r['hours']} h {r['location'] or ''} ({r['source']})"
                    print(f"{r['date']} {r['date']:%a}  {PLAN[r['plan']]:<9} planned {r['expected']:g} h  {extra}{got}")
            elif a.cmd == "import":
                c = get(con, a.contract)
                rep = import_timesheet(con, c, pathlib.Path(a.file), a.dates, dry_run=a.dry_run)
                for d, h, loc in rep["rows"]:
                    print(f"  {d} {d:%a}  {h:g} h {loc or ''}")
                print(f"{'would import' if a.dry_run else 'imported'} {rep['days']} days ({rep['how']}), {rep['hours']} h, "
                      f"{rep['first']} to {rep['last']}" + ("" if a.dry_run else f", {rep['changed']} changed"))
                if rep["outside_contract"]:
                    print(f"  ! {len(rep['outside_contract'])} day(s) outside the contract dates")
            elif a.cmd == "hours":
                c = get(con, a.contract)
                set_hours(con, c["id"], a.date, a.hours, a.loc)
                print(f"{a.date}: {a.hours} h")
            elif a.cmd == "fill":
                c = get(con, a.contract)
                print(f"filled {fill(con, c, _d(_clean(v.iso_date, a.frm, 'from')), _d(_clean(v.iso_date, a.to, 'to')))} day(s) from the schedule")
            elif a.cmd == "month":
                c = get(con, a.contract)
                _print_summary(summary(con, c, *month_bounds(a.month), today))
            elif a.cmd == "invoice":
                if a.action == "list":
                    for i in invoices(con, get(con, a.target)["id"] if a.target else None):
                        print(f"{i['id']}: {i['client']} {i['period_start']} to {i['period_end']}  {i['hours']} h  "
                              f"{_money.fmt(i['amount']) if i['amount'] is not None else '-'}  {i['status']}"
                              f"{' sent ' + i['sent_on'] if i['sent_on'] else ''}{' paid ' + i['paid_on'] if i['paid_on'] else ''}")
                elif a.action == "make":
                    c = get(con, a.target)
                    d0, d1 = month_bounds(a.month) if a.month else (_d(a.frm), _d(a.to))
                    if not d0 or not d1:
                        raise ValueError("give --month YYYY-MM or --from D --to D")
                    iid, s = invoice_make(con, c, d0, d1, today)
                    _print_summary(s)
                    print(f"invoice {iid} recorded as draft (mark it with: invoice sent {iid})")
                else:
                    if not a.target:
                        raise ValueError("which invoice id?")
                    print(f"invoice {invoice_set(con, a.target, a.action, a.on)} marked {a.action}")
            elif a.cmd == "calendar":
                if a.action == "import":
                    name = a.name or a.b
                    if not a.a or not name:
                        raise ValueError("calendar import FILE --name NAME")
                    rows = calendar_import(con, name, pathlib.Path(a.a), a.year, a.dry_run)
                    for d, kind, title in rows:
                        print(f"  {d} {d:%a}  {kind:<8} {title}")
                    print(f"{'would add' if a.dry_run else 'added'} {len(rows)} day(s) to calendar '{name}'")
                elif a.action == "add":
                    calendar_add(con, a.a, a.b, a.kind, a.title)
                    print(f"{a.b} {a.kind} added to '{a.a}'")
                elif a.action == "paydays":
                    d0, d1 = _d(a.frm), _d(a.to)
                    if not a.a or not d0 or not d1:
                        raise ValueError("calendar paydays NAME --from D --to D (--every N | --monthly DAY | --semimonthly)")
                    print(f"{calendar_paydays(con, a.a, d0, d1, a.every, a.monthly, a.semimonthly)} pay day(s) added to '{a.a}'")
                else:
                    y = a.year or today.year
                    for d, kinds in sorted(calendar_days(con, a.a, dt.date(y, 1, 1), dt.date(y, 12, 31)).items()):
                        for kind, title in kinds:
                            print(f"  {d} {d:%a}  {kind:<8} {title or ''}")
            elif a.cmd == "offsite":
                for r in offsite_days(con, a.year):
                    print(f"{r['contract']['client']}: {r['days']} days worked, on site {r['onsite']}, off site {r['offsite']}, {r['hours']} h")
                print("Record only: whether home-office costs are deductible is for your tax preparer.")
    except ValueError as e:
        raise SystemExit(f"error: {e}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
