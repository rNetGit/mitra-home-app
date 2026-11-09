# Changelog

Format: newest first. Each release lists what changed for families and anything they must do. Database changes are
additive migrations applied automatically by `python onboard.py update` (or `upgrade`).

## 0.147.0
No new migration.
- Changed: **Mitra Home is open source.** The code now lives in the public repository `rNetGit/mitra-home-app` (AGPL-3.0-or-later, CONTRIBUTORS.md credits Sanjay Katukojwala). The app looks for new versions there: this release is the last one published from the old private repository, so installs that update through it move over by themselves.
- Added: **Money > Statement**, one month as a home income statement: income by source, expenses grouped (Housing, Utilities, Insurance, Loans, Transport, Food, ...) with each category beside last month and the same month a year ago, then tax, saved and what is left. Below it a budget table lists every budget line (actual, over or under) and any category that moved by 25% and $50 or more, with a one-line reason. It opens on the last whole month, has a month picker and a Print button, and uses the same figures as the This month card.
- Added: **Month check** at the top of the Statement: is the month ready to count as final? It checks that the month is over, every account has lines, nothing is uncategorized, card spending comes from card statements and the month's bills are settled, each open item with a link to fix it.
- Added: **Money > Home costs**: what the house costs to run (Housing, Utilities, home insurance) over the last 12 months: bars per month, this month against the average, the year in total, the share of income and a table by category.

## 0.146.1
No new migration.
- Added: **The Mitra Wall uses the same day themes** as the Calendar: on the week tiles and the month cells (and the month's day-by-day list) a day with Diwali, Thanksgiving, Christmas, a flag day, a birthday or a medical visit gets its tint and coloured edge, and the week tiles show the small drawing. The night look keeps the tint and drops the drawing.
- Added: **Paired phones now get the built-in festival and holiday days** (public holidays and the festivals of your traditions, worked out on the PC) with every sync, so Diwali, Thanksgiving and the rest show on the phone's Calendar, themed. Phone app 0.23 and later reads them; older phones ignore them. Only the day's name and kind are sent, never which tradition it came from. **Settings > Traditions and holidays now says so**: the list of traditions stays on this PC, the days it adds go to your paired phones and walls on the home Wi-Fi, never to Drive or a chat bot.
- Fixed: the Thanksgiving drawing is no longer cut off at the bottom.

## 0.146.0
No new migration.
- Added: **Themed calendar day cards.** On the Calendar week and month views a day takes the look of its most important item: a tinted card with a coloured top edge, and an icon on each row (festival, holiday, medical, class, bill, birthday). Diwali (and Dhanteras, Govardhan Puja, Bhai Dooj), Thanksgiving, Christmas and the flag days (Veterans, Memorial, Independence), plus birthdays and medical visits, also show a small drawing along the bottom of the week card. The drawings are original vector art in `static/themes/`. Plain kinds only tint. Priority: named festival or holiday, birthday, medical, then the plain kinds.
- Added: **View a filed PDF or photo in a window** on a record's page and on a car's wallet card (Download is still there).

## 0.145.5
No new migration.
- Added: **A start time fills in the end one hour later** on the forms for events, appointments and classes (Add and Change), stopping at 23:59. An end time you typed, or one already saved, is left alone.

## 0.145.4
No new migration.
- Added: **Filter this list on a Records part page** (Family > Papers & IDs and the other parts): every word you type has to appear in a row's vendor, type, date, notes or file name. Papers are searched across all of them, not only the newest 300.
- Added: **A car's wallet card opens its filed insurance ID card.** Flip the card and use "Open the insurance ID card". It is found by the VIN's last 4 in the file name (`..._idcard_vin8413.pdf`), the newest paper wins.

## 0.145.3
No new migration.
- Changed: **Today is back to its earlier order** (Late, Today, This week in the first column). 0.145.2's move of "This week" to the second column is reverted.

## 0.145.2
No new migration.
- Changed: **Today: "This week" moves to the top of the second column**, beside Late and Today, instead of the bottom of the first column.

## 0.145.1
No new migration.
- Fixed: **Manage calendar shows one row for a shopping list's items on the same day** (for example "Thanksgiving 2026 (9 items: Pillows, Sheets, ...)") instead of one row per item.

## 0.145.0
No new migration.
- Added: **Manage calendar** (Calendar > Manage calendar, adults): one page for the whole family's events, holidays and days off, with filters by person and kind and Add, Change and Remove on each row. The phone app (0.23) can do the same and it syncs back.
- Added: **Edit a vehicle's details.** The vehicle page has an Edit details form (year, make, model, whole plate and state, VIN last 4, owner, driver, registration and inspection dates, status, notes). The whole plate is kept on this PC and shown on the Wallet car card; until one is entered the card keeps showing the last 4.
- Added: **Phone sync ops** event_update, event_drop, day_add, day_update, day_drop (calendar scope) and vehicle_details (ids scope). Older phones simply do not offer these forms.
- Removed: **The Parking button** on the Family page.
- Fixed: the tests decode subprocess output as UTF-8 (the en dash test on Windows).

## 0.144.0
No new migration.
- Added: **Change and Remove for a family event and for an appointment.** A wrong date or time can be corrected, or the entry removed, from its record page (Family > People > Holidays and dates, and Checkups and appointments > Appointments). Adults only; the same checks as adding; Remove asks for a tick and erases the entry.
- Changed: **The whole app has a new calm look: a cool grey page, white cards and one green accent, in light and dark.** The Today brief card is a soft green wash with a green main button and no longer stretches to the height of the panel beside it. The wall screen keeps its own looks.
- Removed: **The round floating "?" help button and the "New here?" tip.** Help is still under More > Help on this page.

## 0.143.0
No new migration.
- Added: **A wall can pick its own photo look from its Display menu.** The Mitra Home wall app sends the choice to this PC, which saves it in that wall's own screen settings, like the clock face; Settings > Phones and walls > Walls shows it.
- Added: **Today can say the brief in its own words.** When an AI is set up and trusted, the brief's lines about what is late, due and on the calendar are reworded after the page has drawn; only dates, kinds and short titles are sent, with names masked. Without an AI the plain brief stays.
- Changed: **Today keeps the rain, spending and next bill lines under the brief** whether or not the AI reworded it.
- Changed: **Unused Today deck styles and data keys removed.**

## 0.142.0
No new migration.
- Changed: **A new look for the app: Hearth by day, Night Garden at night.** Warm paper, terracotta and serif titles in light mode; deep green and amber in dark mode, the same colours as the Mitra Home phone and tablet app. Every text keeps a contrast of 4.5:1 or more. The wall screen keeps its own looks. A browser that still shows the old colours after the update needs one reload.
- Added: **Ask Mitra at the top of every page.** A bar on every adult page (except Chat itself) takes a question or a quick note, such as "Mateo has the dentist Friday at 4"; Ctrl K (Cmd K on a Mac) jumps to it. The question opens in Chat with its answer and never goes into a web address. The menu's "Chat" is now "Ask Mitra".
- Changed: **Today starts with Mitra's brief.** A few plain sentences say what is late, what is due today, what is on the calendar, whether it will rain and what has been spent so far this month, with quick links; "Mitra noticed" beside it lists what needs keeping up and any reward, wall or update notice. They replace the three summary cards that repeated the lists below them. The brief is written from your own data on this PC; no AI is asked.
- Added: **LED clock for the wall.** A new resting clock face looks like a seven-segment LED desk clock, readable across a room: time only, wide (temperature and date beside the time, a weekday strip below) or side (weekdays, chance of rain and temperature with high / low). Pick the colour (white, blue, green, red, amber), a black or wood background, 12- or 24-hour time (Settings > Phones and walls > Walls, for the household or one wall). At night it is pure black with digits in the night colour. Works on the browser wall and the Mitra Home wall app.
- Fixed: **The Simple / Advanced note in Settings** now runs the full width of the card under Save instead of being squeezed beside the button.
- Changed: **Newer libraries allowed.** The app now accepts FastAPI 0.143 up to 0.162 and needs httpx 0.28.1 or later for its tests; an update installs them by itself.

## 0.141.0
No new migration.
- Added: **More seasonal wall looks.** Holi, Ganesh Chaturthi, Navratri, Dussehra, Makar Sankranti (also Pongal, Lohri, Baisakhi), Onam, Maha Shivaratri, Ugadi, New Year, July 4, India's Independence and Republic Day, Canada Day and Thanksgiving join Halloween, Diwali and Christmas; Diwali gains the toran, kandil and fireworks. The wall screen art now comes from the same scenes as the phone app's wall. On a portrait screen each scene now fits whole instead of being cropped.
- Fixed: **A private job stays private everywhere.** Records, its search and the Chat's SQL look-ups no longer show another adult's private job, its hours or its invoices; only the owner sees them Chat answers also leave out private jobs and private saved items.
- Changed: **The first-run setup says up front what an AI unlocks.** The welcome screen and the "Read your papers" screen now explain that simple text statements are read on this PC, while unfamiliar letters, scanned papers and many bank statements need an AI you choose; what is masked before anything is sent; that a key costs about $5 to $10 a year (OpenRouter is the simple way); and that SimpleFIN Bridge can bring in new transactions every morning instead of a monthly download.

## 0.140.0
Migrations 066, 067, 068 and 069.
- Added: **Preview the wall screen before saving.** Settings > Phones and walls > Walls has a Preview button next to Save the wall screen (and next to Save for a wall): a window shows the resting screen with the choices on the form, clock face, weather footer, night tone and look, without saving anything.
- Added: **House is a Family chip.** City, state, ZIP code and the online look-ups switch (needed for the weather) are one tap from Family, next to Work.
- Changed: **Settings > Agent is now Settings > Home Profile.** Same card (name, tone, brief times, sign-in PINs, hidden items); only its name changed.
- Changed: **Phones and walls moved to the Settings home.** It is now its own pill and card next to Home Profile and Connections, no longer a card inside Connections. Same pages, same address.
- Added: **Hours summary on the Work page.** Family > Work > Summary shows one month as a calendar (hours each day, office or remote, month total, days worked) or one year month by month with the year total. Read only; recorded hours only, and planned hours of past days with no timesheet yet are shown apart, not added.
- Added: **Adult pills on the Work page.** Family > Work opens with a pill for each adult; the signed-in adult is selected and only that adult's jobs and work menus (Timesheets, Paperwork, Schedule, Details, Work calendar) show. Pick another adult to see theirs; a private job stays hidden from everyone else, and "Add a job" starts with the selected adult.
- Added: **A pay period of its own for each job.** Family > Work > Details has "Pay period starts on" and "Pay period ends on" (7 to 31 days, repeating): a job can work a Sunday-to-Saturday schedule and be paid Thursday to Wednesday. The Timesheets tab and the "Send the timesheet" reminder follow the pay period; the Schedule tab is unchanged. Both empty = the schedule cycle, as before.
- Added: **Money on the wall app, behind an adult's PIN.** The Mitra Home app on a wall tablet can show a quick daily look at bills: paid in the last 7 days and due in the next 7 (late ones first), after an adult types their own PIN (the same PIN rules, and one minute, as the browser wall). The amounts are fetched from this PC each time and are never stored on the tablet or in its copy; no account or reference numbers are sent. Needs the app version that adds the Money page.
- Changed: **A sign-in PIN can be replaced without the old one.** Settings > Home Profile (Agent) > Sign-in PINs no longer asks for your own current PIN, so a forgotten PIN is easy to fix; an adult picks the person and saves a new one. Still adults only, still audited (name, never the PIN), and a changed PIN signs that person out everywhere.
- Added: **Turn the wall pages by themselves.** Settings > Phones > Walls has "seconds per page" (0 = off, 10 to 110): after that long without a touch the wall opens the next page of the rail, round to the first. Money is skipped, nothing turns at night, a touch starts the wait again.
- Added: **Swipe between wall pages.** A swipe left or right on the wall moves to the next or previous page of the rail (Today, Calendar, Chores, Lists, Meals). Money is skipped, and the resting clock ignores swipes.
- Added: **Scrapbook photo style for the wall.** Settings > Phones > Walls > Photo style has a new "scrapbook page": up to three photos as white-bordered, slightly tilted prints on a paper page, the months they were taken as a handwritten caption.
- Fixed: **"Save for <wall>" no longer does nothing when "Its own screen" is unticked.** Changing any choice in a wall's window (clock, photos, night, pages, look) now ticks "Its own screen" for you, and a line under the box says an unticked wall follows the household and ignores those choices.
- Changed: **"Add a wall" leads with the Mitra Home app.** The app (Android, iPhone or iPad) is now the first choice and is ticked when the app is open to phones; the web browser choice says it needs this PC on. Nothing else about pairing changes.
- Added: **Set up your home office in Money.** Money > Home office has a "Set up your home office" form (person, tax year, office and home area, months, method, the qualifying yes / no questions, gross income) that saves the profile the figures use; saving again for the same person and year updates it. Records only, not tax advice.
- Changed: **Work is now jobs and businesses, and lives in Family.** Family > Work lists the jobs of the adults in the family: employment, contract, own business (LLC, S-corp, sole prop), rental or side business, each marked primary or secondary, with whether it needs timesheets and who can see it (every adult or only its owner). The page no longer asks for rates and has no Billing tab or invoices: money comes from the bank lines only. Timesheets, the on / off-site schedule, pay days and the work calendar work as before. Money > Work is gone; older rate and invoice data stays in the database, unseen.
- Added: **A timesheet finds its job.** A timesheet in the Inbox is matched to the family's jobs by the names, agency, number and remembered phrases printed on it (no AI); with exactly one clear match it is read in at once, and between two jobs nothing is guessed: the Inbox asks "Whose timesheet is it?" with the jobs to pick from and an optional phrase to remember, so the next sheet finds its job by itself (migration 067). Private jobs are visible, and their sheets importable, only to their owner.
- Fixed: **Work pages never land on the wrong job.** A stale job id no longer falls back to a contract number or a name. Days outside a job's dates are reported and not written by a timesheet import; "8:75" is refused as a time; a leap-day column no longer stops an import; saving the Timesheets tab no longer turns planned hours into worked hours.
- Added: **Remote and office days, work holidays and pay days on the Calendar.** A job with "Show the schedule on the Calendar" on (Family > Work > Details) puts its on-site and off-site days on the Calendar as Office and Remote chips with the person's name, only while the job runs; the work calendar's holidays and floating days replace those days' chips, and its pay days show as markers. A private job stays off the shared Calendar.
- Added: **A reminder to send the timesheet.** On Today, a job marked "Needs timesheets" shows "Send the <job> timesheet: <period>" once its last finished timesheet period has no imported timesheet and had days to work (a private job's reminder does not name the job). The invoice reminders are gone with the billing pages.
- Added: **A warning when one person has more than 24 hours in a day across jobs.** Typing hours or importing a timesheet says so in its message; nothing is blocked.
- Changed: **The Work page opens on your own primary job.** Jobs are listed active first, your own before other people's, primary before secondary.
- Added: **Paperwork for each job.** Family > Work > Paperwork keeps the papers of a job in one list: offer letter, contract, W-2, 1099, timesheet, benefits. Add a paper from a file (it is filed with your other papers) or keep one that is already filed; timesheets you import are added by themselves. Taking a paper off the list never removes it from the archive (migration 068).
- Changed: **Work wording and small fixes from a walk-through.** "Who" on a job lists adults only, and a child or pet cannot be named on one. The schedule and the hours rows say "Office (on site)" and "Remote (off site)", like the Calendar. A paper added to a job is filed under a name that says what it is (for example `..._acme_corp_offer_letter_other.pdf`). A job that does not need timesheets says so on its Timesheets tab.
- Added: **A family that installed from the website hears about new versions.** The daily look first asks the app's own release list (which only a maintainer's PC can read); when that is closed to this PC it asks the public releases of the Mitra Home site instead, and only counts a release that has an installer for this system (a Windows-only release is not offered to a Mac). Such a notice shows on Today, in the Inbox and in Settings > Data > Updates with a link to the download page; it cannot install by itself. Only a version number, its notes and a link are kept.
- Added: **About Mitra Home in Settings > Data.** The version, the Mitra Home website, the download page, the source page and the licence.
- Changed: **The wall's rail says "Calendar" and opens the Day view.** The Day, Week and Month buttons on every calendar page are unchanged; the rail button now lands on the day (before it opened the week).
- Added: **Seasonal wall looks, first step (nothing shows yet).** `wall_season.py` holds the Halloween, Diwali and Christmas looks as data (colours, drawn backdrop, decoration marks with their animation, clock face) and picks the look for a day: the festival day and the 3 days before it, never after. Halloween (Oct 31) and Christmas (Dec 25) are fixed dates; Diwali comes only from the PC's special days (the festival pack or a day an adult added). The wall draws the looks in a later step.
- Added: **The wall dresses for Halloween, Diwali and Christmas.** On the festival day and the 3 days before, the resting clock shows a drawn backdrop (night pumpkins and a lantern; diyas and rangoli; snow and trees) in the festival's colours, with a small flicker, glow, sway or drift on its decorations, and a chip with the festival's name on every wall page. It stays still at night and when the tablet asks for less motion. Switch it off in Settings > Phones > Walls > Seasonal looks; to see one today add `?season=halloween`, `diwali` or `christmas` to the clock's address. The next 60 days of looks also go to the app wall's data for a later app update. Diwali needs its date in the PC's special days (the festival pack or a day an adult added).

## 0.139.0
No database changes.
- Changed: **the first PIN opens Mitra Home to phones by itself.** Saving the first sign-in PIN on this PC restarts the app once for phones and walls on the home Wi-Fi (when phone access is on), so there is no separate "restart once" step. Trying to add a phone or a wall with no PIN now says "Please set up a PIN before you connect a phone" and points to Settings > Agent > Sign-in PINs.
- Changed: **the first run asks about an AI on a screen of its own.** "Read your papers" (step 4 of 6, optional) says what an AI does here, what is sent (only the text of a paper you drop in, with numbers cut to the last four digits and names masked; photos are a separate tick box), where the key stays and what it costs, before the provider form. "No AI" and Continue is a normal choice.
- Changed: **clearer buttons on files that wait in the Inbox.** "File it" is now **File it by hand** (you say what it is; nothing is read from the file) and "Try again" is **Reprocess** (read the file again; "Reprocess all" for every waiting file). With no AI connected a waiting file leads with **Connect an AI**, and Reprocess says it will wait again until one is.
- Changed: **Settings > Phones > Connection says what is left to do.** One card shows the step: Step 1 give an adult a PIN (with a button), Step 2 restart once, or "On". The On/Off switch moved into a fold ("Keep phones out" / "Let phones in"), so a family no longer sees "On" next to "started for this PC only".
- Changed: **Phones and Data are no longer separate Settings tabs.** The tabs are Household profile, Agent and Connections. Phones and walls open from a card at the top of Connections (with the next step), and Data is a lane on the Settings home. Every page still opens by its address.
- Changed: **the Simple / Advanced switch is at the top of Settings** (it was under Household profile), and **a new install starts in Advanced**. An install that already chose Simple keeps it.

## 0.138.0
Database: migration 065 adds `vaccinations` (applied automatically).
- Security: **fixes from the 28 Oct audit.** An agent steered by a document can no longer reach PowerShell through the audio-brief voice, run the scripts that talk to the internet, or send a card number inside a web address; Drive PDFs escape their text and print with scripts off; hostile calendar feeds cannot break the Calendar. Sign-in with a PIN counts every guess even when many arrive at once; with a mail app password saved, the mail server can be changed only on this PC; wrong pairing codes lock out only the device that sent them; look-ups and other calendars connect to the address they checked (no DNS rebinding).
- Changed: **accessibility.** A clear focus ring on buttons, readable hero and banner text, proper menu roles, status lines that screen readers announce, and story-card buttons that follow the theme colours.
- Changed: Settings > Connections > AI offers only the Claude CLI (your Claude plan); Codex stays terminal-only.
- New: **vaccination history** (Family > People > Health > Vaccinations). Add a shot for a person or pet: the vaccine, the day it was given, an optional next due date, the clinic or vet and a short note (no lot numbers or diagnoses). A next due date puts one reminder on Today, the Calendar and the weekly digest, the same as other vaccine reminders (lead time under Settings > Reminder leads, type vaccination). Marking a vaccine reminder done adds the shot to the history and moves the reminder on. Records only, not medical advice.

## 0.137.0
No database changes.
- Changed: **no console window from the Windows installer.** The installer now prepares Mitra Home's private Python while it installs ("Preparing Mitra Home..." on the progress page), so the first start is quick, and the Start menu, the desktop icon and "Start Mitra Home now" start it without a black window. Messages go to a log file; a start that fails shows a message box. Installing over or uninstalling a running Mitra Home stops it first. The last page says how to stop it and where the app, household and backup folders are.
- New: **Settings > Data > Stop Mitra Home** (adults, on this PC). It stays stopped until you start it by hand or restart the PC.
- Changed: **the Mitra Wall is easier to read from across the room.** Bigger text that grows with the tablet, darker grey text, each person's colour as a bar on their things, and late things folded into one red "N late" line (a tap lists them). On a small tablet (an Amazon Fire 7) or a narrow screen the month shows titles only with a count per day, and under phone width it becomes a day-by-day list from today.
- Changed: on the wall's Week, a person's chip shows only that person's things; **Everyone** shows them all.
- New: **Day view on the wall**, next to Week and Month: one lane per person in family order, then House (bills and renewals without amounts), with that day's weather. A small tablet shows the day as one list.
- Changed: **the wall's tap-for-details popup** has a band in the person's colour, a big title, an X in the corner, and a day's things grouped Late / At a time / All day, in bigger text.
- New: **wall themes** (Settings > Phones > Walls > Look, per wall): Paper (as before), Night (dark), Slate (cool grey), Bold (bigger, heavier text) and Photo (one family photo a day, blurred behind the cards).
- New: **Settings > Phones > Walls > Pages**: Chores and Meals show on a wall only when ticked (they are now off until ticked), and **Clock only** makes a wall, say in a bedroom, show only the resting clock.
- Changed: every resting clock shows the weather for today and the next five days; Two cities shows home big and the other place small; at night every clock is on pure black and the red or amber bedroom clock is much bigger.
- Note: the Mitra Home phone app's wall mode does not use Pages, Clock only or themes yet.

## 0.136.0
No database changes.
- Changed: Settings > Connections > AI asks for the provider, then the API key (with the last four characters of a saved key), then the model.
- New: **how to get an AI key, step by step.** The first run's AI card (open) and Settings > Connections (folded, until a key is saved) recommend an OpenRouter key: what waits in the Inbox without one, that names and numbers are masked first and only paid keys with no-training hosts are used, what it costs (about 60 cents a month for a busy family; $5 of credit lasts most families a year), and links to sign up, add credit with auto top-up off, create a key with a credit limit and check the privacy setting. "You are set up" suggests adding one when there is none. The AI stays optional.
- Changed: **on Money > Look back > Ledger the filters sit straight above the transactions.** On a wide screen the tiles, the notes, Download, How the tiles add up and By card member move to a panel on the right that stays in view while you scroll; on a tablet or phone they fold into one summary line above the list that opens with a tap. Same figures and links.
- Changed: **Money > Bills, Receipts, Subscriptions and Accounts show their list first** the same way: the tiles and notes sit in the right-hand panel on a wide screen and fold into the summary line on a tablet or phone. The Subscriptions tables are narrower to fit next to the panel: subscription, status, per month, next charge and decision (category and who uses it open with a tap on the row; per year is in the tiles), and a charge that is due before its statement is loaded says "due, no statement yet".

## 0.135.0
No database changes.
- Changed: **phones and walls on the home Wi-Fi are on by default.** Every way of starting Mitra Home (the Start menu, the desktop icon, the start at sign-in) now opens it to the home Wi-Fi once an adult has a PIN, so a tablet or phone is no longer stuck because the app was started "for this PC only". Settings > Phones > Connection has the switch and a **Restart for phones** button. The Start menu's "Mitra Home for phones" entry is now "Mitra Home (this PC only)" for the opposite.
- New: **Windows Firewall check.** Settings > Phones > Connection shows whether Windows lets phones in and whether the Wi-Fi is set to Private. **Allow phones through Windows Firewall** adds the one rule needed (the phone port only, Private networks only) after Windows asks you to confirm; a network set to Public gets a button to Windows' Wi-Fi settings.
- Changed: **the wall pairing code is large**, with Copy and **Show full screen** (readable from across the room), and the iPad Safari certificate step is explained next to it.
- New: **Settings > Data > Where things are**: the version, the app folder, the household folder, filed papers, backups, exports, logs and the database, each with an Open button on this PC.
- Fixed: after an update or a restart from Settings, the start-at-sign-in task could start a second copy of the app on the next port; the app now records itself when it starts.
- Changed: **bank sync (SimpleFIN) is free for every household.** There is no Pro plan: the Bank sync card is in Settings > Connections (the Advanced view) for everyone, and the morning pull runs whenever it is set up. The bridge itself is still a small service the family pays directly. A `"plan"` line left in `config/family.json` is ignored.

## 0.134.2
No database changes.
- Changed: **the Mitra Wall's week is a heat map.** Instead of the hour grid, each day is one tile, wider (taller on a tablet standing up) and a deeper green the busier it is, with how many things it holds, the weather and everything on it in one list: late and all-day things first, then by time, then bills (no amounts). A tap on a day shows the whole day large. A busy day no longer squeezes into a narrow column.
- Changed: **black behind every resting clock**, day and night (it was dark green or navy), so the wall does not glare in a dark room.
- Fixed: **the clock button and Photos also work at night.** After the night hours began, the clock button was hidden and Photos did nothing, so the clock could be changed only once in the evening. The button now stays, dimmed (hidden only behind the red or amber bedroom clock), and a tap on Photos shows one round of photos; photos still never start on their own at night.
- Fixed: on a small tablet lying down (an Amazon Fire 7), the wall's header, chips and side menu took most of the screen; they shrink there now.

## 0.134.1
No database changes.
- Fixed: **the Mitra Wall's resting clock fits small tablets.** On a small tablet such as an Amazon Fire 7, only the big clock showed; the date, what is next and the children's lines ran off the screen. Every clock now sizes itself to the screen's height as well as its width: the Traditional clock keeps its side column next to it, Words, Kids' day and Traditional stack on a narrow tablet standing upright, Modular keeps its cards on the screen, and the clock picker scrolls on a short screen. Large tablets look as before.
- New: **pair a tablet that cannot scan.** Settings › Phones › Walls › + Add a wall › the Mitra Home app: under the code, **Can't scan?** shows the code as text with a **Copy the text** button (send it to the tablet and paste it in the app), and the address, code and fingerprint to type. For tablets without a camera scanner, such as Amazon Fire. Pasting needs a Mitra Home app version with "Type the code instead" (coming).
- Fixed: the wall no longer says **"The Mock Family Family"** when the family's name already ends in "Family".

## 0.134.0
Database change: migration 064 (`walls.screen`: a wall's own resting screen), applied by the update.
- New: **Clock and Photos on the wall's side menu.** Clock goes to the resting clock at once; Photos starts the family's photos at once, also outside the photo hours (never at night), then the wall carries on as usual. Photos shows only when the wall has photos.
- New: **photo styles for the wall's slideshow** (Settings › Phones › Walls › Photos › Photo style, per wall): **Fade** (as before), **Slow zoom** (a gentle pan and zoom on each photo; still for tablets set to reduce motion), **Blurred fill** (an upright photo on a soft blurred copy of itself instead of black bars), **Collage** (three photos at a time) and **Frame and date** (a print on a dark table with the month it was taken). The month comes from the photo's own date when it is added; only that day is kept, the place and camera details are still dropped. Photos added before this version show no month.
- New: **four more clocks for the Mitra Wall**: **Flip** (number cards that turn over each minute), **Words** ("IT IS QUARTER PAST SEVEN", with dots for the minutes in between), **Two cities** (home and one other place side by side, for family far away: pick the place in Clock > Other place; the tablet works out the time itself, nothing is fetched) and **Kids' day** (the day from 6 AM to 10 PM as a ring in morning, afternoon and evening colours, today's plans on it and a dot for now).
- New: **choose the clock on the wall itself.** The clock button in the top corner of the resting screen lists every face; the one picked becomes that wall's own (the other walls keep theirs). An app wall sends the choice to the PC with its next update.
- New: **each Mitra Wall can have its own screen.** Click a wall in Settings › Phones › Walls and tick **Its own screen**: its own clock, photos and night clock, in three tabs (Clock, Photos, Night). A kitchen wall can show the modular clock with photos while the bedroom tablet is a red night clock. Walls without their own follow the Wall screen card, now in the same Clock / Photos / Night tabs. An app wall takes its own screen with its next update.
- Changed: **Settings › Phones is tidier.** Three tabs, **Phones**, **Walls** and **Connection** (the Wi-Fi address, the certificate and Away from home). Each phone and wall is one line with its person or kind, when it was last seen and a label (OK, Not seen for 14 days, Not used yet, Person left); click it to choose what a phone may carry or to remove it. **+ Add a phone** and **+ Add a wall** open a small window, and the pairing code opens in its own window. Adding a wall first asks whether the tablet runs its web browser or the Mitra Home app, then shows only that code (the two codes side by side were easy to mix up).
- Changed: **Notes and Chat sit on the PC's left menu**, under the five tabs, one click away (they were under More). On a phone they stay under More. Simple view shows Notes only, as before.
- Known: a tablet running the Mitra Home app as the wall gets the new clocks, the clock picker, photo styles and the Clock / Photos buttons with app 0.19.0 (not in the stores yet). Walls in a browser have them now. Photos added before this version show no month in Frame and date.

## 0.133.0
Database change: migration 063 (the Mitra Wall as an app: `walls.kind`, `app_version`, `last_sync`, table `wall_ops`), applied by the update.
- New: **two more clock faces for the Mitra Wall.** Settings › Phones › Mitra Wall › Wall screen › Clock now also offers **Modular** (a big time with cards for the weather, what is next, the children's jobs as rings and dinner, and a line for today's holidays and what is coming) and **Roman** (quiet hands with serif Roman numerals, the date and the next three things). Both lay out for a tablet standing upright too.
- New: **a bedroom night clock.** Wall screen › Night clock: **Dim** keeps the day's clock, darker (as before); **Red** or **Amber** turn the wall into a bedroom clock during the night hours: a black screen with only the large time, the date and the next thing, in a colour that does not light up the room.
- Fixed: **the wall no longer gets stuck on the browser's error page when the PC is off.** It stays on the screen it had (the clock keeps going), says "PC offline since 9:42 · showing 9:40", asks again every 30 seconds and comes back by itself once the PC answers. Money blanks its figures on the tablet when its minute is up, even with the PC unreachable.
- New: **the Mitra Wall as an app that works while the PC is off.** For families who open the PC only now and then: the Wall screen card shows a second code for the Mitra Home app (Android, coming with the next app version). A tablet that scans it keeps its own encrypted copy of what the wall shows (the next five weeks of the calendar, holidays and festivals for the year ahead, the family lists, the children's jobs and stars, the meals, up to 30 photos) and works from it for weeks; jobs ticked and list items added while the PC is off reach the PC the next time it runs on the home Wi-Fi, each once, a job counted for the day it was ticked. Never money, amounts, notes, papers or adults-only lists. Settings lists each wall's kind and its last update, and Today shows a line when an app wall has not updated for two weeks.
- Known: the app wall needs the Mitra Home app with wall mode (Android), not yet in the stores; iPad later. The browser wall works as before.

## 0.132.1
No database changes.
- Fixed: **signing in to a bank again at SimpleFIN no longer adds an empty copy of each account.** SimpleFIN gives a bank's accounts new ids after you sign in again; the bank sync used to keep the old account (with its history and the old id) and make a new empty one every time, so the history and the newest lines ended up on different accounts. It now re-links the old account (matched by the last four digits, plus the name when several share them) and keeps everything on one account. An account whose id the bridge still sends is never taken over. Copies already made are not merged by the update; remove an empty copy only after checking it holds nothing.

## 0.132.0
No database changes.
- New: **one Sync button.** Today > Keep up > **Sync now** now pulls the bank, the Google Drive inbox, the labelled Gmail and the mail folder in one go, in the background (a step that fails does not stop the next; the card shows the step while it runs and what it did for 15 minutes). A house with only the Drive inbox or a mail folder gets the button too. Papers that arrive wait in the Inbox; nothing is read by an AI here.
- New: **Money > Overview says how fresh the data is**: "Data as of: Cards and checking as of Oct 21 · 1 account behind", with a link to the accounts. In Money > Keep, an account with no lines for 35 days or more is marked "no lines for N days".
- Fixed: **a PC whose scheduled jobs run but were never recorded.** When the daily brief, weekly digest, weekly backup or inbox check already exist in Task Scheduler / launchd but `config/family.json` never said so, the app now records it at start (and in `onboard.py upgrade`), so the health check and Today > Keep up report a failed or missing run instead of staying silent. A flag is never switched off, and another copy's jobs do not count.
- Known: the installer / Mac "run the four jobs by themselves on first start" is not in this release.

## 0.131.1
No database changes.
- Fixed: **Today > Keep up lists the accounts that matter first.** A bank-synced account that stopped getting lines comes first, then checking accounts and cards, then savings and CDs (one interest line a month), each by how long it has been quiet. Before, four quiet CDs could fill the card and hide the salary account.

## 0.131.0
No database changes.
- New: **Today > Keep up.** A small card for adults that says what the house needs to stay current, each line with one button: bank sync (last good pull, a bank that asks you to sign in again, and **Sync now** right there instead of in Settings), accounts that went quiet (a synced account with nothing new for 10 days, a statement account with no lines for 40 days: Add statement / Check sync), scheduled jobs that are off, failed or have not run, and how many Inbox cards wait for an answer. Nothing to say = no card. Jobs that evidently run (a recent heartbeat) count as set up even on an install where the setup flag was never written.

## 0.130.3
No database changes.
- Fixed: **the "start when I sign in" job could not make the household folder on a brand-new install.** If the job ran its first start before you opened Mitra Home yourself, the first start failed (a file its own log held open in the app folder), and every 5-minute try failed the same way. The job now writes its log to `%LOCALAPPDATA%\MitraHome\logs`, so the first start works whoever starts it. Starting Mitra Home yourself right after the install was never affected. The uninstaller removes that log folder.

## 0.130.2
No database changes.
- New: **Mitra Home can start by itself when you sign in to the PC (Windows).** The installer has a new checkbox, "Start Mitra Home by itself when I sign in to this PC, and again if it stops" (ticked by default). It sets a small Task Scheduler job that checks every 5 minutes and starts the app, with no window, if it is not running. A restart or a closed window no longer leaves it off. On an existing install, run `python data/autostart.py on web` (add `--lan` for phones); `python data/autostart.py off web` stops it for good. Phones stay opt-in. Mac and Linux: `python data/autostart.py status web` shows a crontab line to add.
- New: **the Windows installer is signed** (publisher Rajesh Katukojwala), so Windows shows the name instead of "Unknown publisher". SmartScreen can still warn at first because a new installer has little download history: More info, then Run anyway.

## 0.130.1
No database changes.
- Fixed: **Money > Regular fits a phone again.** The "Next 7 days" chips wrap (a long name breaks inside its chip) and take a row of their own, so the page no longer scrolls sideways at 375 px.

## 0.130.0
No database changes.
- Changed: **one way of counting spending across Money.** The Money overview, This month, Trends, the budget, the monthly report, the Mitra Wall and the phones now count spending the way the Ledger does: refunds come off, and tax shows on its own line instead of inside "spent". Transfers between your own accounts, investing and card payments never count. In a month with no card lines loaded, card payments made from the bank still count, and the Ledger says so. Your "spent" figures can go down after this update, most in a month with a large tax payment.
- New: **Money > Spending, Bills and Regular on the PC**, the same pages the Mitra Wall has. In the Standard view, Money is now Overview, Spending, Bills and Regular; the other pages sit under "All money pages".
- Changed: **a simpler Advanced Money.** Overview is the month's story card, Needs a look and the three lanes; This month is the story and the categories. Pay > Cards and Look back > Cashflow are gone: the Ledger has the card view (choose a card in Account, the split by card member, and the form to name a category for uncategorized merchants) and Trends has the month-by-month table. Keep > Deposits became Look back > Deposit sources. Missing statements and Price rises moved to Look back.
- New: **phones show Money > Spending, Bills and Regular** (phone app 0.16.0) for adults whose phone has Finance detail. The phone's "This month so far" now matches the PC.
- Fixed: **the Mitra Wall's Today no longer puts the Now mark beside an event that has already ended.** Once every event is over it says "Nothing more today".

## 0.129.0
No database changes.
- New: **three more Money pages on the Mitra Wall** (behind the same adult PIN, a tab row under the Money title: Overview, Spending, Bills, Regular). **Spending** lists every category with this month so far, last month and the same month last year, with bars to compare. **Bills** shows each bill paid this month next to last month's (amount and day), which ones were paid last month and have not come yet this month, and the bill list's open bills due this month. **Regular** lists the bills and subscriptions that keep coming (home and utilities, loans and insurance, subscriptions) with the amount, the next date and what they add up to a month and a year. They count spending and bills the way the Ledger does. Unlocking from one of these pages comes back to it.

## 0.128.1
No database changes.
- Fixed: **the Money > Ledger now says why an account shows nothing.** Choosing an account that has no lines in the dates (for example a checking account whose October statement is not loaded yet) showed an empty list with no warning. It now shows "Not up to date: <account> (newest line Sep 30). Add its latest statement."

## 0.128.0
No database changes.
- Changed: **the Money > Ledger tiles now show cash flow instead of adding up every line.** Income, Spending, Left over, Bills paid, Invested, money moved Between your accounts and Card payments, with a small line under each. A transfer or card payment that has its other side in another account (same cents, within three days) is matched: it counts as neither income nor spending, so moving money to savings or paying a card no longer inflates Money in and Money out. Short yellow notes name the accounts that are not up to date for the dates, transfers or card payments with no other side loaded, and a period with no pay; **How the tiles add up** (a fold under them) groups every line and shows the old totals in and out. The explanation is in the Ledger's help (the ? button). Chips under the tiles filter to one kind of line (with its count and total), and lines that only move money between your accounts read quieter and say **matched** or **no other side**.
- Added: the Ledger's Type filter and the Edit list now include Fees, Utilities, Insurance and Loan payments (they were already allowed; they just could not be picked).

## 0.127.0
No database changes.
- Added: **a mail folder** (Settings > Connections > Mail folder): make a mailbox only for Mitra Home (Gmail, iCloud, Yahoo or Fastmail), forward papers to it or set a forwarding rule in your main mail, and type its address and an app password on this PC. **Test the sign-in** and **Read it now** check it; from then on every inbox check copies what is new into the inbox, the same way the Gmail label does. It is read-only: messages stay unread and nothing is moved or deleted. Attachments get the same checks as an upload; a message without one is kept as text. The app password stays on this PC, is never backed up or sent to an AI, and **Forget it** removes it. Outlook.com and Microsoft 365 often block app passwords, so forward to one of the others. Step by step: docs/MAIL_FOLDER.md.
- Added: **changes made in Google Calendar come back as questions.** If someone moves or deletes one of Mitra Home's events in its own Google calendar, the next morning the Inbox (Calendar) shows a card for it. For a bill, appointment, family event or reminder moved to another day: **Use the new date** or **Keep ours**. For a deleted event: **Take it off Today and the calendar** or **Put it back in Google**. Nothing changes until an adult answers, and until then the sync leaves that event alone. Events you make yourself in Google are never read here. More in docs/GOOGLE_CALENDAR.md.
- Fixed: `python onboard.py update` in a window that cannot answer its "Continue? (Y/n)" question (a remote or scheduled shell) now stops with "nothing was changed, run it again with --yes" instead of an error.

## 0.126.0
Database changes: migration 062 adds savings goals, and the rewards children spend their stars on (applied automatically).
- Changed: **the Family Wall is now called the Mitra Wall.** Same screens, same pairing: walls already paired keep working. It is under Settings > Phones > Mitra Wall, and the setup guide is now docs/MITRA_WALL.md.
- Added: **rewards for stars** (Family > Routines > Rewards). List what a child can ask for, for one child or any child (30 minutes of screen time = 10 stars). A child asks on the wall's Chores screen or their own page; the stars are held until you answer under **Asked for**: **Give it** spends them, **Not now** gives them back. Today shows a line while a request waits. The allowance is separate: it pays for jobs done and does not use stars up.
- Added: **savings goals** (Money > Keep > Budget and loans > Add a savings goal): what it is for, how much, by when, and what is saved so far, or an account kept for it (then its latest statement balance counts). Each goal shows how far it is, where it should be by now and what it takes a month to get there.
- Added: **paying loans off sooner** (Budget and loans, under Loans): for each loan with a balance, rate and payment, what 50, 100 or 250 more a month does to the payoff date and the interest. Arithmetic on what is on file, not advice.
- Added: **net worth by month** (Money > Keep > Accounts): cash, investments and what cards and loans owe at the end of each month, from the statement balances on file, with the change from the month before.
- Added: **a pack for your tax preparer** (Money > Look back > Tax papers > Download the pack for your tax preparer): one zip with the tax-paper checklist, the year-end summary, the home-office figures and copies of the year's filed tax papers.
- Added: **other calendars** (Settings > Connections > Other calendars): paste an iCloud, Outlook, school or work calendar's subscribe address (.ics or webcal://) on this PC, and its events show on the Calendar page next to everything else, read-only, read about once an hour. Only titles and times are kept. The address stays on this PC and goes only to that calendar's own server; this does not depend on the Look things up online switch.
- Added: **a recipe from a web address** (Family > Home > Meals > Save a recipe > Fill it in): paste a recipe page's address and the name, servings, ingredients and method are filled in for you to check, from the recipe data most recipe sites carry (no AI). Needs Look things up online on.
- Added: **an emergency pack for someone you trust** (Today > Documents > Emergency sheet). **Where things are** (the will, who can open the password manager, the safe, the backup drive and so on; places and names only, never a password or number) is printed on the sheet. **Download the sealed copy** makes one file that any web browser opens with a passphrase you choose and tell them separately; no app needed, and the passphrase is not kept. Every document also has **Print**.
- Added: **Share the list** and **Print the list** on a shopping, to-do or packing list: share what is still open to a message, an email or a note (on a PC it is copied), or print just the list.
- Added: **use it away from home with Tailscale.** With Tailscale on the PC and your phones, Settings > Phones shows an **Away from home** address to open in the phone's browser; the PC's own certificate now names that address too. The PC is still never open to the internet. Step by step: docs/REMOTE_ACCESS.md. (When Tailscale is running, the certificate is renewed once with the same key: phone app 0.14 and later stay paired; an older phone app pairs again.)
- Changed: **help on every page is up to date** with the wall, the house card and online look-ups, schools and calendars on a person, the weather and everything above; Chat's "How do I ...?" answers use the same help.
- Docs: docs/plans/MARKET_REVIEW.md, where Mitra Home stands next to similar apps and the plan for what comes next.

## 0.125.0
No database changes.
- Added: **a month view on the Family Wall.** Week | Month at the top of the week: the whole month in whole weeks, up to three lines a day (timed things first) and "+N more"; tap a day for everything on it. Bills are named as due or late, never with an amount.
- Added: **a full-size clock and family photos on the resting wall.** After two minutes untouched the wall shows a big clock, **digital** or **traditional** (hands, with a second hand), and in the day the family's photos in turn: the clock for a while, then a few photos full screen with the time and weather in the corner, then the clock again. At night it stays on a dark clock with no photos. Set it in **Settings > Phones > Family Wall > Wall screen**: the clock, photos on or off, the photo hours, the night hours, how long the clock and each photo show and how many photos each turn. **Add photos** there (several at once, iPhone photos too): this PC makes each one again, upright, at most 1920 pixels and **without its location or camera details**; they stay on this PC (household folder `wall_photos`) and only a paired wall shows them.
- Added: **tap anything on the wall to see it in full**: an event, an appointment, an all-day line or a bill opens a box with its whole title, the day and time and who it is for (no amounts).
- Changed: **the wall shows what Today on the PC counts.** Renewals, car service logs, checkups, seasonal jobs (such as the lawn) and other to-dos now appear on the wall's week, month and Needs doing; anything overdue shows on today, marked late. Done, snoozed and hidden items stay hidden, as on the PC.
- Changed: **Coming up instead of the money card** on the wall's Today: the next three days (tomorrow first), under tonight's dinner. Money stays behind an adult's PIN in the wall's menu.
- Changed: the wall shows the Mitra Home logo; a wall code now works for 15 minutes (it was 5); in the evening the week's grid runs to the time now, so the red line still shows; tonight's weather shows as "low 38°" with a moon, not as a high under a sun.

## 0.124.1
No database changes.
- Fixed: **iPads and iPhones could not open Mitra Home on the home Wi-Fi** ("Safari can't open the page because it couldn't establish a secure connection"). Apple refuses any certificate valid for more than 825 days, and this PC's own certificate was valid for ten years. It is now valid for about a year, names this PC's current Wi-Fi address, and is renewed by itself when the app starts for phones (about a year on, or when the PC's address changes). Android phones did not mind and keep working.
- Changed: **phones stay paired when the certificate is renewed.** The pairing code now also carries this PC's key, and the phone app (0.14) checks the key instead of the certificate. Phones paired before this update, and the iPhone app, pair once more after the first renewal (Settings > Phones on the PC).
- Docs: the Family Wall guide says what to do when a tablet cannot reach the PC (Windows Firewall on a Private network, Safari's certificate warning).

## 0.124.0
Database changes: migration 061 gives family events a start and end time (applied automatically).
- Added: **family events at a time of day.** "Family dinner today 8 to 8:30 pm" in Chat now shows the time on the confirm card and, after OK, sits at 8:00-8:30 PM on the Calendar, on the Family Wall's week grid and Today, on Today's timeline and in the calendar file for phones (at its time, with a reminder an hour before). Before, Chat could not add a time to an event that was not one person's appointment and skipped it. Also on the web: **Family > People > Holidays and dates > Add a family event or a yearly date** (and the **Family event** tile on Add): name, day, optional start and end time, once or every year. A dated flyer read from a photo keeps an event's time as a time instead of in its name.
- Added: **add an event, an appointment or a reminder from the phone app, anywhere.** The phone's **Add** sheet has three short forms (no AI on the phone). Away from the home Wi-Fi the item waits on the phone as "waiting to send" and this PC adds it at the phone's next sync, with the same checks as the web app (adults with the Calendar permission only; a wrong date or an unknown person comes back with the reason). Sending the same item twice never adds it twice. An event can have a start and an end time (or be a whole day), and the phone's calendar shows it at that time. Needs the updated phone app; a phone only offers the forms once the PC has said it takes them.
- Added: **the local weather on the Family Wall and Today.** With the ZIP code set and **Look things up online** on (Family > House), the wall's Today shows the temperature now, the sky, today's high and low and the rain in plain words ("Rain likely from 3 PM"); the resting clock shows the temperature next to the time, and the week shows each day's high and low. Today on the PC gets one weather line. The PC fetches it about every 45 minutes (the tablet never goes online), sending only the ZIP code and the ZIP area's rough position: the National Weather Service in the US, Open-Meteo elsewhere or when it does not answer. No key. With the switch off, no ZIP or no internet, nothing shows.

## 0.123.0
Database changes: migration 059 adds the schools, colleges and employers people are linked to; migration 060 adds walls, wall pairings, routines and the days they were done (both applied automatically).
- Added: **edit the House card** (Family > House, pencil): city, state and ZIP code of the home. No street address is kept. The state picks the state holidays on the calendar.
- Added: **"Look things up online" switch** (Family > House, off until you turn it on). When on, only the ZIP code, the state, the public name of a school, college or employer and the school year go out; never anyone's name, the family name, a street address, a phone number or an account or ID number. Anything else is refused before it is sent.
- Added: **schools near home** when editing a child: a list from the US Department of Education's public school directory (public and private schools, with their district), nearest first; Pick fills in the school.
- Added: **college name check**: type the college and **Check name**; a typo gets "Did you mean ...?" from the US college directory.
- Added: **this year's school, college or work calendar**: **Find this year's calendar** asks your AI to search the web for the official calendar (Anthropic, OpenAI, Gemini or OpenRouter key; public names only) and lists the calendar files it finds; **Import** one, paste a link (.ics feed, PDF or the calendar page) or import a file. Days off, breaks and early dismissals wait in the Inbox for an adult to add. An employer's holiday list lands as holidays for that adult only. No date is ever made up: dates come only from the calendar itself.
- Added: **state holidays for all 50 states and DC** (state-government holidays, with the federal days a state does not keep left out). Before, only eight states had their own days.
- Added: **the Family Wall.** An old tablet or iPad on the wall becomes the family's screen: the week as a calendar (everyone's colour, overlaps side by side, a person chip shows one person's day), Today (what is on, what needs doing, the children's progress, dinner), Chores, Lists, Meals, and a resting clock after two minutes untouched (at night, from 10 PM to 6 AM, a darker clock after 30 seconds); it keeps the screen awake. Pair it in **Settings > Phones > Family Wall**: name it, **Show the wall code**, scan it with the tablet's camera (or type the code). It works on the home Wi-Fi over HTTPS only, with its own sign-in (no person's PIN on the tablet); **Remove** signs it out at its next refresh. At most 5 walls.
- Added: **money stays off the wall until an adult unlocks it.** Every screen names bills as "due" or "late" without an amount. **Money** opens with an adult's own PIN (the same wrong-PIN locks as sign-in) and shows the month: spent against the budget, money in, what is left, the bills of the next two weeks with amounts, and the children's allowance from stars. It locks itself after a minute, or at **Lock now**.
- Added: **children's routines with stars** (Family > Routines, adults): jobs for the morning, after school and the evening, each worth 1 to 5 stars, on chosen days or every day, with a picture. On the wall a child taps a job when it is done (tap again to take it back). Stars count Monday to Sunday; **What a star is worth** sets the allowance rate (25¢ unless changed, 0 = stars only). Nothing is paid automatically.
- Added: **a child's own jobs on their page.** A child signed in with their own PIN sees **My jobs today** at the top of their page: today's jobs by morning, after school and evening, how many are done and their stars this week (never an allowance amount). They tick a job there when it is done and untick it to take it back; another child's jobs never show and cannot be ticked.
- Added: **family lists on the wall**: tap to tick, type to add. Adults-only lists never show there.
- Added: **dates from a photo** (Add > Dates from a photo): photograph a flyer, invitation or school letter. With photo reading on, your AI lists its dates (picture day, a day off school, early dismissal, something to bring by a date). Check each line, untick what you do not want, and **Add the ticked dates**: days off and early dismissals go on the calendar, things to bring become reminders, an event with a time and a person becomes an appointment. Without the AI you type them next to the photo. The photo is removed when you save or discard.
- Added: **a recipe from a photo** (Add > Recipe from a photo): a recipe card or cookbook page fills in the recipe (name, serves, ingredients, method) for you to check and save.
- Added: **star goals**: a goal per child (for example *New bike, 100 stars*) on Family > Routines, counted from the day it is set, with a progress bar on the wall's Chores screen.
- Added: **the allowance in the budget**: **Put it in the budget** on Family > Routines sets the child's allowance line to every job done for a month.
- Added: lists on the wall show who added each item.
- Added: **docs/FAMILY_WALL.md**: pairing a tablet and keeping it on the wall (iPad Guided Access, Android screen pinning, Fire tablet).
- Changed: a person's rename and purge reach the routines too; Chat can answer questions about routines and stars.
- Fixed: **a photo the AI read but that is not a receipt** no longer says "The photo could not be read": the card says the AI read it and asks what it is. Receipt photos with an unclear store, date or total, and answers the AI could not use, say so too.
- Fixed: **Chat no longer says it added something it did not.** When the AI asked for a change that failed the checks (for example a time written into a date), Chat said "I couldn't do one part of that" but still showed the AI's "I've added ..." reply; now it says **Nothing was added or changed** and nothing else.

## 0.122.1
No database changes. Two new packages (Pillow and pillow-heif) are installed on the next start.
- Added: **iPhone photos (HEIC) are read.** With "Let the AI read photos" on, a HEIC receipt photo dropped on the Add page is turned into a JPEG on this PC (smaller, upright, and without the phone's location or camera details) and only that JPEG goes to your AI; the HEIC itself is filed with the receipt. A HEIC card photo can be added to the Wallet too. With photo reading off the photo waits with "Reading photos is off"; on a PC where the two packages could not be installed it waits, as before, with a note to save it as JPG. A HEIC that was already waiting says **Try again**.

## 0.122.0
No database changes. Statements and bank downloads you drop on the Add page are read more often, on this PC first, and when one is not, the page says why and offers the fix.
- Added: **scanned PDFs are read by your AI when "Let the AI read photos" is on** (Settings > Connections). A scan has no text, so before it always waited for you. Now the AI reads the file itself: a scanned statement is imported only when its lines add up to the printed balances (long numbers in its lines keep only their last four digits), a scanned bill or receipt is filed like any other, and anything doubtful waits for you with the AI's guess. With photo reading off nothing is sent and the card says how to turn it on. Needs an API key provider (not Ollama, not the signed-in apps).
- Added: **"Why?" on every file waiting for you**: fold it out to see each step that was tried (this PC's statement reader, the AI) and what each found. **File it** now starts filled in with what the AI read (type, from, date, amount, due date); check it and save.
- Added: **two more checks on statements the AI reads**: the lines must also match the statement's own printed totals of money in and money out (when those agree with its balances), and lines dated outside the statement period are named in the result so you can look at them in Money > Ledger.
- Added: **read a waiting file again from the Add page.** **Try again** on a file puts it back in the inbox and reads it at once; **Try all again** does it for every waiting file. A statement of an account this PC does not have offers **Add the account ending 1234**: name and type, last four only, then the statement is read again. A file that needs photo reading switched on links straight to the AI settings.
- Added: **bank downloads are read without AI.** An OFX / QFX download (the "Quicken" or "Money" file most banks offer) is imported into the account its number names (a new account is added by its last four), and a second download of the same days adds nothing twice. An activity export (CSV) is imported when it says which account it is from: an account column, or the last four in the file name ("Card1234_Activity.csv"); otherwise it waits and asks.
- Added: **Import as statement** on a waiting statement, export or download: choose the account (and, for a PDF, whether to read it as a bank account or a card). A PDF is checked first: when its lines do not add up the card says by how much and nothing is filed, unless you tick **Import even if the lines do not add up**.
- Fixed: **a bank or card statement is read on this PC first, also when an AI is set.** Before, the AI decided first what the paper was, so a card statement could be filed as a bill with no transactions. A statement whose lines add up to the printed balances is now filed and imported with no AI call (the account is added by its last four digits when it is new); only a statement this PC cannot read goes to the AI.
- Fixed: **statements that say "Statement Balance" / "Previous Statement Balance"** are read too (before, only "New / Ending / Closing Balance").
- Fixed: **the progress panel no longer keeps spinning** when a filing run could not start (another run or an update was busy), stopped with an error or took too long. Each file then says "Not read yet" and what to do; the run's output is kept in `logs/intake_web.log`.
- Fixed: **statements that print the whole account number** ("Account Number" followed by all its digits) are matched by their last four digits.
- Fixed: **more bank and card statement layouts are read on this PC**: dates printed as "Sep 26" or "10-3", a star after the date, "Balance Last Statement / Balance This Statement", account numbers printed with spaces, after "Checking" or "Savings", or as "Ending 7-81002", a sign set apart from the amount ("- $500.00"), and statements that print only a closing date. Nine common US checking, credit union and card layouts are now in the tests. A statement that lists two accounts no longer adds a new one on its own: it says which account to add.
- Fixed: **an AI account out of credit** (the provider answers 402) no longer sends files to "File it by hand": they wait in the inbox with "Your AI account is out of credit", and every AI refusal now carries the provider's own short reason (keys hidden).
- Changed: **a file that stays in the inbox keeps saying why** (AI busy, out of credit, today's limit, no AI set) after the progress panel is gone, and a filed statement says how many lines were added.
- Changed: **clearer words on the Add page.** "Today's AI limit is used up" instead of "The AI did not answer"; review cards now say the next step, for example "a statement of an account ending 1234 that is not set up yet", "Reading photos is off", or that iPhone HEIC photos are not read yet.

## 0.121.3
No database changes. Every Money list row opens in a window, and Bills and Accounts read in a better order.
- Changed: **Bills read in the order you scan them**: Due, Status, Amount, then the bill's name (still the link, and still the title on a phone), Vendor and Category. **Accounts** show the name, then the latest reported balance, then Type, Owner and As of.
- Changed: **in every Money list, a row title opens in a window over the list** (Accounts, Bills, Receipts, Subscriptions, Phone bills, Cards, Deposits and the rest), the same way as in the Ledger: the record's details and filed paper, **Previous / Next** (or the arrow keys) through the same list with your filters, and the same change forms as the record page (for example **Mark paid** on a bill), answered in the window. Esc or Close returns to the same place and the list shows the change. The old record link still works.

## 0.121.2
No database changes. The Ledger line opens in a window.
- Changed: **a Ledger line opens in a window over the list** instead of leaving the page: all its details, the filed paper and the change history, **Previous / Next** (or the left and right arrow keys) to go down the filtered list, and the category / type edit right there. Esc or Close goes back to the same place; after a save the list shows the change. The old full-record link is still there ("Open the full record", and for browsers without scripts).

## 0.121.1
No database changes. The Ledger on Money > Look back is easier to read.
- Changed: **the Ledger fits on the screen without sideways scrolling**: Date, Account, Amount, Category, Description, Card member and Type in that order, with long account names and descriptions wrapping onto a second line.
- Added: **Card member** in the Ledger: who made each charge on a card statement (Amex and other cards whose statements list the member) as a column, a **Card member** filter, part of the word search and of the CSV (new `card_member` column). Credit cards such as Amex were already in the Account filter.

## 0.121.0
One small automatic database change (migration 058: a new `manual` column on transactions); the database also switches to WAL mode on first start. Phone app 0.12.0 has the same five tabs (Lists, Notes and Settings open from your picture at the top right).
- Changed: the web app's 2,250-line main file is **split**: Settings and first-run setup, and the phone API, now have their own files (audit A7). Every page and phone call works as before.
- Added: **Download the Ledger as a spreadsheet (.csv)**: every line the filters match, not just the page you see (date, account, description, category, type, amount, whether you edited it).
- Added: **you can fix a line's category and type in the Ledger** (Edit on a row; adults). A line you change stays as you set it: the category rules, the transfer pairing and the data check never overwrite it, and it shows an "edited" tag. Tick "Do the same for every line like this one" to remember the merchant for other lines too. Date, amount, account and description are never changed. (Database: a new `manual` column on transactions, added automatically.)
- Added: **Money > Look back > Ledger** lists every transaction from every account (checking, savings, cards, loans, investments) in one place. Pick a period (this week, month or year) and the dates fill in, or type your own; narrow by account, category, type (spending, income, transfer ...), amount from / to, or a word. Totals cover everything that matches; long lists come in pages.
- Changed: the 1,800-line list of validated edits is **split into five smaller files** (audit A9); every screen, the assistant and the phone sync call it the same way, so nothing looks different.
- Changed: a test now **fails if two parts of the app start importing each other in a circle** (audit A9); nothing changes for families.
- Changed: **every page, report and task now reads today's date from one place** (`dates.today()`), so no two parts of the app can disagree about the day. Nothing looks different; a test or demo can fix the date with `MITRAHOME_TODAY=YYYY-MM-DD`.
- Changed: when your backups are encrypted, **the database copies kept on this PC before an update or a purge are encrypted too** (with the same passphrase). Open one with `python data/backup.py open FILE.db.enc`. After removing a person, `python data/purge.py copies --yes` removes the older copies that still hold their rows (the one made just before the purge stays).
- Fixed: times the app writes (edits, hide and snooze, filed papers, data check runs) are **this PC's local time** in one format; some were UTC, so something done late in the evening could count as the next day.
- Fixed: the database's check for duplicate bank lines (one reference per account) is **tried again on every update** when it was skipped before; references that repeat are listed by `python data/migrate.py status`, never deleted.
- Fixed: an update from a zip **sets aside the code files the new release no longer has** (in the code backup folder, under dropped/), so a removed database update or page cannot run again. Nothing is deleted.
- Changed: the add-on packages (fastapi, uvicorn, jinja2, markdown, pypdf, cryptography) are **held to the versions the app was tested with**; a newer major or minor version arrives only with a release.
- Changed: **the database lets reading and writing happen at the same time** (WAL mode). A page, a phone sync or a report no longer waits for the inbox task or a backup to finish writing, so "busy, try again" should be rare. Backups, restores, updates and moving the household folder handle the database's side file. Nothing to do: the first start after the update switches it over.
- Fixed: the app **no longer starts on a database that still needs its updates** (for example after copying new code by hand). It says so and points to Start Mitra Home or `python onboard.py upgrade`, which back up the database and apply them first.
- Changed: **five tabs on every screen**: Today, Calendar, Add, Money and Family, on the left on a PC and along the bottom on a phone (Add is the big green button and carries the Inbox count). Everything else (To do, This month, Records, Wallet, Notes, Chat, Settings, Help on this page, light / dark, Log out) is under **More**: click your picture at the foot of the menu on a PC, or tap it at the top right on a phone. Money now shows in the Simple view too. Records and Wallet are part of Family.
- Changed: **the Inbox lives on Add**. Add has the drop box (scan, upload, paste or drag), then **Or type it in**: a tile each for a person or pet, a class, a date or reminder, a list item, a note, a subscription, a card for the wallet, or Chat, each opening the form where it lives; the Inbox's cards follow underneath. Old Inbox links open Add.
- Changed: **Records and the Wallet live under Family**. Family opens with everyone's cards, a search over every record and filed paper, and **Needs a look**; its chips open **People**, **Home**, **Cars**, **Papers & IDs** and the **Wallet**. Old Records links still work and the Records home opens Family. Help and messages say "Family > People > ..." instead of "Records > People > ...".
- Changed: **Finance and This month are one place: Money**. Its chips switch between **Overview** (this month in, out, saved and left, then the lanes), **This month** (spending by category, budget, bills, subscriptions, upkeep; any month), **Pay**, **Keep** and **Look back**; inside a lane a second row of chips picks its part. Money shows in the Simple view too. Old Finance and This month links open the same place in Money.
- Changed: **To do is part of Today**. Today lists everything in one place: **Late**, **Today**, **This week**, and **Later this month** folded away underneath. Every row has Done (or Paid) and the **⋯** menu to snooze it 1, 7 or 30 days, hide it or open its record; **Documents** (this week, weekly digest, family meeting, emergency sheet) sit at the foot of the list. Old To do links and bookmarks open Today. "Hidden from the Brief" in Settings > Agent is now "Hidden from Today".

## 0.120.0
No database changes.
- Fixed: on a **laptop running on battery** the scheduled jobs (daily brief, weekly digest, weekly backup, inbox check, phone drop box) were skipped without a word, and a job running when the plug came out was stopped. They now run on battery, and a run missed while the PC was asleep or off happens when it wakes. Tasks registered before this release keep the old behaviour until they are registered again: **Settings > Data > Runs on its own > Switch them all on** (or switch each job off and on).
- Changed: the Calendar's **week** starts today and shows the seven days ahead ("Oct 18 to 24"), so on a Sunday it no longer opens on the week that is ending; Prev and Next move by seven days, and a day picked in the month or year view opens the week from that day.
- Changed: **the first-run setup is five screens instead of ten**: Welcome, Your family (name, where you live, who lives with you), Your home (own or rent, cars, holidays you celebrate), Sign-in (PINs), and All set (check your answers, an optional AI helper, Set everything up). The same questions and checks; a setup someone saved half way resumes on the right screen. PIN boxes appear once you choose PINs, and on a phone the buttons stay in reach at the bottom.
- Changed: **a calm look everywhere**. The coloured cards at the top of Today, To do, Calendar, This month, Finance and Settings, the stat tiles and the Family cards are now light cards with dark text; colour is kept for what it means (late in red, people's colours on their avatars, chart series). Dark mode follows. The page background, lines and text are slightly warmer.
- Fixed: the Calendar's **year view** showed every month in two columns (one on a phone, a very long page); it is a normal 7-day grid again. The colour key under the calendar lists only the colours on screen and folds away; "Google Calendar: not connected" is one quiet line. Today is outlined instead of filled.
- Fixed: with **Help** open, the "New here?" tip and the "?" button no longer sit on top of the panel, and on a wide screen the page moves over instead of hiding behind it.
- Fixed: Family cards are all the same width; birthdays read "Mar 14" in Records; clearer labels: "Ask me the next question", "Missing statements", "Price rises", "Check everything".
- Changed: the **AI** form (first-run setup and Settings > Connections) shows only what applies to the provider you pick: nothing more for "No AI", no key box for Claude Code or Ollama, the Gemini billing box for Gemini only. The edit pencil, the "more" dots and the calendar's Prev / Next use the same line icons as the rest of the app.
- Fixed: a **child's page** on a phone had its top row squeezed into a short strip; name, light/dark and log out now sit at the right. On a PC, form buttons are as wide as their label instead of a whole column. Lists show a letter (not "[") for names that start with a bracket.
- Changed: **Today and To do show the same numbers**: "7 need you" is what is overdue plus what is due today, shown as the Overdue and Due today tiles, with This week beside them; To do no longer adds the coming week into its headline, and its bills line counts the overdue bill too (it said $96 where Today said $156). The phone app shows the PC's count when the PC sees more than the phone can ("1 needs you · 7 on the PC").
- Fixed: a family that chose **"Not now"** for the AI during setup could not file papers from the Inbox: the setup left the AI empty, which the Inbox read as Claude Code, so **File now** never appeared. Setup now saves "No AI", and File now reads what this PC can read by itself.
- Changed: **with No AI, bank and card statements are filed on this PC** when their lines add up to the printed balances (as PayPal statements, phone bills and school calendars already were). The first statement of a new account adds the account (its name as printed, last four digits only); a statement that does not add up stays in the Inbox and says which account it is for.
- Changed: the **"You are set up"** page is a calm summary with one button (Sign in, or Open Today) and three next steps, and says what is read without an AI. "1 vehicle needs a first service-log entry" (not "1 vehicles"), the same for ID documents.
- Fixed: **Missing statements** said "no statements yet" for an account whose statement was filed from the Inbox (the file name carries the account name and "x" + last four); both namings are read now.
- Fixed: the **Year-end** summary showed "archive/2026/&lt;category&gt;" instead of "archive/2026/<category>".
- Changed: **calmer warnings**. The Health check and the Home office questions are a quiet list with a red or amber dot instead of red boxes; list rows on a phone show a small status dot instead of a grey letter tile ("D" for every [DEMO] row); the "Everyone" avatar is a family icon.
- Changed: dates read like dates everywhere: seasonal jobs "Mar 1 to Apr 15" (not "03-01 to 04-15"), appointments "Oct 27, 15:30", paired phones "Sun, Oct 18". Green and amber labels and the year calendar's marked days are easier to read.
- Fixed (phone): fold-out rows such as "Add a card" and "Add a subscription" are a full finger high; the "..." menu on the last To do row could sit under the + button; calendar days and "See all" links are larger to tap; the tax checklist's table fits the screen.
- Changed: links are the app's green instead of bright blue (light and dark); Records and Finance no longer repeat the page name under the title; Today's top card wraps a long row onto two lines instead of cutting it; a row of chips that scrolls sideways on a phone fades at the edge so it is clear there is more.
- Changed: the app folder no longer carries files a family does not use: the copy of the website (`site/`, published from its own repository), and the roadmap, citation, funding and code-of-conduct files. Nothing changes in the app.
- Fixed: **sign-in from another device on the Wi-Fi** is much harder to guess: wrong PINs also count per device (5 wrong PINs lock it for 5 minutes, then 15 minutes, 1 hour, 6 hours, a day), whatever names it tries, and sign-in on this PC is never held by those locks.
- Fixed: a change made on a **phone** (a list item, a paid bill) could be reported as saved while the PC stopped before saving it; it is now saved on the phone's next sync.
- Changed: **updates keep only the newest copies** of the database (5) and of the code (3) they make in `backups_pre_upgrade`; copies you saved there yourself under another name are kept.
- Changed: **restore from backup** can be started only on this PC (from a phone it can be checked, not started), and the app comes back on the PC's own address.
- Fixed: the web app and the phone bots each write their own log file, so a log that cannot be rotated no longer loses later lines; signing in no longer holds up other pages; a phone's session survives a moment when the database is busy; update downloads are removed when the update ends.
- Fixed: the phones' change log is pruned every day (it grew without limit in a household without phones); Tax and Year-end totals are added up in cents.
- Fixed (phone): Today's swipe card is as tall as its tallest slide (no empty space, nothing cut off).

## 0.119.0
No database changes.
- Fixed: an **update, a restore or a database update** no longer runs while something else writes to the database. Running jobs (inbox filing, bank sync, backup) finish first; scheduled jobs skip their turn while it runs; pages wait a few seconds and then say the app is busy. Before, a write made during an update could be lost if the update had to put the database back.
- Fixed: if a database update stopped half way (the PC switched off), the copy from before it is no longer thrown away by the next start. The start stops and says how to put that copy back (`python data/migrate.py recover`).
- Changed: **Settings > Data > Updates > Update** now restarts the app with the new version by itself (the page comes back in about a minute). Before, the old program kept running with a mix of old and new code until you closed the window.
- Fixed: two settings saved at the same moment (for example a PIN on the PC and a phone's rename) can no longer undo each other: every change to `config/family.json` reads the file fresh and saves it under one lock.
- Fixed: after a crash in the middle of a save, reports, the backup and some pages failed with "attempt to write a readonly database" until something else opened the database; they now get past it themselves.
- Fixed: moving the household folder (`python onboard.py home`) moves everything first and changes the pointer last; if a move fails, what had moved goes back, so the app never points at a folder without the database.
- Changed: the **phone app** (0.10.0) tells the PC its version. A phone too old for the PC is told to install the new phone app instead of misreading the PC's answers, and the edits a phone offers now come from the PC.

## 0.118.0
No database changes.
- Fixed: **renaming a person** now also moves their **wallet cards** and their allowance budget line to the new name (a renamed person's library or gym card could no longer be edited). **Removing a person** (`purge.py person`) now removes their wallet cards, full card numbers included, and clears their name from the data check's history.
- Fixed: a **family.json that cannot be read** (for example after a hand edit with a typo) is no longer replaced by an almost empty one when something saves a setting; the change is refused with a sentence saying so, and the file stays as it was until you fix it or restore it. Two saves at the same moment can no longer leave a half-written file.
- Fixed: **File now** and the scheduled inbox check no longer read the inbox at the same time (a paper could be filed twice, or the run stopped half way). If the database is busy while a paper is being filed, the paper goes back to the Inbox for the next run instead of sitting in the archive without a record. A paper whose record was already saved stays filed (it is not filed a second time).
- Fixed: a change the database refuses now says so ("clashes with a record that is already there") instead of "the database is busy, try again", which never went away. Removing **duplicate charges** that each had a receipt no longer fails: the kept charge keeps its own receipt.
- Fixed: **pets** were offered a sign-in PIN (and counted in "4 of 5 with a PIN"). A PIN given to a pet earlier no longer signs in.
- Fixed: in the **first-run setup**, "Here is what I understood" showed every name and birthday one letter per line. Birthdays now read "March 14, 1980" there, "Mar 14" in Records > People, and dates on a child's page read "Fri, Oct 23". The family name box is full width.
- Changed: **buttons are a deeper green** so their white text is easy to read; in dark mode buttons have dark text on the light green (white on it was hard to read).
- Changed: on a **phone**, Help is under **More > Help on this page** instead of a round "?" that covered buttons and the More sheet. "Got it" on the "New here?" tip now hides it on every page, not one page at a time. The tip no longer covers the More sheet or the open Help panel.
- Fixed: the Calendar's week view showed today's "Nothing" in grey on the green day. Plain plurals ("1 thing to fix", "9 starter items").
- Changed: on a **phone**, every box you type in is at least 16 px (an iPhone no longer zooms the page when you tap a search box), buttons and section pills are at least 44 px tall, and no text is smaller than 12 px.
- New: an address that does not exist shows a page with **Go to Today** instead of a line of code.
- Changed: the **phone app** gets the household's currency with each sync, so amounts read "$60.00" (with the next phone app release).

## 0.117.3
Migration 057 (cash flow views), applied by the update.
- Fixed: **Cashflow** counted money that is not income. A family rule had typed TreasuryDirect payouts ("TREAS 310 MISC PAY") as income, and the starter rule for Mobil fuel ("MOBIL%") also caught "MOBILE CHECK DEPOSIT", so check deposits counted as negative fuel spending. The Mobil rule now needs a space after the name; a starter rule a release drops or narrows is removed from your database and the lines it typed are sorted again.
- Fixed: **Card payments** in Cashflow (and the monthly report) were small or negative: a card's own "payment received" line was added to the bank's payment of the same money. Only the payment out of the bank account counts now. Income counts only money that came in.
- New: **Finance > Deposits > Where deposits come from**: each source of money in, with what it counts as now (income, interest, money back from investments, own money moved, refund, tax refund, not sorted). Pick what it is and press **Remember**: every deposit from that source, earlier and later, follows (your word replaces an earlier category). Only pay and interest count as income.
- New: **Finance > Pay > PayPal** (shown once a PayPal statement is filed or a charge says PayPal): every payment from the PayPal statements month by month, matched or still waiting, with the card or bank charge it belongs to, and PayPal charges no statement line explains yet.
- Changed: **Remember** (Cards, This month, Deposits) now also re-sorts lines that already had a category when they match the text, so a correction takes effect on the past too.

## 0.117.2
No database changes.
- New: **PayPal statements** dropped in the Inbox are read on this PC without an AI (they used to wait in "Files to look at" because PayPal prints an email, not an account number). The paper is filed as a statement from PayPal, and every payment becomes a receipt (merchant, date, amount) that is matched to the card or bank charge it was paid with, so the real merchant shows next to a charge like "PAYPAL *...". The payments are not added as spending (the card statement already has them). A month with no activity is filed too. Only US dollar statements are read; anything else waits in the review queue with the reason.

## 0.117.1
No database changes.
- Fixed: **This month** counted money moved between your own accounts as spending (a $5,000 online transfer made 47% of a month "uncategorized"). Online transfers to and from accounts are now a starter rule typed `transfer`, and money sent abroad through Xoom is "international transfers". A bank line with no payee shows its bank text instead of a blank, and the dead "Open in Records" link under Uncategorized (it searched for the word) is gone.
- Fixed: money moved between your own bank accounts showed as a deposit (a $5,000 transfer into a money market account counted as income-like deposit and as spending on the other side). A payment out of one checking, savings or investment account and a deposit of the same cents into another within 3 days, each the only match for the other, are now both marked as a transfer when the category rules run. Anything unclear is left for you.
- New: under **Uncategorized** on This month, each merchant has the same **Remember** box as Finance > Cards. Choosing the category `transfer` (or `investing`) also sets the type, so those charges stop counting as spending.

## 0.117.0
No database changes.
- Fixed: card charges stayed **Uncategorized** (97% of one month on a real card). A category rule now also matches a merchant behind a wallet or processor tag (`AplPay`, `TST*`, `SQ *`, `PayPal *`) and the `(card x1234)` note, and charges that had a type but no category are filled in from the first matching rule every time rules run (after each import, and by the weekly data check).
- New: about 70 more starter rules for the US (grocery, restaurant, pharmacy, hardware, car care, transit, medical, insurance, subscriptions, fuel). Your own rules still win.
- New: **Finance > Cards > Uncategorized merchants**: the merchants whose charges still have no category, biggest first, each with the text to match and a category box. **Remember** saves a rule in `config/category_rules.json`, fills in every charge that matches and files later ones the same way. An **Uncategorized** tile shows the month's share.
- Changed: the Data check line for a bill still open after its due date says to mark it paid with the day you paid (the Inbox offers no remove for it).
- Docs: the website has a Data check section with new screenshots; the demo includes the Data check page.

## 0.116.0
Migrations 055 (`audit_runs`, `audit_findings`) and 056 (`audit_fixes`, `audit_findings.payload`), additive and applied by the update.
- New: **Data check** (Settings > Data > Data check). Every week, with the weekly digest, the app reads through the records for charges entered twice, transactions dated in the future or with no account, spending with no category, accounts with nothing new for 45 days, bills listed twice, paid with no date or still open 30 days after their due date, phone bills whose lines do not add up to the total, filed papers missing on disk and archive files that are not on record, plus the database's own integrity. Each finding is marked Numbers off, Decide or Note and opens its record. **Check now** runs it at once. A data score per run is kept for later reports. Read-only: no record is changed, no AI is used and nothing leaves the PC. The health check warns while the newest run found something to look at. Command line: `python data/audit.py run | show | history`.
- New: the data check **fixes what cannot be wrong** by itself before each run: spending with no category gets one when one of your category rules matches. Each fix is listed under **Fixes** on the Data check page with **Undo**.
- New: what needs a person goes to the **Inbox** (Money): a charge entered twice or a bill listed twice (**Remove the extra copies** keeps the first, or the paid bill), and a bill still open a month after its due date (**Mark it paid** with the day you paid). **Leave it as it is** stops the question for that finding. Removed copies can be put back from the Data check page. Decided on the PC only, not in the phone chat.
- New: **Explain with AI** on the Data check page (when an AI helper with an API key is set up): a few plain sentences on what the findings mean and which to look at first, and one line per finding. Only the finding lines are sent, with names masked; an answer with a number that is not in the findings, or a link, is thrown away; one answer per run, at most three new ones a day. The weekly task asks for it after the check.
- New: the **weekly digest** has a Data check section (score, trend, what to look at, fixes made that week) and the **monthly report** one with every run's score, the average, what the last run found, fixes and Inbox decisions that month.

## 0.115.0
Migration 054 (`wallet_cards.document_id`), additive and applied by the update.
- New: Wallet cards show **your own scan** on their back: tap a card to see it (IDs and insurance from filed papers, cards added from a photo). Scans stay on this PC; phones never get them.
- New: **Add a card from a photo** on the Wallet. When photo reading is on (Settings > Connections > AI helper, now "Let the AI read photos: receipts in the Inbox and wallet cards") the AI fills in the kind, name, issuer, last four, expiry and where the number is; you check every field in **Check the card**, then **Save card** files the photo with it (archive/<year>/ids/), or **Discard the photo**. Only the last four of a number come back from the AI; type a whole membership or library number yourself. Driver licences and passports still come in through the Inbox.
- New: Wallet **search** (plate, wifi, library, a name: every word must be on the card) and **Parking**: the plate as big as the screen allows for a meter or toll booth, a Copy button, the other cars one tap away, and the screen kept on. Installed as an app on a phone or PC, press and hold its icon for the **Plate** shortcut. Phone app 0.9.0 has the same Parking view on its Wallet tab.
- New: a wallet card with an expiry date (library, membership, health) is reminded 30 days before in To do, Today and the weekly digest, like IDs and the car registration; Settings > Household profile > How early to remind changes it. Wallet cards also show up in the Records search.
- Changed: Bank sync asks SimpleFIN for at most 45 days at a time (the first pull, or after a gap), as SimpleFIN now recommends; this ends the "Requested date range exceeds recommended range of 45 days" note. Older days come from your statements.

## 0.114.0
Migration 053 (`wallet_cards`; vehicles: color, body_type, plate, plate_region), additive and applied by the update.
- New: **Wallet** (side rail, under Every day): your cards in one place as card-shaped tiles grouped Car, People, Home and Memberships. Cars show a plate badge, colour and body type (Plate and colour on the car card); insurance, IDs and passports come from filed papers and Records; add membership, store, library, travel and health cards and home facts (Wi-Fi name, trash day, filter size) with Add a card. Tap a card to see where its number is printed on the real one. Expiring within 60 days shows the days left. Reference copies, not official IDs: no state seals, layouts or logos.
- Privacy: whole numbers are kept only for the plate (it is on the street) and for membership, store and library cards (a barcode needs them); known traveler, passport, licence, health and policy numbers stay last 4. Wallet cards are not readable by Chat's SQL look-up.
- Docs: README names the Wallet; the help explains the Keep tiles, the Finance filters and Bank sync; the website has a Wallet section with new screenshots.
- Phones: adult phones with the ID documents permission now also carry cars, current insurance policies and wallet cards (phone app 0.8.0 shows a Wallet tab). Paired phones take a fresh copy once.
- New: Finance > Deposits and Pay > Bills have **From** and **To** months and a **Category** filter next to the search; the search now matches every word anywhere in the row (Deposits: source, the bank's text, type, category and account; Bills: name, vendor, category, status). Keep opens on Deposits (Accounts second). Amounts in Finance tables are right-aligned.
- New: Settings > Connections > Bank sync has **Select all** and **Unselect all** above the list of SimpleFIN accounts.
- Changed: Finance > Keep shows **Cash** (checking and savings) and **Investments** (investment accounts: brokerage, TreasuryDirect T-bills and I bonds, CDs held there) as two tiles instead of one "Cash and investments"; the Keep lane on the Finance home says both. Net position carries the date of the latest balance.
- Changed: Finance tables on a PC show short dates (Oct 9) and the status as a coloured pill (paid, due, overdue), like Records and Work.

## 0.113.2
No database changes.
- Fixed: in dark mode tick boxes, drop-down pickers and scroll bars are dark too (unticked boxes were bright white, for example in Settings > Agent).
- Changed: the sign-in page shows **AI Agent** under the name, like the side rail.
- Docs: README names every page and how they are laid out, points to the website, the demo and the installers on the Releases page; the health check path in DATA.md and GOOGLE_CALENDAR.md is Settings > Data > Health check. Website: new Inbox and Records sections with fresh screenshots.

## 0.113.1
No database changes.
- Changed: **Work** looks like the other redesigned pages: **Finance** at the top goes back, the client is the heading, one row of chips for Billing / Hours / Schedule / Profile / Work calendar (and one for the contracts when there are several), short dates everywhere, missed hours under **Needs a look**, weeks, invoices and work calendar days as compact rows on a phone (tables on a PC, invoice status as a coloured pill), and the import and add forms folded.
- Fixed: help now matches the redesigned pages: hidden To do items and sign-in PINs are under Settings > Agent, rows open on a page of their own, and the Work page has a help entry (and a ? button).
- Fixed: the Family cards no longer push the page a few pixels sideways on a phone; Records search shows a proper subtitle.

## 0.113.0
No database changes.
- Changed: the **Inbox** is the way in for every paper. A big drop box takes files dragged anywhere onto the page, pasted screenshots or the file picker, and each file shows a bar while it is sent. A new **progress panel** shows every file being read and its step (in line, checking, reading, sorting, filed) and the outcome (filed as ..., needs you, already filed); it updates every two seconds while a run is going, also for the scheduled inbox check. With an AI helper (or the no-AI readers) set up, reading starts on its own after an upload; **File them now** runs in the background instead of holding the page.
- Changed: **Finance** has a home page: this month (in, out, saved, left; opens This month), three lanes Pay / Keep / Look back with one figure each (open bills in the next 14 days, net balances, typical month) and a short **Needs a look** list (overdue bills, budget lines over, overdue statements). Inside a lane one row of chips switches parts and **Finance** at the top goes back; the second and third rows of pills are gone.
- Changed: Finance lists read as **compact rows** on a phone (name, a grey line with the details, the amount and a coloured status on the right) instead of a box of label / value pairs per row; a PC keeps the tables. Budget lines are **progress bars** with a tick where spending would be by today; last month's budget and the suggested limits fold away. Bills: about half the height, Budget: about a quarter.
- Changed: **Trends** draws its charts on the page (no chart library): "Each month" shows only months with statements, "What changed" appears only when there are statements from the period before (until then **Where it goes**: share of spending), "Against last year" only when three months can be compared, and a run of months with no statements is one line in Month by month.
- Changed: **Records** has a home page: one search box for every record and filed paper, four lanes People / Home / Vehicles / Papers & IDs with one figure each (open items, upkeep due, vehicles, papers filed) and a **Needs a look** list (overdue items, IDs and car registrations or inspections running out, policies ending in 30 days, upkeep due, critical facts to confirm). Inside an area **Records** at the top goes back and one row of chips switches parts (the two rows of pills are gone).
- Changed: Records lists read as **compact rows** on a phone (name, a grey line with the details, a short date on the right and an **overdue / expired / in 12 days** pill); a PC keeps the tables with short dates and the same pill. One record opens on a page of its own: its name as the heading, the fields as a grid with readable names and dates, the paper with Download, the change form, and the change history folded.
- Changed: **Settings** opens on a summary: the household profile as a bar with **Answer next**, one card per group (Agent, Connections, Phones, Data) with how it stands (brief time and PINs, how many connections are on, phones paired, health warnings), and **Needs a look** with the health check's warnings. Inside a group **Settings** at the top goes back and one row of chips switches groups; each card folds to its heading and a one-line hint (the main card of each group opens), a card stays open after you save in it, and a link to a card opens it. The profile meter is a set of bars.
- Changed: **Notes** has one search box with a row of kind chips under it (All, Notes, Places, Deals, ... with counts); tag, who added it and archived items sit under **More filters**. Pinned items are coloured cards in a grid; the rest are compact rows with a kind icon, the site or address, the note (three lines) and tags, and Pin / Tags / Archive behind a **...** menu. A deal ending within two weeks shows **ends in N days**.
- Changed: open Inbox items are **grouped by category**: Files to look at, Money, Renewals and documents, Family and household, Calendar, app updates. The All view shows the first three of each with **Show all**; the chips at the top (with counts) or **Work through these** show one group. The old Files / Decisions / Questions switch is gone.

## 0.112.0
No database changes.
- New: **Chat answers "How do I ...?"** from the same help text, with no AI and no network: "How do I add a birthday?", "how can I mark a bill paid", "where do I add my passport" get the steps for that part and a link to it on the Help page. A new chip **How do I ...?** shows examples. With an AI connected, questions the help does not cover still go to the AI.
- Changed: the **first-run setup** is laid out for a PC or laptop: the question and its form on the left, and on the right **About this step** (why it is asked, how to type it, what happens next) and **Your answers so far** with a **Change** button for each earlier step. Earlier answers no longer pile up above the form, so each step fits on one screen. The AI step has one main button (Continue; the AI card's Save is secondary), the People box shows an example, and the final summary also lists home, cars, PINs and the AI. On a phone the help and answers sit under the form.
- New: **help on every page**. A round **?** button (bottom right) opens a side panel that says what the page is for and exactly how to add, change, mark done or snooze things there, with the real button names and links to the right Records part. **Help** (`/help`) lists every page's help with a word search. Adults only; no AI, no network. It covers every main page and every part of Records (People, Home, Vehicles, Papers and IDs) and Finance: the panel follows the part you have open. The first time you open a page, a small tip next to the **?** says it is there ("Got it" hides it, remembered in this browser).
- Changed: on a **Mac**, "Runs on its own" uses launchd LaunchAgents (`~/Library/LaunchAgents/ai.mitrahome.*.plist`) instead of cron, which needed Full Disk Access and failed silently. Switching a job on or off, its state in Settings > Data, the setup wizard and `python data/task_register.py remove` all follow; Mitra Home cron lines from before are removed. Linux keeps cron.

## 0.111.0
No database changes.
- Changed: the number tiles on Finance (every part and Trends), Records and Work use the story-card look (gradient tiles, white text); pinned Notes are gradient cards.
- New: **To do at a glance** (count, overdue, next 7 days, bills; by kind; by person) as a story card over the list, and **Family** tiles as gradient cards in each person's colour with their count, next item and overdue badge.
- New: **Calendar at a glance**: a story card over the week and month views. What is on (how many things, the top kinds as coloured bars, the busiest day), Who (per person) and Don't miss (birthdays, holidays, school closures, renewals). Today's day in the week and month grids gets the green card look.
- New: **day card on Today**: the same story-card look as This month. Your day (how many need you, overdue, on today, this week, the top three), On today (times, what is coming up, a 7-day bar chart) and Money (bills in the next 30 days, overdue, this month's spending donut, income / saved / kept). Tap or swipe on a phone; three cards side by side on a wide screen. Choosing a person shows their two cards (no money).
- Changed: **sidebar** fits without scrolling: Money and Everything else fold (remembered), light / dark and log out are icons, "AI Agent" under the name, bigger logo. Chat moved to Today next to Add or scan.
- New: **monthly summary card** on This month, as a phone story card: tap or swipe left / right through Overview (donut by category, income / spent / saved / left), Cash flow (fixed costs, everyday spending, saved, left, where the income came from), Where it went (every category against last month, budget tick), Six months (income and spending bars, month-end pace while the month runs) and Highlights (biggest everyday buy, top place, busiest day, subscriptions, bills ahead). Month picker with previous / next arrows; every category below (beside it on a PC) with all its charges, biggest first or by date. Saved now counts money moved into savings accounts as well as investment transfers.
- New: **New version notice**. The morning task looks once a day for a newer release (Settings > Data > Updates >
  "Check for new versions every day", on by default; off = no network call). Only api.github.com is contacted and
  nothing about the family is sent. A newer release becomes one Inbox item ("Update now" runs the same signed update
  as Settings, adults only; "Later" asks again in a week) and a short line on Today and the Brief for adults. A failed
  look stays quiet; after 7 days of failures the health check says so (usually a missing or expired update token).

## 0.110.0
Migrations 048 (`activity_schedules`), 049 (`calendar_days`), 050 (`member_info`), 051 (members: school, grade, grad_year, relation) and 052 (`home_contacts`), additive and applied by `python onboard.py update`.
- New: **First-run setup, refreshed**: Mitra Home logo and name at the top, "Hi, I am Mitra, your Mitra Home AI agent"
  welcome, a step bar with each step's name (a slim progress bar on phones), the agent's bubbles carry the logo, climate
  and own / rent as tap tiles, country names instead of codes, and the family's currency picked from a list that
  follows the country until you choose one. United States is listed first and is the default.
- New: setup asks which **religious or cultural traditions** the family celebrates (Hindu, Muslim, Christian, Jewish,
  Sikh, Buddhist, Jain, Lunar New Year, or typed, such as "Hindu (Telugu)"). With an AI connected, their holidays and
  festivals are looked up once a year (only the tradition, year and country are sent) and wait in the Inbox for an
  adult to accept, on top of the country's public holidays.
- New: **school calendars without AI**. Drop the district's year calendar (a PDF with a text layer, lines such as
  "Nov 25-27 Thanksgiving Holiday") in the Inbox: the days off and early dismissals are read on this PC and wait in the
  Inbox for an adult to accept. Other layouts still go to the family's AI. With no AI chosen, the inbox check and
  Inbox > File now still file school calendars and phone bills.
- New: **daylight saving clock changes** on the Calendar, Brief and Today ("Clocks change"; US and Canada 2nd Sunday of
  March / 1st Sunday of November, UK last Sunday of March / October; not in Arizona, Hawaii or Saskatchewan).
- New: setup's Home step asks owners for the next **school tax** and **property tax** due dates (US; property tax
  elsewhere). Each becomes a yearly bill; once marked paid, next year's is added. Any yearly bill now rolls forward the
  same way.
- Changed: **every form has the setup look**: clearer fields with a green focus ring, red edge on a field that is not
  filled in right, choices as tap tiles (Settings > How much to show, linking a receipt to a charge), bigger touch
  targets, and buttons that show when they are busy or not available.
- Changed: **folder names**. Backups now go to `Mitra-Home-Backup` next to the household folder, and a new install's
  household folder is `Mitra-Home-Data`. `python onboard.py update` renames an existing `MitraHome_backups` (or
  `FamilyAgent_backups`) folder to `Mitra-Home-Backup`; if the rename cannot happen (a file open), the old folder keeps
  working. An existing household folder keeps its name. Nothing to do.
- New: **Service contacts** (Records > Home > Service contacts): the plumber, furnace company, garage, electrician,
  handyman or anyone else the household has had work done by, with kind of work, phone, email, website, notes, last job,
  a rating and "use them again?". "Used them today" sets the last job; marking an upkeep job done with their name
  counts too (the upkeep form suggests the names). Stays on this PC (not sent to phones or the AI); the emergency sheet
  lists the ones you would use again.
- New: **Edit a family member** (adults): pencil on each Family tile opens the person in Records: fix a name typo (it follows the person through every record, setting and sign-in), role, birthday, how related, school / college / employer, grade or program, graduation year; their IDs and expiries are listed with a link to renew a passport or licence.
- New: **Critical info** per person (Records > People > Critical info): emergency contacts, medical facts (allergies,
  medicines, doctor, blood type) and school / care (school, teacher, caregiver, pickup). Adults add, change, confirm
  ("Still correct") and remove them. A fact not confirmed for 6 months (`info_review_months` in family.json) becomes
  one Inbox item per person. Stays on this PC: not sent to phones, chat or the AI; shown on the printed emergency sheet.
  No passwords, PINs or full numbers; a "Conditions" fact is allowed because this card never leaves the PC.
- New: **Simple / Advanced view** (Settings > Household profile > How much to show). Simple, the default for a new
  install, shows Today, Family, Calendar, Inbox, the Brief, This month, Records, Notes, and in Settings the profile,
  agent, phones and data. Advanced adds Finance (statements, budgets, trends), Chat, and in Settings the connections
  (AI provider, Google, Telegram / Discord, bank sync), optional packs, tax papers, reminder lead times and the
  technical facts. It only changes what is shown: no data is deleted, no feature is switched off, every page still
  opens by its address, and both views are free (nothing to do with Pro). An install that was already running keeps
  seeing everything (Advanced) until you choose Simple. Saved as `ui.mode` in `config/family.json`.
- New: **weekly classes and activities** (swimming Mon + Wed 17:00 at the YMCA, piano on Saturdays): Records > People >
  Classes and activities, Chat ("Sam has swimming Mon and Wed 5pm at the YMCA") or `python data/activities.py add`.
  Days, times, first and last day of the season, a lesson that is off, "not on days off school". Today's and
  tomorrow's classes show on Today and the Brief; every lesson on the Calendar and in What's on; each class is one
  repeating event in the calendar file (`brief/mitrahome.ics`); a child sees their own classes on their page.
  Only the name, place, days and times are kept.
- New: **public holidays** for the US (federal), the UK (England and Wales), Canada (federal) and India (national),
  worked out on this PC from rules in `packs/holidays/` (no internet, no AI). On the Calendar, the Brief, What's on and
  a child's page. On by default; Settings > Household profile > Optional features > Public holidays switches them off.
  Your state, province or nation adds its own days (from `region.state` in your profile): California, Hawaii,
  Illinois, Maine, Massachusetts, Texas, Washington; Alberta, British Columbia, Manitoba, Nova Scotia,
  Ontario, Quebec, Saskatchewan; Scotland and Northern Ireland. Others add theirs by hand.
- The weekly digest lists holidays, festivals and days off for the next 30 days and this week's classes; the
  "this week" page lists classes and days off. Your traditions' days are left out of both, since they can be copied
  to Drive.
- New: **holidays, festivals and days off school** of your own (Records > People > Holidays and dates, Chat, or
  `python data/calendar_days.py add`): one day or a break, for the household or one child. A class marked "not on
  days off school" skips them.
- New, optional: **your family's traditions** (Settings > Household profile > Traditions and holidays): religious,
  cultural or regional, one per line. With the yearly look-up on, your AI is asked once a year for their dates (this
  year's at once, next year's from October 1). It is sent only the tradition's name, the year and the country. The
  dates wait in the Inbox ("Add them to the calendar" / "Leave them out"); nothing shows before you accept. Your
  traditions stay in `config/family.json` on this PC: never on phones, Drive or a chat bot.
- New: a **school calendar** paper (district PDF) dropped in the Inbox is read into its no-school days, breaks and
  early dismissals, which wait in the Inbox like the traditions' dates. Filed under `archive/<year>/school/`.
- Phones without the app: when Mitra Home runs "for phones", Settings > Phones shows the home Wi-Fi address
  as a QR code. Point the phone's camera at it, sign in with your name and PIN, and add it to the home screen. The
  code holds the address only.
- The Mitra Home logo sits beside the name in the side menu and on the sign-in page.
- Phones: two new sync sources, `activities` and `days` (docs/PHONE_API.md); each phone takes one full copy after the
  update. The phone app does not show them yet.
- The phone app's source moved to its own private repository (`rNetGit/mitra-home-companion`, with its history); the
  phone app package id is now `app.mitrahome`. The PC side of the phone protocol is written down in
  `docs/PHONE_API.md`. Nothing changes for families: the release zip never contained the phone app.

## 0.109.1
Released on the local test gate (1078 passed): GitHub Actions CI could not run (billing). No migration. The phone app is unchanged.
- The GitHub repository is now `rNetGit/mitra-home-ai-agent`: updates look there, and the README, contributing and
  release notes use the new address. Nothing to do: GitHub forwards the old address, so older installs and git clones
  keep updating, and a token set for updates still works.

## 0.109.0
Released on the local test gate (1078 passed): GitHub Actions CI could not run (billing). No migration. The phone app is unchanged.
- FamilyAgent is now **Mitra Home** everywhere: the starters (`Start Mitra Home.bat` / `.command` and the "for phones"
  ones), new household and backup folders (`MitraHome_home`, `MitraHome_backups`), scheduled tasks ("Mitra Home Daily
  Digest" ...), the Drive folder and Gmail label for new setups (`MitraHome`), the calendar file (`brief/mitrahome.ics`),
  the log (`logs/mitrahome.log`) and secret names (`MITRAHOME_...` in `config/secrets.env`).
- Nothing to do for an existing install. It keeps its household folder, backup folder, Drive folder, Gmail label and
  saved keys (`FAMILYAGENT_...` names are still read; the next save writes the new name). `python onboard.py update`
  moves scheduled tasks and phone-bot start-up to the new names, so nothing runs twice. An old `Start FamilyAgent`
  file left in a zip install still works; use the new `Start Mitra Home` ones from now on. If you set `FAMILYAGENT_TOKEN` for updates, it still works.
- Unchanged on purpose: the GitHub repository name, and ids that older installs or your phone's calendar already rely on.

## 0.108.2
Released on the local test gate (1071 passed): GitHub Actions CI could not run (billing). No migration. The phone app source changed
(it reaches phones with a new Android build; compiled, not yet checked on an emulator).
- Security Lows from the 2026-10-14 audit: phone ids reject non-ASCII digits, a pairing code can be redeemed only once even when two requests race, the upload content check sees through a byte-order mark or blank lines before a web page or program, and a duplicate scan no longer says where the copy is.
- Offline AI through your own Claude CLI no longer loads your global MCP servers.
- Phone app: the screen cannot be captured while the app lock is on; the daily reminder keeps today's and upcoming rows when there are very many overdue ones, and it stops (and deletes its rows) when the phone has not synced with the PC for 14 days.
- GitHub CI runs one OS on pushes and the full set only on release tags (saves minutes).

## 0.108.1
Released on the local test gate (1069 passed): GitHub Actions CI could not run (billing). No migration, PC side only (the phone app is unchanged).
- Wrong phone pairing codes no longer lock everyone out of PIN sign-in, and a sign-in lock starts again at its shortest length after an hour of quiet.
- "Start FamilyAgent for phones" on a first run (no PIN yet) now opens the app for this PC only instead of stopping.

## 0.108.0
Released on the local test gate (1068 passed): GitHub Actions CI could not run (billing). No migration. The phone app is 0.7.0; it reaches
phones with a new Android build. Checked on the emulator.
- PC sidebar: pages sit under three small labels (Every day, Money, Everything else) with Settings and the version at the bottom. Phones are unchanged.
- Phone app: reminder and lock are switches, the bottom bar has icons and tab roles, the "Checking…" pill keeps the last state until the PC answers, and a row's status sits in its meta line when it has a Done / Paid button.

## 0.107.0
Released on the local test gate (1068 passed): GitHub Actions CI could not run (billing). No migration. The phone changes
are not checked on an emulator yet.
- Phone app "Today first": the hero says "Hi NAME", the date and the summary line; Needs you comes before On today; the
  bills card follows Needs you when a bill is overdue; one tap strip shows scans and changes waiting for the home Wi-Fi;
  the "Phone" tab is now "Settings" with a number badge and its cards ordered by use. The full-app button is a small pill
  in the hero. Phone web files only (`mobile/www`); needs a new phone build to reach phones.
- PC app: the Brief page is now called "To do" (rail, bottom bar, heading). The daily brief itself keeps its name.

## 0.106.1
Released on the local test gate (1068 passed): GitHub Actions CI could not run (billing). No migration, nothing to do.
- Updating no longer prints "migrate_025_constraints.py was edited after it was applied": a migration changed on
  purpose after it shipped is re-recorded quietly (`REVISED` in `data/migrate.py`); any other edit is still reported.

## 0.106.0
Released on the local test gate (1067 passed): GitHub Actions CI could not run (billing). Migration 047 runs
automatically on update.
Bank sync through SimpleFIN (opt-in, Pro households). Nothing to do for families who do not want it.
- Settings > Connections > Bank sync (SimpleFIN): paste a one-time setup token from SimpleFIN Bridge (a service the
  family pays themselves, about $1.50 a month) on this PC, tick the accounts to pull, Pull now, Forget. Balances and new
  transactions then arrive every morning with the daily brief: one read-only request to the bridge, no bank login
  here, the access URL kept write-only in `config/secrets.env`. Same dedupe and after-import steps as a statement.
  A failed pull is one Inbox item (not retried before the next morning); the health check warns after three days
  without a good pull. Migration 047 adds `accounts.simplefin_id`. docs/BANK_SYNC.md.
- Statements and bank sync never double a payment: days a statement covers are skipped, a bank-sync row and a statement
  row of the same amount within 3 days are one payment (both ways, card CSV imports too), and when that is not clear
  the Inbox asks "Possible duplicate" (remove the bank-sync copy / keep both). `python data/bank_sync.py dedupe [--yes]`
  cleans up older copies. The first pull asks for 89 days (the bridge's limit is 90).
Data fixes from the 2026-10-14 audit (M10-M14, M16). Nothing to do for families.
- Phones: removing a person from the household now revokes their phones instead of deleting them, so each phone is
  told to wipe its copy the next time it calls. The person's name also leaves recipes, the meal plan, decided Inbox
  items and phone records, and their allowance line leaves the budget.
- Running migration 025 again by hand (as `migrate.py status` suggests after fixing bad rows) no longer drops the
  phone-sync triggers; every `migrate.py` run puts them back.
- Your own category rules (config/category_rules.json) always win over the starter rules, and changing a rule's
  category takes effect on the next run (it used to keep the old one).
- The same month imported twice from different files (a PDF without references and a CSV with them) is no longer
  doubled: equal date and amount count as the same transaction, one to one.
- A busy ("locked") database now shows as an error instead of an empty "nothing due" list.
- Phones after a restore: a restored database gets a new sync id, so every paired phone takes a full fresh copy
  instead of missing changes (audit M9).
- Phone edits are made exactly once: the edit's id is claimed before the change, so a repeat (a retry racing the
  first send, or after a crash) is answered "already received"; when one edit has to wait, the later ones wait too,
  so they land in the order they were made (audit M15).
- The automatic revoke of a phone whose person left the household is now written to `logs/admin_audit.log`. Docs
  brought in line with the app (README, SECURITY.md, THREAT_MODEL.md, RELEASING.md: HTTPS-only phones, file-backed
  sign-in throttle, names in Chat, the local gate when CI cannot run); old Streamlit leftovers removed.
- Restoring a backup made by a newer version is refused before anything changes (it used to swap the database in
  and then fail to update it). Sign-in and phone pairing read at most their small cap of a request body, so a huge
  request cannot fill memory; phone edits accept plain digits only as ids.
Finance. Nothing to do for families.
- Finance > Cards: a Card picker ("All cards" or one card) before the month, when the family has more than one card;
  the totals, the list and the CSV download follow it. The filter row wraps on phones instead of squeezing the search.
Today first (UX review of 2026-10-15). Nothing to do for families.
- Today: "Needs you" is the first block (phones stack it on top), headings carry counts, and every Needs you row has
  Done or Paid right there (the same ops as the Brief; Undo after a paid bill). The Money card says what is overdue
  before the 30-day total.
- Inbox on phones: a real "Choose files or take a photo" button instead of the bare file picker, the filter bar
  spans the screen, each card keeps its choices on one row (the form opens under them), one status line, and the "+"
  button stays white on the Inbox page.
Security hardening from the 2026-10-14 audit. Nothing to do for families.
- The agent fence is tighter: an agent may move or copy exactly one file from `inbox/` into `archive/` (a third
  operand used to make another folder the destination), may never write a program file anywhere, and may not run the
  admin scripts (`purge`, `restore_backup`, `auth`, `devices`, `updater`, bots, Google, exports): those are for the
  family from Settings or a terminal. Chained commands are now also split on a single `&`; backticks and `$(...)`
  are refused.
- "Open on this PC" (nobody has a PIN yet) is checked on every request: a phone on the Wi-Fi never gets in without a
  PIN, even if the last PIN is removed while the app runs.
- A `config/family.json` that exists but cannot be read (a hand edit gone wrong) now locks everyone out with a clear
  message instead of opening the app to everyone, no longer starts the first run over the broken file, and pauses
  paired phones (they try again later) instead of revoking all of them.
- Dates must be real days (migration 046): the database checks used to look only at the shape of a date, so
  2026-02-30 could be stored and the weekly report then crashed. Every date column now refuses a day that does not
  exist; a stored one is moved to the last day of its month once (printed during the update). The reports and
  detectors that read dates skip a value they cannot read instead of stopping.
- Card CSV import (`import_card_txns.py`) reads the date column in the usual formats and stops on one it cannot read.
- CI runs the whole test suite in one step; the leftover Streamlit dashboard tests are gone.
- Mitra Home phone app 0.6.0 (`mobile/`, not part of this PC release): scans waiting to be sent are now sealed on
  the phone like the copy; a PC that no longer knows the phone (restored from an older backup) clears the pairing
  but keeps the waiting scans and changes for the next pairing; the app lock can no longer be held open by a
  dialog that never left the app, and falls back to the screen lock instead of switching itself off when
  biometrics are unavailable; release builds refuse to run unsigned by accident.

## 0.105.0
Groundwork for the Mitra Home phone app (Android; families will get it from the app store). Nothing to do for families.
- The first-run chat now points to Settings > Phones for phones, and calls Google (your calendar, bills that arrive by
  email) an advanced extra under Settings > Connections. Settings > Connections says the same.
- Phones paired before 0.104 now also get "Open the full app on the home Wi-Fi" (0.104 gave it only to phones paired
  from then on). An adult can turn it off per phone in Settings > Phones.
- Database: migration 045 updates the phones' settings (applied by `python onboard.py update`).
- For maintainers: the app's source is in `mobile/` (Capacitor, Android first). It is not part of an install or the
  release zip; see `mobile/README.md`.

## 0.104.0
Ready for the phone app to open the full app on the home Wi-Fi. Nothing to do for families.
- A paired phone can open the app as its person without typing the PIN. The phone gets a one-time sign-in that works
  once, for one minute, over the encrypted home Wi-Fi link only; the app then shows exactly what that person's PIN
  would (children and guests get their own page).
- Settings > Phones has a new choice per phone, "Open the full app on the home Wi-Fi" (on by default). Turning it off
  or removing the phone signs that phone out of the app within a minute; a changed PIN signs it out at once.
- The person needs a sign-in PIN first (Settings > Agent); without one the phone still pairs, syncs and sends scans.
- Phones paired before this release start over with a fresh copy the next time they sync (their settings changed).

## 0.103.0
Ready for the phone app to keep its own copy. Nothing to do for families.
- A paired phone can now fetch what changed since it last asked, and only what its person may see and its settings in
  Settings > Phones allow: adults get bills, calendar, notes and lists by default (finance detail and ID documents only
  when an adult turns them on; accounts by last four digits only); children and guests get their own items, their own
  appointments and the family lists, never money or notes. Scans, statements and other files are never copied to a phone.
- Changing what a phone may carry, a change of the person's role, or restoring a backup makes the phone start over
  with a fresh copy; a removed list, item or bill disappears from the phone too.
- A phone can send small edits it made while away (add or tick a list item, finish an item, mark a bill paid, save a
  note). Each goes through the same checks as the app, as that person, and is logged like every other edit. If the
  item changed on the PC meanwhile, the PC wins and the phone is told why. A phone that sends the same edit twice
  changes nothing the second time.
- Database: migration 044 adds `sync_log` (which rows changed, no content; entries older than 90 days are pruned) and
  `sync_ops` (applied by `python onboard.py update`).

## 0.102.0
Ready for scans from the phone app. Nothing to do for families.
- A paired phone with "Send scans to the Inbox" on can send a scan or file straight into the inbox over the
  encrypted home Wi-Fi link. Each file gets the same checks as the Inbox page (type, size, content matches the name,
  never a program or web page), and it must arrive unchanged (checked by its fingerprint).
- A phone that loses the connection and sends again never makes a second copy, and a paper that is already waiting,
  already filed or already sent is not saved twice. At most 50 files per phone per day.
- Files saved at the same moment can never overwrite each other (all uploads: Inbox page, phone bot, phones).
- Database: migration 043 adds `device_uploads` (applied by `python onboard.py update`).

## 0.101.0
Phones: encrypted on the home Wi-Fi, and pairing for the coming phone app. Families who use phones: see below.
- When the app is started for phones, phones now use **https** at the app's port + 100 (for example
  `https://192.168.1.20:8701`), encrypted with a certificate this PC makes for itself. Plain http on the Wi-Fi is
  gone; the PC itself still uses `http://127.0.0.1:8601`. A phone's browser warns about the certificate the first
  time: continue only when the fingerprint matches the one in Settings > Phones (also printed in the start window).
- **To do (phones only):** open the new address on each phone and replace the old home-screen icon. If Windows
  Firewall asks, allow the new port with the `netsh` line the start window prints.
- Settings > Phones (adults, on this PC): add a phone with a one-time QR code (5 minutes, works once), see paired
  phones, choose what each may carry (adults: bills, calendar, notes, lists, scans; finance detail and ID documents
  off until turned on; children and guests: their own items, calendar and lists only, never money), and remove a
  lost phone. The phone app itself arrives in a later release.
- The certificate is not in backups: after a restore on a new PC, phones are paired again.
- Database: migration 042 adds `devices` and `device_pairings` (applied by `python onboard.py update`).

## 0.100.1
One look on every page, and a phone bottom bar. Nothing to do for families.
- Phone: the top strip of pages is replaced by a bottom bar (Today, Family, a round Add or scan button with the Inbox
  count, Brief, More). More opens a sheet with every other page, light / dark and Log out; a tap outside or Escape
  closes it. Children and guests keep their own simple page.
- PC: the left rail shows who is signed in, the Inbox count, and an Add or scan button.
- Today has a coloured header. Corners, the hero colour and the sheet shadow are theme values (light and dark), so
  every page shares them.

## 0.100.0
A family-first Today page. Nothing to do for families.
- Today (the first page for adults): a greeting and one line ("2 on today, 3 need you"), person chips that show one
  member, a pet or the House, what is on today, the next seven days as a strip with a dot per person, Needs you (top 3,
  "See all" opens the Brief), This week (top 5), and on the side the money glance (bills due in 30 days, the next
  bill), house and car jobs and renewals. One layout: three columns on a PC, one column on a phone.
- Family: a tile per member, pet and the House with how many items, how many are overdue and the next one; tap a tile
  for everything that person has in the next 30 days.
- This month: spending against the budget so far, bills in the next 30 days, subscriptions (with cancel-before-charge
  warnings), house and car upkeep, renewals and papers.
- Brief: duplicates are merged (an appointment that is also a medical item shows once, with both kinds), every row
  shows whose it is, and the same person chips filter it.
- Expired papers come first, then overdue, then today, then the week; pills say how urgent ("Overdue 7d", "Today",
  "in 6d"); colour only for overdue and today.
- Children and guests keep their own page.

## 0.99.9
Wide tables are easier to read on a phone. Nothing to do for families.
- On a narrow screen, a table with five or more columns (Life items, Upkeep, Inventory, Bills and so on) shows one card
  per row, each line labelled with its column, instead of scrolling sideways.

## 0.99.8
Small clarity fixes. Nothing to do for families.
- Subscriptions: a service whose price went up once (steady before and after) is now proposed, at the new price.
- Health check: new "Update token" row; the update message says to look there.
- "Full check" says it asks the AI and checks every scheduled task on this PC.
- TRADEMARK.md covers the name Mitra Home.

## 0.99.7
Wide tables are easier to spot as scrollable on a phone. Nothing to do for families.
- On a narrow screen a table wider than the card now shows a clear shadow on the edge where more columns continue,
  plus a visible scrollbar under it, so columns such as due dates are not missed.

## 0.99.6
The Inbox stops asking "track as a bill?" about the places you shop. Nothing to do for families.
- A payee whose charges are all groceries, dining, fuel, personal care, cash withdrawals or pets (for bills also
  shopping, travel and entertainment) is no longer proposed as a bill, and the first six are no longer proposed as a
  subscription. Streaming and other subscriptions are unaffected. Cards already waiting for such a payee disappear on
  the next sync; you can still add anything by hand.

## 0.99.5
Chat without an AI finds more. Nothing to do for families.
- A word search in Chat now also lists matching records (bills, payments, policies, people and so on), not only saved
  items, list items and filed papers, so it agrees with the Records search. Adults only, as before.

## 0.99.4
A subscription you add by hand now finds its own charges. Nothing to do for families.
- Finance > Subscriptions > Add: the new subscription matches its name inside the bank's description (a subscription
  called "Netflix" matches "NETFLIX.COM 123"), so it shows its last charge and next date instead of "no charges found".
  Older hand-added ones keep working as before; edit them in the database only if you need a different match.
- `subscriptions.py accept` also keeps the payee name, like the Inbox button does.

## 0.99.3
Two walk-through fixes. Nothing to do for families.
- Inbox: when four or more cards are the same kind (for example fifteen "track as a bill?" payments), they fold under one
  heading with a count; open it and the group stays open while you work through it. Single cards stay as they were.
- Phones: tables wrap long text instead of pushing columns off the screen, show a soft edge when there is more to scroll
  to, and Finance > Cards lists the Amount right after the description.

## 0.99.2
Three fixes from a full walk-through of a sample household. Nothing to do for families; the update applies migration 041.
- Finance > Trends: months with no statements are gaps in the charts (they were drawn as $0, so the lines climbed up
  from zero). The month still running is shown as "so far" and kept out of the charts, the comparisons ("Spent -54% vs
  last month"), the typical month and the monthly report's sentences until it ends.
- Pets no longer get an empty passport row, so the Brief stops asking for a pet's passport expiry. Migration 041 removes
  the untouched ones already there; a pet passport you filled in stays.
- Records search results are headed "Search" instead of the name of whichever area was open.

## 0.99.1
Updates now work on drives that record no owner (USB sticks, exFAT, some external disks). Nothing to do for families.
- The updater tells git to trust the install folder for its own calls only; before this, a git install on such a
  drive stopped with "dubious ownership". Your global git settings are not changed.

## 0.99.0
The classic Streamlit dashboard is gone; the web app is the only app. Nothing to do for families: `Start FamilyAgent`
opens the web app now (port 8601 up; it was 8501), and an update installs the smaller set of packages by itself.
- Removed: `data/dashboard/`, `data/dashboard_app.py`, `data/dashboard_forms.py`, `run_dashboard.bat` / `.sh`, and
  Streamlit, pandas and altair from `requirements.txt` (the app needs fastapi, uvicorn and jinja2).
- `launch.py` starts only the web app; `--web` still works and changes nothing. A restore from backup starts the web
  app again. Phones: the address now ends in `:8601`.
- Kept and moved: the colour tokens and each person's light / dark choice (`data/look.py`), the inbox helpers
  (`inbox_data.py`), Chat's word search (`chat_data.py`), what children see (`limited_view.data`, also used by the
  phone bot).
- Tests: 63 tests that drove the Streamlit pages are gone with them (the web app's own tests cover the same flows);
  the launcher, requirements, language and restore tests now check the web app. The restore test still checks that a
  backup passphrase never goes on a command line.

## 0.98.0
No database change. The last screens that only the classic dashboard had are now in the web app.
- Work page (work contracts pack; Finance > Work > Open the work page): add a contract; Billing (a month's hours,
  amount, on / off site days, planned hours, weeks, pay days, record an invoice, mark invoices sent / paid / draft);
  Hours (one timesheet period day by day: hours and on / off site, blank clears a day; import a timesheet PDF / CSV /
  TXT with the inbox's file checks); Schedule (the repeating one- or two-week cycle); Profile; Work calendar (import
  one, add a day, pay days by rule).
- Settings > Household profile: optional features (festival calendar, work contracts, Amazon orders, shopping lists),
  tax papers (names only) and how early each kind of expiry is reminded.
- Settings > Data > Advanced: folders, the last run of each scheduled task, and the terminal command for each check
  that needs one (the only place in the web app that shows folders and commands).
- Inventory items link their filed receipt and manual. Finance > Budget shows suggested limits from the last six
  months, and the budget form offers allowance lines per child. Downloads: the tax checklist and year-end summary
  (.md), a month of card transactions (.csv; a cell that would start a spreadsheet formula is kept as text) and each
  briefing (.md).

## 0.97.0
No database change. Settings > Data in the web app does everything the classic page did.
- Back up now; Export all my data with a download link for the zip (served only from the exports folder).
- Restore from backup: pick a backup (passphrase for a locked one), Check this backup, then Restore after ticking the
  box. The web app closes, the restore runs on its own, and the web app starts again on the same port (and on the
  home Wi-Fi if it was); the page waits and comes back to Settings > Data, where you sign in again. The result of the
  last restore shows for three days.
- Make it run on its own (daily brief, weekly digest, weekly backup, optional two-hourly inbox check).
- Updates: Check for updates (asks GitHub only when pressed) and Update to the new version.
- Run full check (scheduled tasks, AI, phone bot) and the list of changes made in Settings.

## 0.96.0
No database change. Connections are set up in the web app (Settings > Connections, adults).
- AI provider: choose it, paste the key (saved on this PC, only its last four characters are ever shown), the
  consent and Gemini paid-tier boxes, receipt photos; a small test call after saving, and Test the AI now. The same
  form is on the setup's AI step.
- Phone bot (Telegram): save the bot token (checked with Telegram first), start / stop, start with this PC, and a
  one-time code to link a family member's phone.
- Google: the client file, sign in, which calendars to show, the calendar of its own (allow, settings, preview,
  apply, delete), Gmail (allow, label, check now) and disconnect.
- Keys, tokens, the client file and Google sign-ins are accepted only from a browser on this PC: on the home Wi-Fi
  the web app uses plain http, so a key typed on a phone could be read on that network.

## 0.95.0
No database change. The first run and the first PIN in the web app.
- A new install started with the web app (`python launch.py --web`) opens the setup on its own: the same questions as
  the first-run chat (rules, AI, family, where, people, home, cars, PINs), one step at a time, checked in plain
  language and saved as a draft after each step ("Save, finish later" picks up where you were). People are typed in
  one box and read back with a role to change; PINs are kept in memory only until "Set everything up", then stored as
  a hash. The last page offers the first Brief, the Inbox and Connections, or Sign in when PINs were set.
- Settings > Household profile: "Run the setup interview again" (adults, prefilled; Cancel changes nothing).
- With nobody holding a PIN, the web app on this PC can now change things (it was read-only): the page gives the
  browser a session of its own with a security token. Setting the first PIN (Settings > Agent) ends it, so everyone
  signs in from then on. Phones still need a PIN first.
- The starter no longer refuses `--web` on a brand-new install.

## 0.94.0
No database change. Children and guests have their own page in the web app.
- Signing in with a limited PIN opens "Hi <name>": my things (Done on each), our lists (family lists only: add, tick,
  untick, clear ticked), our saved links (search, save a link or note, a few a day), the next two weeks and birthdays.
  No money, no accounts, no AI, no other page; every change goes through the same checks as before.
- An adult page opened by a child now says "This page is for adults" with a way back, not a link to the classic
  dashboard.

## 0.93.0
No change to the app: documentation.
- README, SETUP_NEW_FAMILY, docs/CHAT, docs/DATA, docs/GOOGLE_CALENDAR and docs/GOOGLE_GMAIL call the product Mitra Home.
  Names that identify things already installed stay FamilyAgent: the repository, the app and household folders, the
  starters (`Start FamilyAgent.bat`), scheduled tasks, the Drive folder and the Gmail label.
- README and SETUP_NEW_FAMILY describe the web app (`python launch.py --web`) and what still opens in the classic
  dashboard. CLAUDE.md's web app row lists every edit form and Settings.

## 0.92.0
No database change. Settings in the web app (adults), in the same four groups as the classic page.
- Household profile: how complete the profile is, Answer next (the next question goes to the top of the Inbox), and
  the full names as printed on your papers (masked before anything goes to the AI).
- Agent: the agent profile (name, tone, daily brief and weekly digest times, what the Brief keeps an eye on, who may
  approve from a phone), sign-in PINs (your own current PIN is asked, wrong tries are throttled as at sign-in; a
  changed PIN signs that person out everywhere, so changing your own takes you to the sign-in page), and the items
  hidden from the Brief with Restore.
- Connections: AI, phone bot and Google with a status line each (no call to Telegram or Google when the page opens).
  Keys and tokens are still typed only in the classic Settings, where Test also lives.
- Data: the health check and the calendar file download. Back up, restore, export, updates, the full check and the
  change log stay in the classic Settings for now.
- The rail's Settings now opens this page.

## 0.91.0
No database change. Lists and meals in the web app (Records > Home, adults).
- Lists: "Start a list" (name, kind, adults only); open a list to see it as a checklist: tick and untick items, remove
  one, add one (how many, for whom), clear the ticked ones, archive the list (with a Yes tick; its items are kept).
- Meals: "Plan a meal" (day, meal, a recipe name or any text; replaces what was planned there), "Save a recipe" (one
  ingredient per line; the same name replaces it), "Put the planned meals on a shopping list" (a date range, staples
  left out). Open a planned meal to take it off the plan, or a recipe to archive it.
- Children and guests still tick family lists in the classic dashboard (these pages are for adults).

## 0.90.0
No database change. Papers > Expiries and IDs in the web app: an "Add an ID document" form (whose, which document,
expiry date, last four characters; one already recorded for that person gets the new date) and, on one document,
"Renewed? New expiry" (date and last four). Never the whole number.

## 0.89.0
No database change. Vehicles in the web app: an "Add a vehicle" form (make, model, year; the same one is not added
twice) and, on one vehicle, Log a service (service, date, odometer with the last reading shown, cost, shop; never a
future date). The next due date follows from the service, as in the classic Records and Chat.

## 0.88.0
No database change. Home in the web app can now change the inventory and log seasonal jobs.
- Inventory: an "Add a thing to the inventory" form (name, category, brand and model, where it is, bought on, price,
  store, warranty end or years, serial last 4, notes); on one thing, Change it (blank clears a field) and "Sold, thrown
  out or lost" (with the date and a Yes tick; it leaves the reminders, its history stays). Receipts and manuals are still
  linked in the classic Records.
- Upkeep: a new "Seasonal jobs" list (window, who, where, last done); open one to log it as done (never a future date).
- Every change goes through the same checks and logs/edits.log line as the classic forms and Chat.

## 0.87.0
No database change. Finance > Keep in the web app can now change budget lines, loans and accounts.
- Budget and loans: a "Set or remove a budget line" form (a category that already has a line gets the new limit; tick
  Remove to drop it) and an "Add a loan" form (kind, lender, balance, rate, payment, payoff date, all but the name
  optional).
- One loan: Update it (new balance, recorded with today's date; rate; payment; payoff date) and Paid off (with a
  Yes tick; it leaves the list, its history stays) or make it active again.
- Accounts: an "Add an account" form (name, type, last four digits only, owner); a second account ending in the same
  four digits is refused, so statements can still be told apart.
- Every change goes through the same checks and logs/edits.log line as the classic Finance forms and Chat.

## 0.86.1
No change for families: faster, leaner tests for maintainers.
- The demo family is built once per test run and copied for each test module, instead of being migrated and seeded
  again for every module.
- `python scripts/smoke_test.py` (the release gate) now runs every test, in parallel when `pytest-xdist` is installed
  (added to requirements-dev.txt); `--serial` runs it in one process. The `smoke` marker is gone, so the gate and the
  full suite are the same run.
- Removed 9 tests that repeated another test (their few unique checks moved into the test they duplicated): the
  classic Settings page check (covered by the Settings groups test), Brief paid / snooze (covered by the paid, undo,
  snooze and restore test), the backup folder name, the receipts and work page renders (moved into their forms tests),
  the two run-script flag greps (now one test in test_launch.py), an always-true database check, and a members sync
  test that migrated a fresh copy (now reads the seeded copy).
- Tests that imported modules from another folder now clean up after themselves. A test of the household folder left its
  copy's updater loaded, which made four updater / signing tests fail in a full run (they passed alone).
- The calendar file's "no long digit runs" check skips event ids (hashes that can hold digits by chance).
- Full suite: about 4 minutes in parallel, was about 16.5 minutes.

## 0.86.0
No database change. Finance > Pay in the web app can now change bills, subscriptions and receipts.
- Bills: open a bill and Mark it paid (with the date it was paid, never a future one); a paid bill can be marked not
  paid again.
- Subscriptions: an Add form on the list; on one subscription Decide (not reviewed yet / keep / cancel / cancelled, with
  an optional note; cancelled flags any later charge) and Stop tracking it / Track it again. Nothing is cancelled for
  you.
- Receipts: an Add form on the list; on one receipt waiting for a charge, pick one of the charges it could be and Link,
  or No charge expected (cash, gift card, refund); a matched receipt can be unlinked.
- Every change goes through the same checks as the classic forms and is written to the change log.
- A Finance row opened in Records no longer shows the People lists under it; its heading names the Finance part and
  "Show all" goes back there. The Home page text says what has moved to the web app so far.

## 0.85.0
No database change. Finance in the web app now shows every part, not only Trends.
- Pay / Keep / Look back buttons, then the parts of that group: bills (by month, with a search), receipts, phone
  bills, subscriptions, Amazon orders, cards (by month, with a search), statement watch, price spikes, accounts,
  deposits (by month), budget and loans, card benefits, cashflow, trends, tax papers and year-end (this year or last),
  home office and work.
- Looking up only: a row opens in full on the Records page (every field, its paper, its changes), and "Show all" there
  goes back to that Finance part. Adding and changing money records stays in the classic dashboard or Chat for now.
- Links to a Finance part from Records now open here instead of the classic dashboard.

## 0.84.0
No database change. Records in the web app can now change the People area.
- Life items (school, medical, pet, chores...): an Add form on the list; on one item Change it (what, for whom, where,
  due date, repeat, cost), Mark done (a repeating item moves to its next date) and Remove (needs a tick first; history
  is kept).
- People and pets: an Add form; on one person change the role, birthday and birth year (also written to
  `config/family.json`, as in the classic dashboard).
- Checkups and upkeep jobs: on one of them, Record it as done (date, where / who).
- Every change goes through the same checks and the same change log as the classic Records forms; the result shows
  once at the top of the page. Home, Vehicles and Papers & IDs are still changed in the classic dashboard.

## 0.83.2
No database change. Fix: a mistyped role in `config/family.json` (for example "audult") was copied into the database.
- `python data/members.py sync` now leaves out a member whose role is not adult, child or pet and says which one to fix
  in `config/family.json`; the other members still sync, so the daily run keeps going.
- `python data/members.py add NAME --role ...` refuses a role other than adult, child or pet.
- A person already stored with a mistyped role keeps it until the role is fixed in `config/family.json` and sync runs.

## 0.83.1
No database change. Fix: after an update the web app could open with the previous release's look (for example the
Records area buttons drawn as plain links) until the page was reloaded.
- The app's own style and script files are now asked for with the version in their address, and the offline helper
  (service worker) keeps a separate store per release and removes the old one, so an update shows its new look on the
  first load.

## 0.83.0
No database change. Records move into the web app for looking things up.
- New: Records at `/records` in the web app (adults): word search over every record and filed paper, the People, Home,
  Vehicles and Papers & IDs areas with their parts, a few counts per area, and read-only lists in which each row opens
  in full: every field, the paper it came from (Download, Open paper) and its change history. A link to several rows
  lists them.
- "Open record" on Brief and Inbox rows and the "From:" links under Chat answers now open Records in the web app.
- Adding and changing records stays in the classic dashboard for now ("Change it in the classic dashboard" on each
  record); Finance parts (bills, accounts, cards...) still open in the classic Finance page. Saved items point to
  Notes, the emergency sheet to the Brief documents.
- Safety: a filed paper downloads only from inside this install's `archive/` folder, always as a download (never shown
  in the page); other people's "only me" saved items stay hidden from records and search; parts, areas and links that
  are not offered are ignored.
- Children keep using Records in the classic dashboard for now.
- Internal: `data/records_data.py` holds the lists, search, record and paper look-ups without web or Streamlit code.

## 0.82.0
No database change. Notes move into the web app.
- New: Notes at `/notes` in the web app (adults): the family's saved links, notes, places and deals, pinned first, with
  word search as you type, Kind / Tag / Added by filters and "Show archived and ended deals"; Pin, Tags and Archive on
  each item, and the Save form (title, link, kind, note, tags, address, deal end date, who sees it).
- Same rules as the classic board: links are never fetched (http(s) only, tracking parts removed, login-token links
  refused) and open in a new tab without passing this page on; other people's "only me" items stay hidden and cannot
  be pinned, tagged or archived; every change goes through the same checks and the change log. Filter choices that
  are not offered (an unknown kind, tag or person) are ignored.
- Children keep using Notes in the classic dashboard for now.
- Internal: `data/notes_data.py` holds the list, filters and actions without web or Streamlit code.

## 0.81.0
No database change. Calendar moves into the web app.
- New: Calendar at `/calendar` in the web app (adults): week, month and year views of every due date, appointment,
  birthday, renewal and festival from the records, Prev / Today / Next, a colour per kind. On a phone the week is a
  list and the month shows colour bars; tap a day to open its week.
- The family's Google Calendar (read-only) shows below, loaded after the page so a slow Google never holds it up,
  fetched at most every five minutes.
- Internal: the dated records moved to `data/calendar_data.py`, which the classic Calendar page now uses too.

## 0.80.0
No database change. Chat moves into the web app.
- New: Chat at `/chat` in the web app (adults): the suggestion chips answered from the records with no AI (what is
  due, what we owe, spending trends, "Log ..."), word search when no AI is set, typed questions to the assistant when
  one is, "From:" links into Records, and the same "Yes, save it" card before any change.
- Safety: the conversation and the change waiting for a yes stay on the PC, in the signed-in session. "Yes, save it"
  sends only a one-time code for that card, so exactly the changes shown run, once; the browser can never hand in a
  change of its own. AI answers are shown without any links or images. At most 40 questions an hour per conversation.
- Internal: the no-AI answers moved to `data/chat_data.py`, which the classic Chat page now uses too. Files are added
  in the Inbox (the web Chat has no file box yet).

## 0.79.1
No database change. Small launcher fix.
- Fixed: `python launch.py --web` now starts the classic dashboard beside the web app (this PC only) when it is not
  already running, so pages not moved yet (Settings, Chat, Calendar, Notes, Records) open from their buttons. It stops
  that copy when the web app stops; a classic dashboard you started yourself is left alone.

## 0.79.0
No database change. The product is renamed.
- Changed: the product is now **Mitra Home** and the agent is called **Mitra** until a household names it in
  Settings > Agent. Households that already chose an agent name keep it.
- Unchanged on purpose: scheduled task names, the backup and household folders, the Google Drive folder, the Gmail
  label `FamilyAgent`, the update repository and the release signing key. A Google calendar made earlier is renamed
  in place to Mitra Home, never duplicated.
- Internal: `data/brand.py` gains `AGENT`; the Gmail label is now a frozen literal instead of following the product
  name.

## 0.78.0
No database change. Inbox moves into the web app.
- New: Inbox at `/inbox` in the web app: add files, the open items as cards (file it, decide, answer a question),
  Files / Decisions / Questions views, "File them now", Open record. Every choice still goes through the same fixed
  handlers as the classic Inbox (adults only, logged).
- Uploads: each file is checked for type, size (25 MB) and that its content matches its name, never overwrites, and
  the inbox folder stops accepting at 500 waiting files. Limited accounts cannot add files.
- Internal: the content check moved from `chat_core.py` to `inbox_upload.py` (shared by the phone bot and the web app);
  Inbox data for the web app in `data/inbox_data.py`.

## 0.77.1
No database change. Fix for the web app Brief.
- Fixed: the documents under Brief (this week, weekly digest, family meeting, emergency sheet) showed raw markdown
  (`##`, pipe tables). They now draw as headings and tables. Text is escaped first and only web, mail and in-page links
  are kept.

## 0.77.0
No database change. Web app: the Brief moves over.
- New: Brief in the web app (`/brief`, Today / Week / Month): Needs you and Coming up, one Paid / Done per row, Snooze
  and Hide in a small menu, Undo after Paid, Back up now, and the four documents (this week, weekly digest, family
  meeting, emergency sheet). Same rows and actions as the classic dashboard (they now share `data/brief_data.py`).
  Adults only. Chat and Inbox still open in the classic dashboard.

## 0.76.0
No database change. Starter for the web app.
- New: `python launch.py --web` (or add `--web` to the starter files) starts the new web app from the same private Python
  environment as the dashboard, on port 8601 or the next free one, and opens the browser. `--lan` works with it (phones on
  the home Wi-Fi, needs a PIN). A second start reopens the running web app. Needs a household first (start FamilyAgent
  normally once). Pages not moved yet link to this folder's own dashboard when it is running.

## 0.75.2
No database change. Fix for the web app.
- Fixed: signing in to the web app from a browser was refused with "Cross-site request refused". The page told the browser
  to send no referrer, so it sent "Origin: null" on the sign-in form. It now sends the page's own address.

## 0.75.1
No database change. Security fix for the web app (0.75.0).
- Fixed: a signed-in web session now ends when that person's PIN is changed or the person is removed, and a changed
  role (adult to limited) applies on the next click. Before, a session stayed valid until it expired.

## 0.75.0
No database change. New web app, first slice (runs beside the dashboard; nothing is replaced yet).
- New: `python data/web_app.py` starts a faster, phone-friendly web app on http://127.0.0.1:8601 (`--lan` for phones on
  the home Wi-Fi, refused until someone has a PIN). Same people and PINs as the dashboard. This slice has the sign-in,
  the left menu, light / dark, **Finance** (income, spending, what was left, what moved most, this year against last),
  and can be installed to a phone's home screen. Other pages open in the classic dashboard until they move over.
- Security: sessions live in memory (a restart signs everyone out), cookie is HttpOnly + SameSite=Strict, every change
  carries a CSRF token, only local host names are answered, strict content policy (no inline scripts, nothing loaded
  from the internet), signed-in pages are never cached. Children's accounts cannot open Finance.
- Needs: `python -m pip install -r requirements.txt` (fastapi, uvicorn, jinja2 are new).

## 0.74.0
No database change. Licence.
- Changed: FamilyAgent is now released under the **GNU AGPL-3.0-or-later** (it was MIT up to 0.73.2; copies you already
  have stay MIT). Copyright (c) 2026 Rajesh Katukojwala (rNetGit). Use is unchanged: free, no account, no subscription.
  Anyone who changes it and shares or hosts it must share those changes under the same licence.
- New: `NOTICE` (author, earlier releases, third-party licences), `TRADEMARK.md` (the name and logo), `CITATION.cff`,
  `.github/FUNDING.yml`, and a sign-off (DCO) note in `CONTRIBUTING.md`.

## 0.73.2
No database change.
- Fixed: the page blinked (and the sign-in screen showed dark text on a dark background) for a person whose light / dark
  choice differed from the household default: the two palettes were applied one after the other on every run. One
  palette is applied per run now.

## 0.73.1
No database change. Phone screens.
- Changed: on a phone the left menu is narrower and folds away as soon as you pick a page (or search); the page fits the
  screen width with no sideways panning, columns stack, and tapping a field no longer zooms the page.

## 0.73.0
No database change.
- New: Settings > Agent > Sign-in PINs. Give each person a PIN (or replace it) without the terminal; needed before the
  dashboard may be opened from a phone. Once anyone has a PIN you also type your own current PIN to change one. The very
  first PIN keeps you signed in. PINs are stored hashed; the audit log names the person, never the PIN.
- Changed: "Money" is now **Finance** and has its own rail entry above Records. Subscriptions and Amazon orders moved
  inside Finance (group Pay). Records keeps People, Home, Vehicles and Papers & IDs. Old links to Money or Subscriptions
  open the same part in Finance.
- Fixed: filing a photo (or a cut-off PDF) as a statement from the Inbox crashed the page. A photo is now just filed with a
  note that its lines were not read; a file that is not a real PDF shows a plain message.

## 0.72.0
No database change. The rail gets two pages of its own, like a mail program's Inbox / Calendar / Notes.
- Changed: Calendar (week / month / year and the Google copy) moved out of Brief to its own rail entry below Brief. Brief
  keeps Today, Week and Month.
- Changed: Notes is a rail entry: your saved links, notes, places, deals and videos, with search, kind and tag filters,
  pins and the add form. The same items are still reachable from Records.

## 0.71.0
No database change. Last of the five look-and-feel releases: Money.
- Changed: every Money table uses readable headings and blanks (no database column names, no "None"); charts share one
  look (green and grey for income and spending, short month names, no rotated labels, no legend titles) and a chart with
  nothing to draw shows "Nothing to chart yet" instead of an empty axis; empty parts show one calm message.
- Changed: the work tab, receipts and connection tables follow the same style.

## 0.70.0
No database change. Fourth look-and-feel release: Papers, Subscriptions and Settings.
- Changed: Settings > Household profile shows the six areas as progress rings with "N of M" under each and one
  "Answer next" button, instead of six bars and six buttons.
- Changed: Subscriptions no longer lists the same row twice: "Decide" shows what is not reviewed yet, "Already decided"
  the rest; the per-category chart is a plain horizontal bar chart and appears only with two or more categories.
- Changed: the Emergency sheet has Download and Print buttons above it. Receipt counts use the shared number tiles.
- Unchanged on purpose: the dark mode switch is still in Settings > Agent as well as the rail.

## 0.69.0
No database change. Third look-and-feel release: People, Home and Vehicles.
- Changed: People shows each member with their own colour dot; empty lists in People, Home, Papers and Vehicles show
  one calm message with a small drawing and a next step. Vehicles shows a single "No vehicles yet" (no second empty
  box for Service). Seasonal tables with nothing in them say so instead of drawing an empty grid. Inventory totals
  use the same number tiles as the rest of the app. The calendar's Week / Month / Year switch is a button group.

## 0.68.0
No database change. Second look-and-feel release: Records.
- Changed: Records has area pills with an icon each (People, Home, Vehicles, Money, Papers & IDs, Subscriptions). Money's
  sixteen parts are grouped as Pay (bills, receipts, phone bills, cards, statement watch, price spikes), Keep (accounts,
  deposits, budget and loans, card benefits) and Look back (cashflow, trends, tax papers, home office, year-end, work).
  On a phone each switcher is one row you slide sideways, so the page content starts higher.
- Changed: every area opens with three or four count tiles; the heading says where you are ("Money - Bills").
- Changed: tables show readable headings (Due, When, Left after bills) instead of database names, blanks instead of the
  word None, and money with the currency symbol. Empty lists show one calm message with a next step instead of a blue
  box. The "tick a row" hint appears once per visit, not on every part.

## 0.67.0
No database change. The first of five look-and-feel releases (the new look is a calm light canvas, white cards, one green accent).
- Changed: a new shell. A tighter page header with the date or place under the title, a left rail with the five pages
  (Chat, Inbox, Brief, Records, Settings), the active page as a soft green row, the Inbox count as a small chip, a red
  dot on Brief when something is overdue and an amber dot on Settings when the health check has something to fix (the
  floating "things to fix" chip is gone; hover Settings for the text). Records is a page of its own in the rail; the
  search box has a magnifier. The bottom of the rail shows the version and the light / dark switch.
- Changed: Brief views, the number tiles, Inbox cards and the empty states use one set of building blocks
  (`data/dashboard/theme.py`: header, kpis, card, chip, empty, section, ring, chart), so the next releases can bring
  the same look to Records.
- Changed: on a phone the page starts under the top bar, number tiles sit two per row and table toolbars are hidden.

## 0.66.0
No database change.
- New: phones on the home Wi-Fi. `Start FamilyAgent for phones.bat` (Windows) or `Start FamilyAgent for phones.command`
  (Mac) starts the dashboard so a phone on the same Wi-Fi can open it, and prints the address to type (for example
  `http://192.168.1.20:8501`). It refuses to start until at least one person has a PIN, so nobody else on the network
  can open the papers. It also prints the one Windows Firewall rule to allow it for the Private network profile only.
  Plain `launch.py --lan` does the same.
- Good to know: the connection is plain http, not encrypted, so use it only on your own Wi-Fi (never a guest or public
  network). Access works only while that window is open and the PC is on. The normal starter still listens on this PC only.

## 0.65.0
No database change.
- New: a double-click starter. `Start FamilyAgent.bat` (Windows) and `Start FamilyAgent.command` (Mac) run `launch.py`,
  which checks for Python 3.12 or newer (opening the download page when it is missing), prepares a private Python
  environment and installs the packages (again only after an update changes them), makes the household folder next to the
  app on a brand-new install, starts the dashboard and opens the browser on the first-run chat. Starting it again opens the
  dashboard that is already running instead of a second one, and never takes over another install's dashboard.
- Changed: the scheduled-task and dashboard start scripts use that environment when it exists. On Windows it lives in
  `%LOCALAPPDATA%\FamilyAgent\venv` (Windows' 260-character path limit breaks long folders); on Mac/Linux in `.venv`
  inside the app folder (kept by updates).
- New in the browser: "Make it run on its own" (the first-run finish screen and Settings > Data) registers the daily
  brief, weekly digest, weekly backup and the optional two-hourly inbox check; Settings > Household profile gets Optional
  features (festival calendar, work contracts, Amazon orders, shopping lists) and Tax papers (names only). The terminal
  wizard registers tasks through the same code (`data/task_register.py`).
- Fixed in the docs: "Start here" no longer says the first-run chat asks where the household folder goes (the starter
  makes it).

## 0.64.0
Database change: migration 040 (`mobile_bills`, `mobile_bill_lines`, `mobile_bill_items`), applied automatically.
- New: phone bills per person. A Verizon bill dropped in the Inbox is read on this PC without any AI (nothing is
  sent anywhere): the bill is still filed as one bill with its total due and due date, and every line's plan, device
  payments, services, surcharges and taxes are stored. Account-wide credits and charges are shared equally across the
  lines (in whole cents, so the people add up to the bill). Two lines under one name are added together. Records >
  Money > Phone bills shows each person's net cost month by month and one bill in detail; the monthly report gets a
  "Phone bills" section. The call lists ("Talk activity") are never read or stored; only the last four digits of the
  account and of each number are kept.
- Safe by checking: a bill is stored per line only when every section, every line and the whole bill add up to the
  cent. Otherwise it waits in the review queue with the reason; nothing wrong is ever stored. `python data/mobile_bill.py
  check FILE` shows what is read; `python data/mobile_bill.py reparse DOCUMENT_ID` reads a filed bill again.
- Changed: removing a person (`purge.py person`) also removes their phone lines (by printed name or by member).
- Not yet: other carriers (T-Mobile, AT&T) are filed as one bill as before.

## 0.63.0
No database change.
- New: the newest monthly report goes to the phone Drive `Brief` folder as a PDF (default on; leave `"monthly"` out of
  `drive.push` to stop it). The weekly task makes last month's report when it is missing and rebuilds it in the first two
  weeks of the month so late statements count.
- New: Gmail without Claude. Mail you label `FamilyAgent` has its attachments (or, with none, its text) copied into
  `inbox/` straight from Google's API, using the same Google sign-in and client file as the calendar. Read-only
  (`gmail.readonly`): nothing is sent, labelled, archived or deleted; only the chosen label is read; copied message ids
  are remembered on this PC. Set up with `python onboard.py add gmail` or Settings > Connections > Google; guide in
  `docs/GOOGLE_GMAIL.md`. **You must:** switch the Gmail API on in your Google Cloud project and allow the extra
  permission once (a new sign-in). The inbox task copies new mail every cycle.
- Changed: signing in to Google again no longer drops a permission you already gave (the calendar-write or Gmail
  permission); `python data/google_calendar.py auth` without `--write` still withdraws the write permission.

## 0.62.0
No database change.
- New: Trends (Records > Money > Trends): income and expenses month by month with what was left, each month against
  the one before and against the same month a year earlier, and the categories that moved most over the last 12
  months against the 12 before. From the filed statements, no AI. The monthly report gets the same section and the
  Chat page a chip, "How is our spending going?", answered without an AI. Internal moves (transfers, investments)
  are not expenses; a card payment counts only in a month that has no card lines of its own.

## 0.61.0
No database change.
- New: your papers, settings and database can live in a folder of their own next to the app (`../FamilyAgent_home`), so an
  update, a re-unzip or a slip inside the app folder cannot touch them. The wizard offers it on a fresh install (default yes);
  `python onboard.py home [PATH]` moves an existing install there (`home --inside` puts it back); `python data/paths.py`
  prints where everything is. The app finds the folder through one line in `familyagent_home.txt`, which updates keep.
  Backups go next to the household folder (`FamilyAgent_backups`), the pre-upgrade copies inside it. Claude Code agents
  reach it through `.claude/settings.local.json` (written by `home`) and the guard hook treats it as inside.
- Changed: every script takes its paths from one module (`data/paths.py`); nothing hard-codes `data/family.db` or
  `inbox/` any more.

## 0.60.4
No database change.
- Fixed: asked for the premium "per car", the chat assistant answered with one car only. It now picks the newest
  policy term first and lists every car on it.

## 0.60.3
No database change.
- Fixed: asking the chat assistant about insurance ("when does my auto policy renew and what is the premium per car?")
  made it ask you for the policy papers or the carrier's name, although both are on file. It now knows the policy
  tables (terms, cars, coverages, discounts, drivers, premium history) and looks them up first.

## 0.60.2
No database change.
- Fixed: `python onboard.py <command> --help` (also `-h`) ran the command instead of showing usage, so
  `upgrade --help` backed up and migrated the database and `reset --help` cleared the checklist. Help anywhere on the
  line now prints the usage and does nothing else.

## 0.60.1
No database change.
- Fixed: subtotal lines on no-fault auto policies ("aggregate no fault benefits", "subtotal ...") could still be
  given a premium of their own when the AI returned one, so a car's coverages added up to more than its premium. They
  now never carry a premium, whatever the AI returns. Run `python data/doc_extract.py reread-policy ID` once for a
  multi-car policy read with 0.60.0 to clear them.

## 0.60.0
Database change: migration 039 (adds which car a policy discount belongs to). Applied automatically by the update.
- Fixed: a policy covering several cars listed the same coverage and discount again and again with no way to tell the
  cars apart, and the count changed from one reading to the next. Each coverage and discount printed under a car now
  keeps that car, Money > Insurance shows it in a new "car" column, and an exact repeat is kept once.
- Fixed: subtotal lines on no-fault auto policies (such as "aggregate no fault benefits") are no longer given a
  premium of their own, so they are not counted twice.
- New: `python data/doc_extract.py reread-policy ID` reads a filed policy's paper again (one AI call) and replaces its
  coverages and discounts, now with their cars. Use it once for a multi-car policy filed before this version.

## 0.59.7
No database change.
- New: the Claude Code intake agent (the one used with a Claude account) now also files a paper dropped twice once.
  Before reading anything it runs `python data/ai_intake.py duplicates`, which moves exact copies of filed papers, and
  repeats inside the inbox, to `archive/duplicates/` with no AI call. Nothing is deleted.

## 0.59.6
No database change.
- New: a paper dropped twice is filed once. When a file in the inbox is an exact copy of one already filed (or waiting
  in needs review), it moves to `archive/duplicates/` before any AI call, and no second document, bill or policy is
  made. Two copies dropped together are caught too. Nothing is deleted. A rescan or a re-saved PDF is a different
  file and is still read.

## 0.59.5
No database change.
- Fixed: long insurance policies read by Gemini 2.5 went to "needs review" with "details not read (not valid JSON)".
  Gemini spent almost all of its answer budget thinking and the answer was cut off. Reading fields from a paper now
  asks Gemini 2.5 Flash for no thinking (2.5 Pro: a small budget) and leaves more room for the answer; a cut-off answer
  is written to the log as such.
- Fixed: answers with more than 50 items were refused (a policy with several cars repeats its coverages per car, a
  statement month often has more than 50 lines). The limit is now 300, and policies get a longer answer.
- Unchanged: a policy still sends only its first 30,000 characters (about the first 8 to 10 pages), where the
  declarations are.
  **To do:** papers that went to needs review with "not valid JSON": move them from `inbox/needs_review/` back to
  `inbox/` (or drop them again) and they are read again.

## 0.59.4
No database change.
- Fixed (privacy): full names printed on papers were sent to the AI when the household knows people by a first name or
  nickname. A policy printing "INSURED: ALEXANDER PATEL" went out as is for a household that wrote "Alex". Now:
  - **Names on your papers** (Settings > Household profile, and the People step of the first run): full names as bills
    and policies print them, one per line. They are hidden before anything is sent to the AI and stay on this PC.
  - The surname in your family name ("The Patel family") is hidden too.
  - Health check warns "Names on papers" while an AI is set, someone is known by one word only and no paper names are
    written.
  **To do:** open Settings > Household profile > Names on your papers and write the full names as your papers print
  them. Papers already filed were read with the names visible to your AI provider; nothing else changed.

## 0.59.3
No database change.
- Fixed (phones and narrow windows): Settings > Data > Health check lists each thing to fix as its own readable line
  with where to fix it; the full table is folded under "All checks".
- Fixed: Inbox card buttons no longer shrink to "Trac…" or "Dis…" in a narrow window; they keep their full words and
  wrap to a second line.
- Fixed: on Brief, a row's Done / Paid button and its "⋯" menu stay together instead of the menu dropping to a line
  of its own on a phone.

## 0.59.2
No database change.
- Fixed: after **Disconnect Google Calendar** and signing in again from Settings, the calendar stayed switched off
  (no Google events on Brief > Calendar or in chat) until "Save the choice" was pressed. Signing in now switches it
  back on and keeps the calendars you picked.
- Fixed: "Save the choice" and `python onboard.py add calendar` no longer forget that the FamilyAgent calendar was
  allowed, or when you signed in.
- **To do if Brief > Calendar shows no Google events although Settings says Connected:** press "Save the choice" in
  Settings > Connections > Google Calendar once.

## 0.59.1
No database change.
- Fixed: Google sign-ins no longer stop every week once the Google project is published. The setup steps
  (`python onboard.py add calendar` and docs/GOOGLE_CALENDAR.md) now say that Google keeps "Publish app" grey until
  Branding has a home page and privacy policy link, and give a public page you may use. If Google refuses the sign-in
  a week or more after it was given, the message now says the project is probably still in "Testing" and how to fix it.
  **To do if your Google Calendar sign-in expires every 7 days:** publish the app (step 4 of the guide), then sign in
  again in Settings > Connections > Google Calendar.
- Fixed: the Google Calendar guide now says that asking the chat "what's on" sends those event titles and times to
  your AI provider.
- Changed: Settings > Connections > Google Calendar is no longer labelled "read-only", because it also offers the
  FamilyAgent calendar. Health check says whether that calendar is allowed.
- Fixed: `python data/migrate.py verify` no longer reports a migration as edited when only its line endings differ
  (Windows checkouts).

## 0.59.0
No database change.
- Changed (inside, nothing to do): the product name now comes from one place (`data/brand.py`) for every page title,
  message and document heading, and a renamed Google calendar is renamed in place instead of being made twice.
  Nothing a household sees changes.

## 0.58.0
No database change.
- New: three more kinds of Inbox cards, so fewer things have to be remembered:
  - **Insurance renewal.** A policy whose term ends within 45 days and has no newer term filed shows how many days
    are left, the premium and its change on the term before. It goes away by itself when you drop the new declarations
    page. Choices: I looked into it, remind me in a week, dismiss.
  - **Price went up.** A subscription whose charge went up, and an insurance premium that renewed 10% or more above the
    term before, join the bills that already raised this flag.
  - **Amazon.** With the Amazon option on: three or more card charges older than two weeks with no order details, and
    three or more orders with no card charge, each one card. Choices: remind me in two weeks, not needed.

## 0.57.0
No database change.
- New: **Restore from backup** in Settings > Data. Pick a backup, check it, tick that you understand, press Restore:
  FamilyAgent closes itself, pauses the phone bot, keeps a copy of today's data with your backups, puts the backup in
  place, brings back filed papers and settings that went missing (nothing that is there is overwritten), and opens
  again on its own. Locked (encrypted) backups ask for their passphrase if it is not saved on this PC. To undo a
  restore, pick "copy from just before a restore" in the same list.
- New: **Start with this PC** switch for the phone bot (Settings > Connections > Phone bot): the bot starts by itself
  when you sign in to Windows. Replaces the terminal command.
- Fixed: a backup taken before encrypted backups were turned on can be restored without the passphrase.
- Changed: Backup, Export and Update buttons use the full width so their names are not cut off.
- Fixed: answering **no car** in the first-run chat now counts as answered. Settings > Household profile no longer
  shows Vehicles as a gap, and the Inbox does not ask "Does the household have a car?" again. Add a car later and the
  answer is cleared.

## 0.56.0
No database change.
- New: **open a record from its row.** In Records, tick a row in a list (people, life items, checkups, appointments,
  upkeep, inventory, shopping, dates, vehicles and their service, bills, receipts, loans, accounts, investments, papers,
  expiries and IDs, insurance, subscriptions, Amazon orders) and that record opens on top with every field, the paper it
  came from and its changes. Replaces the "Open a paper" and "Open one" pickers.
- Fixed: `python onboard.py --help` (also `-h`, `help`) prints the usage instead of starting the setup checklist, and a
  mistyped command says so instead of starting it. Two old hints that pointed at a `step` command now name the real one.

## 0.55.0
No database change. One screen for everyone, in household words.
- Removed: **the Classic view** (the older tabbed screen). Everything it held is on the four pages and Records:
  Family and Money parts are under Records (People, Home, Vehicles, Money, Papers & IDs, Subscriptions), the Ask tab is
  Chat, the old Settings tab is Settings (Household profile, Agent, Connections, Data). Old `?page=classic` links open
  Chat.
- Changed: **no commands, file names or folders on the screen** outside Settings > Data > Advanced. Captions now say
  where to do it in the app ("Records > Vehicles", "Settings > Connections > Google Calendar") or what to tell the
  assistant. The health check shows "where to fix it" in the app; the matching commands are listed under Advanced.
  The same goes for Brief rows, the weekly digest, the emergency sheet, the tax checklist, the phone calendar file and
  Google / Telegram connection messages.
- New: **Log a service** on Records > Vehicles (oil change, tires, brakes, ...), so car service no longer needs a
  command.
- For maintainers: `tests/test_language.py` fails when a command or path appears in household text (dashboard modules
  and the modules whose text reaches the family); `settings.advanced()` is the one allowed place. `health` rows carry
  `here`; `edit_actions.vehicle_service`; `dashboard/ask.py` folded into `chat.py`; `conftest.classic()` replaced by
  `on_page`, `records`, `settings`.

## 0.54.0
No database change. The first run is a conversation, and the Brief opens with a few plain sentences when an AI is set.
- New: **first run as a chat.** The assistant asks one thing at a time in bubbles: the rules, the AI (optional, with a
  test call), the family's name, where you live, who is in the household (typed in one box, for example
  "Alex, adult, March 14 1980", read back so you can fix a role), own or rent, cars, optional PINs. Then "drop up to
  three papers" (filed at once when an AI is set), optional phone and Google Calendar cards, and the first Brief.
  No terminal and no AI are needed. Answers are saved after each screen; "Run the setup interview again" starts from
  what is there.
- New: **a few sentences at the top of Brief > Today** when an API AI is set (OpenAI, Anthropic, Gemini, OpenRouter,
  Ollama). One call a day for the same list, at most four a day; names and identifiers are masked before it leaves;
  an answer with a number or link that is not in your list is thrown away. No AI = nothing is drawn.
- For maintainers: `data/first_run.py` (people / cars / own-rent parsing), `data/brief_narrative.py`,
  `edit_actions.vehicle_add`, `chat.take_files(..., say=)`.

## 0.53.0
No database change. Settings is regrouped, the agent has a profile the family can change, and the household profile
fills itself in over time.
- New: **Settings in four groups.** Household profile, Agent, Connections, Data. Commands and folder names moved
  under Data > Advanced.
- New: **your agent's profile** (Settings > Agent):
  - its name (shown in the left panel, the page title, the Brief and the assistant's own wording);
  - its tone (brief and plain, or warm with a little more detail);
  - when the daily brief and the weekly digest are made (the scheduled tasks move with it);
  - what the Brief keeps an eye on: bills, renewals, checkups, seasonal tasks, school, birthdays, money alerts, home,
    work. Anything switched off stays quiet; backup and stopped-task warnings always show;
  - who may approve Inbox items from a phone (/ok, /no). Empty means every adult.
  Dark mode and the items hidden from the Brief (with Restore) are there too.
- New: **change the agent from Chat.** "Send the brief at 6 instead", "call yourself Ollie", "stop showing birthdays
  in the brief" get the usual confirm card first. Who approves is changed in Settings only.
- New: **connection cards.** AI provider, phone bot and Google Calendar each show Connected, Needs attention or Not set
  up, with a Test button. The details open underneath.
- New: **how complete is your profile.** Settings > Household profile shows a meter for People, Home, Vehicles,
  Money, Papers and Subscriptions, with "Answer next". The same questions arrive in the Inbox, at most two new ones a
  day: a missing birthday (pick the date), own or rent, a car, a first statement, IDs, insurance papers,
  subscriptions. "Ask me later" brings one back in two weeks; "Not needed" / "No car" counts as answered. The phone bot
  answers them too (/ok ID 1 2016-09-02 for a birthday).
- Data has a "Run full check" button (the full health check, no terminal needed).
- For maintainers: `python data/agent_profile.py show|set FIELD VALUE|approvers NAMES`,
  `python data/profile_gaps.py`; proposals source `profile`; assistant action `agent_set`;
  `edit_actions.household_set`; `onboard.py` registers the digest tasks at the profile's times.

## 0.52.0
No database change. The assistant now works in steps, remembers the conversation and shows where its answers come
from; a new Records page holds everything the Family and Money tabs showed.
- New: **the assistant looks things up in steps.** A question that needs two look-ups ("what did we pay the dentist
  last year and when is the next cleaning?") is answered in one go: the AI may run up to four rounds of read-only
  look-ups, seeing each result before the next. Only the first round may ask for changes, before any of your
  records or papers have been read, so text inside a document can never ask for one.
- New: **the change you approve is the change that is made.** The confirm card lists the changes ("Save: Add rice to
  the groceries list"); "Yes, save it" runs exactly those, checked again, without asking the AI a second time.
- New: **memory.** Chat remembers the last ten turns of the conversation, so "Raj's dental was Sep 3" followed by
  "and Sam's too" works. It lives only in the open dashboard tab ("Clear this chat" forgets it); the phone bot's
  /ask remembers the last questions for 30 minutes, in memory only.
- New: **answers show their source.** Under each answer, "From: City Water, due October 12" (or "14 payments")
  opens that record. The "What is due this week?" chip links its rows too.
- New: **Records**, opened from the search box in the left panel, from those links, and from "Open record" in a
  Brief row's menu or on an Inbox card. Six areas (People, Home, Vehicles, Money, Papers & IDs, Subscriptions) hold
  the same lists and forms the Family and Money tabs had. One record opens on top with its details, the paper it
  came from (download) and its change history. Papers has a type filter and "Open a paper". Search looks through
  bills, payments, people, cars, policies, subscriptions, saved items and the text of filed papers; private saved
  items stay with their owner.
- The Classic view still has every older tab until 0.54.
- For maintainers: `python data/records.py label|show|find|cite`; `assistant.run` / `assistant.apply`,
  `admin_actions.ask(user, text, history)` + `admin_actions.confirm(user, writes)`.

## 0.51.0
Database: migration 038 adds `policy_drivers` (applied by `python onboard.py update`). FamilyAgent no longer needs
Claude Code to read your papers: any AI you choose now does the whole job.
- New: **OpenRouter** as an AI provider (Settings > AI provider, or the wizard's AI step). One key reaches many models
  (Gemini, GPT, Claude, Llama...); the default is `google/gemini-2.5-flash`. Every request asks OpenRouter to use only
  hosts that neither store nor train on what is sent.
- New: **documents are read, not just filed.** After the inbox decides what a paper is, a second call reads its
  details into your records, with any provider (API key, OpenRouter, Ollama or a signed-in CLI):
  - insurance policy: carrier, kind, policy last four, term dates, premium and payment plan, vehicles (year, make,
    model, VIN last four; added to your vehicles), drivers, main coverages with limits and deductibles, discounts. A
    renewal is linked to the earlier term, which is marked replaced; the same paper twice is not added twice.
  - ID document (new type): whose, which kind, last four, issued and expiry dates.
  - vehicle registration or inspection (new type): the expiry dates, on the right car.
  - medical letter: the visit (date, time, provider, a few plain words) and the follow-up date.
  - investment statement: value, as-of date, maturity. Tax form: form, year, issuer and amount on the document.
- New: **statements with any AI.** When the no-AI reader cannot read a statement, the AI reads every line; it is
  imported only when the lines add up to the printed opening and closing balances (a new account is added by its
  last four digits if needed). Anything that does not add up waits in the Inbox.
- New: Money > Insurance shows each policy's vehicles, drivers, coverages and discounts. Chat says what it read
  after you drop a file ("Zz Mutual auto policy, renews 2026-09-01, premium $612.40, 2 vehicles, 2 drivers").
- Tested live through OpenRouter (google/gemini-2.5-flash) on a demo family: an auto declarations page, a bank
  statement and a clinic visit summary were each read correctly. The inbox now tells the AI what each document type
  means, files a paper with no printed date under its own dates (policy start, visit date), reads 03/02/2026-style
  dates in your country's order, and forgives harmless answer shapes ("$250", a list of names).
- Safety is unchanged: text is masked before it is sent, every answer is checked field by field, an answer with a
  full account, card or ID number is refused, numbers are stored as last four digits, and a paper the AI is not sure
  about waits for you in the Inbox.

## 0.50.0
No database change. The Brief page is rebuilt; Home and Calendar leave the Classic view.
- New: **Brief has four views: Today, Week, Month, Calendar.** Today shows two short lists, *Needs you* (overdue,
  due today, a seasonal window that is open or missed, an old backup, a scheduled job that stopped) and *Coming up*
  (the next 7 days). A list with nothing in it is not shown, the number tiles appear only when they are not zero,
  and a household with nothing due sees one line: "Nothing needs you this week."
- New: every row has one button (Paid for a bill, Done otherwise; Done on a checkup records today's date, on a
  seasonal task logs it) and a small menu with the details, Snooze 1 / 7 / 30 days and Hide. Paid can be undone.
- New: Week lists the next 7 days day by day; Month the next 30 days week by week, festivals included. Calendar is
  the month / week / year grid with your Google Calendar copy.
- Changed: the Home and Calendar tabs are gone from the Classic view (their content is on Brief). Typed words in
  Chat now also find items on your shopping and to-do lists (this was Home > Find).
- Changed: the calendar's Prev / Today / Next buttons stay on one row on a phone.

## 0.49.0
No database change. The Inbox reaches your phone.
- New: **decide Inbox items from the phone bot** (Telegram, Discord). In a private chat, `/inbox` lists what is
  waiting, each with numbered choices; `/ok 12` takes the first choice, `/ok 12 2` another, `/ok 12 1 2026-03-01`
  answers "when was it last done", and `/no 12` says no (not a bill, not sure, dismiss). Adults only, private chats
  only; every choice goes through the same checked and logged path as the dashboard. Filing a document still needs
  the PC, because it needs the type, sender and date.
- Changed: a file the assistant was not sure about now says what it looked like ("It looked like a bill from City
  Water.").
- Fix: the upload boxes said 200MB per file; the real limit is 25 MB and they now say so.

## 0.48.0
No database change. The dashboard opens on a new four-page layout; everything from before is still under "Classic view".
- New: **left rail with four pages.** Chat, Inbox (with a count), Brief (a dot when something is overdue) and
  Settings. Links keep their page (`?page=inbox`), so a refresh stays where you were.
- New: **Chat is the landing page**, and it works without any AI: "What is due this week?" and "What do we owe?"
  are answered straight from your records; "Log furnace filter" (shown when a checkup or seasonal task is due)
  records it after a "Save: ..." card; typed words search your saved items and filed papers. Drop files into the
  chat box to add them to the inbox. With an AI set, you can ask anything in your own words as on the Ask tab, and
  changes still wait for your OK.
- New: **Inbox page.** The single place to add files, plus one card per thing that needs you (files the assistant was
  not sure about, payments to track, statements to fetch, checkups with no date), each with its choices: File it,
  Track as a bill, Track as subscription, Not a bill, Pick date, Not sure, Not ours.
- New: **Brief page.** Today's list and the calendar, with This week, Weekly digest, Family meeting and Emergency
  sheet one click away. Inbox items are not repeated there.
- Changed: Dark mode and Back up now moved to Settings > Look and backup. Streamlit's own Deploy button and menu are
  hidden when you start the dashboard with `run_dashboard.bat` or `run_dashboard.sh`.
- The browser tab shows your agent's name when `agent.name` is set in `config/family.json` (Settings for it comes later).

## 0.47.0
Database change: migration 037 adds the `proposals` table (applied automatically by `python onboard.py update`).
First step of the new four-page dashboard (Chat, Inbox, Brief, Settings). Nothing on screen changes yet.
- New: **one queue of things that need you.** Files the assistant would not guess about, payments seen three or more
  times (track as a bill, track as a subscription, or not a bill), statements that are late or missing, price rises
  on tracked bills, and checkups or home tasks with no date are gathered into one list, each in one plain line with
  its choices. `python data/proposals.py sync | list | decide ID OPTION | restore ID`. The daily, weekly and inbox
  tasks keep it fresh. No AI is used and nothing is changed until a person picks a choice.
- Safe by design: each item stores only the facts its fixed handler needs, never a command; every choice that changes
  records goes through the same checked, adults-only, logged path as the dashboard forms. An item handled elsewhere
  (for example tracked from the Money tab) drops out by itself; a dismissed payee is not suggested again.
- New: "Not ours" stops tracking a checkup or home task that does not apply to your household (its history stays).
- `purge.py person NAME` also removes that person's items from the queue.

## 0.46.1
No database change. Fixes found by using the Ask tab on a real install.
- Fix: **"what is my balance in savings" failed** ("I couldn't do that one") because the assistant guessed a wrong
  column name. It is now told how accounts and balances join, and when a query fails on a wrong column or table it
  gets one automatic second try with the error in front of it.
- Fix: a lookup that fails no longer says "nothing was changed"; it says it could not look that up.
- New: **"any events next week?" and "holidays next month" work.** The assistant has a read-only "what is on"
  lookup (`python data/whats_on.py [--start DATE] [--days N]`): bills, appointments, expiries, checkups, school items,
  birthdays and festivals from your records, plus your Google Calendar and any holiday calendar your Google account
  has, when connected. It shows dates and titles only.
- Changed: a broad question such as "how is our finance outlook?" now gets balances, this month's spending and bills
  due soon, instead of a question back.

## 0.46.0
No database change. FamilyAgent can keep its due dates on a Google calendar of its own.
- New: **calendar sync.** Settings > Google Calendar > "Put FamilyAgent due dates on Google Calendar". After one extra
  permission, FamilyAgent creates a separate calendar named "FamilyAgent" and keeps bills, statement due dates, ID
  and policy expiries, checkups, school items, birthdays, festivals and seasonal tasks on it, each with a 9:00
  reminder (days before: your choice). `python data/calendar_sync.py status | preview | apply --yes | remove --yes`.
- Safe by design: the permission (`calendar.app.created`) lets Google restrict FamilyAgent to calendars it made
  itself, so your own events cannot be read-changed or deleted by it; nothing is written until you press Apply on a
  preview (or switch on automatic morning sync); events have stable ids so nothing duplicates; a paid or hidden item is
  removed; past events are left alone; "Delete the FamilyAgent calendar" undoes it all.
- Privacy: only vendor names and titles go to Google ("Bill: Electric Co"). Amounts are left out unless you switch
  them on. No statement, account number or document is sent.
- Changed: signing in is read-only unless you press "Allow it"; a read-only sign-in withdraws the write permission.
- Changed: the daily task runs the sync only when automatic sync is switched on.

## 0.45.0
No database change. The assistant talks like a person.
- Changed: in the Ask tab, `python data/assistant.py` and the phone bots the assistant says what it will do in
  plain sentences ("Set Sam's birthday to February 2", "Add milk to the groceries list") and what it did ("Done: ...").
  It no longer shows action names, JSON arguments, SQL, ids, "FAILED", or the path of a file it made.
- Changed: a briefing it builds (family meeting agenda, emergency sheet, meals for the week) is shown as its
  content, not as a file location.
- Changed: when something does not work you get one plain sentence ("I couldn't find that one. Check the name and try
  again."), a trouble with the AI service points to Settings > AI provider, and the technical reason goes to
  `logs/assistant.log` for whoever helps you.
- Changed: answers are asked to use dates in words (October 3) and money with a $ sign, and never to mention tables,
  columns, file names or paths.

## 0.44.0
No database change. A setup interview in the dashboard.
- New: **setup interview**, one question per screen with a progress rail, Back / Continue and "Save, finish
  later". Steps: Welcome, Family (name, country, place, climate, currency), People (adults, children, pets, month and
  day pickers so a birthday cannot be typed wrong), Home, AI (provider and key), Phone (Telegram token), Logins
  (optional PINs, stored hashed), Finish (summary and the rules to accept).
- It opens by itself on a PC that is not set up yet (`run_dashboard.bat`), and again from Settings > "Run the setup
  interview again" (your answers are the starting point). Progress is kept in `config/setup_draft.json`, which never
  holds a PIN or a key.
- It writes through the terminal wizard's own code (`onboard.step_database`, life starters, `auth.set_user`), so the
  dashboard and `python onboard.py` always agree. Safe to run twice.
- The terminal wizard is unchanged: `python onboard.py` still works.

## 0.43.0
No database change. A new look and a left panel.
- New: **left panel on every screen** with the everyday actions: drop files into the inbox (and "File them now"),
  open the **briefings** (This week, Weekly digest, Family meeting agenda, Emergency sheet) as a pop-up with a
  Download button, **Back up now**, and a "n to fix / All good" chip from the health check.
- New: **Light / Dark switch** (Dark mode toggle in the left panel), remembered per person in
  `config/dashboard_prefs.json`. Tables and charts follow it.
- New: an **Azure-portal style**: Fluent colours (blue accent, warm grey background in light, charcoal in dark), flat
  tiles with a blue edge, Segoe UI text, status chips. Streamlit theme options and a little CSS only, no new package.
- Note: the dashboard server holds one theme at a time, so two people using it at the same moment share whichever
  was chosen last.

## 0.42.0
No database change. The dashboard now does what used to need a terminal.
- New: **Ask tab.** The same assistant as `python data/assistant.py`, as a chat box. Questions are answered at once;
  anything that would change your records is shown first and waits for "Yes, make the change". Adults only.
- New: **Settings > AI provider.** Pick Gemini, OpenAI, Anthropic, Ollama, Claude Code or none, paste the API key
  into a password box, tick the privacy confirmations, press Save. A test call runs straight away. The key goes to
  `config/secrets.env` and is never shown again (only "ends ...WXYZ"). Free-tier Gemini and Claude subscription
  tokens are refused, as in the wizard.
- New: **Settings > Phone bot (Telegram).** Paste the BotFather token (checked with Telegram first), Start and Stop
  the bot without a terminal, and make a one-time code to link each person's phone.
- New: **Settings > Google Calendar.** Upload the client file, sign in (a browser tab opens on this PC), choose the
  calendars, disconnect. Same read-only access as `onboard.py add calendar`.
- New: **Back up now**, **Export all my data** (with a download) and **Update** buttons. Restore stays in the terminal
  on purpose: replacing the database while the dashboard has it open is unsafe.
- New: every change made from these screens is listed in Settings > "Changes made here" (who, what, when; never a
  key, token or question).
- Fix: the daily task no longer starts the Claude morning brief when `ai.provider` is not `claude_code`. It was
  timing out and marking the task failed for families that chose Gemini or another provider.
- Fix: the recurring-bills digest test no longer depends on today's date.

## 0.41.0
No database change. The 0.40.3 fixes below ship in this release.
- New: **Google Calendar, read-only, with no Claude account.** `python onboard.py add calendar` walks a family
  through creating its own free Google Cloud project (a Desktop-app client, published "In production" so the sign-in
  does not expire every 7 days), saves the client file as `config/google_client.json`, signs in once in the browser,
  and lets you pick which calendars to show. The Calendar tab then lists the next 7, 14 or 30 days. Guide with every
  click: `docs/GOOGLE_CALENDAR.md`.
- Safe by design: only two read-only permissions (view events, list calendars); sign-in on this PC's loopback address
  with PKCE and a state check; the token only in `config/secrets.env` (never printed, never backed up); only Google's
  own hosts are contacted; nothing is written to the database. `python data/google_calendar.py status | auth |
  calendars | events | revoke`. Settings > Health check shows whether it is signed in.
- Not included yet: writing due dates to a calendar for phone reminders (needs the write permission), Gmail, and
  events in the weekly digest or the Telegram `/week`.

### Also in 0.41.0 (assistant fixes found on a real install)
- Fix: **"Raj dental was Sep 3" now works.** Routine checkups and home tasks (dental cleaning, physical, eye exam,
  furnace filter, ...) are recurring items, but the assistant picked the life-items action and failed with
  "0 matches". The two actions are described apart now, and if a life item is not found the assistant tries the
  recurring item of that name (same person, same date) before giving up.
- Fix: the assistant's "record a checkup" action put the date after `--who`, which the command line refused
  ("unrecognized arguments"); `data/recurring.py` now accepts the date on either side.
- Fix: a question like "what accounts do we have?" no longer ends at the table list. The assistant is told the
  main tables and columns up front, and when it only asked for the table list it gets one more read-only step to
  run the query.
- The table list no longer shows the search index's internal tables.
- Fix: with **Gemini** (thinking models) the answer could be cut short and "I could not understand the model's
  answer" appeared; the Gemini call now allows at least 4096 output tokens and the assistant retries once.
- Fix: greetings and small talk no longer trigger an action ("hello" produced a family-meeting brief), and a
  request with no matching action (for example filing the inbox) gets a pointer instead of an unrelated action.
- Test: the recurring-bills digest test no longer depends on today's date.

## 0.40.3 (not released separately)
No database change. Found by using the assistant on a real install.
- Fix: **"Raj dental was Sep 3" now works.** Routine checkups and home tasks (dental cleaning, physical, eye exam,
  furnace filter, ...) are recurring items, but the assistant picked the life-items action and failed with
  "0 matches". The two actions are described apart now, and if a life item is not found the assistant tries the
  recurring item of that name (same person, same date) before giving up.
- Fix: the assistant's "record a checkup" action put the date after `--who`, which the command line refused
  ("unrecognized arguments"). The date now comes first.
- Fix: a question like "what accounts do we have?" no longer ends at the table list. The assistant is told the
  main tables and columns up front, and when it only asked for the table list it gets one more read-only step to
  run the query.
- The table list no longer shows the search index's internal tables.

## 0.40.2
No database change. Dashboard and first-run polish from the first real-PC test.
- New: **Settings > Health check.** A quick, read-only list of what needs attention, each with the command or place
  that fixes it: database and pending updates, scheduled tasks (registered, and did they run), the newest backup per
  location, the backup passphrase, the AI provider and its key, chat bot tokens, files waiting in the inbox, the
  review queue, people without a birthday, no accounts yet. No secret is shown and no AI is called; a button tests
  the AI provider with one small call. `python data/health.py` prints the same list. The full check is still
  `python onboard.py doctor`.
- New: **Money > Accounts > Add an account** (name, type, last four digits, owner). Before this, the first
  statement needed a terminal command to create its account. An empty Accounts tab now says what to do.
- New: **record when a checkup was last done** from Home and Family > Health (a picker and a date), instead of
  asking the assistant. They are scheduled from that date.
- Fix: the **meals grid starts today**, not on Monday.
- Fix: the **wizard refuses a birthday that is not a month-day** (`78-01` is a year, not 07-18) and a year that is
  not four digits, and says how to type it.
- Fix: Streamlit's "Help agents write better apps / Install" pop-up is hidden by `run_dashboard.bat` / `.sh`.
- Better empty states: no recipes, no accounts.

## 0.40.1
No database change. Found by loading a real bank statement on a real install.
- Fix: **statement PDFs without section headings** are read. Some banks print no "Deposits" / "Withdrawals" headings
  and show only a running balance; the sign of each line now comes from the balances when exactly one way adds up
  (several equally good ways are left for a person, never guessed).
- Fix: **one statement for several accounts** (checking and savings on the same PDF). The block for the account whose
  number matches is used, so the other account's lines no longer break the balance check.
- Fix: a section total printed after its heading ("Deposits and Additions 653.89") no longer hides the heading.
- Privacy: long numbers in a transaction description (a payroll or company ID) are stored as the last four digits
  only ("PPD ID: x0242"), like account numbers.
- Fix: `import_statement.py ... --new NAME --dry-run` no longer leaves the account behind. New: `python
  data/import_statement.py account --new "Name" --type checking --last4 1234` adds an account without a CSV.
- New: `pdf_statement.py FILE --account X --document-id N` links the imported rows to the filed document.
- Known: the Python reader imports transactions and balances; interest on a savings account is a transaction, not
  yet a row in `interest_income`.

## 0.40.0
Database: migration 035 adds the archive search index (`doc_search`, `doc_search_state`), migration 036 adds recipes and
the meal plan (`recipes`, `recipe_ingredients`, `meal_plan`). Both are applied by `python onboard.py update`.
- New: **archive search.** Every filed document's text goes into a search index on this PC, so Home > Find now also
  finds bills, statements, policies and receipts by the words inside them ("water meter", "policy renewal 2025").
  Adults only; children never see archive results.
- The text is masked before it is stored: full account and card numbers, SSNs, emails and phone numbers become
  placeholders (last four kept), as for the AI. Scans and photos without a text layer are found by vendor, type and
  file name.
- The daily task and every inbox check update the index; only new or changed files are read. Run it yourself with
  `python data/archive_search.py index` (`--rebuild` to start over), search with `find WORDS`, see counts with `status`.
- Chat: adults can send `/find WORDS` in a private chat with the Telegram or Discord bot. The reply lists date, type
  and file title only, never document text. Refused in groups and servers and for children.
- The index is derived data: exports leave it out, `purge.py all` empties it.
- New: **receipt photos read by AI** (opt-in). With `"ai": {"read_receipt_photos": true}` (asked by
  `python onboard.py add ai` for API key providers and Ollama), a receipt photo (`.jpg`, `.png`, `.webp`, up to 5 MB)
  in the inbox goes to the family's own provider. Store, date, total and card last four come back, the receipt is
  filed and matched to the card charge. Off by default: a photo cannot be masked first, so what is printed on it
  reaches the provider (with Ollama it stays on this PC).
- An unclear photo, one that is not a receipt, a low-confidence answer, or an answer with a full card number goes to
  the review queue with the AI's guess in the note. The CLI providers (`claude_cli`, `codex_cli`, `gemini_cli`) are
  text only and never get photos. `ai.vision_model` sets a separate model for photos.
- New: **`/ask` in chat** for adults, in a private chat only: "how much did we spend on groceries in September?" is
  answered by the family's AI through the assistant's fixed action catalog. Read-only: a question that would change
  records is refused ("only on the family PC"). Raw query output stays on the PC; only the short answer is sent.
  Identifiers are masked as in `data/assistant.py`. 20 questions a day per person (`chat.ask_per_day` in
  `config/family.json`). The question text is never logged. Children cannot use it (COMPLIANCE.md: children do not
  use the AI). On Discord it is a slash command `/ask` (reply may take a few seconds) or plain text in a DM.
- New: **meals.** Family > Meals: the week's plan (breakfast, lunch, dinner, snack; a recipe or plain text like
  "leftovers"), the family's recipe book (ingredients one per line, `2 cups rice` keeps the amount, `salt (pantry)`
  marks a staple), and one button that puts the planned recipes' ingredients on a shopping list. The same ingredient
  from several meals is merged (2 + 1 onions = 3), staples are left off, items already open are not added twice,
  and a meal's ingredients go on the list only once. Terminal: `python data/meals.py recipe add | plan | week | shop`.
  The assistant can plan meals and fill the list too. Adults only; kids see the result on the shared list.
- Tests: the dashboard forms that had no screen test now have one (add a person, update a loan, add and unlink a
  receipt, the work contract, invoice, calendar day, pay days, profile and schedule forms).

## 0.39.1
No database change. Fixes found in the first live Telegram trial.
- `onboard.py add telegram` / `add discord` now apply pending database migrations first, so the chat tables exist.
- When Windows refuses a sign-in task (needs admin on some PCs), the bot starts from a launcher in the Startup folder.
- An adult added with `members.py` gets an adult chat link (the stored member role is used).
- The "not a member" message shows the `members.py add` command to run.

## 0.39.0
Database: migration 034 adds `chat_links.alerts` (off for everyone; applied by `python onboard.py update`).
- New: **morning alerts from the chat bots.** Each person can send `/alerts on` in a private chat with the bot, or
  an adult can run `python data/chat_core.py alerts NAME on`. The daily task then sends a private message when
  something is due: adults get overdue items and the next 3 days with amounts, children only their own items and
  family entries, never money.
- Nothing due means no message. At most one alert a day per account, even if the task runs twice.
- Never posted in a group or server. On Discord the alert is a direct message sent without the bot window running.
- `python data/chat_alerts.py preview NAME` shows a person's message; `send --dry-run` shows today's without
  sending. A failed send is logged (reason only, never the text) and does not stop the others.

## 0.38.0
No database change.
- New: **send bills, statements and receipts to the chat bots.** Adults send a photo or file to the Telegram bot in a
  private chat, or attach it in a direct message to the Discord bot (up to 5 per message). It is saved into `inbox/`
  with the same checks as the dashboard upload, and the next inbox check files it.
- Children cannot send files. Files in a group or server channel are refused without being downloaded, as are
  files that are too large or of the wrong type.
- The content has to match the file name: a program or web page renamed to `.pdf` or `.jpg` is refused. At most 20
  files a day per person. Captions and message text are never read as instructions.
- File names are kept: `inbox/2026-10-09_101500_telegram_Water bill.pdf`. The chat log records only that an upload
  happened and whether it worked, never the file name.
- Telegram and Discord keep their copy of the file in the chat; `docs/CHAT.md` says how to avoid that for
  statements.

## 0.37.0
No database change.
- New: **Discord bot**, for families whose kids already use Discord. Set up with `python onboard.py add discord`: it
  walks you through the Developer Portal (Public Bot off, no privileged intents), takes the token (hidden, saved only
  in `config/secrets.env`), checks it, prints the link that adds the bot to your family server (permission: send
  messages only), offers to install the `discord.py` package, and can start the bot at every Windows sign-in (task
  `FamilyAgent Discord Bot`). Guide: `docs/CHAT.md`. `python onboard.py doctor` checks the token.
- Slash commands in the server or a direct message: `/due`, `/week`, `/whoami`, `/unlink`, `/help`, `/start CODE`.
  Plain words also work in a direct message.
- In the server, only the person who asked sees the reply, and there are **no money items even for adults**. Bills
  and amounts appear only in a direct message, and never for children. Pairing codes work only in a direct message.
- The same family member can link both Telegram and Discord (one code each; a code can be locked to one app with
  `chat_core.py invite NAME --platform discord`).
- Optional extra `chat` in pyproject (`pip install -e .[chat]`). The Telegram bot still needs nothing extra.

## 0.36.0
Database: migration 033 adds `chat_links`, `chat_invites`, `chat_log` (applied by `python onboard.py update`).
- New: **Telegram bot** so the family can ask FamilyAgent from their phones. Set up with
  `python onboard.py add telegram`: it walks you through @BotFather, takes the token (hidden, saved only in
  `config/secrets.env`), checks it, and can start the bot at every Windows sign-in (task `FamilyAgent Telegram Bot`;
  macOS/Linux get a crontab line). Full guide: `docs/CHAT.md`. `python onboard.py doctor` checks the token.
- The bot runs on this PC (`python data/chat_telegram.py run | check | once`) by long polling: nothing is opened to
  the internet, and the token is only ever sent to api.telegram.org. Text commands only; photos are ignored for now.
- Telegram bot chats are not end-to-end encrypted, hence the rules below.
- **Chat core** shared with the Discord bot coming next (`python data/chat_core.py`).
- Pairing: an adult runs `python data/chat_core.py invite NAME` on this PC and gets an 8-digit code (works once,
  15 minutes, only its hash is stored). The family member sends `/start CODE` to the bot in a private chat.
- Strangers get no reply at all. Five wrong codes in an hour block pairing for that chat account for the hour.
- Roles: children and teens (`limited`, the default for members marked child) never get money information, the same
  rules as their dashboard. Adults get bills and amounts only in a private chat, never in a group or server channel.
- Commands so far: `/due`, `/week`, `/whoami`, `/unlink`, `/help`. Replies come from the database, no AI.
- `chat_core.py links | revoke NAME | log` (the log records who, which command and the outcome, never the text);
  `try telegram ID TEXT` tests a message on this PC. `purge.py` removes a person's chat links and codes.

## 0.35.0
No database change.
- New: **spoken morning brief** (`python data/make_audio_brief.py`): about a minute of plain sentences made from the
  same items as the Home tab (overdue first, then the next seven days, the first six by date, "and N more"), written to
  `brief/YYYY-MM-DD_audio.txt` and, with a voice, `brief/YYYY-MM-DD_audio.wav`. No AI writes it.
- Voices: `python data/make_audio_brief.py setup --engine system` uses the voice built into the computer (Windows
  speech, offline; macOS `say`; Linux `espeak-ng`). `--engine voicestudio` uses a VoiceStudio app you installed
  yourself on this PC (its local speech service; any address other than this PC is refused so the text stays here).
  Off by default (`--engine none`).
- The daily task speaks the brief when a voice is set. Add `"audio"` to `drive.push` in `config/family.json` to get the
  newest audio file in Drive `Brief/` next to the PDFs; like them, it carries names, payees and amounts.
- Not tested with a real VoiceStudio install (only against a stand-in for its speech service).

## 0.34.0
No database change.
- New: **bank and card statement PDFs without AI** (`python data/pdf_statement.py FILE.pdf`, `check FILE.pdf` to only
  look). It finds the account by the last four digits printed on the statement, the period, and every
  "date ... description ... amount" line (posted and transaction dates, reference numbers, paid checks, an extra
  balance column). Cards: charges become money out, payments and credits money in. Bank accounts: the section heading
  (Deposits / Withdrawals / Checks / Fees) decides. Then it checks the arithmetic: beginning balance plus money in minus
  money out must equal the ending balance to the cent. Only a statement that checks out is imported automatically.
- Intake: a statement the AI recognises is now imported straight away when its balances check out (before, every
  statement waited for the Claude finance agent). One that does not check out waits in the review queue with the reason.
- Review queue: filing a PDF as type "statement" imports it the same way and says how many transactions were added.
- Lines already loaded (same reference, or the same date, description and amount) are skipped, so importing a month
  twice, or after a CSV export of it, adds nothing. Category rules run afterwards and waiting receipts are matched.
- Tried on 18 real statements from one US bank (checking with paid checks, and a cashback credit card): all 18 read
  completely and check out. Other banks' layouts are untested: run `check` first and tell us if the balances differ.

## 0.33.0
Migration 032 (additive: new table `receipts`).
- New: **receipts matched to card charges**. A receipt (an e-receipt PDF filed by intake, a photo you describe in the
  review queue on Home, or one typed on Money > Receipts) is matched to the charge with the same amount posted a day
  before to five days after. A store name in the charge makes it "high"; the only charge of that amount is "medium";
  a charge up to 30% higher with the store's name is offered as a "possible tip" (low). Two equally good charges are
  left for you to pick. Receipts that arrive before the charge are matched when the next statement is imported.
- New: **Money > Receipts**: matched receipts with their charge, waiting receipts with up to three candidate charges
  and a Link button, Unlink for a wrong match (it is then left alone), and "no charge expected" for cash or gift cards.
  `python data/receipts.py add | match | list | candidates | link | unlink | ignore` does the same from a terminal.
- New: the review queue shows a photo (PNG, JPG, WEBP) next to its form, so a receipt picture can be typed in.
- Receipt photos are not sent to any AI: reading pictures stays a person's job for now (an opt-in setting may come later).

## 0.32.0
Migration 031 (additive: four columns on `contracts`, new tables `work_hours`, `work_calendar`, `work_invoices`).
For adults who bill their time (self-employed, consultants, contractors). Part of the work contracts pack
(`python onboard.py add packs`), which adds a **Work** tab next to Money.
- New: **work profile** on the Work tab > Profile: client, vendor, contract number, dates, hourly rate, invoice
  frequency (weekly / every two weeks / twice a month / monthly), timesheet cycle (weekly / every two weeks) and the day
  one cycle starts, hours per day, work calendar. Add a contract from the dashboard or `python data/work.py add`.
- New: **hybrid schedule**: one cycle of days (7 or 14), each On site / Off site / Working / Off, repeating. It plans
  the hours and fills in on / off site for every day worked.
- New: **work calendar**: import the employer's or client's calendar PDF (holidays, floating holidays flagged, pay days
  under a "Pay days" heading), add single days, or pay days by rule (every 14 days, twice a month, a day of the month).
  Holidays are taken out of the planned hours.
- New: **timesheet import** without AI: grid timesheets (a row of dates and a "Time Worked" / "Hours" row; several pay
  periods in one file; a December-January period gets the right years), one "date ... hours" line per day, or CSV.
  Only dates, hours and on / off site are kept: no names, supervisors or IDs. A timesheet saved as a picture is refused
  with advice: print the page with the browser's "Save as PDF" (keeps the text), export CSV, or type the hours.
- New: **hours grid** per timesheet period, prefilled from the plan for past days; change what differs and save.
- New: **monthly billing**: hours, hours x rate, days on site / off site, hours per week, pay days, and warnings
  (scheduled days with no hours, days with 0 hours, hours on a holiday). Record the invoice, then mark it sent / paid.
- New: **reminders** on Home: "Invoice <client> for <period>" once a period ends with no invoice recorded, and a sent
  invoice not marked paid after 30 days.
- New: intake types `timesheet` and `work_calendar` (filed under `archive/<year>/work/`); with one contract they are
  imported straight away. `python data/work.py offsite YEAR` counts off-site days as a record for the home-office figures.

## 0.31.1
Docs only (audit Phase 1 item 9, the last open Phase 1 item). No database or code change.
- New: **`docs/DATA.md`**: what is stored where (database tables by area, folders, config, logs, backups), what can
  leave this PC and only when you set it up (your AI provider with masking, Drive `Brief/`, GitHub for updates), how
  to export everything, how to delete one person or everything, and what a purge cannot reach (backups elsewhere,
  exports, Drive, your AI provider's retention). Linked from README and SETUP_NEW_FAMILY.
- This is the first update your install checks for a signature ("Signature OK" when you run `python onboard.py update`).

## 0.31.0
Signed releases (audit Phase 1 item 10, C5/M5). No database change.
- New: from now on every release carries `SHA256SUMS` (the SHA-256 of every file) and `SHA256SUMS.sig` (an Ed25519
  signature by the maintainers' key). `python onboard.py update` checks the signature against the public key your
  install already has (`data/release_keys.json`), then checks that every downloaded file (zip installs) or every
  file of the release tag (git installs) matches the signed list, before it replaces anything. It prints
  "Signature OK" when it does. A wrong signature, an unknown key, or a changed, extra or missing file stops the update
  and nothing is changed.
- A release without the signature files also stops the update, with a message. `--allow-unsigned` accepts it (for a
  zip you were sent and trust); it never excuses a BAD signature.
- Offline updates: keep `SHA256SUMS` and `SHA256SUMS.sig` in the same folder as the zip for `update --from FILE.zip`.
- Downloads follow redirects only to GitHub hosts over https, and your read-only token is no longer sent along when
  GitHub redirects a download to its file servers.
- **This update itself is not checked** (your current version does not know how yet); the next one will be.
- Maintainers: `scripts/sign_release.py init | sign vX.Y.Z | pubkey`; RELEASING.md has the new steps. The checker
  (`data/ed25519_verify.py`) is pure standard library, tested against the RFC 8032 vectors and `cryptography`.

## 0.30.0
Saved items (roadmap "Near term"). Migration 030 (additive: one new table, `saved_items`).
- New: **Family > Saved**: links, notes, places and deals to find again (a git repo, a news article, a YouTube video,
  a restaurant, an offer that ends Friday). Type a title, paste a link (optional), add a note, tags, an address or a
  deal end date, and choose who sees it: everyone, adults only, or **only me**. The kind (repo, video, social, place,
  link, note) is guessed from the link; an end date makes it a deal. Search by any words, filter by kind, tag or who
  added it; pinned items come first; pin, re-tag or archive an item (nothing is deleted).
- Safety: **nothing is fetched from the internet**: no page titles or previews are downloaded, links are never
  embedded and only open in a new tab when clicked. Only `http://` / `https://` links are stored; tracking parts
  (`utm_...`, `fbclid`, `gclid`, YouTube `si`, ...) are removed; links with a user name/password, an email address or
  something that looks like a login token (`token=`, `access_token`, `sig`, `password`...) are refused. Notes are
  checked like other free text (no full card / account / ID numbers, no email addresses). "Only me" hides an item
  from everyone else on the dashboard (other adults too); anyone with access to this PC's files can still read the
  database, and the terminal lists them marked `[private]`. The edit log records ids and kind, never titles or links.
- New: **Home > Find**: one search box over saved items and the shared lists.
- New: kids get **"Our saved links"** on their own screen: family items only (adults-only and private ones never
  show), search, and a small add row (up to 30 a day; they can archive only their own).
- Deals with an end date join the **expiry reminders** (type `deal`, 3 days before by default; change with
  `python data/expiries.py lead deal N`): Action items, the digest's Expiring section, Family > Expiries & IDs and the
  calendar file. Ended deals drop off the lists (still found with `find --all` / "Show archived and ended deals").
- Digest: a **Saved** line ("Saved this week: 4 (2 links, 1 place, 1 deal)"; private items not counted).
- Export: `export_data.py` also writes **bookmarks.html** (import it into any browser). `purge.py person NAME`
  removes that person's private items and clears their name from the shared ones.
- Phone (opt-in): add `"saved"` to `config/family.json` `"drive": {"push": [...]}` to send `saved.pdf` (pinned
  family items only) to Drive `Brief/`. Off by default because links can be personal.
- Assistant: `saved_add`, `saved_find`, `saved_deals` ("save this repo https://github.com/... as voice cloning tool",
  "what was that pizza place near the station?", "which deals are still on?").
- Terminal: `python data/saved.py add "<title>" [--url U] [--kind K] [--note T] [--tags a,b] [--where ADDRESS]
  [--until DATE] [--adults | --private --by NAME] | find "<words>" [--kind K] [--tag T] [--all] | show ID |
  tag ID +x -y | pin ID [--off] | archive ID | recent [N] | deals | brief`.
- Search is plain word matching (every word must appear in the title, note, tags, address, site or link), not
  SQLite FTS5: a household's saved items are a few hundred rows, and an FTS index's shadow tables would complicate
  export, purge and backups.

## 0.29.0
Shared lists (roadmap "Near term"). Migration 029 (additive: two new tables, `lists` and `list_items`).
- New: **Family > Lists**: everyday lists the whole family shares (groceries, a Costco run, packing, Saturday jobs).
  Tick an item and it is saved at once; add items with a quantity and, optionally, who it is for; **Clear ticked**;
  remove an item; archive a list (its items are kept); **Make a new list** (shopping / to-do / packing), optionally
  **adults only**. A "Groceries" list is there to start with. Ticked items fade off after 7 days.
- New: **kids can tick off and add** on their own screen ("Our lists"), on family lists only: adults-only lists
  never show, and kids cannot remove items, put names on them, or make or archive lists. Up to 50 open items per
  person per list. Item text is checked like any other free text (no full card / account / ID numbers, no email
  addresses). The edit log records who did what by id, never the item text.
- New: **the lists on your phone**: with Drive set up, `sync_drive.py push` also sends `lists.pdf` (open items on the
  family lists, adults-only lists left out) to Drive `Brief/`; nothing is sent when every list is empty. Turn it off
  by leaving `"lists"` out of `config/family.json` `"drive": {"push": [...]}`.
- New: the weekly digest gets a **Lists** line (open items per list), and the assistant can add to, tick off and
  read the lists ("add milk to groceries").
- Terminal: `python data/lists.py show | new "<list>" [--kind shopping|todo|packing] [--adults] | add "<list>"
  "<item>" [--qty Q] [--for NAME] | done | undo | drop | clear | archive | summary | brief`.
- Changed: the Family sub-tab "Other lists" is now **More** (it holds vehicles, appointments and the rest), so it is
  not confused with Lists. The shopping pack's Shopping tab (planned purchases with dates and prices) is unchanged.
- `purge.py person NAME` clears that name from list items (the items stay); exports include both tables.
- Tests: copies made by the test suite no longer take the install's own `config/` files (only `*.example.json`),
  so `pytest` inside a family's install neither reads that family's settings nor copies `secrets.env`.

## 0.28.0
Household inventory (roadmap "Near term"). Migration 028 (additive: four columns on `home_assets`).
- New: **Family > Assets & inventory**: appliances, systems and big purchases with where they are, brand and model,
  purchase date, price, store, warranty (end date or years), serial last four, and the **receipt and manual filed in
  `archive/`** picked from the documents list. Four tiles on top: items, value (where prices are known), under
  warranty, need a receipt / manual. Add, change, attach and **Mark gone** (sold / disposed / lost) are forms on the
  tab, adults only, logged without names or serials. A gone item keeps its history but leaves every list, the expiry
  reminders and the inventory value; tick "Show sold / disposed / lost items" to see it.
- New: intake type **manual** (`archive/<year>/manuals/`), from the review queue, `python data/ai_intake.py file ID
  --type manual ...` or the AI pipeline, so a manual dropped in the inbox can be attached to its appliance.
- New: the weekly digest gets a **Household inventory** line (items, value, under warranty, missing receipts and
  manuals) once there is something in it.
- Terminal: `python data/assets.py add | set "<item>" --location ... | attach "<item>" <document_id> --as manual |
  dispose "<item>" --how sold --date D | summary | list --all`.
- Tests: the old-release upgrade fixture now holds back every migration from 025 on (it used to assume 025 was
  among the three newest).

## 0.27.0
Expiry reminders generalised (roadmap "Near term", first item). No database migration.
- New: **Family > Expiries & IDs** opens with **Everything that expires**: passports and other ID documents, vehicle
  registration and inspection, warranties, vaccinations (life items of type vaccine) and insurance terms in one table
  with the status (expired / renew soon / ok / needs a date), the date and the day the reminder starts. Nothing is
  copied: the rows are read from where they already live.
- New: **a reminder lead time per type** (how many days before the date the reminder starts), from the same tab or
  `python data/expiries.py lead TYPE DAYS` (`default` resets). Saved in `config/expiries.json`, on top of the country
  profile (passports 9 months; UK BRP 6 months) and the built-in defaults (other IDs 120 days, vehicle registration
  60, inspection 45, warranty 90, vaccination 30, insurance 30). The Action tab, the weekly digest, the `.ics` file
  and the ID / Assets tabs all read it, so one setting changes every reminder of that type.
- New: **Set an ID document's expiry date** from the dashboard (person, document, date, optional last four), adults
  only, logged without the number. Until now this was terminal-only.
- New: the weekly digest gets **Expiring**, listing everything inside its reminder window whatever the date (a passport
  nine months out never fitted the 30-day horizon before), plus the documents that still have no date.
- Fixed: a warranty ending within 90 days appeared twice on the Action tab and in the digest ("Warranty ends" and
  "Warranty ends: ..."). Vehicle registration and inspection now wait for their lead time instead of showing as soon
  as they fall inside the dashboard's 180-day horizon.
- Terminal: `python data/expiries.py list | soon | leads | lead TYPE DAYS`.

## 0.26.0
Budget vs actual, live (roadmap "Next", second item). No database migration.
- New: Money > Budget & loans opens with **This month so far**: each budget line with what is spent, the limit, what
  would be spent by now at an even pace, the projection to month end and a light: red = already over, amber = on course
  to pass the limit, green = on track. The month is measured up to the newest loaded transaction, not the calendar
  day, so an unloaded statement never looks like money unspent (the heading says "through <date>").
- New: **Suggested limits from the last six full months** (average spend per category, rounded up to 10, next to the
  current limit) with a one-click **Use this limit**. Adults only, logged as before.
- New: **Allowance lines**: `python data/budget.py allowance NAME AMOUNT` or the form on the same tab creates a budget
  line `allowance:NAME`, grouped at the end of the table. Children's screens are unchanged and still read no money.
- New: the weekly digest gets one line, **Budget this month**: lines over, lines on course to pass, how many on track.
- Terminal: `python data/budget.py pace | suggest | allowance NAME AMOUNT`; `set`, `list` and `report` as before.

## 0.25.0
Recurring bill detection (roadmap "Next", first item). No database migration.
- New: the Money > Bills tab ends with **Recurring payments seen in your statements**: every payee charged at a
  monthly, quarterly or yearly interval for three or more cycles (utilities, insurance, loan payments, anything that
  is not a transfer, income or a card payment), with its expected amount (median of the last three charges, "varies"
  when they differ), how many charges, the last one and any price rise. **Track as a bill** adds the next expected
  charge to Bills; **Not a bill** stops proposing it. Adults only, logged to `logs/edits.log` without the payee name.
- New: tracked bills look after themselves. The weekly task runs `python data/recurring_bills.py sync` before the
  digest: when the charge appears in a loaded statement the open bill is marked paid with that date and amount, and
  the next cycle row is added. A charge more than 10% above the earlier ones is flagged as a price rise; a charge that
  is 7 days late although newer transactions are loaded is flagged as missing (Bills tab and the weekly digest's
  "Recurring bills" section, which also lists up to five new candidates).
- New: the same from a terminal: `python data/recurring_bills.py detect | confirm "<payee>" [--name NAME] | dismiss
  "<payee>" | status | sync`. Tracked and dismissed payees live in `config/recurring_bills.json` (git-ignored with the
  rest of `config/`); edit it to undo a dismissal.
- The digest line "Other recurring payments seen" is replaced by that section; the Subscriptions tab caption points to
  the Bills tab for payees that are bills rather than subscriptions.

## 0.24.0
Review queue in the dashboard (audit Phase 3, item 19, last part). No database migration.
- New: on the Home tab, **Files waiting for review** now shows a small form per file: type (bill, receipt, policy, tax,
  medical, investment, statement, other), who it is from, document date, optional amount and due date. **File it**
  renames the original to `YYYY-MM-DD_vendor_type.ext`, moves it into `archive/<year>/<category>/`, records it in
  `documents` and, for a bill or policy with an amount and due date, adds the `bills` row (not twice). No AI is involved;
  the row is marked resolved. **Dismiss** closes a row without filing (the file stays where it is). Adults only; each
  action is appended to `logs/edits.log`.
- New: the same from a terminal: `python data/ai_intake.py file ID --type bill --vendor "Acme Power" --date 2026-09-01
  [--amount 40 --due 2026-09-25 --note ...]` (`review` lists the ids). Bad input changes nothing and exits 2.
- Under the hood `ai_intake.file_document()` is the one place that archives and records a document; the AI pipeline
  uses it too, so a vendor the model produces that fails validation (for example a full account number) now goes to the
  review queue instead of being filed.

## 0.23.0
Export and purge (audit Phase 3, item 19, third part). No database migration.
- New: **`python data/export_data.py`** writes every table of the database as CSV files into `exports/<date_time>/`
  with a `manifest.json` (row counts, version) and a README. `--format json|both`, `--tables bills,transactions`,
  `--out DIR`, `--zip`. Plain files for a spreadsheet, an accountant, or for leaving. Nothing is sent anywhere.
- New: **`python data/purge.py person NAME`** removes one person's rows (life items, appointments, ID documents,
  contracts, recurring checkups and their log, home-office figures, seasonal tasks, the members row), clears their name
  from shared money rows (card holder, account and vehicle owner), drops their hide/snooze state, their entry in
  `config/family.json`, their dashboard login and login-throttle record. **`python data/purge.py all`** empties every
  table (schema kept), removes `config/*.json`, briefs, reports, logs and pre-upgrade backups; `--archive` also deletes
  `inbox/` and `archive/` originals. Both are a dry run until `--yes`. `person` keeps a database snapshot in
  `data/backups_pre_upgrade/`; both write a receipt with counts to `logs/purge_*.json`; the database is VACUUMed so
  deleted rows do not linger. Backups outside the folder are listed for the family to delete by hand.
- `exports/` is git-ignored. `SETUP_NEW_FAMILY.md` gains a "Leaving, or removing one person" section.

## 0.22.0
Calendar file (audit Phase 3, item 19, second part). No database migration.
- New: **`python data/export_ics.py`** writes `brief/familyagent.ics`: every due date the Action tab and weekly digest
  know about (bills, renewals, appointments, birthdays, subscriptions, warranties, ID documents, recurring checkups)
  as all-day events with a reminder the day before. Import it into any phone or desktop calendar; no Google account
  or connector needed. Items marked done, snoozed or ignored are left out. Options: `--horizon DAYS`, `--kinds
  Bill,Renewal,Birthday`, `--alarm N` (0 = no reminder), `--no-amounts`, `--out PATH`, `--stdout`.
- Event ids come from the item's stable key, so importing the file again updates events instead of duplicating them,
  and a paid or snoozed item disappears from the next export. Each description carries the 8-character Id used with
  `action_state.py done/snooze`.
- Dashboard > Settings has a "Download familyagent.ics" button. The weekly task refreshes the file and
  `python data/sync_drive.py push` copies it to the Drive `Brief/` folder (`drive.push` list now defaults to
  `["daily", "weekly", "ics"]`; leave `"ics"` out to stop that).
- What the file contains: vendor names, titles, amounts (unless `--no-amounts`) and last-4 identifiers, exactly as the
  Action tab shows them.
- `ROADMAP.md` added: what is planned, in order, and why.

## 0.21.0
Statement import without AI (audit Phase 3, item 19, first part). No database migration.
- New: **`python data/import_statement.py FILE.csv --account NAME`** loads a bank or card CSV/activity export into
  `transactions` with no AI and no re-typing. The column mapping is guessed from the header (date, description,
  amount or debit/credit, reference, card member, category), with `--map date=Posted,desc=Details,amount=Amount`
  when the names are unusual; `--dates dmy` reads day-first dates (UK/EU exports); semicolon and tab files and the
  "Account: ..." preamble lines banks put above the header are handled; `1.234,56` amounts are read.
- Card exports that print charges as positive numbers are inverted automatically for credit accounts (`--sign`
  overrides), and payment credits are typed `card_payment` so they are not counted as spend.
- Safe to re-run: rows are skipped by reference number, or by count of identical (date, description, cents) rows,
  so two identical same-day charges both stay. A row whose date or amount cannot be read stops the whole import and
  is listed. `--dry-run` shows what would happen; `detect FILE` shows the header and the guess.
- `--save-format KEY` remembers the mapping, date order, sign and account in `config/statement_formats.json`
  (survives updates); `--format KEY` reuses it. `--balance X --as-of DATE` records the statement's closing balance
  for the net-worth view. `--new "Name" --type checking` creates the account on the spot. Categories are applied
  afterwards with the family's rules.
- Agents: the finance and card-extract agents now point CSV exports at the importer instead of reading them.

## 0.20.0
Privacy release for the Claude Code path. Off by default; no database migration.
- New, opt-in: **masking for Claude Code agents.** Until now `claude_code` agents opened documents with their own
  Read tool, so the full text went to Anthropic under your account (the only path without masking). Set
  `"ai": {"agents_read_redacted": true}` in `config/family.json` (the wizard's AI step asks) and the guard hook
  refuses Read, Grep and `cat`-style commands on `inbox/` and `archive/` files; agents then read each document
  through `python data/pii.py read FILE`, the same masking as the Python pipeline (SSN/ID/account/card numbers with
  the last four kept, emails, phones, dates of birth, addresses, your family's names).
- Trade-off, stated plainly: with the option on, photos and scanned PDFs cannot be masked, so agents cannot read
  them at all; they stay in `inbox/` under "Needs your input" for a person. Leave the option off if most of your
  documents are phone photos.
- New: `python data/pii.py read FILE` prints the masked text of any document.
- Docs: THREAT_MODEL.md T2 updated; the four document agents explain the read-through.

## 0.19.0
Country profile release (audit Phase 2, item 17). No database migration. US families see no change; families
elsewhere stop getting US tax forms, US ID types and square feet.
- New: **one country profile per household** (`packs/country/<code>.json`, chosen by `country` in `config/family.json`,
  the wizard asks first). It sets the currency default, units (sq ft / m², miles / km), the labels of the address
  fields, the ID document types and their renewal lead times, the vehicle paperwork names, the tax-paper checklist
  and tax year, the simplified home-office rule, the seasonal pack for each climate and the starter categorisation
  rules. Shipped: `us`, `uk` (P60/P11D/Self Assessment, HMRC flat rate, DVLA/MOT, Tesco-to-TfL starter rules) and
  `generic` (used by CA, AU, NZ, IN and others, with their currency and units). `python data/country.py list`.
- New: a family can adapt a profile by copying it to `config/country/<code>.json` and editing; the copy is merged
  over the shipped one and survives updates.
- Changed: `tax_prep.py`, `home_office.py`, `id_docs.py`, `apply_rules.py` and `seasonal_packs.py recommend` read
  the profile instead of carrying US rules. The home-office report names the rule it applied and the area unit.
- Changed: the wizard's region questions use the country's labels (County / Postcode for the UK) and default the
  currency from the profile.

## 0.18.0
Money arithmetic release (audit Phase 2, item 13). One tiny migration (two computed columns); no screen changes.
- Fixed: **amounts are compared and summed in whole cents.** Dedupe on statement re-import, Amazon order matching and
  the Python-side totals used float equality, so 0.30 and 0.30000000000000004 were different amounts. Everything now
  goes through `data/money.py` (`cents`, `round2`, `eq`, `total`, `parse`).
- Database: `transactions.amount_cents` and `bills.amount_cents` are generated integer columns (always equal to the
  amount in cents, never written) for exact matching in SQL. Amounts themselves stay in the family's currency as
  before, so the views, the Claude Code agents and your own queries keep reading and writing 12.34, not 1234.
- Forms and assistant: amount fields accept what people type ("$1,234.56", "1.234,56", "(12.00)", "40 CR") and store a
  whole number of cents; rates and square feet are unchanged.
- Changed: the Python inbox pipeline stores bill amounts rounded to the cent.

## 0.17.0
Dashboard release (audit Phase 2, item 15). Same five tabs and screens; faster, and the PIN screen is harder to guess
against. No database migration.
- Security: **wrong PINs are now counted in a file** (`logs/login_throttle.json`), not in the browser tab, so
  reloading the page no longer resets the count. Five wrong PINs for a name within 15 minutes lock that name for
  30 seconds, then 1, 2, 5 and 15 minutes on repeat; fifteen wrong PINs across all names lock everyone. A correct
  PIN clears the count. (This is a brake on guessing on a shared PC, not strong security: see data/auth.py.)
- Faster: everything the tabs compute from the database (what needs attention, seasonal tasks, statement watch,
  subscriptions) is computed **once per page load and cached until the database changes**, instead of three to
  four times per load. The Refresh button clears the cache.
- Code: `data/dashboard_app.py` (1,500 lines) is now a 60-line entry point over `data/dashboard/` with one module
  per tab (home, calendar, family, money, settings, login, shared events and helpers). Families' bookmarks, the
  `.bat`/`.sh` launchers and `streamlit run data/dashboard_app.py` are unchanged.
- Changed: bill and deposit amounts in tables use the family's currency format rather than a fixed "$".

## 0.16.0
Row identity release (audit Phase 2, item 14). One small migration; the screens look the same.
- Fixed: **hiding, snoozing or finishing an item now sticks to the record, not to its wording.** Items were keyed by a
  hash of type + title + date, so correcting a vendor name brought a hidden bill back, and two bills from one vendor
  due on the same day were one item. Items that come from a database row are now keyed `<table>:<row id>:<date>`;
  the migration re-keys what you already hid so nothing resurfaces. Price spikes and other computed items keep the
  old key (they have no row of their own).
- Fixed: on the Home tab and in "Handle an item", **Paid marks exactly that bill** (by row), so two same-day bills
  from one vendor can each be paid. The "could not tell which bill" warning is gone.
- Fixed: the family-meeting brief matched names inside other words ("Al" picked up "Allstate"); whole words only now.
- Terminal: `python data/action_state.py done|snooze|ignore|reset` still takes the 8-character Id from the digests
  and also accepts the full key shown by `action_state.py list`; an unknown Id is refused instead of stored.

## 0.15.0
Database integrity release (audit Phase 2, item 12). One migration runs on update; it rebuilds the main tables once,
which takes a few seconds on a large database. Nothing changes on screen.
- Database: **date and status columns are now checked by the database itself.** A bill due "10/15/2026", an event
  dated "tomorrow" or a status word nobody knows can no longer be stored; the scripts, forms and agents already
  validated, now the database refuses too. Existing rows are repaired first (slashed or dotted dates become ISO;
  an unreadable optional date is cleared and listed). If a row cannot be repaired, that one table keeps running
  without the check and `python data/migrate.py status` names it, so the update never fails on old data.
- Database: the indexes the dashboard and digests needed (transaction dates, bill status + due date, document
  type and date, life items by member, events, appointments, ID expiries) and a unique index on (account, source
  reference) so a statement re-import cannot store the same line twice. Deleting a filed document now unlinks the
  rows that pointed at it instead of being refused.
- Updates: **every migration runs against a snapshot.** If one fails, the database file is put back exactly as it
  was and the version marker is not advanced, so a half-applied update cannot happen. Each migration's checksum is
  recorded; `python data/migrate.py status` flags a script edited after it ran and `migrate.py verify` fails on it.
- Fixed: a database from before 0.3 (no `transactions.ref` column) could not run the first migration.
- Changed: migration 006 no longer seeds the US cold-climate task list into every database; the wizard applies the
  pack for the family's country and climate (`python data/seasonal_packs.py apply KEY` by hand). Installs that
  already have those tasks keep them.
- Documented: migration number 011 was never shipped; the gap is deliberate.

## 0.14.1
- Fixed: a labelled account number written in spaced groups ("acct 1234 5678 9012 4321") was masked in two pieces, showing a misleading "[id ending 1234]". It is now one "[id ending 4321]". Nothing leaked either way.

## 0.14.0
Privacy release: what leaves this PC for an AI provider is now masked properly, free-tier providers are refused, and
full identifiers can no longer be typed into records. No database migration.
- Security: **real redaction before anything is sent** (`data/pii.py`). Masked in every document or query result the
  Python pipeline sends: SSN/ITIN/EIN, card and account numbers of 8 digits or more (last four kept, with or without
  spaces or dashes), routing numbers, emails, phone numbers, dates of birth, driver licence / passport / policy / member
  / VIN numbers after their label, street addresses, and your family's own names (replaced by `[person1]`... and mapped
  back locally when the answer comes in). Amounts, dates, times and vendor names are untouched, so filing accuracy does
  not change. Previously only runs of 9+ digits were masked.
- New: see exactly what would be sent for a file, without sending it: `python data/llm.py redact-preview FILE`.
- Security: the model is also told, in every prompt, that the data is private and to use it only for the requested
  fields; and an answer that still contains a full identifier is rejected and the file goes to the review queue.
- Security: **free-tier providers are refused.** `gemini` and `gemini_cli` run only after the family confirms a paid
  tier with billing enabled (`ai.gemini_paid_tier_confirmed: true`; the wizard asks). Google's free tier may train on
  prompts. Ollama (nothing leaves the PC) is the recommended choice for the most sensitive households.
- Security: forms and the assistant refuse text that contains a full account, card, SSN-shaped number or an email
  address (store the last four digits only); the assistant masks identifiers in what you type and in query results
  before they go to the provider (family names stay, since you are talking about them on purpose).
- Settings: `"privacy": {"redact_names": true, "extra_terms": ["employer name", "school name"]}` in
  `config/family.json` adds words to mask or turns name masking off.
- Not covered: the Claude Code agents (`claude_code`) read files with their own tools, so no masking happens on that
  path; the documents go to Anthropic under your own account as before. See THREAT_MODEL.md.
- Action: if you use `gemini` or `gemini_cli`, run `python onboard.py add ai` once to confirm your tier.

## 0.13.0
Architecture release (audit Phase 2, first slice). No new screens. One thing to know: backups made from now on use a
stronger encrypted format; older backups still restore.
- Security: **encrypted backups are now AES-256-GCM** with every chunk tied to its file, position and "last chunk"
  flag, so a backup that was truncated, had chunks dropped, reordered or swapped from another file fails to restore
  instead of restoring silently wrong data. The passphrase-to-key cost went up (scrypt 2^15 -> 2^17). Backups written
  by 0.4.0 to 0.12.0 (format FAB1) are still read; a destination may hold both.
- Security: `config/secrets.env` is written atomically with owner-only permissions (chmod 600 on Mac/Linux).
  `config/family.json` and `logs/heartbeat.json` are written atomically too, so a crash mid-write cannot leave a
  half file.
- Changed: every script opens the database through one helper (`data/db.py`): foreign keys are enforced (a
  transaction can no longer point at an account or document that does not exist), read-only connections for reports
  and the dashboard. The nine copies of the date parser and the month arithmetic live in `data/dates.py`;
  "$" is no longer hard-coded: amounts follow `currency` in `config/family.json` (`data/money.py`).
- Changed: "table not migrated yet" is the only database error the digests and dashboard still skip quietly. A
  locked or damaged database, a full disk or a SQL typo now stop the script with an error instead of showing an
  empty section.
- New: `logs/familyagent.log` (rotated, 512 KiB x 3): scheduled task start/end and result, each AI call (provider,
  model, token counts; never the text), backups, updates, applied migrations. `FAMILYAGENT_LOG_LEVEL=DEBUG` adds
  the skipped not-migrated queries.
- Action: none. If `python onboard.py doctor` or a digest now reports a database error it used to hide, that is the
  point: run `python data/migrate.py` or check free disk space.

## 0.12.0
Engineering release (audit Phase 1). Nothing changes on a family's PC except two new files; no database migration.
- New: the checks now live in `tests/` as pytest modules (migrations from empty, from a schema-only and from an older-release database; every alerts provider on leap days and year boundaries; encrypted backup round trip; the updater in git mode; the wizard with scripted answers; the kid view "no money" invariant). `python scripts/smoke_test.py` still works and runs the same release gate (`python -m pytest -m smoke`). `pip install -r requirements-dev.txt` for pytest and ruff.
- New: GitHub Actions run ruff, `verify_clean.py`, a new agent-definition lint (`scripts/lint_agents.py`) and the full test suite on Windows, Ubuntu and macOS with Python 3.12 and 3.13.
- New: `pyproject.toml` (extras `dashboard`, `crypto`, `pdf`, `dev`), `.editorconfig`, `pre-commit` config, Dependabot, issue and pull request templates.
- New docs: `SECURITY.md` (how to report), `THREAT_MODEL.md` (what is protected from whom, and the known gaps), `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`.
- Changed: `verify_clean.py` skips `tests/` (synthetic account numbers on purpose); the updater lists obsolete files under `tests/` too; small lint fixes (unused variables, import style), no behaviour change.
- Action: none. Maintainers: `pip install -r requirements-dev.txt`.

## 0.11.1
- Fixed: after a zip update to 0.11.0, `doctor` reported "no original-family strings" because `scripts/verify_clean.py` scanned the pre-upgrade code copies in `data/backups_pre_upgrade/`. Those copies are now skipped (they are your rollback, not shipped code). Git installs were not affected.

## 0.11.0
Hardening release after an architecture audit. No new screens; safer agents and several bug fixes.
- Security: **agents are fenced in.** `.claude/settings.json` now allows writes only under `archive/`, `reports/`, `brief/`, `inbox/` and `config/category_rules.json`, file moves only from `inbox/` into `archive/`, and `python data/<script>.py`. Code, agents, `CLAUDE.md`, `tasks/`, `scripts/`, `python -c`, downloads, git and web search are denied. A new hook, `scripts/guard_tool.py`, checks every tool call the same way, so a document that tries to instruct the AI cannot make it edit code or read `config/secrets.env`. The unattended inbox run uses an explicit tool list instead of `--permission-mode acceptEdits`.
- Security: every agent that opens documents (`intake`, `finance`, `card-extract`, `insurance`, `bills`) now states that document text is untrusted data and what to do when a file contains instructions (leave it in `inbox/`, quote it, ask). The privacy rules live once in `CLAUDE.md`.
- Privacy: removed the original family's details that had been left in code (account last4 aliases, card and insurer names, car makes, order counts, dated notes). `python scripts/verify_clean.py` now also flags the *shapes* of such leaks (last4 maps, "card ending 1234", "the user asked", dated anecdotes, "doc 96"). Statement aliases are now per family: `"statement_aliases": {"<last4>": "<primary last4>"}` in `config/family.json`.
- Fixed: a full `python onboard.py` run no longer wipes the dashboard logins set in the "family" step.
- Fixed: a policy marked `replaced` no longer shows as "term ends" forever; accepted statuses are `active`, `expired`, `replaced`, `cancelled`.
- Fixed: a bad date (`snooze ID tomorrow`, a seasonal task with `02-30`, a bill with `10/15/2026`, `life.py done X 2026-13-01`) no longer crashes every digest and the Home tab; writes are validated, reads skip bad rows.
- Fixed: one-off events in `events` appeared twice in digests and on Home.
- Fixed: `pypdf` and `markdown` were missing from `requirements.txt`, so on a fresh install every PDF went to the review queue and Drive briefs were never converted to PDF. Run `python -m pip install -r requirements.txt` after updating.
- Changed: agents record new categorisation rules in `config/category_rules.json` (kept across updates) instead of editing `data/apply_rules.py` (replaced on update). Vehicle service defaults are generic (combustion vs electric) instead of make-specific. The reporter no longer refers to an `OPEN_QUESTIONS.md` file; it reports the review queue instead.
- Docs: `CLAUDE.md` rewritten (privacy section, module table, no stale version); README privacy wording covers all providers.
- Action: `python onboard.py update`, then `python -m pip install -r requirements.txt`. If you had customised `.claude/settings.json`, move your changes to `.claude/settings.local.json`.

## 0.10.0
- New: **edit in place.** Forms in the dashboard for what used to need the command line or the assistant:
  - Family > Life items: add an item (school, medical, pet, chores...), change its title/date/repeat/cost/where, mark it done (repeating items roll to the next date) or remove it.
  - Family > People: change a role or birthday, add a person or pet. Saved to the database AND `config/family.json`, so a later sync or update never undoes it.
  - Money > Budget & loans: set or remove budget lines; add a loan; update a balance, payment or payoff date, or mark a loan paid off (the balance date is recorded).
  - Family > Other lists: add a subscription, turn subscriptions on or off.
- New: **kid view:** a child or guest can mark their OWN non-financial items done ("I finished...") and nothing else.
- Safety: every save goes through `data/edit_actions.py`, which uses the same validators as the assistant (`data/validators.py`), parameterised SQL, adult-only checks, and writes a line to `logs/edits.log` (who, what, which row; no free text). Removing never erases: items become 'dropped'. Optional dates use a tick-box plus a picker.
- Changed: the assistant now imports its validators from `data/validators.py` (no behaviour change).

## 0.9.0
- Changed: **simpler dashboard, 12 tabs down to 5.** Home (alerts + what needs attention + everything coming up), Calendar, Family (people, life items, health, home, education, shopping, IDs, vehicles, warranties, festivals, emergency sheet), Money (bills, insurance, subscriptions, budget and loans, tax, home office, work; the statement-based views fill in once statements are filed and wait in a collapsed box until then) and Settings. Existing views moved, not rewritten.
- New: **act on things where you see them.** Each row in *Needs attention* has Done/Paid, Snooze (7 days) and Hide. *Paid* marks the bill paid, with an Undo. A longer *Handle an item* box offers 1/7/30-day snooze.
- New: **dismissible alerts.** Review-queue, stopped-task, backup and seasonal alerts each have Snooze 7d and (where safe) Ignore. A stale backup or stopped task can only be snoozed for up to 7 days, never ignored for good. Seasonal alerts are grouped into one line and keyed by year.
- New: **Settings tab:** add documents, AI/Drive/backup status, scheduled-task results, *Hidden alerts and items* with Restore, and a *Check for updates* button.
- Changed: the full list of upcoming items is under *Everything coming up* on Home. Nothing was removed from the database or the digests.

## 0.8.0
- New: **`python onboard.py add drive`**: guided Google Drive setup (Google Drive for Desktop, no OAuth or API). Finds your Drive folder, creates `FamilyAgent/Inbox` and `FamilyAgent/Brief`, runs a self-test, and schedules the sweep. The head of the family drops documents into Drive `Inbox` from a phone; the PC moves them into its own `inbox/`.
- New: **`inbox_sweep` task** (every 15 minutes, no AI): moves only settled document/photo/sheet files, with plain file names and a size limit. It skips half-synced files, lock files, online-only Google docs, executables and folders, never overwrites, and removes the Drive copy only after the PC copy is verified. Anything left behind is listed in the log. A stopped sweep shows up in the dashboard warnings and `doctor`.
- Changed: Drive `Brief` now gets only the **daily brief and the weekly digest** (PDF). The this-week snapshot is opt-in: `"drive": {"push": ["daily", "weekly", "this_week"]}` in `config/family.json`. Older files are archived locally as before.
- Changed: `add google` is now just the agent Gmail + Calendar connectors (needs Claude Code); Drive has its own `add drive`. `doctor` checks the Drive folder when one is set.

## 0.7.0
- New: **quick start.** The first `python onboard.py` offers a short, laptop-only setup (about 5 minutes): prerequisites, folders, family, database, AI choice, safety, backups schedule, first documents. No Gmail, Calendar or Drive needed. `python onboard.py easy` does the same any time.
- New: **add later:** `python onboard.py add google|backup|tax|family|packs|ai`. Google (agent Gmail, Calendar, Drive) is now optional; the family profile no longer asks for an email.
- New: **Add documents** box in the dashboard (Action tab): drop files into `inbox/` (type, size and name checks, never overwrites) and, with an API/CLI/Ollama provider, file them with one button. No Drive needed.
- Changed: `doctor` treats Google, a second backup location and Claude sign-in checks as optional unless the chosen AI needs them. The wizard shows a rough monthly cost next to each AI choice.
- Changed: Claude Code is no longer required in the prerequisites step; it is only needed for the `claude_*` options.

## 0.6.0
- New: **use the plan you already pay for.** Three text-only providers that run YOUR OWN signed-in vendor CLI: `claude_cli` (Claude Pro etc., Haiku by default), `codex_cli` (ChatGPT plan), `gemini_cli`. They power inbox filing (`data/ai_intake.py`) and the chat (`data/assistant.py`). The CLI runs with tools off or read-only, in an empty temp folder, without your FamilyAgent API keys; nothing about your login is read or copied.
- New: `ai.claude_model` (e.g. `haiku`) to save plan quota for the full Claude Code agents and scheduled runs. The wizard asks.
- New: scheduled inbox runs through a personal CLI login are OFF unless `ai.allow_unattended_cli` is true. An API key or Ollama is the better unattended choice.
- New: `python data/llm.py matrix` and the doctor show who pays, what works and the terms note for the chosen provider.
- Docs: COMPLIANCE.md updated for CLI sign-ins (Gemini free tier trains on prompts: not for family documents).

## 0.5.0
- New: **`python data/assistant.py`**: the `family` agent for families WITHOUT a Claude account. Works with an OpenAI, Gemini or Anthropic API key, or a local Ollama model. The model can only choose from a fixed list of actions with validated arguments (no free-form commands); changes ask for your "y" first (`--yes` to skip); questions use read-only SQL and the answer step cannot trigger actions.
- New: `AGENTS.md` and `GEMINI.md`: lets Cursor, Codex, Gemini CLI or similar tools, used interactively under the person's own account, follow the same rules and routing.
- Docs: what works without Claude (SETUP_NEW_FAMILY.md, COMPLIANCE.md).

## 0.4.1
- Fixed: `python onboard.py update` shows only the release notes newer than your version, and runs the NEW release's migration and health check straight after updating (the old process used to run its own old code).
- Fixed: a fresh unzip no longer reports a missing `logs/` folder; `upgrade` creates any missing standard folder.

## 0.4.0
- New: **encrypted backups** (`backup_encrypt`): database snapshots, archive and config are encrypted with a passphrase (scrypt + Fernet); file names are hidden; `data/restore_backup.py` restores or verifies. Fixed: backups no longer copy `family.db` in plain text under `data/`, no longer mirror `backups_pre_upgrade/`, and now include `config/` (never `secrets.env`).
- New: **per-person dashboard logins** (`python data/auth.py set NAME adult|limited`): salted-hash PINs, a limited screen for children and guests with no money data, slowed-down guessing. UI-level only (see data/auth.py).
- New: **provider-neutral AI** for the Python inbox pipeline (`data/llm.py`, `data/ai_intake.py`): Anthropic, OpenAI and Gemini via your own API key, or a local Ollama model; masks long digit runs before sending; validates every answer; low-confidence, scanned, unsupported and statement files go to a review queue (`inbox/needs_review/`, shown on the Action tab). Claude Code under your own login stays the default for the agents.
- New: **region-specific seasonal packs** (US cold/mild/hot, Canada, UK, Australia/NZ, India, generic; hurricane and wildfire add-ons): `python data/seasonal_packs.py list|apply`. Your own tasks and the done-log are never touched.
- New: `COMPLIANCE.md` (Anthropic account and credential rules, other providers, sharing rules), a daily cap on unattended AI runs, wizard consent text.
- Fixed: config edits are picked up immediately by a running dashboard.
- Action: run `python onboard.py update` (or `upgrade`). Optional: `pip install cryptography` for encrypted backups; re-run `python onboard.py` steps for AI provider, backups and logins.

## 0.3.1
- Fixed: `python onboard.py check|update` now works from a pushed tag when no formal GitHub Release exists, and explains a 404 (private repository) instead of "offline".
- New: private repositories work with a read-only token in the `FAMILYAGENT_TOKEN` (or `GH_TOKEN`) environment variable; the token is only sent to GitHub and never stored.

## 0.3.0
- New: scheduled jobs run through `tasks/run_task.py` with least-privilege Claude permissions; heartbeat banner on the dashboard.
- New: `python onboard.py doctor` pings Claude and flags env settings that cause `401 failed to authenticate API key`.
- New: members and birthdays, family-life items (school, medical, pets, legal, travel, gifts, chores), loans, budget vs actual.
- New: home-office tax prep (`data/home_office.py`), emergency sheet, family-meeting digest, done/snooze for action items.
- New: `family` agent as the front door; `ask_sql.py` read-only questions; demo data (`seed_demo.py`).
- New: `python onboard.py check|update|upgrade`, versioned migrations, optional dashboard PIN, Mac/Linux cron support.
- Changed: product and file names unified as FamilyAgent (database is now `data/family.db`).
- Action for families coming from a pre-release copy named iHome: rename `data/ihome.db` to `data/family.db` before running `python onboard.py upgrade`.
