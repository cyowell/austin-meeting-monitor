"""
Vercel Serverless Function — Email Subscription via Resend
Handles POST /subscribe from austincouncil.app
Uses the current Resend Contacts API (no audience_id required, Nov 2025+)
"""
from http.server import BaseHTTPRequestHandler
import json
import os

CORS_ORIGIN = 'https://austincouncil.app'


def _cors_headers():
    return {
        'Access-Control-Allow-Origin': CORS_ORIGIN,
        'Access-Control-Allow-Methods': 'POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
        'Access-Control-Max-Age': '86400',
    }


class handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass  # Suppress default stderr logging

    def _send(self, status: int, body: dict):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        for k, v in _cors_headers().items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self):
        """Handle CORS preflight"""
        self.send_response(204)
        for k, v in _cors_headers().items():
            self.send_header(k, v)
        self.end_headers()

    def do_POST(self):
        # Parse body
        try:
            length = int(self.headers.get('Content-Length', 0))
            raw = self.rfile.read(length) if length > 0 else b'{}'
            data = json.loads(raw)
        except Exception:
            data = {}

        email = str(data.get('email', '')).strip().lower()

        # Basic email validation
        if not email or '@' not in email or '.' not in email.split('@')[-1]:
            return self._send(400, {'error': 'Invalid email address'})

        api_key = os.environ.get('RESEND_API_KEY')
        if not api_key:
            return self._send(500, {'error': 'Email service not configured'})

        try:
            import resend  # installed via api/requirements.txt
        except ImportError:
            return self._send(500, {'error': 'resend package not available'})

        resend.api_key = api_key

        try:
            # Try the new Contacts API first (Resend SDK v2+, Nov 2025+)
            # No audience_id needed in the new API
            contact_params = {
                'email': email,
                'unsubscribed': False,
            }

            # If RESEND_AUDIENCE_ID is set, include it (works in both old and new SDK)
            audience_id = os.environ.get('RESEND_AUDIENCE_ID')
            if audience_id:
                contact_params['audience_id'] = audience_id

            resend.Contacts.create(contact_params)
            return self._send(200, {'success': True, 'message': "You're subscribed!"})

        except AttributeError:
            # Fallback: try lowercase contacts (some SDK versions)
            try:
                resend.contacts.create({'email': email, 'unsubscribed': False})
                return self._send(200, {'success': True, 'message': "You're subscribed!"})
            except Exception as exc2:
                return self._send(500, {'error': f'Subscription failed: {exc2}'})

        except Exception as exc:
            return self._send(500, {'error': str(exc)})
