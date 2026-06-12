"""
GitHub Pages Publisher for Austin City Council Meeting Monitor
Generates static HTML pages and RSS feed for automated publishing
Version: 4.0 - Upcoming / Recent sections with post-meeting summaries
"""

SUBSCRIBE_API_URL = 'https://austin-meeting-monitor.vercel.app/subscribe'

import os
import re
import sqlite3
import logging
from datetime import datetime, date
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class GitHubPagesPublisher:
    """Generates static HTML pages and RSS feed for GitHub Pages hosting"""

    def __init__(self, db_path='austin_meetings.db', output_dir='docs'):
        self.db_path = db_path
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        logging.info(f"✓ GitHub Pages publisher initialized (v4.0)")
        logging.info(f"  Output directory: {self.output_dir}")

    def get_all_meetings(self, limit=None):
        """Get all meetings from database, sorted by date (newest first)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("PRAGMA table_info(meetings)")
        columns = {col[1] for col in cursor.fetchall()}
        logging.info(f"  Available columns: {sorted(columns)}")

        # Build column references, accounting for DB schema versions
        id_col    = 'meeting_id' if 'meeting_id' in columns else 'id'
        url_col   = 'meeting_url' if 'meeting_url' in columns else 'url'
        summ_col  = 'gemini_summary' if 'gemini_summary' in columns else 'summary'

        optional = {
            'is_completed':        'is_completed'        in columns,
            'transcript_url':      'transcript_url'      in columns,
            'actions_url':         'actions_url'         in columns,
            'video_url':           'video_url'           in columns,
            'post_meeting_summary':'post_meeting_summary' in columns,
            'created_at':         'created_at'           in columns,
        }

        select = [id_col, 'date', 'meeting_type', url_col, 'agenda_url', summ_col]
        if optional['created_at']:          select.append('created_at')
        if optional['is_completed']:        select.append('is_completed')
        if optional['transcript_url']:      select.append('transcript_url')
        if optional['actions_url']:         select.append('actions_url')
        if optional['video_url']:           select.append('video_url')
        if optional['post_meeting_summary']:select.append('post_meeting_summary')

        query = f"SELECT {', '.join(select)} FROM meetings ORDER BY date DESC"
        if limit:
            query += f' LIMIT {limit}'

        cursor.execute(query)
        meetings = []
        today_str = date.today().isoformat()

        for row in cursor.fetchall():
            i = 0
            def _get(idx_local):
                return row[idx_local] if idx_local < len(row) else None

            m_id         = row[0]
            m_date       = row[1]
            m_type       = row[2]
            m_url        = row[3]
            m_agenda     = row[4]
            m_summary    = row[5] or 'Meeting summary will be available soon.'
            idx = 6

            m_created    = row[idx] if optional['created_at'] else datetime.now().strftime('%Y-%m-%d %H:%M:%S'); idx += 1 if optional['created_at'] else 0
            m_completed  = row[idx] if optional['is_completed'] else None; idx += 1 if optional['is_completed'] else 0
            m_transcript = row[idx] if optional['transcript_url'] else None; idx += 1 if optional['transcript_url'] else 0
            m_actions    = row[idx] if optional['actions_url'] else None; idx += 1 if optional['actions_url'] else 0
            m_video      = row[idx] if optional['video_url'] else None; idx += 1 if optional['video_url'] else 0
            m_post_summ  = row[idx] if optional['post_meeting_summary'] else None

            # Determine completed status: column value, or date in the past
            if m_completed is None:
                is_completed = m_date < today_str
            else:
                is_completed = bool(m_completed)

            meetings.append({
                'id': m_id,
                'date': m_date,
                'meeting_type': m_type,
                'url': m_url,
                'agenda_url': m_agenda,
                'summary': m_summary,
                'created_at': m_created,
                'is_completed': is_completed,
                'transcript_url': m_transcript,
                'actions_url': m_actions,
                'video_url': m_video,
                'post_meeting_summary': m_post_summ,
            })

        conn.close()
        logging.info(f"  📊 Found {len(meetings)} meetings in database")
        return meetings

    def format_date(self, date_str):
        """Format date string nicely"""
        try:
            d = datetime.strptime(date_str, '%Y-%m-%d')
            return {'full': d.strftime('%B %d, %Y'), 'short': d.strftime('%b %d, %Y'),
                    'day': d.strftime('%A'), 'iso': date_str}
        except Exception:
            return {'full': date_str, 'short': date_str, 'day': '', 'iso': date_str}

    def _markdown_to_html(self, text):
        """Convert basic Gemini markdown output to HTML"""
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
                    out.append('<ul>')
                    in_list = True
                content = s[2:]
                content = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', content)
                content = re.sub(r'\*(.+?)\*', r'<em>\1</em>', content)
                out.append(f'<li>{content}</li>')
            else:
                if in_list:
                    out.append('</ul>')
                    in_list = False
                if s:
                    content = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
                    content = re.sub(r'\*(.+?)\*', r'<em>\1</em>', content)
                    out.append(f'<p>{content}</p>')

        if in_list:
            out.append('</ul>')
        return '\n'.join(out)

    def _safe_filter_key(self, meeting_type):
        """Convert meeting type to a safe CSS/data attribute value"""
        return re.sub(r'[^a-z0-9]+', '-', meeting_type.lower()).strip('-')

    def _build_upcoming_card(self, m):
        """Build HTML card for an upcoming (future) meeting"""
        di = self.format_date(m['date'])
        key = self._safe_filter_key(m['meeting_type'])
        summary_html = self._markdown_to_html(m.get('summary', ''))

        agenda_btn = ''
        if m.get('agenda_url'):
            agenda_btn = f'''<a href="{m["agenda_url"]}" class="meeting-link meeting-link-primary" target="_blank" rel="noopener">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                Download Agenda</a>'''

        share_onclick = "openShareModal('{}','{}','{}')".format(
            di["full"].replace("'", "\\'"),
            m["meeting_type"].replace("'", "\\'"),
            "https://austincouncil.app"
        )
        share_btn = f'''<button class="btn-share-card" onclick="{share_onclick}" title="Share this meeting">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>
            Share</button>'''

        summary_section = ''
        if summary_html:
            summary_section = f'''
                <div class="meeting-summary">
                    <h3>Agenda Preview</h3>
                    <div class="summary-content">{summary_html}</div>
                </div>'''

        return f'''
        <div class="meeting-card meeting-card--upcoming" data-type="{key}">
            <div class="meeting-header">
                <div>
                    <div class="meeting-date">{di["full"]}</div>
                    <div class="meeting-day">{di["day"]}</div>
                </div>
                <div style="display:flex;flex-direction:column;align-items:flex-end;gap:8px">
                    <div class="meeting-type">{m["meeting_type"]}</div>
                    <div class="status-badge status-badge--upcoming">
                        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                        Upcoming
                    </div>
                </div>
            </div>
            {summary_section}
            <div class="meeting-links">
                <a href="{m["url"]}" class="meeting-link meeting-link-secondary" target="_blank" rel="noopener">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
                    Meeting Details</a>
                {agenda_btn}
                <span class="meeting-links-spacer"></span>
                {share_btn}
            </div>
        </div>'''

    def _build_recent_card(self, m):
        """Build HTML card for a completed (past) meeting"""
        di = self.format_date(m['date'])
        key = self._safe_filter_key(m['meeting_type'])

        # Prefer post-meeting summary, fall back to agenda summary
        display_summary = m.get('post_meeting_summary') or m.get('summary', '')
        summary_html = self._markdown_to_html(display_summary)
        summary_label = 'What the Council Did' if m.get('post_meeting_summary') else 'Meeting Highlights'

        # Post-meeting action buttons
        extra_btns = ''
        if m.get('video_url'):
            extra_btns += f'''<a href="{m["video_url"]}" class="meeting-link meeting-link-video" target="_blank" rel="noopener">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                Watch Video</a>'''
        if m.get('actions_url'):
            extra_btns += f'''<a href="{m["actions_url"]}" class="meeting-link meeting-link-actions" target="_blank" rel="noopener">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
                Actions Taken</a>'''
        if m.get('transcript_url'):
            extra_btns += f'''<a href="{m["transcript_url"]}" class="meeting-link meeting-link-transcript" target="_blank" rel="noopener">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
                Transcript</a>'''

        agenda_btn = ''
        if m.get('agenda_url'):
            agenda_btn = f'''<a href="{m["agenda_url"]}" class="meeting-link meeting-link-secondary" target="_blank" rel="noopener">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                Agenda</a>'''

        share_onclick = "openShareModal('{}','{}','{}')".format(
            di["full"].replace("'", "\\'"),
            m["meeting_type"].replace("'", "\\'"),
            "https://austincouncil.app"
        )
        share_btn = f'''<button class="btn-share-card" onclick="{share_onclick}" title="Share this meeting">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>
            Share</button>'''

        return f'''
        <div class="meeting-card meeting-card--recent" data-type="{key}">
            <div class="meeting-header">
                <div>
                    <div class="meeting-date">{di["full"]}</div>
                    <div class="meeting-day">{di["day"]}</div>
                </div>
                <div style="display:flex;flex-direction:column;align-items:flex-end;gap:8px">
                    <div class="meeting-type">{m["meeting_type"]}</div>
                    <div class="status-badge status-badge--completed">
                        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
                        Completed
                    </div>
                </div>
            </div>
            <div class="meeting-summary">
                <h3>{summary_label}</h3>
                <div class="summary-content">{summary_html}</div>
            </div>
            <div class="meeting-links">
                <a href="{m["url"]}" class="meeting-link meeting-link-secondary" target="_blank" rel="noopener">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
                    Meeting Details</a>
                {agenda_btn}
                {extra_btns}
                <span class="meeting-links-spacer"></span>
                {share_btn}
            </div>
        </div>'''

    def generate_html_index(self, meetings):
        """Generate main index.html page with Upcoming and Recent sections"""
        today_str = date.today().isoformat()

        upcoming = [m for m in meetings if not m['is_completed']]
        recent   = [m for m in meetings if m['is_completed']]

        # Sort: upcoming ascending (soonest first), recent descending (newest first)
        upcoming.sort(key=lambda m: m['date'])
        recent.sort(key=lambda m: m['date'], reverse=True)

        total = len(meetings)
        n_upcoming = len(upcoming)
        n_recent = len(recent)
        latest_date = self.format_date(recent[0]['date'])['short'] if recent else ('N/A')

        # Count meeting types across all
        type_counts = {}
        for m in meetings:
            t = m['meeting_type']
            type_counts[t] = type_counts.get(t, 0) + 1

        # Filter buttons
        filter_btns = f'<button class="filter-btn active" data-filter="all" onclick="filterMeetings(\'all\')">All <span class="badge">{total}</span></button>\n'
        for mtype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
            key = self._safe_filter_key(mtype)
            filter_btns += f'<button class="filter-btn" data-filter="{key}" onclick="filterMeetings(\'{key}\')">{mtype} <span class="badge">{count}</span></button>\n'

        # Build upcoming cards
        upcoming_cards = ''
        for m in upcoming:
            upcoming_cards += self._build_upcoming_card(m)
        if not upcoming_cards:
            upcoming_cards = '<div class="no-meetings-section"><p>No upcoming meetings scheduled. Check back soon.</p></div>'

        # Build recent cards
        recent_cards = ''
        for m in recent:
            recent_cards += self._build_recent_card(m)
        if not recent_cards:
            recent_cards = '<div class="no-meetings-section"><p>No completed meetings in the database yet.</p></div>'

        updated = datetime.now().strftime('%B %d, %Y at %I:%M %p')

        return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="description" content="Automated AI-powered summaries of Austin City Council meetings. Stay informed about local government.">
    <title>Austin City Council Meeting Monitor</title>
    <link rel="alternate" type="application/rss+xml" title="Austin City Council Meetings" href="feed.xml">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        *{{margin:0;padding:0;box-sizing:border-box}}
        body{{font-family:'Inter',-apple-system,BlinkMacSystemFont,sans-serif;line-height:1.6;color:#1a1a2e;background:#f0f2f8;min-height:100vh}}

        /* ── Header ── */
        header{{background:linear-gradient(135deg,#4f46e5 0%,#7c3aed 100%);color:white;padding:48px 24px 40px;text-align:center;position:relative;overflow:hidden}}
        header::before{{content:'';position:absolute;inset:0;background:url("data:image/svg+xml,%3Csvg width='40' height='40' viewBox='0 0 40 40' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='%23fff' fill-opacity='0.04'%3E%3Cpath d='M20 20h20v20H20zM0 0h20v20H0z'/%3E%3C/g%3E%3C/svg%3E")}}
        header h1{{font-size:2.3em;font-weight:700;letter-spacing:-.5px;margin-bottom:8px;position:relative}}
        header>p{{font-size:1em;opacity:.85;position:relative}}
        .subscribe-box{{background:rgba(255,255,255,.12);padding:22px 24px;margin:24px auto 0;border-radius:12px;backdrop-filter:blur(10px);border:1px solid rgba(255,255,255,.2);max-width:480px;position:relative}}
        .subscribe-box h3{{font-size:1.05em;margin-bottom:5px}}
        .subscribe-box p{{font-size:.88em;opacity:.85;margin-bottom:14px}}
        .subscribe-form{{display:flex;gap:8px;flex-wrap:wrap}}
        .subscribe-form input{{flex:1;min-width:180px;padding:10px 14px;border:none;border-radius:8px;font-family:inherit;font-size:.9em;outline:none;color:#1a1a2e}}
        .subscribe-form button{{padding:10px 18px;background:#f97316;color:white;border:none;border-radius:8px;font-family:inherit;font-size:.9em;font-weight:600;cursor:pointer;transition:background .15s;white-space:nowrap}}
        .subscribe-form button:hover{{background:#ea6c0a}}
        .subscribe-form button:disabled{{opacity:.6;cursor:not-allowed}}
        .subscribe-msg{{font-size:.85em;margin-top:10px;min-height:1.2em}}
        .subscribe-msg.success{{color:#86efac}}
        .subscribe-msg.error{{color:#fca5a5}}
        .btn-rss{{display:inline-flex;align-items:center;gap:6px;padding:8px 14px;background:rgba(255,255,255,.15);color:white;text-decoration:none;border-radius:8px;font-size:.82em;font-weight:600;border:1px solid rgba(255,255,255,.25);transition:background .15s;margin-top:10px}}
        .btn-rss:hover{{background:rgba(255,255,255,.25)}}

        /* ── Layout ── */
        .container{{max-width:900px;margin:0 auto;padding:28px 16px 80px}}

        /* ── Stats ── */
        .stats{{display:flex;justify-content:space-around;background:white;border-radius:12px;padding:22px;margin-bottom:20px;box-shadow:0 2px 12px rgba(79,70,229,.08)}}
        .stat{{text-align:center}}
        .stat-number{{font-size:2em;font-weight:700;color:#4f46e5;line-height:1}}
        .stat-label{{color:#6b7280;font-size:.75em;text-transform:uppercase;letter-spacing:.08em;margin-top:4px}}

        /* ── Controls ── */
        .controls{{background:white;border-radius:12px;padding:18px 22px;margin-bottom:28px;box-shadow:0 2px 12px rgba(79,70,229,.08)}}
        .search-wrap{{position:relative;margin-bottom:14px}}
        .search-wrap svg{{position:absolute;left:13px;top:50%;transform:translateY(-50%);color:#9ca3af;pointer-events:none}}
        #search-input{{width:100%;padding:11px 13px 11px 40px;border:2px solid #e5e7eb;border-radius:8px;font-family:inherit;font-size:.93em;color:#1a1a2e;outline:none;transition:border-color .2s}}
        #search-input:focus{{border-color:#4f46e5}}
        #search-input::placeholder{{color:#9ca3af}}
        .filter-row{{display:flex;flex-wrap:wrap;gap:7px}}
        .filter-btn{{padding:6px 13px;border:2px solid #e5e7eb;border-radius:20px;background:white;color:#6b7280;font-family:inherit;font-size:.81em;font-weight:600;cursor:pointer;transition:all .15s;display:flex;align-items:center;gap:5px}}
        .filter-btn:hover{{border-color:#4f46e5;color:#4f46e5}}
        .filter-btn.active{{border-color:#4f46e5;background:#4f46e5;color:white}}
        .filter-btn .badge{{background:rgba(255,255,255,.25);border-radius:10px;padding:1px 6px;font-size:.85em}}
        .filter-btn:not(.active) .badge{{background:#f3f4f6;color:#4b5563}}

        /* ── Section Headers ── */
        .section-header{{display:flex;align-items:center;gap:12px;margin:32px 0 16px}}
        .section-header h2{{font-size:1.25em;font-weight:700;color:#1a1a2e}}
        .section-count{{background:#f3f4f6;color:#6b7280;border-radius:20px;padding:3px 11px;font-size:.78em;font-weight:700}}
        .section-divider{{flex:1;height:2px;background:#e5e7eb;border-radius:1px}}
        .section-header--upcoming h2{{color:#4f46e5}}
        .section-header--upcoming .section-count{{background:#ede9fe;color:#6d28d9}}
        .section-header--recent h2{{color:#059669}}
        .section-header--recent .section-count{{background:#d1fae5;color:#065f46}}

        /* ── Meeting Cards ── */
        .meeting-card{{background:white;border-radius:14px;padding:26px 30px;margin-bottom:18px;box-shadow:0 2px 12px rgba(79,70,229,.08);border:2px solid transparent;transition:transform .2s,box-shadow .2s,border-color .2s}}
        .meeting-card:hover{{transform:translateY(-3px);box-shadow:0 8px 28px rgba(79,70,229,.14)}}
        .meeting-card.hidden{{display:none}}
        .meeting-card--upcoming{{border-left:4px solid #818cf8}}
        .meeting-card--upcoming:hover{{border-color:#4f46e5;border-left-color:#4f46e5}}
        .meeting-card--recent{{border-left:4px solid #34d399}}
        .meeting-card--recent:hover{{border-color:#059669;border-left-color:#059669}}

        /* ── Card Internals ── */
        .meeting-header{{display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:12px;margin-bottom:18px}}
        .meeting-date{{font-size:1.6em;font-weight:700;color:#4f46e5;line-height:1.1}}
        .meeting-card--recent .meeting-date{{color:#059669}}
        .meeting-day{{color:#9ca3af;font-size:.84em;margin-top:4px}}
        .meeting-type{{background:linear-gradient(135deg,#4f46e5,#7c3aed);color:white;padding:7px 15px;border-radius:20px;font-size:.8em;font-weight:600;white-space:nowrap}}
        .meeting-card--recent .meeting-type{{background:linear-gradient(135deg,#059669,#047857)}}

        /* ── Status Badges ── */
        .status-badge{{display:inline-flex;align-items:center;gap:5px;padding:4px 10px;border-radius:20px;font-size:.75em;font-weight:700}}
        .status-badge--upcoming{{background:#ede9fe;color:#6d28d9}}
        .status-badge--completed{{background:#d1fae5;color:#065f46}}

        /* ── Summary ── */
        .meeting-summary h3{{font-size:.75em;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:#9ca3af;margin-bottom:10px}}
        .summary-content{{color:#374151;line-height:1.8}}
        .summary-content ul{{padding-left:20px}}
        .summary-content li{{margin-bottom:7px}}
        .summary-content p{{margin-bottom:8px}}
        .summary-content strong{{color:#1a1a2e}}

        /* ── Meeting Links ── */
        .meeting-links{{display:flex;gap:8px;margin-top:22px;flex-wrap:wrap;align-items:center}}
        .meeting-link{{display:inline-flex;align-items:center;gap:6px;padding:9px 15px;border-radius:8px;font-weight:600;font-size:.84em;text-decoration:none;transition:all .15s}}
        .meeting-link-primary{{background:#4f46e5;color:white}}
        .meeting-link-primary:hover{{background:#4338ca;transform:translateY(-1px);box-shadow:0 4px 12px rgba(79,70,229,.35)}}
        .meeting-link-secondary{{background:#f3f4f6;color:#4b5563;border:2px solid #e5e7eb}}
        .meeting-link-secondary:hover{{background:#e5e7eb;color:#1a1a2e}}
        .meeting-link-video{{background:#dc2626;color:white}}
        .meeting-link-video:hover{{background:#b91c1c;transform:translateY(-1px);box-shadow:0 4px 12px rgba(220,38,38,.35)}}
        .meeting-link-actions{{background:#059669;color:white}}
        .meeting-link-actions:hover{{background:#047857;transform:translateY(-1px);box-shadow:0 4px 12px rgba(5,150,105,.35)}}
        .meeting-link-transcript{{background:#0891b2;color:white}}
        .meeting-link-transcript:hover{{background:#0e7490;transform:translateY(-1px);box-shadow:0 4px 12px rgba(8,145,178,.35)}}
        .meeting-links-spacer{{flex:1}}
        .btn-share-card{{display:inline-flex;align-items:center;gap:6px;padding:9px 15px;border-radius:8px;font-weight:600;font-size:.84em;text-decoration:none;transition:all .15s;background:#f0edff;color:#4f46e5;border:2px solid #ddd9ff;cursor:pointer;font-family:inherit}}
        .btn-share-card:hover{{background:#e0daff;border-color:#4f46e5;transform:translateY(-1px)}}

        /* ── Empty States ── */
        .no-results,.no-meetings{{text-align:center;padding:60px 20px;color:#6b7280}}
        .no-results{{display:none}}
        .no-results h2,.no-meetings h2{{font-size:1.4em;margin-bottom:8px;color:#374151}}
        .no-meetings-section{{text-align:center;padding:32px 20px;color:#9ca3af;font-size:.9em;background:white;border-radius:12px;border:2px dashed #e5e7eb}}

        /* ── Footer ── */
        footer{{background:white;padding:26px 30px;text-align:center;color:#6b7280;font-size:.86em;border-top:2px solid #f0f2f8}}
        footer p{{margin:5px 0}}
        footer a{{color:#4f46e5;text-decoration:none}}
        footer a:hover{{text-decoration:underline}}

        /* ── FAB & Share ── */
        #back-to-top{{position:fixed;bottom:80px;right:26px;background:#4f46e5;color:white;border:none;border-radius:50%;width:44px;height:44px;cursor:pointer;font-size:19px;box-shadow:0 4px 16px rgba(79,70,229,.4);display:flex;align-items:center;justify-content:center;opacity:0;transform:translateY(10px);transition:opacity .25s,transform .25s;pointer-events:none}}
        #back-to-top.visible{{opacity:1;transform:translateY(0);pointer-events:all}}
        #back-to-top:hover{{background:#4338ca}}
        #share-fab{{position:fixed;bottom:26px;right:26px;background:linear-gradient(135deg,#4f46e5,#7c3aed);color:white;border:none;border-radius:50%;width:48px;height:48px;cursor:pointer;box-shadow:0 4px 18px rgba(79,70,229,.5);display:flex;align-items:center;justify-content:center;transition:transform .2s,box-shadow .2s;z-index:900}}
        #share-fab:hover{{transform:scale(1.1);box-shadow:0 6px 24px rgba(79,70,229,.65)}}
        #share-fab svg{{pointer-events:none}}
        #share-modal-overlay{{position:fixed;inset:0;background:rgba(15,10,40,.55);backdrop-filter:blur(6px);z-index:1000;display:flex;align-items:flex-end;justify-content:flex-end;padding:26px;opacity:0;pointer-events:none;transition:opacity .2s}}
        #share-modal-overlay.open{{opacity:1;pointer-events:all}}
        #share-modal{{background:white;border-radius:20px;padding:28px;width:340px;max-width:calc(100vw - 48px);box-shadow:0 20px 60px rgba(79,70,229,.25),0 4px 16px rgba(0,0,0,.1);transform:translateY(16px) scale(.97);transition:transform .22s cubic-bezier(.34,1.4,.64,1),opacity .2s;opacity:0;position:relative}}
        #share-modal-overlay.open #share-modal{{transform:translateY(0) scale(1);opacity:1}}
        .share-modal-brand{{display:flex;align-items:center;gap:10px;margin-bottom:16px;padding-bottom:14px;border-bottom:2px solid #f0f2f8}}
        .share-modal-brand-icon{{width:36px;height:36px;border-radius:10px;background:linear-gradient(135deg,#4f46e5,#7c3aed);display:flex;align-items:center;justify-content:center;flex-shrink:0}}
        .share-modal-brand-text{{font-weight:700;font-size:.92em;color:#1a1a2e;line-height:1.3}}
        .share-modal-brand-text span{{display:block;font-size:.78em;font-weight:500;color:#6b7280;margin-top:2px}}
        .share-modal-close{{position:absolute;top:16px;right:16px;background:#f3f4f6;border:none;border-radius:8px;width:30px;height:30px;cursor:pointer;display:flex;align-items:center;justify-content:center;color:#6b7280;transition:background .15s}}
        .share-modal-close:hover{{background:#e5e7eb;color:#1a1a2e}}
        .share-preview{{background:#f8f7ff;border-radius:12px;padding:14px 16px;margin-bottom:18px;border-left:4px solid #4f46e5}}
        .share-preview-date{{font-size:.75em;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#7c3aed;margin-bottom:4px}}
        .share-preview-title{{font-size:.9em;font-weight:600;color:#1a1a2e;line-height:1.45}}
        .share-preview-source{{font-size:.75em;color:#9ca3af;margin-top:6px}}
        .share-buttons{{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin-bottom:14px}}
        .share-btn{{display:flex;flex-direction:column;align-items:center;gap:6px;padding:13px 8px;border-radius:12px;border:2px solid #e5e7eb;background:white;cursor:pointer;font-family:inherit;font-size:.78em;font-weight:700;color:#374151;transition:all .15s}}
        .share-btn:hover{{transform:translateY(-2px);box-shadow:0 4px 12px rgba(0,0,0,.08)}}
        .share-btn.twitter:hover{{border-color:#1d9bf0;color:#1d9bf0;background:#f0f9ff}}
        .share-btn.linkedin:hover{{border-color:#0a66c2;color:#0a66c2;background:#f0f6ff}}
        .share-btn.native:hover{{border-color:#4f46e5;color:#4f46e5;background:#f0edff}}
        .share-btn svg{{display:block}}
        .share-copy-row{{display:flex;gap:8px;align-items:center}}
        .share-copy-input{{flex:1;padding:9px 12px;border:2px solid #e5e7eb;border-radius:8px;font-family:inherit;font-size:.82em;color:#6b7280;background:#f9fafb;outline:none;cursor:default}}
        .share-copy-btn{{padding:9px 14px;background:#4f46e5;color:white;border:none;border-radius:8px;font-family:inherit;font-size:.82em;font-weight:700;cursor:pointer;transition:background .15s;white-space:nowrap}}
        .share-copy-btn:hover{{background:#4338ca}}
        .share-copy-btn.copied{{background:#10b981}}

        /* ── Responsive ── */
        @media(max-width:480px){{
            #share-modal{{width:100%;border-radius:20px 20px 16px 16px}}
            #share-modal-overlay{{padding:16px;align-items:flex-end;justify-content:center}}
        }}
        @media(max-width:640px){{
            header h1{{font-size:1.65em}}
            .meeting-card{{padding:18px}}
            .meeting-date{{font-size:1.25em}}
            .stats{{flex-direction:column;gap:16px}}
            .meeting-links{{gap:6px}}
            .meeting-link{{font-size:.8em;padding:8px 12px}}
        }}
    </style>
</head>
<body>
    <header>
        <h1>🏛️ Austin City Council Meeting Monitor</h1>
        <p>Automated AI-powered summaries of Austin City Council meetings</p>
        <nav style="margin-top:10px;font-size:.83em;opacity:.8">
            <a href="/about" style="color:white;text-decoration:none" onmouseover="this.style.opacity=1" onmouseout="this.style.opacity=.8">About &amp; Methodology</a>
            &nbsp;·&nbsp;
            <a href="/about#journalists" style="color:white;text-decoration:none" onmouseover="this.style.opacity=1" onmouseout="this.style.opacity=.8">For Journalists</a>
            &nbsp;·&nbsp;
            <a href="/archives/" style="color:white;text-decoration:none" onmouseover="this.style.opacity=1" onmouseout="this.style.opacity=.8">Archives</a>
        </nav>
        <div class="subscribe-box">
            <h3>📬 Never Miss a Meeting</h3>
            <p>Get email updates when new meetings are posted</p>
            <div class="subscribe-form">
                <input type="email" id="sub-email" placeholder="your@email.com" autocomplete="email">
                <button id="sub-btn" onclick="subscribe()">Subscribe</button>
            </div>
            <div class="subscribe-msg" id="sub-msg"></div>
            <a href="feed.xml" class="btn-rss">📡 RSS Feed</a>
        </div>
    </header>

    <div class="container">
        <div class="stats">
            <div class="stat">
                <div class="stat-number">{n_upcoming}</div>
                <div class="stat-label">Upcoming</div>
            </div>
            <div class="stat">
                <div class="stat-number">{n_recent}</div>
                <div class="stat-label">Completed</div>
            </div>
            <div class="stat">
                <div class="stat-number">{latest_date}</div>
                <div class="stat-label">Last Meeting</div>
            </div>
        </div>

        <div class="controls">
            <div class="search-wrap">
                <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
                <input type="text" id="search-input" placeholder="Search by keyword — housing, budget, zoning..." oninput="applyFilters()">
            </div>
            <div class="filter-row" id="filter-row">
                {filter_btns}
            </div>
        </div>

        <!-- Upcoming Meetings -->
        <div class="section-header section-header--upcoming">
            <h2>📅 Upcoming Meetings</h2>
            <span class="section-count">{n_upcoming}</span>
            <div class="section-divider"></div>
        </div>
        <div id="upcoming-list">
            {upcoming_cards}
        </div>

        <!-- Recent Meetings -->
        <div class="section-header section-header--recent">
            <h2>✅ Recent Meetings</h2>
            <span class="section-count">{n_recent}</span>
            <div class="section-divider"></div>
        </div>
        <div id="recent-list">
            {recent_cards}
        </div>

        <div class="no-results" id="no-results">
            <h2>🔍 No matching meetings</h2>
            <p>Try a different keyword or filter.</p>
        </div>
    </div>

    <footer>
        <p><strong>About This Site</strong></p>
        <p>This site automatically monitors Austin City Council meetings and generates AI-powered summaries to help citizens stay informed.</p>
        <p>Summaries are generated using Google Gemini AI. For official information, always refer to the <a href="https://www.austintexas.gov/department/city-council" target="_blank" rel="noopener">City of Austin website</a>.</p>
        <p style="margin-top:12px">
            <a href="/about">About &amp; Methodology</a> &nbsp;|&nbsp;
            <a href="/about#journalists">For Journalists</a> &nbsp;|&nbsp;
            <a href="/archives/">Archives</a> &nbsp;|&nbsp;
            <a href="/feed.xml">RSS Feed</a> &nbsp;|&nbsp;
            <a href="https://github.com/cyowell/austin-meeting-monitor">GitHub</a>
        </p>
        <p style="margin-top:8px;color:#9ca3af;font-size:.82em">Last updated: {updated}</p>
    </footer>

    <button id="back-to-top" onclick="window.scrollTo({{top:0,behavior:'smooth'}})" title="Back to top">↑</button>

    <!-- Share FAB -->
    <button id="share-fab" onclick="openShareModal('Austin City Council','Latest Meeting','https://austincouncil.app')" title="Share austincouncil.app" aria-label="Share this site">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>
    </button>

    <!-- Share Modal -->
    <div id="share-modal-overlay" role="dialog" aria-modal="true" aria-label="Share" onclick="handleOverlayClick(event)">
        <div id="share-modal">
            <button class="share-modal-close" onclick="closeShareModal()" aria-label="Close">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
            <div class="share-modal-brand">
                <div class="share-modal-brand-icon">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
                </div>
                <div class="share-modal-brand-text">
                    Austin Council Monitor
                    <span>austincouncil.app</span>
                </div>
            </div>
            <div class="share-preview" id="share-preview">
                <div class="share-preview-date" id="share-preview-type"></div>
                <div class="share-preview-title" id="share-preview-title"></div>
                <div class="share-preview-source">&#127963;&#65039; austincouncil.app</div>
            </div>
            <div class="share-buttons" id="share-buttons-row">
                <button class="share-btn twitter" onclick="shareToTwitter()">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-4.714-6.231-5.401 6.231H2.747l7.73-8.835L1.254 2.25H8.08l4.253 5.622L18.244 2.25zM17.083 19.77h1.833L7.084 4.126H5.117z"/></svg>
                    Post on X
                </button>
                <button class="share-btn linkedin" onclick="shareToLinkedIn()">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M16 8a6 6 0 0 1 6 6v7h-4v-7a2 2 0 0 0-2-2 2 2 0 0 0-2 2v7h-4v-7a6 6 0 0 1 6-6z"/><rect x="2" y="9" width="4" height="12"/><circle cx="4" cy="4" r="2"/></svg>
                    LinkedIn
                </button>
                <button class="share-btn native" id="native-share-btn" onclick="nativeShare()" style="display:none">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/><polyline points="16 6 12 2 8 6"/><line x1="12" y1="2" x2="12" y2="15"/></svg>
                    More&#8230;
                </button>
            </div>
            <div class="share-copy-row">
                <input type="text" class="share-copy-input" id="share-copy-url" readonly>
                <button class="share-copy-btn" id="share-copy-btn" onclick="copyShareLink()">Copy link</button>
            </div>
        </div>
    </div>

    <script>
        let activeFilter = 'all';
        function filterMeetings(type) {{
            activeFilter = type;
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.toggle('active', b.dataset.filter === type));
            applyFilters();
        }}
        function applyFilters() {{
            const q = document.getElementById('search-input').value.toLowerCase().trim();
            let visible = 0;
            document.querySelectorAll('.meeting-card').forEach(card => {{
                const show = (activeFilter === 'all' || card.dataset.type === activeFilter) && (!q || card.textContent.toLowerCase().includes(q));
                card.classList.toggle('hidden', !show);
                if (show) visible++;
            }});
            document.getElementById('no-results').style.display = visible === 0 ? 'block' : 'none';
        }}
        window.addEventListener('scroll', () => {{
            document.getElementById('back-to-top').classList.toggle('visible', window.scrollY > 400);
        }});
        async function subscribe() {{
            const email = document.getElementById('sub-email').value.trim();
            const btn = document.getElementById('sub-btn');
            const msg = document.getElementById('sub-msg');
            if (!email || !email.includes('@')) {{
                msg.textContent = 'Please enter a valid email address.';
                msg.className = 'subscribe-msg error';
                return;
            }}
            btn.disabled = true;
            btn.textContent = 'Subscribing...';
            msg.textContent = '';
            msg.className = 'subscribe-msg';
            try {{
                const res = await fetch('{SUBSCRIBE_API_URL}', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{email}})
                }});
                const data = await res.json();
                if (res.ok && data.success) {{
                    msg.textContent = "✓ You're subscribed!";
                    msg.className = 'subscribe-msg success';
                    document.getElementById('sub-email').value = '';
                    btn.textContent = 'Subscribed!';
                }} else {{
                    throw new Error(data.error || 'Subscription failed');
                }}
            }} catch(e) {{
                msg.textContent = 'Something went wrong. Please try again.';
                msg.className = 'subscribe-msg error';
                btn.disabled = false;
                btn.textContent = 'Subscribe';
            }}
        }}
        document.getElementById('sub-email').addEventListener('keydown', e => {{
            if (e.key === 'Enter') subscribe();
        }});

        /* ── Share Feature ── */
        let _shareUrl = 'https://austincouncil.app';
        let _shareText = '';

        function openShareModal(date, type, url) {{
            _shareUrl = url || 'https://austincouncil.app';
            _shareText = `Austin City Council ${{type}} \u2014 ${{date}} | AI-powered summary via austincouncil.app`;
            document.getElementById('share-preview-type').textContent = type;
            document.getElementById('share-preview-title').textContent = `${{date}} Meeting`;
            document.getElementById('share-copy-url').value = _shareUrl;
            document.getElementById('share-copy-btn').textContent = 'Copy link';
            document.getElementById('share-copy-btn').className = 'share-copy-btn';
            document.getElementById('native-share-btn').style.display = navigator.share ? 'flex' : 'none';
            document.getElementById('share-modal-overlay').classList.add('open');
            document.body.style.overflow = 'hidden';
        }}
        function closeShareModal() {{
            document.getElementById('share-modal-overlay').classList.remove('open');
            document.body.style.overflow = '';
        }}
        function handleOverlayClick(e) {{
            if (e.target === document.getElementById('share-modal-overlay')) closeShareModal();
        }}
        document.addEventListener('keydown', e => {{ if (e.key === 'Escape') closeShareModal(); }});
        function shareToTwitter() {{
            const encoded = encodeURIComponent(_shareText + ' ' + _shareUrl);
            window.open(`https://x.com/intent/tweet?text=${{encoded}}`, '_blank', 'noopener');
        }}
        function shareToLinkedIn() {{
            const u = encodeURIComponent(_shareUrl);
            window.open(`https://www.linkedin.com/sharing/share-offsite/?url=${{u}}`, '_blank', 'noopener');
        }}
        async function nativeShare() {{
            try {{
                await navigator.share({{ title: 'Austin Council Monitor', text: _shareText, url: _shareUrl }});
            }} catch(e) {{ /* user cancelled */ }}
        }}
        function copyShareLink() {{
            navigator.clipboard.writeText(_shareUrl).then(() => {{
                const btn = document.getElementById('share-copy-btn');
                btn.textContent = '\u2713 Copied!';
                btn.className = 'share-copy-btn copied';
                setTimeout(() => {{ btn.textContent = 'Copy link'; btn.className = 'share-copy-btn'; }}, 2200);
            }}).catch(() => {{
                document.getElementById('share-copy-url').select();
                document.execCommand('copy');
            }});
        }}
    </script>
</body>
</html>'''

    def generate_rss_feed(self, meetings, site_url='https://austincouncil.app'):
        """Generate RSS 2.0 feed"""
        latest_date = datetime.now()
        if meetings:
            try:
                latest_date = datetime.strptime(meetings[0]['created_at'], '%Y-%m-%d %H:%M:%S')
            except Exception:
                pass

        rss = f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
    <channel>
        <title>Austin City Council Meeting Monitor</title>
        <link>{site_url}</link>
        <description>Automated AI-powered summaries of Austin City Council meetings</description>
        <language>en-us</language>
        <lastBuildDate>{latest_date.strftime('%a, %d %b %Y %H:%M:%S +0000')}</lastBuildDate>
        <atom:link href="{site_url}/feed.xml" rel="self" type="application/rss+xml"/>
        <generator>Austin Meeting Monitor v4.0</generator>
'''
        for meeting in meetings[:50]:
            di = self.format_date(meeting['date'])
            status = '✅ Completed' if meeting['is_completed'] else '📅 Upcoming'
            title = f"[{status}] Austin {meeting['meeting_type']}: {di['full']}"

            # Prefer post-meeting summary for completed meetings
            summary_text = (
                meeting.get('post_meeting_summary') or meeting.get('summary', 'Meeting summary will be available soon.')
            )
            description = f'<p>{summary_text}</p>'
            if meeting.get('video_url'):
                description += f'<p><a href="{meeting["video_url"]}">▶ Watch Video of this Meeting</a></p>'
            if meeting.get('actions_url'):
                description += f'<p><a href="{meeting["actions_url"]}">📋 Actions Taken By Council</a></p>'
            if meeting.get('transcript_url'):
                description += f'<p><a href="{meeting["transcript_url"]}">📄 Closed Caption Transcript (PDF)</a></p>'
            if meeting.get('agenda_url'):
                description += f'<p><a href="{meeting["agenda_url"]}">Download Meeting Agenda (PDF)</a></p>'
            description += f'<p><a href="{meeting["url"]}">View Full Meeting Details</a></p>'

            try:
                pub_date = datetime.strptime(meeting['created_at'], '%Y-%m-%d %H:%M:%S')
                pub_date_str = pub_date.strftime('%a, %d %b %Y %H:%M:%S +0000')
            except Exception:
                pub_date_str = datetime.now().strftime('%a, %d %b %Y %H:%M:%S +0000')

            rss += f'''
        <item>
            <title>{title}</title>
            <link>{meeting['url']}</link>
            <description><![CDATA[{description}]]></description>
            <pubDate>{pub_date_str}</pubDate>
            <guid isPermaLink="false">{site_url}/meeting-{meeting['id']}</guid>
        </item>
'''
        rss += '    </channel>\n</rss>'
        return rss

    def publish(self, site_url='https://austincouncil.app'):
        """Generate all files for GitHub Pages"""
        logging.info("📄 Generating GitHub Pages site...")
        meetings = self.get_all_meetings()

        if not meetings:
            logging.warning("  ⚠️  No meetings found in database - creating placeholder site")

        html_content = self.generate_html_index(meetings)
        html_path = self.output_dir / 'index.html'
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        logging.info(f"  ✅ Generated {html_path}")

        rss_content = self.generate_rss_feed(meetings, site_url)
        rss_path = self.output_dir / 'feed.xml'
        with open(rss_path, 'w', encoding='utf-8') as f:
            f.write(rss_content)
        logging.info(f"  ✅ Generated {rss_path}")

        nojekyll_path = self.output_dir / '.nojekyll'
        nojekyll_path.touch()

        logging.info("✅ GitHub Pages site generated successfully!")
        logging.info(f"  🌐 {site_url}")
        logging.info(f"  📡 {site_url}/feed.xml")
        return True


if __name__ == "__main__":
    logging.info("🚀 Starting GitHub Pages Publisher v4.0")
    publisher = GitHubPagesPublisher(db_path='austin_meetings.db', output_dir='docs')
    publisher.publish(site_url='https://austincouncil.app')
