"""One change through data/edit_actions.py from the command line: how the chat assistant makes the changes that the
app's forms make, as the signed-in person, without importing the form layer itself.

  python data/edit_cli.py FUNCTION '{"arg": "value", ...}' --as NAME --role adult

Only the functions in CHAT_EDITS can be called; the arguments are a JSON object of keyword arguments, which the
function validates again (data/edit_actions.py never raises on bad input: it answers (ok, message)). The message is
printed; the exit code is 0 when the change was made. --as / --role name the person the change is logged for in
logs/edits.log; the assistant passes the signed-in person (or "this PC" at the terminal). Never a shell: the assistant
builds this command line itself from validated arguments (data/assistant.py `edit`).
"""
import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

CHAT_EDITS = ("appointment_add", "bill_add", "event_add")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("function", choices=CHAT_EDITS)
    ap.add_argument("args", help="keyword arguments as a JSON object")
    ap.add_argument("--as", dest="name", required=True)
    ap.add_argument("--role", choices=["adult", "limited"], required=True)
    a = ap.parse_args(argv)
    try:
        kwargs = json.loads(a.args)
    except ValueError:
        print("arguments must be a JSON object")
        return 2
    if not isinstance(kwargs, dict):
        print("arguments must be a JSON object")
        return 2
    import edit_actions as ea
    ok, msg = getattr(ea, a.function)({"name": a.name, "role": a.role}, **kwargs)
    print(msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
