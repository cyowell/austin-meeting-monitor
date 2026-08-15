import { getAllMeetings } from '../../utils/getMeetings.js';

export async function GET() {
  const meetings = getAllMeetings();
  
  // Format the data to match what the client-side search expects.
  // We keep only the fields necessary to reduce payload size.
  const data = meetings.map(m => {
    let year = m.year;
    let decade = m.decade;
    
    if (!year && m.date) {
      year = new Date(m.date).getUTCFullYear();
    }
    if (!decade && year) {
      decade = Math.floor(year / 10) * 10 + 's';
    }

    const summaryPattern = /^Here's.*?meeting.*?:\s*/is;
    const cleanSummary = m.summary
      ? m.summary.replace(summaryPattern, '').replace(/[#*]/g, '').substring(0, 150) + '...'
      : 'No summary available.';

    const formattedDate = new Date(m.date).toLocaleDateString('en-US', {
      timeZone: 'UTC',
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    });

    return {
      id: m.meeting_id,
      title: m.title,
      type: m.meeting_type,
      date: m.date,
      formattedDate,
      year: year || '',
      decade: decade || '',
      summary: cleanSummary,
      rawSummary: m.summary || '' // Used for building snippets during search
    };
  });

  return new Response(JSON.stringify(data), {
    headers: {
      'Content-Type': 'application/json'
    }
  });
}
