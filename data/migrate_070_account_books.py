"""Apply migration 070 to data/family.db (idempotent): accounts as books (PLAN_money_books slice 1).

accounts.subtype          detailed type (account_types.SUBTYPES: checking, money_market, credit_card, 529, mortgage ...);
                          accounts.type stays the coarse one the older code reads and follows the subtype on every save
accounts.subtype_locked   1 = picked by a person; bank sync never guesses it again
accounts.institution      the bank's name (SimpleFIN `org`, or typed)
accounts.ownership        individual | joint
accounts.owners           people as typed, comma separated ("Marcus, Elena"); `owner` stays for the card member logic
accounts.closed_on        ISO date the account was closed (NULL = open); closed accounts leave the totals
accounts.credit_limit, accounts.apr_pct, accounts.due_day (1-31), accounts.min_payment   cards and loans
accounts.sort             display order inside its group (NULL = by name)
loans.account_id, investments.account_id   the account this loan / holding row describes (linked in a later slice)

Existing rows get a subtype from their coarse type, improved by a name guess that agrees with it (account_types.resolve),
and owners = owner.
"""
import sqlite3

import paths  # noqa: E402
import account_types as AT  # noqa: E402

COLUMNS = (("subtype", "TEXT"), ("subtype_locked", "INTEGER NOT NULL DEFAULT 0"), ("institution", "TEXT"),
           ("ownership", "TEXT NOT NULL DEFAULT 'individual'"), ("owners", "TEXT"), ("closed_on", "TEXT"),
           ("credit_limit", "REAL"), ("apr_pct", "REAL"), ("due_day", "INTEGER"), ("min_payment", "REAL"),
           ("sort", "INTEGER"))

c = sqlite3.connect(paths.DB)
have = {r[1] for r in c.execute("PRAGMA table_info(accounts)")}
if have:
    for col, decl in COLUMNS:
        if col not in have:
            c.execute(f"ALTER TABLE accounts ADD COLUMN {col} {decl}")
    owner_col = "owner" in have
    for rid, name, typ, owner, sub, owners in c.execute(
            f"SELECT id, name, type, {'owner' if owner_col else 'NULL'}, subtype, owners FROM accounts").fetchall():
        upd = {}
        if not sub:
            upd["subtype"] = AT.resolve(typ, name)
        if not owners and owner:
            upd["owners"] = owner
        if upd:
            c.execute(f"UPDATE accounts SET {', '.join(k + '=?' for k in upd)} WHERE id=?", (*upd.values(), rid))
for table in ("loans", "investments"):
    cols = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
    if cols and "account_id" not in cols:
        c.execute(f"ALTER TABLE {table} ADD COLUMN account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL")
c.commit()
print("migration 070 ok")
