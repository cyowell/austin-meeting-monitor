import os
import re
import json
import time
import sqlite3
import requests
from datetime import datetime, date
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
    and generates summaries of agendas using Google Gemini.

    Also monitors past meetings for post-meeting content (transcript,
    actions taken, video) once they have occurred, and generates a
    richer civic journalist-style summary from that material.
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
            self.gemini_model = genai.GenerativeModel('gemini-2.5-flash')
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
                meeting_id TEXT PRIMARY KEY,
                date TEXT,
                meeting_type TEXT,
                meeting_url TEXT,
                agenda_url TEXT,
                gemini_summary TEXT,
                created_at TEXT,
                notified_at TEXT
            )
        ''')

        # Migration: add columns to existing databases
        cursor.execute("PRAGMA table_info(meetings)")
        existing_columns = {col[1] for col in cursor.fetchall()}

        migrations = [
            ('notified_at', 'TEXT'),
            ('is_completed', 'INTEGER DEFAULT 0'),
            ('transcript_url', 'TEXT'),
            ('actions_url', 'TEXT'),
            ('video_url', 'TEXT'),
            ('post_meeting_summary', 'TEXT'),
            ('completed_processed_at', 'TEXT'),
        ]
        for col_name, col_type in migrations:
            if col_name not in existing_columns:
                cursor.execute(f'ALTER TABLE meetings ADD COLUMN {col_name} {col_type}')
                logging.info(f"  ✓ Migrated database: added {col_name} column")

        # Automatically mark meetings as completed if their date is in the past
        # (handles meetings added before this feature existed)
        today_str = date.today().isoformat()
        cursor.execute(
            "UPDATE meetings SET is_completed = 1 WHERE date < ? AND (is_completed IS NULL OR is_completed = 0)",
            (today_str,)
        )
        if cursor.rowcount:
            logging.info(f"  ✓ Auto-marked {cursor.rowcount} past meeting(s) as completed")

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

    # ─────────────────────────────────────────────
    # Utilities
    # ─────────────────────────────────────────────

    def extract_meeting_id(self, url):
        """Extract unique meeting ID from URL (e.g., 20260122-reg)
        Handles both old format (.htm) and new format (no extension)"""
        match = re.search(r'/(\d{8}-[a-z]+)(?:\.htm)?', url)
        return match.group(1) if match else None

    def format_meeting_type(self, type_code):
        """Convert meeting type code to readable name"""
        type_map = {
            'reg': 'Regular Meeting',
            'wrk': 'Work Session',
            'spec': 'Special Called Meeting',
            'ahfc': 'Austin Housing Finance Corporation',
            'afc': 'Audit & Finance Committee',
            'mobc': 'Mobility Committee',
            'phc': 'Public Health Committee',
            'hpc': 'Housing & Planning Committee',
            'cwepc': 'Climate, Water, Energy & Public Enterprises Committee',
            'psc': 'Public Safety Committee',
            'eoc': 'Economic Opportunity Committee'
        }
        return type_map.get(type_code, type_code.upper())

    def meeting_exists(self, meeting_id):
        """Check if meeting ID already exists in database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT meeting_id FROM meetings WHERE meeting_id = ?', (meeting_id,))
        exists = cursor.fetchone() is not None
        conn.close()
        return exists

    # ─────────────────────────────────────────────
    # New Meeting Detection (Upcoming)
    # ─────────────────────────────────────────────

    def check_for_new_meetings(self, info_center_url='https://www.austintexas.gov/council/meetings'):
        """
        Scrape the Meeting Info Center page and identify new meetings.
        Returns list of new meeting dictionaries.
        """
        logging.info("\n" + "="*60)
        logging.info("🔍 Checking for new meetings...")
        logging.info(f"📍 URL: {info_center_url}")
        logging.info("="*60)

        try:
            response = self.session.get(info_center_url, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            new_meetings = []

            # Find all meeting links (pattern: /YYYYMMDD-type with or without .htm)
            for link in soup.find_all('a', href=True):
                href = link['href']

                if re.search(r'/\d{8}-[a-z]+(?:\.htm)?', href):
                    meeting_id = self.extract_meeting_id(href)

                    if meeting_id and not self.meeting_exists(meeting_id):
                        full_url = urljoin(info_center_url, href)
                        if not full_url.startswith('http'):
                            full_url = 'https://www.austintexas.gov' + href

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

    def get_agenda_url(self, meeting_url):
        """Scrape the meeting page to find the agenda PDF link"""
        try:
            response = self.session.get(meeting_url, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            for link in soup.find_all('a', href=True):
                href = link['href']
                link_text = link.get_text().lower()

                if 'agenda' in link_text and (href.endswith('.pdf') or 'document.cfm?id=' in href):
                    full_url = urljoin(meeting_url, href)
                    if not full_url.startswith('http'):
                        full_url = 'https://www.austintexas.gov' + href
                    return full_url

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
        Generate summary of agenda using Google Gemini.
        Falls back to simple extraction if Gemini unavailable.
        """
        if not self.gemini_model:
            return self._simple_summary(agenda_text)

        try:
            prompt = f"""Summarize this Austin City Council agenda in 3-5 bullet points.
Focus on the most important items, public hearings, and policy decisions.
Keep it concise and accessible to the general public.

Agenda text:
{agenda_text[:100000]}"""

            response = self.gemini_model.generate_content(prompt)
            summary = response.text.strip()

            logging.info(f"  ✓ Generated Gemini agenda summary ({len(summary)} chars)")
            return summary

        except Exception as e:
            logging.error(f"  ✗ Gemini summarization error: {e}")
            return self._simple_summary(agenda_text)

    def _simple_summary(self, text):
        """Simple rule-based summary extraction (fallback)"""
        lines = [line.strip() for line in text.split('\n') if len(line.strip()) > 20]

        summary = "📋 Key agenda items:\n\n"
        for i, line in enumerate(lines[:5], 1):
            summary += f"{i}. {line[:150]}...\n"

        return summary

    def process_new_meeting(self, meeting_data):
        """
        Complete workflow for a newly discovered meeting:
        download agenda, extract text, summarize, save to DB.
        """
        logging.info(f"\n{'='*60}")
        logging.info(f"📅 Processing: {meeting_data['date']} - {meeting_data['meeting_type']}")
        logging.info(f"{'='*60}")

        agenda_url = self.get_agenda_url(meeting_data['url'])

        if not agenda_url:
            logging.warning("  ⚠️  No agenda found for this meeting")
            summary = "Agenda not yet available. Check back later."
        else:
            logging.info(f"  ✓ Found agenda: {agenda_url}")

            pdf_path = f"temp_agenda_{meeting_data['id']}.pdf"

            if self.download_pdf(agenda_url, pdf_path):
                agenda_text = self.extract_text_from_pdf(pdf_path)

                if agenda_text:
                    summary = self.summarize_agenda(agenda_text)
                else:
                    summary = "Unable to extract text from agenda PDF"

                try:
                    os.remove(pdf_path)
                except Exception:
                    pass
            else:
                summary = "Failed to download agenda PDF"

        # Determine if meeting is already in the past
        today = date.today()
        try:
            meeting_date = datetime.strptime(meeting_data['date'], '%Y-%m-%d').date()
            is_completed = 1 if meeting_date < today else 0
        except ValueError:
            is_completed = 0

        self.save_meeting(meeting_data, agenda_url, summary, is_completed)

        return {
            **meeting_data,
            'agenda_url': agenda_url,
            'summary': summary,
            'is_completed': is_completed
        }

    def save_meeting(self, meeting_data, agenda_url, summary, is_completed=0):
        """Save meeting to database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO meetings (meeting_id, date, meeting_type, meeting_url, agenda_url,
                                  gemini_summary, created_at, is_completed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            meeting_data['id'],
            meeting_data['date'],
            meeting_data['meeting_type'],
            meeting_data['url'],
            agenda_url,
            summary,
            datetime.now().isoformat(),
            is_completed
        ))

        conn.commit()
        conn.close()
        logging.info(f"  ✓ Saved to database (is_completed={is_completed})")

    # ─────────────────────────────────────────────
    # Post-Meeting Processing (Recent)
    # ─────────────────────────────────────────────

    def scrape_post_meeting_data(self, meeting_url):
        """
        Fetch a meeting page and look for post-meeting resources:
        - Closed Caption Transcript PDF
        - Actions Taken By Council URL
        - Video URL (Swagit)

        Returns a dict with keys: transcript_url, actions_url, video_url.
        Values are None if not yet available.
        """
        result = {
            'transcript_url': None,
            'actions_url': None,
            'video_url': None,
        }
        try:
            response = self.session.get(meeting_url, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            page_text = response.text

            # ── Transcript PDF ─────────────────────────────────────────
            # Look for a heading containing "Transcript" or "Closed Caption"
            # followed by a document.cfm link
            in_transcript_section = False
            for element in soup.find_all(['h4', 'h3', 'a']):
                tag = element.name
                text = element.get_text(strip=True)

                if tag in ('h3', 'h4'):
                    in_transcript_section = bool(
                        re.search(r'transcript|closed.?caption', text, re.IGNORECASE)
                    )

                if in_transcript_section and tag == 'a':
                    href = element.get('href', '')
                    if 'document.cfm' in href or href.lower().endswith('.pdf'):
                        full = href if href.startswith('http') else urljoin(meeting_url, href)
                        result['transcript_url'] = full
                        logging.info(f"  ✓ Transcript found: {full}")
                        break

            # ── Actions Taken URL ────────────────────────────────────
            # Pattern: action_notes.cfm?mid=XXXX
            actions_match = re.search(r'action_notes\.cfm\?mid=\d+', page_text, re.IGNORECASE)
            if actions_match:
                actions_rel = actions_match.group(0)
                result['actions_url'] = f"https://services.austintexas.gov/council_meetings/{actions_rel}"
                logging.info(f"  ✓ Actions URL found: {result['actions_url']}")

            # ── Video URL (Swagit) ────────────────────────────────────
            video_match = re.search(r'https?://austintx\.swagit\.com/play/[^\s"<>\']+', page_text)
            if video_match:
                result['video_url'] = video_match.group(0)
                logging.info(f"  ✓ Video URL found: {result['video_url']}")

        except Exception as e:
            logging.error(f"  ✗ Error scraping post-meeting data from {meeting_url}: {e}")

        return result

    def fetch_actions_text(self, actions_url):
        """
        Fetch and parse the Actions Taken By Council HTML page.
        Returns plain text suitable for Gemini summarization.
        """
        try:
            response = self.session.get(actions_url, timeout=20)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            # Remove nav, header, footer noise
            for tag in soup.find_all(['nav', 'header', 'footer', 'script', 'style']):
                tag.decompose()

            text = soup.get_text(separator='\n', strip=True)
            # Collapse excessive blank lines
            text = re.sub(r'\n{3,}', '\n\n', text)
            logging.info(f"  ✓ Actions text fetched ({len(text)} chars)")
            return text

        except Exception as e:
            logging.error(f"  ✗ Error fetching actions page: {e}")
            return None

    def generate_post_meeting_summary(self, meeting_data, transcript_text=None, actions_text=None):
        """
        Generate a civic journalist-style summary of what the council
        ACTUALLY DID at this meeting, using the transcript and actions.
        Falls back to a note if Gemini is unavailable.
        """
        if not self.gemini_model:
            return "Post-meeting summary not available (Gemini API not configured)."

        if not transcript_text and not actions_text:
            return "Post-meeting summary not yet available. Check the city website for details."

        sections = []
        if actions_text:
            sections.append(f"=== ACTIONS TAKEN BY COUNCIL ===\n{actions_text[:60000]}")
        if transcript_text:
            sections.append(f"=== CLOSED CAPTION TRANSCRIPT ===\n{transcript_text[:80000]}")

        combined = "\n\n".join(sections)

        try:
            prompt = f"""You are a civic journalist covering Austin City government for local residents.
Summarize what the Austin City Council ACTUALLY DID at this meeting in 4-6 bullet points.

Base your summary on the official records below. Focus on:
- Key votes and what passed or failed (include vote counts if available)
- Major ordinances, contracts, or policies approved
- Notable public debates or controversial decisions
- Any items that were postponed, tabled, or pulled

Keep the language clear and accessible to a general Austin resident who cares about their city.
Do NOT include meeting procedural details (roll calls, general announcements, etc.).
Use plain English, no jargon.

Meeting: {meeting_data.get('meeting_type', 'Austin City Council Meeting')} — {meeting_data.get('date', '')}

{combined}"""

            response = self.gemini_model.generate_content(prompt)
            summary = response.text.strip()
            logging.info(f"  ✓ Generated post-meeting summary ({len(summary)} chars)")
            return summary

        except Exception as e:
            logging.error(f"  ✗ Gemini post-meeting summarization error: {e}")
            return "Post-meeting summary could not be generated. See the city website for actions taken."

    def process_completed_meetings(self):
        """
        Scan all meetings marked is_completed=1 that haven't been
        post-processed yet (completed_processed_at IS NULL).

        For each, attempt to scrape transcript/actions/video from the
        city website and generate a richer AI summary.

        Also re-checks any meeting whose date is now in the past but
        is not yet marked is_completed (handles newly elapsed meetings).
        """
        logging.info("\n" + "="*60)
        logging.info("🔄 Processing completed meetings...")
        logging.info("="*60)

        today_str = date.today().isoformat()

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # First: mark any newly past meetings as completed
        cursor.execute(
            "UPDATE meetings SET is_completed = 1 WHERE date < ? AND (is_completed IS NULL OR is_completed = 0)",
            (today_str,)
        )
        if cursor.rowcount:
            logging.info(f"  ✓ Newly marked {cursor.rowcount} meeting(s) as completed")

        # Now fetch all completed meetings that haven't been post-processed
        cursor.execute('''
            SELECT meeting_id, date, meeting_type, meeting_url
            FROM meetings
            WHERE is_completed = 1
              AND (completed_processed_at IS NULL OR transcript_url IS NULL)
            ORDER BY date DESC
        ''')
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            logging.info("  ℹ️  No completed meetings need post-processing")
            return []

        processed = []
        for row in rows:
            meeting_id, meeting_date, meeting_type, meeting_url = row

            logging.info(f"\n  📋 Post-processing: {meeting_date} {meeting_type} ({meeting_id})")

            post_data = self.scrape_post_meeting_data(meeting_url)

            # If none of the post-meeting resources are available yet, skip for now
            if not any(post_data.values()):
                logging.info(f"  ⏳ Post-meeting resources not yet available for {meeting_id}")
                # Still mark so we don't continually hammer very old or non-standard meetings
                # Only skip recent ones that might still be pending
                meeting_date_obj = None
                try:
                    meeting_date_obj = datetime.strptime(meeting_date, '%Y-%m-%d').date()
                except ValueError:
                    pass

                days_past = (date.today() - meeting_date_obj).days if meeting_date_obj else 999
                if days_past > 14:
                    # Give up after 2 weeks — mark as processed with no data
                    conn = sqlite3.connect(self.db_path)
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE meetings SET completed_processed_at = ? WHERE meeting_id = ?",
                        (datetime.now().isoformat(), meeting_id)
                    )
                    conn.commit()
                    conn.close()
                continue

            # Fetch text sources
            transcript_text = None
            if post_data['transcript_url']:
                pdf_path = f"temp_transcript_{meeting_id}.pdf"
                if self.download_pdf(post_data['transcript_url'], pdf_path):
                    transcript_text = self.extract_text_from_pdf(pdf_path)
                    try:
                        os.remove(pdf_path)
                    except Exception:
                        pass

            actions_text = None
            if post_data['actions_url']:
                actions_text = self.fetch_actions_text(post_data['actions_url'])

            # Generate the post-meeting summary
            meeting_data_dict = {
                'id': meeting_id,
                'date': meeting_date,
                'meeting_type': meeting_type,
                'url': meeting_url
            }
            post_summary = self.generate_post_meeting_summary(
                meeting_data_dict, transcript_text, actions_text
            )

            # Save everything to DB
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE meetings SET
                    transcript_url = ?,
                    actions_url = ?,
                    video_url = ?,
                    post_meeting_summary = ?,
                    completed_processed_at = ?
                WHERE meeting_id = ?
            ''', (
                post_data['transcript_url'],
                post_data['actions_url'],
                post_data['video_url'],
                post_summary,
                datetime.now().isoformat(),
                meeting_id
            ))
            conn.commit()
            conn.close()

            logging.info(f"  ✅ Post-processing complete for {meeting_id}")
            processed.append(meeting_id)

            time.sleep(2)  # Be polite to the city's servers

        return processed

    # ─────────────────────────────────────────────
    # Notifications
    # ─────────────────────────────────────────────

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
                            "value": meeting_info['summary'][:1000]
                        }
                    ],
                    "url": meeting_info['url'],
                    "color": 5814783
                }]
            }

            response = requests.post(webhook_url, json=message)
            response.raise_for_status()

            logging.info("  ✓ Discord notification sent")
            return True

        except Exception as e:
            logging.error(f"  ✗ Discord notification error: {e}")
            return False

    # ─────────────────────────────────────────────
    # Main Run Cycle
    # ─────────────────────────────────────────────

    def run_check_cycle(self, discord_webhook_url=None):
        """
        Complete check cycle:
        1. Find and process newly announced meetings
        2. Post-process meetings that have now occurred (transcript, actions, video, summary)
        3. Send notifications for newly discovered upcoming meetings
        """
        logging.info("\n" + "="*60)
        logging.info("🚀 STARTING MEETING CHECK CYCLE")
        logging.info("="*60)

        # ── Step 1: New upcoming meetings ─────────────────────────
        new_meetings = self.check_for_new_meetings()

        processed = []
        for meeting_data in new_meetings:
            meeting_info = self.process_new_meeting(meeting_data)
            processed.append(meeting_info)

            if discord_webhook_url:
                self.send_discord_notification(meeting_info, discord_webhook_url)

                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute(
                    'UPDATE meetings SET notified_at = ? WHERE meeting_id = ?',
                    (datetime.now().isoformat(), meeting_data['id'])
                )
                conn.commit()
                conn.close()

            time.sleep(2)

        # ── Step 2: Post-process completed meetings ────────────────
        completed_ids = self.process_completed_meetings()

        logging.info(f"\n{'='*60}")
        logging.info(f"✅ CHECK CYCLE COMPLETE")
        logging.info(f"{'='*60}")
        logging.info(f"New meetings processed: {len(processed)}")
        logging.info(f"Completed meetings post-processed: {len(completed_ids)}")

        return processed

    # ─────────────────────────────────────────────
    # DB Queries
    # ─────────────────────────────────────────────

    def get_recent_meetings(self, limit=10):
        """Retrieve recent (completed) meetings from database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT meeting_id, date, meeting_type, meeting_url, agenda_url,
                   gemini_summary, created_at,
                   is_completed, transcript_url, actions_url, video_url, post_meeting_summary
            FROM meetings
            WHERE is_completed = 1
            ORDER BY date DESC
            LIMIT ?
        ''', (limit,))

        meetings = []
        for row in cursor.fetchall():
            meetings.append({
                'id': row[0], 'date': row[1], 'meeting_type': row[2],
                'url': row[3], 'agenda_url': row[4], 'summary': row[5],
                'discovered_at': row[6], 'is_completed': row[7],
                'transcript_url': row[8], 'actions_url': row[9],
                'video_url': row[10], 'post_meeting_summary': row[11]
            })

        conn.close()
        return meetings

    def get_upcoming_meetings(self, limit=20):
        """Retrieve upcoming meetings from database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        today_str = date.today().isoformat()
        cursor.execute('''
            SELECT meeting_id, date, meeting_type, meeting_url, agenda_url, gemini_summary, created_at
            FROM meetings
            WHERE date >= ? AND (is_completed IS NULL OR is_completed = 0)
            ORDER BY date ASC
            LIMIT ?
        ''', (today_str, limit))

        meetings = []
        for row in cursor.fetchall():
            meetings.append({
                'id': row[0], 'date': row[1], 'meeting_type': row[2],
                'url': row[3], 'agenda_url': row[4], 'summary': row[5],
                'discovered_at': row[6], 'is_completed': 0
            })

        conn.close()
        return meetings


if __name__ == "__main__":
    print("\n" + "="*60)
    print("🏛️  AUSTIN CITY COUNCIL MEETING MONITOR")
    print("="*60)

    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
    DISCORD_WEBHOOK = os.getenv('DISCORD_WEBHOOK_URL')

    if not GEMINI_API_KEY:
        print("\n⚠️  WARNING: No Gemini API key found!")
        print("Set it with: export GEMINI_API_KEY='your-key-here'")
        print("Or paste it directly in the script above.\n")

    monitor = AustinCouncilMonitor(
        db_path='austin_meetings.db',
        gemini_api_key=GEMINI_API_KEY
    )

    new_meetings = monitor.run_check_cycle(discord_webhook_url=DISCORD_WEBHOOK)

    if new_meetings:
        print("\n" + "="*60)
        print("📋 NEW MEETINGS DISCOVERED")
        print("="*60)

        for meeting in new_meetings:
            print(f"\n📅 {meeting['date']} - {meeting['meeting_type']}")
            print(f"🔗 {meeting['url']}")
            print(f"\n{meeting['summary']}")
            print("-" * 60)

    print("\n" + "="*60)
    print("✅ RECENT COMPLETED MEETINGS")
    print("="*60)

    recent = monitor.get_recent_meetings(limit=5)
    for meeting in recent:
        print(f"\n📅 {meeting['date']} - {meeting['meeting_type']}")
        print(f"🔗 {meeting['url']}")
        summary = meeting.get('post_meeting_summary') or meeting.get('summary', '')
        print(f"📝 {summary[:200]}...")

    print("\n" + "="*60)
    print("📅 UPCOMING MEETINGS")
    print("="*60)

    upcoming = monitor.get_upcoming_meetings(limit=5)
    for meeting in upcoming:
        print(f"\n📅 {meeting['date']} - {meeting['meeting_type']}")
        print(f"🔗 {meeting['url']}")
