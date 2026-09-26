import os
import sys
import json
import argparse
import logging
from pathlib import Path

# Add the current directory to path if needed
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from austin_meeting_monitor_gemini import AustinCouncilMonitor
from update_historical_metadata import FULL_PROMPT_TEMPLATE, TITLE_ONLY_PROMPT_TEMPLATE, extract_title_and_summary

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def update_local_pdf(pdf_path, json_path):
    if not os.path.exists(pdf_path):
        logging.error(f"Local PDF file not found: {pdf_path}")
        return
        
    if not os.path.exists(json_path):
        logging.error(f"Target JSON file not found: {json_path}")
        return

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

    # Extract text from local PDF
    logging.info(f"Extracting text from {pdf_path}...")
    transcript_text = monitor.extract_text_from_pdf(pdf_path)
    if not transcript_text:
        logging.error("Could not extract any text from the provided PDF.")
        return

    # Load JSON data
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Determine what to generate
    has_summary = bool(data.get('summary'))
    has_ai_title = data.get('title_source') and 'gemini' in data.get('title_source').lower()
    
    needs_new_title = not has_ai_title or not has_summary # If no summary, regenerate both

    data['transcript'] = transcript_text
    needs_update = True

    try:
        if not has_summary:
            logging.info("Generating Title and Summary...")
            prompt = FULL_PROMPT_TEMPLATE.format(date=data.get('date', ''), text_content=transcript_text[:80000])
            response = monitor.gemini_model.generate_content(prompt)
            
            if response and response.text:
                title, summary = extract_title_and_summary(response.text)
                if summary:
                    data['summary'] = summary
                    data['summary_source'] = 'gemini-1.5-flash'
                if title:
                    data['title'] = title
                    data['title_source'] = 'gemini-1.5-flash'
                    
        elif needs_new_title:
            logging.info("Generating Title ONLY...")
            context = data.get('summary') if data.get('summary') else transcript_text[:80000]
            prompt = TITLE_ONLY_PROMPT_TEMPLATE.format(date=data.get('date', ''), text_content=context)
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
                    data['title'] = title
                    data['title_source'] = 'gemini-1.5-flash'
                    
    except Exception as e:
        logging.error(f"Error generating content: {e}")
        return

    if needs_update:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        logging.info(f"Successfully updated {json_path}!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Update meeting JSON with local PDF")
    parser.add_argument("pdf_path", help="Path to the local PDF file")
    parser.add_argument("json_path", help="Path to the JSON file to update")
    
    args = parser.parse_args()
    update_local_pdf(args.pdf_path, args.json_path)
