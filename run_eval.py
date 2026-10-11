"""Measure how often each approach gets high / low / normal right, on made-up reports with known answers.

    export FEATHERLESS_API_KEY=...
    python run_eval.py --n 40        ->  results.json and results.md

Systems compared
  A  LLM only          the model reads the report and also decides high/low/normal
  B  Pipeline          model only extracts; the rule engine decides (printed range from the report)
  C  Pipeline + profile  same, but with the person's age and sex (checked against what that person's range is)
"""
import argparse
import json
import os
import time

import llm
import make_synthetic
from rules import analyze_findings, canonical, to_num


def by_key(items):
    out = {}
    for f in items or []:
        if isinstance(f, dict) and f.get("name"):
            k = canonical(f["name"])
            if k and k not in out:
                out[k] = f
    return out


def tally(m, truth_status, got):
    m["tests"] += 1
    if got is None:
        m["missed"] += 1
        return
    m["correct"] += got == truth_status
    m["flips"] += {got, truth_status} == {"high", "low"}


def blank():
    return {"tests": 0, "correct": 0, "missed": 0, "flips": 0, "value_ok": 0, "value_n": 0}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--data", default="synthetic_reports.json")
    a = ap.parse_args(argv)
    if not os.path.exists(a.data):
        make_synthetic.main(["--n", str(a.n), "--seed", str(a.seed), "--out", a.data])
    reports = json.load(open(a.data))[: a.n]
    M = {s: {g: blank() for g in ("all", "clean", "noisy")} for s in ("A_llm_only", "B_pipeline", "C_pipeline_profile")}
    fails = {s: 0 for s in M}
    ocr = {"slips": 0, "flagged": 0}
    for i, rep in enumerate(reports, 1):
        print(f"report {i}/{len(reports)}", end="\r", flush=True)
        grp = "noisy" if rep["noisy"] else "clean"
        truth = {t["key"]: t for t in rep["tests"]}
        try:
            base = by_key(llm.call_json(llm.BASELINE_PROMPT, rep["text"]).get("findings"))
        except Exception:
            base, fails["A_llm_only"] = {}, fails["A_llm_only"] + 1
        try:
            ext = llm.call_json(llm.EXTRACT_PROMPT, rep["text"]).get("findings") or []
            plain, _ = analyze_findings(ext, None, None)
            prof, _ = analyze_findings(ext, rep["age"], rep["sex"])
        except Exception:
            ext, plain, prof = [], [], []
            fails["B_pipeline"] += 1
            fails["C_pipeline_profile"] += 1
        plain, prof = by_key(plain), by_key(prof)
        exk = by_key(ext)
        for k, t in truth.items():
            for sysname, got, want in (("A_llm_only", (base.get(k) or {}).get("status"), t["status_printed"]),
                                       ("B_pipeline", (plain.get(k) or {}).get("status"), t["status_printed"]),
                                       ("C_pipeline_profile", (prof.get(k) or {}).get("status"), t["status_personal"])):
                for g in ("all", grp):
                    tally(M[sysname][g], want, got if got in ("high", "low", "normal") else None)
            if k in exk:  # extraction accuracy (same for B and C)
                v = to_num(exk[k].get("value"))
                for g in ("all", grp):
                    M["B_pipeline"][g]["value_n"] += 1
                    M["B_pipeline"][g]["value_ok"] += v is not None and abs(v - t["value"]) <= 0.005 * abs(t["value"]) + 1e-9
            if t["ocr_slip"]:
                ocr["slips"] += 1
                ocr["flagged"] += "OCR" in (plain.get(k) or {}).get("check", "")
    pct = lambda a_, b_: f"{100 * a_ / b_:.1f}%" if b_ else "n/a"
    names = {"A_llm_only": "A. LLM only", "B_pipeline": "B. Pipeline (rules, printed range)", "C_pipeline_profile": "C. Pipeline + age/sex"}
    lines = [f"Evaluation on {len(reports)} synthetic reports ({M['A_llm_only']['all']['tests']} tests), model {llm.MODEL}", "",
             "| System | Group | Tests | Correct status | High/low flips | Missed |", "|---|---|---|---|---|---|"]
    for s, n in names.items():
        for g in ("all", "clean", "noisy"):
            m = M[s][g]
            lines.append(f"| {n} | {g} | {m['tests']} | {pct(m['correct'], m['tests'])} | {m['flips']} | {m['missed']} |")
    ev = M["B_pipeline"]["all"]
    lines += ["", f"Value extraction accuracy: {pct(ev['value_ok'], ev['value_n'])} of {ev['value_n']} extracted values matched the true value.",
              f"Simulated OCR slips (lost decimal point): {ocr['slips']}; flagged by the OCR check: {ocr['flagged']}.",
              f"Failed calls (JSON or API errors): {fails}", "",
              "Notes: truth for A and B is the status under the range printed on the report; truth for C is the status under the person's own sex-specific range.",
              "Reports are made up. Results show this model and prompt on synthetic data and may differ on real reports."]
    open("results.md", "w").write("\n".join(lines))
    json.dump({"metrics": M, "ocr": ocr, "failed": fails, "model": llm.MODEL, "n": len(reports)}, open("results.json", "w"), indent=1)
    print("\n" + "\n".join(lines))


if __name__ == "__main__":
    main()
