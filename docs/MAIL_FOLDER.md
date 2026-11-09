# The mail folder: forward papers to a mailbox made for Mitra Home

Mitra Home can read one folder of a mailbox and copy what arrives into its inbox: bills, statements, school letters,
receipts. It works with most mail providers, not just Gmail (Gmail users can also use the Gmail label instead:
docs/GOOGLE_GMAIL.md).

## 1. Make a mailbox only for Mitra Home

Create a new, empty address, for example `riveras.mitra@gmail.com` or an iCloud address. Do not use your main mailbox:
if the PC were ever lost, only the forwarded papers would be in that box.

Then send it what should be filed:
- forward a bill or school letter by hand when it arrives, or
- in your main mail, set a forwarding rule (for example everything from your power company, your school or your bank's
  "statement ready" address).

## 2. Make an app password

An app password is a separate password the provider makes for one app. You can delete it at any time, and it is never
your account's own password.

| Provider | Where | Server |
|---|---|---|
| Gmail | Turn on 2-Step Verification, then myaccount.google.com/apppasswords | imap.gmail.com |
| iCloud | account.apple.com > Sign-In and Security > App-Specific Passwords | imap.mail.me.com |
| Yahoo | Account security > Generate app password | imap.mail.yahoo.com |
| Fastmail | Settings > Privacy & Security > App passwords (IMAP, read-only is enough) | imap.fastmail.com |

**Outlook.com and work or school Microsoft 365 mailboxes** often do not allow app passwords for IMAP any more. Make the
Mitra Home mailbox at one of the providers above and forward to it from Outlook instead. Proton Mail needs its Bridge
app and is not supported.

## 3. Set it in Mitra Home

On the PC: **Settings > Connections > Mail folder**. Type the mailbox address (the server is guessed from it), paste the
app password, tick **Read it with every inbox check**, and **Save**. **Test the sign-in** counts the messages without
changing anything; **Read it now** copies what is new.

The first time, the last 30 days are read. After that, only new messages. Each message is copied once.

## What Mitra Home does with the mailbox

- Signs in over an encrypted connection (TLS, the server's certificate checked), only to a server on the public internet.
- Opens the folder **read-only**: messages stay unread, nothing is moved, flagged or deleted.
- Copies attachments of the kinds the inbox accepts (PDF, pictures, statements, spreadsheets), after the same checks as
  any upload; a message without one is kept as a text file. Small logos are skipped.
- Keeps the app password in `config/secrets.env` on this PC: never backed up, never shown again, never sent to an AI.

## Stop it

**Forget it** in the same card forgets the app password and what was read. Then delete the app password at the
provider too.
