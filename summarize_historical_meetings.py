import os
import json
import time
import glob
from pathlib import Path
from austin_meeting_monitor_gemini import AustinCouncilMonitor
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def main():
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        logging.error("GEMINI_API_KEY environment variable is not set.")
        logging.info("Usage: GEMINI_API_KEY=your_key python3 summarize_historical_meetings.py")
        return

    monitor = AustinCouncilMonitor(gemini_api_key=api_key)
    
    historical_dir = Path("historical/2020s/2026")
    json_files = glob.glob(str(historical_dir / "*.json"))
    
    processed_count = 0
    skipped_count = 0

    for filepath in sorted(json_files):
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        needs_update = False
        
        # We need a transcript if it's missing and we have a pdf_url
        if not data.get('transcript') and data.get('pdf_url'):
            logging.info(f"Downloading PDF for {data['meeting_id']}...")
            pdf_path = f"temp_transcript_{data['meeting_id']}.pdf"
            
            if monitor.download_pdf(data['pdf_url'], pdf_path):
                logging.info(f"Extracting text for {data['meeting_id']}...")
                text = monitor.extract_text_from_pdf(pdf_path)
                if text:
                    data['transcript'] = text
                    needs_update = True
                
                try:
                    os.remove(pdf_path)
                except Exception:
                    pass
        
        # We need a summary if it's missing
        if not data.get('summary') and data.get('transcript'):
            logging.info(f"Generating summary for {data['meeting_id']}...")
            summary = monitor.generate_post_meeting_summary(
                meeting_data=data,
                transcript_text=data['transcript'],
                actions_text=None
            )
            
            if summary:
                data['summary'] = summary
                data['summary_source'] = 'gemini-2.5-flash'
                needs_update = True
                
        if needs_update:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            logging.info(f"Updated {filepath}")
            processed_count += 1
            
            # Rate limit
            logging.info("Sleeping for 35 seconds to prevent rate limiting...")
            time.sleep(35)
        else:
            skipped_count += 1
            logging.info(f"Skipped {filepath} (already complete or missing PDF)")

    logging.info(f"Done! Processed {processed_count} files, skipped {skipped_count}.")

if __name__ == "__main__":
    main()
