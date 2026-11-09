"""The rules every validated edit follows (the edit functions themselves are in edit_family / edit_home / edit_money /
edit_work.py and are re-exported by edit_actions.py, audit A9): one transaction, the edit log, the adult check, input
cleaning and the `edits` decorator that turns bad input or database trouble into (False, message).

Every function takes `actor` (the signed-in dashboard user {"name", "role"}) first and returns (ok, message); it never raises
on bad input. Input is checked with the same validators as the assistant (data/validators.py), the SQL is parameterised, only
named columns can change, and each change is appended to logs/edits.log (who, what, which row; no free text).

  * Only adults may edit. The exceptions: life_done_own (a child or guest can finish THEIR OWN non-financial items)
    the shared lists (a signed-in child or guest can add, tick and untick items on FAMILY lists) and saved items (they
    can save family links and notes, a few a day, and archive their own).
  * People edits are written to config/family.json too (that file is the source `members.py sync` copies from), so a later
    sync or upgrade cannot undo them. Nothing is ever deleted: removing a life item marks it 'dropped'.
"""
import contextlib
import datetime as dt
import functools
import pathlib
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import config  # noqa: E402
import members as mem  # noqa: E402
import db  # noqa: E402

DB = paths.DB
LOG = paths.LOGS / "edits.log"
ROLES = list(mem.ROLES)
ACCOUNT_TYPES = ["checking", "savings", "credit", "loan", "investment"]
KIND_OF_CATEGORY = {"transfer": "transfer", "transfers": "transfer", "investing": "investment_transfer",  # category -> txn_type
                    "salary": "income", "income": "income", "interest": "interest", "tax refund": "tax"}
LOAN_KINDS = ["mortgage", "auto", "student", "personal", "heloc", "other"]
FREQS = ["weekly", "monthly", "quarterly", "yearly", "once"]
CLEAR = ""  # passing "" for an optional field clears it
BUSY = "could not save (the database is busy or locked); try again in a moment"


class EditError(ValueError):
    pass


@contextlib.contextmanager
def _con():
    """One transaction: commits on success, rolls back on error, always closes."""
    c = db.connect(DB, timeout=10)
    try:
        with c:
            yield c
    finally:
        c.close()


def _log(actor, action, detail):
    try:
        LOG.parent.mkdir(exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{dt.datetime.now().isoformat(timespec='seconds')}\t{(actor or {}).get('name') or '-'}\t{action}\t{detail}\n")
    except OSError:
        pass


def _adult(actor):
    if (actor or {}).get("role") != "adult":
        raise EditError("only an adult can change this")


def _clean(validator, value, label):
    try:
        return validator(value)
    except (ValueError, TypeError) as e:
        raise EditError(f"{label}: {e}") from None


def _opt(validator, value, label):
    return None if value is None or str(value).strip() == "" else _clean(validator, value, label)


def edits(fn):
    """Turn EditError / database trouble into (False, message)."""
    @functools.wraps(fn)
    def wrapper(*a, **k):
        try:
            return True, fn(*a, **k)
        except (EditError, config.Broken) as e:
            return False, str(e)
        except sqlite3.Error as e:
            return False, _db_trouble(fn.__name__, e)
    return wrapper


CLASH = "nothing was saved: that change clashes with a record that is already there"
FAILED = "nothing was saved: the database refused the change (the details are in the logs folder)"


def _db_trouble(action, e):
    """BUSY only when the database really is locked (worth a retry); a constraint or a real fault says so and is
    logged, instead of asking the family to try again forever."""
    text = str(e).lower()
    if isinstance(e, sqlite3.OperationalError) and ("locked" in text or "busy" in text):
        return BUSY
    import log
    log.get("edits").warning("%s failed: %s: %s", action, type(e).__name__, e)
    return CLASH if isinstance(e, sqlite3.IntegrityError) else FAILED


def _member_name(con, who):
    if not who:
        return None
    name = mem.resolve(con, who)
    if name not in mem.names(con):
        raise EditError(f"for: '{who}' is not a family member")
    return name


def _item(con, item_id):
    con.row_factory = sqlite3.Row
    r = con.execute("SELECT * FROM life_items WHERE id=? AND status='open'", (item_id,)).fetchone()
    if not r:
        raise EditError("that item no longer exists (or is already finished)")
    return r


def _signed_in(actor):
    name = (actor or {}).get("name")
    if (actor or {}).get("role") != "adult" and not name:
        raise EditError("sign in first")
    return name or None


def _lv(fn, *a, **k):
    try:
        return fn(*a, **k)
    except ValueError as e:
        raise EditError(str(e)) from None
