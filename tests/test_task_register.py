"""task_register.adopt_flags: jobs this install already runs get their flags in family.json."""


def test_adopt_flags_sets_what_the_scheduler_already_runs(modules, monkeypatch):
    tr, config = modules("task_register"), modules("config")
    with config.family_edit() as c:
        c.pop("tasks_registered", None)
        c.pop("inbox_cycle", None)
    states = {"daily_digest": ("on", "x"), "weekly_digest": ("off", ""), "weekly_backup": ("off", ""), "inbox_cycle": ("paused", "x")}
    monkeypatch.setattr(tr, "job_state", lambda job, run=None, root=tr.ROOT: states.get(job, ("off", "")))
    assert tr.adopt_flags() == ["inbox_cycle", "tasks_registered"]
    assert config.family()["tasks_registered"] is True and config.family()["inbox_cycle"] is True
    assert tr.adopt_flags() == [], "nothing left to set"
    with config.family_edit() as c:
        c.pop("tasks_registered", None)
    states.update(daily_digest=("off", ""), inbox_cycle=("elsewhere", "y"))
    assert tr.adopt_flags() == [] and not config.family().get("tasks_registered"), "other copies' tasks do not count"
