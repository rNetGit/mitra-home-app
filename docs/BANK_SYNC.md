# Bank sync through SimpleFIN (optional, for power users)

Mitra Home never logs into a bank and never holds a bank password. Most families download statements and drop them
in the Inbox. Families who want balances and new transactions to arrive by themselves every morning can connect
**SimpleFIN Bridge** instead. It is opt-in, adults only, set up on this PC only, and everything it adds can be
forgotten with one click. Mitra Home charges nothing for it; the card sits in Settings > Connections (shown in the
Advanced view), and statements in the Inbox keep working for everyone.

## What SimpleFIN is
[SimpleFIN Bridge](https://bridge.simplefin.org) is a small paid service, independent of Mitra Home. **The family
signs up there and pays them directly** (about $1.50 a month at the time of writing; Mitra Home takes nothing).
At the bridge you connect your banks under your own logins. The bridge then offers your account data in one plain,
read-only format to any app you hand a *setup token* to. Mitra Home is such an app.

## What leaves this PC
- **One request a day to SimpleFIN** (`https://<bridge host>/simplefin/accounts`, read-only `GET`), carrying the
  access credentials SimpleFIN gave you and the date to start from. That is all. No bank is contacted by Mitra Home,
  nothing is written anywhere, and nothing about your family is sent along (no names, no categories, no notes).
- Nothing else. The transactions, balances and account names that come back stay in `family.db` on this PC like a
  statement you dropped in the Inbox. If you chose an AI provider, bank-synced transactions are *not* sent to it by
  this feature; only documents you drop in the Inbox go to the AI, masked, as described in the README.

## What stays on this PC and where
| What | Where | Note |
|---|---|---|
| The access URL (carries its own user name and password) | `config/secrets.env` as `SIMPLEFIN_ACCESS_URL` | Write-only: never shown, logged, exported or backed up. Treat it like a bank token. |
| Which SimpleFIN accounts you ticked, last pull, last error | `config/bank_sync.json` | Names, last four digits, bank name. No numbers, no secret. |
| The link between a SimpleFIN account and your `accounts` row | `accounts.simplefin_id` | An opaque id from the bridge, not an account number. |
| Transactions and balances | `transactions`, `account_balances` (kind `snapshot`) | Same tables as a statement import. |

## Set it up
1. At SimpleFIN Bridge: create an account, connect your banks, then **Create a setup token** (one long string).
2. In Mitra Home on this PC: Settings > Connections > **Bank sync (SimpleFIN)** > paste the token > Connect.
   The token works once; after that Mitra Home holds the access URL and the token is useless to anyone else.
   The box is shown only on this PC, never on a phone (the home Wi-Fi speaks plain http).
3. **Tick the accounts to pull** and save. Nothing is pulled for an account you did not tick, and no `accounts` row is
   made for it. A ticked account is matched to an existing row by the last four digits and name, or a new row is made.
4. **Pull now** for the last 45 days (SimpleFIN recommends at most 45 days a request; older days come from your statements). From then on the daily brief task pulls every morning (`tasks/run_task.py
   daily_digest`; `python tasks/run_task.py bank_sync` or `python data/bank_sync.py pull` run it by hand).

## What a pull does
- Asks for transactions since the last good pull (three days earlier, to be safe; the first time, or after a gap, at most 45 days back).
- Drops pending ones and anything already in `transactions` (same dedupe as a CSV statement import: SimpleFIN's
  transaction id is the `ref`, so a repeat is never added twice).
- Then the same steps as after a statement: category rules, receipt matching, recurring bills, the Inbox queue.
- Stores the balance as a snapshot for that day (cards and loans as the amount owed).

## When it fails
A pull that fails (bridge down, access revoked, bank needs attention at SimpleFIN) is **not retried**; it is written as
one item in the Inbox ("Bank sync did not work", with the reason) and tried again the next morning. The health check
(Settings > Data) warns when the last good pull is older than three days. The reason shown never contains the secret.

## Forget it
Settings > Connections > Bank sync > **Forget the bank connection** (tick the box), or `python data/bank_sync.py
forget`. This removes the access URL from this PC and clears the SimpleFIN ids on your accounts. Transactions and
balances already pulled stay, like any imported statement. To cut the bridge's own access to your banks, delete the
connections at SimpleFIN Bridge too.

## Command line
```
python data/bank_sync.py setup TOKEN   claim a setup token once, save the access URL
python data/bank_sync.py pull          pull the ticked accounts now
python data/bank_sync.py status        last pull, accounts, last error (never the secret)
python data/bank_sync.py dedupe        list bank-sync rows that repeat a statement row (--yes removes the copies)
python data/bank_sync.py forget        remove the access URL and the SimpleFIN ids
```

## Statements and bank sync together
Families often have statements in Mitra Home already when they turn bank sync on, and some keep dropping statements
afterwards. The same payment is never kept twice:
- **Days a statement already covers are skipped.** For an account that already has statement rows, bank sync only adds
  transactions dated after the newest statement row of that account.
- **One payment, two sources.** A bank-sync row and a statement row in the same account with the same amount (to the
  cent) and dates at most 3 days apart are one payment (the bank and SimpleFIN often date it a day or two apart and
  word it differently). Each row pairs once, so two $5 coffees stay two. This works both ways: a statement imported
  after bank sync skips the rows bank sync already brought in.
- **When it cannot tell** (two or more statement rows of that amount within 3 days), the bank-sync row is added and the
  Inbox asks once: "Possible duplicate: ...", with *Remove the bank-sync copy* or *Keep both*. Removing moves any
  receipt or Amazon order link and the category over to the statement row, and is written to `logs/edits.log`.
- **Older copies** (from before this check): `python data/bank_sync.py dedupe` lists them, `--yes` removes the
  bank-sync copies after a snapshot of the database in `backups_pre_upgrade/`.
Bank-sync rows are recognised by their reference: `sfin:` followed by SimpleFIN's transaction id.
Agents never run this script (it is on the guard hook's admin list); it is for the family, from Settings or a terminal.
