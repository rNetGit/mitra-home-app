"""Second pass of inbox filing for every AI provider: read the details a document type carries and store them.

ai_intake.py first asks what a document is (type, sender, date). For the types below it then asks once more, with a
fixed list of fields per type, and stores the answer in the right tables:

  policy      -> policies + policy_vehicles (+ vehicles) + policy_drivers + policy_coverages + policy_discounts
                 (coverages and discounts printed per car carry that car: vehicle_id -> policy_vehicles)
  id          -> id_documents (passport, licence, ... : expiry, last four digits)
  vehicle     -> vehicles (registration / inspection expiry)
  medical     -> appointments (visit date, follow-up)
  investment  -> investments (value, as-of date, maturity)
  tax         -> the document's note (form, tax year, issuer, amount)
  school_calendar -> calendar_days as 'proposed' (no-school days, breaks, early dismissals) until an adult accepts them
                 in the Inbox (proposals source 'days'); the school's name is kept as the label, nothing about a child
  statement   -> transactions, only when the balances add up (read_statement; used when data/pdf_statement.py,
                 which needs no AI, cannot read the statement)

The document text is untrusted DATA: it is masked first (data/pii.py), the answer is validated field by field
(llm.validate), an answer holding a full account, card, VIN or ID number is refused, and nothing in it is ever run.
Numbers are stored as last four digits only. `prepare()` checks everything before the file is moved; `save()` writes.

  python data/doc_extract.py fields            what is read for each type
  python data/doc_extract.py reread-policy ID  read a filed policy's paper again (one AI call) and replace its
                                               coverages and discounts, now with the car each one belongs to
"""
import datetime as dt
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import llm  # noqa: E402
import money as _money  # noqa: E402

POLICY_KINDS = ["auto", "home", "renters", "umbrella", "condo", "life", "health", "pet", "other"]
PLANS = ["annual", "semiannual", "quarterly", "monthly", "escrow", "other"]
INVEST_KINDS = ["fd", "mutual_fund", "stock", "retirement", "brokerage", "savings_bond", "other"]
CONF = (int, float), True, None
NUM = (int, float), False, None
TXT = str, False, None


def _id_types():
    try:
        import id_docs
        return list(id_docs.TYPES)
    except Exception:  # noqa: BLE001 (country profile missing in a bare copy)
        return ["passport", "drivers_license", "state_id", "green_card", "vehicle_registration", "insurance_card", "other"]


SCHEMAS = {
    "policy": {
        "carrier": (str, True, None), "kind": (str, True, POLICY_KINDS), "policy_last4": TXT,
        "term_start": TXT, "term_end": TXT, "premium_total": NUM, "payment_plan": (str, False, PLANS),
        "insured_names": TXT, "property_address_city": TXT,
        "vehicles": (list, False, {"year": (int, False, None), "make": TXT, "model": TXT, "vin_last4": TXT, "premium": NUM}),
        "drivers": (list, False, {"name": (str, True, None), "relation": TXT, "excluded": (bool, False, None)}),
        "coverages": (list, False, {"coverage": (str, True, None), "limit": TXT, "deductible": NUM, "premium": NUM,
                                    "vehicle": TXT}),
        "discounts": (list, False, {"name": (str, True, None), "amount": NUM, "vehicle": TXT}),
        "confidence": CONF},
    "id": {"person": (str, True, None), "id_type": (str, True, None), "number_last4": TXT, "issued": TXT,
           "expires": TXT, "authority": TXT, "confidence": CONF},
    "vehicle": {"year": (int, False, None), "make": TXT, "model": TXT, "vin_last4": TXT, "plate_last4": TXT,
                "owner": TXT, "registration_expires": TXT, "inspection_expires": TXT, "confidence": CONF},
    "medical": {"person": TXT, "provider": TXT, "purpose": TXT, "visit_date": TXT, "visit_time": TXT,
                "followup_due": TXT, "confidence": CONF},
    "investment": {"name": (str, True, None), "kind": (str, False, INVEST_KINDS), "current_value": NUM, "invested": NUM,
                   "as_of": TXT, "maturity_date": TXT, "confidence": CONF},
    "tax": {"form": (str, True, None), "tax_year": (int, False, None), "issuer": TXT, "amount": NUM, "confidence": CONF},
    "school_calendar": {"school": TXT, "school_year": TXT,
                        "days": (list, True, {"date": (str, True, None), "end": TXT, "name": (str, True, None),
                                              "kind": (str, False, ["closure", "early", "holiday"])}),
                        "confidence": CONF},
}
STATEMENT = {
    "institution": (str, True, None), "account_type": (str, True, ["checking", "savings", "credit", "loan", "investment"]),
    "account_last4": TXT, "period_start": TXT, "period_end": TXT, "opening_balance": NUM, "closing_balance": NUM,
    "total_in": NUM, "total_out": NUM,
    "transactions": (list, True, {"date": (str, True, None), "description": (str, True, None), "amount": ((int, float), True, None)}),
    "confidence": CONF,
}
DATES = "Dates as YYYY-MM-DD. Numbers as plain numbers (no currency signs). Any account, policy, VIN, plate or ID number: last four characters only."
INSTRUCTIONS = {
    "policy": ("This is an insurance policy document (declarations page, renewal or ID card). Extract: carrier, kind (one of "
               f"{', '.join(POLICY_KINDS)}), policy_last4, term_start, term_end, premium_total (the full-term premium), payment_plan "
               f"(one of {', '.join(PLANS)}), insured_names, property_address_city (city only, home policies), vehicles (year, make, "
               "model, vin_last4, premium for that vehicle), drivers (name, relation to the policyholder, excluded true/false), "
               "coverages (coverage name, limit as printed, deductible, premium, vehicle), discounts (name, amount, vehicle), "
               "confidence (0 to 1). When the paper prints coverages or discounts under each car, list them once per car "
               "and set vehicle to that car's vin_last4 (or year make model when no VIN is printed); leave vehicle empty for "
               "lines that cover the whole policy. Lines that only add up other lines (aggregate or subtotal lines) get no premium."),
    "id": (f"This is an identity document. Extract: person (whose it is), id_type (one of {', '.join(_id_types())}), "
           "number_last4, issued, expires, authority (issuing state or country), confidence (0 to 1)."),
    "vehicle": ("This is a vehicle registration, inspection or title paper. Extract: year, make, model, vin_last4, plate_last4, "
                "owner, registration_expires, inspection_expires, confidence (0 to 1)."),
    "medical": ("This is a medical paper (visit summary, appointment letter, referral). Extract: person (the patient), provider "
                "(clinic or doctor), purpose (a few plain words, no diagnosis), visit_date, visit_time (HH:MM), followup_due (date "
                "of the next visit or follow-up if one is stated), confidence (0 to 1)."),
    "investment": (f"This is an investment statement or certificate. Extract: name (account or fund name), kind (one of "
                   f"{', '.join(INVEST_KINDS)}), current_value, invested (amount put in, if printed), as_of (date of the value), "
                   "maturity_date, confidence (0 to 1)."),
    "tax": ("This is a tax form or tax letter. Extract: form (e.g. W-2, 1099-INT, 1098, property tax bill), tax_year, issuer, "
            "amount (the main amount on it), confidence (0 to 1)."),
    "school_calendar": ("This is a school or school district calendar for a school year. Extract: school (the school or "
                        "district name), school_year (e.g. 2026-27), days: EVERY day students have no school (holidays, "
                        "breaks, teacher work or staff development days, closures) with kind closure, and every early "
                        "dismissal or half day with kind early; name = what the calendar calls it; end = the last day of "
                        "a break that spans several days (leave it out for one day). Leave out the first and last day of "
                        "school, exams, events and sports. confidence (0 to 1)."),
}
STATEMENT_INSTRUCTION = (
    "This is a bank, card or loan statement. Extract: institution, account_type (checking, savings, credit, loan or "
    "investment), account_last4, period_start, period_end, opening_balance and closing_balance as printed (for a card: "
    "the balance owed), and transactions: EVERY line in the period with date, description and amount, where money "
    "leaving the account or a card purchase is negative and money coming in or a payment to the card is positive. "
    "Leave out running-balance, subtotal and summary lines. total_in and total_out: the statement's own printed totals "
    "of money in (deposits and credits; for a card: payments and credits) and money out (withdrawals and debits; for a "
    "card: purchases, fees and interest), as positive numbers, empty when not printed. confidence (0 to 1).")
LIMITS = {"policy": (30000, 8000), "statement": (60000, 12000), "school_calendar": (20000, 4000)}
SCHOOL_DAYS_MAX = 120  # entries kept from one school calendar  # (characters sent, answer tokens); a multi-car policy repeats coverages per car
MIN_CONF = 0.7


class Unusable(ValueError):
    pass


def _order():
    try:
        import country
        return country.profile().get("date_order") or "mdy"
    except Exception:  # noqa: BLE001
        return "mdy"


def _iso(v):
    """YYYY-MM-DD from what a model returned: ISO, else 03/02/2026 read in this country's order (day first where dates
    are written day first), else 'Mar 2, 2026'. None when nothing fits."""
    if not v:
        return None
    s = str(v).strip()
    try:
        return dt.date.fromisoformat(s[:10]).isoformat()
    except ValueError:
        pass
    m = re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})$", s)
    if m:
        a, b, y = (int(x) for x in m.groups())
        y = y + 2000 if y < 100 else y
        mo, da = (b, a) if _order() == "dmy" else (a, b)
        try:
            return dt.date(y, mo, da).isoformat()
        except ValueError:
            return None
    from dates import parse_any
    d = parse_any(s)
    return d.isoformat() if d else None


def _l4(v):
    s = re.sub(r"[^0-9A-Za-z]", "", str(v or ""))
    return s[-4:].upper() if s else None


def _t(v, n=80):
    s = " ".join(str(v or "").split())[:n]
    return s or None


def _num(v):
    if v is None:
        return None
    x = float(v)
    if x < 0 or x > 1e9:
        raise Unusable("an amount is out of range")
    return _money.round2(x)


def read(typ, text):
    """Ask the provider for the fields of `typ`. -> (details, errors). Raises llm.LLMError when no AI can be reached."""
    chars, tokens = LIMITS.get(typ, (12000, 900))
    return llm.extract_json(f"{INSTRUCTIONS[typ]} {DATES}", text, SCHEMAS[typ], purpose=f"details_{typ}", max_tokens=tokens, max_chars=chars)


def prepare(typ, d):
    """Clean and check the answer before anything moves. -> cleaned dict. Raises Unusable with a plain reason."""
    if float(d.get("confidence") or 0) < MIN_CONF:
        raise Unusable(f"not sure about the details (confidence {float(d.get('confidence') or 0):.2f})")
    c = {"confidence": float(d["confidence"])}
    if typ == "policy":
        c.update(carrier=_t(d["carrier"]), kind=d["kind"], policy_last4=_l4(d.get("policy_last4")),
                 term_start=_iso(d.get("term_start")), term_end=_iso(d.get("term_end")),
                 premium_total=_num(d.get("premium_total")), payment_plan=d.get("payment_plan"),
                 insured_names=_t(d.get("insured_names"), 160), city=_t(d.get("property_address_city"), 60))
        if not c["carrier"] or not (c["term_end"] or c["term_start"]):
            raise Unusable("no carrier or no policy dates")
        if c["term_start"] and c["term_end"] and c["term_end"] <= c["term_start"]:
            raise Unusable("the policy ends before it starts")
        c["vehicles"] = [{"year": v.get("year") if v.get("year") and 1950 <= v["year"] <= 2100 else None,
                          "make": _t(v.get("make"), 40), "model": _t(v.get("model"), 40), "vin_last4": _l4(v.get("vin_last4")),
                          "premium": _num(v.get("premium"))} for v in d.get("vehicles") or [] if v.get("make") or v.get("vin_last4")]
        c["drivers"] = [{"name": _t(x["name"], 60), "relation": _t(x.get("relation"), 30), "excluded": bool(x.get("excluded"))}
                        for x in d.get("drivers") or [] if _t(x.get("name"), 60)]
        c["coverages"] = [{"coverage": _t(x["coverage"], 60), "limit": _t(x.get("limit"), 40), "deductible": _num(x.get("deductible")),
                           "premium": _num(x.get("premium")), "vehicle": _t(x.get("vehicle"), 60)}
                          for x in d.get("coverages") or [] if _t(x.get("coverage"), 60)]
        c["discounts"] = [{"name": _t(x["name"], 60), "amount": _num(x.get("amount")), "vehicle": _t(x.get("vehicle"), 60)}
                          for x in d.get("discounts") or [] if _t(x.get("name"), 60)]
    elif typ == "id":
        t = str(d["id_type"]).strip().lower().replace(" ", "_")
        c.update(person=_t(d["person"], 60), id_type=t if t in _id_types() else "other", number_last4=_l4(d.get("number_last4")),
                 issued=_iso(d.get("issued")), expires=_iso(d.get("expires")), authority=_t(d.get("authority"), 40))
        if not c["person"]:
            raise Unusable("whose document it is was not read")
    elif typ == "vehicle":
        c.update(year=d.get("year") if d.get("year") and 1950 <= d["year"] <= 2100 else None, make=_t(d.get("make"), 40),
                 model=_t(d.get("model"), 40), vin_last4=_l4(d.get("vin_last4")), plate_last4=_l4(d.get("plate_last4")),
                 owner=_t(d.get("owner"), 60), registration_expires=_iso(d.get("registration_expires")),
                 inspection_expires=_iso(d.get("inspection_expires")))
        if not (c["vin_last4"] or c["plate_last4"] or c["make"]):
            raise Unusable("which vehicle it is was not read")
        if not (c["registration_expires"] or c["inspection_expires"]):
            raise Unusable("no expiry date")
    elif typ == "medical":
        tm = str(d.get("visit_time") or "")
        c.update(person=_t(d.get("person"), 60), provider=_t(d.get("provider"), 80), purpose=_t(d.get("purpose"), 80),
                 visit_date=_iso(d.get("visit_date")), visit_time=tm if re.fullmatch(r"[0-2]\d:[0-5]\d", tm) else None,
                 followup_due=_iso(d.get("followup_due")))
        if not (c["visit_date"] or c["followup_due"]):
            raise Unusable("no visit or follow-up date")
    elif typ == "investment":
        c.update(name=_t(d["name"]), kind=d.get("kind") or "other", current_value=_num(d.get("current_value")),
                 invested=_num(d.get("invested")), as_of=_iso(d.get("as_of")), maturity_date=_iso(d.get("maturity_date")))
        if not c["name"] or (c["current_value"] is None and not c["maturity_date"]):
            raise Unusable("no account name, value or maturity date")
    elif typ == "tax":
        y = d.get("tax_year")
        c.update(form=_t(d["form"], 40), tax_year=y if y and 1990 <= y <= 2100 else None, issuer=_t(d.get("issuer")),
                 amount=_num(d.get("amount")))
        if not c["form"]:
            raise Unusable("the form was not read")
    elif typ == "school_calendar":
        days, seen = [], set()
        for x in d.get("days") or []:
            a, b = _iso(x.get("date")), _iso(x.get("end"))
            name = _t(x.get("name"), 80)
            if not a or not name or re.search(r"https?:|www\.|[<>{}]", name):
                continue
            if b and (b < a or (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days > 30):
                b = None
            kind = x.get("kind") if x.get("kind") in ("closure", "early") else "closure"
            if (a, kind, name) not in seen:
                seen.add((a, kind, name))
                days.append({"day": a, "end": b if b != a else None, "kind": kind, "name": name})
        if not days:
            raise Unusable("no days off were read")
        days.sort(key=lambda x: x["day"])
        c.update(school=_t(d.get("school"), 60), school_year=_t(d.get("school_year"), 20), days=days[:SCHOOL_DAYS_MAX],
                 first=days[0]["day"])
    else:
        raise Unusable(f"no details are read for {typ}")
    return c


def _member(con, name):
    try:
        import members
        return members.resolve(con, name)
    except Exception:  # noqa: BLE001
        return name


def _vehicle_id(con, year, make, model, vin4, plate4=None):
    """The vehicles row for this car (by VIN or plate last four, else year + make + model), or None."""
    for col, val in (("vin_last4", vin4), ("plate_last4", plate4)):
        if val:
            r = con.execute(f"SELECT id FROM vehicles WHERE UPPER({col})=? AND COALESCE(status,'active')='active'", (val,)).fetchone()
            if r:
                return r[0]
    if make and model:
        r = con.execute("SELECT id FROM vehicles WHERE LOWER(make)=LOWER(?) AND LOWER(model)=LOWER(?) AND (? IS NULL OR year=?) "
                        "AND COALESCE(status,'active')='active'", (make, model, year, year)).fetchall()
        if len(r) == 1:
            return r[0][0]
    return None


def _save_policy(con, c, doc_id):
    hit = con.execute("SELECT id FROM policies WHERE LOWER(carrier)=LOWER(?) AND COALESCE(policy_last4,'')=COALESCE(?,'') "
                      "AND COALESCE(term_start,'')=COALESCE(?,'') AND COALESCE(term_end,'')=COALESCE(?,'')",
                      (c["carrier"], c["policy_last4"], c["term_start"], c["term_end"])).fetchone()
    if hit:
        con.execute("UPDATE policies SET document_id=COALESCE(document_id, ?) WHERE id=?", (doc_id, hit[0]))
        return f"{c['carrier']} {c['kind']} policy: already on file"
    prior = con.execute("SELECT id FROM policies WHERE LOWER(carrier)=LOWER(?) AND kind=? AND COALESCE(policy_last4,'')=COALESCE(?,'') "
                        "AND COALESCE(status,'active')='active' AND term_end IS NOT NULL AND term_end <= COALESCE(?, term_end) "
                        "ORDER BY term_end DESC LIMIT 1",
                        (c["carrier"], c["kind"], c["policy_last4"], c["term_start"])).fetchone()
    pid = con.execute("INSERT INTO policies(kind, carrier, policy_last4, term_start, term_end, premium_total, payment_plan, "
                      "insured_names, property_address, status, document_id, prior_policy_id, notes) VALUES (?,?,?,?,?,?,?,?,?,'active',?,?,?)",
                      (c["kind"], c["carrier"], c["policy_last4"], c["term_start"], c["term_end"], c["premium_total"],
                       c["payment_plan"], c["insured_names"], c["city"], doc_id, prior[0] if prior else None,
                       f"read by AI, confidence {c['confidence']:.2f}")).lastrowid
    if prior:
        con.execute("UPDATE policies SET status='replaced' WHERE id=?", (prior[0],))
    for v in c["vehicles"]:
        vid = _vehicle_id(con, v["year"], v["make"], v["model"], v["vin_last4"])
        if vid is None:
            vid = con.execute("INSERT INTO vehicles(year, make, model, vin_last4, status, notes) VALUES (?,?,?,?, 'active', ?)",
                              (v["year"], v["make"], v["model"], v["vin_last4"], f"from {c['carrier']} policy")).lastrowid
        con.execute("INSERT INTO policy_vehicles(policy_id, vin_last4, year, make, model, premium, vehicle_id) VALUES (?,?,?,?,?,?,?)",
                    (pid, v["vin_last4"], v["year"], v["make"], v["model"], v["premium"], vid))
    for x in c["drivers"]:
        con.execute("INSERT INTO policy_drivers(policy_id, name, relation, excluded) VALUES (?,?,?,?)",
                    (pid, _member(con, x["name"]), x["relation"], int(x["excluded"])))
    _save_lines(con, pid, c)
    bits = [f"{c['carrier']} {c['kind']} policy"]
    if c["term_end"]:
        bits.append(f"renews {c['term_end']}")
    if c["premium_total"] is not None:
        bits.append(f"premium {_money.fmt(c['premium_total'])}")
    if c["vehicles"]:
        bits.append(f"{len(c['vehicles'])} vehicle(s)")
    if c["drivers"]:
        bits.append(f"{len(c['drivers'])} driver(s)")
    if prior:
        bits.append("replaces the earlier term")
    return ", ".join(bits)


def _car(cars, ref):
    """policy_vehicles id for the car a coverage or discount line names (VIN last four, else year/make/model words
    that fit exactly one car on the policy), or None (whole policy, or not sure which car)."""
    if not ref:
        return None
    four = _l4(ref)
    hit = [i for i, vin, *_ in cars if vin and vin == four]
    if len(hit) == 1:
        return hit[0]
    words = set(re.findall(r"[a-z0-9]+", ref.lower()))
    years = {w for w in words if re.fullmatch(r"(19|20)\d\d", w)}

    def fits(year, model):
        mw = set(re.findall(r"[a-z0-9]+", (model or "").lower()))
        return bool(mw) and mw <= words and (not years or str(year) in years)
    hit = [i for i, _, year, _make, model in cars if fits(year, model)]
    return hit[0] if len(hit) == 1 else None


_SUBTOTAL = re.compile(r"\s*(aggregate|sub-?total)\b", re.I)


def _save_lines(con, pid, c):
    """Coverages and discounts of policy `pid`, each tied to its car when printed per car; an exact repeat of a line
    (same car, name, limit, deductible, premium) is kept once. -> (coverages, discounts) written."""
    cars = con.execute("SELECT id, vin_last4, year, make, model FROM policy_vehicles WHERE policy_id=?", (pid,)).fetchall()
    seen, n = set(), [0, 0]
    for x in c["coverages"]:
        vid = _car(cars, x.get("vehicle"))
        premium = None if _SUBTOTAL.match(x["coverage"]) else x["premium"]  # a model may still price a subtotal line
        key = ("c", vid, x["coverage"].lower(), x["limit"], x["deductible"], premium)
        if key not in seen:
            seen.add(key)
            n[0] += 1
            con.execute("INSERT INTO policy_coverages(policy_id, vehicle_id, coverage, limit_text, deductible, premium) VALUES (?,?,?,?,?,?)",
                        (pid, vid, x["coverage"], x["limit"], x["deductible"], premium))
    for x in c["discounts"]:
        vid = _car(cars, x.get("vehicle"))
        key = ("d", vid, x["name"].lower(), x["amount"])
        if key not in seen:
            seen.add(key)
            n[1] += 1
            con.execute("INSERT INTO policy_discounts(policy_id, vehicle_id, name, amount, applied) VALUES (?,?,?,?,1)",
                        (pid, vid, x["name"], x["amount"]))
    return tuple(n)


def reread_policy(con, pid):
    """Read a filed policy's paper again and replace its coverages and discounts (vehicles, drivers and the policy row
    stay). One AI call. -> summary. Raises Unusable with a plain reason."""
    import doc_text
    import records
    row = con.execute("SELECT d.filed_path FROM policies p JOIN documents d ON d.id=p.document_id WHERE p.id=?", (pid,)).fetchone()
    if not row or not row[0]:
        raise Unusable(f"policy {pid} has no filed paper")
    path = records.source_file(row[0])
    if path is None:
        raise Unusable("the policy's paper is not in archive/")
    text, status = doc_text.extract(path)
    if status != "ok":
        raise Unusable(f"the paper could not be read as text ({status})")
    raw, errs = read("policy", text)
    if errs or raw is None:
        raise Unusable("the AI answer was not usable: " + "; ".join(errs[:3]))
    c = prepare("policy", raw)
    con.execute("DELETE FROM policy_coverages WHERE policy_id=?", (pid,))
    con.execute("DELETE FROM policy_discounts WHERE policy_id=?", (pid,))
    nc, nd = _save_lines(con, pid, c)
    tied = con.execute("SELECT (SELECT count(*) FROM policy_coverages WHERE policy_id=? AND vehicle_id IS NOT NULL) + "
                       "(SELECT count(*) FROM policy_discounts WHERE policy_id=? AND vehicle_id IS NOT NULL)", (pid, pid)).fetchone()[0]
    return f"policy {pid}: {nc} coverage(s), {nd} discount(s), {tied} tied to a car"


def _save_id(con, c, doc_id):
    person = _member(con, c["person"])
    ex = con.execute("SELECT id FROM id_documents WHERE person=? AND doc_type=?", (person, c["id_type"])).fetchone()
    if ex:
        con.execute("UPDATE id_documents SET expires=COALESCE(?, expires), issued=COALESCE(?, issued), number_last4=COALESCE(?, number_last4), "
                    "issuing_authority=COALESCE(?, issuing_authority), document_id=?, active=1 WHERE id=?",
                    (c["expires"], c["issued"], c["number_last4"], c["authority"], doc_id, ex[0]))
    else:
        con.execute("INSERT INTO id_documents(person, doc_type, number_last4, issued, expires, issuing_authority, document_id) "
                    "VALUES (?,?,?,?,?,?,?)", (person, c["id_type"], c["number_last4"], c["issued"], c["expires"], c["authority"], doc_id))
    return f"{person} {c['id_type'].replace('_', ' ')}" + (f", expires {c['expires']}" if c["expires"] else ", no expiry printed")


def _save_vehicle(con, c, doc_id):
    vid = _vehicle_id(con, c["year"], c["make"], c["model"], c["vin_last4"], c["plate_last4"])
    if vid is None:
        vid = con.execute("INSERT INTO vehicles(year, make, model, vin_last4, plate_last4, owner, registration_expires, "
                          "inspection_expires, status) VALUES (?,?,?,?,?,?,?,?, 'active')",
                          (c["year"], c["make"], c["model"], c["vin_last4"], c["plate_last4"], c["owner"] and _member(con, c["owner"]),
                           c["registration_expires"], c["inspection_expires"])).lastrowid
    else:
        con.execute("UPDATE vehicles SET registration_expires=COALESCE(?, registration_expires), inspection_expires=COALESCE(?, inspection_expires), "
                    "plate_last4=COALESCE(plate_last4, ?), vin_last4=COALESCE(vin_last4, ?) WHERE id=?",
                    (c["registration_expires"], c["inspection_expires"], c["plate_last4"], c["vin_last4"], vid))
    name = " ".join(str(x) for x in (c["year"], c["make"], c["model"]) if x) or "vehicle"
    parts = [f"registration {c['registration_expires']}" if c["registration_expires"] else "",
             f"inspection {c['inspection_expires']}" if c["inspection_expires"] else ""]
    return f"{name}: " + ", ".join(p for p in parts if p)


def _save_medical(con, c, doc_id):
    person = _member(con, c["person"]) if c["person"] else None
    when = c["visit_date"] or c["followup_due"]
    stamp = when + (f" {c['visit_time']}" if c["visit_time"] and c["visit_date"] else "")
    ex = con.execute("SELECT id FROM appointments WHERE COALESCE(person,'')=COALESCE(?,'') AND substr(appt_datetime,1,10)=? "
                     "AND COALESCE(provider,'')=COALESCE(?,'')", (person, when, c["provider"])).fetchone()
    if ex:
        con.execute("UPDATE appointments SET followup_due=COALESCE(?, followup_due) WHERE id=?", (c["followup_due"], ex[0]))
    else:
        con.execute("INSERT INTO appointments(person, provider, purpose, appt_datetime, followup_due) VALUES (?,?,?,?,?)",
                    (person, c["provider"], c["purpose"] or "Visit", stamp,
                     c["followup_due"] if c["visit_date"] else None))
    s = f"{c['purpose'] or 'visit'}" + (f" for {person}" if person else "") + f" on {when}"
    return s + (f", follow-up by {c['followup_due']}" if c["followup_due"] and c["visit_date"] else "")


def _save_investment(con, c, doc_id):
    ex = con.execute("SELECT id FROM investments WHERE LOWER(name)=LOWER(?)", (c["name"],)).fetchone()
    if ex:
        con.execute("UPDATE investments SET current_value=COALESCE(?, current_value), as_of=COALESCE(?, as_of), "
                    "invested=COALESCE(?, invested), maturity_date=COALESCE(?, maturity_date) WHERE id=?",
                    (c["current_value"], c["as_of"], c["invested"], c["maturity_date"], ex[0]))
    else:
        con.execute("INSERT INTO investments(name, kind, invested, current_value, as_of, maturity_date) VALUES (?,?,?,?,?,?)",
                    (c["name"], c["kind"], c["invested"], c["current_value"], c["as_of"], c["maturity_date"]))
    return c["name"] + (f": {_money.fmt(c['current_value'])}" if c["current_value"] is not None else "") + \
        (f" as of {c['as_of']}" if c["as_of"] else "") + (f", matures {c['maturity_date']}" if c["maturity_date"] else "")


def _save_school_calendar(con, c, doc_id):
    """Each day as a proposed calendar_days row (source school); an adult accepts them in the Inbox."""
    n = 0
    for x in c["days"]:
        n += con.execute("INSERT OR IGNORE INTO calendar_days(day, end_day, kind, name, source, label, status, document_id) "
                         "VALUES (?,?,?,?, 'school', ?, 'proposed', ?)",
                         (x["day"], x["end"], x["kind"], x["name"], c["school"] or "school calendar", doc_id)).rowcount
    return f"{n} school day{'s' if n != 1 else ''} off or early from {c['school'] or 'the school calendar'}" \
        + (f" {c['school_year']}" if c["school_year"] else "") + ", waiting in the Inbox"


def _save_tax(con, c, doc_id):
    return " ".join(x for x in (c["form"], str(c["tax_year"]) if c["tax_year"] else "", f"from {c['issuer']}" if c["issuer"] else "",
                                _money.fmt(c["amount"]) if c["amount"] is not None else "") if x)


SAVE = {"policy": _save_policy, "id": _save_id, "vehicle": _save_vehicle, "medical": _save_medical,
        "investment": _save_investment, "tax": _save_tax, "school_calendar": _save_school_calendar}
DETAILS = tuple(SAVE)


DATE_FIELDS = {"policy": ("term_start", "term_end"), "id": ("issued", "expires"), "vehicle": ("registration_expires", "inspection_expires"),
               "medical": ("visit_date", "followup_due"), "investment": ("as_of", "maturity_date"), "tax": (),
               "school_calendar": ("first",)}


def date_of(typ, c):
    """A date to file the paper under when none was printed on it (policy start, visit date, ...), or None."""
    for k in DATE_FIELDS.get(typ, ()):
        if c.get(k):
            return c[k]
    if typ == "tax" and c.get("tax_year"):
        return f"{c['tax_year']}-12-31"
    return None


def save(con, typ, c, doc_id):
    """Write the prepared details (no commit) and add a one-line summary to the document's note. -> summary."""
    summary = SAVE[typ](con, c, doc_id)
    con.execute("UPDATE documents SET notes=substr(COALESCE(notes,'') || '; ' || ?, 1, 300) WHERE id=?", (summary, doc_id))
    return summary


# ---------- statements the no-AI reader could not use
def read_statement(con, text):
    """Ask the provider for every line of a statement and check it. -> dict like pdf_statement.read() (rows, period,
    begin, end, verified, account). Raises Unusable when the answer cannot be trusted, llm.LLMError without an AI."""
    chars, tokens = LIMITS["statement"]
    if len(text) > chars:
        raise Unusable("the statement is too long for the AI reader; export it as CSV instead")
    d, errs = llm.extract_json(f"{STATEMENT_INSTRUCTION} {DATES}", text, STATEMENT, purpose="details_statement", max_tokens=tokens, max_chars=chars)
    return _checked_statement(con, d, errs)


SCAN_NOTE = ("Some statements print the same lines twice (by date, then again by type, or a daily balance list): "
             "list each line once.")
SCAN_PAGES = 15  # pages of a scanned statement sent to the AI at most (a year of a small account fits)
_HARD = re.compile(r"\b\d{3}-\d{2}-\d{4}\b|\d(?:[ -]?\d){8,}|\b[\w.+-]+@[\w-]+\.[\w.-]+\b")


def _scrub(v):
    """A long number keeps only its last four digits (an x before them), an email address goes: what the AI copied from a scan."""
    return _HARD.sub(lambda m: "[email]" if "@" in m.group() else "x" + re.sub(r"\D", "", m.group())[-4:], v) \
        if isinstance(v, str) else v


def _scrub_statement(d):
    if isinstance(d, dict):
        d["institution"] = _scrub(d.get("institution"))
        for t in d.get("transactions") or []:
            if isinstance(t, dict):
                t["description"] = _scrub(t.get("description"))
    return d


def read_statement_scan(con, path):
    """A scanned statement PDF (pictures of the pages, no text layer) read by the AI from the file itself (opt-in:
    ai.read_receipt_photos, as photos; a scan cannot be masked first). Checked exactly like read_statement: imported
    only when the lines add up to the printed balances. Raises Unusable, or llm.LLMError when the AI cannot be used."""
    try:
        from pypdf import PdfReader
        pages = len(PdfReader(str(path)).pages)
    except Exception:  # noqa: BLE001 (an unreadable PDF: the provider is not asked)
        raise Unusable("the PDF could not be opened") from None
    if pages > SCAN_PAGES:
        raise Unusable(f"the scan has {pages} pages; at most {SCAN_PAGES} are sent to the AI")
    _, tokens = LIMITS["statement"]
    d, errs = llm.extract_image_json(f"{STATEMENT_INSTRUCTION} {SCAN_NOTE} {DATES}", path, STATEMENT, purpose="details_statement_scan",
                                     max_tokens=tokens, clean=_scrub_statement)
    return _checked_statement(con, d, errs)


def _check_printed_totals(d, rows, begin, end, owed):
    """The second check: the statement's own printed totals of money in and money out. Used only when they agree with
    its balances (a figure the AI read wrongly, or a summary that splits purchases and fees, is not a reason to refuse),
    and then the lines must match them too, so two misread lines that cancel each other out are caught."""
    tin, tout = d.get("total_in"), d.get("total_out")
    if not isinstance(tin, (int, float)) or not isinstance(tout, (int, float)):
        return
    tin, tout = abs(float(tin)), abs(float(tout))
    if not _money.eq((begin - tin + tout) if owed else (begin + tin - tout), end):
        return
    got_in = _money.round2(sum(r["amount"] for r in rows if r["amount"] > 0))
    got_out = _money.round2(-sum(r["amount"] for r in rows if r["amount"] < 0))
    if not (_money.eq(got_in, tin) and _money.eq(got_out, tout)):
        raise Unusable(f"lines do not match the printed totals (money in {got_in} against {tin}, "
                       f"money out {got_out} against {tout})")


def _checked_statement(con, d, errs):
    """The AI's statement answer -> dict like pdf_statement.read(), only when its lines add up (see read_statement)."""
    if errs or d is None:
        raise Unusable("the AI answer was not usable: " + "; ".join(errs[:3]))
    if float(d.get("confidence") or 0) < MIN_CONF:
        raise Unusable(f"the AI was not sure (confidence {float(d['confidence']):.2f})")
    last4 = _l4(d.get("account_last4"))
    if not last4:
        raise Unusable("the account's last four digits were not read")
    begin, end = d.get("opening_balance"), d.get("closing_balance")
    if begin is None or end is None:
        raise Unusable("opening or closing balance not read, so the lines cannot be checked")
    rows = []
    for t in d["transactions"][:2000] if isinstance(d["transactions"], list) else []:
        day = _iso(t.get("date"))
        if not day:
            raise Unusable("a line has no readable date")
        rows.append({"date": day, "desc": _t(t["description"], 200) or "(no description)", "amount": _money.round2(t["amount"]),
                     "ref": None, "cardholder": None, "category": None})
    if not rows:
        raise Unusable("no transaction lines")
    kind = d["account_type"]
    total = _money.round2(sum(r["amount"] for r in rows))
    want = (begin - total) if kind in ("credit", "loan") else (begin + total)
    if not _money.eq(want, end):
        raise Unusable(f"lines do not add up to the closing balance (opening {begin}, lines {total}, closing {end})")
    _check_printed_totals(d, rows, begin, end, kind in ("credit", "loan"))
    hit = con.execute("SELECT id, name, type, last4 FROM accounts WHERE last4=?", (last4,)).fetchall()
    if len(hit) > 1:
        raise Unusable(f"more than one account ends in {last4}")
    if hit:
        acct = dict(zip(("id", "name", "type", "last4"), hit[0]))
    else:  # a new account: named after the institution, last four digits only
        name = f"{_t(d['institution'], 40)} {kind}"
        aid = con.execute("INSERT INTO accounts(name, type, last4) VALUES (?,?,?)", (name, kind, last4)).lastrowid
        acct = {"id": aid, "name": name, "type": kind, "last4": last4, "new": True}
    per = (dt.date.fromisoformat(_iso(d.get("period_start")) or min(r["date"] for r in rows)),
           dt.date.fromisoformat(_iso(d.get("period_end")) or max(r["date"] for r in rows)))
    return {"rows": rows, "period": per, "begin": begin, "end": end, "verified": True, "account": acct, "last4": [last4]}


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "fields":
        for t, sc in {**SCHEMAS, "statement": STATEMENT}.items():
            print(f"{t:<11} {', '.join(sc)}")
    elif len(sys.argv) > 2 and sys.argv[1] == "reread-policy":
        import db
        _con = db.connect(paths.DB)
        try:
            print(reread_policy(_con, int(sys.argv[2])))
        except (Unusable, llm.LLMError, ValueError, TypeError) as e:
            print(f"not changed: {e}")
            sys.exit(2)
        _con.commit()
    else:
        print(__doc__)
