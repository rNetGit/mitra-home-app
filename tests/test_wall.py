"""The Mitra Wall (data/wall.py, data/edit_wall.py, migration 060): one-time pairing codes, wall tokens, revoke; children's
routines by part of the day, ticks once a day, stars of the week and the allowance rate; who may change what."""
import datetime as dt

import pytest

NOW = dt.datetime(2026, 10, 18, 9, 0, 0)  # a Sunday
ADULT = {"name": "Alex", "role": "adult"}
SAM = {"name": "Sam", "role": "limited"}


@pytest.fixture()
def W(modules):
    return modules("wall")


@pytest.fixture()
def con(W):
    c = W._con()
    c.execute("DELETE FROM routine_done")
    c.execute("DELETE FROM routines")
    c.execute("DELETE FROM wall_pairings")
    c.execute("DELETE FROM walls")
    c.commit()
    yield c
    c.close()


# ---- pairing ----------------------------------------------------------------------------------------------------
def test_codes_are_unambiguous_and_typed_any_way(W):
    assert set(W.CODE_ALPHABET).isdisjoint(set("01OIL"))
    assert W.clean_code("ab23-cd45") == "AB23CD45" and W.clean_code(" ab23 cd45 ") == "AB23CD45"
    for bad in ("", "AB23CD4", "AB23CD450", "AB23CD4O", "AB23-CD4I", None):
        assert W.clean_code(bad) == "", bad
    assert W.pretty_code("AB23CD45") == "AB23-CD45"


def test_a_code_pairs_one_wall_once_before_it_expires(W, con):
    with pytest.raises(W.WallError):
        W.pair_start(con, "   ", now=NOW)
    code, info = W.pair_start(con, "Kitchen  wall", by="Alex", now=NOW)
    assert info["name"] == "Kitchen wall" and len(code) == 8
    assert code not in str(con.execute("SELECT * FROM wall_pairings").fetchall()), "only the hash is stored"
    assert W.pair_redeem(con, "ZZZZZZZZ", now=NOW) is None
    late = NOW + dt.timedelta(minutes=W.PAIR_MINUTES, seconds=1)
    assert W.pair_redeem(con, code, now=late) is None, "expired"
    code, _ = W.pair_start(con, "Kitchen wall", now=NOW)
    token, w = W.pair_redeem(con, W.pretty_code(code).lower(), now=NOW)
    assert w["name"] == "Kitchen wall" and len(token) == W.TOKEN_LEN
    assert W.pair_redeem(con, code, now=NOW) is None, "a code works once"
    assert token not in str(con.execute("SELECT * FROM walls").fetchall()), "only the token's hash is stored"
    assert W.authenticate(con, token, now=NOW) == {"id": w["id"], "name": "Kitchen wall", "kind": "browser"}
    assert W.authenticate(con, "x" * W.TOKEN_LEN, now=NOW) is None and W.authenticate(con, "short", now=NOW) is None
    assert W.actor(w) == {"name": "Kitchen wall", "role": "limited", "wall": w["id"]}
    assert W.revoke(con, w["id"]) and not W.revoke(con, w["id"])
    assert W.authenticate(con, token, now=NOW) == {"revoked": True}
    assert W.listing(con) == []


def test_a_new_code_cancels_the_old_one_and_walls_are_capped(W, con):
    first, _ = W.pair_start(con, "Hall", now=NOW)
    second, _ = W.pair_start(con, "Hall", now=NOW)
    assert W.pair_redeem(con, first, now=NOW) is None and W.pair_redeem(con, second, now=NOW)
    for i in range(W.MAX_WALLS - 1):
        c, _ = W.pair_start(con, f"Wall {i}", now=NOW)
        assert W.pair_redeem(con, c, now=NOW)
    with pytest.raises(W.WallError, match="Remove one first"):
        W.pair_start(con, "One too many", now=NOW)


# ---- routines and stars -----------------------------------------------------------------------------------------
def test_routines_are_for_children_and_only_adults_change_them(modules, W, con):
    ea = modules("edit_actions")
    assert W.children(con) == ["Sam"], "adults and pets have no routines"
    ok, msg = ea.routine_add(SAM, "Sam", "morning", "Brush teeth")
    assert not ok and "adult" in msg
    for args, words in ((("Alex", "morning", "Run"), "children"), (("Biscuit", "morning", "Sit"), "children"),
                        (("Nobody", "morning", "X"), "not a family member"), (("Sam", "noon", "X"), "pick morning"),
                        (("Sam", "morning", ""), "name the job"), (("Sam", "morning", "x" * 61), "60 characters")):
        ok, msg = ea.routine_add(ADULT, *args)
        assert not ok and words in msg, (args, msg)
    assert not ea.routine_add(ADULT, "Sam", "morning", "Bed", stars=9)[0]
    assert not ea.routine_add(ADULT, "Sam", "morning", "Bed", weekdays="XX")[0]
    ok, msg = ea.routine_add(ADULT, "sam", "morning", "Make  the bed", icon="bed", stars=1)
    assert ok and msg == "Added 'Make the bed' to Sam's morning.", msg
    assert ea.routine_add(ADULT, "Sam", "afternoon", "Walk Biscuit", icon="paw", stars=2, weekdays="MO,TU,WE,TH,FR")[0]
    assert ea.routine_add(ADULT, "Sam", "evening", "Lights out", icon="not-an-icon")[0]
    rows = W.routines(con, "Sam")
    assert [(r["part"], r["title"], r["icon"], r["stars"]) for r in rows] == [
        ("morning", "Make the bed", "bed", 1), ("afternoon", "Walk Biscuit", "paw", 2), ("evening", "Lights out", "star", 1)]
    assert rows[1]["weekdays"] == "MO,TU,WE,TH,FR" and W.clean_weekdays("su,mo,tu,we,th,fr,sa") == ""


def test_ticks_count_once_a_day_and_add_up_to_the_week(modules, W, con):
    ea = modules("edit_actions")
    ea.routine_add(ADULT, "Sam", "morning", "Make the bed", icon="bed")
    ea.routine_add(ADULT, "Sam", "afternoon", "Walk Biscuit", icon="paw", stars=2, weekdays="MO,TU,WE,TH,FR")
    bed, walk = [r["id"] for r in W.routines(con, "Sam")]
    sunday, monday = NOW.date(), NOW.date() + dt.timedelta(days=1)
    wall = {"name": "Kitchen wall", "role": "limited", "wall": 1}
    assert not ea.routine_tick({"name": "Mia", "role": "limited"}, bed, day=sunday)[0], "another child cannot"
    ok, msg = ea.routine_tick(wall, bed, day=sunday)
    assert ok and msg == "Sam: 'Make the bed' done."
    assert ea.routine_tick(SAM, bed, day=sunday)[1] == "'Make the bed' was already done."
    ok, msg = ea.routine_tick(SAM, walk, day=sunday)
    assert not ok and "not for today" in msg, "walk is a weekday job"
    view = W.day_view(con, sunday, "morning")
    assert view[0]["name"] == "Sam" and (view[0]["done"], view[0]["total"]) == (1, 1)
    assert [r["title"] for r in view[0]["parts"]["afternoon"]] == [], "not on a Sunday"
    assert view[0]["stars_week"] == 1 and view[0]["cents_week"] == 25
    # Monday starts a new week: Sunday's star belongs to the week before
    assert ea.routine_tick(ADULT, walk, day=monday)[0]
    assert W.stars_between(con, "Sam", W.week_start(monday), W.week_start(monday) + dt.timedelta(days=6)) == 2
    assert ea.routine_tick(wall, walk, done=False, day=monday)[1] == "Sam: 'Walk Biscuit' is back on the list."
    # a dropped job keeps the stars already earned
    assert ea.routine_drop(ADULT, bed)[0] and not ea.routine_drop(ADULT, bed)[0]
    assert W.stars_between(con, "Sam", W.week_start(sunday), sunday) == 1
    assert not ea.routine_tick(wall, bed, day=sunday)[0], "a removed job cannot be ticked"
    log = (W.paths.LOGS / "edits.log").read_text(encoding="utf-8")
    assert "routine_done\tid=" in log or "\troutine_done\t" in log


def test_star_rate_is_set_by_adults_and_kept_in_bounds(modules, W):
    ea = modules("edit_actions")
    assert not ea.star_rate_set(SAM, 50)[0]
    assert not ea.star_rate_set(ADULT, 501)[0] and not ea.star_rate_set(ADULT, "lots")[0]
    assert ea.star_rate_set(ADULT, 10) == (True, "Each star is worth 10¢ now.")
    assert W.star_cents() == 10
    assert ea.star_rate_set(ADULT, 0)[1] == "Stars no longer add allowance."
    ea.star_rate_set(ADULT, 25)


def test_part_of_the_day(W):
    assert [W.part_of(dt.datetime(2026, 10, 18, h)) for h in (6, 11, 12, 16, 17, 22)] == [
        "morning", "morning", "afternoon", "afternoon", "evening", "evening"]


def test_a_goal_counts_stars_from_the_day_it_was_set(modules, W, con):
    ea, dates = modules("edit_actions"), modules("dates")
    today = dates.today()
    ea.routine_add(ADULT, "Sam", "morning", "Brush teeth", stars=3)
    rid = W.routines(con, "Sam")[0]["id"]
    W.tick(con, rid, today - dt.timedelta(days=1), "Sam")  # before the goal: does not count
    con.commit()
    assert not ea.goal_set(SAM, "Sam", "Bike", 10)[0], "adults only"
    assert not ea.goal_set(ADULT, "Alex", "Bike", 10)[0], "children only"
    for bad in ("", "x" * 41):
        assert not ea.goal_set(ADULT, "Sam", bad, 10)[0]
    for bad in (0, W.GOAL_MAX_STARS + 1, "lots"):
        assert not ea.goal_set(ADULT, "Sam", "Bike", bad)[0]
    ok, msg = ea.goal_set(ADULT, "Sam", "  New   bike ", 4)
    assert ok and msg == "Sam's goal: New bike, 4 stars from today."
    g = W.goal_view(con, "Sam", today)
    assert (g["title"], g["earned"], g["left"], g["pct"], g["reached"]) == ("New bike", 0, 4, 0, False)
    W.tick(con, rid, today, "Sam")
    con.commit()
    g = W.goal_view(con, "Sam", today)
    assert (g["earned"], g["left"], g["pct"], g["reached"]) == (3, 1, 75, False)
    assert W.day_view(con, today)[0]["goal"]["earned"] == 3
    assert ea.goal_clear(ADULT, "Sam")[0] and W.goal_view(con, "Sam", today) is None
    assert not ea.goal_clear(ADULT, "Sam")[0]


def test_a_goal_follows_a_rename(modules, W, con):
    ea = modules("edit_actions")
    con.execute("INSERT OR IGNORE INTO members(name, role) VALUES ('Robin', 'child')")
    con.commit()
    assert ea.goal_set(ADULT, "Robin", "Skates", 50)[0]
    assert ea.member_update(ADULT, "Robin", new_name="Robbie")[0]
    assert "Robbie" in W.goals() and "Robin" not in W.goals()


def test_the_allowance_line_is_every_job_done_for_a_month(modules, W, con):
    ea = modules("edit_actions")
    assert not ea.allowance_budget_set(ADULT, "Sam")[0], "no jobs yet"
    ea.routine_add(ADULT, "Sam", "morning", "Make the bed", stars=1)                        # 7 a week
    ea.routine_add(ADULT, "Sam", "afternoon", "Piano", stars=2, weekdays="MO,WE")            # 4 a week
    assert W.week_max_stars(W.routines(con, "Sam")) == 11
    assert not ea.allowance_budget_set(SAM, "Sam")[0]
    ok, msg = ea.allowance_budget_set(ADULT, "Sam")
    want = round(11 * W.star_cents() * 52 / 12 / 100, 2)
    assert ok and f"{want:,.2f} a month" in msg
    assert con.execute("SELECT monthly_limit FROM budget WHERE category='allowance:Sam'").fetchone()[0] == want
    v = next(k for k in W.manage(con, NOW.date())["children"] if k["name"] == "Sam")
    assert (v["max_week"], v["max_month"]) == (11, want)
