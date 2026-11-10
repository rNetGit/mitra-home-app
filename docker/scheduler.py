"""Runs the lines of /data/config/crontab.txt (written by the wizard / Settings through the crontab shim).
Five time fields (numbers, *, */n, a-b, comma lists; weekday 0 or 7 = Sunday) then a shell command.
Checked every minute and the file is read each time, so a changed time applies without a restart."""
import datetime as dt
import subprocess
import time
from pathlib import Path

FILE = Path("/data/config/crontab.txt")


def field_ok(spec, value, lo, hi):
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, s = part.split("/", 1)
            step = int(s)
        if part in ("*", ""):
            a, b = lo, hi
        elif "-" in part:
            a, b = (int(x) for x in part.split("-", 1))
        else:
            a = b = int(part)
            if step != 1:
                b = hi
        if a <= value <= b and (value - a) % step == 0:
            return True
    return False


def due(line, now):
    f = line.split(None, 5)
    if len(f) < 6 or line.lstrip().startswith("#"):
        return None
    wd = (now.weekday() + 1) % 7  # cron: Sunday = 0
    ok = (field_ok(f[0], now.minute, 0, 59) and field_ok(f[1], now.hour, 0, 23) and field_ok(f[2], now.day, 1, 31)
          and field_ok(f[3], now.month, 1, 12) and (field_ok(f[4], wd, 0, 6) or (wd == 0 and field_ok(f[4], 7, 0, 7))))
    return f[5] if ok else None


def main():
    while True:
        now = dt.datetime.now()
        try:
            for line in FILE.read_text(encoding="utf-8").splitlines():
                cmd = due(line, now)
                if cmd:
                    subprocess.Popen(["sh", "-c", cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, ValueError):
            pass
        time.sleep(60 - dt.datetime.now().second)


if __name__ == "__main__":
    main()
