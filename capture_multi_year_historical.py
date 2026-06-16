import os
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from pathlib import Path
import re
import time

BASE_URL = "https://www.austintexas.gov"
ARCHIVES_URL = f"{BASE_URL}/council/archive/city_council_meeting_archives"
START_YEAR = 2004
END_YEAR = 2025

def get_decade(year):
    return f"{year // 10 * 10}s"

def parse_date(date_str):
    try:
        return datetime.strptime(date_str, "%B %d, %Y")
    except ValueError:
        return None

def process_meeting(href, date_str, title, meeting_type, meeting_date, year):
    # Ensure href does not double the base URL if it's already absolute
    if href.startswith('http'):
        meeting_url = href
    else:
        meeting_url = BASE_URL + href
        
    meeting_id = meeting_url.rstrip('/').split('/')[-1]
    
    print(f"  Processing {date_str} - {meeting_id}")
    
    try:
        response = requests.get(meeting_url, timeout=10)
    except Exception as e:
        print(f"    -> Request failed: {e}")
        return
        
    if response.status_code != 200:
        print(f"    -> Failed to fetch {meeting_url}")
        return
    
    soup = BeautifulSoup(response.content, "html.parser")
    
    # Check for cancellation
    if soup.find(string=lambda text: "Cancellation" in text if text else False):
        print("    -> Skipped (Cancellation Notice)")
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
        
    decade = get_decade(year)
    output_dir = Path(f"historical/{decade}/{year}")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    date_formatted = meeting_date.strftime("%Y-%m-%d")
    filename = f"{date_formatted}_{meeting_id}.json"
    filepath = output_dir / filename
    
    if filepath.exists():
        print(f"    -> Skipped (Already exists: {filepath})")
        return
        
    data = {
        "meeting_id": meeting_id,
        "title": title,
        "meeting_type": meeting_type,
        "date": date_formatted,
        "year": year,
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
    
    decade = get_decade(year)
    output_dir = Path(f"historical/{decade}/{year}")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    filename = f"{date_formatted}_{meeting_id}.json"
    filepath = output_dir / filename
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    print(f"    -> Saved {filepath}")

def extract_year_links():
    print("Fetching master archives page...")
    response = requests.get(ARCHIVES_URL, timeout=10)
    soup = BeautifulSoup(response.content, "html.parser")
    
    year_links = {}
    for a in soup.find_all('a'):
        text = a.get_text(strip=True)
        if text.isdigit():
            year = int(text)
            if START_YEAR <= year <= END_YEAR:
                href = a.get('href')
                if href:
                    if href.startswith('/'):
                        href = BASE_URL + href
                    year_links[year] = href
    
    return year_links

def process_year(year, index_url):
    print(f"\n======================================")
    print(f"Processing Year: {year}")
    print(f"Index URL: {index_url}")
    print(f"======================================")
    
    response = requests.get(index_url, timeout=10)
    soup = BeautifulSoup(response.content, "html.parser")
    
    count = 0
    skipped = 0
    for a in soup.find_all("a"):
        href = a.get('href')
        if not href or '/council/' not in href:
            continue
            
        raw_text = a.get_text().replace('\xa0', ' ')
        text = re.sub(r'\s+', ' ', raw_text).strip()
        
        date_match = re.match(r'^([A-Z][a-z]+ \d{1,2}, \d{4})', text)
        if not date_match:
            continue
            
        date_str = date_match.group(1)
        meeting_date = parse_date(date_str)
        if not meeting_date:
            continue
            
        # Optional: check if the meeting is actually for this year (in case links cross over)
        if meeting_date.year != year:
            continue
            
        title = text
        meeting_type = text[len(date_str):].strip()
        
        process_meeting(href, date_str, title, meeting_type, meeting_date, year)
        count += 1
        
        # Slight delay to be nice to the server since we are pulling thousands of pages
        time.sleep(0.5)

    print(f"-> Finished year {year}: Processed {count} meetings.")
    return count

def main():
    year_links = extract_year_links()
    print(f"Found {len(year_links)} master index links: {sorted(list(year_links.keys()))}")
    
    total_meetings = 0
    # Process from newest to oldest
    for year in sorted(year_links.keys(), reverse=True):
        total_meetings += process_year(year, year_links[year])
        
    print(f"\nALL DONE! Processed {total_meetings} meetings in total.")

if __name__ == "__main__":
    main()
