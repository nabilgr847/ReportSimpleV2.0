"""Rule engine v2: deterministic status, age/sex-aware ranges, urgency and OCR flags.

The language model never decides high/low/normal. This module does.
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return json.load(f)


RANGES = _load("ranges.json")
KB = _load("knowledge.json")["tests"]
TESTS = {t["key"]: t for t in RANGES["tests"]}

# ---------------------------------------------------------------- name matching
EXCLUDE = ("vldl", "nonhdl", "ratio", "direct", "indirect", "mean", "volume",
           "distribution", "percent", "%", "crit", "index")


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _tokens(s):
    return set(t for t in re.split(r"[^a-z0-9]+", str(s).lower()) if t)


_SHORT, _LONG = [], []
for _t in RANGES["tests"]:
    for _a in _t["aliases"]:
        n = _norm(_a)
        (_SHORT if len(n) <= 3 else _LONG).append((n, _t["key"]))
_SHORT.sort(key=lambda x: -len(x[0]))
_LONG.sort(key=lambda x: -len(x[0]))


def canonical(name):
    """Map a test name from a report to a known test key, or None."""
    n, toks = _norm(name), _tokens(name)
    if not n or any(x in str(name).lower().replace(" ", "") for x in EXCLUDE) or "non" in toks and "hdl" in toks:
        return None
    for a, k in _SHORT:
        if a in toks:
            return k
    for a, k in _LONG:
        if a in n:
            return k
    return None


# ---------------------------------------------------------------- numbers and ranges
def to_num(s):
    m = re.search(r"-?\d[\d,]*\.?\d*", str(s))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def parse_range(s):
    """'13.0 - 17.0' -> (13.0, 17.0); '< 200' -> (None, 200); '> 40' -> (40, None)."""
    s = str(s or "").replace(",", "")
    m = re.search(r"(\d+\.?\d*)\s*[-–]\s*(\d+\.?\d*)", s)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = re.search(r"[<≤]\s*(\d+\.?\d*)", s)
    if m:
        return None, float(m.group(1))
    m = re.search(r"[>≥]\s*(\d+\.?\d*)", s)
    if m:
        return float(m.group(1)), None
    return None


def fmt_range(rng):
    if not rng:
        return "n/a"
    lo, hi = rng
    if lo is not None and hi is not None:
        return f"{lo:g} - {hi:g}"
    if hi is not None:
        return f"< {hi:g}"
    return f"> {lo:g}"


def status(v, lo, hi):
    if lo is not None and v < lo:
        return "low"
    if hi is not None and v > hi:
        return "high"
    return "normal"


def _unit_norm(u):
    return re.sub(r"\s+", "", str(u or "").lower().replace("µ", "u").replace("μ", "u"))


def _mid(r):
    lo, hi = r
    if lo is not None and hi is not None:
        return (lo + hi) / 2
    return hi if hi is not None else lo


# ---------------------------------------------------------------- personalized range
def table_range(key, sex, age):
    """Range from ranges.json for this person, or None. Needs adult age and a stated sex for sex-specific tests."""
    t = TESTS.get(key)
    if not t:
        return None, ""
    r = t["ranges"]
    adult = age is not None and age >= 18
    if "any" in r:
        return tuple(r["any"]), "general adult table"
    if adult and sex in r:
        return tuple(r[sex]), f"adult {sex} table"
    return None, ""


def _plausible(f, key, rng, printed):
    """Check that the report unit/magnitude matches the table unit, so we never compare mg/dL to mmol/L."""
    t = TESTS[key]
    u = _unit_norm(f.get("unit"))
    if u:
        return u in t["units"]
    ref = printed or rng
    tbl = rng
    if ref and tbl and _mid(ref) and _mid(tbl):
        ratio = _mid(ref) / _mid(tbl)
        return 0.33 <= ratio <= 3
    v = to_num(f.get("value"))
    return bool(v and tbl and _mid(tbl) and 0.05 <= v / _mid(tbl) <= 20)


# ---------------------------------------------------------------- main entry
def analyze_findings(findings, age=None, sex=None):
    """Return (checked_findings, stats). Each finding gets status, range_used, range_source, conflict, check."""
    sex = sex if sex in ("male", "female") else None
    out = []
    stats = {"checked": 0, "personalized": 0, "conflicts": 0, "unchecked": 0, "ocr_suspect": 0}
    for f in findings:
        f = dict(f)
        v = to_num(f.get("value"))
        key = canonical(f.get("name"))
        printed = parse_range(f.get("normal_range"))
        f.update(key=key, printed_range=fmt_range(printed) if printed else "", conflict="", check="",
                 deviation=0.0, range_used="", range_source="", status="unclear")
        tbl, tbl_src = (None, "")
        if key and age is not None and age >= 18 or key and not printed:
            tbl, tbl_src = table_range(key, sex, age)
            if tbl and not _plausible(f, key, tbl, printed):
                tbl, tbl_src = None, ""
        # personalized range wins only if a stated age/sex was needed and applied
        use, src = None, ""
        if tbl and age is not None and age >= 18 and sex and "any" not in TESTS[key]["ranges"]:
            use, src = tbl, tbl_src + f" ({sex}, age {age})"
            stats["personalized"] += 1
        elif printed:
            use, src = printed, "range printed on the report"
        elif tbl:
            use, src = tbl, tbl_src
        if v is None or use is None:
            f["check"] = "Not auto-verified (no readable value or range)"
            stats["unchecked"] += 1
            out.append(f)
            continue
        lo, hi = use
        st = status(v, lo, hi)
        f.update(status=st, range_used=fmt_range(use), range_source=src, range_nums=[lo, hi])
        f["deviation"] = (v - hi) / hi if st == "high" and hi else (lo - v) / lo if st == "low" and lo else 0.0
        if printed and use is not printed:
            ps = status(v, *printed)
            if ps != st:
                f["conflict"] = (f"The report's printed range ({fmt_range(printed)}) would give {ps.upper()}, "
                                 f"but the {src} gives {st.upper()}. Ask your doctor which range applies.")
                stats["conflicts"] += 1
        decimals = any(b is not None and b != int(b) for b in (lo, hi))
        if st != "normal" and decimals and v == int(v) and status(v / 10, lo, hi) == "normal":
            f["check"] = f"Possible OCR error: maybe {v / 10:g}. Check the original report."
            stats["ocr_suspect"] += 1
        stats["checked"] += 1
        out.append(f)
    return out, stats


def urgency(findings):
    """Simple heuristic (not clinical triage)."""
    worst = "routine"
    for f in findings:
        if f.get("status") in ("high", "low"):
            worst = "see_doctor_soon"
            if f.get("deviation", 0) >= (1.0 if f["status"] == "high" else 0.7):
                return "urgent"
    return worst
