import fs from 'node:fs';
import path from 'node:path';

export function getAllMeetings() {
  const rootDir = path.resolve('../');
  const realTimeDir = path.join(rootDir, 'real-time');
  const historicalDir = path.join(rootDir, 'historical');

  const meetings = [];

  function scanDir(dir) {
    if (!fs.existsSync(dir)) return;
    const files = fs.readdirSync(dir);
    for (const file of files) {
      const fullPath = path.join(dir, file);
      const stat = fs.statSync(fullPath);
      if (stat.isDirectory()) {
        scanDir(fullPath);
      } else if (file.endsWith('.json')) {
        try {
          const data = JSON.parse(fs.readFileSync(fullPath, 'utf8'));
          if (data && data.meeting_id) {
            meetings.push({ ...data, _sourcePath: fullPath });
          }
        } catch (e) {
          console.error(`Error parsing ${fullPath}`, e);
        }
      }
    }
  }

  scanDir(realTimeDir);
  scanDir(historicalDir);

  // Sort by date descending
  return meetings.sort((a, b) => {
    if (!a.date || !b.date) return 0;
    return new Date(b.date).getTime() - new Date(a.date).getTime();
  });
}
