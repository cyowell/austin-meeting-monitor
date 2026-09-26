import sqlite3
import os
from austin_meeting_monitor_gemini import AustinCouncilMonitor

def main():
    monitor = AustinCouncilMonitor()
    conn = sqlite3.connect('austin_meetings.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    ids = ['20260728-reg', '20260723-ahfc', '20260722-reg', '20260716-reg']
    for mid in ids:
        cursor.execute("SELECT * FROM meetings WHERE meeting_id = ?", (mid,))
        row = cursor.fetchone()
        if not row:
            print(f"Not found: {mid}")
            continue
            
        meeting_data = dict(row)
        transcript_text = row['transcript_text']
        
        # generate new summary using the updated prompt
        print(f"Generating summary for {mid}...")
        summary = monitor.generate_post_meeting_summary(meeting_data, None, transcript_text, None)
        
        cursor.execute("UPDATE meetings SET post_meeting_summary = ? WHERE meeting_id = ?", (summary, mid))
        print(f"Updated {mid} with new summary")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    main()
