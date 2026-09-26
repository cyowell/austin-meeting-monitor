"""
Email Sender for Austin City Council Meeting Monitor
Uses Resend API to send meeting alerts to subscribers via Resend Audiences
"""

import os
import re
import sqlite3
import logging
from datetime import datetime

try:
    from github_pages_publisher import STRINGS, MEETING_TYPES
except ImportError:
    STRINGS = {}
    MEETING_TYPES = {}

try:
    import resend
    RESEND_AVAILABLE = True
except ImportError:
    RESEND_AVAILABLE = False
    logging.warning("resend package not installed. Run: pip install resend")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

SITE_URL = 'https://austincouncil.app'
FROM_EMAIL = 'updates@austincouncil.app'
FROM_NAME = 'Austin Council Monitor'


class MeetingEmailSender:
    """Sends HTML email alerts for new Austin City Council meetings via Resend"""

    def __init__(self, api_key, audience_id=None, db_path='austin_meetings.db'):
        self.api_key = api_key
        self.audience_id = audience_id
        self.db_path = db_path
        if RESEND_AVAILABLE:
            resend.api_key = api_key
        logging.info("✓ Email sender initialized")

    # ── Subscriber management ────────────────────────────────────────────────

    def get_subscribers(self, target_audience_id=None):
        """Fetch active subscribers from Resend — auto-discovers the audience ID"""
        try:
            # Auto-discover audience if not explicitly provided
            audience_id = target_audience_id or self.audience_id
            if not audience_id:
                audiences = resend.Audiences.list()
                items = getattr(audiences, 'data', None) or []
                if not items:
                    logging.warning("⚠️  No Resend audiences found — create one at resend.com/audiences")
                    return []
                
                # Prioritize audience named 'General'
                general_audience = None
                for item in items:
                    name = item.get('name', '') if isinstance(item, dict) else getattr(item, 'name', '')
                    if str(name).strip().lower() == 'general':
                        general_audience = item
                        break
                
                if general_audience:
                    audience_id = general_audience.get('id') if isinstance(general_audience, dict) else getattr(general_audience, 'id')
                else:
                    audience_id = items[0].get('id') or items[0].id
                
                logging.info(f"  📋 Auto-discovered audience ID: {audience_id}")

            contacts = resend.Contacts.list(audience_id=audience_id)
            data = getattr(contacts, 'data', None) or contacts.get('data', [])
            active = [c for c in data if not (c.get('unsubscribed') or getattr(c, 'unsubscribed', False))]
            logging.info(f"  📬 {len(active)} active subscriber(s)")
            return active
        except Exception as e:
            logging.error(f"  ✗ Error fetching subscribers: {e}")
            return []

    # ── Pending meetings ─────────────────────────────────────────────────────

    def get_unnotified_meetings(self):
        """Get meetings from DB that haven't been emailed yet.
        Skips any meeting whose summary is NULL or a known extraction-error
        string — those indicate the scraper failed and will retry next run.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT meeting_id, date, meeting_type, meeting_url, agenda_url, gemini_summary, gemini_summary_es
            FROM meetings
            WHERE notified_at IS NULL
            ORDER BY date DESC
        ''')
        meetings = []
        skipped = []
        # Error strings written by old versions of the scraper — never email these.
        _BAD_SUMMARIES = {
            'Unable to extract text from agenda PDF',
            'Failed to download agenda PDF',
            'Agenda not yet available. Check back later.',
        }
        for row in cursor.fetchall():
            summary = row[5]
            if not summary or summary.strip() in _BAD_SUMMARIES:
                skipped.append(row[0])
                continue
            meetings.append({
                'id': row[0], 'date': row[1], 'meeting_type': row[2],
                'url': row[3], 'agenda_url': row[4],
                'summary': summary, 'summary_es': row[6]
            })
        conn.close()
        if skipped:
            logging.warning(
                f"  ⚠️  Skipped {len(skipped)} meeting(s) with missing/broken summary "
                f"(will retry next run): {', '.join(skipped)}"
            )
        logging.info(f"  📋 {len(meetings)} unnotified meeting(s) ready to send")
        return meetings

    def mark_as_notified(self, meeting_ids):
        """Mark meetings as emailed in the DB"""
        if not meeting_ids:
            return
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        for mid in meeting_ids:
            cursor.execute('UPDATE meetings SET notified_at = ? WHERE meeting_id = ?', (now, mid))
        conn.commit()
        conn.close()
        logging.info(f"  ✓ Marked {len(meeting_ids)} meeting(s) as notified")

    # ── Email rendering ──────────────────────────────────────────────────────

    def _markdown_to_html(self, text):
        """Convert Gemini markdown output to email-safe HTML"""
        if not text:
            return ''
        lines = text.split('\n')
        out = []
        in_list = False
        for line in lines:
            s = line.strip()
            is_bullet = s.startswith('* ') or s.startswith('- ')
            if is_bullet:
                if not in_list:
                    out.append('<ul style="margin:0 0 12px 0;padding-left:22px">')
                    in_list = True
                content = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s[2:])
                content = re.sub(r'\*(.+?)\*', r'<em>\1</em>', content)
                out.append(f'<li style="margin-bottom:7px;color:#374151;line-height:1.6">{content}</li>')
            else:
                if in_list:
                    out.append('</ul>')
                    in_list = False
                if s:
                    content = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
                    content = re.sub(r'\*(.+?)\*', r'<em>\1</em>', content)
                    out.append(f'<p style="margin:0 0 10px 0;color:#374151;line-height:1.7">{content}</p>')
        if in_list:
            out.append('</ul>')
        return '\n'.join(out)

    def _meeting_card(self, m, lang='en'):
        """Render a single meeting card for the email"""
        try:
            d = datetime.strptime(m['date'], '%Y-%m-%d')
            if lang == 'es':
                months_es = ['Enero','Febrero','Marzo','Abril','Mayo','Junio','Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre']
                days_es = ['Lunes','Martes','Miércoles','Jueves','Viernes','Sábado','Domingo']
                date_full = f"{d.day} de {months_es[d.month-1]} de {d.year}"
                date_day = days_es[d.weekday()]
            else:
                date_full = d.strftime('%B %d, %Y')
                date_day = d.strftime('%A')
        except Exception:
            date_full, date_day = m['date'], ''

        summary_source = m.get('summary_es') if lang == 'es' else m.get('summary')
        summary_html = self._markdown_to_html(summary_source or '')
        
        display_type = m["meeting_type"]
        if lang == 'es':
            display_type = MEETING_TYPES.get(display_type, display_type)
            
        s = STRINGS.get(lang, STRINGS.get('en', {}))

        agenda_btn = ''
        if m.get('agenda_url'):
            agenda_btn = f'''
            <a href="{m['agenda_url']}"
               style="display:inline-block;margin-left:8px;padding:9px 16px;background:#f3f4f6;
                      color:#4b5563;text-decoration:none;border-radius:7px;font-size:13px;font-weight:600">
                📋 {s.get('download_agenda', 'Download Agenda')}
            </a>'''

        return f'''
        <div style="background:white;border-radius:12px;padding:24px;margin-bottom:18px;
                    border:1px solid #e5e7eb;box-shadow:0 2px 8px rgba(79,70,229,0.06)">
            <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:14px">
                <tr>
                    <td valign="top">
                        <div style="font-size:20px;font-weight:700;color:#4f46e5;line-height:1.1">{date_full}</div>
                        <div style="color:#9ca3af;font-size:13px;margin-top:3px">{date_day}</div>
                    </td>
                    <td valign="top" align="right">
                        <span style="display:inline-block;background:#4f46e5;color:white;
                                    padding:6px 14px;border-radius:20px;font-size:12px;
                                    font-weight:600;white-space:nowrap">
                            {display_type}
                        </span>
                    </td>
                </tr>
            </table>
            <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;
                        color:#9ca3af;margin-bottom:10px">{s.get('meeting_highlights', 'Meeting Highlights')}</div>
            <div style="font-size:14px">{summary_html}</div>
            <div style="margin-top:18px">
                <a href="{m['url']}"
                   style="display:inline-block;padding:9px 18px;background:#4f46e5;color:white;
                          text-decoration:none;border-radius:7px;font-size:13px;font-weight:600">
                    &#128196; {s.get('meeting_details', 'View Meeting Details')}
                </a>
                {agenda_btn}
            </div>
        </div>'''

    def build_email_html(self, meetings, lang='en'):
        """Build the full HTML email"""
        count = len(meetings)
        s = STRINGS.get(lang, STRINGS.get('en', {}))
        
        if lang == 'es':
            headline = f"{count} Nueva{'s' if count > 1 else ''} Reunión{'es' if count > 1 else ''} Publicada{'s' if count > 1 else ''}"
            monitor_title = "Monitor del Concejo de Austin"
            site_url = f"{SITE_URL}/es/"
            unsub_text = "Darse de baja"
        else:
            headline = f"{count} New Meeting{'s' if count > 1 else ''} Posted"
            monitor_title = "Austin City Council Monitor"
            site_url = SITE_URL
            unsub_text = "Unsubscribe"
            
        cards = ''.join(self._meeting_card(m, lang) for m in meetings)

        return f'''<!DOCTYPE html>
<html lang="{lang}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0">
    <title>{monitor_title} — {headline}</title>
</head>
<body style="margin:0;padding:0;background:#f0f2f8;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif">
    <div style="max-width:600px;margin:0 auto;padding:24px 16px 40px">

        <!-- Header -->
        <div style="background:linear-gradient(135deg,#4f46e5 0%,#7c3aed 100%);
                    border-radius:14px;padding:36px 28px;text-align:center;margin-bottom:22px">
            <div style="font-size:36px;margin-bottom:10px">🏛️</div>
            <h1 style="color:white;margin:0 0 6px;font-size:22px;font-weight:700;letter-spacing:-0.3px">
                {monitor_title}
            </h1>
            <p style="color:rgba(255,255,255,0.88);margin:0;font-size:14px">{headline}</p>
        </div>

        <!-- Meeting cards -->
        {cards}

        <!-- Footer -->
        <div style="text-align:center;padding:20px 0 0;color:#9ca3af;font-size:12px;line-height:1.8">
            <p style="margin:0 0 6px">
                <a href="{site_url}" style="color:#4f46e5;text-decoration:none;font-weight:600">
                    austincouncil.app
                </a>
                &nbsp;·&nbsp;
                <a href="{SITE_URL}/feed.xml" style="color:#4f46e5;text-decoration:none">RSS Feed</a>
                &nbsp;·&nbsp;
                <a href="https://github.com/cyowell/austin-meeting-monitor"
                   style="color:#4f46e5;text-decoration:none">GitHub</a>
            </p>
            <p style="margin:0 0 6px">
                {s.get('footer_desc', 'Automated AI-powered summaries of Austin City Council meetings.')}
            </p>
            <p style="margin:0 0 10px">
                {s.get('footer_gemini', 'For official information, visit <a href="https://www.austintexas.gov/department/city-council" style="color:#4f46e5;text-decoration:none">austintexas.gov</a>.')}
            </p>
            <p style="margin:0">
                <a href="{{{{ unsubscribe_url }}}}"
                   style="color:#9ca3af;text-decoration:underline;font-size:11px">
                    {unsub_text}
                </a>
            </p>
        </div>
    </div>
</body>
</html>'''

    # ── Main send flow ───────────────────────────────────────────────────────

    def send_alerts(self):
        """Full send cycle: find unnotified meetings, email subscribers, mark as done"""
        logging.info("\n" + "="*60)
        logging.info("📧 STARTING EMAIL ALERT CYCLE")
        logging.info("="*60)

        meetings = self.get_unnotified_meetings()
        if not meetings:
            logging.info("✓ No new meetings to notify about.")
            return 0

        # Fetch English (default) subscribers
        subscribers_en = self.get_subscribers()
        
        # Fetch Spanish subscribers
        audience_id_es = os.environ.get('RESEND_AUDIENCE_ID_ES', '80847ef2-0cbe-4dcf-b978-665c6422d0d4')
        subscribers_es = self.get_subscribers(target_audience_id=audience_id_es)
        
        total_subscribers = len(subscribers_en) + len(subscribers_es)

        if total_subscribers == 0:
            logging.warning("⚠️  No subscribers in either audience — skipping send, but marking as notified.")
            self.mark_as_notified([m['id'] for m in meetings])
            return 0

        count = len(meetings)
        subject_en = f"🏛️ {count} New Austin City Council Meeting{'s' if count > 1 else ''}"
        subject_es = f"🏛️ {count} Nueva{'s' if count > 1 else ''} Reunión{'es' if count > 1 else ''} del Concejo de Austin"
        
        html_en = self.build_email_html(meetings, lang='en')
        html_es = self.build_email_html(meetings, lang='es')

        sent = 0
        
        # Send English emails
        for sub in subscribers_en:
            email = sub.get('email')
            if not email: continue
            try:
                resend.Emails.send({
                    "from": f"{FROM_NAME} <{FROM_EMAIL}>",
                    "to": [email],
                    "subject": subject_en,
                    "html": html_en
                })
                sent += 1
                logging.info(f"  ✓ Sent (EN) → {email}")
            except Exception as e:
                logging.error(f"  ✗ Failed (EN) → {email}: {e}")
                
        # Send Spanish emails
        for sub in subscribers_es:
            email = sub.get('email')
            if not email: continue
            try:
                resend.Emails.send({
                    "from": f"Monitor del Concejo <{FROM_EMAIL}>",
                    "to": [email],
                    "subject": subject_es,
                    "html": html_es
                })
                sent += 1
                logging.info(f"  ✓ Sent (ES) → {email}")
            except Exception as e:
                logging.error(f"  ✗ Failed (ES) → {email}: {e}")

        self.mark_as_notified([m['id'] for m in meetings])

        logging.info(f"\n✅ EMAIL CYCLE COMPLETE: {sent}/{total_subscribers} sent")
        return sent


if __name__ == "__main__":
    import sys

    api_key = os.getenv('RESEND_API_KEY')
    audience_id = os.getenv('RESEND_AUDIENCE_ID')

    if not api_key:
        print("❌ RESEND_API_KEY environment variable not set")
        sys.exit(1)

    sender = MeetingEmailSender(
        api_key=api_key,
        audience_id=audience_id,
        db_path='austin_meetings.db'
    )
    sender.send_alerts()
