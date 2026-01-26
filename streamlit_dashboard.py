import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
import os

# Page configuration
st.set_page_config(
    page_title="Austin City Council Meeting Monitor",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
    <style>
    .main-header {
        font-size: 2.5rem;
        color: #1E3A8A;
        text-align: center;
        margin-bottom: 1rem;
    }
    .meeting-card {
        background-color: #F3F4F6;
        padding: 1.5rem;
        border-radius: 0.5rem;
        margin-bottom: 1rem;
        border-left: 4px solid #3B82F6;
    }
    .meeting-date {
        font-size: 1.2rem;
        font-weight: bold;
        color: #1E3A8A;
    }
    .meeting-type {
        color: #6B7280;
        font-size: 0.9rem;
    }
    .summary-text {
        margin-top: 1rem;
        line-height: 1.6;
    }
    .stButton>button {
        background-color: #3B82F6;
        color: white;
    }
    </style>
""", unsafe_allow_html=True)


class MeetingDashboard:
    def __init__(self, db_path='austin_meetings.db'):
        self.db_path = db_path
        
    def get_connection(self):
        """Create database connection"""
        if not os.path.exists(self.db_path):
            st.error(f"Database not found: {self.db_path}")
            return None
        return sqlite3.connect(self.db_path)
    
    def get_meetings(self, limit=None, search_term=None):
        """Retrieve meetings from database with optional filtering"""
        conn = self.get_connection()
        if not conn:
            return []
        
        query = '''
            SELECT id, date, meeting_type, url, agenda_url, summary, discovered_at
            FROM meetings
            WHERE 1=1
        '''
        params = []
        
        if search_term:
            query += ' AND (meeting_type LIKE ? OR summary LIKE ?)'
            params.extend([f'%{search_term}%', f'%{search_term}%'])
        
        query += ' ORDER BY date DESC'
        
        if limit:
            query += f' LIMIT {limit}'
        
        cursor = conn.cursor()
        cursor.execute(query, params)
        
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
    
    def get_stats(self):
        """Get database statistics"""
        conn = self.get_connection()
        if not conn:
            return {}
        
        cursor = conn.cursor()
        
        # Total meetings
        cursor.execute('SELECT COUNT(*) FROM meetings')
        total_meetings = cursor.fetchone()[0]
        
        # Meetings with agendas
        cursor.execute('SELECT COUNT(*) FROM meetings WHERE agenda_url IS NOT NULL')
        with_agendas = cursor.fetchone()[0]
        
        # Most recent meeting date
        cursor.execute('SELECT MAX(date) FROM meetings')
        latest_date = cursor.fetchone()[0]
        
        # Meeting types breakdown
        cursor.execute('SELECT meeting_type, COUNT(*) FROM meetings GROUP BY meeting_type')
        meeting_types = dict(cursor.fetchall())
        
        conn.close()
        
        return {
            'total_meetings': total_meetings,
            'with_agendas': with_agendas,
            'latest_date': latest_date,
            'meeting_types': meeting_types
        }


def main():
    # Header
    st.markdown('<h1 class="main-header">🏛️ Austin City Council Meeting Monitor</h1>', unsafe_allow_html=True)
    st.markdown("---")
    
    # Initialize dashboard
    dashboard = MeetingDashboard()
    
    # Sidebar
    with st.sidebar:
        st.header("📊 Dashboard Controls")
        
        # Search functionality
        search_term = st.text_input("🔍 Search meetings", placeholder="e.g., housing, budget, zoning")
        
        # Filter by number of meetings
        show_limit = st.slider("Number of meetings to display", 5, 50, 10)
        
        # Refresh button
        if st.button("🔄 Refresh Data"):
            st.rerun()
        
        st.markdown("---")
        
        # Statistics
        st.subheader("📈 Statistics")
        stats = dashboard.get_stats()
        
        if stats:
            st.metric("Total Meetings", stats['total_meetings'])
            st.metric("With Agendas", stats['with_agendas'])
            if stats['latest_date']:
                st.metric("Latest Meeting", stats['latest_date'])
            
            # Meeting types breakdown
            if stats['meeting_types']:
                st.markdown("**Meeting Types:**")
                for meeting_type, count in sorted(stats['meeting_types'].items(), key=lambda x: x[1], reverse=True):
                    st.text(f"• {meeting_type}: {count}")
        
        st.markdown("---")
        
        # Email signup placeholder
        st.subheader("📧 Get Notifications")
        st.info("Email notifications coming soon! Check back later to subscribe.")
        
        # About section
        st.markdown("---")
        st.markdown("""
        **About This Tool**
        
        This dashboard monitors the Austin City Council Meeting Info Center and provides AI-powered summaries of meeting agendas.
        
        Data is updated twice daily.
        """)
    
    # Main content area
    col1, col2 = st.columns([3, 1])
    
    with col1:
        st.header("📅 Upcoming & Recent Meetings")
    
    with col2:
        # View toggle
        view_mode = st.selectbox("View", ["Card View", "Table View"])
    
    # Get meetings
    meetings = dashboard.get_meetings(limit=show_limit, search_term=search_term if search_term else None)
    
    if not meetings:
        st.warning("No meetings found. Make sure the monitoring script has run at least once.")
        st.info("Run `python3 austin_meeting_monitor_gemini.py` to populate the database.")
    else:
        if search_term:
            st.success(f"Found {len(meetings)} meeting(s) matching '{search_term}'")
        
        if view_mode == "Card View":
            # Card view - more visual
            for meeting in meetings:
                with st.container():
                    st.markdown(f"""
                    <div class="meeting-card">
                        <div class="meeting-date">📅 {meeting['date']}</div>
                        <div class="meeting-type">{meeting['meeting_type']}</div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    col1, col2, col3 = st.columns([2, 2, 1])
                    
                    with col1:
                        st.markdown(f"[🔗 Meeting Page]({meeting['url']})")
                    
                    with col2:
                        if meeting['agenda_url']:
                            st.markdown(f"[📄 View Agenda PDF]({meeting['agenda_url']})")
                        else:
                            st.text("Agenda not yet available")
                    
                    with col3:
                        with st.expander("ℹ️ Details"):
                            st.text(f"ID: {meeting['id']}")
                            st.text(f"Added: {meeting['discovered_at'][:10]}")
                    
                    # Summary
                    st.markdown("**Summary:**")
                    st.markdown(f'<div class="summary-text">{meeting["summary"]}</div>', unsafe_allow_html=True)
                    
                    st.markdown("---")
        
        else:
            # Table view - more compact
            df = pd.DataFrame(meetings)
            df['date'] = pd.to_datetime(df['date'])
            
            # Create clickable links
            df['Meeting Link'] = df['url'].apply(lambda x: f'[Link]({x})')
            df['Agenda'] = df['agenda_url'].apply(lambda x: f'[PDF]({x})' if x else 'N/A')
            
            # Display table
            st.dataframe(
                df[['date', 'meeting_type', 'Meeting Link', 'Agenda']],
                use_container_width=True,
                hide_index=True
            )
            
            # Show summaries below
            st.subheader("📝 Meeting Summaries")
            for meeting in meetings:
                with st.expander(f"{meeting['date']} - {meeting['meeting_type']}"):
                    st.markdown(meeting['summary'])
                    st.markdown(f"[View Meeting Page]({meeting['url']})")
                    if meeting['agenda_url']:
                        st.markdown(f"[Download Agenda PDF]({meeting['agenda_url']})")
    
    # Footer
    st.markdown("---")
    st.markdown("""
    <div style='text-align: center; color: #6B7280; font-size: 0.9rem;'>
        <p>Data sourced from <a href='https://www.austintexas.gov/department/city-council/council/council_meeting_info_center.htm' target='_blank'>Austin City Council Meeting Info Center</a></p>
        <p>Summaries generated using Google Gemini AI | Last updated: Check sidebar for latest meeting date</p>
    </div>
    """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
