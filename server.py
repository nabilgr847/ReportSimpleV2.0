"""ReportSimple v2 web server (Flask). Serves the web app and a small JSON API.

Nothing is written to disk or a database. Uploaded files are processed in memory.
"""
import collections
import io
import os
import time

import pdfplumber
import pytesseract
from flask import Flask, abort, jsonify, request, send_file
from pdf2image import convert_from_bytes
from PIL import Image, ImageOps

import llm
from report_pdf import build_pdf
from rules import KB, analyze_findings, to_num, urgency

HERE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
LANGS = {"English": "English", "Bangla": "Bangla (Bengali)", "Hindi": "Hindi"}
OCR_LANGS = os.environ.get("OCR_LANGS", "eng")
MAX_PAGES = 5

# ------------------------------------------------------------------ tiny rate limiter (protects API credit)
_hits = collections.defaultdict(collections.deque)


def limited(bucket, limit, per=60):
    ip = (request.headers.get("X-Forwarded-For", request.remote_addr or "?")).split(",")[0].strip()
    q, now = _hits[(bucket, ip)], time.time()
    while q and now - q[0] > per:
        q.popleft()
    if len(q) >= limit:
        return True
    q.append(now)
    return False


def err(msg, code):
    return jsonify({"error": msg}), code


# ------------------------------------------------------------------ OCR / text
def read_image(data):
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img).convert("L")  # fix phone rotation, grayscale
    if max(img.size) > 3000:
        img.thumbnail((3000, 3000))
    return pytesseract.image_to_string(ImageOps.autocontrast(img), lang=OCR_LANGS)


def extract_text(data, filename):
    name = (filename or "").lower()
    if name.endswith(".txt"):
        return data.decode("utf-8", errors="ignore")
    if name.endswith(".pdf"):
        text = ""
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages[:MAX_PAGES]:
                text += (page.extract_text() or "") + "\n"
        if len(text.strip()) < 30:  # scanned PDF -> OCR
            for img in convert_from_bytes(data, dpi=200, first_page=1, last_page=MAX_PAGES):
                text += pytesseract.image_to_string(img, lang=OCR_LANGS) + "\n"
        return text
    return read_image(data)


# ------------------------------------------------------------------ pipeline
def clean_findings(raw):
    out = []
    for f in (raw or [])[:60]:
        if isinstance(f, dict) and f.get("name"):
            out.append({k: ("" if f.get(k) is None else str(f.get(k))[:80]) for k in ("name", "value", "unit", "normal_range")})
    return out


def run_pipeline(text, lang, age, sex):
    extracted = llm.call_json(llm.EXTRACT_PROMPT, text[:12000])
    findings, stats = analyze_findings(clean_findings(extracted.get("findings")), age, sex)
    if not findings:
        return None
    need = [f["name"] for f in findings if f["key"] not in KB]
    facts = "\n".join(f"- {f['name']}: {f['value']} {f['unit']} (range used {f['range_used'] or 'n/a'}) -> {f['status'].upper()}"
                      for f in findings)
    ex = llm.call_json(llm.EXPLAIN_PROMPT, f"Language: {LANGS[lang]}\nNEED_MEANING: {need}\n\nVerified results:\n{facts}")
    meanings = ex.get("meanings") if isinstance(ex.get("meanings"), dict) else {}
    for f in findings:
        e = KB.get(f["key"])
        f["kb"] = ({"measures": e["measures"], "meaning": e[f["status"]] if f["status"] in ("high", "low") else "",
                    "source": e["source"], "url": e["url"]} if e else None)
        f["ai_meaning"] = "" if e else str(meanings.get(f["name"], ""))[:300]
    qs = ex.get("questions_for_doctor")
    return {"findings": findings, "stats": stats, "level": urgency(findings),
            "summary": str(ex.get("summary", ""))[:1500],
            "questions": [str(q)[:300] for q in qs][:6] if isinstance(qs, list) else []}


def parse_profile(form):
    lang = form.get("lang", "English")
    lang = lang if lang in LANGS else "English"
    try:
        age = int(form.get("age", "")) if form.get("age", "").strip() else None
        age = age if age is not None and 0 < age <= 120 else None
    except ValueError:
        age = None
    sex = form.get("sex", "").lower()
    return lang, age, sex if sex in ("male", "female") else None


# ------------------------------------------------------------------ routes
@app.get("/")
def index():
    return send_file(os.path.join(HERE, "index.html"))


@app.get("/api/health")
def health():
    return jsonify({"ok": True})


@app.post("/api/analyze")
def analyze():
    if limited("analyze", 8):
        return err("Too many requests. Please wait a minute and try again.", 429)
    lang, age, sex = parse_profile(request.form)
    text, f = request.form.get("text", "").strip(), request.files.get("file")
    try:
        if f and f.filename:
            text = extract_text(f.read(), f.filename)
    except Exception:
        return err("Could not read this file. Try a clearer photo or a PDF.", 422)
    if len(text.strip()) < 15:
        return err("No readable text found. Use a clear, flat, well-lit photo, or paste the text.", 422)
    try:
        res = run_pipeline(text.strip(), lang, age, sex)
    except Exception:
        return err("The AI service is busy or returned an unexpected answer. Please try again.", 502)
    if res is None:
        return err("No lab values were found in this report.", 422)
    res["text_read"] = text.strip()[:6000]
    return jsonify(res)


@app.post("/api/pdf")
def pdf():
    d = request.get_json(silent=True) or {}
    r = d.get("result") or {}
    if not isinstance(r.get("findings"), list):
        return err("Bad request", 400)
    data = build_pdf(clean_pdf_findings(r["findings"]), str(r.get("summary", ""))[:1500],
                     [str(q)[:300] for q in r.get("questions", [])][:6], r.get("level", "routine"), KB,
                     str(d.get("date", ""))[:10], d.get("age"), d.get("sex"))
    return send_file(io.BytesIO(data), mimetype="application/pdf", as_attachment=True, download_name="reportsimple_summary.pdf")


def clean_pdf_findings(items):
    keep = ("name", "value", "unit", "status", "range_used", "range_source", "key", "conflict", "check")
    return [{k: str(f.get(k, ""))[:200] for k in keep} for f in items[:60] if isinstance(f, dict)]


@app.post("/api/chat")
def chat():
    if limited("chat", 20):
        return err("Too many messages. Please wait a minute.", 429)
    d = request.get_json(silent=True) or {}
    msg, items = str(d.get("message", "")).strip()[:500], d.get("findings")
    lang = d.get("lang") if d.get("lang") in LANGS else "English"
    if not msg or not isinstance(items, list) or not items:
        return err("Open a report first, then ask about it.", 400)
    lines, notes = [], []
    for f in clean_pdf_findings(items):
        lines.append(f"- {f['name']}: {f['value']} {f['unit']} (range {f['range_used'] or 'n/a'}) -> {f['status'].upper()}")
        e = KB.get(f["key"])
        if e and f["status"] in ("high", "low"):
            notes.append(f"{f['name']}: {e['measures']} {e[f['status']]}")
    system = f"{llm.CHAT_PROMPT}\n\nReply language: {LANGS[lang]}\n\nVERIFIED RESULTS:\n" + "\n".join(lines) + \
             ("\n\nBACKGROUND:\n" + "\n".join(notes) if notes else "")
    hist = []
    for h in (d.get("history") or [])[-6:]:
        if isinstance(h, dict) and h.get("role") in ("user", "assistant"):
            hist.append({"role": h["role"], "content": str(h.get("content", ""))[:600]})
    try:
        reply = llm.call_text(system, hist + [{"role": "user", "content": msg}])
    except Exception:
        return err("The AI service is busy. Please try again.", 502)
    return jsonify({"reply": reply})


@app.errorhandler(413)
def too_big(_):
    return err("File too large (max 10 MB).", 413)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 7860)))
