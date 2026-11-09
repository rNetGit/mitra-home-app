"""Statement layouts of the big US banks and card issuers, read without AI (data/pdf_statement.py): each fixture is
the text layer a statement of that layout gives (made-up names, numbers and lines; the layouts are kept neutral by
name). Each must find the account's last four, the period, every line with the right sign, and add up to the printed
balances. A layout the reader cannot check must be refused (verified not True), never imported with wrong lines."""
import pytest

from conftest import db

# key: (account type, last4, lines, text)
LAYOUTS = {
    "national_checking_a": ("checking", "9012", 3, """
Your Adv Plus Banking
for October 1, 2026 to October 31, 2026                      Account number: 1234 5678 9012
Account summary
Beginning balance on October 1, 2026                                   $1,234.56
Deposits and other additions                                             2,500.00
Withdrawals and other subtractions                                      -1,100.00
Checks                                                                      -0.00
Service fees                                                                -0.00
Ending balance on October 31, 2026                                     $2,634.56
Deposits and other additions
Date        Description                                                    Amount
10/03/26    EXAMPLE CORP DES:PAYROLL ID:XXXXX12345 INDN:SAMPLE PERSON CO ID:XXXXX12345 PPD    2,500.00
Total deposits and other additions                                     $2,500.00
Withdrawals and other subtractions
Date        Description                                                    Amount
10/05/26    CHECKCARD 1004 GROCERY MART ANYTOWN ST 24431066277100012345678    -100.00
10/15/26    ONLINE BANKING TRANSFER TO SAV 9876 CONFIRMATION# 1234567890     -1,000.00
Total withdrawals and other subtractions                              -$1,100.00
"""),
    "national_checking_b": ("checking", "6789", 4, """
TOTAL CHECKING
October 1, 2026 through October 31, 2026
Account Number: 000000123456789
CHECKING SUMMARY
                                   INSTANCES            AMOUNT
Beginning Balance                                    $1,000.00
Deposits and Additions                    1           2,500.00
ATM & Debit Card Withdrawals              2            -150.00
Electronic Withdrawals                    1            -500.00
Ending Balance                            4          $2,850.00
TRANSACTION DETAIL
DATE      DESCRIPTION                                          AMOUNT        BALANCE
          Beginning Balance                                                $1,000.00
10/03     Example Corp Payroll PPD ID: 1234567890            2,500.00       3,500.00
10/05     Card Purchase 10/04 Grocery Mart Anytown ST Card 1004 -100.00      3,400.00
10/07     Card Purchase 10/06 Gas Station Anytown ST Card 1004  -50.00       3,350.00
10/20     Zelle Payment To Sample Person 123456789            -500.00       2,850.00
          Ending Balance                                                   $2,850.00
"""),
    "national_card_b": ("credit", "1234", 3, """
ACCOUNT SUMMARY
Account Number: XXXX XXXX XXXX 1234
Previous Balance                         $500.00
Payment, Credits                        -$500.00
Purchases                               +$212.34
Cash Advances                              $0.00
Balance Transfers                          $0.00
Fees Charged                               $0.00
Interest Charged                           $0.00
New Balance                              $212.34
Opening/Closing Date                09/24/26 - 10/23/26
Credit Access Line                    $10,000
Payment Due Date:                      11/20/26
Minimum Payment Due:                    $40.00
ACCOUNT ACTIVITY
Date of
Transaction     Merchant Name or Transaction Description          $ Amount
PAYMENTS AND OTHER CREDITS
10/10           Payment Thank You-Mobile                           -500.00
PURCHASE
09/25           GROCERY MART ANYTOWN ST                             112.34
10/02           ONLINE BOOKS 800-555-0100 WA                        100.00
"""),
    "card_monthname_dates": ("credit", "4321", 3, """
Cashback Card | Visa Signature ending in 4321
Sep 25, 2026 - Oct 24, 2026 | 30 days in Billing Cycle
Payment Due Date Nov 20, 2026
New Balance $212.34
Minimum Payment Due $25.00
Account Summary
Previous Balance $500.00
Payments - $500.00
Other Credits - $0.00
Transactions + $212.34
Fees Charged + $0.00
Interest Charged + $0.00
New Balance = $212.34
Transactions
Trans Date Post Date Description Amount
Payments, Credits and Adjustments
Oct 10 Oct 10 MOBILE PYMT Authdate 10-Oct - $500.00
SAMPLE PERSON #4321: Transactions
Sep 26 Sep 27 GROCERY MART ANYTOWN ST $112.34
Oct 3 Oct 4 ONLINE BOOKS 800-555-0100 WA $100.00
"""),
    "regional_checking_dash_dates": ("checking", "9012", 3, """
Express Checking 123456789012
Statement period Sep 30, 2026 - Oct 31, 2026
Beginning balance 9-30-26 $1,000.00
Additions +2,500.00
Subtractions -650.00
Net fees and charges -0.00
Ending balance 10-31-26 $2,850.00
Additions
Deposits
Date Serial # Source
10-3 Direct Deposit, Example Corp Payroll $2,500.00
Total additions $2,500.00
Subtractions
Withdrawals
Date Location
10-5 POS Purchase Grocery Mart Anytown $100.00
10-18 Online Transfer To Savings $550.00
Total subtractions $650.00
"""),
    "community_checking_this_statement": ("checking", "7890", 2, """
REGULAR CHECKING
ACCOUNT NUMBER 1234567890
STATEMENT PERIOD 10/01/26 THRU 10/31/26
BALANCE LAST STATEMENT              1,000.00
DEPOSITS                  1         2,500.00
WITHDRAWALS               1           100.00
BALANCE THIS STATEMENT              3,400.00
DATE    DESCRIPTION                     AMOUNT        BALANCE
10/03   DEPOSIT PAYROLL               2,500.00       3,500.00
10/05   POS PURCHASE GROCERY MART       100.00-      3,400.00
"""),
    "credit_union_two_accounts": ("checking", "4455", 3, """
Statement Period 10/01/26 - 10/31/26
Summary of your deposit accounts
                                Previous     Deposits/     Withdrawals/     Ending
                                Balance      Credits       Debits           Balance
Share Savings  1234567811       $100.00       $0.05          $0.00          $100.05
Everyday Checking 1234564455   $1,000.00   $2,500.00        $650.00        $2,850.00
Everyday Checking - 1234564455
Date   Transaction Detail                                  Amount($)     Balance($)
10-01  Beginning Balance                                                   1,000.00
10-03  Deposit - ACH Paid From EXAMPLE CORP PAYROLL         2,500.00       3,500.00
10-05  POS Debit- Debit Card 1004 10-04-26 Grocery Mart       100.00-      3,400.00
10-18  Transfer To Shares                                    550.00-      2,850.00
10-31  Ending Balance                                                      2,850.00
Share Savings - 1234567811
Date   Transaction Detail                                  Amount($)     Balance($)
10-01  Beginning Balance                                                     100.00
10-31  Dividend                                                0.05          100.05
10-31  Ending Balance                                                        100.05
"""),
    "charge_card_asterisk": ("credit", "1002", 3, """
Prime Card
Account Ending 7-81002
Closing Date 10/23/26
Previous Balance $500.00
Payments/Credits -$500.00
New Charges +$212.34
Fees +$0.00
Interest Charged +$0.00
New Balance $212.34
Payment Due Date 11/17/26
Payments and Credits
Summary
Payments -$500.00
Detail *Indicates posting date
Payments
10/10/26* AUTOPAY PAYMENT RECEIVED - THANK YOU -$500.00
New Charges
Detail
SAMPLE PERSON Card Ending 7-81002
09/25/26 GROCERY MART ANYTOWN ST $112.34
10/02/26 ONLINE BOOKS 800-555-0100 WA $100.00
"""),
    "card_open_to_close": ("credit", "5566", 3, """
Cashback Card  Account number ending in 5566
Open to Close Date: 09/24/2026 - 10/23/2026
ACCOUNT SUMMARY
Previous Balance                    $500.00
Payments and Credits               -$500.00
Purchases                          +$212.34
Balance Transfers                    +$0.00
Cash Advances                        +$0.00
Fees Charged                         +$0.00
Interest Charged                     +$0.00
New Balance                         $212.34
TRANSACTIONS
Trans.  Post
Date    Date    Description                                      Amount
PAYMENTS AND CREDITS
10/10   10/10   INTERNET PAYMENT - THANK YOU                    -$500.00
PURCHASES
09/25   09/26   GROCERY MART ANYTOWN ST       Supermarkets       $112.34
10/02   10/03   ONLINE BOOKS 800-555-0100 WA  Merchandise        $100.00
"""),
}


@pytest.fixture(scope="module")
def PS(root, modules):
    return modules("pdf_statement")


@pytest.mark.parametrize("key", list(LAYOUTS))
def test_layout_reads_and_adds_up(key, PS, root, tmp_path):
    kind, last4, n, text = LAYOUTS[key]
    assert last4 in PS.last4s(text), (key, PS.last4s(text))
    con = db(root)
    try:
        con.execute("DELETE FROM accounts WHERE last4=?", (last4,))
        con.execute("INSERT INTO accounts(name, type, last4) VALUES (?,?,?)", (f"Layout {key}", kind, last4))
        f = tmp_path / f"{key}.txt"
        f.write_text(text, encoding="utf-8")
        res = PS.read(con, f)
    finally:
        con.rollback()
        con.close()
    assert res["account"]["last4"] == last4
    assert res["verified"] is True, (key, res["begin"], res["end"], res["money_in"], res["money_out"], res["rows"])
    assert len(res["rows"]) == n, (key, res["rows"])
    assert res["period"], key


def test_a_layout_missing_a_line_is_refused(PS, root, tmp_path):
    kind, last4, _, text = LAYOUTS["national_checking_b"]
    cut = "\n".join(ln for ln in text.splitlines() if "Gas Station" not in ln)
    res = PS.parse(cut, False, last4)
    assert res["verified"] is not True, "a statement that does not add up is never imported"


def test_first_statements_of_new_accounts_through_intake(root):
    """As a PDF in the inbox with no AI: new accounts are added by last four with the right type; a statement that
    names two accounts adds none and says which to add."""
    from test_paypal_statement import _pdf
    from conftest import q, run
    esc = lambda t: t.replace("(", "\\(").replace(")", "\\)")  # noqa: E731
    box = root / "inbox"
    box.mkdir(exist_ok=True)
    picks = ("card_monthname_dates", "charge_card_asterisk", "regional_checking_dash_dates", "credit_union_two_accounts")
    for key in picks:
        _pdf(box / f"{key}.pdf", [(20, 770 - i * 11, esc(ln)) for i, ln in enumerate(LAYOUTS[key][3].splitlines()) if ln.strip()])
    r = run(["data/ai_intake.py", "local"], root)
    assert r.returncode == 0, r.stdout[-800:] + r.stderr[-400:]
    for key in picks[:3]:
        kind, last4, n, _ = LAYOUTS[key]
        assert q(root, "SELECT type FROM accounts WHERE last4=?", last4) == [(kind,)], (key, r.stdout)
        assert q(root, "SELECT COUNT(*) FROM transactions t JOIN accounts a ON a.id=t.account_id WHERE a.last4=?", last4)[0][0] == n
    assert (box / "credit_union_two_accounts.pdf").exists() and "7811 or 4455" in r.stdout, r.stdout
    assert not q(root, "SELECT 1 FROM accounts WHERE last4 IN ('7811', '4455')")
