"""Saved items in data/family.db (table saved_items, migration 030): links, notes, places, deals, videos, repos, articles.

  python data/saved.py add "<title>" [--url U] [--kind K] [--note T] [--tags a,b] [--where ADDRESS] [--until YYYY-MM-DD]
                           [--adults | --private --by NAME]
  python data/saved.py find "<words>" [--kind K] [--tag T] [--all]     every word must match (title, note, tags, address,
                                                                      site, URL); --all: archived items and ended deals too
  python data/saved.py show ID
  python data/saved.py tag ID +x -y                                   add / remove tags
  python data/saved.py pin ID [--off]
  python data/saved.py archive ID
  python data/saved.py recent [N]
  python data/saved.py deals                                          deals still on, soonest end first
  python data/saved.py brief                                          brief/saved.md: pinned family items (for Drive, opt-in)

Safety: nothing is fetched from the internet (no title or preview download; the title is what a person typed). Only
http(s) URLs are stored, tracking parameters (utm_*, fbclid, gclid, YouTube `si`, ...) are stripped, and a URL that
looks like it carries a login token or password is refused. Free text is checked like every other field (no full
account, card or ID numbers, no email addresses).
Audience: family (everyone signed in, kids too), adults, private (only the person who saved it, on the dashboard; the
terminal and anyone with file access to this PC can still read the database). The terminal acts as an adult and
lists private items too, marked [private].
Library: clean_url, guess_kind, parse_tags, add, get, visible, search, recent, deals, set_tags, pin, archive, alerts,
expiry_rows, week_summary, brief_md, write_brief, bookmarks_html. Writers raise ValueError; the dashboard goes through
data/edit_actions.py (who may do what, logging).
"""
import brand
import argparse
import datetime as dt
import html
import pathlib
import re
import sqlite3
import sys
import urllib.parse as up

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import dates  # noqa: E402
import db  # noqa: E402
import pii  # noqa: E402
import validators as v  # noqa: E402
from dates import parse as _pd  # noqa: E402

DB = paths.DB
ROOT = HERE.parent
KINDS = ["link", "note", "place", "deal", "video", "repo", "article", "social"]
AUDIENCES = ["family", "adults", "private"]
MAX_KID_PER_DAY = 30  # limited users: items one person may add in a day
MAX_TAGS = 10

TRACKING = re.compile(r"^(utm_[a-z_]+|fbclid|gclid|dclid|gbraid|wbraid|msclkid|yclid|mc_cid|mc_eid|igshid|igsh|_hsenc|_hsmi|"
                      r"mkt_tok|oly_anon_id|oly_enc_id|vero_id|spm)$", re.I)
SI_HOSTS = ("youtube.com", "youtu.be", "music.youtube.com", "open.spotify.com")  # `si` there is a share-tracking id
SECRET_KEYS = re.compile(r"^(token|access_token|id_token|refresh_token|auth|auth_token|authtoken|apikey|api_key|key|sig|"
                         r"signature|x-amz-signature|password|passwd|pwd|pass|secret|session|sessionid|sid|otp)$", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
KIND_BY_HOST = [
    ("repo", ("github.com", "gitlab.com", "bitbucket.org", "codeberg.org", "huggingface.co")),
    ("video", ("youtube.com", "youtu.be", "m.youtube.com", "vimeo.com")),
    ("social", ("facebook.com", "fb.com", "m.facebook.com", "instagram.com", "x.com", "twitter.com", "tiktok.com",
                "threads.net", "reddit.com", "linkedin.com", "bsky.app")),
    ("place", ("maps.google.com", "maps.app.goo.gl", "maps.apple.com", "goo.gl")),
]


def _now():
    return dt.datetime.now().isoformat(timespec="seconds")


def _clean(validator, value, label):
    try:
        return validator(value)
    except (ValueError, TypeError) as e:
        raise ValueError(f"{label}: {e}") from None


# ---------------------------------------------------------------- URL, kind, tags, note
def clean_url(url):
    """-> (url, domain). http(s) only, no user:password@, no token-looking parameters, tracking parameters removed."""
    s = str(url or "").strip()
    if not s:
        return None, None
    if len(s) > 2000 or any(c.isspace() or ord(c) < 32 for c in s):
        raise ValueError("URL: too long or has spaces in it")
    p = up.urlsplit(s)
    if p.scheme.lower() not in ("http", "https") or not p.hostname:
        raise ValueError("URL: only web addresses that start with http:// or https:// can be saved")
    if p.username or p.password:
        raise ValueError("URL: it has a user name or password in it; save the address without it")
    host = p.hostname.lower()
    domain = host[4:] if host.startswith("www.") else host
    keep = []
    for part in (p.query, p.fragment):
        for k, _ in up.parse_qsl(part, keep_blank_values=True):
            if SECRET_KEYS.match(k) or "password" in k.lower() or "token" in k.lower():
                raise ValueError("URL: it looks like it carries a login token or password; never save those")
    for k, val in up.parse_qsl(p.query, keep_blank_values=True):
        if TRACKING.match(k) or (k.lower() == "si" and domain in SI_HOSTS):
            continue
        keep.append((k, val))
    q = up.urlencode(keep, doseq=True, quote_via=up.quote) if keep != up.parse_qsl(p.query, keep_blank_values=True) else p.query
    netloc = host + (f":{p.port}" if p.port else "")
    out = up.urlunsplit((p.scheme.lower(), netloc, p.path or "", q, p.fragment))
    if EMAIL.search(up.unquote(p.query + " " + p.fragment)):
        raise ValueError("URL: it has an email address in it; save the address without it")
    return out, domain


def guess_kind(url=None, domain=None):
    """Kind from the site: repo / video / social / place, else link; no URL = note."""
    if not url:
        return "note"
    domain = domain or clean_url(url)[1]
    path = up.urlsplit(url).path.lower()
    if re.match(r"^(www\.)?google\.[a-z.]+$", domain) and path.startswith("/maps"):
        return "place"
    if domain == "goo.gl" and not path.startswith("/maps"):
        return "link"
    for kind, hosts in KIND_BY_HOST:
        if domain in hosts or any(domain.endswith("." + h) for h in hosts):
            return kind
    return "link"


def parse_tags(tags):
    """'Goa, #Restaurants,birthday' -> ['goa', 'restaurants', 'birthday'] (lower case, no duplicates, at most 10)."""
    if tags is None:
        return []
    raw = tags if isinstance(tags, (list, tuple)) else str(tags).split(",")
    out = []
    for t in raw:
        t = " ".join(str(t).strip().lstrip("#").lower().split())
        if not t:
            continue
        t = _clean(v.text(30), t, "tag")
        if "," in t:
            raise ValueError("tag: no commas inside a tag")
        if t not in out:
            out.append(t)
    if len(out) > MAX_TAGS:
        raise ValueError(f"at most {MAX_TAGS} tags")
    return out


def _tags_str(lst):
    return ",".join(lst) or None


def clean_note(x, max_len=5000):
    """A note keeps its line breaks (unlike one-line text fields)."""
    if x is None or not str(x).strip():
        return None
    s = "\n".join(line.rstrip() for line in str(x).replace("\r\n", "\n").replace("\r", "\n").strip().split("\n"))
    if len(s) > max_len or any(ord(c) < 32 and c not in "\n\t" for c in s):
        raise ValueError(f"note: at most {max_len} characters of plain text")
    if pii.contains_hard(s):
        raise ValueError("note: contains a full account, card, ID or SSN-shaped number or an email address; store the last four digits only")
    return s


# ---------------------------------------------------------------- read
def _rows(con, sql, params=()):
    con.row_factory = sqlite3.Row
    return [_dress(dict(r)) for r in con.execute(sql, params)]


def _dress(r):
    r["tag_list"] = [t for t in (r.get("tags") or "").split(",") if t]
    return r


def get(con, item_id):
    r = _rows(con, "SELECT * FROM saved_items WHERE id=?", (item_id,))
    return r[0] if r else None


def visible(item, viewer):
    """viewer None = the terminal (sees all). Adults: family + adults + their own private. Others: family + their own private."""
    if viewer is None:
        return True
    name, role = (viewer or {}).get("name") or "", (viewer or {}).get("role")
    if item["audience"] == "private":
        return bool(name) and item["owner"] == name
    return item["audience"] == "family" or role == "adult"


def _where(viewer, today, all):
    w, a = [], []
    if not all:
        w.append("status='active' AND (expires_on IS NULL OR expires_on >= ?)")
        a.append(today.isoformat())
    if viewer is not None:
        name = (viewer or {}).get("name") or ""
        aud = "audience IN ('family','adults')" if (viewer or {}).get("role") == "adult" else "audience='family'"
        w.append(f"({aud} OR (audience='private' AND owner=? AND owner<>''))")
        a.append(name)
    return (" WHERE " + " AND ".join(w)) if w else "", a


def search(con, words="", kind=None, tag=None, viewer=None, today=None, all=False, owner=None, limit=200):
    """Items the viewer may see where every word appears somewhere (title, note, tags, address, site, URL).
    Pinned first, then title matches, then newest. Ended deals and archived items only with all=True."""
    today = today or dates.today()
    where, args = _where(viewer, today, all)
    extra = []
    if kind:
        extra.append("kind=?")
        args.append(kind)
    if tag:
        extra.append("(',' || COALESCE(tags,'') || ',') LIKE ?")
        args.append(f"%,{tag.strip().lstrip('#').lower()},%")
    if owner:
        extra.append("owner=?")
        args.append(owner)
    ws = [w.lower() for w in str(words or "").split() if w.strip()]
    for w in ws:
        extra.append("lower(title || ' ' || COALESCE(body,'') || ' ' || COALESCE(tags,'') || ' ' || COALESCE(place_address,'') "
                     "|| ' ' || COALESCE(domain,'') || ' ' || COALESCE(url,'')) LIKE ? ESCAPE '\\'")
        args.append("%" + w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
    if extra:
        where = (where + " AND " if where else " WHERE ") + " AND ".join(extra)
    rs = _rows(con, "SELECT * FROM saved_items" + where + " ORDER BY added_at DESC, id DESC", args)
    if ws:
        rs.sort(key=lambda r: -sum(w in r["title"].lower() for w in ws))
    rs.sort(key=lambda r: -r["pinned"])
    return rs[:limit]


def recent(con, n=10, viewer=None, today=None):
    return search(con, viewer=viewer, today=today, limit=n)


def deals(con, viewer=None, today=None):
    """Deals still on (end date today or later, or no end date), soonest end first."""
    rs = search(con, kind="deal", viewer=viewer, today=today)
    return sorted(rs, key=lambda r: (r["expires_on"] is None, r["expires_on"] or ""))


def added_today_by(con, owner, today=None):
    today = today or dates.today()
    return con.execute("SELECT COUNT(*) FROM saved_items WHERE owner=? AND substr(added_at,1,10)=?",
                       (owner, today.isoformat())).fetchone()[0]


# ---------------------------------------------------------------- writers (no permission checks here)
def add(con, title, url=None, kind=None, note=None, tags=None, where=None, until=None, audience="family", owner=None):
    """Returns (id, added?). A URL already saved and active comes back as (its id, False) instead of a second row."""
    title = _clean(v.text(200), title, "title")
    url, domain = clean_url(url)
    until = _clean(v.iso_date, until, "until") if until not in (None, "") else None
    kind = kind or ("deal" if until else guess_kind(url, domain))  # an end date and no kind: it is a deal
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    if audience not in AUDIENCES:
        raise ValueError("audience must be family, adults or private")
    if audience == "private" and not owner:
        raise ValueError("a private item needs the name of the person it belongs to")
    note = clean_note(note)
    where = _clean(v.text(200), where, "where") if where not in (None, "") else None
    tg = _tags_str(parse_tags(tags))
    if url:
        old = con.execute("SELECT id FROM saved_items WHERE url=? AND status='active' AND audience=? AND COALESCE(owner,'')=?",
                          (url, audience, owner or "")).fetchone()
        if old:
            return old[0], False
    iid = con.execute("INSERT INTO saved_items(kind, title, url, domain, body, place_address, expires_on, tags, audience, owner, "
                      "added_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (kind, title, url, domain, note, where, until, tg, audience, owner or None, _now())).lastrowid
    return iid, True


def set_tags(con, item_id, plus=(), minus=()):
    r = get(con, item_id)
    if not r:
        raise ValueError(f"no saved item {item_id}")
    tags = [t for t in r["tag_list"] if t not in parse_tags(list(minus))]
    tags = parse_tags(tags + parse_tags(list(plus)))
    con.execute("UPDATE saved_items SET tags=? WHERE id=?", (_tags_str(tags), item_id))
    return tags


def pin(con, item_id, on=True):
    return bool(con.execute("UPDATE saved_items SET pinned=? WHERE id=?", (1 if on else 0, item_id)).rowcount)


def archive(con, item_id):
    return bool(con.execute("UPDATE saved_items SET status='archived' WHERE id=? AND status='active'", (item_id,)).rowcount)


def opened(con, item_id):
    con.execute("UPDATE saved_items SET last_opened=? WHERE id=?", (_now(), item_id))


# ---------------------------------------------------------------- reminders, digest, phone, export
def _missing(e):
    if not db.missing(e):
        raise e
    return []


def expiry_rows(con, today=None):
    """Deals with an end date today or later (not private): data/expiries.py lists them as type 'deal'."""
    today = today or dates.today()
    try:
        return _rows(con, "SELECT * FROM saved_items WHERE status='active' AND audience<>'private' AND expires_on >= ? "
                          "ORDER BY expires_on", (today.isoformat(),))
    except sqlite3.OperationalError as e:
        return _missing(e)


def alerts(con, today):
    """Deals ending inside their reminder lead (expiries type 'deal'): the Action tab and the .ics file."""
    import expiries
    lead = expiries.lead_days("deal")
    out = []
    for r in expiry_rows(con, today):
        end = _pd(r["expires_on"])
        if end and end <= today + dt.timedelta(days=lead):
            out.append({"date": end, "kind": "Deal", "title": f"Deal ends {end:%a %b %d}: {r['title']}",
                        "detail": r["domain"] or r["place_address"] or "", "amount": None, "ref": ("saved_items", r["id"])})
    return out


def week_summary(con, today=None):
    """(count, {kind: n}) of items added in the last 7 days, private ones left out."""
    today = today or dates.today()
    since = (today - dt.timedelta(days=6)).isoformat()
    try:
        rs = con.execute("SELECT kind, COUNT(*) FROM saved_items WHERE audience<>'private' AND substr(added_at,1,10) >= ? "
                         "GROUP BY kind ORDER BY 2 DESC, 1", (since,)).fetchall()
    except sqlite3.OperationalError as e:
        _missing(e)
        return 0, {}
    by = {k: n for k, n in rs}
    return sum(by.values()), by


def week_line(con, today=None):
    n, by = week_summary(con, today)
    if not n:
        return None
    return f"Saved this week: {n} (" + ", ".join(f"{k} {kd}{'s' if k != 1 else ''}" for kd, k in by.items()) + ")."


def _md(s):
    for a, b in (("[", "("), ("]", ")"), ("`", "'"), ("*", "-"), ("_", " "), ("<", "("), (">", ")")):
        s = s.replace(a, b)
    return s


def brief_md(con, today=None):
    """Pinned FAMILY items (adults-only and private left out) as markdown for the phone, or None."""
    today = today or dates.today()
    try:
        rs = [r for r in search(con, today=today) if r["pinned"] and r["audience"] == "family"]
    except sqlite3.OperationalError as e:
        _missing(e)
        return None
    if not rs:
        return None
    out = [f"# Saved ({today:%a %b %d})", ""]
    for r in rs:
        line = f"- **{_md(r['title'])}** ({r['kind']})"
        if r["url"]:
            line += f" <{r['url']}>"
        if r["place_address"]:
            line += f" · {_md(r['place_address'])}"
        if r["expires_on"]:
            line += f" · until {r['expires_on']}"
        out.append(line)
    return "\n".join(out) + "\n"


def write_brief(con=None, today=None):
    own = con is None
    con = con or db.connect(DB, readonly=True)
    try:
        md = brief_md(con, today)
    finally:
        if own:
            con.close()
    p = paths.BRIEF / "saved.md"
    if md is None:
        if p.exists():
            p.unlink()
        return None
    p.parent.mkdir(exist_ok=True)
    p.write_text(md, encoding="utf-8")
    return p


def bookmarks_html(rows):
    """Netscape bookmark file (every browser imports it): one folder per kind, tags kept."""
    out = ["<!DOCTYPE NETSCAPE-Bookmark-file-1>", '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">',
           f"<TITLE>{brand.PRODUCT} saved items</TITLE>", f"<H1>{brand.PRODUCT} saved items</H1>", "<DL><p>"]
    by = {}
    for r in rows:
        if r.get("url"):
            by.setdefault(r["kind"], []).append(r)
    for kind in sorted(by):
        out += [f"    <DT><H3>{html.escape(kind)}</H3>", "    <DL><p>"]
        for r in by[kind]:
            try:
                add_date = int(dt.datetime.fromisoformat(r["added_at"]).timestamp())
            except (TypeError, ValueError):
                add_date = 0
            out.append(f'        <DT><A HREF="{html.escape(r["url"], quote=True)}" ADD_DATE="{add_date}" '
                       f'TAGS="{html.escape(r.get("tags") or "", quote=True)}">{html.escape(r["title"])}</A>')
            if r.get("body"):
                out.append(f"        <DD>{html.escape(r['body'][:500])}")
        out.append("    </DL><p>")
    out.append("</DL><p>")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- terminal
def _line(r):
    flags = ("* " if r["pinned"] else "  ") + f"[{r['id']}] {r['kind']:<7} {r['title']}"
    bits = [r["url"] or "", r["place_address"] or "", f"until {r['expires_on']}" if r["expires_on"] else "",
            ("#" + " #".join(r["tag_list"])) if r["tag_list"] else "",
            {"family": "", "adults": "[adults only]", "private": f"[private: {r['owner']}]"}[r["audience"]],
            "[archived]" if r["status"] == "archived" else ""]
    return flags + "".join(f"  {b}" for b in bits if b)


def main():
    ap = argparse.ArgumentParser(description="Saved links, notes, places and deals")
    ap.add_argument("cmd", choices=["add", "find", "show", "tag", "pin", "archive", "recent", "deals", "brief"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--url")
    ap.add_argument("--kind", choices=KINDS)
    ap.add_argument("--note")
    ap.add_argument("--tags")
    ap.add_argument("--tag")
    ap.add_argument("--where")
    ap.add_argument("--until")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--adults", action="store_true", help="add: hidden from the kid / guest screen")
    g.add_argument("--private", action="store_true", help="add: only the person named with --by sees it on the dashboard")
    ap.add_argument("--by", help="add: who saved it (needed with --private)")
    ap.add_argument("--off", action="store_true", help="pin: unpin")
    ap.add_argument("--all", action="store_true")
    a, extra = ap.parse_known_args()
    if a.cmd == "tag":  # "-x" would look like an option to argparse
        a.args += extra
    elif extra:
        ap.error("unrecognized arguments: " + " ".join(extra))
    today = dates.today()
    if a.cmd == "brief":
        p = write_brief(today=today)
        print(f"wrote {paths.rel(p)}" if p else "nothing pinned for the family; no brief/saved.md")
        return
    con = db.connect(DB)
    try:
        if a.cmd == "add":
            if len(a.args) != 1:
                raise ValueError('need "<title>"')
            by = None
            if a.by:
                import members as mem
                by = mem.resolve(con, a.by)
                if by not in mem.names(con):
                    raise ValueError(f"--by: '{a.by}' is not a family member")
            aud = "private" if a.private else "adults" if a.adults else "family"
            iid, added = add(con, a.args[0], a.url, a.kind, a.note, a.tags, a.where, a.until, aud, by)
            con.commit()
            r = get(con, iid)
            print(("saved: " if added else "already saved: ") + _line(r).strip())
            return
        if a.cmd in ("find", "recent", "deals"):
            if a.cmd == "find":
                rs = search(con, " ".join(a.args), a.kind, a.tag, today=today, all=a.all)
            elif a.cmd == "deals":
                rs = deals(con, today=today)
            else:
                n = int(a.args[0]) if a.args and a.args[0].isdigit() else 10
                rs = search(con, today=today, all=a.all, limit=n)
            for r in rs:
                print(_line(r))
            if not rs:
                print("nothing found" + ("" if a.all or a.cmd != "find" else " (archived items and ended deals: add --all)"))
            return
        if not a.args or not str(a.args[0]).isdigit():
            raise ValueError("need the item number (python data/saved.py find ... shows it in [brackets])")
        iid = int(a.args[0])
        r = get(con, iid)
        if not r:
            raise ValueError(f"no saved item {iid}")
        if a.cmd == "show":
            opened(con, iid)
            con.commit()
            print(_line(r).strip())
            if r["body"]:
                print("\n" + r["body"])
            print(f"\nadded {r['added_at']}" + (f" by {r['owner']}" if r["owner"] else ""))
        elif a.cmd == "tag":
            ops = a.args[1:]
            bad = [o for o in ops if o[:1] not in "+-" or len(o) < 2]
            if not ops or bad:
                raise ValueError("tag ID +add -remove (each tag starts with + or -)")
            tags = set_tags(con, iid, [o[1:] for o in ops if o[0] == "+"], [o[1:] for o in ops if o[0] == "-"])
            con.commit()
            print("tags: " + (", ".join(tags) or "(none)"))
        elif a.cmd == "pin":
            pin(con, iid, not a.off)
            con.commit()
            print(("unpinned: " if a.off else "pinned: ") + r["title"])
        elif a.cmd == "archive":
            archive(con, iid)
            con.commit()
            print("archived: " + r["title"])
    except ValueError as e:
        raise SystemExit(str(e)) from None
    finally:
        con.close()


if __name__ == "__main__":
    main()
