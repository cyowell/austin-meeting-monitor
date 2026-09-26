import sqlite3

db_path = 'austin_meetings.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

updates = [
    (
        "20260716-reg",
        "Title: Austin Budget Hearings and Police Funding\n\n"
    ),
    (
        "20260722-reg",
        "Title: Austin Budget Work Session on Social Services\n\n"
    ),
    (
        "20260723-ahfc",
        "Title: AHFC Approves 4800 Bowman Road Acquisition\n\n"
    ),
    (
        "20260728-reg",
        "Title: Austin Discusses New Budget and Charter Changes\n\n"
    )
]

for mid, title_prefix in updates:
    cursor.execute("SELECT post_meeting_summary FROM meetings WHERE meeting_id = ?", (mid,))
    row = cursor.fetchone()
    if row and row[0]:
        summary = row[0]
        # Remove any existing boilerplate
        if "Here's what the Austin Housing Finance Corporation" in summary:
            summary = summary.split('\n\n', 1)[1]
        elif "Here's a summary of what the Austin City Council actually did" in summary:
            summary = summary.split('\n\n', 1)[1]
        
        new_summary = title_prefix + summary
        cursor.execute("UPDATE meetings SET post_meeting_summary = ? WHERE meeting_id = ?", (new_summary, mid))
        print(f"Updated {mid}")

conn.commit()
conn.close()
