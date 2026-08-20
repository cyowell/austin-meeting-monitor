import os
import sys
import json
import time
import glob
import logging
from pathlib import Path

# Add the current directory to path if needed so we can import AustinCouncilMonitor
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from austin_meeting_monitor_gemini import AustinCouncilMonitor

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# User's exact prompt for full summary + title
FULL_PROMPT_TEMPLATE = """Summarize this {date} Austin City Council agenda in 3-5 bullet points. Keep it concise and accessible to the modern, general public. Focus on the most important and interesting items, public hearings, and policy decisions. Put a title that is SEO friendly for the summary in the first line prepended by "Title:" that itself is under 50 characters, mentions key interesting content. For the title DO NOT mention the council, the year or that it's a summary in the title.

Meeting Transcript / Actions:
{text_content}"""

# Derived prompt for just the title
TITLE_ONLY_PROMPT_TEMPLATE = """Provide a title for this {date} Austin City Council meeting based on the content below. Keep it concise and accessible to the modern, general public. Put a title that is SEO friendly in the first line prepended by "Title:" that itself is under 50 characters, mentions key interesting content. For the title DO NOT mention the council, the year or that it's a summary in the title. Return ONLY the title line.

Meeting Transcript / Summary:
{text_content}"""

def get_decade_folder(year):
    decade = (year // 10) * 10
    return f"{decade}s"

def extract_title_and_summary(response_text):
    lines = response_text.strip().split('\n')
    title = None
    summary_lines = []
    
    for line in lines:
        # Check if line starts with Title:, case-insensitive, might have markdown bold
        clean_line = line.replace('**', '').strip()
        if clean_line.lower().startswith("title:"):
            title = clean_line[6:].strip()
            # Remove any trailing quotes if they were added
            if title.startswith('"') and title.endswith('"'):
                title = title[1:-1]
        else:
            summary_lines.append(line)
            
    summary = '\n'.join(summary_lines).strip()
    return title, summary

def main():
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        logging.error("GEMINI_API_KEY environment variable is not set.")
        return
        
    # Strip any accidental quotes, newlines, or whitespace from the API key
    api_key = api_key.replace('"', '').replace("'", "").replace("\\n", "").replace("\\r", "").strip()
    api_key = ''.join(api_key.split()) # Remove any internal whitespace

    monitor = AustinCouncilMonitor(gemini_api_key=api_key)
    if not monitor.gemini_model:
        logging.error("Failed to initialize Gemini model.")
        return

    base_dir = Path("historical")
    processed_count = 0
    skipped_count = 0
    error_count = 0

    for year in range(2005, 2027):
        decade_folder = get_decade_folder(year)
        year_dir = base_dir / decade_folder / str(year)
        
        if not year_dir.exists():
            continue
            
        json_files = sorted(glob.glob(str(year_dir / "*.json")))
        
        for filepath in json_files:
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception as e:
                logging.error(f"Error reading {filepath}: {e}")
                continue
                
            needs_update = False
            has_summary = bool(data.get('summary'))
            has_ai_title = data.get('title_source') == 'gemini-1.5-flash' or data.get('title_source') == 'gemini-2.5-flash' # Using 1.5 flash or 2.5 flash based on what the user uses

            # Overwrite all titles if we don't have an AI source for it
            needs_new_title = True
            if data.get('title_source') and 'gemini' in data.get('title_source').lower():
                # We already generated a title for this with AI, skip unless summary is also missing and we need to do both
                if has_summary:
                    needs_new_title = False

            if not needs_new_title and has_summary:
                skipped_count += 1
                continue

            # Check if we need to download/extract PDF transcript first
            if not data.get('transcript'):
                download_url = data.get('pdf_url') or data.get('actions_url') or data.get('agenda_url')
                if download_url:
                    logging.info(f"Downloading PDF for {data['meeting_id']} from {download_url}...")
                    pdf_path = f"temp_transcript_{data['meeting_id']}.pdf"
                    
                    if monitor.download_pdf(download_url, pdf_path):
                        logging.info(f"Extracting text for {data['meeting_id']}...")
                        text = monitor.extract_text_from_pdf(pdf_path)
                        if text:
                            data['transcript'] = text
                            needs_update = True
                        try:
                            os.remove(pdf_path)
                        except Exception:
                            pass

            transcript_text = data.get('transcript')
            if not transcript_text:
                logging.info(f"Skipped {filepath}: No transcript available to generate metadata.")
                skipped_count += 1
                continue

            try:
                if not has_summary:
                    # Generate BOTH Title and Summary
                    logging.info(f"Generating Title and Summary for {data['meeting_id']}...")
                    prompt = FULL_PROMPT_TEMPLATE.format(date=data.get('date', ''), text_content=transcript_text[:80000])
                    response = monitor.gemini_model.generate_content(prompt)
                    
                    if response and response.text:
                        title, summary = extract_title_and_summary(response.text)
                        if summary:
                            data['summary'] = summary
                            data['summary_source'] = 'gemini-1.5-flash'
                            needs_update = True
                        if title:
                            data['title'] = title
                            data['title_source'] = 'gemini-1.5-flash'
                            needs_update = True
                
                elif needs_new_title:
                    # Generate ONLY Title
                    logging.info(f"Generating Title ONLY for {data['meeting_id']}...")
                    # We can use the summary as context since it's much shorter, or the transcript. Transcript is safer for a good title.
                    context = data.get('summary') if data.get('summary') else transcript_text[:80000]
                    prompt = TITLE_ONLY_PROMPT_TEMPLATE.format(date=data.get('date', ''), text_content=context)
                    response = monitor.gemini_model.generate_content(prompt)
                    
                    if response and response.text:
                        title, _ = extract_title_and_summary(response.text)
                        if not title: # If it failed to use the Title: prefix, just take the first line
                            title = response.text.strip().split('\n')[0].replace('**', '').strip()
                            if title.lower().startswith("title:"):
                                title = title[6:].strip()
                                
                        if title:
                            # Remove quotes if present
                            if title.startswith('"') and title.endswith('"'):
                                title = title[1:-1]
                            data['title'] = title
                            data['title_source'] = 'gemini-1.5-flash'
                            needs_update = True

            except Exception as e:
                error_str = str(e).lower()
                if '429' in error_str or 'exhausted' in error_str or 'quota' in error_str:
                    logging.error(f"Rate limit reached: {e}")
                    logging.info("Exiting gracefully so cron job can resume tomorrow.")
                    return # Exit the main function completely
                else:
                    logging.error(f"Error generating content for {data['meeting_id']}: {e}")
                    error_count += 1
                    time.sleep(5) # Small sleep on generic errors
                    continue

            if needs_update:
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2)
                logging.info(f"Updated {filepath}")
                processed_count += 1
                
                # Sleep to help avoid aggressive rate limiting
                logging.info("Sleeping for 15 seconds to respect rate limits...")
                time.sleep(15)

    logging.info(f"Finished processing. Updated: {processed_count}, Skipped: {skipped_count}, Errors: {error_count}")

if __name__ == "__main__":
    main()
