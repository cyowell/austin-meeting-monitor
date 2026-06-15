import os
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from pathlib import Path
import re

BASE_URL = "https://www.austintexas.gov"
INDEX_URL = f"{BASE_URL}/council/2026/2026_master_index"
START_DATE = datetime(2026, 1, 14)
END_DATE = datetime(2026, 3, 5)

OUTPUT_DIR = Path("historical/2020s/2026")

def parse_date(date_str):
    try:
        return datetime.strptime(date_str, "%B %d, %Y")
    except ValueError:
        return None

def process_meeting(href, date_str, title, meeting_type, meeting_date):
    # Ensure href does not double the base URL if it's already absolute
    if href.startswith('http'):
        meeting_url = href
    else:
        meeting_url = BASE_URL + href
        
    meeting_id = meeting_url.rstrip('/').split('/')[-1]
    
    print(f"Processing {date_str} - {title} ({meeting_id})")
    
    response = requests.get(meeting_url, timeout=10)
    if response.status_code != 200:
        print(f"  -> Failed to fetch {meeting_url}")
        return
    
    soup = BeautifulSoup(response.content, "html.parser")
    
    # Check for cancellation
    if soup.find(string=lambda text: "Cancellation" in text if text else False):
        print("  -> Skipped (Cancellation Notice)")
        return
        
    agenda_url = None
    pdf_url = None
    video_url = None
    actions_url = None
    
    for link in soup.find_all("a"):
        text = link.get_text().strip()
        link_href = link.get('href', '')
        
        if not link_href:
            continue
            
        # Resolve relative URLs
        if link_href.startswith('/'):
            link_href = BASE_URL + link_href
            
        if "Agenda" in text and "Packet" not in text and "Cancellation" not in text and not agenda_url:
            agenda_url = link_href
        
        if "Transcript" in text:
            pdf_url = link_href
            
        if "swagit.com/play" in link_href:
            video_url = link_href
            
        if "action_notes.cfm" in link_href or "Actions" in text:
            actions_url = link_href

    # Fallback to Agenda if Transcript doesn't exist
    if not pdf_url:
        pdf_url = agenda_url
        
    date_formatted = meeting_date.strftime("%Y-%m-%d")
    
    data = {
        "meeting_id": meeting_id,
        "title": title,
        "meeting_type": meeting_type,
        "date": date_formatted,
        "year": 2026,
        "meeting_url": meeting_url,
        "agenda_url": agenda_url,
        "video_url": video_url,
        "actions_url": actions_url,
        "pdf_url": pdf_url,
        "summary_source": None,
        "summary": None,
        "topics": [],
        "transcript": None
    }
    
    filename = f"{date_formatted}_{meeting_id}.json"
    filepath = OUTPUT_DIR / filename
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    print(f"  -> Saved {filepath}")

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    print("Fetching master index...")
    response = requests.get(INDEX_URL, timeout=10)
    soup = BeautifulSoup(response.content, "html.parser")
    
    links = soup.find_all("a", class_="edims")
    
    processed_count = 0
    skipped_count = 0
    
    for link in links:
        href = link.get('href')
        if not href or '/council/2026/' not in href:
            continue
            
        raw_text = link.get_text().replace('\xa0', ' ')
        text = re.sub(r'\s+', ' ', raw_text).strip()
        
        date_match = re.match(r'^([A-Z][a-z]+ \d{1,2}, \d{4})', text)
        if not date_match:
            continue
            
        date_str = date_match.group(1)
        meeting_date = parse_date(date_str)
        if not meeting_date:
            continue
            
        if START_DATE <= meeting_date <= END_DATE:
            # We use the full text as title for now, or just the remainder
            title = text
            meeting_type = text[len(date_str):].strip()
            
            process_meeting(href, date_str, title, meeting_type, meeting_date)
            processed_count += 1
        else:
            skipped_count += 1

    print(f"\nDone! Processed {processed_count} meetings in range. Skipped {skipped_count} outside range.")

if __name__ == "__main__":
    main()
