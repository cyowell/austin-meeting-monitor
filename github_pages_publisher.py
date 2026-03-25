"""
GitHub Pages Publisher for Austin City Council Meeting Monitor
Generates static HTML pages and RSS feed for automated publishing
Version: 2.2 - Fixed column name mapping (meeting_url instead of url)
"""

import os
import sqlite3
import logging
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class GitHubPagesPublisher:
    """
    Generates static HTML pages and RSS feed for GitHub Pages hosting
    """
    
    def __init__(self, db_path='austin_meetings.db', output_dir='docs'):
        """
        Initialize GitHub Pages publisher
        
        Args:
            db_path: Path to SQLite database
            output_dir: Output directory for generated files (GitHub Pages uses 'docs' folder)
        """
        self.db_path = db_path
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        logging.info(f"✓ GitHub Pages publisher initialized (v2.2)")
        logging.info(f"  Output directory: {self.output_dir}")
    
    def get_all_meetings(self, limit=None):
        """Get all meetings from database, sorted by date (newest first)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Check what columns exist in the table
        cursor.execute("PRAGMA table_info(meetings)")
        columns = {col[1] for col in cursor.fetchall()}
        logging.info(f"🔍 Database schema check:")
        logging.info(f"  Available columns: {sorted(columns)}")
        
        # Map expected columns to actual columns
        column_mapping = {
            'id': 'meeting_id' if 'meeting_id' in columns else 'id',
            'date': 'date',
            'meeting_type': 'meeting_type',
            'url': 'meeting_url' if 'meeting_url' in columns else 'url',
            'agenda_url': 'agenda_url',
            'summary': 'gemini_summary' if 'gemini_summary' in columns else 'summary',
            'created_at': 'created_at'
        }
        
        # Verify required columns exist
        required = ['date', 'meeting_type']
        for req in required:
            actual_col = column_mapping.get(req, req)
            if actual_col not in columns:
                logging.error(f"  ❌ Missing required column: {req} (looking for {actual_col})")
                raise ValueError(f"Database missing required column: {req}")
        
        logging.info(f"  ✅ All required columns found")
        
        # Build query with actual column names
        select_cols = [
            column_mapping['id'],
            column_mapping['date'],
            column_mapping['meeting_type'],
            column_mapping['url'],
            column_mapping['agenda_url'],
            column_mapping['summary']
        ]
        
        # Add created_at if it exists
        if column_mapping['created_at'] in columns:
            select_cols.append(column_mapping['created_at'])
        
        query = f'''
            SELECT {', '.join(select_cols)}
            FROM meetings
            ORDER BY {column_mapping['date']} DESC
        '''
        
        if limit:
            query += f' LIMIT {limit}'
        
        cursor.execute(query)
        meetings = []
        
        for row in cursor.fetchall():
            meeting = {
                'id': row[0],
                'date': row[1],
                'meeting_type': row[2],
                'url': row[3],
                'agenda_url': row[4] if row[4] else None,
                'summary': row[5] if row[5] else 'Meeting summary will be available soon.',
                'created_at': row[6] if len(row) > 6 else datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            meetings.append(meeting)
        
        conn.close()
        logging.info(f"  📊 Found {len(meetings)} meetings in database")
        return meetings
    
    def format_date(self, date_str):
        """Format date string nicely"""
        try:
            date_obj = datetime.strptime(date_str, '%Y-%m-%d')
            return {
                'full': date_obj.strftime('%B %d, %Y'),  # March 25, 2026
                'short': date_obj.strftime('%b %d, %Y'),  # Mar 25, 2026
                'day': date_obj.strftime('%A'),  # Tuesday
                'iso': date_str  # 2026-03-25
            }
        except:
            return {
                'full': date_str,
                'short': date_str,
                'day': '',
                'iso': date_str
            }
    
    def generate_html_index(self, meetings):
        """Generate main index.html page"""
        
        html = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="description" content="Automated summaries of Austin City Council meetings with AI-generated highlights">
    <title>Austin City Council Meeting Monitor</title>
    <link rel="alternate" type="application/rss+xml" title="Austin City Council Meetings" href="feed.xml">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            line-height: 1.6;
            color: #333;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 900px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
        }
        
        header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 40px 30px;
            text-align: center;
        }
        
        header h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.2);
        }
        
        header p {
            font-size: 1.1em;
            opacity: 0.95;
        }
        
        .subscribe-box {
            background: rgba(255,255,255,0.15);
            padding: 20px;
            margin-top: 20px;
            border-radius: 8px;
            backdrop-filter: blur(10px);
        }
        
        .subscribe-box h3 {
            margin-bottom: 10px;
            font-size: 1.3em;
        }
        
        .subscribe-buttons {
            display: flex;
            gap: 10px;
            justify-content: center;
            flex-wrap: wrap;
            margin-top: 15px;
        }
        
        .btn {
            display: inline-block;
            padding: 12px 24px;
            background: white;
            color: #667eea;
            text-decoration: none;
            border-radius: 6px;
            font-weight: 600;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.2);
        }
        
        .btn-rss {
            background: #ff6600;
            color: white;
        }
        
        main {
            padding: 40px 30px;
        }
        
        .stats {
            display: flex;
            justify-content: space-around;
            margin-bottom: 40px;
            padding: 20px;
            background: #f8f9fa;
            border-radius: 8px;
        }
        
        .stat {
            text-align: center;
        }
        
        .stat-number {
            font-size: 2.5em;
            font-weight: bold;
            color: #667eea;
        }
        
        .stat-label {
            color: #666;
            font-size: 0.9em;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        
        .meeting-card {
            background: white;
            border: 2px solid #e9ecef;
            border-radius: 12px;
            padding: 30px;
            margin-bottom: 30px;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        
        .meeting-card:hover {
            transform: translateY(-4px);
            box-shadow: 0 8px 24px rgba(0,0,0,0.1);
            border-color: #667eea;
        }
        
        .meeting-header {
            display: flex;
            justify-content: space-between;
            align-items: start;
            margin-bottom: 20px;
            flex-wrap: wrap;
            gap: 15px;
        }
        
        .meeting-date {
            font-size: 1.8em;
            font-weight: bold;
            color: #667eea;
        }
        
        .meeting-day {
            color: #666;
            font-size: 0.9em;
            margin-top: 5px;
        }
        
        .meeting-type {
            background: #667eea;
            color: white;
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 0.9em;
            font-weight: 600;
        }
        
        .meeting-summary {
            margin: 20px 0;
            line-height: 1.8;
        }
        
        .meeting-summary h3 {
            color: #333;
            margin-bottom: 15px;
            font-size: 1.2em;
        }
        
        .meeting-summary p {
            color: #555;
            white-space: pre-wrap;
        }
        
        .meeting-links {
            display: flex;
            gap: 15px;
            margin-top: 20px;
            flex-wrap: wrap;
        }
        
        .meeting-link {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 10px 20px;
            background: #f8f9fa;
            color: #667eea;
            text-decoration: none;
            border-radius: 6px;
            font-weight: 600;
            transition: background 0.2s;
        }
        
        .meeting-link:hover {
            background: #e9ecef;
        }
        
        footer {
            background: #f8f9fa;
            padding: 30px;
            text-align: center;
            color: #666;
            border-top: 2px solid #e9ecef;
        }
        
        footer p {
            margin: 10px 0;
        }
        
        footer a {
            color: #667eea;
            text-decoration: none;
        }
        
        footer a:hover {
            text-decoration: underline;
        }
        
        .no-meetings {
            text-align: center;
            padding: 60px 20px;
            color: #666;
        }
        
        .no-meetings h2 {
            font-size: 2em;
            margin-bottom: 15px;
        }
        
        @media (max-width: 768px) {
            header h1 {
                font-size: 1.8em;
            }
            
            .stats {
                flex-direction: column;
                gap: 20px;
            }
            
            .meeting-header {
                flex-direction: column;
            }
            
            .meeting-date {
                font-size: 1.4em;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🏛️ Austin City Council Meeting Monitor</h1>
            <p>Automated AI-powered summaries of Austin City Council meetings</p>
            
            <div class="subscribe-box">
                <h3>📬 Never Miss a Meeting</h3>
                <p>Subscribe to get automatic notifications when new meetings are posted</p>
                <div class="subscribe-buttons">
                    <a href="feed.xml" class="btn btn-rss">📡 RSS Feed</a>
                    <a href="https://blogtrottr.com/" class="btn" target="_blank">📧 Email Updates</a>
                </div>
            </div>
        </header>
        
        <main>
            <div class="stats">
                <div class="stat">
                    <div class="stat-number">''' + str(len(meetings)) + '''</div>
                    <div class="stat-label">Total Meetings</div>
                </div>
                <div class="stat">
                    <div class="stat-number">''' + (self.format_date(meetings[0]['date'])['short'] if meetings else 'N/A') + '''</div>
                    <div class="stat-label">Latest Meeting</div>
                </div>
                <div class="stat">
                    <div class="stat-number">🤖</div>
                    <div class="stat-label">AI Powered</div>
                </div>
            </div>
'''
        
        if not meetings:
            html += '''
            <div class="no-meetings">
                <h2>No meetings found yet</h2>
                <p>Check back soon for automated meeting summaries!</p>
            </div>
'''
        else:
            for meeting in meetings:
                date_info = self.format_date(meeting['date'])
                summary = meeting.get('summary', 'Meeting summary will be available soon.')
                
                html += f'''
            <div class="meeting-card">
                <div class="meeting-header">
                    <div>
                        <div class="meeting-date">{date_info['full']}</div>
                        <div class="meeting-day">{date_info['day']}</div>
                    </div>
                    <div class="meeting-type">{meeting['meeting_type']}</div>
                </div>
                
                <div class="meeting-summary">
                    <h3>Meeting Highlights</h3>
                    <p>{summary}</p>
                </div>
                
                <div class="meeting-links">
                    <a href="{meeting['url']}" class="meeting-link" target="_blank" rel="noopener">
                        📄 Full Meeting Details
                    </a>
'''
                
                if meeting.get('agenda_url'):
                    html += f'''                    <a href="{meeting['agenda_url']}" class="meeting-link" target="_blank" rel="noopener">
                        📋 Download Agenda
                    </a>
'''
                
                html += '''                </div>
            </div>
'''
        
        html += '''        </main>
        
        <footer>
            <p><strong>About This Site</strong></p>
            <p>This site automatically monitors Austin City Council meetings and generates AI-powered summaries to help citizens stay informed.</p>
            <p>Summaries are generated using Google Gemini AI. For official information, always refer to the <a href="https://www.austintexas.gov/department/city-council" target="_blank">City of Austin website</a>.</p>
            <p style="margin-top: 20px; font-size: 0.9em;">
                Last updated: ''' + datetime.now().strftime('%B %d, %Y at %I:%M %p') + ''' | 
                <a href="https://github.com/cyowell/austin-meeting-monitor">View on GitHub</a>
            </p>
        </footer>
    </div>
</body>
</html>'''
        
        return html
    
    def generate_rss_feed(self, meetings, site_url='https://cyowell.github.io/austin-meeting-monitor'):
        """Generate RSS 2.0 feed"""
        
        latest_date = datetime.now()
        if meetings:
            try:
                latest_date = datetime.strptime(meetings[0]['created_at'], '%Y-%m-%d %H:%M:%S')
            except:
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
        <generator>Austin Meeting Monitor v2.2</generator>
'''
        
        for meeting in meetings[:50]:
            date_info = self.format_date(meeting['date'])
            title = f"Austin {meeting['meeting_type']}: {date_info['full']}"
            
            description = f"<p>{meeting.get('summary', 'Meeting summary will be available soon.')}</p>"
            
            if meeting.get('agenda_url'):
                description += f'<p><a href="{meeting["agenda_url"]}">Download Meeting Agenda (PDF)</a></p>'
            
            description += f'<p><a href="{meeting["url"]}">View Full Meeting Details</a></p>'
            
            try:
                pub_date = datetime.strptime(meeting['created_at'], '%Y-%m-%d %H:%M:%S')
                pub_date_str = pub_date.strftime('%a, %d %b %Y %H:%M:%S +0000')
            except:
                pub_date_str = datetime.now().strftime('%a, %d %b %Y %H:%M:%S +0000')
            
            guid = f"{site_url}/meeting-{meeting['id']}"
            
            rss += f'''
        <item>
            <title>{title}</title>
            <link>{meeting['url']}</link>
            <description><![CDATA[{description}]]></description>
            <pubDate>{pub_date_str}</pubDate>
            <guid isPermaLink="false">{guid}</guid>
        </item>
'''
        
        rss += '''    </channel>
</rss>'''
        
        return rss
    
    def publish(self, site_url='https://cyowell.github.io/austin-meeting-monitor'):
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
        logging.info(f"  ✅ Created {nojekyll_path}")
        
        logging.info("✅ GitHub Pages site generated successfully!")
        logging.info(f"\n  🌐 Site will be available at: {site_url}")
        logging.info(f"  📡 RSS feed: {site_url}/feed.xml")
        
        return True


if __name__ == "__main__":
    logging.info("🚀 Starting GitHub Pages Publisher v2.2")
    
    publisher = GitHubPagesPublisher(
        db_path='austin_meetings.db',
        output_dir='docs'
    )
    
    publisher.publish(site_url='https://cyowell.github.io/austin-meeting-monitor')
