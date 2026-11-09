"""The mail folder (data/mail_folder.py): a Mitra-only mailbox read-only over IMAP with an app password; attachments and
texts to the inbox with the upload checks; nothing in the mailbox changed; the password typed only on this PC."""
import email.message
import imaplib

import pytest

from test_webapp import _csrf, _login, _post, web  # noqa: F401 (the web fixture)

PDF = b"%PDF-1.4\n" + b"0" * 2000 + b"\n%%EOF"


def _msg(subject, sender, body, attach=None):
    m = email.message.EmailMessage()
    m["Subject"], m["From"], m["Date"] = subject, sender, "Mon, 19 Oct 2026 09:00:00 -0400"
    m.set_content(body)
    if attach:
        m.add_attachment(attach[1], maintype=attach[2], subtype=attach[3], filename=attach[0])
    return m.as_bytes()


MAILS = {b"1": _msg("Your bill", "billing@power.example", "See the attached bill.", ("bill.pdf", PDF, "application", "pdf")),
         b"2": _msg("Field trip on Friday", "office@school.example", "Please send the signed form and $12 by Thursday."),
         b"3": _msg("Logo only", "x@y.example", "hi", ("logo.png", b"\x89PNG\r\n\x1a\n" + b"0" * 100, "image", "png"))}


class FakeIMAP:
    calls = []
    password = "abcd efgh ijkl mnop".replace(" ", "")

    def __init__(self, host, port, ssl_context=None, timeout=None):
        assert ssl_context is not None and port == 993
        FakeIMAP.calls.append(("connect", host))

    def login(self, user, pw):
        FakeIMAP.calls.append(("login", user))
        if pw != FakeIMAP.password:
            raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")
        return "OK", [b"ok"]

    def select(self, folder, readonly=False):
        FakeIMAP.calls.append(("select", folder, readonly))
        return ("OK", [b"3"]) if folder == '"INBOX"' else ("NO", [b"no such"])

    def response(self, code):
        return "OK", [b"77"]

    def uid(self, cmd, *args):
        FakeIMAP.calls.append(("uid", cmd) + tuple(a for a in args if a))
        if cmd == "SEARCH":
            return "OK", [b" ".join(MAILS)]
        uid = args[0].encode() if isinstance(args[0], str) else args[0]
        if args[1] == "(RFC822.SIZE)":
            return "OK", [b"%s (UID %s RFC822.SIZE %d)" % (uid, uid, len(MAILS[uid]))]
        assert args[1] == "(BODY.PEEK[])", "messages are only ever peeked"
        return "OK", [(b"%s (UID %s BODY[] {%d}" % (uid, uid, len(MAILS[uid])), MAILS[uid]), b")"]

    def close(self):
        FakeIMAP.calls.append(("close",))

    def logout(self):
        FakeIMAP.calls.append(("logout",))


@pytest.fixture()
def mf(modules, monkeypatch):
    m = modules("mail_folder")
    config = modules("config")
    monkeypatch.setattr(m.imaplib, "IMAP4_SSL", FakeIMAP)
    monkeypatch.setattr(m, "_public", lambda host: host != "mail.local")
    FakeIMAP.calls = []
    m.STATE.unlink(missing_ok=True)
    config.write_secret(m.MAIL_SECRET, FakeIMAP.password)
    with config.family_edit() as cfg:
        cfg["mail_folder"] = {"enabled": True, "address": "riveras.mitra@gmail.com", "host": "imap.gmail.com", "port": 993,
                              "folder": "INBOX"}
    yield m
    config.write_secret(m.MAIL_SECRET, "")


def test_clean_settings_and_guess_the_server(modules):
    m = modules("mail_folder")
    assert m.clean("a@icloud.com", "", "", "")["host"] == "imap.mail.me.com"
    assert m.clean("a@example.org", "", 993, "Bills")["host"] == "imap.example.org"
    for bad in (("not an address", "", 993, ""), ("a@gmail.com", "", 143, ""), ("a@proton.me", "", 993, ""),
                ("a@gmail.com", "imap.gmail.com", 993, 'IN"BOX'), ("a@gmail.com", "bad host!", 993, "")):
        with pytest.raises(m.MailError):
            m.clean(*bad)


def test_pull_copies_files_and_texts_read_only_and_once(mf, modules):
    inbox = modules("paths").INBOX
    before = set(p.name for p in inbox.iterdir())
    r = mf.pull()
    new = sorted(set(p.name for p in inbox.iterdir()) - before)
    assert r["messages"] == 3 and r["files"] == 1 and r["texts"] == 1, r  # "hi" alone is too short to keep
    assert any(n.endswith("_mail_power.example_bill.pdf") for n in new)
    assert any("_mail_school.example_Field-trip-on-Friday" in n for n in new)
    assert not any("logo" in n for n in new), "a tiny picture is a logo, not a paper"
    cmds = {c[1] for c in FakeIMAP.calls if c[0] == "uid"}
    assert cmds <= {"SEARCH", "FETCH"} and ("select", '"INBOX"', True) in FakeIMAP.calls, "read-only: EXAMINE, SEARCH, FETCH"
    assert all(c[-1] in ("(RFC822.SIZE)", "(BODY.PEEK[])") for c in FakeIMAP.calls if c[:2] == ("uid", "FETCH"))
    assert mf.pull()["messages"] == 0, "each message is copied once"
    assert mf.status()["last_pull"]


def test_a_wrong_app_password_or_a_private_server_is_refused(mf, modules):
    modules("config").write_secret(mf.MAIL_SECRET, "wrong")
    with pytest.raises(mf.MailError, match="refused the sign-in"):
        mf.test()
    modules("config").write_secret(mf.MAIL_SECRET, FakeIMAP.password)
    assert mf.test() == 3
    with modules("config").family_edit() as cfg:
        cfg["mail_folder"]["host"] = "mail.local"
    with pytest.raises(mf.MailError, match="public internet"):
        mf.test()


def test_settings_password_only_on_this_pc_and_never_shown(web, mf, modules, monkeypatch):  # noqa: F811
    c, _, _ = web
    _login(c)
    token = _csrf(c)
    app_mod = modules("webapp.app")
    config = modules("config")
    config.write_secret(mf.MAIL_SECRET, "")
    monkeypatch.setattr(app_mod, "is_local", lambda request: False)
    _post(c, "/settings/mail", token, op="save", address="riveras.mitra@gmail.com", host="", port="993", folder="INBOX",
          password="secretapppw", enabled="1")
    assert config.read_secret(mf.MAIL_SECRET) == ""
    monkeypatch.setattr(app_mod, "is_local", lambda request: True)
    _post(c, "/settings/mail", token, op="save", address="riveras.mitra@gmail.com", host="", port="993", folder="INBOX",
          password="abcd efgh ijkl mnop", enabled="1")
    assert config.read_secret(mf.MAIL_SECRET) == FakeIMAP.password, "spaces dropped, as providers show it in groups"
    page = c.get("/settings?group=connections").text
    assert "Mail folder" in page and FakeIMAP.password not in page and "saved; blank = keep it" in page
    audit = (modules("paths").LOGS / "admin_audit.log").read_text(encoding="utf-8")
    assert "mail_folder_set" in audit and FakeIMAP.password not in audit and "riveras.mitra" not in audit
    _post(c, "/settings/mail", token, op="test")
    assert "Signed in: 3 messages" in c.get("/settings?group=connections").text
    _post(c, "/settings/mail", token, op="forget", sure="1")
    assert config.read_secret(mf.MAIL_SECRET) == "" and not config.family()["mail_folder"]["enabled"]


def test_a_phone_cannot_point_the_saved_password_at_another_server(web, mf, modules, monkeypatch):  # noqa: F811
    """audit 2026-10-28: address / host / port changed from a phone kept the saved app password, and Test then signed
    in to the new server with it"""
    c, _, _ = web
    _login(c)
    token = _csrf(c)
    app_mod = modules("webapp.app")
    config = modules("config")
    monkeypatch.setattr(app_mod, "is_local", lambda request: True)
    _post(c, "/settings/mail", token, op="save", address="riveras.mitra@gmail.com", host="", port="993", folder="INBOX",
          password=FakeIMAP.password, enabled="1")
    monkeypatch.setattr(app_mod, "is_local", lambda request: False)
    for change in ({"host": "imap.attacker.example"}, {"address": "x@attacker.example"}, {"port": "994"}):
        form = {"address": "riveras.mitra@gmail.com", "host": "imap.gmail.com", "port": "993", "folder": "INBOX", **change}
        _post(c, "/settings/mail", token, op="save", password="", enabled="1", **form)
        assert mf.settings()["host"] == "imap.gmail.com" and mf.settings()["address"] == "riveras.mitra@gmail.com"
        assert mf.settings()["port"] == 993
    _post(c, "/settings/mail", token, op="save", address="riveras.mitra@gmail.com", host="imap.gmail.com", port="993",
          folder="Mitra", password="", enabled="1")
    assert mf.settings()["folder"] == "Mitra", "the folder and the switch may still change from a phone"
    assert config.read_secret(mf.MAIL_SECRET) == FakeIMAP.password
