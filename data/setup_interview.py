"""The setup interview: the same questions as `python onboard.py` (family, people, country, AI, phone, logins), asked
one at a time in the app, with a draft saved after every screen so a person can stop and come back.

This module is the logic only (no web code): `validate` says what is wrong with an answer, `finish` writes
config/family.json and builds the database through the wizard's own functions (onboard.step_database, life seed),
so the screens and the terminal wizard cannot drift apart. Secrets (API key, bot token) never go in the draft: the
AI screen saves them straight to config/secrets.env through admin_actions.save_ai.
"""
import contextlib
import datetime as dt
import io
import json
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import dates  # noqa: E402
import config  # noqa: E402

CONFIG = paths.CONFIG / "family.json"
DRAFT = paths.CONFIG / "setup_draft.json"
DB = paths.DB
ROLES = ("adult", "child", "pet")
CLIMATES = ("cold", "mild", "hot")
MONTH_DAYS = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
# The chat-style first run asks these in this order (data/dashboard/interview.py); `step` in the draft indexes this list.
SECTIONS = ["Welcome", "AI", "Family", "Where", "Traditions", "People", "Home", "Cars", "Logins", "Finish"]


def needed():
    """True on a PC that has not been set up: no family name or members, or no database yet. A family.json that
    exists but cannot be read is a broken install, not a new one: the first run must not overwrite it."""
    cfg = config.family()
    if config.broken("family.json"):
        return False
    return not (cfg.get("family_name") and cfg.get("members")) or not DB.exists()


def _vehicles_now():
    """The active vehicles already in the database (a re-run starts from them), as {year, make, model}."""
    if not DB.exists():
        return []
    try:
        import db
        con = db.connect(DB, readonly=True)
        try:
            return [{"year": r[0], "make": r[1] or "", "model": r[2] or ""} for r in con.execute(
                "SELECT year, make, model FROM vehicles WHERE COALESCE(status,'active')='active' ORDER BY id")]
        finally:
            con.close()
    except Exception:  # noqa: BLE001 (older database without the table: nothing to prefill)
        return []


def defaults():
    """Answers to start from: what is already configured, then the saved draft on top."""
    cfg = config.family()
    reg = cfg.get("region") or {}
    a = {"family_name": cfg.get("family_name", ""), "country": cfg.get("country", "US"),
         "place": reg.get("place", ""), "state": reg.get("state", ""), "county": reg.get("county", ""), "zip": reg.get("zip", ""),
         "climate": cfg.get("climate") or ("cold" if cfg.get("cold_climate", False) else "mild"),
         "currency": cfg.get("currency", ""), "members": [dict(m) for m in cfg.get("members", [])],
         "home_office": bool(cfg.get("home_office", False)), "accept_rules": False, "step": 0,
         "tenure": (cfg.get("household") or {}).get("tenure", ""), "vehicles": _vehicles_now(),
         "cars_done": bool((cfg.get("household") or {}).get("no_vehicles")),
         "paper_names": list((cfg.get("privacy") or {}).get("paper_names") or []),
         "traditions": list(cfg.get("traditions") or []), "traditions_lookup": bool(cfg.get("traditions_lookup", True))}
    try:
        a.update(json.loads(DRAFT.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return a


def save_draft(answers):
    """Save progress. PINs and anything secret are never part of `answers`."""
    keep = {k: v for k, v in answers.items() if k not in ("pins", "logins_on")}
    config.write_json(DRAFT, keep)


def clear_draft():
    DRAFT.unlink(missing_ok=True)


def valid_birthday(month, day):
    try:
        return 1 <= int(month) <= 12 and 1 <= int(day) <= MONTH_DAYS[int(month) - 1]
    except (TypeError, ValueError):
        return False


def md_text(month, day):
    return f"{int(month):02d}-{int(day):02d}"


def member_problem(m, others=()):
    name = (m.get("name") or "").strip()
    if not name:
        return "Type a name."
    if len(name) > 60:
        return "That name is too long (60 characters at most)."
    if any(c in name for c in '<>"\\/') or any(ord(c) < 32 for c in name):
        return "Please use letters, numbers, spaces, apostrophes or hyphens in a name."
    if name.lower() in {o.lower() for o in others}:
        return f"{name} is already in the list."
    if m.get("role") not in ROLES:
        return "Choose adult, child or pet."
    bd = (m.get("birth_month_day") or "").strip()
    if bd and not re.fullmatch(r"(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])", bd):
        return "Birthday must be a month and a day."
    by = m.get("birth_year")
    if by not in (None, "") and not (str(by).isdigit() and 1900 <= int(by) <= dates.today().year):
        return "Birth year must be a four-digit year such as 1978."
    return ""


def validate(step, a):
    """-> list of plain-language problems for this screen (empty = fine to continue)."""
    out = []
    if step == "Family":
        if not (a.get("family_name") or "").strip():
            out.append("Give the family a name (it is only shown on your own screens).")
        if len((a.get("family_name") or "")) > 80:
            out.append("The family name is too long.")
        if a.get("climate") not in CLIMATES:
            out.append("Pick the climate that is closest.")
        cur = (a.get("currency") or "").strip()
        if cur and not re.fullmatch(r"[A-Za-z]{3}", cur):
            out.append("Currency is a three-letter code such as USD, GBP or INR.")
        if len((a.get("zip") or "")) > 12:
            out.append("That postal code is too long.")
    elif step == "People":
        ms = a.get("members") or []
        if not ms:
            out.append("Add at least one person.")
        elif not any(m.get("role") == "adult" for m in ms):
            out.append("Add at least one adult.")
        seen = []
        for m in ms:
            p = member_problem(m, seen)
            if p:
                out.append(f"{m.get('name') or 'A person'}: {p}")
            seen.append(m.get("name") or "")
    elif step == "Finish":
        if not a.get("accept_rules"):
            out.append("Please tick the box to accept the rules.")
        out += validate("Family", a) + validate("People", a)
    return out


TAX_NAMES = {"school_tax": "School tax", "property_tax": "Property tax"}


def home_tax_bills(taxes, today=None):
    """Yearly home tax bills from the setup answers ({key: 'YYYY-MM-DD'}): one open bill each (a date already passed
    moves to next year); a re-run of setup never adds a second open bill of the same name. -> messages."""
    import db
    today = today or dates.today()
    out = []
    with db.open(DB) as con:
        for k, day in taxes.items():
            name = TAX_NAMES.get(k)
            try:
                d = dt.date.fromisoformat(day)
            except (TypeError, ValueError):
                continue
            if not name:
                continue
            while d < today:
                d = d.replace(year=d.year + 1) if not (d.month == 2 and d.day == 29) else dt.date(d.year + 1, 2, 28)
            if con.execute("SELECT 1 FROM bills WHERE name=? AND status IN ('due','overdue')", (name,)).fetchone():
                continue
            con.execute("INSERT INTO bills(name, frequency, due_date, status) VALUES (?, 'yearly', ?, 'due')", (name, d.isoformat()))
            out.append(f"{name} reminder added for {d.isoformat()}.")
        con.commit()
    return out


def summary(a):
    ms = a.get("members") or []
    return [("Family", a.get("family_name") or "-"),
            ("Where", ", ".join(x for x in (a.get("place"), a.get("state"), a.get("country")) if x) or "-"),
            ("People", ", ".join(f"{m['name']} ({m['role']})" for m in ms) or "-"),
            ("Climate", a.get("climate") or "-"),
            ("Currency", (a.get("currency") or "").upper() or "from the country"),
            ("Traditions", ", ".join(a.get("traditions") or []) or "none (public holidays only)")]


def _regions(a, prof):
    labels = prof.get("address", {})
    return {"place": (a.get("place") or "").strip()[:80], "state": (a.get("state") or "").strip()[:60],
            "county": (a.get("county") or "").strip()[:60], "zip": (a.get("zip") or "").strip()[:12], "_labels": labels}


def finish(a, pins=None):
    """Write the configuration and build the database. -> (ok, [messages]). Safe to run again."""
    problems = validate("Finish", a)
    if problems:
        return False, problems
    import country as _country
    import seasonal_packs
    sys.path.insert(0, str(ROOT))
    import onboard
    cfg = dict(config.family())
    if not (cfg.get("ai") or {}).get("provider"):
        # "Not now" on the AI card is a choice: No AI. Left empty, the Inbox read it as Claude Code and waited for a
        # scheduled check, so a family without an AI never got File now for the papers this PC reads itself.
        cfg["ai"] = {**(cfg.get("ai") or {}), "provider": "none"}
    if not cfg.get("members") and not cfg.get("ui"):  # a brand-new install starts in the Simple view
        import view_mode
        cfg["ui"] = {"mode": view_mode.NEW_INSTALL}
    code = _country.normalize(a.get("country") or "US")
    prof = _country.load(code)
    cfg["family_name"] = a["family_name"].strip()
    cfg["members"] = [{"name": m["name"].strip(), "role": m["role"], "birth_month_day": (m.get("birth_month_day") or "").strip(),
                       "birth_year": int(m["birth_year"]) if str(m.get("birth_year") or "").isdigit() else None}
                      for m in a["members"]]
    if a.get("paper_names"):
        import pii
        names, _ = pii.clean_paper_names("\n".join(a["paper_names"]))
        cfg["privacy"] = {**(cfg.get("privacy") or {}), "paper_names": names}
    cfg["country"] = code
    reg = _regions(a, prof)
    reg.pop("_labels")
    cfg["region"] = reg
    cfg["climate"] = a["climate"]
    cfg["cold_climate"] = a["climate"] == "cold"
    cfg["seasonal_pack"] = seasonal_packs.recommend(code, a["climate"])
    cfg.setdefault("seasonal_addons", [])
    cfg["currency"] = (a.get("currency") or prof.get("currency") or "USD").upper()
    cfg["home_office"] = bool(a.get("home_office"))
    trad = [t for t in a.get("traditions") or [] if str(t).strip()]  # religious / cultural holidays (data/traditions.py)
    cfg["traditions"] = trad
    cfg["traditions_lookup"] = bool(a.get("traditions_lookup")) and bool(trad)
    taxes = (a.get("home_taxes") or {}) if a.get("tenure") == "own" else {}
    if a.get("tenure") in ("own", "rent"):
        cfg["household"] = {**(cfg.get("household") or {}), "tenure": a["tenure"]}
    # "no car" typed (or the step passed empty) is an answer: the profile meter must not ask again.
    hh = dict(cfg.get("household") or {})
    if a.get("cars_done") and not a.get("vehicles"):
        hh["no_vehicles"] = True
    else:
        hh.pop("no_vehicles", None)
    if hh:
        cfg["household"] = hh
    else:
        cfg.pop("household", None)
    cfg.setdefault("packs", {})
    msgs = []
    paths.ensure()
    config.write_json(CONFIG, cfg)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ok, why = onboard.step_database(cfg, None)
    if not ok:
        return False, [f"The database could not be built: {why}", buf.getvalue()[-400:]]
    msgs.append("Database ready.")
    r = subprocess.run([sys.executable, str(HERE / "life.py"), "seed"], cwd=ROOT, capture_output=True, text=True, timeout=120)
    line = (r.stdout.strip() or r.stderr.strip()[-200:]).splitlines()[0] if (r.stdout.strip() or r.stderr.strip()) else "Starter items added."
    msgs.append(line[:1].upper() + line[1:] + ("" if line.endswith(".") else "."))
    if taxes:
        msgs += home_tax_bills(taxes)
    if a.get("vehicles"):
        import edit_actions
        for x in a["vehicles"]:
            okv, msg = edit_actions.vehicle_add({"name": "setup", "role": "adult"}, x.get("make"), x.get("model"), x.get("year"))
            if not okv:
                msgs.append(f"A car was not saved: {msg}")
    ex, dst = paths.ROOT / "config" / "contacts.example.json", paths.CONFIG / "contacts.json"  # the example is code
    if ex.exists() and not dst.exists():
        dst.write_bytes(ex.read_bytes())
    if pins:
        import auth
        names = {m["name"]: m["role"] for m in cfg["members"]}
        for name, pin in pins.items():
            if name in names and len(pin or "") >= 4 and names[name] != "pet":
                auth.set_user(name, "adult" if names[name] == "adult" else "limited", pin)
        msgs.append("Logins saved (hashed).")
    with config.family_edit() as cfg:
        cfg["setup_completed"] = dates.today().isoformat()
    clear_draft()
    return True, msgs
