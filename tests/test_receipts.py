"""Receipts (migration 032 + data/receipts.py): matching to charges (exact amount, merchant word, possible tip, ties
left for a person), manual link / unlink / ignore that the matcher respects, receipts from intake and the review
queue, matching again after a statement import, and the Finance > Receipts tab."""
import pytest

from conftest import db, q, run

ADULT, KID = {"name": "Alex", "role": "adult"}, {"name": "Sam", "role": "limited"}


@pytest.fixture(scope="module")
def R(root, modules):
    return modules("receipts")


@pytest.fixture(scope="module")
def card(root):
    con = db(root)
    con.execute("INSERT INTO accounts(name, type, last4) VALUES ('Rcpt Visa', 'credit', '4242')")
    aid = con.execute("SELECT id FROM accounts WHERE name='Rcpt Visa'").fetchone()[0]
    for d, desc, amt in [("2026-09-03", "TARGET 00012345 MAPLE GROVE", -54.21),
                         ("2026-09-05", "OLIVE GARDEN #1234", -61.80),      # 51.50 + tip
                         ("2026-09-06", "SHELL OIL 5544", -40.00),
                         ("2026-09-06", "SHELL OIL 7788", -40.00),
                         ("2026-09-10", "HOME DEPOT 1234", -19.99),
                         ("2026-09-20", "PAYMENT THANK YOU", 500.00)]:
        con.execute("INSERT INTO transactions(account_id, txn_date, description, amount) VALUES (?,?,?,?)", (aid, d, desc, amt))
    con.commit()
    con.close()
    return aid


def _one(root, rid):
    return q(root, "SELECT transaction_id, match_confidence, status, auto FROM receipts WHERE id=?", rid)[0]


def test_exact_amount_and_merchant_is_high(root, R, card):
    con = db(root)
    try:
        rid = R.add(con, "Target", "2026-09-02", "54.21")
        con.commit()
    finally:
        con.close()
    txn = q(root, "SELECT id FROM transactions WHERE description LIKE 'TARGET%'")[0][0]
    assert _one(root, rid) == (txn, "high", "matched", 1)


def test_tip_is_low_and_ties_wait_for_a_person(root, R, card):
    con = db(root)
    try:
        tip = R.add(con, "Olive Garden", "2026-09-04", 51.50)
        tie = R.add(con, "Gas station", "2026-09-06", 40)
        late = R.add(con, "Corner Bakery", "2026-09-01", 12.00)
        con.commit()
        assert _one(root, tip)[1:3] == ("low", "matched")
        assert "possible tip" in R.get(con, tip)["match_note"]
        assert _one(root, tie)[:3] == (None, "none", "open") and "2 charges fit equally" in R.get(con, tie)["match_note"]
        assert _one(root, late)[:3] == (None, "none", "open")
        assert len(R.candidates(con, R.get(con, tie))) == 2
    finally:
        con.close()


def test_manual_link_unlink_ignore_are_respected(root, R, card, modules):
    ea = modules("edit_actions")
    rid = q(root, "SELECT id FROM receipts WHERE merchant='Gas station'")[0][0]
    shell = q(root, "SELECT id FROM transactions WHERE description='SHELL OIL 7788'")[0][0]
    assert not ea.receipt_link(KID, rid, shell)[0]
    ok, msg = ea.receipt_link(ADULT, rid, shell)
    assert ok, msg
    assert _one(root, rid) == (shell, "manual", "matched", 0)
    other = q(root, "SELECT id FROM receipts WHERE merchant='Target'")[0][0]
    ok, msg = ea.receipt_link(ADULT, other, shell)
    assert not ok and "already linked" in msg
    ok, _ = ea.receipt_unlink(ADULT, rid)
    assert ok and _one(root, rid) == (None, "none", "open", 0)
    con = db(root)
    try:
        R.match(con)
        con.commit()
    finally:
        con.close()
    assert _one(root, rid)[0] is None, "the matcher leaves a receipt a person unlinked alone"
    ok, _ = ea.receipt_ignore(ADULT, rid)
    assert ok and _one(root, rid)[2] == "ignored"
    assert "Gas station" not in (root / "logs" / "edits.log").read_text(encoding="utf-8")


def test_receipt_filed_from_review_queue_becomes_a_receipt(root, card, modules):
    ea = modules("edit_actions")
    (root / "inbox" / "needs_review").mkdir(parents=True, exist_ok=True)
    f = root / "inbox" / "needs_review" / "IMG_0042.jpg"
    f.write_bytes(b"\xff\xd8\xff\xe0 not really a jpeg")
    con = db(root)
    con.execute("INSERT INTO review_queue(path, reason, created_at) VALUES (?, 'picture', '2026-09-11')",
                ("inbox/needs_review/IMG_0042.jpg",))
    con.commit()
    rv = con.execute("SELECT max(id) FROM review_queue").fetchone()[0]
    con.close()
    ok, msg = ea.review_file(ADULT, rv, "receipt", "Home Depot", "2026-09-09", 19.99)
    assert ok, msg
    r = q(root, "SELECT r.match_confidence, d.doc_type FROM receipts r JOIN documents d ON d.id=r.document_id "
                "WHERE r.merchant='Home Depot'")
    assert r == [("high", "receipt")]


def test_statement_import_matches_waiting_receipts(root, card, tmp_path):
    r = run(["data/receipts.py", "add", "Corner Bakery Cafe", "2026-10-01", "8.75"], root)
    assert r.returncode == 0 and "no charge yet" in r.stdout, r.stdout + r.stderr
    f = tmp_path / "oct.csv"
    f.write_text("Date,Description,Amount\n10/02/2026,CORNER BAKERY 0042,8.75\n", encoding="utf-8")
    r = run(["data/import_statement.py", str(f), "--account", "4242"], root)
    assert r.returncode == 0, r.stderr[-300:]
    assert q(root, "SELECT match_confidence FROM receipts WHERE merchant='Corner Bakery Cafe'") == [("high",)]
    out = run(["data/receipts.py", "list"], root).stdout
    assert "Corner Bakery Cafe" in out and "(high)" in out


def test_bad_input_refused(root, R):
    con = db(root)
    try:
        for args in (("", "2026-09-01", 5), ("X", "09/01/2026", 5), ("X", "2026-09-01", 0), ("X", "2026-09-01", 5, "4242424242424242")):
            with pytest.raises(ValueError):
                R.add(con, *args)
    finally:
        con.rollback()
        con.close()


