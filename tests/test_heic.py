"""iPhone HEIC photos (audit 2026-10-18, slice S6): with Pillow + pillow-heif on this PC a HEIC receipt photo is turned
into a JPEG here (upright, smaller, no EXIF) and only that JPEG goes to the family's AI; the HEIC itself is filed. With
photo reading off it waits with "Reading photos is off"; without the packages it waits with a plain reason and nothing
is sent. The Wallet keeps a HEIC card photo as the JPEG. Made-up data; the AI is the test suite's mock provider."""
import base64
import io

import pytest

from conftest import q

# a 64 x 48 red HEIC made with pillow-heif (446 bytes)
HEIC = base64.b64decode(
    "AAAAHGZ0eXBoZWljAAAAAG1pZjFoZWljbWlhZgAAAX1tZXRhAAAAAAAAACFoZGxyAAAAAAAAAABwaWN0AAAAAAAAAAAAAAAAAAAAACJpbG9jAA"
    "AAAERAAAEAAQAAAAABoQABAAAAAAAAAB0AAAAjaWluZgAAAAAAAQAAABVpbmZlAgAAAAABAABodmMxAAAAAA5waXRtAAAAAAABAAAA/WlwcnAA"
    "AADdaXBjbwAAAHZodmNDAQNwAAAAkAAAAAAAHvAA/P34+AAADwNgAAEAGEABDAH//wNwAAADAJAAAAMAAAMAHroCQGEAAQAqQgEBA3AAAAMAkA"
    "AAAwAAAwAeoCCBBZbq5Ka5uAhoMCAAAAMDIAAAAwAhYgABAAZEAcFzwIkAAAATY29scm5jbHgAAQANAAaAAAAAFGlzcGUAAAAAAAAAQAAAAEAA"
    "AAAoY2xhcAAAAEAAAAABAAAAMAAAAAEAAAAAAAAAAv////AAAAACAAAAEHBpeGkAAAAAAwgICAAAABhpcG1hAAAAAAAAAAEAAQWBAgMFhAAAAC"
    "VtZGF0AAAAGSgBrxOA9SeBP//gpUf/utZ4fg8Lfnny1PA=")
JPEG = b"\xff\xd8\xff\xe0" + b"converted here" + b"\x00" * 32
GOOD = {"is_receipt": True, "store": "Sample Bakery", "date": "2026-10-11", "total": 18.40, "card_last4": "4321",
        "confidence": 0.93}


@pytest.fixture()
def converter(modules, monkeypatch):
    """This PC 'has' pillow-heif: the converter answers JPEG for a HEIC, so the suite needs no image packages."""
    heic = modules("heic")
    seen = []

    def to_jpeg(src):
        seen.append(src)
        return JPEG
    monkeypatch.setattr(heic, "available", lambda: True)
    monkeypatch.setattr(heic, "to_jpeg", to_jpeg)
    return seen


@pytest.fixture()
def no_converter(modules, monkeypatch):
    monkeypatch.setattr(modules("heic"), "_libs", lambda: None)


def _drop(root, name, tail):
    f = root / "inbox" / name
    f.parent.mkdir(exist_ok=True)
    f.write_bytes(HEIC + tail.encode())  # each photo its own bytes, or the exact-copy check files it as a duplicate
    return f


def _intake(modules, f):
    ai, db = modules("ai_intake"), modules("db")
    con = db.connect(modules("paths").DB)
    try:
        return ai.process_file(con, f)
    finally:
        con.close()


def test_a_heic_receipt_is_read_as_a_jpeg_and_the_heic_is_filed(root, modules, mock_llm, converter):
    mock_llm.use("anthropic", read_receipt_photos=True)
    mock_llm.set(GOOD)
    f = _drop(root, "IMG_2743.HEIC", "a")
    name, status, info = _intake(modules, f)
    assert status == "filed", info
    assert info.endswith("2026-10-11_sample_bakery_receipt.heic"), "the original HEIC is what gets filed"
    assert (root / info).read_bytes().startswith(HEIC) and not f.exists()
    assert q(root, "SELECT merchant, total, card_last4 FROM receipts WHERE merchant='Sample Bakery'") == \
        [("Sample Bakery", 18.40, "4321")]
    sent = mock_llm.seen[0]["body"]["messages"][0]["content"][0]["source"]
    assert sent["media_type"] == "image/jpeg" and base64.b64decode(sent["data"]) == JPEG, "only the JPEG made here"
    assert len(converter) == 1


def test_a_heic_photo_waits_when_photo_reading_is_off(root, modules, mock_llm, converter):
    mock_llm.use("anthropic")
    mock_llm.set(GOOD)
    f = _drop(root, "IMG_2744.heic", "b")
    _, status, reason = _intake(modules, f)
    assert status == "review" and reason.startswith("photo not read: reading photos with AI is off"), reason
    assert (root / "inbox" / "needs_review" / "IMG_2744.heic").exists() and mock_llm.seen == [] and converter == []
    assert modules("proposals")._plain_reason(reason, "IMG_2744.heic").startswith("Reading photos is off.")


def test_without_the_packages_a_heic_waits_with_a_plain_reason(root, modules, mock_llm, no_converter):
    mock_llm.use("anthropic", read_receipt_photos=True)
    mock_llm.set(GOOD)
    f = _drop(root, "IMG_2745.HEIC", "c")
    _, status, reason = _intake(modules, f)
    assert status == "review" and reason.startswith("HEIC photo not read") and "pillow-heif" in reason, reason
    assert (root / "inbox" / "needs_review" / "IMG_2745.HEIC").exists() and mock_llm.seen == [], "nothing was sent"
    plain = modules("proposals")._plain_reason(reason, "IMG_2745.HEIC")
    assert "iPhone photo (HEIC)" in plain and "Save it as JPG" in plain
    llm = modules("llm")
    assert not llm.reads_photo(f.name) and llm.reads_photo("a.JPG")
    with pytest.raises(llm.LLMError, match="pillow-heif"):
        llm.extract_image_json("read it", root / "inbox" / "needs_review" / "IMG_2745.HEIC", {"store": (str, True, None)})


def test_an_older_heic_card_says_try_again_once_this_pc_reads_them(modules, monkeypatch):
    pr, heic = modules("proposals"), modules("heic")
    old = "HEIC photo: this iPhone photo format is not read yet; save it as JPG or PDF and drop it again"
    monkeypatch.setattr(heic, "available", lambda: True)
    assert "press Reprocess" in pr._plain_reason(old, "IMG_1.HEIC")
    assert "press Reprocess" in pr._plain_reason("file type not read by the Python pipeline", "IMG_1.HEIC")
    assert pr._plain_reason("photo not read by AI", "IMG_1.HEIC").startswith("The AI could not read the photo")
    monkeypatch.setattr(heic, "available", lambda: False)
    assert "cannot turn that format" in pr._plain_reason(old, "IMG_1.HEIC")


def test_a_heic_card_photo_waits_in_the_wallet_as_a_jpeg(modules, converter, monkeypatch):
    wallet = modules("wallet")
    ok, token = wallet.save_draft("IMG_3001.HEIC", HEIC)
    assert ok, token
    f = wallet.draft_path(token)
    assert f.suffix == ".jpg" and f.read_bytes() == JPEG
    wallet.drop_draft(token)
    monkeypatch.setattr(modules("heic"), "to_jpeg", lambda src: (_ for _ in ()).throw(ValueError("no")))
    ok, why = wallet.save_draft("IMG_3002.heic", HEIC)
    assert not ok and "HEIC" in why
    assert wallet.save_draft("IMG_3003.heic", b"not a photo at all")[0] is False


def test_the_real_converter_makes_an_upright_jpeg_without_exif(modules):
    pytest.importorskip("pillow_heif")
    from PIL import Image
    heic = modules("heic")
    assert heic.available()
    out = heic.to_jpeg(HEIC)
    with Image.open(io.BytesIO(out)) as im:
        assert im.format == "JPEG" and im.size == (64, 48) and not im.getexif()
    with pytest.raises(ValueError, match="not a HEIC"):
        heic.to_jpeg(b"\xff\xd8\xff\xe0 a jpeg")
    with pytest.raises(ValueError, match="could not be converted"):
        heic.to_jpeg(HEIC[:120])


def test_a_real_heic_goes_through_intake_as_a_jpeg(root, modules, mock_llm):
    pytest.importorskip("pillow_heif")
    from PIL import Image
    mock_llm.use("openai", read_receipt_photos=True, vision_model="see-1")
    mock_llm.set({**GOOD, "store": "Sample Deli"})
    _, status, info = _intake(modules, _drop(root, "IMG_2746.HEIC", "d"))
    assert status == "filed" and info.endswith("_sample_deli_receipt.heic"), info
    url = mock_llm.seen[0]["body"]["messages"][1]["content"][1]["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")
    with Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))) as im:
        assert im.format == "JPEG" and im.size == (64, 48)
