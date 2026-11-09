"""Validated edits for the web app: work profile, schedule, hours, calendar and invoices (split from edit_actions.py, audit A9).

See edit_core.py for the rules every edit follows; edit_actions.py re-exports everything, callers keep using it.
"""
import datetime as dt
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import validators as v  # noqa: E402
from edit_core import (  # noqa: E402
    EditError,
    _adult,
    _clean,
    _con,
    _log,
    _lv,
    edits,
)


# ---------------------------------------------------------------- work: profile, schedule, hours, calendar, invoices
def _work():
    import work
    return work


def _check_adult(con, person):
    """A job belongs to an adult: refuse a name that is a child or a pet of this family (unknown names pass, as before)."""
    p = str(person or "").strip()
    if not p:
        return
    r = con.execute("SELECT role FROM members WHERE name=?", (p,)).fetchone()
    if r and r[0] != "adult":
        raise EditError("who: a job belongs to an adult of the family")


def _d(s, label):
    return dt.date.fromisoformat(_clean(v.iso_date, s, label))


@edits
def work_contract_add(actor, client, vendor=None, contract_no=None, person=None, start=None, end=None, rate=None,
                      kind="employment", rank="primary", needs_timesheets=False):
    _adult(actor)
    with _con() as con:
        _check_adult(con, person)
        cid = _lv(_work().add_contract, con, client, vendor, contract_no, person, start, end, rate, kind, rank, needs_timesheets)
        _log(actor, "work_contract_add", f"id={cid} kind={kind}")
    return f"Added {client}. Set its schedule and details next."


@edits
def work_profile(actor, contract_id, **fields):
    """fields as work.set_profile (invoice_freq, timesheet_cycle, cycle_anchor, hours_per_day, schedule, work_calendar,
    hourly_rate, start_date, end_date, vendor, person, client, contract_no, status). None = unchanged, "" = clear."""
    _adult(actor)
    with _con() as con:
        _check_adult(con, fields.get("person"))
        cid, changed = _lv(_work().set_profile, con, int(contract_id), **fields)
        _log(actor, "work_profile", f"id={cid} fields={','.join(changed)}")
    return "Saved." if changed else "Nothing changed."


@edits
def work_hours_save(actor, contract_id, rows):
    """rows: [(date ISO, hours or None/'' to clear, 'onsite'|'offsite'|None)]. Typed hours replace what was there."""
    _adult(actor)
    W = _work()
    n = cleared = 0
    with _con() as con:
        c = _lv(W.get_by_id, con, int(contract_id))
        for day, hours, loc in rows:
            day = _clean(v.iso_date, day, "date")
            if hours is None or str(hours).strip() == "":
                cleared += con.execute("DELETE FROM work_hours WHERE contract_id=? AND work_date=?", (c["id"], day)).rowcount
                continue
            _lv(W.set_hours, con, c["id"], day, hours, loc or None, "manual")
            n += 1
        _log(actor, "work_hours_save", f"contract={c['id']} days={n} cleared={cleared}")
        warn = _work().overload_note(con, c["id"], [d for d, h, _ in rows if h is not None and str(h).strip() != ""])
    return f"Saved {n} day{'' if n == 1 else 's'}" + (f", cleared {cleared}" if cleared else "") + "." + warn


@edits
def work_fill(actor, contract_id, start, end):
    _adult(actor)
    W = _work()
    with _con() as con:
        c = _lv(W.get_by_id, con, int(contract_id))
        n = W.fill(con, c, _d(start, "from"), _d(end, "to"))
        _log(actor, "work_fill", f"contract={c['id']} days={n}")
    return f"Filled {n} day{'' if n == 1 else 's'} from the schedule."


@edits
def work_import(actor, filename, kind, contract_id=None, calendar=None, year=None):
    """Import a timesheet or work calendar that was just saved into inbox/ (data/inbox_upload.py) and file it."""
    _adult(actor)
    import inbox_upload
    name = inbox_upload.clean_name(filename)
    path = paths.INBOX / name
    if name != filename or not path.is_file():
        raise EditError("the uploaded file is not in the inbox")
    with _con() as con:
        msg = _lv(_work().file_and_import, con, path, kind, contract=int(contract_id) if contract_id else None, calendar=calendar,
                  year=int(year) if year else None)
        _log(actor, "work_import", f"kind={kind} contract={contract_id or '-'}")
    return f"Imported: {msg}."


@edits
def review_timesheet_job(actor, review_id, contract_id, phrase=None):
    """The answer to "Which job is this timesheet for?": import the waiting file into that job and, when words that identify
    the job's sheets are given, remember them so the next sheet finds its job by itself."""
    _adult(actor)
    import work_match
    W = _work()
    with _con() as con:
        c = _lv(W.get_by_id, con, int(contract_id))
        row = con.execute("SELECT path, resolved FROM review_queue WHERE id=?", (int(review_id),)).fetchone()
        if not row or row[1]:
            raise EditError("that item is already handled")
        f = paths.HOME / row[0]
        if not f.is_file():
            raise EditError("the file is no longer where the queue says; dismiss the item")
        msg = _lv(W.file_and_import, con, f, "timesheet", contract=c["id"])
        con.execute("UPDATE review_queue SET resolved=1 WHERE id=?", (int(review_id),))
        remembered = ""
        if phrase and str(phrase).strip():
            remembered = _lv(work_match.rule_add, con, c["id"], phrase)
        _log(actor, "review_timesheet_job", f"review={review_id} contract={c['id']}" + (" rule" if remembered else ""))
    return f"Imported into {c['client']}: {msg}." + (f' Sheets with "{remembered}" will go there by themselves.' if remembered else "")


@edits
def work_paper_attach(actor, contract_id, document_id, kind):
    """Keep an already filed paper with a job (a link only)."""
    _adult(actor)
    W = _work()
    with _con() as con:
        client = _lv(W.paper_add, con, int(contract_id), int(document_id), kind)
        _log(actor, "work_paper_attach", f"contract={contract_id} document={document_id} kind={kind}")
    return f"Kept with {client}."


@edits
def work_paper_remove(actor, contract_id, document_id):
    """Take a paper off a job's list. The paper itself stays filed."""
    _adult(actor)
    with _con() as con:
        _lv(_work().paper_remove, con, int(contract_id), int(document_id))
        _log(actor, "work_paper_remove", f"contract={contract_id} document={document_id}")
    return "Taken off the list. The paper is still filed."


@edits
def work_paper_upload(actor, filename, contract_id, kind):
    """A paper that was just saved into inbox/ (data/inbox_upload.py): filed and kept with the job."""
    _adult(actor)
    import inbox_upload
    name = inbox_upload.clean_name(filename)
    path = paths.INBOX / name
    if name != filename or not path.is_file():
        raise EditError("the uploaded file is not in the inbox")
    with _con() as con:
        client = _lv(_work().file_paper, con, path, int(contract_id), kind)
        _log(actor, "work_paper_upload", f"contract={contract_id} kind={kind}")
    return f"Filed and kept with {client}."


@edits
def work_calendar_add(actor, name, day, kind, title=None):
    _adult(actor)
    with _con() as con:
        _lv(_work().calendar_add, con, name, day, kind, title)
        _log(actor, "work_calendar_add", f"kind={kind}")
    return f"Added {day} ({kind})."


@edits
def work_paydays(actor, name, start, end, every=None, monthly=None, semimonthly=False):
    _adult(actor)
    with _con() as con:
        n = _lv(_work().calendar_paydays, con, name, _d(start, "from"), _d(end, "to"), every or None, monthly or None, semimonthly)
        _log(actor, "work_paydays", f"n={n}")
    return f"Added {n} pay day{'' if n == 1 else 's'}."


@edits
def work_invoice_make(actor, contract_id, start, end):
    _adult(actor)
    W = _work()
    with _con() as con:
        c = _lv(W.get, con, int(contract_id))
        iid, s = _lv(W.invoice_make, con, c, _d(start, "from"), _d(end, "to"))
        _log(actor, "work_invoice_make", f"id={iid} contract={c['id']}")
    amt = f" = {s['amount']:.2f}" if s["amount"] is not None else ""
    return f"Invoice {iid} recorded as draft: {s['hours']} h{amt}."


@edits
def work_invoice_set(actor, invoice_id, status, on=None):
    _adult(actor)
    with _con() as con:
        iid = _lv(_work().invoice_set, con, int(invoice_id), status, on)
        _log(actor, "work_invoice_set", f"id={iid} status={status}")
    return f"Invoice {iid} marked {status}."
