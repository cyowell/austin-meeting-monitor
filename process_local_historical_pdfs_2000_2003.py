import os
import sys
import json
import logging
import re
from pathlib import Path

# Add the current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from austin_meeting_monitor_gemini import AustinCouncilMonitor
from update_historical_metadata import FULL_PROMPT_TEMPLATE, extract_title_and_summary

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_decade_folder(year):
    decade = (year // 10) * 10
    return f"{decade}s"

def parse_filename(filename):
    # e.g. 2000-01-06_Regular_Document_January-6-2000-Austin-City-Council-Regul.pdf
    if "Archive-Unknown" in filename:
        return None
        
    match = re.match(r'^(\d{4})-(\d{2})-(\d{2})_([^_]+)_', filename)
    if not match:
        logging.warning(f"Could not parse filename format: {filename}")
        return None
        
    year = int(match.group(1))
    month = match.group(2)
    day = match.group(3)
    raw_type = match.group(4)
    
    date_str = f"{year}-{month}-{day}"
    date_compact = f"{year}{month}{day}"
    
    type_code_map = {
        'Regular': ('reg', 'Austin City Council Regular Meeting'),
        'AHFC': ('ahfc', 'Austin Housing Finance Corporation (AHFC)'),
        'Special-Called': ('spec', 'Austin City Council Special-Called Meeting'),
        'Work-Session': ('wrk', 'Austin City Council Work Session'),
        'Council-Archive': ('archive', 'Council Archive')
    }
    
    type_info = type_code_map.get(raw_type, ('unk', raw_type.replace('-', ' ')))
    short_type = type_info[0]
    full_type = type_info[1]
    
    meeting_id = f"{date_compact}-{short_type}"
    
    return {
        'year': year,
        'date': date_str,
        'meeting_id': meeting_id,
        'meeting_type': full_type
    }

def main():
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        logging.error("GEMINI_API_KEY environment variable is not set.")
        return
        
    api_key = api_key.replace('"', '').replace("'", "").replace("\\n", "").replace("\\r", "").strip()
    api_key = ''.join(api_key.split())

    monitor = AustinCouncilMonitor(gemini_api_key=api_key)
    if not monitor.gemini_model:
        logging.error("Failed to initialize Gemini model.")
        return

    source_dir = Path("/Users/charlesy/Documents/Coding/austin_council_historical_2000_2003")
    if not source_dir.exists():
        logging.error(f"Source directory not found: {source_dir}")
        return
        
    output_base_dir = Path("historical")

    processed = 0
    skipped = 0
    errors = 0
    
    pdf_files = sorted([f for f in source_dir.iterdir() if f.name.endswith('.pdf')])

    for pdf_path in pdf_files:
        meta = parse_filename(pdf_path.name)
        if not meta:
            logging.info(f"Skipping {pdf_path.name}")
            skipped += 1
            continue
            
        year = meta['year']
        decade_folder = get_decade_folder(year)
        target_dir = output_base_dir / decade_folder / str(year)
        target_dir.mkdir(parents=True, exist_ok=True)
        
        json_filename = f"{meta['date']}_{meta['meeting_id']}.json"
        target_json = target_dir / json_filename
        
        if target_json.exists():
            # If we want to skip already processed files (useful if restarting script)
            logging.info(f"Already exists, skipping: {json_filename}")
            skipped += 1
            continue
            
        logging.info(f"Processing {pdf_path.name} -> {json_filename}")
        transcript_text = monitor.extract_text_from_pdf(str(pdf_path))
        
        if not transcript_text:
            logging.error(f"Failed to extract text from {pdf_path.name}")
            errors += 1
            continue
            
        try:
            prompt = FULL_PROMPT_TEMPLATE.format(date=meta['date'], text_content=transcript_text[:80000])
            response = monitor.gemini_model.generate_content(prompt)
            
            title = None
            summary = None
            if response and response.text:
                title, summary = extract_title_and_summary(response.text)
                
            if not summary:
                logging.error(f"Failed to generate summary for {pdf_path.name}")
                errors += 1
                continue
                
            # Construct JSON
            data = {
                "meeting_id": meta['meeting_id'],
                "title": title or "Austin City Council Meeting",
                "meeting_type": meta['meeting_type'],
                "date": meta['date'],
                "year": meta['year'],
                "meeting_url": None,
                "agenda_url": None,
                "video_url": None,
                "actions_url": None,
                "pdf_url": None,
                "summary_source": "gemini-2.5-flash",
                "summary": summary,
                "topics": [],
                "transcript": transcript_text,
                "title_source": "gemini-2.5-flash"
            }
            
            with open(target_json, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
                
            processed += 1
            logging.info(f"Saved {json_filename}")
            
        except Exception as e:
            error_str = str(e).lower()
            if '429' in error_str or 'exhausted' in error_str or 'quota' in error_str:
                logging.error(f"Rate limit reached: {e}")
                logging.info("Exiting gracefully so you can resume later.")
                return
            else:
                logging.error(f"Error generating content for {pdf_path.name}: {e}")
                errors += 1
                continue
                
    logging.info(f"Finished! Processed: {processed}, Skipped: {skipped}, Errors: {errors}")

if __name__ == "__main__":
    main()
