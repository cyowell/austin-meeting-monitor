"""
Minimal test handler - no external dependencies
"""
from http.server import BaseHTTPRequestHandler
import json


class handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        self._send(200, {'status': 'ok', 'message': 'Python serverless is working'})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', 'https://austincouncil.app')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            raw = self.rfile.read(length) if length > 0 else b'{}'
            data = json.loads(raw)
        except Exception:
            data = {}

        email = str(data.get('email', '')).strip().lower()
        if not email or '@' not in email:
            return self._send(400, {'error': 'Invalid email'})

        import os
        api_key = os.environ.get('RESEND_API_KEY', '')
        return self._send(200, {
            'success': True,
            'email': email,
            'has_api_key': bool(api_key),
            'api_key_length': len(api_key),
        })

    def _send(self, status, body):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Access-Control-Allow-Origin', 'https://austincouncil.app')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(payload)
