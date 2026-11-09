"""0.58.0 Inbox producers (data/proposals.py): policy renewals, price spikes (subscriptions, policy premiums) and Amazon
charges / orders without a match. They write only queue entries: every option settles the queue item and changes no
record; items disappear by themselves when the records no longer report them."""
import datetime as D
import json

import pytest

from conftest import db, q, read_family, write_family

ADULT = {"name": "Alex", "role": "adult"}
CHILD = {"name": "Sam", "role": "child"}
TODAY = D.date.today()


def iso(n):
    return (TODAY + D.timedelta(days=n)).isoformat()


@pytest.fixture(scope="module")
def pr(root, modules):
    return modules("proposals")


def _sync(pr):
    return pr.sync(today=TODAY)


def _open(pr, root, source, like=""):
    con = db(root)
    try:
        return [r for r in pr.items(con) if r["source"] == source and like in r["summary"]]
    finally:
        con.close()


def _exec(root, sql, *args):
    con = db(root)
    cur = con.execute(sql, args)
    con.commit()
    last = cur.lastrowid
    con.close()
    return last


@pytest.fixture(scope="module")
def policies(root):
    old = _exec(root, "INSERT INTO policies(kind, carrier, policy_last4, term_start, term_end, premium_total, status) "
                      "VALUES ('auto', 'Acme Mutual', '4321', ?, ?, 1000, 'replaced')", iso(-455), iso(-90))
    cur = _exec(root, "INSERT INTO policies(kind, carrier, policy_last4, term_start, term_end, premium_total, status, "
                      "prior_policy_id) VALUES ('auto', 'Acme Mutual', '4321', ?, ?, 1200, 'active', ?)", iso(-90), iso(30), old)
    far = _exec(root, "INSERT INTO policies(kind, carrier, policy_last4, term_start, term_end, premium_total, status) "
                      "VALUES ('home', 'Roof Re', '9876', ?, ?, 900, 'active')", iso(-100), iso(200))
    return {"old": old, "cur": cur, "far": far}


def test_a_policy_ending_soon_with_no_newer_term_asks_to_file_the_renewal(root, pr, policies):
    _sync(pr)
    items = _open(pr, root, "renewal")
    assert [i["summary"] for i in items] == ["Your Acme Mutual auto policy ending 4321 runs out on "
                                             f"{D.date.fromisoformat(iso(30)):%b %d} (30 days)"], "far-off terms are left alone"
    it = items[0]
    assert it["kind"] == "decision" and "$1,200.00" in it["detail"] and "+20.0%" in it["detail"]
    assert it["ref_table"] == "policies" and it["ref_id"] == policies["cur"]
    assert list(it["options"]) == ["reviewed", "later", "dismiss"]
    assert not pr.decide(CHILD, it["id"], "reviewed")[0]
    before = q(root, "SELECT COUNT(*), SUM(premium_total) FROM policies")
    ok, msg = pr.decide(ADULT, it["id"], "later", today=TODAY)
    assert ok and msg == "I will remind you in a week."
    assert q(root, "SELECT status, until FROM proposals WHERE id=?", it["id"]) == [("snoozed", iso(7))]
    assert q(root, "SELECT COUNT(*), SUM(premium_total) FROM policies") == before, "no record is changed"
    _sync(pr)
    assert q(root, "SELECT status FROM proposals WHERE id=?", it["id"]) == [("snoozed",)]
    pr.sync(today=TODAY + D.timedelta(days=8))
    assert q(root, "SELECT status FROM proposals WHERE id=?", it["id"]) == [("open",)], "comes back when the week is over"


def test_filing_the_next_term_makes_the_renewal_item_go_away(root, pr, policies):
    it = _open(pr, root, "renewal")[0]
    _exec(root, "INSERT INTO policies(kind, carrier, policy_last4, term_start, term_end, premium_total, status, prior_policy_id) "
                "VALUES ('auto', 'Acme Mutual', '4321', ?, ?, 1250, 'active', ?)", iso(30), iso(395), policies["cur"])
    _sync(pr)
    assert q(root, "SELECT status FROM proposals WHERE id=?", it["id"]) == [("expired",)]
    assert not _open(pr, root, "renewal")


def test_a_premium_that_went_up_ten_percent_is_a_price_spike(root, pr, policies):
    spikes = _open(pr, root, "price_rise", "premium")
    assert [s["summary"] for s in spikes] == ["The Acme Mutual auto premium went up 20% ($1,000.00 to $1,200.00)"]
    s = spikes[0]
    assert s["detail"].startswith("Worth a call to ask why?") and "4321" in s["detail"] and s["ref_id"] == policies["cur"]
    assert pr.decide(ADULT, s["id"], "ok")[0]
    _sync(pr)
    assert q(root, "SELECT status FROM proposals WHERE id=?", s["id"]) == [("done",)], "answered once, not asked again"
    assert q(root, "SELECT COUNT(*) FROM proposals WHERE dedupe_key LIKE 'price_rise:policy:%'") == [(1,)]


def test_a_smaller_rise_or_an_old_term_is_not_a_spike(root, pr):
    old = _exec(root, "INSERT INTO policies(kind, carrier, term_start, term_end, premium_total, status) "
                      "VALUES ('renters', 'Small Co', ?, ?, 100, 'replaced')", iso(-700), iso(-500))
    _exec(root, "INSERT INTO policies(kind, carrier, term_start, term_end, premium_total, status, prior_policy_id) "
                "VALUES ('renters', 'Small Co', ?, ?, 105, 'active', ?)", iso(-30), iso(300), old)
    older = _exec(root, "INSERT INTO policies(kind, carrier, term_start, term_end, premium_total, status) "
                        "VALUES ('umbrella', 'Big Co', ?, ?, 100, 'replaced')", iso(-900), iso(-700))
    _exec(root, "INSERT INTO policies(kind, carrier, term_start, term_end, premium_total, status, prior_policy_id) "
                "VALUES ('umbrella', 'Big Co', ?, ?, 200, 'active', ?)", iso(-500), iso(100), older)
    _sync(pr)
    assert not _open(pr, root, "price_rise", "Small Co") and not _open(pr, root, "price_rise", "Big Co")


def test_a_subscription_that_went_up_is_a_price_spike(root, pr):
    name = q(root, "SELECT name FROM subscriptions WHERE match_pattern='%STREAMCO%'")[0][0]
    acct = q(root, "SELECT account_id FROM transactions WHERE description LIKE '%STREAMCO%' LIMIT 1")[0][0]
    # after the newest seeded charge (the demo seed dates one on the 5th of this month, which is ahead of today until then)
    last = q(root, "SELECT MAX(txn_date) FROM transactions WHERE description LIKE '%STREAMCO%'")[0][0]
    _exec(root, "INSERT INTO transactions(account_id, txn_date, description, amount, category, txn_type) "
                "VALUES (?, ?, 'DEMO STREAMCO', -19.99, 'subscriptions', 'spend')", acct,
          (D.date.fromisoformat(last) + D.timedelta(days=1)).isoformat())
    _sync(pr)
    s = _open(pr, root, "price_rise", name)
    assert [x["summary"] for x in s] == [f"{name} went up (15.99 to 19.99)"], s
    assert s[0]["ref_table"] == "subscriptions" and json.loads(json.dumps(s[0]["payload"])) == {"payee": name}
    assert pr.decide(ADULT, s[0]["id"], "dismiss")[0]
    _sync(pr)
    assert q(root, "SELECT status FROM proposals WHERE id=?", s[0]["id"]) == [("dismissed",)]


def test_amazon_items_need_the_pack_and_three_unmatched(root, pr):
    acct = q(root, "SELECT id FROM accounts LIMIT 1")[0][0]
    for n in (40, 41, 42):
        _exec(root, "INSERT INTO transactions(account_id, txn_date, description, amount, category, txn_type) "
                    "VALUES (?, ?, 'AMAZON MKTPLACE PMTS', -20.0, 'shopping', 'spend')", acct, iso(-n))
    _sync(pr)
    assert not _open(pr, root, "amazon"), "pack off: nothing"
    fam = read_family(root)
    fam.setdefault("packs", {})["amazon"] = True
    write_family(root, fam)
    _sync(pr)
    ch = _open(pr, root, "amazon", "charges")
    assert [c["summary"] for c in ch] == ["3 Amazon charges ($60.00) have no order details"]
    assert "Prime fees" in ch[0]["detail"] and ch[0]["payload"] == {}
    assert list(ch[0]["options"]) == ["later", "dismiss"]
    assert not _open(pr, root, "amazon", "orders"), "no unmatched orders yet"
    for i, n in enumerate((50, 51)):
        _exec(root, "INSERT INTO amazon_orders(order_no, order_date, total, status, items) VALUES (?, ?, 33.0, 'delivered', 'x')",
              f"111-000000{i}-0000000", iso(-n))
    _sync(pr)
    assert not _open(pr, root, "amazon", "orders"), "two is below the bar"
    _exec(root, "INSERT INTO amazon_orders(order_no, order_date, total, status, items) VALUES ('111-0000009-0000000', ?, 12.5, 'delivered', 'y')",
          iso(-52))
    _exec(root, "INSERT INTO amazon_orders(order_no, order_date, total, status, items) VALUES ('111-0000008-0000000', ?, 9, 'refunded', 'z')",
          iso(-53))
    _sync(pr)
    od = _open(pr, root, "amazon", "orders")
    assert [o["summary"] for o in od] == ["3 Amazon orders ($78.50) have no card charge"], "refunded ones are not counted"
    ok, msg = pr.decide(ADULT, ch[0]["id"], "later", today=TODAY)
    assert ok and msg == "I will remind you in two weeks."
    assert q(root, "SELECT until FROM proposals WHERE id=?", ch[0]["id"]) == [(iso(14),)]
    assert pr.decide(ADULT, od[0]["id"], "dismiss")[0]
    assert q(root, "SELECT status FROM proposals WHERE id=?", od[0]["id"]) == [("dismissed",)]
    _exec(root, "UPDATE amazon_orders SET status='cancelled' WHERE order_no='111-0000009-0000000'")
    _sync(pr)
    assert q(root, "SELECT status FROM proposals WHERE id=?", od[0]["id"]) == [("dismissed",)], "a dismissed one stays dismissed"
    fam["packs"]["amazon"] = False
    write_family(root, fam)


def test_the_phone_bot_default_no_answer_covers_the_new_sources(root, modules):
    cc = modules("chat_core")
    assert cc.NO_CHOICE["renewal"] == "dismiss" and cc.NO_CHOICE["amazon"] == "dismiss"
    pr = modules("proposals")
    for src in ("renewal", "amazon", "price_rise"):
        assert cc.NO_CHOICE[src] in pr.OPTIONS[src]


def test_sync_stays_idempotent_with_the_new_producers(root, pr):
    first = _sync(pr)
    again = _sync(pr)
    assert again["added"] == 0 and again["expired"] == 0 and again["refreshed"] == 0 and again["open"] == first["open"]
