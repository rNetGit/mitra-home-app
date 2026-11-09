"""Redaction before anything leaves the PC (data/pii.py): the hard tier is always masked, the known tier is
pseudonymised and restored, the soft tier (amounts, dates, vendors) survives untouched, and the guards refuse full
identifiers coming back from the model or typed into a form."""
import json
import os
import re
import subprocess
import sys

import pytest

from conftest import KEYS, q, read_family, run, write_family

HARD = [
    ("SSN 123-45-6789", "123-45-6789", "[ssn]"),
    ("Social Security Number: 123 45 6789", "123 45 6789", "[ssn]"),
    ("EIN 12-3456789", "12-3456789", "[tax id]"),
    ("Card 4111 1111 1111 1111", "4111 1111 1111 1111", "[number ending 1111]"),
    ("Card 4111-1111-1111-1111", "4111-1111-1111-1111", "[number ending 1111]"),
    ("Account 1234 5678 9012 4321.", "1234 5678 9012 4321", "[number ending 4321]"),
    ("acct 12345678", "12345678", "ending 5678]"),  # the "acct" label wins: [id ending 5678]
    ("acct 1234 5678 9012 4321, due", "1234 5678 9012 4321", "[id ending 4321], due"),
    ("routing 021000021", "021000021", "[number ending 0021]"),
    ("IBAN DE89370400440532013000", "DE89370400440532013000", "[id ending 3000]"),
    ("mail alex.smith@example.com now", "alex.smith@example.com", "[email]"),
    ("call (512) 555-1234", "555-1234", "[phone]"),
    ("call +1 512.555.9876", "555.9876", "[phone]"),
    ("DOB 03/14/1985", "03/14/1985", "[date of birth]"),
    ("Date of birth: 1985-03-14", "1985-03-14", "[date of birth]"),
    ("Born on March 14, 1985", "March 14, 1985", "[date of birth]"),
    ("Driver's License No. D1234567", "D1234567", "[id ending 4567]"),
    ("Passport # X12345678", "X12345678", "[id ending 5678]"),
    ("Member ID ABC123456", "ABC123456", "[id ending 3456]"),
    ("VIN 1HGCM82633A004352", "1HGCM82633A004352", "[id ending 4352]"),
    ("Policy No. HO-998877665", "HO-998877665", "[id ending 7665]"),
    ("at 123 Main Street, Apt 4B,", "123 Main Street", "[address]"),
    ("at 9 Oak Hill Rd.", "Oak Hill Rd", "[address]"),
]
SOFT = ["$123.45", "1,234,567.89", "45.00", "2026-09-25", "09/25/2026", "10/15/2026", "3:30 pm", "Invoice 4821", "ref 12345",
        "ACME POWER", "Samsung TV", "20260925", "policy x1234", "ending 4321", "$12345678.00", "12345678.50", "2026-09-01T10:30"]


@pytest.fixture(scope="module")
def pii(modules):
    return modules("pii")


@pytest.mark.parametrize("text,secret,mask", HARD, ids=[h[0] for h in HARD])
def test_hard_tier_is_masked(pii, text, secret, mask):
    out = pii.Redactor().redact(text)
    assert secret not in out and mask in out, out


@pytest.mark.parametrize("keep", SOFT)
def test_soft_tier_survives(pii, keep):
    text = f"Statement for ACME POWER. Total {keep} see note. Account 1234 5678 9012 4321 SSN 123-45-6789."
    out = pii.Redactor(["Alex Smith"]).redact(text)
    assert keep in out, out
    assert "1234 5678 9012 4321" not in out and "123-45-6789" not in out


def test_known_tier_pseudonymises_and_restores(pii):
    r = pii.Redactor(["Alex Smith", "Sam", "Biscuit"], ["Oak School"])
    out = r.redact("Dear Alex Smith, SMITH, ALEX and Sam's dentist at Oak School; Samsung TV for Biscuit. Sam.")
    assert "Alex" not in out and "Smith" not in out and "Oak School" not in out and "Biscuit" not in out
    assert "[person1]" in out and "[person2]'s" in out and "[term1]" in out
    assert "Samsung" in out, "whole words only"
    assert r.restore({"vendor": "[person1]'s", "list": ["[term1]", 3]}) == {"vendor": "Alex Smith's", "list": ["Oak School", 3]}
    assert "name" in r.counts and r.summary()


def test_short_names_and_opt_out(pii):
    assert "Al" in pii.Redactor(["Al"]).redact("Al pays"), "names under 3 characters are not masked (too many false hits)"
    assert "Alex" in pii.Redactor(["Alex"], redact_names=False).redact("Alex pays")


def test_household_terms_come_from_family_json(root, pii):
    fam = read_family(root)
    fam["privacy"] = {"extra_terms": ["Zeta Employer"]}
    write_family(root, fam)
    try:
        out = pii.redact("Alex works at Zeta Employer with Sam")
        assert "Alex" not in out and "Zeta Employer" not in out and "Sam" not in out
        fam["privacy"] = {"redact_names": False}
        write_family(root, fam)
        assert "Alex" in pii.redact("Alex works")
    finally:
        fam.pop("privacy", None)
        write_family(root, fam)


def test_names_printed_on_papers_are_masked(root, pii, modules):
    """Short household names miss the legal names a policy prints in capitals; paper names and the surname close that."""
    page = "INSURED: ALEXANDER QUINTERO  09/01/2026  TOTAL PREMIUM $1,196.00\nDear Mr. Quintero, ... Samantha Quintero"
    fam = read_family(root)
    keep = json.dumps(fam)
    assert "ALEXANDER" in pii.redact(page), "the gap this release closes: a nickname-only household leaks legal names"
    assert pii.names_on_papers_missing(fam)
    try:
        fam["family_name"] = "The Quintero family"
        fam["ai"] = {**(fam.get("ai") or {}), "provider": "ollama"}
        write_family(root, fam)
        h = modules("health")
        assert [r for r in h.checks() if r["name"] == "Names on papers" and r["status"] == "warn"]
        out = pii.redact(page)
        assert "QUINTERO" not in out.upper() and "family" not in pii.surname_words("The Quintero family")
        aa = modules("admin_actions")
        adult, child = {"name": "Alex", "role": "adult"}, {"name": "Sam", "role": "child"}
        assert not aa.paper_names_set(child, "Alexander Quintero")[0]
        assert not aa.paper_names_set(adult, "Alexander 4411")[0], "digits are refused"
        assert aa.paper_names_set(adult, "Alexander Quintero\n\nSamantha  Quintero\nalexander quintero")[0]
        fam = read_family(root)
        assert fam["privacy"]["paper_names"] == ["Alexander Quintero", "Samantha Quintero"]
        assert not pii.names_on_papers_missing(fam)
        out = pii.redact(page)
        for w in ("ALEXANDER", "QUINTERO", "Samantha", "Quintero"):
            assert w not in out, w
        assert "$1,196.00" in out and "09/01/2026" in out, "amounts and dates survive"
        log = (root / "logs" / "admin_audit.log").read_text(encoding="utf-8")
        assert "paper_names\t2 name(s)" in log and "Quintero" not in log, "the audit holds the count, never the names"
        assert not [r for r in h.checks() if r["name"] == "Names on papers"]
    finally:
        write_family(root, json.loads(keep))


@pytest.mark.parametrize("text,hard", [
    ("$123.45 due 2026-09-25", False), ("ref 12345678", False), ("20261008", False), ("balance 123456789.00", False),
    ("123-45-6789", True), ("1234 5678 9012 3456", True), ("a@b.com", True), ("acct 123456789", True),
])
def test_contains_hard_guard(pii, text, hard):
    assert pii.contains_hard(text) is hard


def test_validators_refuse_full_identifiers(modules):
    v = modules("validators")
    for bad in ("my SSN is 123-45-6789", "card 4111111111111111", "mail me at a@b.com"):
        with pytest.raises(ValueError, match="last four"):
            v.text()(bad)
    assert v.text()("Dentist, policy ending 4321, $45.00 on 2026-10-01") == "Dentist, policy ending 4321, $45.00 on 2026-10-01"


def test_preview_cli_sends_nothing(root, tmp_path):
    f = tmp_path / "bill.txt"
    f.write_text("ACME POWER bill for Alex. Account 1234 5678 9012 4321, due $55.00 by 2026-11-01. SSN 123-45-6789", encoding="utf-8")
    r = run(["data/llm.py", "redact-preview", str(f)], root)
    assert r.returncode == 0, r.stderr[-300:]
    assert "[number ending 4321]" in r.stdout and "[ssn]" in r.stdout and "$55.00" in r.stdout and "123-45-6789" not in r.stdout
    assert "[person" in r.stdout, "family names from config/family.json are masked"
    assert "masked:" in r.stdout
    r = subprocess.run([sys.executable, "data/pii.py", "--text", "call 512-555-1234"], cwd=root, capture_output=True, text=True)
    assert "[phone]" in r.stdout


# ---- through the mock provider

BILL = {"doc_type": "bill", "vendor": "Acme Power", "doc_date": "2026-09-01", "amount": 123.45, "due_date": "2026-09-25",
        "account_last4": "4321", "period": "Aug 2026", "confidence": 0.93}
SCHEMA = {"doc_type": (str, True, ["bill", "other"]), "vendor": (str, False, None), "confidence": ((int, float), True, None)}
DOC = ("ACME POWER bill for Alex Smith, 123 Main Street. SSN 123-45-6789, DOB 03/14/1985, alex@example.com, (512) 555-1234. "
       "Account 1234 5678 9012 4321. Amount due $123.45 by 2026-09-25.")


def test_nothing_hard_reaches_the_provider(root, modules, mock_llm):
    llm = modules("llm")
    mock_llm.use("anthropic")
    mock_llm.set(BILL)
    obj, errs = llm.extract_json(llm.UNTRUSTED, DOC, SCHEMA)
    assert not errs and obj["vendor"] == "Acme Power"
    sent = json.dumps(mock_llm.seen[-1]["body"])
    for secret in ("123-45-6789", "03/14/1985", "alex@example.com", "555-1234", "1234 5678 9012 4321", "Alex", "Main Street"):
        assert secret not in sent, secret
    for keep in ("$123.45", "2026-09-25", "ACME POWER", "ending 4321"):
        assert keep in sent, keep
    assert "private data" in sent, "the soft-tier instruction is in the prompt"


def test_placeholders_in_the_answer_are_restored(root, modules, mock_llm):
    llm = modules("llm")
    mock_llm.use("anthropic")
    mock_llm.set({**BILL, "vendor": "[person1]"})
    obj, errs = llm.extract_json(llm.UNTRUSTED, DOC, SCHEMA)
    assert not errs and obj["vendor"] == "Alex"


def test_answer_with_a_full_number_is_rejected(root, modules, mock_llm):
    llm = modules("llm")
    mock_llm.use("anthropic")
    mock_llm.queue = [json.dumps({**BILL, "vendor": "Acme 1234567890123"}), json.dumps({**BILL, "vendor": "Acme 1234567890123"})]
    obj, errs = llm.extract_json(llm.UNTRUSTED, DOC, SCHEMA)
    assert errs and "full account" in errs[0]


def test_intake_routes_a_leaky_answer_to_review(root, modules, mock_llm):
    mock_llm.use("anthropic")
    mock_llm.queue = [json.dumps({**BILL, "period": "acct 9876543210"}), json.dumps({**BILL, "period": "acct 9876543210"})]
    f = root / "inbox" / "leaky.txt"
    f.write_text(DOC, encoding="utf-8")
    r = run(["data/ai_intake.py"], root, env=KEYS)
    assert r.returncode == 0, r.stderr[-300:]
    assert (root / "inbox" / "needs_review" / "leaky.txt").exists()
    assert q(root, "select count(*) from review_queue where path like '%leaky.txt' and detail like '%full account%'")[0][0] == 1


@pytest.mark.parametrize("prov", ["gemini", "gemini_cli"])
def test_free_tier_gemini_is_refused_until_confirmed(root, modules, mock_llm, tmp_path, prov):
    llm = modules("llm")
    fake = tmp_path / "fake_cli.py"
    fake.write_text("import sys\nsys.stdin.read()\nprint('hello from cli')\n", encoding="utf-8")
    mock_llm.use(prov, cli_path=str(fake))
    mock_llm.set("hello from gemini")
    with pytest.raises(llm.LLMError, match="paid tier"):
        llm.complete("say hi")
    assert not mock_llm.seen, "nothing was sent"
    mock_llm.use(prov, cli_path=str(fake), gemini_paid_tier_confirmed=True)
    assert llm.complete("say hi").startswith("hello from")


def test_assistant_masks_what_you_type_but_keeps_names(root, modules, mock_llm):
    mock_llm.use("anthropic")
    mock_llm.set(json.dumps({"reply": "noted", "actions": [], "question": None}))
    r = run(["data/assistant.py", "--yes", "Sam's dentist, my SSN is 123-45-6789, card 4111 1111 1111 1111"], root, env=KEYS)
    assert r.returncode == 0, r.stdout + r.stderr[-200:]
    sent = json.dumps(mock_llm.seen[-1]["body"])
    assert "123-45-6789" not in sent and "4111 1111 1111 1111" not in sent and "Sam" in sent
    assert "private data" in sent


def test_wizard_refuses_gemini_without_paid_tier(tmp_path):
    from conftest import copy_template
    root = copy_template(tmp_path / "w")
    env = {**os.environ, "AIFA_DRY_RUN": "1"}
    choices = (root / "onboard.py").read_text(encoding="utf-8").split("AI_CHOICES = [", 1)[1].split("\n]", 1)[0]
    num = {k: str(i) for i, k in enumerate(re.findall(r'^    \("(\w+)", ', choices, re.M), 1)}  # the wizard's own menu order
    r = subprocess.run([sys.executable, "onboard.py", "add", "ai"], cwd=root, input=num["gemini"] + "\nn\n", capture_output=True, text=True, timeout=120, env=env)
    assert "free-tier provider refused" in r.stdout, r.stdout[-400:]
    assert not (read_family(root).get("ai") or {}).get("gemini_paid_tier_confirmed")
    r = subprocess.run([sys.executable, "onboard.py", "add", "ai"], cwd=root, input=num["ollama"] + "\n\n", capture_output=True, text=True, timeout=120, env=env)
    assert (read_family(root).get("ai") or {}).get("provider") == "ollama", r.stdout[-400:]
