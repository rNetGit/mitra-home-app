"""Phone bills per line without AI (data/mobile_bill.py): the per-line summary and details of a carrier bill, the
section / line / bill checks to the cent, the equal split of account-wide credits in whole cents, the call pages that are
never read, idempotent storing, intake routing before any AI call, monthly report, purge and the Records tab.
The fixture is made-up text in the layout of a Verizon bill (no real names or numbers)."""
import os
import sqlite3

import pytest

from conftest import db, q, run

BILL = """PO BOX 1
SAMPLE CITY, NY 10000
Questions about your bill?
verizon.com/support
Total Amount Due
$129.00
Bill date March 24, 2027
Account number 111222333-00001
Invoice number 1234567890
Snapshot of your bill
Total due on Apr 16 $129.00
Account: 111222333-00001
Invoice: 1234567890
Billing period: Feb 25  - Mar 24, 2027

3
Your March bill is $129.00
Bill summary by line
Account-wide charges & credits -$10.00
Alex Sample $61.00
Example Phone One  (555-010-0101)
Jamie Sample $56.00
Example Phone Two  (555-010-0102)
Alex Sample $22.00
Example Watch  (555-010-0103)
Total: $129.00

4
Account: 111222333-00001
Invoice: 1234567890
Billing period: Feb 25  - Mar 24, 2027
Charges by line details
Account-wide charges & credits -$10.00
One-time charges & credits -$10.00
Courtesy credit -$10.00
Alex Sample $61.00
Example Phone One
555-010-0101
Plan $45.00
Unlimited Plus $55.00
Jan 25 - Feb 24
Auto Pay discount -$10.00
Devices $10.00
EX1 256 $30.00
Payment 2 of 36 ($1,000.00 remaining)
Device Promotional Credit -$20.00
Credit 2 of 36
Surcharges $4.00
Federal Charge $3.00
Admin Charge $1.00
Taxes & gov fees $2.00
State Tax $1.50
County Tax $0.50
Plan
Plans are billed a month in advance.
Includes the $10.00/month discount on

5
Charges by line details (continued)
Account: 111222333-00001
Invoice: 1234567890
Billing period: Feb 25  - Mar 24, 2027
Jamie Sample $56.00
Example Phone Two
555-010-0102
Plan $40.00
Unlimited Plus $50.00
Auto Pay discount -$10.00
Services & perks $10.00
Streaming bundle $10.00
Surcharges $4.00
Federal Charge $3.00
Admin Charge $1.00
Taxes & gov fees $2.00
State Tax $1.50
County Tax $0.50
Alex Sample $22.00
Example Watch
555-010-0103
Plan $20.00
Watch line $20.00
Surcharges $1.50
Federal Charge $1.00
Admin Charge $0.50
Taxes & gov fees $0.50
State Tax $0.50

9
Account: 111222333-00001
Invoice: 1234567890
Billing period: Feb 25  - Mar 24, 2027
Talk activity
Alex Sample
555-010-0101
Example Phone One
Date Time Number Origination Destination Min. Airtime Charges LD/Other Charges Total
Mar 1 10:32 PM 555-010-0199 Sample City, NY Incoming, CL 1 -- -- --
"""


@pytest.fixture(scope="module")
def MB(root, modules):
    return modules("mobile_bill")


def _no_ai_env():
    return {k: v for k, v in os.environ.items() if "API_KEY" not in k}


def test_reads_lines_sections_and_the_equal_split(MB):
    r = MB.read(BILL)
    assert r["carrier"] == "Verizon" and r["invoice"] == "1234567890" and r["account_last4"] == "2333"
    assert str(r["bill_date"]) == "2027-03-24" and str(r["due_date"]) == "2027-04-16"
    assert (str(r["period_start"]), str(r["period_end"])) == ("2027-02-25", "2027-03-24")
    assert r["bill_total"] == 129.0 and r["total_due"] == 129.0 and r["account_wide"] == -10.0
    a, j, w = r["lines"]
    assert (a["person"], a["phone_last4"], a["line_total"]) == ("Alex Sample", "0101", 61.0)
    assert (a["plan"], a["devices"], a["surcharges"], a["taxes"], a["perks"]) == (45.0, 10.0, 4.0, 2.0, 0.0)
    assert j["perks"] == 10.0 and w["plan"] == 20.0
    assert [x["account_share"] for x in r["lines"]] == [-3.34, -3.33, -3.33]
    assert [x["net"] for x in r["lines"]] == [57.66, 52.67, 18.67]
    assert round(sum(x["net"] for x in r["lines"]), 2) == r["bill_total"]
    assert [i["label"] for i in r["account_items"]] == ["Courtesy credit"]
    assert not any("Mar 1" in i["label"] for ln in r["lines"] for i in ln["items"]), "call lists are never read"


def test_split_is_exact_in_cents(MB):
    assert MB.split_account_wide(-10.0, 3) == [-3.34, -3.33, -3.33]
    assert MB.split_account_wide(5.0, 2) == [2.5, 2.5]
    assert MB.split_account_wide(0.01, 3) == [0.01, 0.0, 0.0]
    assert MB.split_account_wide(0, 4) == [0, 0, 0, 0]
    for amt, n in ((-25.0, 5), (-17.77, 7), (13.01, 6)):
        assert round(sum(MB.split_account_wide(amt, n)), 2) == amt


def test_a_figure_that_does_not_add_up_is_refused(MB):
    bad = BILL.replace("Plan $45.00\nUnlimited Plus $55.00", "Plan $46.00\nUnlimited Plus $55.00")
    with pytest.raises(MB.BillError):
        MB.read(bad)
    r = MB.read(bad, strict=False)
    assert r["verified"] is False and r["problems"]
    with pytest.raises(MB.BillError):
        MB.store(sqlite3.connect(":memory:"), r)
    with pytest.raises(MB.BillError):
        MB.read(BILL.replace("Total: $129.00", "Total: $130.00"))
    assert not MB.looks_like("Bill summary by line only")


def test_cli_check_and_store_are_idempotent(root, tmp_path):
    f = tmp_path / "march.txt"
    f.write_text(BILL, encoding="utf-8")
    r = run(["data/mobile_bill.py", "check", str(f)], root)
    assert r.returncode == 0 and "everything adds up" in r.stdout and "Alex Sample" in r.stdout, r.stderr[-300:]
    assert q(root, "SELECT count(*) FROM mobile_bills") == [(0,)]
    for _ in range(2):
        r = run(["data/mobile_bill.py", str(f)], root)
        assert r.returncode == 0 and "stored as phone bill" in r.stdout, r.stderr[-300:]
    assert q(root, "SELECT count(*) FROM mobile_bills") == [(1,)]
    assert q(root, "SELECT count(*) FROM mobile_bill_lines") == [(3,)]
    assert q(root, "SELECT round(sum(net), 2) FROM mobile_bill_lines") == [(129.0,)]
    assert q(root, "SELECT count(*) FROM mobile_bill_items WHERE line_id IS NULL") == [(1,)]
    assert q(root, "SELECT count(*) FROM mobile_bill_items WHERE label LIKE '%Mar 1%' OR label LIKE '%Incoming%'") == [(0,)]


def test_months_groups_two_lines_of_one_person(root, modules):
    MB = modules("mobile_bill")
    con = db(root)
    rows = MB.months(con, 12)
    con.close()
    by = {r["person"]: r for r in rows}
    assert by["Alex Sample"]["lines"] == 2 and by["Alex Sample"]["net"] == 76.33
    assert by["Jamie Sample"]["net"] == 52.67 and {r["month"] for r in rows} == {"2027-03"}


def test_monthly_report_has_a_phone_bills_section(root):
    r = run(["data/make_report.py", "monthly", "2027-03"], root)
    assert r.returncode == 0, r.stderr[-300:]
    text = (root / "reports" / "2027-03_monthly.md").read_text(encoding="utf-8")
    assert "## Phone bills" in text and "| Jamie Sample | 1 |" in text and "52.67" in text


def test_intake_files_a_phone_bill_without_any_ai(root):
    con = sqlite3.connect(root / "data" / "family.db")
    con.execute("DELETE FROM mobile_bill_items")
    con.execute("DELETE FROM mobile_bill_lines")
    con.execute("DELETE FROM mobile_bills")
    con.commit()
    con.close()
    (root / "inbox").mkdir(exist_ok=True)
    (root / "inbox" / "MyBill_03.24.2027.txt").write_text(BILL, encoding="utf-8")
    r = run(["data/ai_intake.py"], root, env=_no_ai_env())
    assert "phone bill: 3 lines" in r.stdout, r.stdout + r.stderr[-300:]
    doc = q(root, "SELECT id, vendor, doc_date FROM documents ORDER BY id DESC LIMIT 1")[0]
    assert doc[1:] == ("Verizon", "2027-03-24")
    assert q(root, "SELECT amount, due_date FROM bills WHERE document_id=?", doc[0]) == [(129.0, "2027-04-16")]
    assert q(root, "SELECT document_id FROM mobile_bills") == [(doc[0],)]
    assert q(root, "SELECT count(*) FROM mobile_bill_lines") == [(3,)]


def test_a_phone_bill_that_does_not_add_up_goes_to_review(root):
    bad = BILL.replace("Total: $129.00", "Total: $131.00").replace("1234567890", "9999999999")
    (root / "inbox" / "MyBill_bad.txt").write_text(bad, encoding="utf-8")
    r = run(["data/ai_intake.py"], root, env=_no_ai_env())
    assert "review" in r.stdout and "MyBill_bad.txt" in r.stdout, r.stdout
    assert q(root, "SELECT count(*) FROM review_queue WHERE reason LIKE 'phone bill not read per line%'") == [(1,)]
    assert q(root, "SELECT count(*) FROM mobile_bills") == [(1,)]
    assert (root / "inbox" / "needs_review" / "MyBill_bad.txt").exists()


def test_purge_person_removes_their_lines(root):
    con = sqlite3.connect(root / "data" / "family.db")  # the printed name belongs to the member Sam
    con.execute("UPDATE mobile_bill_lines SET member='Sam' WHERE person='Jamie Sample'")
    con.commit()
    con.close()
    r = run(["data/purge.py", "person", "Sam", "--yes"], root)
    assert r.returncode == 0, r.stdout[-300:] + r.stderr[-300:]
    assert q(root, "SELECT count(*) FROM mobile_bill_lines WHERE person='Jamie Sample'") == [(0,)]
    assert q(root, "SELECT count(*) FROM mobile_bill_lines") == [(2,)]
    assert q(root, "SELECT count(*) FROM mobile_bill_items WHERE line_id IS NOT NULL AND line_id NOT IN "
                   "(SELECT id FROM mobile_bill_lines)") == [(0,)]


