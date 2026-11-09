"""Plain-words explanation of a data check run (data/audit.py): one AI call per run says what the findings mean and what to
look at first, plus one short line per finding. No API provider (or a signed-in CLI) = nothing, and the page works as
before.

Safety, as in brief_narrative.py: findings are masked by data/pii.py before they leave and put back in the answer; they
are marked as data, never instructions; an answer is kept only when it is short, has no link and no number that is not
in the findings (brief_narrative.clean); one answer per run (logs/audit_explain.json) and at most MAX_PER_DAY fresh
calls a day. Only the finding lines are sent: no account numbers (the findings have none), no papers, no other records.

  python data/audit_explain.py [--force]     explain the newest run (the weekly digest task runs it)
  explain(con, run_id=None, force=False)     -> {"summary", "items": {dedupe_key: line}} or None
  cached(run_id)                             -> the stored explanation or None
"""
import argparse
import datetime as dt
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import config  # noqa: E402
import dates  # noqa: E402
import db  # noqa: E402
import paths  # noqa: E402

CACHE = paths.LOGS / "audit_explain.json"
MAX_PER_DAY = 3
MAX_FINDINGS = 10
ITEM_CHARS = 200
KEEP_RUNS = 12
SYSTEM = ("You explain a household records check to the family. Use only the facts in the list. No greeting, no markdown, "
          "no links, no new numbers or dates, no financial, tax or legal advice. Plain, calm words.")
SCHEMA = {"summary": (str, True, None), "items": (list, False, {"n": (int, True, None), "why": (str, True, None)})}


def provider_ok():
    try:
        import brief_narrative
        return brief_narrative.provider_ok()
    except Exception:  # noqa: BLE001
        return False


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


def cached(run_id):
    return (_read().get("runs") or {}).get(str(run_id))


def _findings(con, run_id):
    return db.rows(con, "SELECT dedupe_key, level, summary, detail FROM audit_findings WHERE run_id=? ORDER BY "
                        "CASE level WHEN 'money' THEN 0 WHEN 'decide' THEN 1 ELSE 2 END, id LIMIT ?", (run_id, MAX_FINDINGS))


def facts(fs):
    word = {"money": "Numbers off", "decide": "To decide", "note": "Note"}
    return "\n".join(f"{i}. [{word.get(f['level'], f['level'])}] {f['summary']}" + (f" ({f['detail']})" if f["detail"] else "")
                     for i, f in enumerate(fs, 1))


def explain(con, run_id=None, force=False, today=None):
    """Explain run `run_id` (default the newest finished one). Cached per run; `force` asks again (still capped)."""
    import brief_narrative as bn
    import llm
    import pii
    today = today or dates.today()
    if run_id is None:
        r = db.one(con, "SELECT MAX(id) AS id FROM audit_runs WHERE finished_at IS NOT NULL")
        run_id = r and r["id"]
    if not run_id:
        return None
    if not force and cached(run_id):
        return cached(run_id)
    fs = _findings(con, run_id)
    if not fs or not provider_ok():
        return None
    c = _read()
    if c.get("day") != today.isoformat():
        c["day"], c["calls"] = today.isoformat(), 0
    if int(c.get("calls", 0)) >= MAX_PER_DAY:
        return None
    text = facts(fs)
    red = pii.redactor()
    prompt = (f"{llm.UNTRUSTED}\n{llm.PRIVACY}\n\nA weekly check of the family's records found the items below. Answer as JSON "
              '{"summary": "two or three sentences: what these mean together and which to look at first", '
              '"items": [{"n": <item number>, "why": "one sentence: why it matters or what usually causes it"}]}.\n'
              f"Items:\n{red.redact(text)}")
    c["calls"] = int(c.get("calls", 0)) + 1
    out = None
    try:
        obj = json.loads(llm.complete(prompt, system=SYSTEM, json_mode=True, max_tokens=700, purpose="audit_explain"))
        if not llm.validate(obj, SCHEMA):
            summary = bn.clean(red.restore(obj["summary"]), text, len(fs))
            items = {}
            for it in obj.get("items") or []:
                n = it.get("n")
                if isinstance(n, int) and 1 <= n <= len(fs):
                    why = bn.clean(red.restore(it.get("why") or ""), text, len(fs))
                    if why and len(why) <= ITEM_CHARS:
                        items[fs[n - 1]["dedupe_key"]] = why
            if summary or items:
                out = {"summary": summary, "items": items, "at": dt.datetime.now().strftime("%Y-%m-%d %H:%M")}
    except Exception as e:  # noqa: BLE001 (the page works without it)
        import log
        log.get("audit").info("explanation skipped: %s", type(e).__name__)
    runs = c.get("runs") or {}
    if out:
        runs[str(run_id)] = out
        runs = dict(sorted(runs.items(), key=lambda kv: int(kv[0]))[-KEEP_RUNS:])
    c["runs"] = runs
    _write(c)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    if not provider_ok():
        print("no API provider: nothing to explain with")
        return 0
    with db.open(paths.DB, readonly=True) as con:
        x = explain(con, force=a.force)
    print(json.dumps(x, indent=1) if x else "nothing explained (no findings, the daily limit, or the answer was not usable)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
