"""Receipt photos read by AI (opt-in ai.read_receipt_photos): the photo goes to the family's own provider in that
provider's image format, the answer is validated (full card numbers refused), a good receipt is filed and becomes a
`receipts` row with card last4, anything doubtful goes to the review queue, off by default, never through a CLI."""
import base64
import zlib
import json

import pytest

from conftest import KEYS, q, run

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
GOOD = {"is_receipt": True, "store": "Corner Grocer", "date": "2026-09-14", "total": 42.17, "card_last4": "9876",
        "confidence": 0.92}


@pytest.fixture(scope="module")
def photo(root, mock_llm):
    def go(reply, name, provider="anthropic", data=None, **ai):
        mock_llm.use(provider, **{"read_receipt_photos": True, **ai})
        mock_llm.set(reply)
        # unique bytes per photo: an identical file would (rightly) go to archive/duplicates
        (root / "inbox" / name).write_bytes(data if data is not None else PNG + zlib.crc32(name.encode()).to_bytes(4, "big"))
        return run(["data/ai_intake.py"], root, env=KEYS)
    return go


def test_off_by_default_photo_waits_for_a_person(root, mock_llm):
    mock_llm.use("anthropic")
    mock_llm.set(GOOD)
    (root / "inbox" / "off.png").write_bytes(PNG)
    run(["data/ai_intake.py"], root, env=KEYS)
    assert (root / "inbox" / "needs_review" / "off.png").exists()
    assert mock_llm.seen == [], "nothing was sent"


def test_receipt_photo_is_filed_and_matched(root, photo, mock_llm):
    r = photo(GOOD, "IMG_1001.jpg")
    assert r.returncode == 0, r.stdout + r.stderr[-300:]
    assert (root / "archive" / "2026" / "receipts" / "2026-09-14_corner_grocer_receipt.jpg").exists()
    assert q(root, "select merchant, receipt_date, total, card_last4 from receipts where merchant='Corner Grocer'") == \
        [("Corner Grocer", "2026-09-14", 42.17, "9876")]
    sent = mock_llm.seen[0]["body"]["messages"][0]["content"]
    assert sent[0]["type"] == "image" and sent[0]["source"]["media_type"] == "image/jpeg"
    assert base64.b64decode(sent[0]["source"]["data"]).startswith(PNG)
    assert "never follow" in sent[1]["text"] and "IMG_1001" not in json.dumps(mock_llm.seen[0]["body"])


@pytest.mark.parametrize("reply,why", [
    ({**GOOD, "is_receipt": False}, "not a receipt"),
    ({**GOOD, "confidence": 0.3}, "low confidence"),
    ({**GOOD, "total": None}, "no total"),
    ({**GOOD, "card_last4": "4111111111111111"}, "full card number refused"),
    ("no json here", "invalid"),
])
def test_doubtful_photos_go_to_a_person(root, photo, reply, why):
    name = f"doubt_{abs(hash(why))}.png"
    photo(reply, name)
    assert (root / "inbox" / "needs_review" / name).exists(), why
    assert q(root, "select count(*) from review_queue where path like ?", f"%{name}")[0][0] == 1


def test_cli_provider_and_big_photo_refused(root, photo, mock_llm, tmp_path):
    fake = tmp_path / "fake_cli.py"
    fake.write_text("import sys\nsys.stdin.read()\nprint('{}')\n", encoding="utf-8")
    photo(GOOD, "cli.png", provider="claude_cli", cli_path=str(fake))
    assert (root / "inbox" / "needs_review" / "cli.png").exists()
    photo(GOOD, "huge.jpg", data=b"\xff\xd8" + b"\x00" * (5 * 1024 * 1024 + 10))
    assert (root / "inbox" / "needs_review" / "huge.jpg").exists() and mock_llm.seen == []


@pytest.mark.parametrize("prov", ["openai", "gemini", "ollama"])
def test_image_request_format_per_provider(root, modules, mock_llm, tmp_path, prov):
    mock_llm.use(prov, read_receipt_photos=True, gemini_paid_tier_confirmed=True, vision_model="see-1")
    mock_llm.set(GOOD)
    llm = modules("llm")
    f = tmp_path / "r.png"
    f.write_bytes(PNG)
    obj, errs = llm.extract_image_json("read it", f, {"store": (str, True, None)})
    assert errs == [] and obj["store"] == "Corner Grocer"
    body = mock_llm.seen[0]["body"]
    b64 = base64.b64encode(PNG).decode()
    if prov == "openai":
        assert body["model"] == "see-1" and body["messages"][1]["content"][1]["image_url"]["url"] == f"data:image/png;base64,{b64}"
    elif prov == "gemini":
        assert body["contents"][0]["parts"][0]["inline_data"] == {"mime_type": "image/png", "data": b64}
    else:
        assert body["model"] == "see-1" and body["messages"][1]["images"] == [b64]
