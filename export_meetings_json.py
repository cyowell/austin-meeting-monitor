import sqlite3
import os
import json
from pathlib import Path

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / 'real-time'

def write_meeting_json(row):
    # row is a sqlite3.Row
    meeting_id = row['meeting_id']
    try:
        date_short = row['date'] # "YYYY-MM-DD"
        year = int(date_short.split('-')[0]) if date_short else None

        filename = f"{date_short}_{meeting_id}.json"
        path = OUTPUT_DIR / filename
        path.parent.mkdir(parents=True, exist_ok=True)

        summary = row['post_meeting_summary'] or row['gemini_summary']
        title = ""
        if summary:
            # retrieved from the summary AI in first line
            for line in summary.split('\n'):
                if line.strip():
                    title = line.strip()
                    if title.lower().startswith('title:'):
                        title = title[6:].strip()
                    title = title.replace('**', '').replace('*', '').strip()
                    break

        transcript = row['transcript_text']

        # PRESERVE EXISTING GOOD DATA
        # If the JSON file already exists on disk, we should not overwrite any manually corrected
        # titles or transcripts with empty or inferred data from the database.
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
                
                # Preserve title if the existing one is good (doesn't start with "Here's a summary")
                if existing_data.get('title') and not existing_data['title'].startswith("Here's a summary"):
                    title = existing_data['title']
                
                # Preserve transcript if it exists
                if existing_data.get('transcript'):
                    transcript = existing_data['transcript']
            except Exception as e:
                print(f"Warning: could not read existing {path}: {e}")

        data = {
            'meeting_id': meeting_id,
            'title': title,
            'meeting_type': row['meeting_type'],
            'date': date_short,
            'year': year,
            'meeting_url': row['meeting_url'],
            'agenda_url': row['agenda_url'],
            'video_url': row['video_url'],
            'actions_url': row['actions_url'],
            'pdf_url': row['transcript_url'],
            'summary_source': 'gemini-2.5-flash',
            'summary': summary,
            'topics': [], # We don't have topics extraction natively yet in DB
            'transcript': transcript,
        }

        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
            
        return f"OK: {path}"

    except Exception as e:
        return f"FAILED {meeting_id}: {type(e).__name__}: {e}"

def main():
    conn = sqlite3.connect(BASE_DIR / 'austin_meetings.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT 
            meeting_id,
            date,
            meeting_type,
            meeting_url,
            agenda_url,
            video_url,
            actions_url,
            gemini_summary,
            post_meeting_summary,
            transcript_url,
            transcript_text
        FROM meetings
        WHERE date >= '2026-03-12' AND completed_processed_at IS NOT NULL
    """)
    
    rows = cursor.fetchall()
    print(f"Processing {len(rows)} rows...")
    
    for row in rows:
        result = write_meeting_json(row)
        print(result)

if __name__ == '__main__':
    main()
