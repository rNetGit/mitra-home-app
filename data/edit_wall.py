"""Validated edits for the Mitra Wall: children's routines (add, remove, tick) and the star rate (re-exported by
edit_actions.py). Adults add and remove routines and set the rate; a routine is ticked by an adult, by the child it
belongs to (signed in on their own page), or by a paired wall (wall.actor: a limited member named after the wall).
Every change goes to logs/edits.log by id, never by the text a child typed.
"""
import datetime as dt
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import config  # noqa: E402
import dates  # noqa: E402
import wall as W  # noqa: E402
from edit_core import EditError, _adult, _con, _log, _member_name, edits  # noqa: E402

MAX_ROUTINES = 40  # per child: a wall of tiles, not a task manager


def _id(value):
    v = str(value if value is not None else "").strip()
    if not (v.isascii() and v.isdigit()) or len(v) > 12:
        raise EditError("that job is no longer on the list")
    return int(v)


def _title(text):
    t = " ".join(str(text or "").split())
    if not t:
        raise EditError("name the job, for example Brush teeth")
    if len(t) > 60:
        raise EditError("keep the job under 60 characters")
    return t


@edits
def routine_add(actor, member, part, title, icon="star", stars=1, weekdays=""):
    _adult(actor)
    if part not in W.PARTS:
        raise EditError("pick morning, after school or evening")
    if icon not in W.ICONS:
        icon = "star"
    try:
        stars = int(stars)
    except (TypeError, ValueError):
        raise EditError("stars: a number from 1 to 5") from None
    if not 1 <= stars <= 5:
        raise EditError("stars: a number from 1 to 5")
    try:
        days = W.clean_weekdays(weekdays)
    except W.WallError as e:
        raise EditError(str(e)) from None
    text = _title(title)
    with _con() as con:
        who = _member_name(con, member)
        if not who:
            raise EditError("pick a child")
        if who not in W.children(con):
            raise EditError("routines are for children (adults and pets have none)")
        n = con.execute("SELECT COUNT(*) FROM routines WHERE member=? AND status='active'", (who,)).fetchone()[0]
        if n >= MAX_ROUTINES:
            raise EditError(f"{who} already has {MAX_ROUTINES} jobs; remove one first")
        sort = con.execute("SELECT COALESCE(MAX(sort), 0) + 1 FROM routines WHERE member=? AND part=?", (who, part)).fetchone()[0]
        rid = con.execute("INSERT INTO routines(member, part, title, icon, stars, weekdays, sort, created_at) "
                          "VALUES (?,?,?,?,?,?,?,?)",
                          (who, part, text, icon, stars, days, sort, dt.datetime.now().isoformat(timespec="seconds"))).lastrowid
        _log(actor, "routine_add", f"id={rid} member={who} part={part}")
    return f"Added '{text}' to {who}'s {W.PART_LABEL[part].lower()}."


@edits
def routine_drop(actor, routine_id):
    _adult(actor)
    with _con() as con:
        r = con.execute("SELECT id, member, title FROM routines WHERE id=? AND status='active'", (_id(routine_id),)).fetchone()
        if not r:
            raise EditError("that job is already gone")
        con.execute("UPDATE routines SET status='dropped' WHERE id=?", (r[0],))
        _log(actor, "routine_drop", f"id={r[0]}")
    return f"Removed '{r[2]}' from {r[1]}'s jobs (the stars already earned stay)."


@edits
def routine_tick(actor, routine_id, done=True, day=None):
    """Tick (or untick) a routine for today. Adults, the child it belongs to, or a paired wall."""
    a = actor or {}
    day = day or dates.today()
    with _con() as con:
        r = con.execute("SELECT id, member, title FROM routines WHERE id=? AND status='active'", (_id(routine_id),)).fetchone()
        if not r:
            raise EditError("that job is no longer on the list")
        if a.get("role") != "adult" and not a.get("wall") and a.get("name") != r[1]:
            raise EditError("only that child, an adult or the Mitra Wall can tick this")
        try:
            changed = W.tick(con, r[0], day, a.get("name"), done)
        except W.WallError as e:
            raise EditError(str(e)) from None
        if changed:
            _log(a, "routine_done" if done else "routine_undone", f"id={r[0]} day={day.isoformat()}")
    if not changed:
        return f"'{r[2]}' was already {'done' if done else 'not done'}."
    return f"{r[1]}: '{r[2]}' done." if done else f"{r[1]}: '{r[2]}' is back on the list."


@edits
def reward_add(actor, title, stars, member=""):
    """A reward children can ask for with their stars (adults): what it is, the stars it costs, one child or any child."""
    _adult(actor)
    t = " ".join(str(title or "").split())
    if not t:
        raise EditError("name the reward, for example 30 minutes of screen time")
    if len(t) > 60:
        raise EditError("keep the reward under 60 characters")
    try:
        stars = int(str(stars).strip())
    except (TypeError, ValueError):
        raise EditError(f"stars: a number from 1 to {W.REWARD_MAX_STARS}") from None
    if not 1 <= stars <= W.REWARD_MAX_STARS:
        raise EditError(f"stars: a number from 1 to {W.REWARD_MAX_STARS}")
    with _con() as con:
        who = None
        if str(member or "").strip():
            who = _member_name(con, member)
            if not who or who not in W.children(con):
                raise EditError("pick a child, or leave it for any child")
        n = con.execute("SELECT COUNT(*) FROM rewards WHERE status='active'").fetchone()[0]
        if n >= W.MAX_REWARDS:
            raise EditError(f"there are {W.MAX_REWARDS} rewards already; remove one first")
        rid = con.execute("INSERT INTO rewards(title, stars, member, status, created_at) VALUES (?,?,?, 'active', ?)",
                          (t, stars, who, dt.datetime.now().isoformat(timespec="seconds"))).lastrowid
        _log(actor, "reward_add", f"id={rid}")
    return f"Added the reward '{t}' ({stars} stars)" + (f" for {who}." if who else ".")


@edits
def reward_drop(actor, reward_id):
    _adult(actor)
    with _con() as con:
        r = con.execute("SELECT id, title FROM rewards WHERE id=? AND status='active'", (_id(reward_id),)).fetchone()
        if not r:
            raise EditError("that reward is already gone")
        con.execute("UPDATE rewards SET status='dropped' WHERE id=?", (r[0],))
        con.execute("UPDATE reward_claims SET status='declined', decided_at=?, decided_by=? WHERE reward_id=? AND status='asked'",
                    (dt.datetime.now().isoformat(timespec="seconds"), actor.get("name") or None, r[0]))
        _log(actor, "reward_drop", f"id={r[0]}")
    return f"Removed the reward '{r[1]}' (a request for it that was waiting gets its stars back)."


@edits
def reward_ask(actor, reward_id, member):
    """A child asks for a reward: the child themself (signed in), a paired wall, or an adult for them. The stars are held
    until an adult answers; there must be enough, and one request per reward waits at a time."""
    a = actor or {}
    with _con() as con:
        who = _member_name(con, member)
        if not who or who not in W.children(con):
            raise EditError("pick the child asking")
        if a.get("role") != "adult" and not a.get("wall") and a.get("name") != who:
            raise EditError("only that child, an adult or the Mitra Wall can ask for this")
        r = con.execute("SELECT id, title, stars, member FROM rewards WHERE id=? AND status='active'",
                        (_id(reward_id),)).fetchone()
        if not r or (r[3] and r[3] != who):
            raise EditError("that reward is not on the list")
        if con.execute("SELECT 1 FROM reward_claims WHERE reward_id=? AND member=? AND status='asked'", (r[0], who)).fetchone():
            return f"{who} already asked for '{r[1]}'. A grown-up will answer."
        bal = W.star_balance(con, who)
        if bal < r[2]:
            raise EditError(f"{who} has {bal} star{'s' if bal != 1 else ''}; '{r[1]}' takes {r[2]}")
        cid = con.execute("INSERT INTO reward_claims(reward_id, member, stars, status, asked_at, asked_by) "
                          "VALUES (?,?,?, 'asked', ?, ?)",
                          (r[0], who, r[2], dt.datetime.now().isoformat(timespec="seconds"), a.get("name") or None)).lastrowid
        _log(a, "reward_ask", f"id={cid} reward={r[0]}")
    return f"{who} asked for '{r[1]}'. A grown-up will answer."


@edits
def reward_decide(actor, claim_id, give):
    """An adult answers a request: give (the stars are spent) or not now (the stars come back)."""
    _adult(actor)
    with _con() as con:
        c = con.execute("SELECT c.id, c.member, w.title, c.stars FROM reward_claims c JOIN rewards w ON w.id=c.reward_id "
                        "WHERE c.id=? AND c.status='asked'", (_id(claim_id),)).fetchone()
        if not c:
            raise EditError("that request was already answered")
        con.execute("UPDATE reward_claims SET status=?, decided_at=?, decided_by=? WHERE id=?",
                    ("given" if give else "declined", dt.datetime.now().isoformat(timespec="seconds"),
                     actor.get("name") or None, c[0]))
        _log(actor, "reward_given" if give else "reward_declined", f"id={c[0]}")
    if give:
        return f"Given: {c[1]} gets '{c[2]}' ({c[3]} stars spent)."
    return f"Not now: {c[1]}'s {c[3]} stars are back."


@edits
def goal_set(actor, member, title, stars):
    """A child's goal (one each): a title and the stars it takes, counted from today."""
    _adult(actor)
    t = " ".join(str(title or "").split())
    if not t:
        raise EditError("name the goal, for example New bike")
    if len(t) > 40:
        raise EditError("keep the goal under 40 characters")
    try:
        n = int(str(stars).strip())
    except (TypeError, ValueError):
        raise EditError(f"stars: a whole number from 1 to {W.GOAL_MAX_STARS}") from None
    if not 1 <= n <= W.GOAL_MAX_STARS:
        raise EditError(f"stars: a whole number from 1 to {W.GOAL_MAX_STARS}")
    with _con() as con:
        who = _member_name(con, member)
        if not who or who not in W.children(con):
            raise EditError("pick a child")
    with config.family_edit() as cfg:
        wall = cfg.setdefault("wall", {})
        wall.setdefault("goals", {})[who] = {"title": t, "stars": n, "since": dates.today().isoformat()}
    _log(actor, "goal_set", f"member={who} stars={n}")
    return f"{who}'s goal: {t}, {n} stars from today."


@edits
def goal_clear(actor, member):
    _adult(actor)
    with config.family_edit() as cfg:
        g = (cfg.get("wall") or {}).get("goals") or {}
        if member not in g:
            raise EditError("there is no goal to clear")
        del g[member]
    _log(actor, "goal_clear", f"member={member}")
    return f"{member}'s goal is cleared (the stars stay)."


@edits
def allowance_budget_set(actor, member):
    """Put the most a child can earn from stars in a month into the budget line allowance:<child>."""
    _adult(actor)
    with _con() as con:
        who = _member_name(con, member)
        if not who or who not in W.children(con):
            raise EditError("pick a child")
        top = W.week_max_stars(W.routines(con, who))
        if not top:
            raise EditError(f"{who} has no jobs yet")
        monthly = round(top * W.star_cents() * W.WEEKS_PER_MONTH / 100, 2)
        category = "allowance:" + who  # budget.py's allowance line (written here: edit_money would join an import cycle)
        con.execute("INSERT INTO budget(category, monthly_limit) VALUES (?,?) "
                    "ON CONFLICT(category) DO UPDATE SET monthly_limit=excluded.monthly_limit", (category, monthly))
        _log(actor, "budget_set", f"category={category}")
    from money import fmt
    return f"{who}'s allowance line in the budget: {fmt(monthly, 2)} a month (every job done)."


@edits
def star_rate_set(actor, cents):
    _adult(actor)
    try:
        c = int(cents)
    except (TypeError, ValueError):
        raise EditError("cents per star: a whole number from 0 to 500") from None
    if not 0 <= c <= 500:
        raise EditError("cents per star: a whole number from 0 to 500")
    with config.family_edit() as cfg:
        cfg["wall"] = {**(cfg.get("wall") or {}), "star_cents": c}
    _log(actor, "star_rate_set", f"cents={c}")
    return f"Each star is worth {c}¢ now." if c else "Stars no longer add allowance."


# ---- the wall's resting screen: clock face, photos, schedule (data/wall_screen.py) ---------------------------------
@edits
def wall_screen_set(actor, clock, photos, photo_seconds, clock_seconds, per_turn, photos_from, photos_to, night_from,
                    night_to, night_tone="dim", zone="", photo_style="", tabs=(), clock_only=False, theme="", rotate_seconds=0,
                    led=None):
    """The resting screen: the clock face, the night clock's colour, photos on or off, how long each shows and the hours;
    `tabs` = the optional wall pages (Chores, Meals) to show; `led` = the LED clock's choices (wall_screen.clean)."""
    import wall_screen as WS
    _adult(actor)
    try:
        s = WS.clean(clock, photos, photo_seconds, clock_seconds, per_turn, photos_from, photos_to, night_from, night_to,
                     night_tone, zone, photo_style, tabs, clock_only, theme, rotate_seconds, led)
    except WS.ScreenError as e:
        raise EditError(str(e)) from None
    with config.family_edit() as cfg:
        cfg["wall"] = {**(cfg.get("wall") or {}), "screen": s}
    _log(actor, "wall_screen_set", "fields=" + ",".join(sorted(s)))
    return (f"Saved: {WS.FACE_NAMES[s['clock']]} clock" + (f", photos {s['photos_from']}-{s['photos_to']}" if s["photos"] else ", no photos")
            + f", night {s['night_from']}-{s['night_to']} ({s['night_tone']}).")


@edits
def wall_seasonal_set(actor, on):
    """Seasonal wall looks on or off for every wall (family.json wall.seasonal)."""
    _adult(actor)
    with config.family_edit() as cfg:
        cfg["wall"] = {**(cfg.get("wall") or {}), "seasonal": bool(on)}
    _log(actor, "wall_seasonal_set", "on" if on else "off")
    return "Seasonal looks are on: the wall dresses for festivals and holidays on your calendar (Diwali, Holi, Christmas and more)." if on else "Seasonal looks are off."


@edits
def wall_screen_own_set(actor, wall_id, own, clock="", photos=False, photo_seconds="", clock_seconds="", per_turn="",
                        photos_from="", photos_to="", night_from="", night_to="", night_tone="dim", zone="",
                        photo_style="", tabs=(), clock_only=False, theme="", rotate_seconds=0, led=None):
    """One wall's own resting screen (walls.screen, migration 064), or `own` false = back to the household's."""
    import wall_screen as WS
    _adult(actor)
    v = str(wall_id if wall_id is not None else "").strip()
    if not (v.isascii() and v.isdigit()) or len(v) > 12:
        raise EditError("that wall is no longer paired")
    s = None
    if own:
        try:
            s = WS.clean(clock, photos, photo_seconds, clock_seconds, per_turn, photos_from, photos_to, night_from,
                         night_to, night_tone, zone, photo_style, tabs, clock_only, theme, rotate_seconds, led)
        except WS.ScreenError as e:
            raise EditError(str(e)) from None
    with _con() as con:
        r = con.execute("SELECT name FROM walls WHERE id=? AND revoked_at IS NULL", (int(v),)).fetchone()
        if not r or not WS.set_own(con, int(v), s):
            raise EditError("that wall is no longer paired")
        name = r[0]
    _log(actor, "wall_screen_own_set", f"wall {v} " + ("fields=" + ",".join(sorted(s)) if s else "household"))
    if not s:
        return f"{name} follows the household's wall screen again."
    return (f"Saved for {name}: {WS.FACE_NAMES[s['clock']]} clock"
            + (f", photos {s['photos_from']}-{s['photos_to']}" if s["photos"] else ", no photos")
            + f", night {s['night_from']}-{s['night_to']} ({s['night_tone']}).")


@edits
def wall_photo_add(actor, name, data):
    """One photo for the wall, made here without its EXIF (location) and at most 1920 pixels a side."""
    import wall_screen as WS
    _adult(actor)
    try:
        fname = WS.add_photo(name, data)
    except WS.ScreenError as e:
        raise EditError(str(e)) from None
    _log(actor, "wall_photo_add", f"photo={fname}")
    return "Photo added to the wall."


@edits
def wall_photo_remove(actor, name):
    import wall_screen as WS
    _adult(actor)
    if not WS.remove_photo(name):
        raise EditError("that photo is no longer on the wall")
    _log(actor, "wall_photo_remove", f"photo={name}")
    return "Photo removed from the wall."


@edits
def wall_face_set(actor, clock):
    """The clock face picked on the wall itself (the wall's own screen; a wall without one starts from the household's)."""
    import wall_screen as WS
    wid = (actor or {}).get("wall")
    if not wid:
        raise EditError("pick the face on the wall, or in Settings > Phones > Walls")
    if clock not in WS.FACES:
        raise EditError("pick one of the faces in the list")
    with _con() as con:
        s = WS.settings(wall_id=wid)
        s["clock"] = clock
        if not WS.set_own(con, wid, s):
            raise EditError("this wall is no longer paired")
    _log(actor, "wall_face_set", f"wall {wid} clock={clock}")
    return f"The wall shows the {WS.FACE_NAMES[clock]} clock now."


@edits
def wall_photo_style_set(actor, style):
    """The photo look picked on the wall itself (Display menu): saved in that wall's own screen, like the clock face."""
    import wall_screen as WS
    wid = (actor or {}).get("wall")
    if not wid:
        raise EditError("pick the photo look on the wall, or in Settings > Phones > Walls")
    if style not in WS.STYLES:
        raise EditError("pick one of the photo looks in the list")
    with _con() as con:
        s = WS.settings(wall_id=wid)
        s["photo_style"] = style
        if not WS.set_own(con, wid, s):
            raise EditError("this wall is no longer paired")
    _log(actor, "wall_photo_style_set", f"wall {wid} style={style}")
    return f"The wall shows photos with {WS.STYLE_NAMES[style]} now."
