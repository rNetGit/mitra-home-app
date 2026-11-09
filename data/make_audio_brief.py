"""Short spoken morning brief (about a minute) -> brief/YYYY-MM-DD_audio.txt and, with a voice engine, .wav.

  python data/make_audio_brief.py                 write today's script and audio (engine from config/family.json)
  python data/make_audio_brief.py --text-only     only the script
  python data/make_audio_brief.py setup --engine system|voicestudio|none [--voice NAME] [--url URL] [--rate N]

What it says: overdue items, what is due in the next seven days (the first six, by date), today's events, and a count
of the rest. Made from the database with no AI. It carries what the PDF briefs carry (names, payees, amounts).
Engines (config/family.json "audio"):
  none         nothing is spoken (default until you choose one)
  system       the voice built into this computer: Windows (System.Speech, offline), macOS `say`, Linux `espeak-ng`
  voicestudio  a VoiceStudio app you installed yourself, on this PC only (http://127.0.0.1:3900; OpenAI-style
               /v1/audio/speech). Other hosts are refused so the text never leaves the PC.
`python data/sync_drive.py push` copies the newest audio file to Drive Brief/ only when "audio" is in drive.push.
"""
import argparse
import datetime as dt
import json
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import dates  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402

ROOT = HERE.parent
BRIEF = paths.BRIEF
ENGINES = ["none", "system", "voicestudio"]
DEFAULT_URL = "http://127.0.0.1:3900/v1/audio/speech"
MAX_ITEMS = 6
KEEP_DAYS = 7
# a voice is a name the speech engine knows ("Microsoft Zira Desktop", "Samantha", "en-us+f3"): letters, digits and a few
# marks, never quotes or anything a shell reads (a document steering an agent must not get code into the brief's command)
VOICE_OK = re.compile(r"^[\w .()+-]{1,60}$")


def clean_voice(voice):
    """-> the voice name, or "" for none. Raises ValueError for anything that is not a plain name."""
    voice = str(voice or "").strip()
    if voice and not VOICE_OK.match(voice):
        raise ValueError("a voice name may only have letters, digits, spaces and . ( ) + -")
    return voice


def settings():
    a = config.family().get("audio") or {}
    try:
        voice = clean_voice(a.get("voice"))
    except ValueError:
        voice = ""  # a bad name saved before this check (or by hand) falls back to the default voice
    return {"engine": a.get("engine") or "none", "voice": voice, "url": a.get("url") or DEFAULT_URL,
            "rate": int(a.get("rate") or 0)}


def _money_words(amount):
    if amount is None:
        return ""
    whole = int(round(abs(amount)))
    sym = (config.family().get("currency") or "USD").upper()
    unit = {"USD": "dollars", "CAD": "dollars", "AUD": "dollars", "GBP": "pounds", "EUR": "euros", "INR": "rupees"}.get(sym, sym)
    return f", {whole:,} {unit}"


def _when(d, today):
    n = (d - today).days
    if n < 0:
        return f"{-n} day{'s' if n != -1 else ''} overdue"
    if n == 0:
        return "today"
    if n == 1:
        return "tomorrow"
    return f"on {d:%A}"


def script(con, today=None):
    """The words to speak (plain sentences, no symbols a voice would read out)."""
    import action_items as ai
    today = today or dates.today()
    items = ai.collect_items(con, today, 7)
    name = (config.family().get("family_name") or "").strip()
    lines = [f"Good morning{', ' + name if name else ''}. Here is your brief for {today:%A, %B} {today.day}."]
    over = [i for i in items if i["date"] < today]
    soon = [i for i in items if today <= i["date"] <= today + dt.timedelta(days=7)]
    if not over and not soon:
        lines.append("Nothing is due in the next seven days.")
    if over:
        lines.append(f"{len(over)} item{'s are' if len(over) != 1 else ' is'} overdue.")
    for i in (over + soon)[:MAX_ITEMS]:
        title = " ".join(str(i["title"]).replace("&", "and").replace("#", "number ").replace("/", " ").split())
        lines.append(f"{i['kind']}: {title}{_money_words(i.get('amount'))}, {_when(i['date'], today)}.")
    rest = len(over) + len(soon) - MAX_ITEMS
    if rest > 0:
        lines.append(f"And {rest} more on the dashboard.")
    lines.append("That's all. Have a good day.")
    return "\n".join(lines)


def _wav_system(text, out, voice="", rate=0):
    voice = clean_voice(voice)
    sysname = platform.system()
    if sysname == "Windows":
        # the voice goes in through the environment like the file names: nothing typed is ever part of the command
        ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
              + ("try { $s.SelectVoice($env:FA_VOICE) } catch {}; " if voice else "")
              + f"$s.Rate = {max(-10, min(10, int(rate)))}; $s.SetOutputToWaveFile($env:FA_OUT); "
              "$s.Speak([IO.File]::ReadAllText($env:FA_IN)); $s.Dispose()")
        tmp = out.with_suffix(".speak.txt")
        tmp.write_text(text, encoding="utf-8")
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True, text=True,
                               timeout=300, env={**os.environ, "FA_OUT": str(out), "FA_IN": str(tmp), "FA_VOICE": voice})
        finally:
            tmp.unlink(missing_ok=True)
        if r.returncode != 0 or not out.exists():
            raise RuntimeError(f"Windows speech failed: {(r.stderr or r.stdout)[-300:]}")
        return out
    if sysname == "Darwin" and shutil.which("say"):
        aiff = out.with_suffix(".aiff")
        subprocess.run(["say", "-o", str(aiff)] + (["-v", voice] if voice else []) + [text], check=True, timeout=300)
        if shutil.which("afconvert"):
            subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16", str(aiff), str(out)], check=True, timeout=300)
            aiff.unlink(missing_ok=True)
            return out
        return aiff
    for tool in ("espeak-ng", "espeak"):
        if shutil.which(tool):
            subprocess.run([tool, "-w", str(out)] + (["-v", voice] if voice else []) + [text], check=True, timeout=300)
            return out
    raise RuntimeError("no voice built into this computer was found (Windows speech, macOS say, or espeak-ng)")


def _loopback(url):
    u = urllib.parse.urlparse(url)
    return u.scheme in ("http", "https") and u.hostname in ("127.0.0.1", "localhost", "::1")


def _wav_voicestudio(text, out, url, voice=""):
    if not _loopback(url):
        raise RuntimeError("the VoiceStudio address must be on this PC (127.0.0.1 or localhost)")
    body = {"model": "omnivoice", "input": text, "response_format": "wav"}
    if voice:
        body["voice"] = voice
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never through a proxy
    try:
        with opener.open(req, timeout=600) as r:
            data = r.read()
    except OSError as e:
        raise RuntimeError(f"VoiceStudio did not answer at {url} ({e}); is the app running?") from None
    if len(data) < 44 or data[:4] != b"RIFF":
        raise RuntimeError("VoiceStudio did not send a WAV file")
    out.write_bytes(data)
    return out


def speak(text, out, s=None):
    s = s or settings()
    if s["engine"] == "system":
        return _wav_system(text, out, s["voice"], s["rate"])
    if s["engine"] == "voicestudio":
        return _wav_voicestudio(text, out, s["url"], s["voice"])
    return None


def tidy(today):
    """Keep a week of audio briefs in brief/."""
    for f in list(BRIEF.glob("*_audio.*")):
        try:
            d = dt.date.fromisoformat(f.name[:10])
        except ValueError:
            continue
        if (today - d).days > KEEP_DAYS:
            f.unlink(missing_ok=True)


def make(today=None, text_only=False):
    today = today or dates.today()
    BRIEF.mkdir(exist_ok=True)
    con = db.connect(readonly=True)
    try:
        text = script(con, today)
    finally:
        con.close()
    txt = BRIEF / f"{today.isoformat()}_audio.txt"
    txt.write_text(text + "\n", encoding="utf-8")
    audio = None if text_only else speak(text, BRIEF / f"{today.isoformat()}_audio.wav")
    tidy(today)
    return txt, audio


def setup(engine, voice=None, url=None, rate=None):
    if engine not in ENGINES:
        raise ValueError(f"engine must be one of {ENGINES}")
    if url and not _loopback(url):
        raise ValueError("the VoiceStudio address must be on this PC (127.0.0.1 or localhost)")
    if voice is not None:
        voice = clean_voice(voice)
    with config.family_edit() as fam:
        a = dict(fam.get("audio") or {})
        a["engine"] = engine
        for k, val in (("voice", voice), ("url", url), ("rate", rate)):
            if val is not None:
                a[k] = val
        fam["audio"] = a
    return a


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "setup":
        ap = argparse.ArgumentParser()
        ap.add_argument("--engine", required=True, choices=ENGINES), ap.add_argument("--voice"), ap.add_argument("--url")
        ap.add_argument("--rate", type=int)
        a = ap.parse_args(argv[1:])
        try:
            print("audio:", setup(a.engine, a.voice, a.url, a.rate))
        except ValueError as e:
            raise SystemExit(f"error: {e}")
        return
    ap = argparse.ArgumentParser()
    ap.add_argument("--text-only", action="store_true")
    a = ap.parse_args(argv)
    try:
        txt, audio = make(text_only=a.text_only)
    except RuntimeError as e:
        raise SystemExit(f"error: {e}")
    print(f"wrote {paths.rel(txt)}" + (f" and {paths.rel(audio)}" if audio else
                                                          " (no voice engine set: python data/make_audio_brief.py setup --engine system)"))


if __name__ == "__main__":
    main()
