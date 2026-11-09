"""Which job does a timesheet belong to? (Work, S2.) No AI: the words on the sheet against the family's jobs.

candidates(con, text, uploader=None) -> [{id, label, score, reasons}] best first, only active jobs that need timesheets and
that the uploader may see (a private job only for its owner; no uploader = shared jobs only).
choose(cands) -> the one job to import into, or None when a person must pick (nothing is guessed between two jobs).
rule_add(con, contract_id, phrase) remembers words printed on that job's sheets.
"""
import datetime as dt
import re

RULE_SCORE, NAME_SCORE, NUMBER_SCORE, UPLOADER_SCORE = 10, 4, 4, 2
CONFIDENT, MARGIN = 4, 3


def _norm(s):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).split())


def _has(hay, needle):
    n = _norm(needle)
    return len(n) >= 3 and f" {n} " in f" {hay} "


def _label(c):
    return c["client"] + (f" ({c['person']})" if c.get("person") else "")


def jobs(con, uploader=None):
    cur = con.cursor()
    cur.row_factory = __import__("sqlite3").Row
    rows = [dict(r) for r in cur.execute("SELECT * FROM contracts WHERE status='active' AND (needs_timesheets=1 OR timesheet_cycle IS NOT NULL) "
                                    "ORDER BY client, id")]
    return [c for c in rows if c.get("visibility") != "private" or (uploader and c.get("person") == uploader)]


def candidates(con, text, uploader=None):
    hay = _norm(text)
    rules = []
    try:
        rules = con.execute("SELECT pattern, contract_id FROM work_match_rules").fetchall()
    except Exception:  # noqa: BLE001 (an older database: no rules yet)
        pass
    out = []
    for c in jobs(con, uploader):
        score, why = 0, []
        for pat, cid in rules:
            if cid == c["id"] and _has(hay, pat):
                score += RULE_SCORE
                why.append("a remembered phrase")
        for key, label in (("client", "the name"), ("vendor", "the agency")):
            if c.get(key) and _has(hay, c[key]):
                score += NAME_SCORE
                why.append(label)
        no = _norm(c.get("contract_no")).replace(" ", "")
        if len(no) >= 4 and no in hay.replace(" ", ""):
            score += NUMBER_SCORE
            why.append("the number")
        if uploader and c.get("person") == uploader:
            score += UPLOADER_SCORE
            why.append("it is yours")
        out.append({"id": c["id"], "label": _label(c), "score": score, "reasons": why, "person": c.get("person")})
    return sorted(out, key=lambda x: (-x["score"], x["label"]))


def choose(cands):
    if len(cands) == 1:
        return cands[0]
    if len(cands) > 1 and cands[0]["score"] >= CONFIDENT and cands[0]["score"] - cands[1]["score"] >= MARGIN:
        return cands[0]
    return None


def rule_add(con, contract_id, phrase):
    p = _norm(phrase)
    if not 3 <= len(p) <= 60:
        raise ValueError("the phrase must be 3 to 60 letters or digits")
    con.execute("INSERT INTO work_match_rules(pattern, contract_id, created_at) VALUES (?,?,?) "
                "ON CONFLICT(pattern) DO UPDATE SET contract_id=excluded.contract_id",
                (p, int(contract_id), dt.datetime.now().isoformat(timespec="seconds")))
    return p
