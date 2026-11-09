"""Context help for the web app: the "?" panel on each page and the Help page (/help). Plain text, no AI, no network.

Each entry: title, purpose (one sentence), sections [(heading, [lines])] and links [(label, url)]. In a line,
[Name] is a button or link on the screen (shown as a key cap; tests check the name still exists in the templates) and
**text** is bold. Keys are the rail page keys (`active` in webapp/app.py), `records:<area>:<part>` and `finance:<part>`
(`key_for`).
"""

import re

HELP = {
    "home": {
        "title": "Today",
        "purpose": "What needs you today, what is on, and the money ahead, for the whole family or one person.",
        "sections": [
            ("Add something", [
                "Got a paper? Press [Add or scan] and drop the bill, statement, receipt or photo. It is read, filed "
                "and its due date lands here.",
                "Rather type it? Press [Chat] and write it the way you would say it, for example "
                "\"Sam's dentist is Oct 21 at 3pm\". You see what will be saved and press [Yes, save it].",
                "Birthdays, classes, IDs and other dates have their own forms in Family (links below).",
            ]),
            ("Done, paid, snooze", [
                "Press [Done] or [Paid] on a row under **Late**, **Today** or **This week**. A paid bill shows [Undo] for a moment.",
                "The **⋯** menu on a row: snooze it 1, 7 or 30 days, or hide it. Hidden items come back from Settings > Home Profile "
                "> Hidden from Today ([Restore]).",
            ]),
            ("Change or correct", [
                "**⋯** > [Open record] on a row, or find it in Family; the forms under it change it.",
            ]),
            ("Documents", [
                "Under **Documents**: [This week], [Weekly digest], [Family meeting] and [Emergency sheet] make a page you "
                "can read here, download or print.",
                "Under the emergency sheet: **Where things are** (the will, who can open the password manager, the safe, "
                "the backup drive ...; places and names only) is printed on the sheet ([Save where things are]). "
                "[Download the sealed copy] makes one file for someone you trust that opens in any browser with a "
                "passphrase you tell them separately.",
            ]),
            ("Tips", [
                "Tap a name above the card to see only that person's things.",
                "On a phone, tap or swipe the card for **On today** and **Money**.",
                "With the ZIP code set and **Look things up online** on (Family > House), the line under the title "
                "shows today's weather.",
            ]),
        ],
        "links": [("Family > People > Life items", "/records?domain=people&section=life"),
                  ("Add and Inbox", "/add")],
    },
    "family": {
        "title": "Family",
        "purpose": "One card per person (and one for the house and cars) with their next 30 days, a search over every "
                   "record and filed paper, and Needs a look (overdue items, IDs and car renewals running out, policies "
                   "ending, upkeep due). The chips at the top open People, Home, Cars, Papers & IDs and the Wallet.",
        "sections": [
            ("Add a person or a pet", [
                "Go to Family > People > People and use [Add a person or pet]: name, role, birthday.",
            ]),
            ("Change or correct", [
                "The pencil on a card opens that person's record: name, birthday, school, IDs. Fill in **Change it** "
                "and press [Save changes].",
                "A new name is used everywhere from then on; papers already filed keep the old spelling.",
            ]),
            ("See one person", [
                "Tap a card to list everything for that person. From there, open Today just for them.",
            ]),
            ("The house", [
                "The pencil on the House card opens Family > House: city, state and ZIP code (no street address). The "
                "state picks the state holidays on the calendar.",
                "**Look things up online** (off until you turn it on) lets the app list schools near home, check a "
                "college's name, find this year's school, college or work calendar and show the local weather. Only "
                "the ZIP code, the state, public names and the school year go out; never anyone's name.",
            ]),
            ("School, college or work", [
                "On a person's record, under **School, college or work calendar**: [Schools near home] lists the "
                "schools around your ZIP code ([Pick] fills one in); [Check name] catches a typo in a college's name.",
                "[Find this year's calendar] asks your AI to search the web for the official calendar; [Import] one it "
                "found, or use [Import from link] or [Import file]. The days off wait in the Inbox until you add them.",
            ]),
            ("Children's jobs", [
                "Family > Routines: the children's morning, after-school and evening jobs with stars, their goals and "
                "the allowance. They show on the Mitra Wall.",
            ]),
        ],
        "links": [("Family > People", "/records?domain=people&section=people"), ("Family > House", "/family/house"),
                  ("Family > Routines", "/family/routines")],
    },
    "calendar": {
        "title": "Calendar",
        "purpose": "Every due date, appointment, class, holiday and birthday from your records, by week, month or year.",
        "sections": [
            ("Add something", [
                "The calendar shows your records, so you add things where they belong:",
                "a weekly class or sport: Family > People > Classes and activities, [Add a weekly class or activity];",
                "a holiday or a day off school: Family > People > Holidays and dates;",
                "a family event at a time (dinner 8 to 8:30 PM, a party) or a yearly date: the same page, "
                "[Add a family event or a yearly date], or tell Chat \"family dinner today 8 to 8:30 pm\";",
                "a doctor, school or pet date: Family > People > Life items, [Add an item];",
                "a bill: drop it in the Inbox, or Money > Pay > Bills. Or just tell Chat.",
            ]),
            ("Change or correct", [
                "Change the record it comes from (Family, or Money for bills). The calendar updates by itself.",
                "A family event or yearly date added by mistake: Family > People > Holidays and dates, open its row, "
                "then [Save changes] to fix the date or time, or [Remove] to take it off.",
                "A doctor or other visit with a time: Family > People > Checkups and appointments, the Appointments list, open its row, then "
                "[Save changes] or [Remove].",
            ]),
            ("Moving around", [
                "[Week], [Month] and [Year] switch the view; the arrows and [Today] move through time.",
                "In the year view, tap a coloured day to open its week.",
            ]),
            ("Tips", [
                "The card on top counts what is on, who it is for and what not to miss.",
                "Your Google calendar, if connected, is shown below as a read-only copy; so are other calendars (iCloud, "
                "Outlook, school, work) added in Settings > Connections > Other calendars.",
                "If the app puts its dates on a Google calendar of its own and someone moves or deletes one there, the "
                "Inbox asks you: use the new date, keep ours, or take it off. Nothing changes until you answer.",
            ]),
        ],
        "links": [("Classes and activities", "/records?domain=people&section=classes"),
                  ("Holidays and dates", "/records?domain=people&section=dates"),
                  ("Life items", "/records?domain=people&section=life")],
    },
    "inbox": {
        "title": "Add",
        "purpose": "The way in for everything: drop or scan papers, type something in, and the Inbox of what needs a person.",
        "sections": [
            ("Type it in", [
                "The tiles under **Or type it in** open the form where that thing lives: a person or pet, a class, a "
                "date or reminder, a family event, a list item, a note, a subscription, a card for the wallet, or Chat.",
                "[Dates from a photo]: take a photo of a flyer, invitation or school letter. With photo reading on, the AI "
                "lists its dates; check each line (day, name, time, who, kind), untick what you do not want, then "
                "[Add the ticked dates]. Without the AI, type them next to the photo.",
                "[Recipe from a photo]: a recipe card or cookbook page fills in the recipe; check it, then [Save the recipe].",
            ]),
            ("Add files", [
                "Drag files anywhere onto this page, paste a picture, or press [Choose files or take a photo].",
                "Each file shows a bar while it is sent. Scans from the phone app arrive here too.",
            ]),
            ("Watch them being read", [
                "The panel under the drop box shows every file and its step: in line, checking, reading, sorting, filed.",
                "With an AI helper set up, reading starts on its own. Otherwise press [File them now]: common bank "
                "statements, CSV exports and phone bills are read without AI. Anything it cannot read waits under "
                "**Files to look at**.",
                "Each waiting file says why, and **Why?** shows every step that was tried. **Add the account ending ...** "
                "adds the account a statement names and reads it again; **Reprocess** reads a file again after you "
                "changed something (an AI connected, photo reading on, AI account topped up); **Reprocess all** does it for every "
                "file. **File it by hand** is different: you say what the file is and nothing is read from it.",
            ]),
            ("Work through what is left", [
                "Open items are grouped: Files to look at, Money, Renewals and documents, Family and household, "
                "Calendar. Tap a group name at the top, or press [Work through these], to see only that group.",
                "Each card asks one thing (a new subscription, a price rise, a missing birthday ...). Pick an answer "
                "and press [Save], or snooze it for later. After filing, [Open record] shows what was saved.",
            ]),
            ("Tips", [
                "An exact copy of a paper already filed is set aside, never filed twice.",
            ]),
        ],
        "links": [("Settings > Connections (AI helper)", "/settings?group=connections")],
    },
    "month": {
        "title": "This month",
        "purpose": "Where the money went this month (or any month), category by category.",
        "sections": [
            ("Fill it", [
                "Spending comes from your bank and card statements: drop them in the Inbox ([Add or scan]).",
                "Budget lines: Money > Keep > Budget and loans ([Set or remove a budget line]). Bills paid and what "
                "comes every month: Money > Bills and Money > Regular.",
            ]),
            ("Read the card", [
                "Tap or swipe through Overview, Cash flow, Where it went, Six months and Highlights.",
                "Pick another month with the month list or the arrows.",
                "Below the card, open a category to see every charge, biggest first or by date.",
            ]),
            ("Change or correct", [
                "Charges come straight from your statements and are not edited here. Bills and subscriptions are "
                "changed in Money > Pay.",
            ]),
        ],
        "links": [("Money > Budget", "/money?part=budget"), ("Money > Subscriptions", "/money?part=subs"),
                  ("Add and Inbox", "/add")],
    },
    "routines": {
        "title": "Routines",
        "purpose": "The children's jobs on the Mitra Wall: morning, after school and evening, with stars.",
        "sections": [
            ("Add", [
                "Under **Add a job** pick the child, when, the job, a picture and its stars (1 to 5), tick the days it "
                "is on (none = every day), then [Add the job].",
                "On the wall a child taps the job when it is done; tapping again takes it back. Each job counts once a day.",
                "A child who signs in with their own PIN also sees **My jobs today** on their page and ticks them there "
                "(only their own jobs, with their stars but never an amount).",
            ]),
            ("Rewards", [
                "Under **Rewards**: what a child can spend stars on, for one child or any child, then [Add the reward].",
                "A child asks on the wall's Chores screen or their own page; Today tells you, and you answer under "
                "**Asked for**: [Give it] spends the stars, [Not now] gives them back.",
                "Stars to spend = every star earned, minus rewards asked for or given. The allowance does not use them up.",
            ]),
            ("Change", [
                "[Remove] takes a job off the wall; the stars it already earned stay in the week.",
                "**What a star is worth**: cents per star, then [Save the rate]. 0 = stars only.",
            ]),
            ("Tips", [
                "Stars count Monday to Sunday. The week's allowance shows on the wall's Money screen, which opens only "
                "with an adult's PIN; nothing is paid automatically.",
                "Pair the wall itself in Settings > Phones > Mitra Wall.",
            ]),
        ],
        "links": [("Settings > Phones and walls", "/settings?group=phones"), ("Family", "/family")],
    },
    "wall": {
        "title": "Mitra Wall",
        "purpose": "An old tablet or iPad on the wall that shows the family's week, today's plan, the children's jobs, "
                   "the lists and the meals.",
        "sections": [
            ("Set it up", [
                "On this PC: Settings > Phones > Mitra Wall, name it, [Show the wall code], then scan the code with the "
                "tablet's camera. docs/MITRA_WALL.md has the steps to keep it on the wall (Guided Access, screen pinning).",
            ]),
            ("What it shows", [
                "**Today**: what is on, what needs doing (the same to-dos as Today on the PC, late ones marked), the "
                "children's jobs, dinner and **Coming up** (the next three days).",
                "**Week** and **Month** at the top switch the calendar; tap a person to see only their day. Tap anything "
                "to see it in full: the whole title, the day and time and who it is for.",
                "**Chores**, **Lists** and **Meals**: children tick their jobs, anyone ticks or adds to the family lists.",
                "After two minutes untouched it rests on a clock and the family's photos (Settings > Phones > Mitra "
                "Wall > Wall screen).",
            ]),
            ("Money stays off it", [
                "Bills show as due or late, never with an amount. **Money** opens only with an adult's own PIN and locks "
                "itself after a minute.",
            ]),
            ("Tips", [
                "With the ZIP code and **Look things up online** on (Family > House) it shows the local weather; the PC "
                "fetches it, the tablet never goes online.",
                "Adults-only lists, critical info and papers never show on the wall.",
            ]),
        ],
        "links": [("Settings > Phones and walls", "/settings?group=phones"), ("Family > Routines", "/family/routines")],
    },
    "wallet": {
        "title": "Wallet",
        "purpose": "Your cards in one place: IDs, cars and plates, insurance, memberships and home facts.",
        "sections": [
            ("Add", [
                "IDs and insurance come from filed papers and Family; cars from Family > Cars.",
                "Open [Add a card] for a membership, store, library, travel or health card, or home facts (Wi-Fi name, "
                "trash day, filter size), then [Save card].",
                "On a car, [Plate and colour] keeps the whole plate, its state, colour and body type; then [Save].",
                "**Add a card from a photo**: take or pick a photo of the card. When photo reading is on (Settings > "
                "Connections > AI helper) the AI fills in the card (only the last four of a number); check every field, "
                "then [Save card], or [Discard the photo]. The photo is filed with the card and shown on its back.",
            ]),
            ("Change", [
                "Under a card you added: [Change] to correct it, or tick the box and [Remove].",
                "IDs, cars and policies change in Family: tap the card, then **Open record**.",
            ]),
            ("Find", [
                "Tap a card to see where its number is printed on the real one, and your own scan of it when one is "
                "filed. The chips at the top show one group; "
                "a card running out within 60 days says how many days are left.",
                "Type in the search box (plate, wifi, library, a name) and [Find]: every word must be on the card.",
                "[Parking] shows the plate as big as the screen allows for a meter or toll booth, with [Copy the plate]; "
                "the screen stays on. Installed as an app, press and hold its icon for the Plate shortcut.",
                "A card you added with an expiry date is reminded 30 days before on Today and in the weekly digest "
                "(Settings > Household profile > How early to remind changes it).",
            ]),
            ("Tips", [
                "These are reference copies, not official IDs. Whole numbers are kept only for the plate and for "
                "membership, store and library cards (for the barcode); everything else keeps the last 4.",
                "Paired phones with the ID documents permission carry the wallet too.",
            ]),
        ],
        "links": [("Family > Cars", "/records?domain=vehicles&section=vehicles"),
                  ("Family > Papers > IDs", "/records?domain=papers&section=ids")],
    },
    "notes": {
        "title": "Notes",
        "purpose": "Links, notes, places and deals you want to find again.",
        "sections": [
            ("Add", [
                "Open [Save a link, note, place or deal], type a title (and the link if there is one), pick who sees "
                "it, then [Save].",
                "A deal with an end date also shows up on Today before it ends.",
            ]),
            ("Change", [
                "Pinned items sit on top as coloured cards with their buttons; on any other row tap **...** to see them.",
                "[Pin] keeps a note on top; [Unpin] lets it go back in line.",
                "[Tags] changes its tags ([Save tags]); [Archive] puts it away.",
            ]),
            ("Find", [
                "Type in **Search**, or tap a kind in the row under it (Places, Deals ...). **More filters** has the "
                "tag, who added it and **Show archived and ended deals**. A deal ending within two weeks shows how many "
                "days are left.",
            ]),
            ("Tips", [
                "Links are never opened by the app; they open in a new tab only when you click them.",
            ]),
        ],
        "links": [],
    },
    "chat": {
        "title": "Chat",
        "purpose": "Ask about your records, or tell it something to save, in plain words.",
        "sections": [
            ("Ask", [
                "\"When does the car insurance renew?\", \"What did we spend on groceries last month?\". Each answer "
                "says which records it used.",
            ]),
            ("Add or change", [
                "Type it the way you would say it: \"Sam's dentist is Oct 21 at 3pm\". Nothing is saved until you "
                "press [Yes, save it] on the card that shows exactly what will change.",
            ]),
            ("Tips", [
                "Typed requests need an AI helper (Settings > Connections). [Clear this chat] starts over.",
                "Answers are records, not professional advice.",
            ]),
        ],
        "links": [("Settings > Connections", "/settings?group=connections")],
    },
    "work": {
        "title": "Work",
        "purpose": "The jobs and businesses of the adults in the family: timesheets, the on / off-site schedule, pay days "
                   "and the work calendar. No pay amounts or invoices: money comes from the bank lines.",
        "sections": [
            ("Add", [
                "[Add job] at the top: the name, the kind (employment, contract, own business, rental, side business), who, primary or secondary and whether it needs timesheets.",
                "Hours come from a timesheet you import, or are typed per day under **Timesheets**.",
            ]),
            ("Change", [
                "Pick the job's part in the row of chips: Timesheets, Schedule, Details, Work calendar.",
                "Details: kind, primary or secondary, who can see it, the timesheet cycle and the work calendar name; then [Save profile].",
            ]),
            ("Tips", [
                "Days on the schedule with no hours, and hours on a holiday, show in red above the weeks.",
                "Off-site days feed the home-office figures in Money; whether a deduction applies is for your tax "
                "preparer.",
            ]),
        ],
        "links": [("Family", "/family"), ("Money > Home office", "/money?part=home_office")],
    },
    "settings": {
        "title": "Settings",
        "purpose": "Your household, the agent, connections, phones and your data.",
        "sections": [
            ("Find your way", [
                "Settings opens on a summary: how complete the profile is ([Ask me the next question] puts it in the Inbox), one card "
                "per group with how it stands, and **Needs a look** for health warnings. Open a group, then switch "
                "groups in the row at the top; tap a card's heading to open it.",
            ]),
            ("Household profile", [
                "How complete your profile is, Simple or Advanced view, names as printed on papers, traditions and "
                "holidays, optional features, tax papers and how early to remind.",
            ]),
            ("Home Profile", [
                "The agent's name and tone, when the daily brief and weekly digest arrive, and what they watch; "
                "sign-in PINs ([Save PIN]); items hidden from Today ([Restore]).",
            ]),
            ("Connections", [
                "An AI helper, Google Calendar and Gmail, and the phone bot. Keys can be typed only on this PC.",
                "**Mail folder**: a mailbox made only for this app (any provider) that you forward papers to; type its "
                "address and an app password on this PC, then [Save]. It is read with every inbox check, read-only "
                "(docs/MAIL_FOLDER.md).",
                "**Other calendars**: paste an iCloud, Outlook or other calendar's subscribe address (.ics or webcal://) "
                "and [Add the calendar]; it shows on the Calendar page, read-only, read about once an hour.",
                "**Bank sync (SimpleFIN)** (optional) pulls balances and new transactions every morning. Paste the setup "
                "token on this PC, tick the accounts (**Select all** / **Unselect all**), save, then **Pull now**.",
            ]),
            ("Phones", [
                "Pair a phone with the app's QR code ([Show the pairing code]); remove a lost phone.",
                "**Mitra Wall**: an old tablet or iPad on the wall. Name it, [Show the wall code], then scan the code with "
                "the tablet's camera (or open the address on it and type the code within 15 minutes). Remove a wall "
                "to sign it out.",
                "**Wall screen**: after two minutes untouched the wall shows a big clock (digital, traditional, modular = "
                "the time with the weather, what is next, the children's jobs and dinner, or Roman = hands with serif "
                "numerals) and in the day the family's photos in turn; at night a dark clock, or with **Night clock** red "
                "or amber a bedroom clock (black, only the time and the date). Pick the clock, the night clock, the photo "
                "and night hours and how long each shows, then [Save the wall screen].",
                "[Add photos] (several at once, iPhone photos too): each is made again on this PC, upright and without "
                "its location or camera details. They stay on this PC; only a paired wall shows them.",
                "Away from home: with Tailscale on the PC and the phone, Settings > Phones shows an **Away from home** "
                "address to open in the phone's browser (docs/REMOTE_ACCESS.md). The PC is never open to the internet.",
                "A phone that stops connecting after the PC renews its own certificate (about once a year): pair it "
                "again here. Phone app 0.14 and later stay paired.",
            ]),
            ("Data", [
                "Back up, restore, export, updates, the health check, and **Runs on its own** (the daily brief, weekly "
                "digest and backup on a schedule).",
                "**Data check** reads the records every week for charges entered twice, bills still open long after "
                "their due date, phone bills that do not add up and papers missing on disk; [Check now] runs it at once. "
                "The safe fix (a missing category one of your rules knows) happens by itself and can be "
                "undone there; charges or bills entered twice and bills still open wait in the Inbox to accept or leave. "
                "With an AI helper set up, [Explain with AI] puts the findings in plain words.",
            ]),
        ],
        "links": [("Household profile", "/settings?group=household"), ("Data", "/settings?group=data")],
    },
}


FIND = ("Pick the months with **From** and **To**, narrow it with **Category**, or type in the search box "
        "(any words, any order)")
OPEN = ("Tap a row (on a PC, the first column) to open it on a page of its own: its details, the paper it came from, the "
        "form to change it and its history. The link at the top goes back to the list.")
LOOK = "This part is for looking up. To add or change something here, tell Chat."


def _e(title, purpose, add=None, change=None, more=None, links=None):
    sections = []
    if add:
        sections.append(("Add", add))
    if change:
        sections.append(("Change or correct", change))
    for h, lines in (more or []):
        sections.append((h, lines))
    return {"title": title, "purpose": purpose, "sections": sections, "links": links or []}


PARTS = {
    "records": _e("Family records", "Everything the app knows, by area: People, Home, Cars, Papers & IDs.",
                  add=["Pick an area in the chips under **Family** (People, Home, Cars, Papers & IDs, Wallet), then a "
                       "part in the row below; parts you can add to have a form at the top (for example [Add a person or "
                       "pet]). Or drop the paper in the Inbox, or tell Chat."],
                  change=[OPEN],
                  more=[("Find", ["Type in the search box at the top: it looks through every record and every filed paper."])]),
    # People
    "records:people:people": _e("People", "Everyone in the household, pets included.",
                                add=["[Add a person or pet]: name, role (adult, child, pet) and birthday."],
                                change=[OPEN, "Fill in **Change it** and press [Save changes]. A new name is used everywhere "
                                        "from then on; papers already filed keep the old spelling."],
                                more=[("School, college or work", [
                                    "Under **School, college or work calendar** on a person: [Schools near home], "
                                    "[Check name] for a college, then [Find this year's calendar], [Import from link] or "
                                    "[Import file]. Needs **Look things up online** on (Family > House) for the look-ups."])]),
    "records:people:life": _e("Life items", "School forms, doctor and dentist visits, vaccines, pet care, chores, gifts and "
                              "other dated things for a person.",
                              add=["[Add an item]: what, for whom, the date, and how often it repeats."],
                              change=[OPEN, "**Change it** > [Save changes]. [Mark done] moves a repeating item to its next "
                                      "date and closes a one-off. [Remove] takes it off the lists but keeps its history."]),
    "records:people:health": _e("Checkups and appointments", "Regular checkups (dentist, eye test ...) and booked appointments.",
                                add=["A booked appointment: Family > People > Life items, [Add an item], or tell Chat."],
                                change=[OPEN, "After a checkup press [Mark done]; the next one is set from its interval."]),
    "records:people:school": _e("School", "School items: forms, trips, fees and events, per child.",
                                add=["[Add an item] in Life items, or drop the school letter in the Inbox."],
                                change=[OPEN],
                                links=[("Life items", "/records?domain=people&section=life")]),
    "records:people:classes": _e("Classes and activities", "Lessons, sports and clubs that repeat every week.",
                                 add=["[Add a weekly class or activity]: what, for whom, the days, the time, and when the "
                                      "term starts and ends."],
                                 change=[OPEN, "**Change it** > [Save changes]. [Skip that day] for one missed session; "
                                         "[End it] when the term or the activity is over."],
                                 more=[("Where it shows", ["Calendar, Today and the child's own page."])]),
    "records:people:dates": _e("Holidays and dates", "Public holidays, festivals, school closures and early dismissals.",
                               add=["[Add a holiday, festival or day off school]. School calendars dropped in the Inbox "
                                    "and your traditions also suggest dates; you accept them in the Inbox.",
                                    "A school, college or work calendar can be found and imported on the person's record "
                                    "(School, college or work calendar). State holidays follow the state set on Family > House."],
                               change=[OPEN, "[Remove] a date that is wrong."]),
    "records:people:profiles": _e("Critical info", "Facts you may need fast: emergency contacts, allergies, doctors, school contacts.",
                                  add=["[Add a fact (contact, allergy, doctor, school)]. It stays on this PC; it never goes "
                                       "to an AI, a phone or Chat."],
                                  change=[OPEN, "**Change it** > [Save changes]; [Still correct] when you have checked it; "
                                          "[Remove] when it no longer applies."],
                                  more=[("Tips", ["Facts not checked for a while come back in the Inbox to confirm."])]),
    # Home
    "records:home:lists": _e("Lists", "Shopping, to-do and packing lists everyone can tick off.",
                             add=["[Start a list], then open it and use [Add to the list]."],
                             change=[OPEN, "Tick items with **✓** (and untick with **↺**); [Clear ticked items] tidies up; "
                                     "[Archive the list] when you are done with it.",
                                     "[Share the list] sends what is still open to a message, an email or a note (on a PC "
                                     "it is copied, ready to paste); [Print the list] prints just the list."]),
    "records:home:meals": _e("Meals", "Recipes and the week's meal plan.",
                             add=["[Save a recipe] with its ingredients; [Plan a meal] for a day; "
                                  "[Put the planned meals on a shopping list].",
                                  "Under Save a recipe, [Fill it in] reads a recipe page you paste the address of (most "
                                  "recipe sites carry the recipe data; no AI). Needs Look things up online on (Family > "
                                  "House). Check it, then Add."],
                             change=[OPEN, "[Take it off the plan] for a planned meal; [Archive this recipe] for one you "
                                     "no longer make."]),
    "records:home:upkeep": _e("Upkeep", "Home and car jobs that come back: filters, gutters, smoke alarms, seasonal tasks.",
                              add=["They come from your region's seasonal list and your home; to add your own, tell Chat."],
                              change=[OPEN, "[Mark done] when a job is done; [Season is over] skips the rest of a "
                                      "seasonal job this year."]),
    "records:home:contacts": _e("Service contacts", "The plumber, electrician, furnace company and others you call.",
                                add=["[Add a plumber, furnace company, garage ...]: name, trade, phone, notes, rating."],
                                change=[OPEN, "**Change it** > [Save changes]; [Used them today] records the last job; "
                                        "[Remove] when you stop using them."],
                                more=[("Tips", ["They are printed on the emergency sheet unless you said you would not use them again."])]),
    "records:home:inventory": _e("Inventory", "Things you own: where they are, what they cost, warranty, receipt and manual.",
                                 add=["[Add a thing to the inventory]."],
                                 change=[OPEN, "**Change it** > [Save changes]; [Receipt and manual] links filed papers; "
                                         "[Sold, thrown out or lost] takes it off the inventory but keeps its history."]),
    "records:home:shopping": _e("Shopping", "Planned purchases with target dates and prices.",
                                change=[OPEN, LOOK]),
    # Vehicles
    "records:vehicles:vehicles": _e("Vehicles", "Your cars: registration, inspection, insurance and services.",
                                    add=["[Add a vehicle]: make, model, year, and the registration and inspection dates."],
                                    change=[OPEN, "Under **Log a service**, pick the service, the date and the odometer, then "
                                            "[Save]; the next due date follows from it."]),
    # Papers
    "records:papers:papers": _e("Papers", "Every filed document, by year and type.",
                                add=["Drop papers in the Inbox ([Add or scan]); they are renamed, sorted and filed here."],
                                change=[OPEN, "A wrong date or type: tell Chat."]),
    "records:papers:ids": _e("Expiries and IDs", "Passports, licences and other IDs, and everything else that expires.",
                             add=["[Add an ID document]: kind, whose, expiry date, and only the last four characters of "
                                  "the number."],
                             change=[OPEN, "Renewed? Under **Renewed? New expiry** type the new date and press [Save]."]),
    "records:papers:policies": _e("Insurance", "Your policies, what they cover, and when they renew.",
                                  add=["Drop the declarations page in the Inbox; the policy, its cars, drivers and "
                                       "coverages are read from it."],
                                  change=[OPEN, LOOK]),
    # Finance
    "finance": _e("Money", "Overview shows this month (in, spent, saved, left) and anything that needs a look. "
                  "Spending, Bills and Regular are the quick outlook: spending by category against last month and a "
                  "year ago, bills paid this month against last, and what keeps coming every month. In the Advanced "
                  "view three lanes follow: Pay (bill list, receipts, subscriptions), Keep (accounts, budget, loans) "
                  "and Look back (the Ledger, trends, statements, taxes); inside a lane a second row switches between "
                  "its parts. In the Standard view they are folded under All money pages.",
                  add=["Statements, bills and receipts go in the Inbox ([Add or scan]). Parts with a form have it at "
                       "the top (subscriptions, receipts, budget, loans, accounts)."],
                  change=["Where rows open: " + OPEN[:1].lower() + OPEN[1:]]),
    "finance:bills": _e("Bills", "Bills due this month (or the months you pick), paid or not.",
                        add=["Drop the bill in the Inbox, or tell Chat. Steady charges in your statements also become "
                             "suggested bills in the Inbox."],
                        change=[OPEN, "[Mark paid] or [Mark as not paid]. A yearly bill rolls on to next year when paid."],
                        more=[("Find", [FIND + ": name, vendor or category."])]),
    "finance:receipts": _e("Receipts", "Receipts matched to card charges.",
                           add=["Drop a receipt photo in the Inbox, or [Add a receipt by hand]: store, date, total."],
                           change=[OPEN, "[Link] it to one of the suggested charges, or [No charge expected] for a cash "
                                   "receipt."]),
    "finance:mobile": _e("Phone bills", "Each phone line's share of the bill, per person.",
                         add=["Drop the phone bill PDF in the Inbox; Verizon bills are read without AI."],
                         change=[LOOK]),
    "finance:subs": _e("Subscriptions", "What you pay for every month or year, and when it charges next.",
                       add=["[Add a subscription], or confirm the ones found in your statements in the Inbox."],
                       change=[OPEN, "Pick keep or cancel and press [Save decision]; [Stop tracking it] for one that "
                               "ended. Nothing is ever cancelled for you."]),
    "finance:paypal": _e("PayPal", "Every payment from your PayPal statements, month by month, and the card or bank "
                         "charge each one belongs to.",
                         add=["Drop the PayPal statement PDF in the Inbox; it is read without AI."],
                         change=[OPEN, "A payment still waiting usually means that card's statement is not filed yet."]),
    "finance:amazon": _e("Amazon orders", "Amazon orders matched to their card charges.",
                         change=[LOOK]),
    "finance:spending": _e("Spending", "Money spent by category: this month so far, last month and the same month a "
                           "year ago, counted as in the Ledger.",
                           add=["Drop bank and card statements in the Inbox."],
                           change=[LOOK, "A charge in the wrong category: fix it in the Ledger."]),
    "finance:paid": _e("Bills", "Bills paid this month next to last month, per payee: paid, still to come, or new.",
                       add=["Drop the statements in the Inbox; a bill on the bill list shows under **Open on the bill list**."],
                       change=[LOOK, "Mark a bill paid on the bill list (Money > Pay > Bills)."]),
    "finance:regular": _e("Regular", "What comes every month: home and utilities, loans and insurance, subscriptions, "
                          "with the total a month and a year.",
                          add=["Found in the statements (paid in two of the last four months), your subscriptions and "
                               "the bill list."],
                          change=[LOOK, "Change or cancel a subscription in Money > Pay > Subscriptions."]),
    "finance:ledger": _e("Ledger", "Every transaction from every account in one list, with the money flow worked out above it.",
                         add=["Drop the statements in the Inbox. For a checking account, drop the latest statement or activity "
                              "download; the page tells you which accounts are behind."],
                         change=["Pick a period (the dates fill in) or type your own dates, narrow by account, category, "
                                 "type, amount or a word, then press [Show].",
                                 "One card: pick it under Account; **By card member** splits its spending per person. "
                                 "Category **Uncategorized** lists the card shops with no category: name one and press "
                                 "[Remember], and every charge from it is sorted from then on.",
                                 "A line in the wrong category: open it, pick the category (and the type), then [Save]. Tick "
                                 "**Do the same for every line like this one** and the same shop is sorted that way from then on.",
                                 "The lines themselves come from your statements and are not edited here."],
                         more=[("The tiles",
                                ["**Income**: pay and interest. **Spending**: everything bought, billed or charged, with refunds taken off. "
                                 "**Left over**: income less spending (and tax).",
                                 "**Bills paid** is the part of spending that is utilities, insurance, loans, phone and internet. "
                                 "**Invested** is money set aside, such as a 529 or a brokerage deposit.",
                                 "**Between your accounts**: money you moved from one of your accounts to another. **Card payments**: "
                                 "money paid onto your cards. Neither is income or spending, so they never inflate those tiles, "
                                 "except in a month with no card statement: then a card payment stands for that card's "
                                 "spending, and a note says so.",
                                 "A transfer or card payment is **matched** when the same amount goes out of one account and into another "
                                 "within three days. Each payment is counted once."]),
                               ("The yellow notes",
                                ["**Not up to date** names the accounts whose newest line is older than the dates you picked. Their "
                                 "spending, pay and transfers are missing until you add the latest statement. A salary account that is "
                                 "behind is why Income can show nothing.",
                                 "**Other side not loaded**: a transfer or card payment whose other end is not in the list yet, or is an "
                                 "account you do not track. It matches by itself once that statement is added."]),
                               ("Check the totals",
                                ["Open **How the tiles add up** to see every line grouped, with the totals in and out. Pick a kind of "
                                 "line under it (Spending, Transfers, Card payments, Investing...) to list just those."])]),
    "finance:watch": _e("Missing statements", "Which accounts have statements, and which are missing.",
                        add=["Drop the missing statements in the Inbox."], change=[LOOK]),
    "finance:spikes": _e("Price rises", "Bills and subscriptions that went up.", change=[LOOK]),
    "finance:accounts": _e("Accounts", "Bank, card and loan accounts (last four digits only).",
                           add=["[Add an account]; filed statements add their account by themselves."],
                           change=[OPEN],
                           more=[("Tips", ["The tiles split **Cash** (checking and savings) from **Investments** "
                                           "(investment accounts: brokerage, T-bills, I bonds, CDs held there), then "
                                           "what cards and loans owe and the net position.",
                                           "**Net worth by month**: the same sum at the end of each month from the "
                                           "statement balances on file, with the change from the month before. Loans "
                                           "kept only on Budget and loans are not in it."])]),
    "finance:deposits": _e("Deposit sources", "Where the money coming in comes from, by month.",
                           change=[LOOK, "**Where deposits come from**: pick what a source is (pay, interest, money back "
                                   "from investments, own money moved, a refund) and press [Remember]. Only pay and "
                                   "interest count as income on Overview, in Trends and in the Ledger.",
                                   "The deposits themselves are lines of the Ledger: **See the pay in the Ledger**."]),
    "finance:budget": _e("Budget and loans", "Monthly limits per category, and your loans.",
                         add=["[Set or remove a budget line]: pick a category and a monthly limit (0 removes it). "
                              "[Add a loan]: lender, balance, rate, payment.",
                              "[Add a savings goal]: what it is for, how much, by when, and what is saved so far, or an "
                              "account kept for it (then its latest statement balance counts). **Savings goals** shows "
                              "how far each one is and what it takes a month to get there."],
                         change=[OPEN, "A loan: **Update it** > [Save]; [Mark paid off] when it is cleared."],
                         more=[("Tips", ["The bars show how each budget line is going this month.",
                                         "**Paying loans off sooner** (folded): for each loan with a balance, rate and "
                                         "payment, what 50, 100 or 250 more a month does to the payoff date and the "
                                         "interest. Arithmetic on what is on file, not advice."])]),
    "finance:benefits": _e("Card benefits", "Credits and perks your cards give, and whether you used them.", change=[LOOK]),
    "finance:trends": _e("Trends", "Income, spending and what was left, month by month, against last year.",
                         change=[LOOK, "Pick 6, 12 or 24 months at the top."]),
    "finance:tax": _e("Tax papers", "Which tax documents you have for the year and which are still missing.",
                      add=["Drop tax papers in the Inbox."], change=[LOOK],
                      more=[("For your tax preparer", ["[Download the pack for your tax preparer (.zip)]: this checklist, "
                                                       "the year-end summary, the home-office figures and copies of the "
                                                       "year's filed tax papers, in one file to send or put on a USB stick."])]),
    "finance:home_office": _e("Home office", "Home office figures for the tax year.", change=[LOOK]),
    "finance:year_end": _e("Year-end", "A summary of the year, with a download.", change=[LOOK]),
}
HELP.update(PARTS)


def key_for(active, ctx):
    """The help entry for a page: a Records or Finance part when one is open, else the page itself."""
    if active == "records" and ctx.get("dom") and ctx.get("sec"):
        k = f"records:{ctx['dom']}:{ctx['sec']}"
        return k if k in HELP else "records"
    if active == "money":  # Money: This month, a Finance part, or the overview
        if ctx.get("part") == "month":
            return "month"
        k = f"finance:{ctx.get('part')}"
        return k if k in HELP else "finance"
    return active if active in HELP else ""


GROUPS = [("pages", "Pages"), ("records", "Family records"), ("finance", "Money")]


def group_of(key):
    return "records" if key.startswith("records") else "finance" if key.startswith("finance") else "pages"


def get(key):
    return HELP.get(key)


def labels(entry):
    """The [Name]s an entry mentions (button and link names on screen)."""
    out = []
    for _heading, lines in entry["sections"]:
        for line in lines:
            out += re.findall(r"\[([^\]]+)\]", line)
    return out


def search(q):
    """Entries whose text has every word of `q` (case-insensitive), in rail order."""
    words = [w for w in (q or "").lower().split() if w]
    out = []
    for key, e in HELP.items():
        text = " ".join([e["title"], e["purpose"]] + [h + " " + " ".join(ls) for h, ls in e["sections"]]).lower()
        if all(w in text for w in words):
            out.append(key)
    return out


# ---- Chat: "How do I ...?" answered from the entries above (no AI) -----------------------------------------------
_HOWTO = re.compile(r"^\s*(how\s+(do|can|should|would)\s+(i|we|you)|how\s+to|where\s+(do|can|is|are)\s+(i|we)?|"
                    r"can\s+(i|we)|help(\s+me)?(\s+with)?|i\s+(want|need)\s+to|what\s+is\s+the\s+way\s+to)\b", re.I)
_STOP = set("a an the my our your his her their i we you me us it its this that these those to of for in on at by with "
            "and or do does did can could should would how where what which when is are be get put make some any one "
            "please thing things there here up from into about app mitra home".split())
# Words for the job, not the topic: they help rank but cannot pick an entry by themselves.
_VERBS = set("add new change edit correct fix update delete remove mark done paid snooze hide undo see find look "
             "set enter type save keep log track open move rename show item stuff detail info".split())
# Everyday words -> the entry that covers them (one key per word; checked by tests/test_help.py).
SYNONYMS = {
    "birthday": "records:people:life", "anniversary": "records:people:life", "kid": "records:people:people",
    "child": "records:people:people", "pet": "records:people:people", "person": "records:people:people",
    "member": "records:people:people", "dentist": "records:people:health", "doctor": "records:people:health",
    "appointment": "records:people:health", "checkup": "records:people:health", "class": "records:people:classes",
    "lesson": "records:people:classes", "activity": "records:people:classes", "holiday": "records:people:dates",
    "allergy": "records:people:profiles", "medicine": "records:people:profiles", "grocery": "records:home:shopping",
    "chore": "records:home:upkeep", "repair": "records:home:upkeep", "plumber": "records:home:contacts",
    "car": "records:vehicles:vehicles", "oil": "records:vehicles:vehicles", "passport": "records:papers:ids",
    "license": "records:papers:ids", "licence": "records:papers:ids", "policy": "records:papers:policies", "insurance": "records:papers:policies",
    "bill": "finance:bills", "pay": "finance:bills", "receipt": "finance:receipts", "subscription": "finance:subs",
    "statement": "inbox", "upload": "inbox", "scan": "inbox", "paper": "inbox", "budget": "finance:budget",
    "loan": "finance:budget", "goal": "finance:budget", "saving": "finance:budget", "account": "finance:accounts", "spending": "finance:trends", "tax": "finance:tax",
    "note": "notes", "pin": "settings", "sign": "settings", "password": "settings", "ai": "settings", "backup": "settings",
    "phone": "settings", "away": "settings", "remote": "settings", "tailscale": "settings", "theme": "settings", "dark": "settings", "todo": "home", "reminder": "home",
    "icloud": "settings", "email": "settings", "mail": "settings", "forward": "settings", "outlook": "settings", "charge": "finance:ledger", "transaction": "finance:ledger", "category": "finance:ledger", "ledger": "finance:ledger",
    "duplicate": "settings", "overdue": "home", "late": "home", "snooze": "home", "wallet": "wallet", "plate": "wallet", "emergency": "home",
    "wall": "wall", "tablet": "wall", "ipad": "wall", "clock": "wall", "routine": "routines",
    "star": "routines", "allowance": "routines", "reward": "routines", "weather": "family", "zip": "family",
    "college": "records:people:people",
}


def is_howto(text):
    """True for "how do I ...", "where can I ...", "help with ..." style questions."""
    return bool(_HOWTO.match(text or ""))


def _stem(w):
    if w.endswith("ss"):
        return w
    for end in ("ies", "es", "s"):
        if w.endswith(end) and len(w) - len(end) >= 3:
            return w[: -len(end)] + ("y" if end == "ies" else "")
    return w


_PHRASES = [(r"\bto[\s-]?do\b", "todo"), (r"\bback\s+up\b", "backup"), (r"\bsign\s+in\b", "sign")]


def _words(text):
    text = (text or "").lower()
    for pat, rep in _PHRASES:
        text = re.sub(pat, rep, text)
    return [_stem(w) for w in re.findall(r"[a-z]+", text) if w not in _STOP]


def _text_of(e):
    return " ".join([e["purpose"]] + [h + " " + " ".join(ls) for h, ls in e["sections"]])


def howto(text, n=3):
    """Help entry keys that answer a question, best first ([] when nothing fits). Only a topic word picks an entry:
    a title or synonym hit counts most, a word in the text less, and job words (add, change ...) only rank."""
    words = _words(_HOWTO.sub("", text or "", count=1))
    topic = [w for w in words if w not in _VERBS]
    if not topic:
        return []
    scores = {}
    for key, e in HELP.items():
        title = set(_words(e["title"]))
        body = set(_words(_text_of(e)))
        s = 0
        for w in topic:
            s += 6 if w in title else 0
            s += 5 if SYNONYMS.get(w) == key else 0
            s += 1 if w in body else 0
        if s >= 3:
            s += sum(1 for w in words if w in _VERBS and w in body)
            scores[key] = s
    return sorted(scores, key=lambda k: (-scores[k], list(HELP).index(k)))[:n]


def as_chat(key):
    """One entry as Chat markdown: [Name] becomes bold, sections become short lists."""
    e = HELP[key]
    out = [f"**{e['title']}**: {e['purpose']}"]
    for heading, lines in e["sections"]:
        out.append(f"**{heading}**")
        out += ["- " + re.sub(r"\[([^\]]+)\]", r"**\1**", line) for line in lines]
    return out


# ---- the assistant: what the AI knows about the app itself ---------------------------------------------------------
# Short facts about the pages, the statuses and where each kind of fix lives. The AI sees these in every planning
# prompt, so an app question gets an answer that names the real page and button. Button names here must exist on a
# screen (tests/test_chat_help.py checks them against the templates, like the entries above).
GLOSSARY = [
    "Today (the first tab): everything that needs a person now, as Late / Today / This week / Later; [Done], [Paid], snooze "
    "or hide from the row's ⋯ menu; hidden rows come back from Settings > Home Profile > Hidden from Today.",
    "Family tab: one card per person plus the house and cars; chips open People, Home, Cars, Papers & IDs, Wallet; the "
    "search box finds any record or filed paper; Needs a look = overdue items, IDs and renewals running out, policies ending.",
    "Records (inside Family): every stored row by area; a row opens on its own page with its details, the paper it came "
    "from and its history; the forms under it change or remove it (Change it > Save changes).",
    "Add tab (the Inbox): drop or scan a bill, statement, receipt, policy or photo and it is read and filed; the Inbox "
    "lists files waiting and questions to decide; Why? on a waiting file shows what was tried.",
    "Money tab: Overview, Spending, Bills (paid this month against last), Regular (what comes every month); in the "
    "Advanced view also Pay (bill list, receipts, subscriptions), Keep (accounts, budget, loans) and Look back (ledger, "
    "deposit sources, trends, missing statements, price rises, tax, year-end).",
    "Calendar: every due date, appointment, class, holiday and birthday from the records, read-only; add things where they live.",
    "Wallet (Family > Wallet): cards for the cars, IDs, policies and membership cards, with the plate and number last four.",
    "Settings: household profile, people and PINs, the agent (name, tone, brief time, hidden rows), Connections (AI, "
    "phones, Google, phone bot), Data (back up, export, restore, updates, Data check, Health check).",
    "A bill's status: due = not paid, overdue = past its date, paid; Mark paid / Mark as not paid on the bill's record or "
    "Paid on Today; a yearly bill rolls to next year when paid.",
    "A charge in the wrong category: Money > Look back > Ledger, open the line, pick the category, Save; tick 'Do the same for "
    "every line like this one' to make it a rule. Or in the Ledger pick category Uncategorized and Remember a shop's category.",
    "A charge or bill entered twice, a bill open long after its date: Settings > Data > Data check lists them with "
    "Remove / Paid / Keep; Undo on that page puts a removed copy back.",
    "A paper filed as the wrong type or with wrong details: open its record and change it; a file still waiting in the "
    "Inbox can be filed by hand with File it by hand, or read again with Reprocess.",
    "A wrong name, birthday or school: Family, the pencil on the person's card, Change it; a new name is used everywhere "
    "from then on.",
    "A missed statement month: Money > Look back > Missing statements names the account and month; drop the statement on Add.",
    "Subscriptions: Money > Pay > Subscriptions; Keep or Cancel records the decision only (nothing is cancelled for you); "
    "tracking on / off hides one from reminders.",
    "Budget: Money > Keep > Budget and loans; a limit per category and how each line is going this month.",
    "Classes that repeat weekly: Family > People > Classes and activities. One-off dates, forms, appointments: Life "
    "items. Routine checkups (dental, physical, furnace filter): Checkups, marked done with a date.",
    "Holidays, festivals, days off school: Family > People > Holidays and dates; public holidays come from the country "
    "pack and are not stored. Family events with nobody in particular (dinner at 8, a party; with a start and end time "
    "or all day) and yearly dates (anniversaries): the same page, Add a family event or a yearly date; a visit for one "
    "person is an appointment.",
    "Mitra Wall: a paired tablet showing Today, Week / Month, Chores, Lists, Meals and a resting clock with photos; "
    "set up and the wall screen (clock, photos, night hours) in Settings > Phones > Mitra Wall; children's jobs, stars "
    "goals and rewards (children ask, adults give) in Family > Routines; bills without amounts, Money behind an adult's PIN.",
    "Family > House: city, state, ZIP code (state holidays) and the Look things up online switch (schools near home, "
    "college name check, finding a school / college / work calendar on a person's record, local weather).",
    "Phones: Settings > Phones pairs the companion app with a QR code; the phone bot (Telegram / Discord) answers /due, "
    "/week, /ask in a private chat; children never get money details.",
    "Papers never leave this PC; only what an adult types or a filed paper's fields go to the family's own AI; the "
    "assistant records and adds up, it does not give tax, legal, medical, insurance or financial advice.",
]


def glossary_text():
    return "\n".join("- " + re.sub(r"\[([^\]]+)\]", r"\1", line) for line in GLOSSARY)


def lookup(text, n=3):
    """Help entries for ANY question about the app (no how-do-I prefix needed): the how-to scorer first, then every
    word of the text in an entry, best first ([] when nothing fits)."""
    keys = howto(text, n)
    if keys:
        return keys
    words = [w for w in _words(text) if w not in _VERBS]
    hits = [k for k in search(" ".join(words)) if words] if words else []
    return hits[:n]


def as_data(key):
    """One entry as plain text for the AI: title, purpose, each section, the links' labels (never a URL)."""
    e = HELP[key]
    out = [f"{e['title']}: {e['purpose']}"]
    for heading, lines in e["sections"]:
        out.append(f"{heading}:")
        out += ["  - " + re.sub(r"\[([^\]]+)\]", r"\1", line) for line in lines]
    if e.get("links"):
        out.append("See also: " + ", ".join(label for label, _ in e["links"]))
    return "\n".join(out)


def main(argv=None):
    """  python data/help_text.py lookup WORDS...   the entries that answer a question, as text
         python data/help_text.py glossary         the facts about the app the assistant always sees"""
    import sys
    if hasattr(sys.stdout, "reconfigure"):  # a Windows console is cp1252: the help text has characters such as "⋯"
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a = list(sys.argv[1:] if argv is None else argv)
    if a[:1] == ["glossary"]:
        print(glossary_text())
    elif a[:1] == ["lookup"] and a[1:]:
        keys = lookup(" ".join(a[1:]))
        print("\n\n".join(f"[{k}]\n{as_data(k)}" for k in keys) if keys else "No help entry matches those words.")
    else:
        raise SystemExit(main.__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
