import sqlite3
import re

db_path = 'austin_meetings.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

cursor.execute("SELECT meeting_id, post_meeting_summary FROM meetings WHERE post_meeting_summary IS NOT NULL")
rows = cursor.fetchall()

updated = 0
for row in rows:
    meeting_id, summary = row
    
    # Strip prefixes like "Here's a summary of what the Austin City Council did at its August 12, 2026, meeting:"
    new_summary = re.sub(r"^Here's a summary of what the Austin City Council did at its.*?:", "", summary, flags=re.IGNORECASE).strip()
    
    # Also strip "Here's a summary of what the Austin City Council did..." without date
    new_summary = re.sub(r"^Here's a summary of what the Austin City Council did.*?:", "", new_summary, flags=re.IGNORECASE).strip()

    if new_summary != summary:
        cursor.execute("UPDATE meetings SET post_meeting_summary = ? WHERE meeting_id = ?", (new_summary, meeting_id))
        updated += 1
        print(f"Updated {meeting_id}")

conn.commit()
conn.close()
print(f"Total updated: {updated}")
