"""How a category rule is matched to a transaction description (shared by apply_rules.py, audit_fix.py and the Cards page).

A rule pattern is an SQL LIKE pattern on UPPER(description). Card statements put a wallet or processor tag in front of
the merchant ("AplPay SUNOCO ...", "TST* YOUNG CHAM...", "SQ *TASTEFUL ...") that would stop a pattern such as
"SUNOCO%" from matching, so a rule is tried on the description as printed AND with those tags taken off.
"""
import re

TAGS = re.compile(r"^(?:(?:APLPAY|APPLE PAY|GOOGLE PAY|GPAY|TST\s*\*|SQ\s*\*|PAYPAL\s*\*|PP\s*\*|SP\s*\*|PT\s*\*)\s*)+")
CARD_TAIL = re.compile(r"\s*\((?:CARD\s*)?X?\d{3,4}\)\s*$")
# what a deposit is (Finance > Deposits, edit_actions.category_rule_add): txn_type -> (default category, what a person reads)
DEPOSIT_KINDS = {"income": ("salary", "Income (pay, salary)"), "interest": ("interest", "Interest"),
                 "transfer": ("transfer", "Own money moved between accounts"),
                 "investment_transfer": ("investing", "Money back from investments (TreasuryDirect, brokerage)"),
                 "tax": ("tax refund", "Tax refund"), "spend": ("refund", "Refund (lowers spending)")}


def clean(description):
    """The description in capitals without the wallet / processor tag in front and the card note (last four digits in brackets) after."""
    s = " ".join(str(description or "").upper().split())
    s = TAGS.sub("", s)
    return CARD_TAIL.sub("", s).strip()


def texts(description):
    """The strings a rule is tried on: as printed, then cleaned (when that differs)."""
    raw = " ".join(str(description or "").upper().split())
    c = clean(description)
    return [raw] if c in ("", raw) else [raw, c]


def first_rule(con, description, columns="category, payee_type, payee"):
    """The first rule (lowest priority number) matching the description, as a row of `columns`, or None."""
    t = texts(description)
    where = " OR ".join("? LIKE pattern" for _ in t)
    return con.execute(f"SELECT {columns} FROM category_rules WHERE {where} ORDER BY priority, id LIMIT 1", t).fetchone()


def reapply(con, pattern, only=None):
    """Lines whose description matches `pattern` take what the rules say now (the first matching rule's category, type and
    payee; nothing left = category and type cleared), even when they already had a category: used after a family rule is
    added or changed and after a starter rule is dropped. `only` = (category, txn_type): touch just the lines that still
    carry that pair (what a dropped rule gave them). A line a person changed by hand (`manual`) is never touched.
    -> number of lines changed."""
    n = 0
    for tid, desc, cat, typ, payee in con.execute("SELECT id, description, category, txn_type, payee FROM transactions "
                                                  "WHERE manual=0").fetchall():
        if not any(con.execute("SELECT ? LIKE ?", (t, pattern)).fetchone()[0] for t in texts(desc)):
            continue
        if only is not None and (cat, typ) != tuple(only):
            continue
        r = first_rule(con, desc)
        new = (r[0], r[1], r[2] or payee) if r else (None, None, payee)
        if new != (cat, typ, payee):
            con.execute("UPDATE transactions SET category=?, txn_type=?, payee=? WHERE id=?", (*new, tid))
            n += 1
    return n


def merchant_key(description, words=3):
    """A short merchant name for a rule: the cleaned description up to the first word with a digit, # or *, at most
    `words` words ("ACME PHARMACY #00996 TOWN NY" -> "ACME PHARMACY")."""
    out = []
    for w in clean(description).split():
        if any(ch.isdigit() or ch in "#*" for ch in w) or len(out) >= words:
            break
        out.append(w)
    return " ".join(out)


def pair_transfers(con, days=3):
    """Money moved between two of the family's own bank accounts shows as a payment out of one and a deposit into the other
    (the second line often carries only a name, so no rule can know). A line out and a line in of the same cents on two
    different checking / savings / investment accounts within `days` days, each the only candidate for the other, are
    both marked as a transfer (category filled in where empty), so neither counts as spending or as income.
    Lines that already have another type are left alone. -> number of pairs."""
    rows = con.execute(
        "SELECT t.id, t.txn_date, t.amount, t.txn_type, t.account_id, t.category FROM transactions t JOIN accounts a ON a.id=t.account_id "
        "WHERE a.type IN ('checking','savings','investment') AND (t.txn_type IS NULL OR t.txn_type='transfer') AND t.amount != 0 AND t.manual=0").fetchall()
    import datetime as dt
    day = {}
    for r in rows:
        try:
            day[r[0]] = dt.date.fromisoformat(str(r[1])[:10])
        except ValueError:
            pass
    out = [r for r in rows if r[2] < 0 and r[0] in day]
    inn = [r for r in rows if r[2] > 0 and r[0] in day]

    def near(a, b):
        return (a[4] != b[4] and round(a[2] * 100) == -round(b[2] * 100) and abs((day[a[0]] - day[b[0]]).days) <= days
                and not (a[3] == "transfer" and b[3] == "transfer"))
    n = 0
    for o in out:
        ins = [i for i in inn if near(o, i)]
        if len(ins) != 1 or len([x for x in out if near(x, ins[0])]) != 1:
            continue
        for r in (o, ins[0]):
            con.execute("UPDATE transactions SET txn_type='transfer', category=CASE WHEN TRIM(COALESCE(category,''))='' "
                        "THEN 'transfer' ELSE category END WHERE id=?", (r[0],))
        n += 1
    return n
