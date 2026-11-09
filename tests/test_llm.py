"""Provider-neutral AI (data/llm.py) against a mock server: request formats, redaction, key handling, caps, and the
signed-in CLI providers through a fake vendor CLI. No real keys, no network, no real login."""
import json
import os

import pytest

from conftest import KEYS, read_family, write_family

BILL = {"doc_type": "bill", "vendor": "Acme Power", "doc_date": "2026-09-01", "amount": 123.45, "due_date": "2026-09-25",
        "account_last4": "4321", "period": "Aug 2026", "confidence": 0.93}


@pytest.fixture(scope="module")
def llm(root, modules, mock_llm):
    return modules("llm")


@pytest.mark.parametrize("prov,path_part,hdr,expect", [
    ("anthropic", "/v1/messages", "x-api-key", "sk-ant-api03-test"),
    ("openai", "/v1/chat/completions", "authorization", "Bearer sk-openai-test"),
    ("gemini", ":generateContent", "x-goog-api-key", "gem-test-key"),
    ("ollama", "/api/chat", None, None),
])
def test_request_format_and_response_parsing(llm, mock_llm, prov, path_part, hdr, expect):
    mock_llm.use(prov, gemini_paid_tier_confirmed=True)  # free-tier refusal is tested in test_pii.py
    mock_llm.set("hello from " + prov)
    out = llm.complete("say hi")
    req = mock_llm.seen[-1]
    hv = {k.lower(): v for k, v in req["headers"].items()}
    assert out == "hello from " + prov
    assert path_part in req["path"]
    if hdr:
        assert hv.get(hdr) == expect
    if prov == "gemini":
        assert "gem-test-key" not in req["path"], "key goes in a header, not the URL"


def test_gemini_json_calls_limit_thinking_so_the_answer_fits(llm, mock_llm):
    """Real 2.5 Flash spent 3,928 of 4,096 output tokens thinking on a long policy and cut the JSON off."""
    mock_llm.use("gemini", gemini_paid_tier_confirmed=True)
    mock_llm.set('{"doc_type": "bill"}')
    llm.extract_json("x", "y", {"doc_type": (str, True, None)}, max_tokens=900)
    gen = mock_llm.seen[-1]["body"]["generationConfig"]
    assert gen["maxOutputTokens"] >= 900 + 8192 and gen["responseMimeType"] == "application/json"
    model = llm.settings()["model"]
    if "2.5" in model:
        assert gen["thinkingConfig"]["thinkingBudget"] == (512 if "pro" in model else 0)
    assert llm.gemini_thinking_budget("gemini-2.5-flash", True) == 0
    assert llm.gemini_thinking_budget("gemini-2.5-pro", True) == 512
    assert llm.gemini_thinking_budget("gemini-2.5-flash", False) is None, "chat keeps Google's default"
    assert llm.gemini_thinking_budget("gemini-3-flash", True) is None, "other models: leave thinking to Google"
    llm.complete("say hi")
    assert "thinkingConfig" not in mock_llm.seen[-1]["body"]["generationConfig"]


def test_extract_json_validates_and_redacts(llm, mock_llm):
    mock_llm.use("anthropic")
    mock_llm.set("Here you go: " + json.dumps(BILL))
    obj, errs = llm.extract_json(llm.UNTRUSTED, "Account 1234 5678 9012 3456 total due $123.45 by 2026-09-25", {
        "doc_type": (str, True, ["bill", "other"]), "vendor": (str, False, None), "confidence": ((int, float), True, None)})
    assert not errs and obj["vendor"] == "Acme Power", errs
    sent = json.dumps(mock_llm.seen[-1]["body"])
    assert "1234 5678 9012 3456" not in sent and "number ending 3456" in sent
    assert "$123.45" in sent and "2026-09-25" in sent
    mock_llm.set("not json at all")
    obj, errs = llm.extract_json("x", "y", {"doc_type": (str, True, None)})
    assert errs, "garbage output is rejected, not trusted"


def test_redact_masks_long_digit_runs_only(llm):
    out = llm.redact("acct 123456789012 paid $45.00 on 2026-01-02, ref 12345")
    assert "123456789012" not in out and "$45.00" in out and "2026-01-02" in out and "12345" in out


def test_subscription_token_is_refused(llm, mock_llm):
    mock_llm.use("anthropic")
    os.environ["MITRAHOME_ANTHROPIC_API_KEY"] = "sk-ant-oat01-subscription-token"
    try:
        with pytest.raises(llm.LLMError) as e:
            llm.complete("hi")
        assert "subscription" in str(e.value).lower() or "OAuth" in str(e.value)
    finally:
        os.environ["MITRAHOME_ANTHROPIC_API_KEY"] = KEYS["MITRAHOME_ANTHROPIC_API_KEY"]


def test_missing_key_gives_a_clear_error(llm, mock_llm):
    mock_llm.use("openai")
    os.environ.pop("MITRAHOME_OPENAI_API_KEY")
    saved = os.environ.pop("OPENAI_API_KEY", None)
    try:
        with pytest.raises(llm.LLMError, match="No API key"):
            llm.complete("hi")
    finally:
        os.environ["MITRAHOME_OPENAI_API_KEY"] = KEYS["MITRAHOME_OPENAI_API_KEY"]
        if saved is not None:
            os.environ["OPENAI_API_KEY"] = saved


def test_remote_ollama_refused_by_default(llm, mock_llm):
    mock_llm.use("ollama", base_url="http://192.168.1.50:11434")
    with pytest.raises(llm.LLMError, match="not this PC"):
        llm.complete("hi")


def test_daily_cap_and_usage_log(root, llm, mock_llm):
    mock_llm.use("anthropic", max_calls_per_day=1)
    mock_llm.set("ok")
    llm.complete("ZZCAPMARKER one")
    with pytest.raises(llm.LLMError) as e:
        llm.complete("ZZCAPMARKER two")
    assert "cap" in str(e.value).lower()
    assert "ZZCAPMARKER" not in (root / "logs" / "ai_usage.log").read_text(encoding="utf-8"), "usage log has no prompt text"


def test_store_key_never_into_family_json(root, llm):
    """Keys live in config/secrets.env only."""
    llm.store_key("gemini", "gem-store-test")
    try:
        assert "gem-store-test" in (root / "config" / "secrets.env").read_text(encoding="utf-8")
        assert "gem-store-test" not in json.dumps(read_family(root))
    finally:
        (root / "config" / "secrets.env").unlink(missing_ok=True)


# ---- signed-in CLIs as a text model (claude_cli / codex_cli / gemini_cli)

FAKE_CLI = (
    "import sys, os, json, pathlib\n"
    "a = sys.argv[1:]\n"
    "data = sys.stdin.read()\n"
    "rec = {'argv': a, 'cwd': os.getcwd(), 'stdin': data, 'leak': [k for k in os.environ if k.startswith('MITRAHOME_')]}\n"
    "pathlib.Path(os.environ['FAKE_CLI_LOG']).write_text(json.dumps(rec))\n"
    "if os.environ.get('FAKE_CLI_FAIL'):\n"
    "    print('not signed in', file=sys.stderr); sys.exit(2)\n"
    "reply = os.environ.get('FAKE_CLI_REPLY', 'cli says hi')\n"
    "if '--output-last-message' in a:\n"
    "    pathlib.Path(a[a.index('--output-last-message') + 1]).write_text(reply)\n"
    "    print('noise')\n"
    "else:\n"
    "    print(reply)\n")


@pytest.fixture(scope="module")
def fake_cli(tmp_path_factory):
    d = tmp_path_factory.mktemp("cli")
    fake = d / "fake_cli.py"
    fake.write_text(FAKE_CLI, encoding="utf-8")
    os.environ["FAKE_CLI_LOG"] = str(d / "fake_cli_log.json")
    for k in ("FAKE_CLI_FAIL", "FAKE_CLI_REPLY"):
        os.environ.pop(k, None)
    yield fake
    for k in ("FAKE_CLI_LOG", "FAKE_CLI_FAIL", "FAKE_CLI_REPLY"):
        os.environ.pop(k, None)


def _rec():
    return json.loads(open(os.environ["FAKE_CLI_LOG"], encoding="utf-8").read())


@pytest.mark.parametrize("prov", ["claude_cli", "codex_cli", "gemini_cli"])
def test_cli_provider_contract(root, llm, mock_llm, fake_cli, prov):
    mock_llm.use(prov, cli_path=str(fake_cli), gemini_paid_tier_confirmed=True)
    out = llm.complete("PROMPT-MARKER-QQ please", system="SYS-MARKER-QQ", purpose="cli-test")
    r = _rec()
    assert out == "cli says hi"
    assert "PROMPT-MARKER-QQ" in r["stdin"] and "SYS-MARKER-QQ" in r["stdin"], "prompt goes on stdin"
    assert not any("PROMPT-MARKER" in x for x in r["argv"]), "never on the command line"
    assert str(root) not in r["cwd"], "runs in an empty temp folder"
    assert r["leak"] == [], "family API keys are not passed to the CLI"
    a = r["argv"]
    if prov == "claude_cli":
        assert "--tools" in a and a[a.index("--tools") + 1] == "" and a[a.index("--model") + 1] == "haiku"
        assert "--strict-mcp-config" in a  # no MCP servers from the user's global config
    if prov == "codex_cli":
        assert "read-only" in a and "--ephemeral" in a and out != "noise"
    if prov == "gemini_cli":
        assert "-p" in a


def test_cli_model_override_failure_and_missing_cli(llm, mock_llm, fake_cli, tmp_path):
    mock_llm.use("claude_cli", cli_path=str(fake_cli), model="sonnet")
    llm.complete("x")
    a = _rec()["argv"]
    assert a[a.index("--model") + 1] == "sonnet"
    os.environ["FAKE_CLI_FAIL"] = "1"
    try:
        with pytest.raises(llm.LLMError) as e:
            llm.complete("x")
        assert "not signed in" in str(e.value) and "signed in" in str(e.value)
    finally:
        os.environ.pop("FAKE_CLI_FAIL")
    mock_llm.use("codex_cli", cli_path=str(tmp_path / "no_such_cli.py"))
    with pytest.raises(llm.LLMError):
        llm.complete("x")


def test_cli_providers_share_the_daily_cap(llm, mock_llm, fake_cli):
    mock_llm.use("claude_cli", cli_path=str(fake_cli), max_calls_per_day=1)
    llm.complete("one")
    with pytest.raises(llm.LLMError) as e:
        llm.complete("two")
    assert "cap" in str(e.value).lower()


def test_claude_model_setting_for_scheduled_runs(root, modules, mock_llm):
    rt = modules("run_task")
    fam = read_family(root)
    fam["ai"] = {"provider": "claude_code"}
    write_family(root, fam)
    assert rt.claude_model("sonnet") == "sonnet"
    fam["ai"]["claude_model"] = "haiku"
    write_family(root, fam)
    assert rt.claude_model("sonnet") == "haiku"
    fam["ai"]["claude_model"] = "haiku; rm -rf /"
    write_family(root, fam)
    assert rt.claude_model("sonnet") == "sonnet", "odd values are ignored"


def test_provider_matrix_mentions_training_warning(root):
    from conftest import run
    r = run(["data/llm.py", "matrix"], root)
    assert all(x in r.stdout for x in ("claude_cli", "codex_cli", "gemini_cli", "ollama")) and "TRAIN" in r.stdout
