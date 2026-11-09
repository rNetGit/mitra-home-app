"""The four-page shell (0.48): left rail, Chat as the landing page (works without any AI), Inbox over the proposals
queue, Brief, Settings; the old Classic view is gone. Streamlit AppTest against a seeded throwaway copy."""

import pytest

from conftest import db, q

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest


def _last(at):
    return at.chat_message[-1].markdown[0].value


def test_seasonal_done_edit_action(root, modules):
    ea = modules("edit_actions")
    con = db(root)
    con.execute("INSERT OR IGNORE INTO seasonal_tasks(name, category, start_md, end_md) VALUES ('Flu shots', 'Health', '09-15', '11-30')")
    con.commit()
    con.close()
    tid, name = q(root, "SELECT id, name FROM seasonal_tasks WHERE name='Flu shots'")[0]
    assert ea.seasonal_done({"name": "Sam", "role": "child"}, tid)[0] is False
    assert ea.seasonal_done({"name": "Alex", "role": "adult"}, tid, "2999-01-01")[0] is False
    ok, msg = ea.seasonal_done({"name": "Alex", "role": "adult"}, tid, "2026-10-01", "CVS")
    assert ok and msg == f"Logged: {name} on 2026-10-01."
    assert q(root, "SELECT place FROM seasonal_log WHERE task_id=? AND done_date='2026-10-01'", tid) == [("CVS",)]
