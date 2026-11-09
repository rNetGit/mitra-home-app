"""The sentence or two at the top of Brief > Today: one AI call turns the list below it into plain words. No AI set (or a
signed-in CLI, which is too slow for a page that opens on a click) = nothing is drawn and nothing changes.

Safety, in this order: the rows are masked by data/pii.py before they leave (names become [personN] and are put back in
the answer); the rows are marked as data, never instructions; the answer is kept only when it is short, has no link and
no number or date that is not in the list; one answer per day and list (cached in logs/brief_narrative.json), and at
most MAX_PER_DAY fresh calls a day so ticking things off cannot run up the AI bill.

    narrate(rows, today, name="")     -> text ("" when there is nothing to say or no AI)
    cached(rows, today)               -> True when `narrate` would answer without a call
    rows: dicts with date, kind, title, amount (what Brief > Today shows)
"""
import hashlib
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import config  # noqa: E402
import llm  # noqa: E402
import pii  # noqa: E402

CACHE = paths.LOGS / "brief_narrative.json"
MAX_PER_DAY = 4
MAX_ROWS = 14
MAX_CHARS = 420
SYSTEM = ("You write the opening lines of a household's daily brief. Use only the facts in the list. At most three short "
          "sentences in plain words, no greeting, no markdown, no advice, no new numbers or dates, no links.")


def provider_ok():
    s = llm.settings()
    return s["provider"] in llm.API + ("fake",) and not llm.training_risk(s)


def _label(d, today):
    n = (d - today).days
    if n < 0:
        return f"overdue by {-n} day{'s' if n != -1 else ''}"
    if n == 0:
        return "today"
    if n == 1:
        return "tomorrow"
    return f"on {d:%A %B} {d.day}"


def facts(rows, today):
    """The list as plain lines, oldest first, capped; the order and wording are stable so the cache can key on them."""
    out = []
    for r in sorted(rows, key=lambda r: (r["date"], r.get("kind", ""), r.get("title", "")))[:MAX_ROWS]:
        amt = f" ({r['amount']:.2f})" if r.get("amount") else ""
        out.append(f"- {r.get('kind', 'Item')}: {r['title']}{amt}, {_label(r['date'], today)}")
    return "\n".join(out)


def _sig(text, name, tone):
    return hashlib.sha1(f"{name}|{tone}|{text}".encode("utf-8")).hexdigest()[:16]


def _read():
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(d):
    try:
        CACHE.parent.mkdir(exist_ok=True)
        config.write_json(CACHE, d)
    except OSError:
        pass


def _tone():
    try:
        import agent_profile
        return agent_profile.get()["tone"], agent_profile.tone_rule()
    except Exception:  # noqa: BLE001 (the profile is a nicety)
        return "brief", ""


def _forms(token):
    """A number as it may be written back: 1,234.50 -> 1,234.50 / 1234.50 / 1234 / 1,234."""
    flat = token.replace(",", "")
    out = {token, flat, flat.split(".")[0]}
    if "." in flat and set(flat.split(".")[1]) == {"0"}:
        out.add(flat.split(".")[0])
    if "," in token:
        out.add(token.split(".")[0])
    return out


def clean(text, source, nrows=0):
    """The answer if it can be trusted, else ''. Every number (amount, day) must appear in the list it was made from;
    a count of the rows themselves ("three bills") is fine."""
    t = " ".join((text or "").replace("*", "").replace("#", "").replace("`", "").split()).strip(" \"'")
    if not t or len(t) > MAX_CHARS or re.search(r"https?://|www\.|\[person\d+\]|\[[a-z ]+\]", t, re.I):
        return ""
    have = set()
    for tok in re.findall(r"\d+(?:[.,]\d+)*", source):
        have |= _forms(tok)
    for n in re.findall(r"\d+(?:[.,]\d+)*", t):
        n = n.rstrip(".,")
        if not (_forms(n) & have) and not (n.isdigit() and 0 < int(n) <= nrows):
            return ""
    return t


def cached(rows, today):
    text = facts(rows, today)
    if not text:
        return True
    c = _read()
    if c.get("day") != today.isoformat():
        return False
    return c.get("sig") == _sig(text, "", _tone()[0]) or int(c.get("calls", 0)) >= MAX_PER_DAY


def narrate(rows, today, name=""):
    text = facts(rows, today)
    if not text or not provider_ok():
        return ""
    tone, rule = _tone()
    sig = _sig(text, "", tone)
    c = _read()
    if c.get("day") != today.isoformat():
        c = {"day": today.isoformat(), "calls": 0}
    if c.get("sig") == sig:
        return c.get("text", "")
    if int(c.get("calls", 0)) >= MAX_PER_DAY:
        return ""
    r = pii.redactor()
    masked = r.redact(text)
    prompt = (f"{llm.UNTRUSTED}\n{llm.PRIVACY}\n\nToday is {today:%A %B} {today.day}. {rule}\n"
              f"Write the opening of the brief for these items:\n{masked}")
    out = ""
    try:
        out = clean(r.restore(llm.complete(prompt, system=SYSTEM, max_tokens=160, purpose="brief_narrative")), text,
                    min(len(rows), MAX_ROWS))
    except Exception as e:  # noqa: BLE001 (the brief opens without the sentence)
        import log
        log.get("brief").info("narrative skipped: %s", type(e).__name__)
    _write({"day": today.isoformat(), "sig": sig, "text": out, "calls": int(c.get("calls", 0)) + 1})
    return out
