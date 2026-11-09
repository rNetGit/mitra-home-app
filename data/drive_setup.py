"""Guided Google Drive setup for the phone drop box and briefs (Google Drive for Desktop; no OAuth, no API).

  python data/drive_setup.py find              list Drive folders found on this PC
  python data/drive_setup.py check [FOLDER]    test Inbox sweep + Brief write in FOLDER (default: config drive_path)

Used by `python onboard.py add drive`. Layout created under the Drive folder you pick:
  MitraHome/Inbox   phone -> PC. Drop bills, photos, statements here from the Drive app. The PC sweeps them into inbox/
                      and removes them from Drive after verifying the copy.
  MitraHome/Brief   PC -> phone. Only the daily brief and weekly digest (PDF). They contain vendor names and amounts.
Raw documents, the database and backups never go to Drive. Do not share Inbox with anyone you would not trust to drop files
there; do not share Brief with anyone who should not see your bills.
"""
import os
import pathlib
import platform
import sys
import tempfile
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import brand  # noqa: E402


def find_drive_roots():
    """Folders that look like Google Drive for Desktop's 'My Drive' on this PC."""
    found = []
    home = pathlib.Path.home()
    if platform.system() == "Windows":
        for letter in "GHIJKLMNOPQRSTUVWXYZDEF":
            for name in ("My Drive", "Google Drive"):
                p = pathlib.Path(f"{letter}:/{name}")
                if p.is_dir():
                    found.append(p)
        found += [p for p in (home / "Google Drive", home / "My Drive") if p.is_dir()]
    else:
        found += [p for p in (home / "Google Drive", home / "My Drive") if p.is_dir()]
        cloud = home / "Library" / "CloudStorage"
        if cloud.is_dir():
            found += [p / "My Drive" for p in cloud.glob("GoogleDrive-*") if (p / "My Drive").is_dir()]
    seen, out = set(), []
    for p in found:
        k = str(p.resolve()).lower()
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


def prepare(root):
    """Create <root>/MitraHome/{Inbox,Brief} (or use <root>/Mitra Home when that one is already there, from before
    the rename). Returns the folder."""
    root = pathlib.Path(root)
    if not root.is_dir():
        raise FileNotFoundError(f"{root} is not a folder. Is Google Drive for Desktop running and signed in?")
    if root.name.lower() in ("mitrahome", "familyagent"):
        fa = root
    else:
        fa = root / "FamilyAgent" if (root / "FamilyAgent").is_dir() and not (root / "MitraHome").exists() else root / "MitraHome"
    (fa / "Inbox").mkdir(parents=True, exist_ok=True)
    (fa / "Brief").mkdir(parents=True, exist_ok=True)
    return fa


def selftest(fa):
    """Local round trip: a test file in Inbox is swept into a throwaway folder and removed from Drive; Brief is writable.
    Does not touch the real inbox/. Returns [(check name, ok, note)]."""
    import sync_drive
    fa = pathlib.Path(fa)
    res = []
    marker = fa / "Inbox" / "MitraHome_selftest.txt"
    try:
        marker.write_text(f"{brand.PRODUCT} drive test. Safe to delete.", encoding="utf-8")
        old = time.time() - 600
        os.utime(marker, (old, old))
        with tempfile.TemporaryDirectory() as td:
            pulled, _ = sync_drive.pull(drive=fa, dst=td)
            res.append(("test file swept from Drive Inbox to this PC", pulled == [marker.name] and (pathlib.Path(td) / marker.name).exists(), ""))
        res.append(("...and removed from Drive after the copy", not marker.exists(), ""))
    except OSError as e:
        res.append(("Inbox is readable and writable", False, str(e)))
    finally:
        marker.unlink(missing_ok=True)
    probe = fa / "Brief" / ".mitrahome_write_test"
    try:
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
        res.append(("Brief folder is writable", True, ""))
    except OSError as e:
        res.append(("Brief folder is writable", False, str(e)))
    return res


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "find"
    if cmd == "find":
        roots = find_drive_roots()
        print("\n".join(str(p) for p in roots) or "No Google Drive folder found. Install Google Drive for Desktop and sign in.")
    elif cmd == "check":
        import config
        target = sys.argv[2] if len(sys.argv) > 2 else str(config.drive_path() or "")
        if not target:
            sys.exit("No folder given and drive_path is not set. Run: python onboard.py add drive")
        ok_all = True
        for name, ok, note in selftest(target):
            ok_all &= ok
            print(f"  [{'x' if ok else '!'}] {name}{(': ' + note) if note else ''}")
        sys.exit(0 if ok_all else 1)
