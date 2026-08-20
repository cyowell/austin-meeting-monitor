"""
One-off fix: insert the May 7, 2026 Regular Meeting into the DB,
download and summarize the real agenda PDF, then rebuild the site.
"""
import os
import sys
import sqlite3
from datetime import datetime, date

# Add project root to path so we can reuse the monitor class
sys.path.insert(0, os.path.dirname(__file__))
from austin_meeting_monitor_gemini import AustinCouncilMonitor

DB_PATH = os.path.join(os.path.dirname(__file__), 'austin_meetings.db')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

if not GEMINI_API_KEY:
    print("\n❌ ERROR: GEMINI_API_KEY is not set in your environment.")
    print("   Run: export GEMINI_API_KEY='AIza...'  then try again.\n")
    sys.exit(1)

MEETING = {
    'id':           '20260507-reg',
    'date':         '2026-05-07',
    'meeting_type': 'Regular Meeting',
    'url':          'https://www.austintexas.gov/council/2026/20260507-reg',
    'link_text':    'May 7, 2026 Regular Meeting',
}
AGENDA_URL = 'https://services.austintexas.gov/edims/document.cfm?id=472241'

def main():
    monitor = AustinCouncilMonitor(db_path=DB_PATH, gemini_api_key=GEMINI_API_KEY)

    # Check if already in DB
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT meeting_id, gemini_summary FROM meetings WHERE meeting_id = ?", (MEETING['id'],))
    row = cursor.fetchone()
    conn.close()

    if row:
        print(f"⚠️  Record exists: {row[0]}")
        print(f"   Current summary starts with: {str(row[1])[:120]}")
        print("   Clearing bad summary and re-processing...")
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM meetings WHERE meeting_id = ?", (MEETING['id'],))
        conn.commit()
        conn.close()
    else:
        print("ℹ️  No existing record — inserting fresh.")

    # Download and summarize the PDF
    print(f"\n📥 Downloading agenda PDF: {AGENDA_URL}")
    pdf_path = f"temp_agenda_{MEETING['id']}.pdf"

    if monitor.download_pdf(AGENDA_URL, pdf_path):
        agenda_text = monitor.extract_text_from_pdf(pdf_path)
        try:
            os.remove(pdf_path)
        except Exception:
            pass

        if agenda_text and len(agenda_text) > 200:
            print(f"✓ Extracted {len(agenda_text)} chars from PDF")
            summary = monitor.summarize_agenda(agenda_text)
            print(f"✓ Summary generated ({len(summary)} chars)")
        else:
            print("⚠️  Could not extract text from PDF — using placeholder")
            summary = "Agenda available. Visit the meeting page for full details."
    else:
        print("✗ Failed to download PDF")
        summary = "Agenda PDF available at the city website."

    # Insert into DB (meeting is upcoming — May 7 is in the future)
    today = date.today()
    meeting_date_obj = datetime.strptime(MEETING['date'], '%Y-%m-%d').date()
    is_completed = 1 if meeting_date_obj < today else 0

    monitor.save_meeting(MEETING, AGENDA_URL, summary, is_completed)
    print(f"\n✅ Saved to DB (is_completed={is_completed})")
    print(f"   Summary preview: {summary[:200]}")


if __name__ == '__main__':
    main()
