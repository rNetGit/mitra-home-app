"""The document pipeline for every provider (0.51): OpenRouter as a provider, nested answer checks, and the second
call that reads a policy, ID, vehicle paper, medical letter, investment or tax paper into its tables; statements the
no-AI reader cannot use are read by the AI and imported only when the lines add up. Mock provider, no network."""
import pytest

from conftest import KEYS, q, run


def classify(typ, vendor, date="2026-03-01", amount=None, due=None, conf=0.95):
    return {"doc_type": typ, "vendor": vendor, "doc_date": date, "amount": amount, "due_date": due,
            "account_last4": None, "period": None, "confidence": conf}


POLICY = {"carrier": "Zz Mutual", "kind": "auto", "policy_last4": "8812", "term_start": "2026-03-01", "term_end": "2026-09-01",
          "premium_total": 612.4, "payment_plan": "semiannual", "insured_names": "Alex", "property_address_city": None,
          "vehicles": [{"year": 2019, "make": "Honda", "model": "Zz Accord", "vin_last4": "4352", "premium": 330.1},
                       {"year": 2021, "make": "Toyota", "model": "Zz Rav4", "vin_last4": "9917", "premium": 282.3}],
          "drivers": [{"name": "Alex", "relation": "named insured", "excluded": False},
                      {"name": "Sam", "relation": "child", "excluded": True}],
          "coverages": [{"coverage": "Bodily injury", "limit": "100/300", "deductible": None, "premium": 210.0},
                        {"coverage": "Collision", "limit": None, "deductible": 500, "premium": 150.5}],
          "discounts": [{"name": "Multi-car", "amount": 44.0}], "confidence": 0.92}


@pytest.fixture(scope="module")
def llm(root, modules, mock_llm):
    return modules("llm")


@pytest.fixture(scope="module")
def intake(root, modules, mock_llm):
    def go(replies, fname, content, provider="openai"):
        mock_llm.use(provider)
        mock_llm.set(replies[-1])
        mock_llm.queue[:] = [__import__("json").dumps(r) if not isinstance(r, str) else r for r in replies]
        (root / "inbox" / fname).write_text(content, encoding="utf-8")
        r = run(["data/ai_intake.py"], root, env=KEYS)
        mock_llm.queue[:] = []
        return r
    return go


def test_openrouter_request_asks_for_hosts_that_keep_no_data(llm, mock_llm):
    mock_llm.use("openrouter", model="google/gemini-2.5-flash")
    mock_llm.set("hello from openrouter")
    assert llm.complete("say hi", max_tokens=50) == "hello from openrouter"
    req = mock_llm.seen[-1]
    hv = {k.lower(): v for k, v in req["headers"].items()}
    assert "/v1/chat/completions" in req["path"] and hv["authorization"] == "Bearer sk-or-v1-test"
    assert req["body"]["provider"] == {"data_collection": "deny"} and req["body"]["max_tokens"] == 50
    assert req["body"]["model"] == "google/gemini-2.5-flash" and hv.get("x-title") == "Mitra Home"
    assert "openrouter" in llm.KEYED and "openrouter" in llm.TEXT and llm.DEFAULTS["openrouter"][1] == "https://openrouter.ai/api"


def test_openrouter_is_offered_everywhere_a_provider_is_chosen(root, modules):
    aa = modules("admin_actions")
    assert "openrouter" in aa.PROVIDERS and "openrouter" in aa.KEYED and "openrouter" in aa.TEST_NOW
    assert '("openrouter",' in (root / "onboard.py").read_text(encoding="utf-8")
    for f in ("data/inbox_data.py", "tasks/run_task.py", "data/health.py"):
        assert '"openrouter"' in (root / f).read_text(encoding="utf-8"), f


def test_nested_answers_are_checked_item_by_item(llm):
    sc = {"name": (str, True, None), "items": (list, False, {"what": (str, True, None), "n": ((int, float), False, None)})}
    assert llm.validate({"name": "x", "items": [{"what": "a", "n": 1}]}, sc) == []
    errs = llm.validate({"name": "x", "items": [{"n": "one"}, "nope"]}, sc)
    assert "items[0].what missing" in errs and "items[0].n has the wrong type" in errs and "items[1]. is not an object" in errs
    assert llm.validate({"name": "x", "items": "a"}, sc) == ["items must be a list (at most 300)"]
    assert llm.carries_identifier({"a": [{"b": "card 4111111111111111"}]}) and not llm.carries_identifier({"a": [{"b": "x4321"}]})


def test_auto_policy_becomes_policy_vehicles_drivers_coverages(root, intake):
    r = intake([classify("policy", "Zz Mutual", amount=612.4, due="2026-03-01"), POLICY], "zz_dec.txt",
               "ZZ MUTUAL auto declarations. Policy 4471-22-8812. 2019 Honda Accord VIN 1HGCM82633A004352 ...")
    assert r.returncode == 0, r.stdout + r.stderr[-300:]
    assert "Zz Mutual auto policy, renews 2026-09-01" in r.stdout and "2 vehicle(s), 2 driver(s)" in r.stdout, r.stdout
    pid, last4, plan, prem, doc = q(root, "select id, policy_last4, payment_plan, premium_total, document_id from policies where carrier='Zz Mutual'")[0]
    assert (last4, plan, prem) == ("8812", "semiannual", 612.4) and doc
    assert q(root, "select make, vin_last4 from policy_vehicles where policy_id=? order by id", pid) == [("Honda", "4352"), ("Toyota", "9917")]
    assert q(root, "select count(*) from vehicles where model in ('Zz Accord', 'Zz Rav4')")[0][0] == 2, "cars added to vehicles"
    assert q(root, "select name, excluded from policy_drivers where policy_id=? order by id", pid) == [("Alex", 0), ("Sam", 1)]
    assert q(root, "select coverage, limit_text, deductible from policy_coverages where policy_id=? order by id", pid) == [
        ("Bodily injury", "100/300", None), ("Collision", None, 500.0)]
    assert q(root, "select name, amount from policy_discounts where policy_id=?", pid) == [("Multi-car", 44.0)]
    assert q(root, "select amount from bills where vendor='Zz Mutual'") == [(612.4,)]
    assert "Zz Mutual auto policy" in q(root, "select notes from documents where id=?", doc)[0][0]
    # the renewal: a new term, the earlier one is marked replaced, the cars are not added twice
    renew = {**POLICY, "term_start": "2026-09-01", "term_end": "2027-03-01", "premium_total": 640.0}
    intake([classify("policy", "Zz Mutual", "2026-08-10"), renew], "zz_renew.txt", "ZZ MUTUAL renewal declarations ...")
    rows = q(root, "select status, prior_policy_id from policies where carrier='Zz Mutual' order by term_start")
    assert rows[0][0] == "replaced" and rows[1] == ("active", pid), rows
    assert q(root, "select count(*) from vehicles where model in ('Zz Accord', 'Zz Rav4')")[0][0] == 2
    # the same paper again: already on file
    r = intake([classify("policy", "Zz Mutual", "2026-08-11"), renew], "zz_renew_copy.txt", "ZZ MUTUAL renewal declarations copy ...")
    assert "already on file" in r.stdout and q(root, "select count(*) from policies where carrier='Zz Mutual'")[0][0] == 2


PER_CAR = {**POLICY, "carrier": "Zz Percar Mutual", "policy_last4": "5521",
           "coverages": [{"coverage": "Bodily injury", "limit": "250/500", "premium": 121.0, "vehicle": "4352"},
                         {"coverage": "Bodily injury", "limit": "250/500", "premium": 139.0, "vehicle": "VIN ending 9917"},
                         {"coverage": "Collision", "deductible": 500, "premium": 320.0, "vehicle": "2021 Toyota Zz Rav4"},
                         {"coverage": "Bodily injury", "limit": "250/500", "premium": 121.0, "vehicle": "4352"},
                         {"coverage": "Roadside assistance", "limit": "100", "premium": 11.0, "vehicle": None},
                         {"coverage": "AGGREGATE NO FAULT BENEFITS AVAILABLE", "limit": "50000", "premium": 76.0, "vehicle": "4352"}],
           "discounts": [{"name": "Multi-car", "amount": 210.0, "vehicle": "4352"},
                         {"name": "Multi-car", "amount": 296.0, "vehicle": "9917"},
                         {"name": "Paid in full", "amount": 88.0}]}
CAR_SQL = ("select {col}, coalesce(v.vin_last4, '') from {table} x left join policy_vehicles v on v.id=x.vehicle_id "
           "where x.policy_id=? order by x.id")


def test_coverages_printed_per_car_keep_their_car(root, intake, mock_llm):
    r = intake([classify("policy", "Zz Percar Mutual"), PER_CAR], "zz_percar.txt", "ZZ PERCAR MUTUAL auto declarations, two cars ...")
    assert r.returncode == 0 and "Zz Percar Mutual auto policy" in r.stdout, r.stdout + r.stderr[-300:]
    pid = q(root, "select id from policies where carrier='Zz Percar Mutual'")[0][0]
    cov = [("Bodily injury", "4352"), ("Bodily injury", "9917"), ("Collision", "9917"), ("Roadside assistance", ""),
           ("AGGREGATE NO FAULT BENEFITS AVAILABLE", "4352")]
    assert q(root, CAR_SQL.format(col="x.coverage", table="policy_coverages"), pid) == cov, "one row per car, the exact repeat once"
    disc = [("Multi-car", "4352"), ("Multi-car", "9917"), ("Paid in full", "")]
    assert q(root, CAR_SQL.format(col="x.name", table="policy_discounts"), pid) == disc
    # a subtotal line never carries a premium, even when the model gave it one (it would be counted twice)
    assert q(root, "select premium from policy_coverages where policy_id=? and coverage like 'AGGREGATE%'", pid) == [(None,)]
    assert q(root, "select sum(premium) from policy_coverages where policy_id=?", pid)[0][0] == 121 + 139 + 320 + 11
    # a policy filed before cars were recorded: read again, lines replaced with their cars (vehicles, drivers kept)
    con = __import__("sqlite3").connect(root / "data" / "family.db")
    con.execute("update policy_coverages set vehicle_id=null where policy_id=?", (pid,))
    con.execute("update policy_discounts set vehicle_id=null where policy_id=?", (pid,))
    con.commit()
    con.close()
    mock_llm.use("openai")
    mock_llm.set(PER_CAR)
    r = run(["data/doc_extract.py", "reread-policy", str(pid)], root, env=KEYS)
    assert r.returncode == 0 and "5 coverage(s), 3 discount(s), 6 tied to a car" in r.stdout, r.stdout + r.stderr[-300:]
    assert q(root, CAR_SQL.format(col="x.coverage", table="policy_coverages"), pid) == cov
    assert q(root, "select count(*) from policy_vehicles where policy_id=?", pid)[0][0] == 2
    r = run(["data/doc_extract.py", "reread-policy", "999999"], root, env=KEYS)
    assert r.returncode == 2 and "not changed: policy 999999 has no filed paper" in r.stdout, r.stdout


def test_id_vehicle_medical_investment_tax(root, intake):
    intake([classify("id", "Passport office"), {"person": "Alex", "id_type": "passport", "number_last4": "X771",
                                               "issued": "2020-05-01", "expires": "2030-04-30", "authority": "US", "confidence": 0.9}],
           "zz_pass.txt", "PASSPORT ... ")
    assert q(root, "select number_last4, expires, document_id is not null from id_documents where person='Alex' and doc_type='passport'") == [
        ("X771", "2030-04-30", 1)]
    intake([classify("vehicle", "DMV"), {"year": 2019, "make": "Honda", "model": "Zz Accord", "vin_last4": "4352", "plate_last4": "7KQ2",
                                         "owner": "Alex", "registration_expires": "2027-02-28", "inspection_expires": None,
                                         "confidence": 0.9}], "zz_reg.txt", "VEHICLE REGISTRATION ...")
    assert q(root, "select registration_expires, plate_last4 from vehicles where model='Zz Accord'") == [("2027-02-28", "7KQ2")]
    intake([classify("medical", "Zz Clinic"), {"person": "Sam", "provider": "Zz Clinic", "purpose": "Checkup", "visit_date": "2026-03-01",
                                               "visit_time": "09:30", "followup_due": "2026-09-01", "confidence": 0.9}],
           "zz_visit.txt", "VISIT SUMMARY ...")
    assert q(root, "select appt_datetime, followup_due from appointments where provider='Zz Clinic'") == [("2026-03-01 09:30", "2026-09-01")]
    intake([classify("investment", "Zz Brokerage"), {"name": "Zz Index Fund", "kind": "mutual_fund", "current_value": 15000.5,
                                                     "invested": 12000, "as_of": "2026-02-28", "maturity_date": None, "confidence": 0.9}],
           "zz_inv.txt", "INVESTMENT STATEMENT ...")
    assert q(root, "select kind, current_value, as_of from investments where name='Zz Index Fund'") == [("mutual_fund", 15000.5, "2026-02-28")]
    intake([classify("tax", "Zz Employer", "2026-01-31"), {"form": "W-2", "tax_year": 2025, "issuer": "Zz Employer", "amount": 85000,
                                                          "confidence": 0.9}], "zz_w2.txt", "FORM W-2 ...")
    note = q(root, "select notes from documents where vendor='Zz Employer'")[0][0]
    assert "W-2 2025 from Zz Employer" in note, note


@pytest.mark.parametrize("details,why", [
    ({**POLICY, "confidence": 0.3}, "not sure"),
    ({**POLICY, "policy_last4": "4471228812991"}, "full number"),
    ({**POLICY, "term_start": "2026-09-01", "term_end": "2026-03-01"}, "ends before it starts"),
    ("not json at all", "unusable"),
])
def test_doubtful_details_wait_for_a_person(root, intake, details, why):
    fname = f"zz_doubt_{abs(hash(why)) % 10000}.txt"
    intake([classify("policy", "Zz Doubt"), details], fname, f"ZZ DOUBT policy paper ({why}) ...")  # unique: copies go to duplicates
    assert (root / "inbox" / "needs_review" / fname).exists(), why
    assert "policy: details not read" in q(root, "select reason from review_queue where path like ?", f"%{fname}")[0][0]
    assert not q(root, "select 1 from policies where carrier='Zz Mutual Doubt'")


STMT = {"institution": "Zz Credit Union", "account_type": "checking", "account_last4": "6020", "period_start": "2026-02-01",
        "period_end": "2026-02-28", "opening_balance": 1000.0, "closing_balance": 1350.25,
        "transactions": [{"date": "2026-02-03", "description": "PAYROLL ZZ", "amount": 2000.0},
                         {"date": "2026-02-10", "description": "RENT", "amount": -1500.0},
                         {"date": "2026-02-20", "description": "GROCER ZZ", "amount": -149.75}],
        "confidence": 0.9}


def test_statement_the_reader_cannot_use_is_read_by_ai_when_it_adds_up(root, intake):
    r = intake([classify("statement", "Zz Credit Union", "2026-02-28"), STMT], "zz_stmt.txt",
               "ZZ CREDIT UNION checking statement Feb 2026 ... (a layout the no-AI reader does not know)")
    assert "3 transactions added" in r.stdout and "new account Zz Credit Union checking x6020" in r.stdout, r.stdout
    aid = q(root, "select id from accounts where last4='6020'")[0][0]
    assert q(root, "select txn_date, amount from transactions where account_id=? order by txn_date", aid) == [
        ("2026-02-03", 2000.0), ("2026-02-10", -1500.0), ("2026-02-20", -149.75)]
    assert q(root, "select balance from account_balances where account_id=? and as_of='2026-02-28'", aid) == [(1350.25,)]
    bad = {**STMT, "closing_balance": 9999.0}
    intake([classify("statement", "Zz Credit Union", "2026-03-31"), bad], "zz_stmt_bad.txt", "ZZ CREDIT UNION March ...")
    reason = q(root, "select reason from review_queue where path like '%zz_stmt_bad.txt'")[0][0]
    assert "do not add up" in reason and q(root, "select count(*) from transactions where account_id=?", aid)[0][0] == 3


def test_real_model_answer_shapes_are_forgiven(llm, modules):
    """Shapes seen from google/gemini-2.5-flash through OpenRouter on 2026-10-10."""
    dx = modules("doc_extract")
    ans = {**POLICY, "term_start": "03/01/2026", "insured_names": ["Alex Test"],
           "vehicles": [{"year": "2019", "make": "HONDA", "model": "ACCORD EX", "vin_last4": "4352", "premium": "$331.20"}],
           "drivers": [{"name": "Sam Test", "relation_to_the_policyholder": "Child", "excluded": "true"}],
           "coverages": [{"coverage_name": "Collision", "limit": "Actual cash value", "deductible": "$1,250", "premium": 173}],
           "kind": "Auto", "confidence": 1}
    obj = llm.coerce(ans, dx.SCHEMAS["policy"])
    assert llm.validate(obj, dx.SCHEMAS["policy"]) == [], llm.validate(obj, dx.SCHEMAS["policy"])
    c = dx.prepare("policy", obj)
    assert c["term_start"] == "2026-03-01" and c["insured_names"] == "Alex Test" and c["kind"] == "auto"
    assert c["vehicles"][0]["year"] == 2019 and c["vehicles"][0]["premium"] == 331.2
    assert c["drivers"][0] == {"name": "Sam Test", "relation": "Child", "excluded": True}
    assert c["coverages"][0]["coverage"] == "Collision" and c["coverages"][0]["deductible"] == 1250.0
    assert "coverages (a list of objects with keys coverage, limit, deductible, premium, vehicle)" in llm.keys_of(dx.SCHEMAS["policy"])
    assert llm.coerce({"n": "100/300"}, {"n": ((int, float), False, None)}) == {"n": "100/300"}, "not a number: left for validate"


def test_a_paper_with_no_printed_date_is_filed_under_its_own_dates(root, intake):
    pol = {**POLICY, "carrier": "Zz Nodate Mutual", "policy_last4": "1199"}
    r = intake([classify("policy", "Zz Nodate Mutual", date=None), pol], "zz_nodate.txt", "ZZ NODATE MUTUAL declarations ...")
    assert "Zz Nodate Mutual auto policy" in r.stdout, r.stdout
    assert list((root / "archive" / "2026" / "insurance").glob("2026-03-01_zz_nodate_mutual_policy*")), "filed under the term start"
