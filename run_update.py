import sqlite3
import os
import json
from pathlib import Path
from austin_meeting_monitor_gemini import AustinCouncilMonitor

monitor = AustinCouncilMonitor(gemini_api_key=os.getenv('GEMINI_API_KEY'))
monitor.init_database()

conn = sqlite3.connect('austin_meetings.db')
cursor = conn.cursor()
cursor.execute("UPDATE meetings SET completed_processed_at = NULL, transcript_url = NULL, transcript_text = NULL WHERE date LIKE '%05-28%'")
conn.commit()
conn.close()

monitor.process_completed_meetings()
