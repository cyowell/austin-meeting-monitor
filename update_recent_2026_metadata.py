import os
import sys
import json
import logging
from pathlib import Path

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from austin_meeting_monitor_gemini import AustinCouncilMonitor
from update_historical_metadata import TITLE_ONLY_PROMPT_TEMPLATE, extract_title_and_summary

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

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

    real_time_dir = Path("real-time")
    if not real_time_dir.exists():
        logging.error(f"Directory not found: {real_time_dir}")
        return
        
    start_date = "2026-03-12"
    end_date = "2026-05-28"

    processed = 0
    errors = 0
    
    json_files = sorted([f for f in real_time_dir.iterdir() if f.name.endswith('.json')])

    for filepath in json_files:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            logging.error(f"Error reading {filepath}: {e}")
            continue

        meeting_date = data.get('date', '')
        if not (start_date <= meeting_date <= end_date):
            continue

        logging.info(f"Processing {filepath.name}...")
        needs_update = False

        # 1. Download missing transcript if needed
        if not data.get('transcript'):
            download_url = data.get('pdf_url') or data.get('actions_url') or data.get('agenda_url')
            if download_url:
                logging.info(f"Downloading PDF from {download_url}...")
                pdf_path = f"temp_transcript_{data['meeting_id']}.pdf"
                
                if monitor.download_pdf(download_url, pdf_path):
                    logging.info("Extracting text...")
                    text = monitor.extract_text_from_pdf(pdf_path)
                    if text:
                        data['transcript'] = text
                        needs_update = True
                    try:
                        os.remove(pdf_path)
                    except Exception:
                        pass
            else:
                logging.warning(f"No valid URL found to download transcript for {filepath.name}")

        # 2. Generate new title
        context = data.get('summary') if data.get('summary') else data.get('transcript', '')[:80000]
        if context:
            logging.info("Generating new title...")
            prompt = TITLE_ONLY_PROMPT_TEMPLATE.format(date=meeting_date, text_content=context)
            
            try:
                response = monitor.gemini_model.generate_content(prompt)
                if response and response.text:
                    title, _ = extract_title_and_summary(response.text)
                    if not title:
                        title = response.text.strip().split('\n')[0].replace('**', '').strip()
                        if title.lower().startswith("title:"):
                            title = title[6:].strip()
                            
                    if title:
                        if title.startswith('"') and title.endswith('"'):
                            title = title[1:-1]
                        
                        # Only update if the title actually changed
                        if data.get('title') != title:
                            data['title'] = title
                            data['title_source'] = 'gemini-2.5-flash'
                            needs_update = True
                            logging.info(f"New title generated: {title}")
                            
            except Exception as e:
                error_str = str(e).lower()
                if '429' in error_str or 'exhausted' in error_str or 'quota' in error_str:
                    logging.error(f"Rate limit reached: {e}")
                    logging.info("Exiting gracefully so you can resume later.")
                    return
                else:
                    logging.error(f"Error generating title for {filepath.name}: {e}")
                    errors += 1
                    continue

        if needs_update:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            processed += 1
            logging.info(f"Successfully updated {filepath.name}")

    logging.info(f"Finished! Processed/Updated: {processed}, Errors: {errors}")

if __name__ == "__main__":
    main()
