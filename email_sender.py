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

    def get_subscribers(self):
        """Fetch active subscribers from Resend — auto-discovers the audience ID"""
        try:
            # Auto-discover audience if not explicitly provided
            audience_id = self.audience_id
            if not audience_id:
                audiences = resend.Audiences.list()
                items = getattr(audiences, 'data', None) or []
                if not items:
                    logging.warning("⚠️  No Resend audiences found — create one at resend.com/audiences")
                    return []
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
        """Get meetings from DB that haven't been emailed yet"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT meeting_id, date, meeting_type, meeting_url, agenda_url, gemini_summary
            FROM meetings
            WHERE notified_at IS NULL
            ORDER BY date DESC
        ''')
        meetings = []
        for row in cursor.fetchall():
            meetings.append({
                'id': row[0], 'date': row[1], 'meeting_type': row[2],
                'url': row[3], 'agenda_url': row[4],
                'summary': row[5] or 'Meeting summary will be available soon.'
            })
        conn.close()
        logging.info(f"  📋 {len(meetings)} unnotified meeting(s) found")
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

    def _meeting_card(self, m):
        """Render a single meeting card for the email"""
        try:
            d = datetime.strptime(m['date'], '%Y-%m-%d')
            date_full = d.strftime('%B %d, %Y')
            date_day = d.strftime('%A')
        except Exception:
            date_full, date_day = m['date'], ''

        summary_html = self._markdown_to_html(m.get('summary', ''))

        agenda_btn = ''
        if m.get('agenda_url'):
            agenda_btn = f'''
            <a href="{m['agenda_url']}"
               style="display:inline-block;margin-left:8px;padding:9px 16px;background:#f3f4f6;
                      color:#4b5563;text-decoration:none;border-radius:7px;font-size:13px;font-weight:600">
                📋 Download Agenda
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
                            {m['meeting_type']}
                        </span>
                    </td>
                </tr>
            </table>
            <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;
                        color:#9ca3af;margin-bottom:10px">Meeting Highlights</div>
            <div style="font-size:14px">{summary_html}</div>
            <div style="margin-top:18px">
                <a href="{m['url']}"
                   style="display:inline-block;padding:9px 18px;background:#4f46e5;color:white;
                          text-decoration:none;border-radius:7px;font-size:13px;font-weight:600">
                    &#128196; View Meeting Details
                </a>
                {agenda_btn}
            </div>
        </div>'''

    def build_email_html(self, meetings):
        """Build the full HTML email"""
        count = len(meetings)
        headline = f"{count} New Meeting{'s' if count > 1 else ''} Posted"
        cards = ''.join(self._meeting_card(m) for m in meetings)

        return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0">
    <title>Austin City Council — {headline}</title>
</head>
<body style="margin:0;padding:0;background:#f0f2f8;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif">
    <div style="max-width:600px;margin:0 auto;padding:24px 16px 40px">

        <!-- Header -->
        <div style="background:linear-gradient(135deg,#4f46e5 0%,#7c3aed 100%);
                    border-radius:14px;padding:36px 28px;text-align:center;margin-bottom:22px">
            <div style="font-size:36px;margin-bottom:10px">🏛️</div>
            <h1 style="color:white;margin:0 0 6px;font-size:22px;font-weight:700;letter-spacing:-0.3px">
                Austin City Council Monitor
            </h1>
            <p style="color:rgba(255,255,255,0.88);margin:0;font-size:14px">{headline}</p>
        </div>

        <!-- Meeting cards -->
        {cards}

        <!-- Footer -->
        <div style="text-align:center;padding:20px 0 0;color:#9ca3af;font-size:12px;line-height:1.8">
            <p style="margin:0 0 6px">
                <a href="{SITE_URL}" style="color:#4f46e5;text-decoration:none;font-weight:600">
                    austincouncil.app
                </a>
                &nbsp;·&nbsp;
                <a href="{SITE_URL}/feed.xml" style="color:#4f46e5;text-decoration:none">RSS Feed</a>
                &nbsp;·&nbsp;
                <a href="https://github.com/cyowell/austin-meeting-monitor"
                   style="color:#4f46e5;text-decoration:none">GitHub</a>
            </p>
            <p style="margin:0 0 6px">
                Automated AI-powered summaries of Austin City Council meetings.
            </p>
            <p style="margin:0 0 10px">
                For official information, visit
                <a href="https://www.austintexas.gov/department/city-council"
                   style="color:#4f46e5;text-decoration:none">austintexas.gov</a>
            </p>
            <p style="margin:0">
                <a href="{{{{ unsubscribe_url }}}}"
                   style="color:#9ca3af;text-decoration:underline;font-size:11px">
                    Unsubscribe
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

        subscribers = self.get_subscribers()
        if not subscribers:
            logging.warning("⚠️  No subscribers — skipping send, but marking as notified.")
            self.mark_as_notified([m['id'] for m in meetings])
            return 0

        count = len(meetings)
        subject = f"🏛️ {count} New Austin City Council Meeting{'s' if count > 1 else ''}"
        html = self.build_email_html(meetings)

        sent = 0
        for sub in subscribers:
            email = sub.get('email')
            if not email:
                continue
            try:
                resend.Emails.send({
                    "from": f"{FROM_NAME} <{FROM_EMAIL}>",
                    "to": [email],
                    "subject": subject,
                    "html": html
                })
                sent += 1
                logging.info(f"  ✓ Sent → {email}")
            except Exception as e:
                logging.error(f"  ✗ Failed → {email}: {e}")

        self.mark_as_notified([m['id'] for m in meetings])

        logging.info(f"\n✅ EMAIL CYCLE COMPLETE: {sent}/{len(subscribers)} sent")
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
