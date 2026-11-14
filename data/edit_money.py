"""Validated edits for the web app: budget lines, loans, subscriptions, bills, the review queue, recurring bills, receipts and accounts (split from edit_actions.py, audit A9).

See edit_core.py for the rules every edit follows; edit_actions.py re-exports everything, callers keep using it.
"""
import datetime as dt
import sqlite3
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import account_types as AT  # noqa: E402
import config  # noqa: E402
import dates  # noqa: E402
import paths  # noqa: E402
import validators as v  # noqa: E402
from edit_core import (  # noqa: E402
    ACCOUNT_TYPES,
    EditError,
    FREQS,
    KIND_OF_CATEGORY,
    LOAN_KINDS,
    _adult,
    _clean,
    _con,
    _log,
    _lv,
    _member_name,
    _opt,
    edits,
)


# ---------------------------------------------------------------- home office
@edits
def home_office_set(actor, year, who, office_sqft=None, home_sqft=None, months=None, method=None, self_employed=None,
                    exclusive=None, regular=None, principal=None, income=None):
    """Create or update one person's home-office profile for a tax year. Omitted/None = unchanged; the yes/no answers
    take 1, 0 or "" (unanswered). Records only, not tax advice."""
    _adult(actor)
    year = _clean(v.integer(2000, 2100), year, "tax year")
    method = _opt(v.one_of(("simplified", "regular")), method, "method")
    cols = {"office_sqft": _opt(v.num(0, 1e6), office_sqft, "office area"), "home_sqft": _opt(v.num(0, 1e6), home_sqft, "home area"),
            "months_used": _opt(v.integer(1, 12), months, "months used"), "method": method,
            "gross_income": _opt(v.money(0, 1e9), income, "gross income")}
    for col, val, label in (("self_employed", self_employed, "self-employed"), ("exclusive_use", exclusive, "used only for work"),
                            ("regular_use", regular, "regular use"), ("principal_place", principal, "principal place")):
        cols[col] = None if val in (None, "") else _clean(v.one_of(("0", "1")), val, label)
    with _con() as con:
        who = _member_name(con, who)
        if not who:
            raise EditError("for: pick a family member")
        con.execute("INSERT OR IGNORE INTO home_office_profile(tax_year, who) VALUES (?,?)", (year, who))
        for col, val in cols.items():
            if val is not None:
                con.execute(f"UPDATE home_office_profile SET {col}=? WHERE tax_year=? AND who=?", (val, year, who))  # noqa: S608 (col is from the fixed dict above)
        _log(actor, "home_office_set", f"year={year}")
    return f"Saved the {year} home-office details for {who}."


# ---------------------------------------------------------------- budget and loans
@edits
def budget_set(actor, category, limit):
    _adult(actor)
    category = _clean(v.text(60), category, "category")
    limit = _clean(v.money(0, 1e7), limit, "monthly limit")
    with _con() as con:
        con.execute("INSERT INTO budget(category, monthly_limit) VALUES (?,?) "
                    "ON CONFLICT(category) DO UPDATE SET monthly_limit=excluded.monthly_limit", (category, limit))
        _log(actor, "budget_set", f"category={category}")
    return f"Budget for {category}: {limit:,.2f} a month."


TXN_TYPES = ("spend", "income", "interest", "transfer", "card_payment", "investment_transfer", "tax", "fee", "utility",
             "insurance", "loan_payment")


@edits
def txn_update(actor, txn_id, category=None, txn_type=None, similar=False):
    """Money > Ledger: set a line's category and / or type by hand (adults). Only these two change; date, amount, account
    and description stay as the statement printed them. The line is marked `manual`, so the category rules, the transfer
    pairing and the data check never overwrite it. category "" = none; txn_type "" or None = leave. similar = also
    remember the merchant (`category_rule_add`), so every other line like it, now and later, follows (not for card
    payments, fees, utilities, insurance or loan payments: those types have no rule). -> message."""
    _adult(actor)
    try:
        txn_id = int(txn_id)
    except (TypeError, ValueError):
        raise EditError("that line is not there") from None
    new_cat = None if category is None else str(category).strip()
    if new_cat:
        new_cat = _clean(v.text(40), new_cat, "category").lower()
    new_type = str(txn_type or "").strip() or None
    if new_type:
        new_type = _clean(v.one_of(list(TXN_TYPES)), new_type, "type")
    with _con() as con:
        r = con.execute("SELECT description, category, txn_type FROM transactions WHERE id=?", (txn_id,)).fetchone()
        if not r:
            raise EditError("that line is no longer there")
        desc, old_cat, old_type = r
        cat = old_cat if new_cat is None else (new_cat or None)
        typ = new_type or old_type
        if similar:
            import rule_match
            if not cat:
                raise EditError("category: name one to remember it for the lines that look like this")
            if (typ or "spend") not in rule_match.DEPOSIT_KINDS:
                raise EditError("this type cannot be remembered for other lines; save only this one")
        fields = [n for n, a, b in (("category", cat, old_cat), ("type", typ, old_type)) if (a or None) != (b or None)]
        if fields:
            con.execute("UPDATE transactions SET category=?, txn_type=?, manual=1 WHERE id=?", (cat, typ, txn_id))
            _log(actor, "txn_update", f"id={txn_id} fields={','.join(fields)}")
    out = "Saved." if fields else "Nothing changed."
    if similar:
        import rule_match
        kind = typ if (typ or "spend") in rule_match.DEPOSIT_KINDS else None
        pattern = rule_match.merchant_key(desc) or rule_match.clean(desc)[:24]
        ok, msg = category_rule_add(actor, pattern, cat, kind)
        if not ok:
            raise EditError(f"{out} The rule for similar lines was not saved: {msg}")
        out = f"{out} {msg}"
    return out


@edits
def category_rule_add(actor, pattern, category, kind=None):
    """Remember a merchant or a deposit source: lines whose description matches `pattern` get `category` now and on every
    later import. Written to config/category_rules.json (the family's own rules, which win over the starter set) and to the
    rule table; lines the pattern matches take the rule even when they had another category (the family's word wins), and
    other lines with no category that a rule matches are filled in. `kind` = the txn_type (rule_match.DEPOSIT_KINDS; Finance >
    Deposits says what a deposit is), else it follows the category (KIND_OF_CATEGORY, default spending). -> message."""
    _adult(actor)
    import audit_fix
    import rule_match
    pattern = _clean(v.text(60), pattern, "text to match").upper()
    if kind not in (None, ""):
        kind = _clean(v.one_of(list(rule_match.DEPOSIT_KINDS)), kind, "kind")
        category = (str(category or "").strip() or rule_match.DEPOSIT_KINDS[kind][0])
    category = _clean(v.text(40), category, "category").lower()
    if "%" not in pattern:
        pattern += "%"
    if len(pattern.replace("%", "").strip()) < 3:
        raise EditError("text to match: give at least three letters of the merchant's name")
    path = paths.CONFIG / "category_rules.json"
    rules = [r for r in (config.data_file("category_rules.json") or []) if isinstance(r, list) and len(r) == 4]
    kind = kind or KIND_OF_CATEGORY.get(category, "spend")  # "transfer" must stop counting as spending
    rules = [r for r in rules if str(r[0]).upper() != pattern] + [[pattern, category, kind, None]]
    config.write_json(path, rules)
    with _con() as con:
        con.execute("INSERT INTO category_rules(pattern, category, payee_type, payee, priority) VALUES (?,?,?,?,?) "
                    "ON CONFLICT(pattern) DO UPDATE SET category=excluded.category, payee_type=excluded.payee_type, "
                    "payee=excluded.payee, priority=excluded.priority", (pattern, category, kind, None, min(len(rules), 99)))
        n = rule_match.reapply(con, pattern) + audit_fix.categorize(con)[0]
        _log(actor, "category_rule_add", f"pattern={pattern} category={category} kind={kind} rows={n}")
    return (f"Remembered: {pattern.rstrip('%').strip()} is {category}. "
            f"{n} line{'' if n == 1 else 's'} updated; new ones follow the rule.")


@edits
def budget_delete(actor, category):
    _adult(actor)
    with _con() as con:
        n = con.execute("DELETE FROM budget WHERE category=?", (category,)).rowcount
        _log(actor, "budget_delete", f"category={category}")
    if not n:
        raise EditError("no such budget line")
    return f"Removed the {category} budget line."


@edits
def loan_add(actor, name, kind="other", lender=None, balance=None, rate=None, payment=None, payoff=None):
    _adult(actor)
    name = _clean(v.text(80), name, "name")
    kind = _clean(v.one_of(LOAN_KINDS), kind, "kind")
    lender = _opt(v.text(80), lender, "lender")
    balance = _opt(v.money(0, 1e9), balance, "balance")
    rate = _opt(v.num(0, 100), rate, "rate %")
    payment = _opt(v.money(0, 1e7), payment, "payment")
    payoff = _opt(v.iso_date, payoff, "payoff date")
    with _con() as con:
        cur = con.execute("INSERT INTO loans(name, lender, kind, balance, balance_date, rate_pct, payment, payoff_date) VALUES (?,?,?,?,?,?,?,?)",
                          (name, lender, kind, balance, dates.today().isoformat() if balance is not None else None, rate, payment, payoff))
        aid = _loan_account(con, cur.lastrowid, name, kind, lender)
        _log(actor, "loan_add", f"id={cur.lastrowid} kind={kind} account={aid}")
    return f"Added the {name} loan."


LOAN_SUBTYPE = {"mortgage": "mortgage", "auto": "auto", "student": "student", "personal": "personal", "heloc": "heloc"}


def _loan_account(con, loan_id, name, kind, lender):
    """The account a new loan is the detail of: the one unlinked loan account of that name, else a new one (as migration
    071 does for older loans). -> account id, or None when the name is taken by another kind of account twice over."""
    linked = {r[0] for r in con.execute("SELECT account_id FROM loans WHERE account_id IS NOT NULL")}
    same = [r[0] for r in con.execute("SELECT id FROM accounts WHERE type='loan' AND lower(name)=lower(?)", (name,))
            if r[0] not in linked]
    if len(same) == 1:
        aid = same[0]
    else:
        label = name
        for label in (name, f"{name} (loan)"):
            if not con.execute("SELECT 1 FROM accounts WHERE name=? COLLATE NOCASE", (label,)).fetchone():
                break
        else:
            return None
        aid = con.execute("INSERT INTO accounts(name, type, subtype, subtype_locked, institution) VALUES (?,?,?,1,?)",
                          (label, "loan", LOAN_SUBTYPE.get(kind, "other_loan"), lender)).lastrowid
    con.execute("UPDATE loans SET account_id=? WHERE id=?", (aid, loan_id))
    return aid


@edits
def loan_update(actor, loan_id, balance=None, rate=None, payment=None, payoff=None, status=None):
    """Omitted/None = unchanged; "" clears payoff. A new balance records today as its date."""
    _adult(actor)
    with _con() as con:
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM loans WHERE id=?", (loan_id,)).fetchone()
        if not row:
            raise EditError("no such loan")
        upd = {}
        if balance is not None and str(balance) != "":
            upd["balance"] = _clean(v.money(0, 1e9), balance, "balance")
            upd["balance_date"] = dates.today().isoformat()
        if rate is not None and str(rate) != "":
            upd["rate_pct"] = _clean(v.num(0, 100), rate, "rate %")
        if payment is not None and str(payment) != "":
            upd["payment"] = _clean(v.money(0, 1e7), payment, "payment")
        if payoff is not None:
            upd["payoff_date"] = _opt(v.iso_date, payoff, "payoff date")
        if status is not None:
            upd["status"] = _clean(v.one_of(["active", "paid_off"]), status, "status")
        if not upd:
            return "Nothing changed."
        con.execute(f"UPDATE loans SET {', '.join(k + '=?' for k in upd)} WHERE id=?", (*upd.values(), loan_id))
        _log(actor, "loan_update", f"id={loan_id} fields={','.join(upd)}")
    return f"Saved the {row['name']} loan."


# ---------------------------------------------------------------- savings goals
def _goal_account(con, account):
    if account is None or str(account).strip() == "":
        return None
    try:
        aid = int(account)
    except (TypeError, ValueError):
        raise EditError("pick the account from the list")
    if not con.execute("SELECT 1 FROM accounts WHERE id=?", (aid,)).fetchone():
        raise EditError("pick the account from the list")
    return aid


@edits
def savings_goal_add(actor, name, target, due=None, saved=None, account=None):
    """A savings goal: what for, how much, by when (optional), set aside so far (typed) or one account kept for it."""
    _adult(actor)
    name = _clean(v.text(60), name, "what it is for")
    target = _clean(v.money(0.01, 1e9), target, "amount to save")
    due = _opt(v.iso_date, due, "by when")
    saved = _opt(v.money(0, 1e9), saved, "saved so far") or 0
    now = dates.now_iso()
    with _con() as con:
        aid = _goal_account(con, account)
        cur = con.execute("INSERT INTO savings_goals(name, target, saved, due_date, account_id, status, created_at, updated_at) "
                          "VALUES (?,?,?,?,?, 'active', ?, ?)", (name, target, saved, due, aid, now, now))
        _log(actor, "savings_goal_add", f"id={cur.lastrowid}")
    return f"Added the savings goal {name}."


@edits
def savings_goal_update(actor, goal_id, saved=None, target=None, due=None, account=None, status=None):
    """Omitted / None = unchanged; due "" clears the date, account "" stops using an account. status done | dropped |
    active."""
    _adult(actor)
    with _con() as con:
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM savings_goals WHERE id=?", (goal_id,)).fetchone()
        if not row:
            raise EditError("no such savings goal")
        upd = {}
        if saved is not None and str(saved) != "":
            upd["saved"] = _clean(v.money(0, 1e9), saved, "saved so far")
        if target is not None and str(target) != "":
            upd["target"] = _clean(v.money(0.01, 1e9), target, "amount to save")
        if due is not None:
            upd["due_date"] = _opt(v.iso_date, due, "by when")
        if account is not None:
            upd["account_id"] = _goal_account(con, account)
        if status is not None:
            upd["status"] = _clean(v.one_of(["active", "done", "dropped"]), status, "status")
        if not upd:
            return "Nothing changed."
        upd["updated_at"] = dates.now_iso()
        con.execute(f"UPDATE savings_goals SET {', '.join(k + '=?' for k in upd)} WHERE id=?", (*upd.values(), goal_id))
        _log(actor, "savings_goal_update", f"id={goal_id} fields={','.join(k for k in upd if k != 'updated_at')}")
    if upd.get("status") == "done":
        return f"Well done: {row['name']} is marked reached."
    return f"Saved the savings goal {row['name']}."


# ---------------------------------------------------------------- subscriptions
@edits
def bill_add(actor, name, due, amount=None, vendor=None, frequency="once"):
    """A bill to pay by a date: the family's name for it, the company, the amount (may be unknown yet), how often."""
    _adult(actor)
    name = _clean(v.text(80), name, "name")
    due = _clean(v.iso_date, due, "due date")
    amount = _opt(v.money(0, 1e7), amount, "amount")
    vendor = _opt(v.text(80), vendor, "from")
    frequency = _clean(v.one_of(FREQS), frequency or "once", "how often")
    with _con() as con:
        dup = con.execute("SELECT id FROM bills WHERE lower(name)=lower(?) AND due_date=?", (name, due)).fetchone()
        if dup:
            raise EditError("already recorded: a bill with that name and due date")
        cur = con.execute("INSERT INTO bills(name, vendor, frequency, amount, due_date, status) VALUES (?,?,?,?,?,'due')",
                          (name, vendor, frequency, amount, due))
        _log(actor, "bill_add", f"id={cur.lastrowid}")
    return f"Added the bill {name}, due {due}" + (f", {amount:.2f}" if amount is not None else ", amount not known yet") + "."


@edits
def subscription_add(actor, name, amount=None, frequency="monthly", next_renewal=None):
    _adult(actor)
    name = _clean(v.text(80), name, "name")
    amount = _opt(v.money(0, 1e6), amount, "amount")
    frequency = _clean(v.one_of(FREQS), frequency, "how often")
    renew = _opt(v.iso_date, next_renewal, "next renewal")
    with _con() as con:
        words = " ".join("".join(ch for ch in name if ch.isalnum() or ch == " ").split())
        pattern = f"%{words.upper()}%" if len(words) >= 3 else None  # match the name inside the bank's description
        cur = con.execute("INSERT INTO subscriptions(name, amount, frequency, next_renewal, active, match_pattern) VALUES (?,?,?,?,1,?)",
                          (name, amount, frequency, renew, pattern))
        _log(actor, "subscription_add", f"id={cur.lastrowid}")
    return f"Added {name}."


@edits
def subscription_set_active(actor, sub_id, active):
    _adult(actor)
    with _con() as con:
        row = con.execute("SELECT name FROM subscriptions WHERE id=?", (sub_id,)).fetchone()
        if not row:
            raise EditError("no such subscription")
        con.execute("UPDATE subscriptions SET active=? WHERE id=?", (1 if active else 0, sub_id))
        _log(actor, "subscription_set_active", f"id={sub_id} active={int(bool(active))}")
    return f"{row[0]} is now {'on' if active else 'off'}."


SUB_DECISIONS = ["unreviewed", "keep", "cancel", "cancelled"]


@edits
def subscription_decide(actor, sub_id, decision, note=None):
    """keep | cancel | cancelled | unreviewed (the same as `subscriptions.py decide`); today becomes the review date, which
    for 'cancelled' is the date after which a charge is flagged. A note is added to the earlier ones."""
    _adult(actor)
    decision = _clean(v.one_of(SUB_DECISIONS), decision, "decision")
    note = _opt(v.text(200), note, "note")
    with _con() as con:
        row = con.execute("SELECT name FROM subscriptions WHERE id=?", (int(sub_id),)).fetchone()
        if not row:
            raise EditError("no such subscription")
        con.execute("UPDATE subscriptions SET decision=?, reviewed_on=?, notes=CASE WHEN ? IS NULL THEN notes "
                    "ELSE COALESCE(notes || ' | ', '') || ? END WHERE id=?",
                    (decision, dates.today().isoformat(), note, note, int(sub_id)))
        _log(actor, "subscription_decide", f"id={int(sub_id)} decision={decision}")
    return f"{row[0]}: {decision}."


# ---------------------------------------------------------------- bills
@edits
def bill_move(actor, bill_id, due):
    """A new due date for an open bill (the Inbox: a change made in Google Calendar)."""
    _adult(actor)
    due = _clean(v.iso_date, due, "due date")
    with _con() as con:
        r = con.execute("SELECT name, status FROM bills WHERE id=?", (bill_id,)).fetchone()
        if not r:
            raise EditError("that bill is no longer on record")
        if r[1] == "paid":
            raise EditError("that bill is already paid")
        con.execute("UPDATE bills SET due_date=? WHERE id=?", (due, bill_id))
        _log(actor, "bill_move", f"id={bill_id}")
    return f"{r[0]} is now due {dates.day_text(due)}."


@edits
def bill_paid(actor, bill_id, when=None):
    """Mark one open bill paid on `when` (default today, never in the future)."""
    _adult(actor)
    today = dates.today().isoformat()
    day = _opt(v.iso_date, when, "paid on") or today
    if day > today:
        raise EditError("paid on: it can not be in the future")
    with _con() as con:
        r = con.execute("SELECT COALESCE(vendor, name), name, vendor, frequency, due_date FROM bills "
                        "WHERE id=? AND status IN ('due','overdue')", (int(bill_id),)).fetchone()
        if not r:
            raise EditError("that bill is not open any more")
        con.execute("UPDATE bills SET status='paid', paid_date=? WHERE id=?", (day, int(bill_id)))
        _log(actor, "bill_paid", f"id={int(bill_id)}")
        nxt = _next_yearly(con, r)
    return f"Marked {r[0]} as paid." + (f" Next one is due {nxt}." if nxt else "")


def _next_yearly(con, r):
    """A yearly bill (home tax, a yearly fee) gets next year's open bill once it is paid, unless one is already open
    or already there for that date. -> the new due date or None."""
    key, name, vendor, freq, due = r
    if (freq or "") != "yearly":
        return None
    d = dt.date.fromisoformat(due[:10])
    nxt = (d.replace(year=d.year + 1) if not (d.month == 2 and d.day == 29) else dt.date(d.year + 1, 2, 28)).isoformat()
    if con.execute("SELECT 1 FROM bills WHERE COALESCE(vendor, name)=? AND (status IN ('due','overdue') OR due_date=?)",
                   (key, nxt)).fetchone():
        return None
    con.execute("INSERT INTO bills(name, vendor, frequency, due_date, status) VALUES (?,?, 'yearly', ?, 'due')", (name, vendor, nxt))
    return nxt


@edits
def bill_unpaid(actor, bill_id):
    """Undo a paid mark: the bill is due again (overdue when its date has passed)."""
    _adult(actor)
    today = dates.today().isoformat()
    with _con() as con:
        r = con.execute("SELECT COALESCE(vendor, name), due_date FROM bills WHERE id=? AND status='paid'",
                        (int(bill_id),)).fetchone()
        if not r:
            raise EditError("that bill is not marked paid")
        con.execute("UPDATE bills SET status=?, paid_date=NULL WHERE id=?",
                    ("overdue" if r[1] < today else "due", int(bill_id)))
        _log(actor, "bill_unpaid", f"id={int(bill_id)}")
    return f"{r[0]} is open again."


# ---------------------------------------------------------------- review queue (files the AI pipeline would not guess about)
@edits
def review_file(actor, review_id, typ, vendor, date, amount=None, due=None):
    """File a waiting document by hand: type, vendor and date are required; amount and due date add a bill for bills and
    policies. Moves the file into archive/ and logs it; no AI is involved (data/ai_intake.py resolve_review)."""
    _adult(actor)
    import ai_intake
    typ = _clean(v.one_of(list(ai_intake.CATEGORY)), typ, "type")
    vendor = _clean(v.text(80), vendor, "vendor")
    date = _clean(v.iso_date, date, "date")
    amount = _opt(v.money(0, 1e9), amount, "amount")
    due = _opt(v.iso_date, due, "due date")
    with _con() as c:
        try:
            doc_id, dest = ai_intake.resolve_review(c, int(review_id), typ, vendor, date, amount, due,
                                                    "filed by a person from the dashboard review queue")
        except ValueError as e:
            raise EditError(str(e)) from None
        _log(actor, "review_file", f"review={review_id} document={doc_id} type={typ}")
    msg = f"Filed as {dest.name} with the {dest.parent.name} papers of {dest.parent.parent.name}."
    if typ == "statement" and dest.suffix.lower() not in (".pdf", ".txt"):
        msg += " It is a photo, so its lines were not read; add the transactions from a PDF or CSV export of the statement."
    elif typ == "statement":
        import pdf_statement as ps
        try:
            with _con() as c:
                rep = ps.import_pdf(c, dest, document_id=doc_id)
            msg += f" {rep['inserted']} transactions added ({rep['skipped']} already loaded)."
        except (ps.StatementError, ValueError) as e:
            msg += f" Not imported: {e}"
    return msg


@edits
def review_retry(actor, review_id):
    """Read a waiting document again: it goes back into the inbox for the next filing run (no AI call here)."""
    _adult(actor)
    import ai_intake
    with _con() as c:
        try:
            dest = ai_intake.retry_review(c, int(review_id))
        except ValueError as e:
            raise EditError(str(e)) from None
        _log(actor, "review_retry", f"review={review_id}")
    return f"{dest.name} is back in the inbox to be read again."


@edits
def review_add_account(actor, review_id, name, kind, last4):
    """The fix for a statement of an account this PC does not know: add the account (last four only), then read the
    statement again."""
    _adult(actor)
    ok, msg = account_add(actor, name, kind, last4)
    if not ok:
        raise EditError(msg)
    ok, again = review_retry(actor, review_id)
    if not ok:
        raise EditError(f"Account {name} added, but the statement could not go back to the inbox: {again}")
    return f"Account {name} added. {again}"


@edits
def review_import_statement(actor, review_id, account_id, read_as=None, force=False):
    """Import a waiting statement (PDF, activity CSV, OFX / QFX) into the account a person picked; a PDF only when it
    adds up, unless they ticked Import anyway (ai_intake.import_review_statement)."""
    _adult(actor)
    import ai_intake
    try:
        account_id = int(account_id)
    except (TypeError, ValueError):
        raise EditError("choose one of the accounts") from None
    if read_as not in (None, "", "bank", "card"):
        raise EditError("read it as a bank account or a card")
    with _con() as c:
        try:
            msg = ai_intake.import_review_statement(c, int(review_id), account_id, read_as, bool(force))
        except ValueError as e:
            raise EditError(f"Not imported: {e}.") from None
        _log(actor, "review_import_statement", f"review={review_id} account={account_id} forced={bool(force)}")
    return msg


@edits
def review_dismiss(actor, review_id):
    """Close a review row without filing (the file stays where it is; nothing is deleted)."""
    _adult(actor)
    with _con() as c:
        cur = c.execute("UPDATE review_queue SET resolved=1 WHERE id=? AND resolved=0", (int(review_id),))
        if cur.rowcount != 1:
            raise EditError("that review item is already closed")
        _log(actor, "review_dismiss", f"review={review_id}")
    return "Dismissed. The file is still in inbox/needs_review/."


# ---------------------------------------------------------------- recurring bills found in transactions
@edits
def recurring_confirm(actor, payee, name=None):
    """Track a detected recurring payee as a bill (data/recurring_bills.py confirm): the next expected charge becomes a
    bills row and the weekly sync keeps it rolling forward."""
    _adult(actor)
    import recurring_bills as rb
    payee = _clean(v.text(80), payee, "payee")
    name = _opt(v.text(80), name, "name")
    with _con() as c:
        try:
            bid = rb.confirm(c, payee, name=name)
        except ValueError as e:
            raise EditError(str(e)) from None
        _log(actor, "recurring_confirm", f"bill={bid}")
    return f"Tracking {payee} as a bill (next one is in the Bills list)."


@edits
def recurring_dismiss(actor, payee):
    """Stop proposing this payee (config/recurring_bills.json 'ignored')."""
    _adult(actor)
    import recurring_bills as rb
    payee = _clean(v.text(80), payee, "payee")
    rb.dismiss(payee)
    _log(actor, "recurring_dismiss", "1")
    return f"{payee} will not be proposed again."


@edits
def bank_copy_remove(actor, txn_id):
    """Remove a bank-sync row that repeats a statement row (bank_sync.remove_copy: links and category move over)."""
    _adult(actor)
    import bank_sync
    txn_id = _clean(v.integer(1, 10**12), txn_id, "transaction")
    with _con() as c:
        twin = bank_sync.remove_copy(c, txn_id)
        if twin is None:
            raise EditError("that row is not a bank-sync copy of a statement row (any more)")
        _log(actor, "bank_copy_remove", f"id={txn_id} kept={twin}")
    return "Removed the bank-sync copy; the statement row stays."


@edits
def audit_remove_copies(actor, fix, ids, key=None):
    """Remove the extra copies of a charge entered twice (fix dupe_txn) or a bill listed twice (dupe_bill), found by
    the data check; the first charge / the paid or first bill stays. Undoable (audit_fix.undo)."""
    _adult(actor)
    import audit_fix
    fix = _clean(v.one_of(("dupe_txn", "dupe_bill")), fix, "fix")
    ids = sorted({_clean(v.integer(1, 10**12), i, "row") for i in (ids or [])})
    if len(ids) < 2:
        raise EditError("there is nothing to remove")
    q = ",".join("?" * len(ids))
    with _con() as c:
        if fix == "dupe_txn":
            same = c.execute("SELECT COUNT(*), COUNT(DISTINCT account_id || '|' || txn_date || '|' || amount_cents || '|' || "
                             "UPPER(TRIM(COALESCE(description, '')))), MIN(description), COUNT(NULLIF(TRIM(ref), '')) FROM transactions "
                             f"WHERE id IN ({q})", ids).fetchone()
            keep, table, action = ids[0], "transactions", "remove_txns"
        else:
            same = c.execute("SELECT COUNT(*), COUNT(DISTINCT LOWER(TRIM(name)) || '|' || due_date), MIN(name), 0 FROM bills "
                             f"WHERE id IN ({q})", ids).fetchone()
            paid = c.execute(f"SELECT MIN(id) FROM bills WHERE id IN ({q}) AND status='paid'", ids).fetchone()[0]
            keep, table, action = paid or ids[0], "bills", "remove_bills"
        if same[0] != len(ids) or same[1] != 1 or (fix == "dupe_txn" and same[3]):  # rows with a bank reference are real
            raise EditError("those rows have changed since the data check; run it again")
        drop = [i for i in ids if i != keep]
        try:
            u = audit_fix.remove_rows(c, table, keep, drop)
        except audit_fix.FixError as e:
            raise EditError(str(e)) from None
        name = (same[2] or "the row")[:60]
        what = "1 extra copy" if len(drop) == 1 else f"{len(drop)} extra copies"
        audit_fix.record(c, action, f"Removed {what} of {name}", u, (actor or {}).get("name") or "-", key=key)
        _log(actor, "audit_remove_copies", f"{table} kept={keep} removed={','.join(map(str, drop))}")
    return f"Removed {what} of {name}. Settings > Data > Data check can put it back."


@edits
def audit_fix_undo(actor, fix_id):
    """Undo one fix of the data check (Settings > Data > Data check)."""
    _adult(actor)
    import audit_fix
    fix_id = _clean(v.integer(1, 10**12), fix_id, "fix")
    with _con() as c:
        try:
            msg = audit_fix.undo(c, fix_id, (actor or {}).get("name") or "-")
        except audit_fix.FixError as e:
            raise EditError(str(e)) from None
        _log(actor, "audit_fix_undo", f"id={fix_id}")
    return msg


@edits
def subscription_accept(actor, merchant):
    """Track a detected recurring merchant as a subscription (the same as `subscriptions.py accept`), matched by its
    description words and, when the bank gave one, its payee name. The decision starts 'unreviewed'."""
    _adult(actor)
    import subscriptions as subs
    merchant = _clean(v.text(80), merchant, "merchant")
    with _con() as c:
        cand = next((r for r in subs.detect(c) if r["merchant"].lower() == merchant.lower()), None)
        if not cand:
            raise EditError("that payment is no longer showing as recurring (or is already tracked)")
        cur = c.execute("INSERT INTO subscriptions(name, amount, frequency, next_renewal, active, match_pattern, match_payee, decision) "
                        "VALUES (?,?,?,?,1,?,?,'unreviewed')",
                        (cand["merchant"], cand["amount"], cand["frequency"], cand["next"].isoformat(),
                         "%" + cand["merchant"].upper() + "%", cand["merchant"]))
        _log(actor, "subscription_accept", f"id={cur.lastrowid}")
    return f"Tracking {cand['merchant']} as a subscription."


# ---------------------------------------------------------------- receipts
def _receipts():
    import receipts
    return receipts


@edits
def receipt_add(actor, merchant, date, total, last4=None):
    _adult(actor)
    with _con() as con:
        rid = _lv(_receipts().add, con, merchant, date, total, last4 or None)
        r = _receipts().get(con, rid)
        _log(actor, "receipt_add", f"id={rid} matched={r['match_confidence']}")
    return f"Receipt {rid} added: " + ("matched to a charge." if r["transaction_id"] else (r["match_note"] or "open."))


@edits
def receipt_link(actor, receipt_id, txn_id):
    _adult(actor)
    with _con() as con:
        rid = _lv(_receipts().link, con, int(receipt_id), int(txn_id))
        _log(actor, "receipt_link", f"id={rid} txn={int(txn_id)}")
    return f"Receipt {rid} linked."


@edits
def receipt_unlink(actor, receipt_id):
    _adult(actor)
    with _con() as con:
        rid = _lv(_receipts().unlink, con, int(receipt_id))
        _log(actor, "receipt_unlink", f"id={rid}")
    return f"Receipt {rid} unlinked; it will not be matched again automatically."


@edits
def receipt_ignore(actor, receipt_id):
    _adult(actor)
    with _con() as con:
        rid = _lv(_receipts().ignore, con, int(receipt_id))
        _log(actor, "receipt_ignore", f"id={rid}")
    return f"Receipt {rid}: no charge expected."


# ---------------------------------------------------------------- accounts and checkup dates (adults)
def _subtype(kind):
    """A form's type: a detailed subtype or one of the older coarse types -> (subtype, coarse type)."""
    kind = str(kind or "").strip()
    if kind in AT.SUBTYPES:
        return kind, AT.coarse(kind)
    kind = _clean(v.one_of(ACCOUNT_TYPES), kind, "type")
    return AT.DEFAULT_OF_TYPE[kind], kind


def _last4(last4):
    last4 = str(last4 or "").strip() or None
    if last4 and not (len(last4) == 4 and last4.isdigit()):
        raise EditError("last 4: exactly four digits, never the whole account number")
    return last4


@edits
def account_add(actor, name, kind, last4=None, owner=None, institution=None, ownership=None):
    """A bank or card account, so statements can be matched to it. Last four digits only. `kind` = a subtype
    (account_types.SUBTYPES) or a coarse type."""
    _adult(actor)
    name = _clean(v.text(60), name, "name")
    sub, kind = _subtype(kind)
    last4 = _last4(last4)
    owner = _opt(v.text(40), owner, "owner")
    institution = _opt(v.text(60), institution, "bank")
    ownership = _opt(v.one_of(AT.OWNERSHIP), ownership, "ownership") or "individual"
    with _con() as con:
        if con.execute("SELECT 1 FROM accounts WHERE name=? COLLATE NOCASE", (name,)).fetchone():
            raise EditError(f"there is already an account called {name}")
        if last4 and con.execute("SELECT 1 FROM accounts WHERE last4=?", (last4,)).fetchone():
            raise EditError(f"another account already ends in {last4}; statements could not tell them apart")
        con.execute("INSERT INTO accounts(name, type, last4, owner, owners, subtype, subtype_locked, institution, ownership) "
                    "VALUES (?,?,?,?,?,?,1,?,?)", (name, kind, last4, owner, owner, sub, institution, ownership))
        _log(actor, "account_add", f"type={sub}")
    return f"Account {name} added. Drop its statement (PDF or CSV export) in the Inbox."


@edits
def account_update(actor, account_id, name=None, kind=None, institution=None, ownership=None, owners=None,
                   closed_on=None, credit_limit=None, apr=None, due_day=None, min_payment=None, death_benefit=None,
                   premium=None, loan_id=None, holdings=None, value=None):
    """Change an account. None = unchanged, "" clears (not the name or type). A type set here is locked: bank sync
    never guesses it again. Owners are names as typed ("Marcus, Elena"); joint needs two. `loan_id` = the loan row this
    account is ("" = none); `holdings` = ids of the investments rows it holds (the list replaces the links)."""
    _adult(actor)
    with _con() as con:
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM accounts WHERE id=?", (int(account_id),)).fetchone()
        if not row:
            raise EditError("no such account")
        upd = {}
        if name is not None and str(name).strip() and str(name).strip() != row["name"]:
            name = _clean(v.text(60), name, "name")
            if con.execute("SELECT 1 FROM accounts WHERE name=? COLLATE NOCASE AND id!=?", (name, row["id"])).fetchone():
                raise EditError(f"there is already an account called {name}")
            upd["name"] = name
        if kind is not None and str(kind).strip():
            sub, coarse = _subtype(kind)
            if sub != row["subtype"] or not row["subtype_locked"]:
                upd.update(subtype=sub, type=coarse, subtype_locked=1)
        if institution is not None:
            upd["institution"] = _opt(v.text(60), institution, "bank")
        if owners is not None:
            people = [p.strip() for p in str(owners).split(",") if p.strip()]
            for p in people:
                _clean(v.text(40), p, "owner")
            upd["owners"] = ", ".join(people) or None
        if ownership is not None and str(ownership).strip():
            upd["ownership"] = _clean(v.one_of(AT.OWNERSHIP), ownership, "ownership")
        if closed_on is not None:
            upd["closed_on"] = _opt(v.iso_date, closed_on, "closed on")
            if upd["closed_on"] and upd["closed_on"] > dates.today().isoformat():
                raise EditError("closed on: it can not be in the future")
        if credit_limit is not None:
            upd["credit_limit"] = _opt(v.money(0, 1e7), credit_limit, "credit limit")
        if apr is not None:
            upd["apr_pct"] = _opt(v.num(0, 100), apr, "APR %")
        if due_day is not None:
            upd["due_day"] = _opt(v.integer(1, 31), due_day, "due day")
        if min_payment is not None:
            upd["min_payment"] = _opt(v.money(0, 1e7), min_payment, "minimum payment")
        if death_benefit is not None:
            upd["death_benefit"] = _opt(v.money(0, 1e9), death_benefit, "death benefit")
        if premium is not None:
            upd["premium"] = _opt(v.money(0, 1e6), premium, "premium a month")
        owners_now = upd.get("owners", row["owners"])
        if upd.get("ownership", row["ownership"]) == "joint" and len([p for p in (owners_now or "").split(",") if p.strip()]) < 2:
            raise EditError("a joint account needs two owners (type them like: Marcus, Elena)")
        upd = {k: x for k, x in upd.items() if x != row[k]}
        links = _link_details(con, row["id"], loan_id, holdings)
        if value is not None and str(value).strip():
            sub = upd.get("subtype", row["subtype"])
            if AT.group_of(sub) != "property":
                raise EditError("a value by hand is only for a home, a vehicle or other property")
            worth = _clean(v.money(0, 1e10), value, "value")
            day = dates.today().isoformat()
            old = con.execute("SELECT balance FROM account_balances WHERE account_id=? AND kind='estimate' "
                              "ORDER BY as_of DESC LIMIT 1", (row["id"],)).fetchone()
            if not old or old[0] != worth:
                con.execute("INSERT INTO account_balances(account_id, as_of, balance, kind) VALUES (?,?,?,'estimate') "
                            "ON CONFLICT(account_id, as_of, kind) DO UPDATE SET balance=excluded.balance",
                            (row["id"], day, worth))
                links.append("value")
        if not upd and not links:
            return "Nothing changed."
        if upd:
            con.execute(f"UPDATE accounts SET {', '.join(k + '=?' for k in upd)} WHERE id=?", (*upd.values(), row["id"]))
        _log(actor, "account_update", f"id={row['id']} fields={','.join(list(upd) + links)}")
    return f"Saved {upd.get('name', row['name'])}."


def _link_details(con, acct_id, loan_id, holdings):
    """Point one loan row and a set of investments rows at this account. -> the names of what changed."""
    changed = []
    if loan_id is not None:
        lid = int(loan_id) if str(loan_id).strip() else None
        if lid is not None:
            r = con.execute("SELECT account_id FROM loans WHERE id=?", (lid,)).fetchone()
            if not r:
                raise EditError("no such loan")
            if r[0] not in (None, acct_id):
                raise EditError("that loan already belongs to another account")
        now = [x for (x,) in con.execute("SELECT id FROM loans WHERE account_id=?", (acct_id,))]
        if now != ([lid] if lid else []):
            con.execute("UPDATE loans SET account_id=NULL WHERE account_id=?", (acct_id,))
            if lid:
                con.execute("UPDATE loans SET account_id=? WHERE id=?", (acct_id, lid))
            changed.append("loan")
    if holdings is not None:
        want = {int(h) for h in holdings if str(h).strip()}
        for h in want:
            r = con.execute("SELECT account_id FROM investments WHERE id=?", (h,)).fetchone()
            if not r:
                raise EditError("no such holding")
            if r[0] not in (None, acct_id):
                raise EditError("that holding already belongs to another account")
        now = {x for (x,) in con.execute("SELECT id FROM investments WHERE account_id=?", (acct_id,))}
        if now != want:
            con.execute("UPDATE investments SET account_id=NULL WHERE account_id=?", (acct_id,))
            con.executemany("UPDATE investments SET account_id=? WHERE id=?", [(acct_id, h) for h in want])
            changed.append("holdings")
    return changed


def _account_tables(con):
    """Every table with an account_id column (found at run time, so a later migration's table is merged too)."""
    tables = [t for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    return [t for t in tables if t != "accounts" and "account_id" in {r[1] for r in con.execute(f"PRAGMA table_info({t})")}]


@edits
def account_merge(actor, keep_id, drop_id):
    """Two rows that are the same bank account (a statement import and bank sync, say): every transaction, balance
    and link of `drop_id` moves to `keep_id`, blanks of the kept row are filled from the other (last4, bank sync link,
    bank, owners, card fields), then the emptied row is removed. A line both rows already have (same ref, or a balance
    on the same day) is kept once. Logged by ids."""
    _adult(actor)
    keep_id, drop_id = int(keep_id), int(drop_id)
    if keep_id == drop_id:
        raise EditError("pick a different account to merge")
    with _con() as con:
        con.row_factory = sqlite3.Row
        keep = con.execute("SELECT * FROM accounts WHERE id=?", (keep_id,)).fetchone()
        drop = con.execute("SELECT * FROM accounts WHERE id=?", (drop_id,)).fetchone()
        if not keep or not drop:
            raise EditError("no such account")
        if keep["type"] != drop["type"]:
            raise EditError(f"{keep['name']} is {keep['type']} and {drop['name']} is {drop['type']}: "
                            "change one so both are the same kind first")
        if keep["last4"] and drop["last4"] and keep["last4"] != drop["last4"]:
            raise EditError(f"they end in different numbers ({keep['last4']} and {drop['last4']}), so they are not the same account")
        moved, dropped = 0, 0
        for t in _account_tables(con):
            if t == "transactions":
                # same ref on both = the same line: keep the kept account's copy
                dropped += con.execute(
                    "DELETE FROM transactions WHERE account_id=? AND COALESCE(ref,'')!='' AND ref IN "
                    "(SELECT ref FROM transactions WHERE account_id=? AND COALESCE(ref,'')!='')", (drop_id, keep_id)).rowcount
            cur = con.execute(f"UPDATE OR IGNORE {t} SET account_id=? WHERE account_id=?", (keep_id, drop_id))
            moved += cur.rowcount
            left = con.execute(f"DELETE FROM {t} WHERE account_id=?", (drop_id,)).rowcount  # unique clashes = repeats
            dropped += left
        fill = {k: drop[k] for k in ("last4", "simplefin_id", "institution", "owners", "owner", "credit_limit", "apr_pct",
                                      "due_day", "min_payment") if k in keep.keys() and not keep[k] and drop[k]}
        con.execute("DELETE FROM accounts WHERE id=?", (drop_id,))
        if fill:
            con.execute(f"UPDATE accounts SET {', '.join(k + '=?' for k in fill)} WHERE id=?", (*fill.values(), keep_id))
        _log(actor, "account_merge", f"keep={keep_id} drop={drop_id} moved={moved} repeats={dropped}")
    return (f"Merged {drop['name']} into {keep['name']}: {moved} line(s) moved"
            + (f", {dropped} repeat(s) kept once" if dropped else "") + ".")


@edits
def recurring_done(actor, item_id, when=None, provider=None):
    """Record that a checkup or home task was done (the same as `data/recurring.py done`)."""
    _adult(actor)
    today = dates.today().isoformat()
    day = _opt(v.iso_date, when, "date") or today
    if day > today:
        raise EditError("date: it can not be in the future")
    provider = _opt(v.text(80), provider, "where / who")
    with _con() as con:
        r = con.execute("SELECT id, name, who FROM recurring_items WHERE id=? AND active=1", (int(item_id),)).fetchone()
        if not r:
            raise EditError("that item no longer exists")
        con.execute("UPDATE recurring_items SET last_done=?, provider=COALESCE(?, provider) WHERE id=?", (day, provider, r[0]))
        con.execute("INSERT INTO recurring_log(item_id, done_date, provider) VALUES (?,?,?)", (r[0], day, provider))
        _log(actor, "recurring_done", f"id={r[0]}")
    return f"Recorded: {r[1]} ({r[2]}) on {day}."


@edits
def seasonal_done(actor, task_id, when=None, place=None):
    """Log a seasonal task as done (the same as `data/seasonal.py done`)."""
    _adult(actor)
    today = dates.today().isoformat()
    day = _opt(v.iso_date, when, "date") or today
    if day > today:
        raise EditError("date: it can not be in the future")
    place = _opt(v.text(80), place, "where")
    with _con() as con:
        r = con.execute("SELECT id, name FROM seasonal_tasks WHERE id=? AND active=1", (int(task_id),)).fetchone()
        if not r:
            raise EditError("that task no longer exists")
        con.execute("INSERT INTO seasonal_log(task_id, done_date, place) VALUES (?,?,?)", (r[0], day, place))
        _log(actor, "seasonal_done", f"id={r[0]}")
    return f"Logged: {r[1]} on {day}."


@edits
def recurring_stop(actor, item_id):
    """'Not ours': stop tracking a checkup or home task (active=0; its history stays)."""
    _adult(actor)
    with _con() as con:
        r = con.execute("SELECT id, name, who FROM recurring_items WHERE id=? AND active=1", (int(item_id),)).fetchone()
        if not r:
            raise EditError("that item no longer exists")
        con.execute("UPDATE recurring_items SET active=0 WHERE id=?", (r[0],))
        _log(actor, "recurring_stop", f"id={r[0]}")
    return f"Stopped tracking {r[1]}" + (f" ({r[2]})." if r[2] else ".")
