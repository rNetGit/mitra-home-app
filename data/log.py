"""One logger for the whole tool (standard library only).

    import log
    L = log.get("backup")          # logger "mitrahome.backup"
    L.info("snapshot written to %s", dest)

Writes to logs/mitrahome.log (rotated at 512 KiB, three old copies kept), INFO and up. A process that runs for hours
(the web app, the phone bots) calls `log.use("web")` first and writes to logs/mitrahome-web.log instead: on Windows a
file another process holds open cannot be renamed, so one shared file stopped rotating and lost lines. If a rotation
is still refused, the lines go on in the same file. Never put document
text, prompts, keys or full account numbers in a log line; the file is plain text next to the database.
Scripts keep printing to stdout for the person running them; the log is for "what happened last night".
Set MITRAHOME_LOG_LEVEL=DEBUG to see the skipped not-migrated-yet queries.
"""
import logging
import logging.handlers
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
import paths  # noqa: E402
FILE = paths.LOGS / "mitrahome.log"
_ready = False


class _Rotating(logging.handlers.RotatingFileHandler):
    """Rotation that another process may block (Windows keeps open files from being renamed): keep writing to the
    same file and try again at the next record instead of dropping lines."""

    def doRollover(self):
        try:
            super().doRollover()
        except OSError:
            if self.stream is None:
                self.stream = self._open()


def _setup():
    global _ready
    if _ready:
        return
    root = logging.getLogger("mitrahome")
    level = paths.env("MITRAHOME_LOG_LEVEL", "INFO").upper()
    root.setLevel(getattr(logging, level, logging.INFO))
    try:
        FILE.parent.mkdir(exist_ok=True)
        h = _Rotating(FILE, maxBytes=512 * 1024, backupCount=3, encoding="utf-8")
    except OSError:
        h = logging.NullHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"))
    root.addHandler(h)
    root.propagate = False
    _ready = True


def use(process):
    """This process writes to logs/mitrahome-<process>.log from now on (long-running processes: web, telegram,
    discord). Safe to call after loggers were made: they all write through the one "mitrahome" handler."""
    global FILE, _ready
    if not process.isidentifier():
        raise ValueError("process name: letters, digits and _ only")
    root = logging.getLogger("mitrahome")
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()
    FILE = paths.LOGS / f"mitrahome-{process}.log"
    _ready = False
    _setup()


def get(name):
    _setup()
    return logging.getLogger(f"mitrahome.{name}")
