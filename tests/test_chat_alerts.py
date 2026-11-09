"""Daily chat alerts (migration 034 + chat_core.alert_text/set_alerts + data/chat_alerts.py): opt-in only, /alerts on
only in private, adult text with amounts, kid text never money, nothing due -> no message, once a day per account,
a failed send is logged without text and does not stop the others, Telegram + Discord REST senders, daily task wired."""
import datetime as D
import http.server
import json
import os
import threading

import pytest

from conftest import SRC, db, q, run

NOW = D.datetime(2026, 10, 9, 7, 0, 0)
TODAY = NOW.date()


@pytest.fixture(scope="module")
def C(root, modules):
    return modules("chat_core")


@pytest.fixture(scope="module")
def A(root, modules):
    return modules("chat_alerts")


@pytest.fixture(scope="module")
def dbp(root):
    return root / "data" / "family.db"


@pytest.fixture(scope="module")
def setup(C, root, dbp):
    c = db(root)
    c.execute("INSERT INTO bills(name, vendor, amount, due_date, status) VALUES ('Gas','FlameCo',61.50,?, 'due')",
              ((TODAY + D.timedelta(days=2)).isoformat(),))
    c.execute("INSERT INTO life_items(domain, title, member, due_date, status) VALUES ('school','Field trip form','Sam',?, 'open')",
              ((TODAY + D.timedelta(days=1)).isoformat(),))
    c.commit()
    c.close()
    con = C._con(dbp)
    try:
        for name, uid, plat in (("Alex", "10", "telegram"), ("Sam", "20", "telegram"), ("Alex", "30", "discord")):
            code, *_ = C.invite(con, name, now=NOW)
            assert "linked" in C.handle(plat, uid, f"/start {code}", db=dbp, now=NOW)
    finally:
        con.close()


def H(C, dbp, uid, text, private=True, platform="telegram"):
    return C.handle(platform, uid, text, private=private, db=dbp, now=NOW)


def test_column_added_off_by_default(root, setup):
    assert q(root, "select count(*) from chat_links where alerts=1")[0][0] == 0


def test_opt_in_commands(C, dbp, setup):
    assert "off" in H(C, dbp, "10", "/alerts")
    assert "private chat" in H(C, dbp, "10", "/alerts on", private=False)
    assert "Alerts on" in H(C, dbp, "10", "/alerts on")
    assert "Alerts are on" in H(C, dbp, "10", "/alerts")
    assert "Alerts off" in H(C, dbp, "10", "/alerts off", private=False)  # turning off works anywhere
    assert "Alerts on" in H(C, dbp, "10", "/alerts on")
    assert "Alerts on" in H(C, dbp, "20", "/alerts on")


def test_nobody_without_opt_in_gets_anything(A, C, dbp, setup):
    sent = []
    res = A.send(today=TODAY, senders={"telegram": lambda u, t: sent.append((u, t)), "discord": lambda u, t: sent.append((u, t))},
                 db=dbp, now=NOW)
    assert {r[1] for r in res} <= {"Alex", "Sam"} and "30" not in [u for u, _ in sent]


def test_adult_and_kid_text(C, dbp, setup):
    con = C._con(dbp)
    try:
        adult = C.alert_text(con, {"member": "Alex", "role": "adult"}, TODAY, dbp)
        kid = C.alert_text(con, {"member": "Sam", "role": "limited"}, TODAY, dbp)
        far = C.alert_text(con, {"member": "Sam", "role": "limited"}, TODAY - D.timedelta(days=30), dbp)
    finally:
        con.close()
    assert "FlameCo" in adult and "$61.50" in adult and "Good morning Alex" in adult
    assert "Field trip form" in kid and "FlameCo" not in kid and "$" not in kid
    assert far is None


def test_send_once_per_day_and_failures(A, C, dbp, root, setup):
    c = db(root)
    c.execute("DELETE FROM chat_log WHERE command='alert'")
    c.commit()
    c.close()
    sent = []
    s = {"telegram": lambda u, t: sent.append((u, t)), "discord": lambda u, t: sent.append((u, t))}
    res = A.send(today=TODAY, senders=s, db=dbp, now=NOW)
    assert ("telegram", "Alex", "sent") in res and ("telegram", "Sam", "sent") in res
    kid = [t for u, t in sent if u == "20"][0]
    assert "$" not in kid and "FlameCo" not in kid
    again = A.send(today=TODAY, senders=s, db=dbp, now=NOW + D.timedelta(hours=1))
    assert all(r[2] == "already_sent" for r in again) and len(sent) == 2

    def boom(u, t):
        raise OSError("network down")
    tomorrow = NOW + D.timedelta(days=1)
    res = A.send(today=tomorrow.date(), senders={"telegram": boom}, db=dbp, now=tomorrow)
    assert {r[2] for r in res} == {"failed"}
    rows = q(root, "select outcome from chat_log where command='alert' and substr(at,1,10)=?", tomorrow.date().isoformat())
    assert rows and all(r[0] == "error" for r in rows)
    dump = " ".join(str(x) for r in q(root, "select * from chat_log") for x in r)
    assert "FlameCo" not in dump and "Field trip" not in dump


def test_nothing_due_no_message_and_no_bot(A, C, dbp, setup):
    sent = []
    past = TODAY - D.timedelta(days=60)
    res = A.send(today=past, senders={"telegram": lambda u, t: sent.append(u)}, db=dbp, now=NOW - D.timedelta(days=60))
    assert ("telegram", "Sam", "nothing_due") in res and "20" not in sent
    con = C._con(dbp)
    try:
        C.set_alerts(con, "Alex", True)  # discord link too
    finally:
        con.close()
    res = A.send(today=TODAY + D.timedelta(days=2), senders={}, db=dbp, now=NOW + D.timedelta(days=2))
    assert ("discord", "Alex", "no_bot") in res


def test_revoked_link_gets_nothing(A, C, dbp, setup):
    con = C._con(dbp)
    try:
        code, *_ = C.invite(con, "Alex", now=NOW)
    finally:
        con.close()
    C.handle("telegram", "40", f"/start {code}", db=dbp, now=NOW)
    H(C, dbp, "40", "/alerts on")
    H(C, dbp, "40", "/unlink")
    sent = []
    A.send(today=TODAY + D.timedelta(days=3), senders={"telegram": lambda u, t: sent.append(u), "discord": lambda u, t: None},
           db=dbp, now=NOW + D.timedelta(days=3))
    assert "40" not in sent


class FakeDiscord:
    def __init__(self):
        self.posts = []
        state = self

        class Hd(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
                state.posts.append((self.path, body, self.headers.get("Authorization")))
                out = {"id": "777"} if self.path == "/users/@me/channels" else {"id": "1"}
                data = json.dumps(out).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Hd)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_port}"


def test_discord_send_dm_rest(root, modules, monkeypatch):
    f = FakeDiscord()
    monkeypatch.setenv("MITRAHOME_DISCORD_API", f.base)
    Dm = modules("chat_discord")
    Dm.send_dm("TOK", "1234", "hello @everyone")
    f.srv.shutdown()
    assert f.posts[0][0] == "/users/@me/channels" and f.posts[0][1] == {"recipient_id": "1234"}
    assert f.posts[1][0] == "/channels/777/messages" and f.posts[1][1]["allowed_mentions"] == {"parse": []}
    assert f.posts[1][2] == "Bot TOK"
    with pytest.raises(Dm.DiscordError):
        Dm.send_dm("TOK", "not-an-id", "x")


def test_cli_and_daily_task_wired(root, setup):
    r = run(["data/chat_core.py", "alerts", "Sam", "on"], root)
    assert r.returncode == 0 and "alerts on" in r.stdout
    assert run(["data/chat_core.py", "alerts", "Nobody", "on"], root).returncode == 1
    assert "alerts on" in run(["data/chat_core.py", "links"], root).stdout
    r = run(["data/chat_alerts.py", "send", "--dry-run"], root,
            env={"MITRAHOME_TELEGRAM_TOKEN": "", "MITRAHOME_DISCORD_TOKEN": ""})
    assert r.returncode == 0
    assert run(["data/chat_alerts.py", "preview", "Sam"], root).returncode == 0
    rt = (SRC / "tasks" / "run_task.py").read_text(encoding="utf-8")
    assert '"data/chat_alerts.py", "send"' in rt
    assert "/alerts on" in (SRC / "docs" / "CHAT.md").read_text(encoding="utf-8")


def test_env_clean():
    assert "MITRAHOME_DISCORD_API" not in os.environ or os.environ["MITRAHOME_DISCORD_API"].startswith("http://127.0.0.1")
