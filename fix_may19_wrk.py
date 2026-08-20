"""
One-off fix: Insert May 19 Work Session into DB (with Gemini summary),
then trigger email send for all unnotified meetings (May 19 wrk + May 21 reg).

Run with:
  GEMINI_API_KEY=xxx RESEND_API_KEY=xxx python3 fix_may19_wrk.py
"""

import os
import sqlite3
import requests
import fitz  # PyMuPDF
from datetime import datetime, date

# ── Gemini ──────────────────────────────────────────────────────────────────
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '')
DB_PATH = 'austin_meetings.db'

MEETING_ID   = '20260519-wrk'
MEETING_DATE = '2026-05-19'
MEETING_TYPE = 'Work Session'
MEETING_URL  = 'https://www.austintexas.gov/council/2026/20260519-wrk'
AGENDA_URL   = 'https://services.austintexas.gov/edims/document.cfm?id=473411'


def already_in_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT meeting_id FROM meetings WHERE meeting_id = ?', (MEETING_ID,))
    exists = c.fetchone() is not None
    conn.close()
    return exists


def download_and_extract_pdf():
    headers = {'User-Agent': 'Mozilla/5.0 (Austin Council Monitor - Public Information Tool)'}
    r = requests.get(AGENDA_URL, headers=headers, timeout=30)
    r.raise_for_status()
    pdf_path = f'temp_{MEETING_ID}.pdf'
    with open(pdf_path, 'wb') as f:
        f.write(r.content)
    doc = fitz.open(pdf_path)
    text = ''
    for page in doc:
        text += page.get_text()
    doc.close()
    os.remove(pdf_path)
    print(f'  ✓ Extracted {len(text)} chars from PDF')
    return text


def gemini_summary(text):
    if not GEMINI_AVAILABLE or not GEMINI_API_KEY:
        print('  ⚠️  Gemini not configured — using fallback summary')
        return _fallback_summary()

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')
    prompt = f"""Summarize this Austin City Council agenda in 3-5 bullet points.
Focus on the most important items, public hearings, and policy decisions.
Keep it concise and accessible to the general public.

Agenda text:
{text[:100000]}"""
    response = model.generate_content(prompt)
    summary = response.text.strip()
    print(f'  ✓ Gemini summary generated ({len(summary)} chars)')
    return summary


def _fallback_summary():
    return (
        "* **Austin Energy Peaker Units (A7):** Council will discuss implementation of "
        "natural gas-powered peaker generation units as part of Austin Energy's Resource, "
        "Generation and Climate Protection Plan to 2035, pulled by Council Member Siegel.\n"
        "* **A/V & Broadcast Contracts (A23):** Council will discuss six contracts totaling "
        "up to $36M for audio/visual and television broadcast equipment for all City departments, "
        "pulled by Council Members Alter and Laine.\n"
        "* **FY 2026–2027 Budget Priorities (B1):** Council will receive a briefing on priorities "
        "for the upcoming fiscal year budget development process.\n"
        "* **2026 Bond Program (B2):** Staff will present recommendations on elements of a potential "
        "2026 bond program and election.\n"
        "* **Dog's Head Development (B3):** Council will discuss a proposed development agreement "
        "and future annexation of a 2,614-acre mixed-use development in the City's ETJ near the "
        "Colorado River, US-183, and SH-130, including a potential TIRZ and local government corporation."
    )


def insert_meeting(summary):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO meetings
          (meeting_id, date, meeting_type, meeting_url, agenda_url,
           gemini_summary, created_at, is_completed)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        MEETING_ID,
        MEETING_DATE,
        MEETING_TYPE,
        MEETING_URL,
        AGENDA_URL,
        summary,
        datetime.now().isoformat(),
        0,  # upcoming — May 19 is still in the future as of today (May 14)
    ))
    conn.commit()
    conn.close()
    print(f'  ✓ Inserted {MEETING_ID} into database')


def send_emails():
    """Use email_sender to send alerts for all unnotified meetings"""
    if not RESEND_API_KEY:
        print('  ⚠️  No RESEND_API_KEY — skipping email send')
        return

    from email_sender import MeetingEmailSender
    sender = MeetingEmailSender(api_key=RESEND_API_KEY, db_path=DB_PATH)
    count = sender.send_alerts()
    print(f'  ✓ Emails sent: {count}')


if __name__ == '__main__':
    print('=' * 60)
    print('FIX: May 19 Work Session patch')
    print('=' * 60)

    if already_in_db():
        print(f'  ℹ️  {MEETING_ID} already in DB — skipping insert')
    else:
        print(f'\n📥 Downloading and extracting agenda PDF...')
        try:
            text = download_and_extract_pdf()
        except Exception as e:
            print(f'  ✗ PDF download failed: {e} — using fallback summary')
            text = None

        print('\n🤖 Generating summary...')
        summary = gemini_summary(text) if text else _fallback_summary()

        print('\n💾 Inserting into database...')
        insert_meeting(summary)

    print('\n📧 Sending email alerts for all unnotified meetings...')
    send_emails()

    print('\n✅ Done! Now run: python3 github_pages_publisher.py && git add -A && git commit && git push')
