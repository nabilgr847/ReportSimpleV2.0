"""Generate made-up lab reports with known ground truth, for measuring accuracy.

    python make_synthetic.py --n 40 --seed 7   ->  synthetic_reports.json

All patients and values are invented. About a third of the reports get simulated OCR slips.
"""
import argparse
import json
import random

from rules import TESTS, fmt_range, status


def pick_value(rng, r, want):
    lo, hi = r
    if lo is not None and hi is not None:
        sp = hi - lo
        v = {"normal": rng.uniform(lo + 0.1 * sp, hi - 0.1 * sp), "high": hi + rng.uniform(0.05, 0.8) * sp,
             "low": lo - rng.uniform(0.05, 0.5) * sp}[want]
    elif hi is not None:
        v = {"normal": rng.uniform(0.5 * hi, 0.95 * hi), "high": hi * (1 + rng.uniform(0.05, 0.8)), "low": rng.uniform(0.3 * hi, 0.5 * hi)}[want]
    else:
        v = {"normal": lo * (1 + rng.uniform(0.05, 0.6)), "low": lo * (1 - rng.uniform(0.05, 0.4)), "high": lo * 2}[want]
    v = max(v, 0.1)
    return int(round(v)) if v >= 100 else round(v, 1)


def fmt_val(v, key):
    return f"{v:,}" if isinstance(v, int) and v >= 1000 and key in ("wbc", "platelets") else str(v)


FORMATS = [
    lambda n, v, u, r: f"{n:<28}{v} {u}   {r}",
    lambda n, v, u, r: f"{n.upper()}: {v} {u} [Ref: {r}]",
    lambda n, v, u, r: f"{n} | {v} | {u} | {r}",
    lambda n, v, u, r: f"{n}  {v}  {r}  {u}",
]


def make_report(rng, idx):
    sex, age = rng.choice(["male", "female"]), rng.randint(18, 80)
    keys = rng.sample(list(TESTS), rng.randint(8, 14))
    fmt, noisy = rng.choice(FORMATS), rng.random() < 0.33
    generic = rng.random() < 0.25  # lab prints one combined (male) range for everyone
    lines, tests = ["CityCare Diagnostic Laboratory (synthetic)", f"Patient: Synthetic {idx}   Age/Sex: {age}/{sex[0].upper()}", ""], []
    for k in keys:
        t = TESTS[k]
        personal = tuple(t["ranges"].get(sex) or t["ranges"].get("any"))
        printed = tuple(t["ranges"].get("male") or t["ranges"].get("any")) if generic else personal
        v = pick_value(rng, personal, rng.choices(["normal", "high", "low"], [0.5, 0.25, 0.25])[0])
        shown, dropped = fmt_val(v, k), False
        if noisy and rng.random() < 0.2 and isinstance(v, float):
            shown, dropped = str(v).replace(".", ""), True  # simulated OCR slip: lost decimal point
        lines.append(fmt(t["name"], shown, t["unit"], fmt_range(printed)))
        tests.append({"key": k, "name": t["name"], "value": v, "unit": t["unit"], "printed_range": fmt_range(printed),
                      "status_printed": status(v, *printed), "status_personal": status(v, *personal), "ocr_slip": dropped})
    return {"id": idx, "age": age, "sex": sex, "noisy": noisy, "text": "\n".join(lines), "tests": tests}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="synthetic_reports.json")
    a = ap.parse_args(argv)
    rng = random.Random(a.seed)
    data = [make_report(rng, i + 1) for i in range(a.n)]
    json.dump(data, open(a.out, "w"), indent=1)
    print(f"wrote {a.out}: {len(data)} reports, {sum(len(d['tests']) for d in data)} tests")


if __name__ == "__main__":
    main()
