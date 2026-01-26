import os
import re
import json
import time
import sqlite3
import requests
from datetime import datetime
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import logging

# PDF text extraction
try:
    import fitz  # PyMuPDF
    PDF_LIBRARY = 'pymupdf'
except ImportError:
    try:
        import pdfplumber
        PDF_LIBRARY = 'pdfplumber'
    except ImportError:
        PDF_LIBRARY = None
        logging.warning("No PDF library found. Install PyMuPDF: pip install PyMuPDF")

# Gemini API
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    logging.warning("Gemini not available. Install: pip install google-generativeai")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class AustinCouncilMonitor:
    """
    Monitors Austin City Council Meeting Info Center for new meetings
    and generates summaries of agendas using Google Gemini
    """
    
    def __init__(self, db_path='austin_meetings.db', gemini_api_key=None):
        self.db_path = db_path
        self.gemini_api_key = gemini_api_key
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Austin Council Monitor - Public Information Tool)'
        })
        self.init_database()
        
        # Configure Gemini if available
        if self.gemini_api_key and GEMINI_AVAILABLE:
            genai.configure(api_key=self.gemini_api_key)
            self.gemini_model = genai.GenerativeModel('gemini-flash-latest')
            logging.info("✓ Gemini API configured successfully")
        else:
            self.gemini_model = None
            if not self.gemini_api_key:
                logging.warning("⚠️  No Gemini API key provided - using simple extraction")
            if not GEMINI_AVAILABLE:
                logging.warning("⚠️  Gemini library not installed - using simple extraction")
    
    def init_database(self):
        """Initialize SQLite database for tracking meetings"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS meetings (
                id TEXT PRIMARY KEY,
                date TEXT,
                meeting_type TEXT,
                url TEXT,
                agenda_url TEXT,
                summary TEXT,
                discovered_at TEXT,
                notified_at TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS subscribers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE,
                subscribed_at TEXT,
                active INTEGER DEFAULT 1
            )
        ''')
        
        conn.commit()
        conn.close()
        logging.info(f"✓ Database initialized: {self.db_path}")
    
    def extract_meeting_id(self, url):
        """Extract unique meeting ID from URL (e.g., 20260122-reg)"""
        match = re.search(r'/(\d{8}-[a-z]+)\.htm', url)
        return match.group(1) if match else None
    
    def check_for_new_meetings(self, info_center_url='https://www.austintexas.gov/department/city-council/council/council_meeting_info_center.htm'):
        """
        Scrape the Meeting Info Center page and identify new meetings
        Returns list of new meeting dictionaries
        """
        logging.info("\n" + "="*60)
        logging.info("🔍 Checking for new meetings...")
        logging.info("="*60)
        
        try:
            response = self.session.get(info_center_url, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            new_meetings = []
            
            # Find all meeting links (they follow pattern: YYYYMMDD-type.htm)
            for link in soup.find_all('a', href=True):
                href = link['href']
                
                # Look for meeting page links
                if re.search(r'/\d{8}-[a-z]+\.htm', href):
                    meeting_id = self.extract_meeting_id(href)
                    
                    if meeting_id and not self.meeting_exists(meeting_id):
                        full_url = urljoin(info_center_url, href)
                        
                        # Extract date and type from ID
                        date_str = meeting_id[:8]
                        meeting_type = meeting_id[9:]
                        
                        try:
                            date_obj = datetime.strptime(date_str, '%Y%m%d')
                            formatted_date = date_obj.strftime('%Y-%m-%d')
                        except ValueError:
                            formatted_date = date_str
                        
                        meeting_data = {
                            'id': meeting_id,
                            'date': formatted_date,
                            'meeting_type': self.format_meeting_type(meeting_type),
                            'url': full_url,
                            'link_text': link.get_text().strip()
                        }
                        
                        new_meetings.append(meeting_data)
                        logging.info(f"  🆕 New meeting found: {meeting_id} - {meeting_data['link_text']}")
            
            if not new_meetings:
                logging.info("  ℹ️  No new meetings found")
            
            return new_meetings
            
        except Exception as e:
            logging.error(f"✗ Error checking for new meetings: {e}")
            return []
    
    def meeting_exists(self, meeting_id):
        """Check if meeting ID already exists in database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM meetings WHERE id = ?', (meeting_id,))
        exists = cursor.fetchone() is not None
        conn.close()
        return exists
    
    def format_meeting_type(self, type_code):
        """Convert meeting type code to readable name"""
        type_map = {
            'reg': 'Regular Meeting',
            'wrk': 'Work Session',
            'spec': 'Special Called Meeting',
            'afc': 'Audit & Finance Committee',
            'mobc': 'Mobility Committee',
            'phc': 'Public Health Committee',
            'hpc': 'Housing & Planning Committee',
            'cwepc': 'Climate, Water, Energy & Public Enterprises Committee',
            'psc': 'Public Safety Committee',
            'eoc': 'Economic Opportunity Committee'
        }
        return type_map.get(type_code, type_code.upper())
    
    def get_agenda_url(self, meeting_url):
        """
        Scrape the meeting page to find the agenda PDF link
        """
        try:
            response = self.session.get(meeting_url, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Look for agenda links
            for link in soup.find_all('a', href=True):
                href = link['href']
                link_text = link.get_text().lower()
                
                # Check if it's an agenda
                if 'agenda' in link_text and (href.endswith('.pdf') or 'document.cfm?id=' in href):
                    return urljoin(meeting_url, href)
            
            return None
            
        except Exception as e:
            logging.error(f"✗ Error finding agenda URL: {e}")
            return None
    
    def download_pdf(self, url, save_path):
        """Download PDF from URL"""
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            
            with open(save_path, 'wb') as f:
                f.write(response.content)
            
            logging.info(f"  ✓ Downloaded PDF: {os.path.basename(save_path)}")
            return True
            
        except Exception as e:
            logging.error(f"  ✗ Error downloading PDF: {e}")
            return False
    
    def extract_text_from_pdf(self, pdf_path):
        """Extract text from PDF using available library"""
        if PDF_LIBRARY == 'pymupdf':
            return self._extract_with_pymupdf(pdf_path)
        elif PDF_LIBRARY == 'pdfplumber':
            return self._extract_with_pdfplumber(pdf_path)
        else:
            logging.error("  ✗ No PDF extraction library available")
            return None
    
    def _extract_with_pymupdf(self, pdf_path):
        """Extract text using PyMuPDF"""
        try:
            doc = fitz.open(pdf_path)
            text = ""
            for page in doc:
                text += page.get_text()
            doc.close()
            logging.info(f"  ✓ Extracted {len(text)} characters from PDF")
            return text
        except Exception as e:
            logging.error(f"  ✗ PyMuPDF extraction error: {e}")
            return None
    
    def _extract_with_pdfplumber(self, pdf_path):
        """Extract text using pdfplumber"""
        try:
            import pdfplumber
            text = ""
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    text += page.extract_text() or ""
            logging.info(f"  ✓ Extracted {len(text)} characters from PDF")
            return text
        except Exception as e:
            logging.error(f"  ✗ pdfplumber extraction error: {e}")
            return None
    
    def summarize_agenda(self, agenda_text):
        """
        Generate summary of agenda using Google Gemini
        Falls back to simple extraction if Gemini unavailable
        """
        if not self.gemini_model:
            return self._simple_summary(agenda_text)
        
        try:
            prompt = f"""Summarize this Austin City Council agenda in 3-5 bullet points. 
Focus on the most important items, public hearings, and policy decisions.
Keep it concise and accessible to the general public.

Agenda text:
{agenda_text[:100000]}"""  # Gemini can handle large context
            
            response = self.gemini_model.generate_content(prompt)
            summary = response.text.strip()
            
            logging.info(f"  ✓ Generated Gemini summary ({len(summary)} chars)")
            return summary
            
        except Exception as e:
            logging.error(f"  ✗ Gemini summarization error: {e}")
            return self._simple_summary(agenda_text)
    
    def _simple_summary(self, text):
        """Simple rule-based summary extraction (fallback)"""
        # Extract first few meaningful lines
        lines = [line.strip() for line in text.split('\n') if len(line.strip()) > 20]
        
        summary = "📋 Key agenda items:\n\n"
        for i, line in enumerate(lines[:5], 1):
            summary += f"{i}. {line[:150]}...\n"
        
        summary += "\n(Note: This is a basic extraction. Add Gemini API key for AI-powered summaries)"
        
        return summary
    
    def process_new_meeting(self, meeting_data):
        """
        Complete workflow: download agenda, extract text, summarize, save to DB
        """
        logging.info(f"\n{'='*60}")
        logging.info(f"📅 Processing: {meeting_data['date']} - {meeting_data['meeting_type']}")
        logging.info(f"{'='*60}")
        
        # Get agenda URL
        agenda_url = self.get_agenda_url(meeting_data['url'])
        
        if not agenda_url:
            logging.warning("  ⚠️  No agenda found for this meeting")
            summary = "Agenda not yet available. Check back later."
        else:
            logging.info(f"  ✓ Found agenda: {agenda_url}")
            
            # Download agenda
            pdf_path = f"temp_agenda_{meeting_data['id']}.pdf"
            
            if self.download_pdf(agenda_url, pdf_path):
                # Extract text
                agenda_text = self.extract_text_from_pdf(pdf_path)
                
                if agenda_text:
                    # Generate summary with Gemini
                    summary = self.summarize_agenda(agenda_text)
                else:
                    summary = "Unable to extract text from agenda PDF"
                
                # Clean up temp file
                try:
                    os.remove(pdf_path)
                except:
                    pass
            else:
                summary = "Failed to download agenda PDF"
        
        # Save to database
        self.save_meeting(meeting_data, agenda_url, summary)
        
        return {
            **meeting_data,
            'agenda_url': agenda_url,
            'summary': summary
        }
    
    def save_meeting(self, meeting_data, agenda_url, summary):
        """Save meeting to database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO meetings (id, date, meeting_type, url, agenda_url, summary, discovered_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            meeting_data['id'],
            meeting_data['date'],
            meeting_data['meeting_type'],
            meeting_data['url'],
            agenda_url,
            summary,
            datetime.now().isoformat()
        ))
        
        conn.commit()
        conn.close()
        logging.info(f"  ✓ Saved to database")
    
    def send_discord_notification(self, meeting_info, webhook_url):
        """Send notification via Discord webhook"""
        try:
            message = {
                "embeds": [{
                    "title": f"🏛️ New Austin City Council Meeting",
                    "description": f"**{meeting_info['meeting_type']}**\n📅 {meeting_info['date']}",
                    "fields": [
                        {
                            "name": "Summary",
                            "value": meeting_info['summary'][:1000]  # Discord limit
                        }
                    ],
                    "url": meeting_info['url'],
                    "color": 5814783  # Blue color
                }]
            }
            
            response = requests.post(webhook_url, json=message)
            response.raise_for_status()
            
            logging.info("  ✓ Discord notification sent")
            return True
            
        except Exception as e:
            logging.error(f"  ✗ Discord notification error: {e}")
            return False
    
    def run_check_cycle(self, discord_webhook_url=None):
        """
        Complete check cycle: find new meetings, process them, send notifications
        """
        logging.info("\n" + "="*60)
        logging.info("🚀 STARTING MEETING CHECK CYCLE")
        logging.info("="*60)
        
        new_meetings = self.check_for_new_meetings()
        
        if not new_meetings:
            logging.info("\n✓ Check cycle complete. No new meetings found.")
            return []
        
        processed = []
        for meeting_data in new_meetings:
            meeting_info = self.process_new_meeting(meeting_data)
            processed.append(meeting_info)
            
            # Send Discord notification if configured
            if discord_webhook_url:
                self.send_discord_notification(meeting_info, discord_webhook_url)
                
                # Mark as notified
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute(
                    'UPDATE meetings SET notified_at = ? WHERE id = ?',
                    (datetime.now().isoformat(), meeting_data['id'])
                )
                conn.commit()
                conn.close()
            
            time.sleep(2)  # Be respectful between requests
        
        logging.info(f"\n{'='*60}")
        logging.info(f"✅ CHECK CYCLE COMPLETE")
        logging.info(f"{'='*60}")
        logging.info(f"New meetings processed: {len(processed)}")
        
        return processed
    
    def get_recent_meetings(self, limit=10):
        """Retrieve recent meetings from database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, date, meeting_type, url, agenda_url, summary, discovered_at
            FROM meetings
            ORDER BY date DESC
            LIMIT ?
        ''', (limit,))
        
        meetings = []
        for row in cursor.fetchall():
            meetings.append({
                'id': row[0],
                'date': row[1],
                'meeting_type': row[2],
                'url': row[3],
                'agenda_url': row[4],
                'summary': row[5],
                'discovered_at': row[6]
            })
        
        conn.close()
        return meetings


if __name__ == "__main__":
    print("\n" + "="*60)
    print("🏛️  AUSTIN CITY COUNCIL MEETING MONITOR")
    print("="*60)
    
    # SETUP: Add your API keys here
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')  # Set via: export GEMINI_API_KEY="your-key"
    DISCORD_WEBHOOK = os.getenv('DISCORD_WEBHOOK_URL')  # Optional
    
    if not GEMINI_API_KEY:
        print("\n⚠️  WARNING: No Gemini API key found!")
        print("Set it with: export GEMINI_API_KEY='gemini_api_key'")
        print("Or paste it directly in the script above.\n")
        
        # Uncomment and paste your key here if not using environment variable:
        # GEMINI_API_KEY = "paste-your-gemini-api-key-here"
    
    # Initialize monitor
    monitor = AustinCouncilMonitor(
        db_path='austin_meetings.db',
        gemini_api_key='GEMINI_API_KEY'
    )
    
    # Run a check cycle
    new_meetings = monitor.run_check_cycle(discord_webhook_url=DISCORD_WEBHOOK)
    
    # Display results
    if new_meetings:
        print("\n" + "="*60)
        print("📋 NEW MEETINGS DISCOVERED")
        print("="*60)
        
        for meeting in new_meetings:
            print(f"\n📅 {meeting['date']} - {meeting['meeting_type']}")
            print(f"🔗 {meeting['url']}")
            print(f"\n{meeting['summary']}")
            print("-" * 60)
    
    # Show recent meetings from database
    print("\n" + "="*60)
    print("📚 RECENT MEETINGS IN DATABASE")
    print("="*60)
    
    recent = monitor.get_recent_meetings(limit=5)
    for meeting in recent:
        print(f"\n📅 {meeting['date']} - {meeting['meeting_type']}")
        print(f"🔗 {meeting['url']}")
        print(f"📝 {meeting['summary'][:200]}...")
