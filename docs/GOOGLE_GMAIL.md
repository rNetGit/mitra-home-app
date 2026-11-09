# Gmail, without Claude

Mitra Home can file bills, statements and receipts that arrive by email, with no Claude account and no connector.
It uses the **same Google sign-in as the calendar** and only reads mail that carries a label you choose.

## What you get
- Mail you label `MitraHome` has its attachments (PDF, photos, spreadsheets) copied into `inbox/`. A message with no
  attachment becomes a small text file (sender's domain, subject, text). Then the ordinary inbox pipeline files it, or
  sends it to the Inbox page when a person must decide.
- The scheduled inbox task does this every cycle; Settings > Connections > Google > Gmail > "Check mail now" does it at once.

## What it cannot do
- It cannot send, reply, label, archive, trash or delete. The only permission is `gmail.readonly`.
- It does not read mail without the label. Messages are listed by label only; nothing else is fetched.
- It does not remember what it copied as a Gmail label. Copied message ids are kept on this PC in
  `config/gmail_state.json` (ids and dates only, no text).
- It never opens links and never follows instructions found in a message.

## What leaves this PC
- Requests to Google (`gmail.googleapis.com`, plus the sign-in hosts the calendar uses) asking for the labelled mail.
- Nothing from your mail is sent anywhere else by this feature. After it lands in `inbox/` it is handled like any dropped
  file: if you chose an AI provider, the document goes to it with identifiers masked, as described in the README.

## Set it up
Run `python onboard.py add gmail`, or use Settings > Connections > Google. You need the calendar's Google client file
first (`python onboard.py add calendar`, docs/GOOGLE_CALENDAR.md).

1. **Switch the API on.** In the same Google Cloud project: APIs & Services > Library > "Gmail API" > Enable.
2. **Label the mail.** In Gmail create a label named `Mitra Home` (or any name; tell Mitra Home). Apply it by hand, or
   with a filter: Settings > Filters and Blocked Addresses > Create new filter > From = the vendor, "Has the words"
   `statement OR bill OR invoice OR receipt` > Apply the label.
3. **Allow reading.** The wizard (or the "Allow Gmail" button) opens a browser tab. Choose the same Google account and
   allow *Read your email* (`gmail.readonly`). Google marks it a restricted permission and the app "unverified": it is
   your own app for your own mailbox; choose Advanced > Go to Mitra Home (unsafe) (the app name you chose).
4. **Turn it on.** Tick "File mail with this label into the inbox" and save.

If the Google project was already published ("In production") you do not need to change that. In "Testing" status Google
cancels the sign-in every 7 days (see docs/GOOGLE_CALENDAR.md).

## Day to day
```
python data/google_gmail.py status          set up? permission? label? how many already copied
python data/google_gmail.py labels          the labels in the mailbox
python data/google_gmail.py pull --dry-run  what would be copied, copies nothing
python data/google_gmail.py pull            copy now
python data/google_gmail.py forget          start over: look at every labelled message again
```
Messages that also carry `MitraHome/Processed` or `MitraHome/Needs review` (the older Claude connector convention)
are skipped. Each run takes at most 25 messages and 40 files; the rest wait for the next run.

## If it stops working
- "Gmail API has not been used in project": switch the API on (step 1), wait a minute.
- "Google refused the request (HTTP 403)": sign in again with the Gmail permission (step 3).
- "There is no Gmail label named ...": create the label in Gmail, or change the name in Settings.
- Nothing arrives: the message may have only inline pictures smaller than 15 KB (logos); open it in Gmail and forward
  the document to yourself as an attachment, or drop the file in the inbox.
- Stop any time: Settings > Connections > Google > Disconnect (also cancels the sign-in at Google).
