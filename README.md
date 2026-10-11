# ReportSimple V2

**Medical lab reports in plain language.** Upload a lab report (PDF, photo or text) and get a simple explanation in English, Bangla or Hindi, a rule-checked status for every test, sourced explanations, a PDF for your doctor, trends across reports, and a chat that only talks about your report.

> Educational tool only. It does not diagnose and is not a substitute for a doctor.

V2 is a rewrite of an earlier prototype (v1, a small Streamlit app). New in V2: mobile web app, sex-specific ranges, sourced explanations, report comparison and trends, PDF for the doctor, grounded chat, voice read-aloud, Hindi, and a measured accuracy test.

## The problem
People get lab reports full of numbers and abbreviations with no explanation. They wait days for a doctor, search confusing information online, or worry about normal values. This is harder for people who are not comfortable with medical English.

## How it works
```
Report (PDF / photo / text)
   -> OCR (Tesseract, pdfplumber)
   -> LLM step 1: EXTRACT name, value, unit, range      (Qwen2.5 via Featherless AI)
   -> RULE ENGINE (rules.py): high / low / normal, age and sex ranges, unit checks, urgency, OCR flags
   -> LLM step 2: EXPLAIN verified results only: summary + questions for the doctor
   -> Sourced test explanations from knowledge.json (written for this project, with a public source)
   -> Web app (index.html): result tabs, graphs, compare, chat, PDF
```
**Key idea:** the AI explains, a rule engine decides. In early tests the model labeled a high HbA1c as low and wrote a wrong summary, so the model is no longer trusted with numbers.

## Features
| Feature | How |
|---|---|
| Rule-checked status | `rules.py` parses the printed range or uses a sex-specific adult table (`ranges.json`) |
| Age / sex ranges | Used only on the server for range choice, never sent to the AI. Under 18 the printed range is used |
| Unit safety | If the report unit differs from the table unit (for example mmol/L), the table range is not used |
| Sourced explanations | `knowledge.json`, each entry links to MedlinePlus |
| Result tabs | Summary, Detailed, Graph (where each value sits in its range) |
| Compare and trends | Saved reports are compared with arrows and a trend chart |
| PDF for the doctor | Generated with reportlab |
| Chat | Answers only about the opened report, never diagnoses or recommends treatment |
| Voice | Browser text-to-speech (voice availability depends on the phone) |
| Languages | English, Bangla, Hindi (AI text). Menus are English |
| Privacy | No login, no database, uploads processed in memory. Saved reports live only in the browser (localStorage). Privacy mode saves nothing |

**Privacy note:** the report text is sent to an AI service (Featherless AI) to be explained. Do not upload names, ID numbers or addresses.

## Accuracy test
`make_synthetic.py` creates made-up reports with known answers and simulated OCR slips. `run_eval.py` compares (A) an LLM that decides status by itself with (B) our pipeline and (C) the pipeline with age and sex.
```bash
export FEATHERLESS_API_KEY=...
python run_eval.py --n 40      # writes results.md and results.json
```
**Results:** _(paste the table from results.md here after running)_

## Run locally
```bash
sudo apt install tesseract-ocr poppler-utils
pip install -r requirements.txt
export FEATHERLESS_API_KEY="your_key"
export FEATHERLESS_MODEL="Qwen/Qwen2.5-7B-Instruct"   # optional
python server.py        # open http://localhost:7860
```
Try the sample reports: `sample_blood_report.pdf`, `sample_critical_report.pdf`, `sample_liver_kidney_thyroid.pdf` (made-up data).

## Deploy
A `Dockerfile` is included (tested only by reading it; build and verify on your host). Set `FEATHERLESS_API_KEY` as a secret on the host, never in the code.

## Limitations
- Reference ranges are typical adult values from common sources; labs differ. Pregnancy and children are not covered. `ranges.json` and `knowledge.json` should be reviewed by a qualified professional.
- OCR can misread blurry photos; the app shows the text it read. A small AI model can write awkward Bangla or Hindi.
- Urgency is a simple rule of thumb, not triage.
- Only the CBC and hemoglobin entries link to a specific MedlinePlus page; the others link to the MedlinePlus lab tests index.
- PDF summaries print Latin text only; Bangla and Hindi summaries appear in the app.
- Not supported: images such as X-rays, prescriptions, wearable data.

## Files
`server.py` Flask API · `index.html` web app · `rules.py` rule engine · `llm.py` prompts and model calls · `report_pdf.py` PDF · `ranges.json`, `knowledge.json` data · `make_synthetic.py`, `run_eval.py` evaluation
