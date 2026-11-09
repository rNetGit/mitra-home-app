# The Mitra Wall: an old tablet on the wall

The Mitra Wall turns a spare iPad, Android tablet or Fire tablet into the family's screen in the kitchen or hall:

- the week as a calendar, in each person's colour;
- what is on today, and what needs doing;
- the children's jobs, with stars;
- the family's lists and the week's meals;
- a big clock when nobody is using it.

It runs in the tablet's web browser. There is no app to install.

## Before you start: what to know

- **The PC has to be on**, with Mitra Home open to phones (the default; Settings > Phones > Connection shows it). The
  wall talks only to that PC over the home Wi-Fi, encrypted with the PC's own certificate. Nothing goes through the
  internet.
- **The wall is not a person.** It has its own sign-in, made by pairing. Nobody's PIN is stored on the tablet. It can:
  - tick family lists and the children's jobs, and add to the family lists;
  - show calendar names, with bills only as "due" or "late".

  It never shows adults-only lists, critical info, papers or scans.
- **Money stays locked.** The Money screen opens only when an adult types their own PIN on the wall. It locks itself
  again after a minute. Too many wrong PINs lock it for a while, the same as signing in.
  Inside Money, four pages: **Overview** (this month, the next two weeks' bills, allowance), **Spending** (each
  category this month, last month and the same month last year), **Bills** (paid this month next to last month, and
  what has not come yet) and **Regular** (the bills and subscriptions that keep coming, a month and a year).

## 1. Pair the tablet

1. On the PC, open **Settings › Phones**.
2. Under **Mitra Wall**, give the wall a name (for example *Kitchen wall*) and press **Show the wall code**.
3. On the tablet, point the camera at the code. (Or open the address shown under the code in the browser and type
   the eight letters and digits.)
4. The first time, the tablet's browser warns that the connection is not private. That is because the certificate
   is this PC's own, not one bought from a company. Continue only when the certificate fingerprint matches the one
   shown on the PC under **Phones on the home Wi-Fi**.
5. Press **Pair this wall**. The wall opens on Today.

The code works once, for 15 minutes. Up to five walls can be paired.

## 2. Keep it on the wall

The wall keeps the screen awake while it is open, where the browser allows it. It goes to the clock after two minutes
untouched and dims from 10 PM to 6 AM. Each tablet also needs a few of its own settings.

**iPad**
- Settings › Display & Brightness › Auto-Lock: **Never** (keep it plugged in).
- Settings › Accessibility › **Guided Access**: turn it on and set a passcode. Open the wall in Safari, then
  triple-click the top (or Home) button and press Start. The iPad then stays on the wall and nobody can leave it
  without the passcode.

**Android tablet**
- Settings › Display › Screen timeout: the longest there is. Some tablets also have a "stay awake while charging"
  switch under Developer options.
- Pin the screen: Settings › Security › **App pinning** (or Screen pinning). Open the wall in Chrome, open recent
  apps, tap Chrome's icon and choose Pin.
- Or use a kiosk browser app from the Play Store that opens one address in full screen.

**Fire tablet**
- Settings › Display › Screen timeout: the longest there is. Open the wall in the Silk browser and keep the tablet
  on its charger.

Portrait or landscape both work: the screens rearrange themselves.

## 3. Set up the children's jobs

On the PC, open **Family › Routines**:

- **Add a job** for each child: morning, after school or evening. Give it a picture and 1 to 5 stars, on chosen days
  or every day.
- **What a star is worth** sets the allowance rate (25¢ unless you change it; 0 = stars only).
- **Goal**: something a child is saving stars for, for example *New bike, 100 stars*. Only stars earned from the day
  the goal is set count toward it. The wall shows how far along it is.
- **Put it in the budget** turns "every job done for a month" into the child's allowance line in Money.

Nothing is paid automatically.

## 4. The clock and photos (optional)

After two minutes untouched the wall shows a full-size clock. On the PC, **Settings › Phones › Mitra Wall › Wall
screen** chooses:

- **Clock**: digital; traditional (hands); **modular** (a big time with cards for the weather, what is next, the
  children's jobs as rings and dinner, and a line for today's holidays and what is coming); or **Roman** (quiet hands
  with serif numerals, the date and the next three things).
- **Photos**: shown in turn with the clock during the photo hours (7 AM to 9 PM unless changed); the clock shows for
  a while (45 seconds), then a few photos (4, 15 seconds each), then the clock again.
- **Night**: from 10 PM to 6 AM unless changed, the wall stays on a dark clock with no photos.
- **Night clock**: *dim* keeps the day's clock, darker. *Red* or *amber* turns the wall into a bedroom clock: a black
  screen with only the large time, the date and the next thing, in a colour that does not light up the room. The
  setting is for every paired wall.

**Add photos** on the same card (several at once; iPhone photos work too). The PC makes each photo again: turned upright,
at most 1920 pixels, and without its location or camera details. They are kept on the PC in the household folder
(`wall_photos`), and only a paired wall shows them. **Remove** takes a photo off the wall (your original is untouched).

## 5. The weather (optional)

The wall can show the local weather: now and today's high and low on Today, a small temperature next to the resting
clock, and each day's high and low on the week. The PC fetches it (the tablet never goes online) about every 45
minutes, only when **Family › House** has the ZIP code and **Look things up online** is on. What goes out: the ZIP code
and the rough position of the ZIP area, never the house or anyone's name. US forecasts come from the National Weather
Service; elsewhere, or when it does not answer, from Open-Meteo. No weather (switch off, no ZIP, no internet) = the
wall simply shows none.

## Remove a wall

On the PC: **Settings › Phones › Mitra Wall**, tick the box next to the wall, then **Remove**. The tablet shows the
pairing page at its next refresh (within a minute).

## When something is not right

| What you see | What to do |
|---|---|
| "The wall opens over HTTPS only" | Settings › Phones › Connection › **Restart for phones** on the PC, then use the address shown there. |
| "Safari can't open the page because it couldn't establish a secure connection" | Update the PC to 0.124.1 or later and start it **for phones** again: older versions made a certificate iPads refuse. |
| The tablet times out but the PC opens the page | Windows Firewall blocks it. Settings › Phones › Connection shows the rule and the network type, with **Allow phones through Windows Firewall** (Windows asks to confirm). When Windows calls the home Wi-Fi a **Private** network, an allow rule for **Public** networks does not count. By hand: Administrator PowerShell, `New-NetFirewallRule -DisplayName "Mitra Home phones" -Direction Inbound -Protocol TCP -LocalPort 8701 -Profile Private -RemoteAddress LocalSubnet -Action Allow`. |
| "This Connection Is Not Private" | Expected the first time: the PC makes its own certificate. Tap **Show Details**, check the fingerprint matches Settings › Phones on the PC, then **visit this website**. |
| The pairing page again | The wall was removed, or the code was too old. Make a new code on the PC. |
| "PC offline since 9:42 · showing 9:40" | The PC is off, asleep, restarting or on another Wi-Fi. The wall stays on the screen it had (the clock keeps going) and asks the PC again every 30 seconds; it updates by itself once the PC answers. Ticks and adds need the PC for now. |
| Money will not open | Only adults with a sign-in PIN can open it. After too many wrong PINs, wait and try again. |
| A change made on a phone does not show yet | The wall reloads itself every minute when nobody is touching it. |
| No weather | Set the ZIP code and turn on **Look things up online** in Family › House. The first forecast shows within a minute or two; `python data/weather.py status` on the PC says when it last worked. |
