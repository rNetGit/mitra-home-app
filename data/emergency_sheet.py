"""One-page emergency sheet -> reports/emergency_sheet.md (print it; keep a copy in the fire safe / with a trusted person).

  python data/emergency_sheet.py

Pulls members, vehicles (plate last4), insurance carriers, accounts (name + last4), ID documents (type + expiry),
loans, contacts from config/contacts.json (see config/contacts.example.json) and "Where things are" (config/family.json
`emergency.where`, set on Today > Documents > Emergency sheet). NO passwords, PINs or full numbers.
The sheet is a local file; printing it is your choice. seal(text, passphrase) makes a copy for a trusted person: one
HTML file that any browser opens with the passphrase (AES-256-GCM, key by PBKDF2-SHA256), offline, no app needed.
"""
import pathlib
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import dates  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402

ROOT = HERE.parent
# "Where things are": what someone we trust needs to find, as places and names (never a password, PIN or number)
WHERE = [("will", "The will and power of attorney"),
         ("passwords", "Who can open the password manager (a name, never the password)"),
         ("safe", "Fire safe or safe-deposit box"),
         ("backup", "The backup drive"),
         ("insurance", "Insurance and house papers"),
         ("pets", "The pets: vet and who can take them"),
         ("other", "Anything else")]
WHERE_MAX = 200
SEAL_ITERATIONS = 600_000


def where(fam=None):
    """The family's "Where things are" notes: {key: text} for the keys in WHERE that are filled in."""
    got = ((fam if fam is not None else config.family()).get("emergency") or {}).get("where") or {}
    return {k: str(got[k]) for k, _ in WHERE if str(got.get(k) or "").strip()}


def q(con, sql):
    try:
        return con.execute(sql).fetchall()
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
        return []


def build(con):
    fam = config.family()
    L = [f"# Emergency sheet - {fam.get('family_name', 'Family')}", "", f"_Updated {dates.today():%B %d, %Y}. Do not write passwords or PINs on this sheet._", ""]
    reg = config.region()
    if any(reg.values()):
        L += [f"Home: {', '.join(x for x in (reg['place'], reg['county'], reg['state'], reg['zip']) if x)}", ""]
    L += ["## People", ""]
    for n, role, md, by in q(con, "SELECT name, role, birth_month_day, birth_year FROM members ORDER BY id"):
        L.append(f"- {n} ({role})" + (f", birthday {md}" if md else ""))
    import member_info
    facts = member_info.for_sheet(con)
    if facts:
        L += ["", "## Critical info by person", ""]
        L += [f"- {m} - {cat}, {lb}: {val}" for m, cat, lb, val in facts]
    L += ["", "## Contacts", ""]
    contacts = (config.data_file("contacts.json") or {}).get("contacts", [])
    L += [f"- {c.get('role', '')}: {c.get('name', '')} {c.get('phone', '')} {c.get('notes', '')}".rstrip() for c in contacts] or \
         ["- _No contacts yet: doctors, school, neighbours, utility shut-offs (see Settings > Data > Advanced)_"]
    import home_contacts
    help_ = home_contacts.for_sheet(con)
    if help_:
        L += ["", "## House help (plumber, furnace, garage ...)", ""]
        L += [f"- {t}: {n} {p}".rstrip() + (f" ({no})" if no else "") for t, n, p, no in help_]
    L += ["", "## Insurance", ""]
    L += [f"- {k} - {c} (policy x{l}), term ends {te or '?'}" for k, c, l, te in
          q(con, "SELECT kind, carrier, policy_last4, term_end FROM policies WHERE status IS NULL OR status NOT IN ('expired','replaced','cancelled','superseded')")] or ["- _none recorded_"]
    L += ["", "## Vehicles", ""]
    L += [f"- {y} {m} {mo}, plate x{p or '?'}" for y, m, mo, p in
          q(con, "SELECT year, make, model, plate_last4 FROM vehicles WHERE status='active'")] or ["- _none recorded_"]
    L += ["", "## Accounts (names and last 4 only)", ""]
    L += [f"- {n} ({t}) x{l}" for n, t, l in q(con, "SELECT name, type, last4 FROM accounts ORDER BY type, name")] or ["- _none recorded_"]
    L += ["", "## Loans", ""]
    L += [f"- {n} ({k or ''}) at {lender or '?'}" for n, k, lender in q(con, "SELECT name, kind, lender FROM loans WHERE status='active'")] or ["- _none recorded_"]
    L += ["", "## ID documents", ""]
    L += [f"- {p}: {t}, expires {e or '?'}" for p, t, e in q(con, "SELECT person, doc_type, expires FROM id_documents WHERE active=1 ORDER BY person")] or ["- _none recorded_"]
    L += ["", "## Where things are", ""]
    notes = where(fam)
    L += [f"- {label}: {notes[k]}" for k, label in WHERE if k in notes]
    L += ["- Originals of statements and policies: the archive folder on the family PC."]
    if "passwords" not in notes:
        L += ["- Who can open the password manager / has the master plan: _write the person's name, not the password_"]
    L += [""]
    return "\n".join(L)


SEALED_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Emergency sheet (sealed)</title>
<style>body{font:16px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;max-width:46rem;margin:2rem auto;padding:0 1rem;color:#14181f}
input,button{font:inherit;padding:.5rem .75rem}pre{white-space:pre-wrap;font:15px/1.55 system-ui,-apple-system,Segoe UI,sans-serif}
.muted{color:#5e6672}@media print{form,.muted{display:none}}</style></head>
<body><h1>Emergency sheet</h1>
<p class="muted">Sealed by the family's __PRODUCT__ on __DATE__. Type the passphrase they gave you. Nothing is sent
anywhere: it opens in this browser, offline.</p>
<form id="f"><input id="p" type="password" autocomplete="off" placeholder="Passphrase" required autofocus>
<button>Open</button> <span id="m" class="muted" role="status"></span></form>
<pre id="out"></pre>
<script>
var D = __DATA__;
function bytes(s){var b=atob(s),a=new Uint8Array(b.length);for(var i=0;i<b.length;i++)a[i]=b.charCodeAt(i);return a;}
document.getElementById('f').addEventListener('submit', function(e){
  e.preventDefault();
  var m=document.getElementById('m'); m.textContent='Opening...';
  if(!window.crypto||!crypto.subtle){m.textContent='This browser cannot open it: try Chrome, Edge, Firefox or Safari.';return;}
  var pass=new TextEncoder().encode(document.getElementById('p').value);
  crypto.subtle.importKey('raw',pass,'PBKDF2',false,['deriveKey']).then(function(k){
    return crypto.subtle.deriveKey({name:'PBKDF2',salt:bytes(D.salt),iterations:D.iter,hash:'SHA-256'},k,
      {name:'AES-GCM',length:256},false,['decrypt']);
  }).then(function(key){
    return crypto.subtle.decrypt({name:'AES-GCM',iv:bytes(D.iv)},key,bytes(D.ct));
  }).then(function(plain){
    document.getElementById('out').textContent=new TextDecoder().decode(plain);
    document.getElementById('f').hidden=true; m.textContent='';
  }).catch(function(){m.textContent='That passphrase does not open it.';});
});
</script></body></html>
"""


def seal(text, passphrase, today=None):
    """The sheet as one HTML file that opens with `passphrase` in any modern browser (Web Crypto), offline. The
    passphrase is never stored; without it the file cannot be read."""
    import base64
    import json
    import os
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    salt, iv = os.urandom(16), os.urandom(12)
    key = PBKDF2HMAC(hashes.SHA256(), 32, salt, SEAL_ITERATIONS).derive(passphrase.encode("utf-8"))
    ct = AESGCM(key).encrypt(iv, text.encode("utf-8"), None)
    b64 = lambda x: base64.b64encode(x).decode("ascii")  # noqa: E731
    data = json.dumps({"salt": b64(salt), "iv": b64(iv), "ct": b64(ct), "iter": SEAL_ITERATIONS})
    import brand
    return (SEALED_PAGE.replace("__DATA__", data).replace("__DATE__", f"{today or dates.today():%B %d, %Y}")
            .replace("__PRODUCT__", brand.PRODUCT))


if __name__ == "__main__":
    con = db.connect(paths.DB, readonly=True)
    out = paths.REPORTS / "emergency_sheet.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(build(con), encoding="utf-8")
    print(out)
