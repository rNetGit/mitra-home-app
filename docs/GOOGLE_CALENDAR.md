# Google Calendar, without Claude

Mitra Home can show your Google Calendar events in the dashboard (Calendar) with no Claude account and no AI.
It only reads your events. Nothing here can create, change or delete them. Optionally it can keep a calendar of its
own for due dates (see the end of this page).

Each family uses **its own** free Google Cloud project, so no credentials are shared and nothing needs Google's app
verification. The first time takes about 15 minutes. After that it is one sign-in.

## What you get
- Calendar > Google Calendar: the next 7, 14 or 30 days from the calendars you choose, refreshed every 5 minutes.
- `python data/google_calendar.py events` in a terminal.
- Settings > Data > Health check shows whether it is signed in.

## What leaves this PC
- Requests to Google (`accounts.google.com`, `oauth2.googleapis.com`, `www.googleapis.com`) asking for your events.
  No document, bill or account number goes to Google.
- If you connected an AI provider and ask the chat what is coming up ("what's on next week?"), the titles and times of
  the Google events in that date range go to that provider, with your own account, to answer. Nothing else from Google
  leaves this PC.
- Event titles and times are shown on the dashboard. They are not written to the database or to briefs.
- The sign-in token (a "refresh token") is kept only in `config/secrets.env` on this PC. It is never printed, never in
  `family.json`, and never in a backup.

## Set it up

Run `python onboard.py add calendar`. It walks through the steps below and checks each result.

1. **Create a project.** Open <https://console.cloud.google.com/> signed in as the Google account that owns the calendar.
   Create a project named `Mitra Home`.
2. **Turn on the API.** APIs & Services > Library > search "Google Calendar API" > Enable.
3. **Consent screen.** APIs & Services > OAuth consent screen (also shown as "Google Auth platform"). User type
   **External**. App name `Mitra Home`, your email for support and contact. You do not need to add scopes here.
4. **Publish it.** Google keeps the "Publish app" button grey until Branding has two links.
   - **Branding:** Application home page and Application privacy policy link: any public page about the app. You may
     use the project's own: `https://rnetgit.github.io/Mitra Home/`. Under **Authorized domains** add
     `rnetgit.github.io`. Leave the logo empty (a logo starts a Google review). Save.
   - **Audience:** press **Publish app**. The status now reads **In production**.
   - In **Testing** status Google cancels the sign-in every **7 days**, and you would have to sign in weekly.
   - Google will label the app "unverified". It is your own app for your own calendar; that is expected, and an app with
     a handful of users does not need verification. (Google limits unverified apps to 100 new users.)
5. **Make a client.** Credentials > Create credentials > OAuth client ID > Application type **Desktop app** > Create >
   **Download JSON**.
6. **Give the file to Mitra Home.** The wizard asks for the path of the downloaded file and saves it as
   `config/google_client.json`. It must be a **Desktop app** client (the file starts with `"installed"`).
7. **Sign in.** A browser tab opens. Choose the account. If Google says it has not verified the app, choose
   **Advanced > Go to Mitra Home (unsafe)** (the app name you chose in step 3) and allow the two read-only calendar permissions:
   - *View events on all your calendars* (`calendar.events.readonly`)
   - *See the list of calendars you're subscribed to* (`calendar.calendarlist.readonly`)
8. **Pick calendars.** The wizard lists them; choose the ones to show (blank = the main one).

## Day to day
```
python data/google_calendar.py status       signed in? which calendars?
python data/google_calendar.py calendars    the calendars this account can read
python data/google_calendar.py events --days 14
python data/google_calendar.py revoke       sign out here and ask Google to cancel the access
```

## If it stops working
| What you see | What it means | Fix |
|---|---|---|
| "Google refused the sign-in (invalid_grant)" | the sign-in expired or was removed (Testing status, password change, access removed, or unused for 6 months) | make sure the app is "In production" (step 4), then sign in again. A sign-in made while the app was in Testing keeps the 7-day limit even after you publish |
| "Publish app" is grey | Branding has no home page / privacy policy link | step 4 |
| "Is the Calendar API switched on for the project" | step 2 was skipped, or it is on a different project | enable the Google Calendar API in the same project as the client |
| "config/google_client.json is not a Desktop-app OAuth client" | the client was made as "Web application" | create a new client of type Desktop app |
| Browser shows a Google error "redirect_uri_mismatch" | wrong client type | use a Desktop app client |

## Removing it
`python data/google_calendar.py revoke`, then delete `config/google_client.json`. You can also remove "Mitra Home" ("Mitra Home" on an older set-up) at
<https://myaccount.google.com/permissions>. Google keeps at most 100 sign-ins per account and client; a new sign-in
cancels the oldest.

## Limits
- Read-only on purpose. Putting Mitra Home's due dates onto a calendar for phone reminders is a separate step that
  would need the write permission; until then use the calendar file (`brief/mitrahome.ics`) or Drive.
- Gmail is not included.

## Putting Mitra Home's due dates on Google Calendar (optional, writes)
Mitra Home can keep bills, statement due dates, expiries, checkups, birthdays, festivals and seasonal tasks on a
calendar of its own, with a reminder at 9:00. Settings > Connections > Google Calendar > "Put Mitra Home due dates on Google
Calendar".
1. **Allow it.** One extra permission: "Make secondary Google calendars, and see, create, change and delete events on
   them" (`calendar.app.created`). Google limits it to calendars Mitra Home made itself, so your own events are out of
   reach. Google's sign-in screen opens again; tick the boxes.
2. **Choose** how far ahead (30 to 365 days), the reminder, whether amounts appear in titles, and whether it updates
   itself every morning.
3. **Preview what would change**, then **Apply these changes**. Nothing is written before that, unless automatic
   sync is on.
4. A paid or hidden item disappears from the calendar at the next sync; a moved due date moves its event.
   If someone **moves or deletes one of these events in Google**, Mitra Home does not change anything by itself: the
   next morning the Inbox (Calendar group) asks an adult. For a moved bill, appointment, family event or life item:
   **Use the new date** (the record moves) or **Keep ours** (Google gets it back). For a deleted one: **Take it off
   Today and the calendar** or **Put it back in Google**. Other dates (renewals, birthdays) are changed where they are
   kept. Until you answer, the sync leaves that event as it is in Google.
5. **Delete the Mitra Home calendar** removes everything it made (a calendar made under the old name is renamed in place). Disconnecting Google Calendar also stops it.

What leaves this PC: titles such as "Bill: Electric Co" and the due date (and the amount only if you switch that on).
From a terminal: `python data/calendar_sync.py status | preview | apply --yes | remove --yes`.
