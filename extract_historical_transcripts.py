import os
import json
import time
import glob
from pathlib import Path
import fitz  # PyMuPDF
import requests

def download_pdf(url, save_path):
    try:
        response = requests.get(url, timeout=30, headers={'User-Agent': 'Mozilla/5.0 (Austin Council Monitor - History Script)'})
        response.raise_for_status()
        with open(save_path, 'wb') as f:
            f.write(response.content)
        return True
    except Exception as e:
        print(f"    Failed to download {url}: {e}")
        return False

def extract_text_from_pdf(pdf_path):
    try:
        doc = fitz.open(pdf_path)
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        return text
    except Exception as e:
        print(f"    Failed to extract text: {e}")
        return None

def main():
    base_dir = Path("historical")
    
    # We only process years from 2005 to 2026.
    # Years are organized like historical/2000s/2005/...
    count_processed = 0
    
    for decade in os.listdir(base_dir):
        decade_path = base_dir / decade
        if not decade_path.is_dir(): continue
        
        for year_str in os.listdir(decade_path):
            year_path = decade_path / year_str
            if not year_path.is_dir(): continue
            
            try:
                year = int(year_str)
            except ValueError:
                continue
                
            if year < 2005 or year > 2026:
                continue
                
            # Find all JSON files in this year's directory
            json_files = glob.glob(str(year_path / "*.json"))
            for jf in json_files:
                with open(jf, 'r', encoding='utf-8') as f:
                    try:
                        data = json.load(f)
                    except json.JSONDecodeError:
                        continue
                
                # Check if we need to process
                if not data.get('transcript') and data.get('pdf_url'):
                    print(f"Processing: {jf}")
                    pdf_url = data['pdf_url']
                    pdf_path = f"temp_hist_{data['meeting_id']}.pdf"
                    
                    if download_pdf(pdf_url, pdf_path):
                        text = extract_text_from_pdf(pdf_path)
                        if text:
                            data['transcript'] = text
                            
                            with open(jf, 'w', encoding='utf-8') as f:
                                json.dump(data, f, indent=2)
                            
                            print(f"  -> Extracted {len(text)} chars of transcript.")
                            count_processed += 1
                        else:
                            print("  -> Extraction returned empty.")
                            
                        # Cleanup temp pdf
                        try:
                            os.remove(pdf_path)
                        except:
                            pass
                    
                    # Be nice to the server
                    time.sleep(1)
                    
    print(f"\nDone! Extracted text for {count_processed} meetings.")

if __name__ == "__main__":
    main()
