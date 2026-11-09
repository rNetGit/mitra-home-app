# Using Mitra Home away from home

Mitra Home never opens your PC to the internet. Away from home, the phone app shows its last copy, and anything you
add waits as "waiting to send" until the phone is back on the home Wi-Fi.

To reach the live app from anywhere, put your PC and your phones on a **private network** of your own. Tailscale is the
easiest: free for a family, nothing to set up on the router, and only devices you add can see each other. (Any other VPN
works too; see the end.)

## 1. Set up Tailscale

1. On the PC: install Tailscale from tailscale.com/download and sign in.
2. On each phone that should reach Mitra Home: install the Tailscale app and sign in **with the same account** (or
   share the PC with that person's account from Tailscale's admin page).
3. Leave Tailscale on, on the PC at least.

## 2. Start Mitra Home for phones

Mitra Home opens to phones by default (Settings > Phones > Connection). Start Tailscale first, then start Mitra Home
(or press **Restart for phones** there). When Tailscale runs, the app sees this PC's Tailscale
address (it starts with 100.) and:

- names it in the PC's own certificate (renewed with the same key, so paired phone apps 0.14 and later stay paired);
- prints it when it starts: "Phones on your private network (away from home): https://100.x.y.z:8701";
- shows it in **Settings > Phones > Phones on the home Wi-Fi > Away from home**.

## 3. Open it on the phone

With Tailscale on, open that address in the phone's browser. The first time the browser warns about the certificate:
check that the fingerprint matches the one in Settings > Phones, then continue. Sign in with your name and PIN, and
add it to the home screen.

It works on mobile data and any Wi-Fi, as long as the PC is on, Mitra Home runs for phones, and Tailscale is on at both
ends.

**The phone app** (not the browser) still syncs only on the home Wi-Fi for now; reaching the PC over Tailscale is planned
(docs/plans/MARKET_REVIEW.md, group 4).

## If it does not connect

- **Windows Firewall**: Settings > Phones > Connection > **Allow phones through Windows Firewall**, or once in PowerShell
  as administrator:
  `netsh advfirewall firewall add rule name="Mitra Home phones" dir=in action=allow protocol=TCP localport=8701 profile=private`.
  If Windows put the Tailscale network on another profile, use `profile=any` instead.
- **Use the 100. address, not a name**: Mitra Home accepts IP addresses. A Tailscale name (MagicDNS) needs
  `MITRAHOME_WEB_HOSTS=yourpc.tailnet-name.ts.net` set for the app, and the certificate does not name it, so the browser
  warns every time.
- **No "Away from home" in Settings**: Tailscale was not running when Mitra Home started. Start Tailscale, then
  Settings > Phones > Connection > Restart for phones (or close Mitra Home and start it again).

## Another VPN

Set `MITRAHOME_REMOTE_IP` to this PC's address on that network (for example a WireGuard or ZeroTier address) before
starting Mitra Home for phones. The certificate then names it and Settings shows it, exactly as with Tailscale.

## What this does not change

- Nothing listens on the internet: only devices on your private network can reach the PC.
- Sign-in still needs a PIN; the money rules, children's limits and everything else stay the same.
- Tailscale carries the traffic encrypted between your devices; Mitra Home's own HTTPS runs inside it.
