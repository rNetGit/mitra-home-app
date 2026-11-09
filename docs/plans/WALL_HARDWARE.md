# Mitra Wall hardware: beyond the old tablet

Can a cheap portable monitor with a small computer stick behind it serve as a Mitra Wall? Short answer: yes for the
screen, with care for input and power, and it is rarely cheaper than a used tablet. Written in October 2026 against
0.127.0; `docs/MITRA_WALL.md` is the family's setup guide.

## 1. What the wall needs from a device

From `data/webapp/static/wall.js` and `data/webapp/routes_wall.py`:

- **A browser with JavaScript**, on the home Wi-Fi, that can reach the PC's phone port (8701 by default) over HTTPS
  and accept the PC's own certificate once (check the fingerprint against Settings > Phones).
- **A cookie that survives restarts**: pairing sets `mh_wall` for 400 days. A kiosk browser that wipes cookies on
  exit would ask to pair at every boot.
- **Some way to tap.** The page listens for `click`, `pointerdown`, `keydown` and `touchstart`, so a mouse, a touch
  screen or a keyboard all work. Without any input the wall is display-only: it still shows Today, the week, the
  month, meals, the clock and photos, and reloads itself every minute, but nobody can tick a chore or a list, open a
  detail, or type a PIN for the Money screen.
- **A screen that stays on.** The page asks for a wake lock where the browser allows it; the device must not sleep
  on its own. Portrait or landscape both work.
- **Only the home Wi-Fi.** The wall never goes online; weather and photos come from the PC.

## 2. The monitor in question

A 15.6" 1080p portable monitor of the kind sold for laptops (USB-C or mini HDMI, a folding felt cover as the stand,
typically well under a hundred dollars) is a plain display: no computer, no Wi-Fi, no battery, and usually **no
touch**. Touch versions of the same size exist for roughly double the price. 15.6" at 1080p is a fine size for a
kitchen wall; the browser should be set to about 125 to 150 percent zoom so the agenda reads from across the room.

## 3. What to put behind it

| Stick or board | Fit | Notes |
|---|---|---|
| **Raspberry Pi 4 (2 GB or more) or Pi 5** | Good | Raspberry Pi OS with Chromium in kiosk mode (`--kiosk --noerrdialogs --disable-infobars`, screen blanking off). Plenty for one 1080p page. Needs its own power supply, a case and an SD card. The Pi 5 is more than this needs. |
| **Raspberry Pi Zero 2 W** | Marginal | Chromium at 1080p is slow to load and short on memory; the page is light once drawn, but reloads every minute. Works for display-only; not pleasant with input. |
| **Android TV stick** (any brand) with a kiosk browser app | Good, cheapest | A kiosk browser (several in the Play Store) opens one address full screen and keeps cookies. Comes with a remote, which gives arrow keys and Enter: enough for `data-pop` details, not comfortable for ticking a list. |
| **An old laptop or mini PC** | Good | Any browser in full screen; easiest to trust the certificate on. Bulkier. |

A touch monitor makes the Pi or the stick a real wall (ticks, lists, PIN pad). A non-touch monitor plus a small
wireless mouse or a numeric keypad is the cheap middle: the keypad alone types the PIN and moves between items.

## 4. Power

The monitor and the computer each need power; a USB-C monitor can sometimes be fed by the Pi's USB port but the
Pi 4's ports share a 1.2 A budget and most portable monitors want more, so plan on two plugs or one dual-port wall
charger of 30 W or more. Mount both behind the monitor with adhesive strips; the felt cover stand is not meant for a
wall, so a VESA adapter plate or a picture ledge is needed for anything permanent.

## 5. Cost picture (approximate, check before buying)

| Set-up | Rough cost | Touch | Battery | One device |
|---|---|---|---|---|
| Used iPad or Android tablet, 10" | 50 to 120 | yes | yes | yes |
| Fire tablet on sale, 10" | 60 to 100 | yes | yes | yes |
| Portable monitor + Android TV stick + remote | 90 to 140 | no | no | no |
| Portable monitor + Raspberry Pi 4 kit | 130 to 180 | no | no | no |
| Touch portable monitor + Raspberry Pi 4 kit | 200 to 260 | yes | no | no |

The tablet wins on price, touch, battery during a power cut, and having one thing to mount. The monitor route wins on
screen size (15.6" against 10") and on never running out of OS updates. It suits a family that already owns the
parts, or wants a larger screen.

## 6. What the app could do to help (not started)

- A setup note in `docs/MITRA_WALL.md` for "a monitor and a small computer": kiosk flags, trusting the certificate on
  Raspberry Pi OS and Android TV, zoom level, and a remote-control key map.
- A **keyboard-first mode** on the wall: number keys to tick the first nine jobs, arrow keys between items, Enter for
  details, Escape back to Today. Today only Enter and Space act on the focused item. Small change in `wall.js` and the
  routine templates, no server change.
- The pairing page could offer the 8-character code in large type for devices with no camera (the code already
  exists; the QR is the usual path).
- Nothing here needs a new hardware product: the design choice stays "hardware families already own".
