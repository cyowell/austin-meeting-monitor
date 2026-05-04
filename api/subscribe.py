"""
Vercel Serverless Function — Email Subscription via Resend
Handles POST /subscribe from austincouncil.app

Runtime: Python 3.12 (see vercel.json)
Dependencies: resend (see api/requirements.txt)
"""
from http.server import BaseHTTPRequestHandler
import json
import os

CORS_ORIGIN = 'https://austincouncil.app'

CORS_HEADERS = {
    'Access-Control-Allow-Origin': CORS_ORIGIN,
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Max-Age': '86400',
}


class handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass  # Suppress default access log noise

    def _send(self, status: int, body: dict):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        for k, v in CORS_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self):
        """Handle CORS preflight"""
        self.send_response(204)
        for k, v in CORS_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            raw = self.rfile.read(length) if length > 0 else b'{}'
            data = json.loads(raw)
        except Exception:
            data = {}

        email = str(data.get('email', '')).strip().lower()

        # Basic validation
        if not email or '@' not in email or '.' not in email.split('@')[-1]:
            return self._send(400, {'error': 'Invalid email address'})

        api_key = os.environ.get('RESEND_API_KEY')
        if not api_key:
            return self._send(500, {'error': 'Email service not configured'})

        try:
            import resend
        except ImportError:
            return self._send(500, {'error': 'resend package not installed'})

        resend.api_key = api_key

        # Build contact params
        params = {'email': email, 'unsubscribed': False}

        # Include audience_id if set (legacy Resend API compat)
        audience_id = os.environ.get('RESEND_AUDIENCE_ID')
        if audience_id:
            params['audience_id'] = audience_id

        try:
            resend.Contacts.create(params)
            return self._send(200, {'success': True, 'message': "You're subscribed!"})
        except Exception as exc:
            # Try lowercase fallback (some SDK versions)
            try:
                resend.contacts.create(params)
                return self._send(200, {'success': True, 'message': "You're subscribed!"})
            except Exception:
                return self._send(500, {'error': str(exc)})
