"""
Vercel Serverless Function — Email Subscription via Resend
Handles POST /api/subscribe from austincouncil.app
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
        # Suppress default stderr logging
        pass

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
        length = int(self.headers.get('Content-Length', 0))
        raw = self.rfile.read(length) if length > 0 else b'{}'
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {}

        email = str(data.get('email', '')).strip().lower()

        # Basic email validation
        if not email or '@' not in email or '.' not in email.split('@')[-1]:
            return self._send(400, {'error': 'Invalid email address'})

        api_key = os.environ.get('RESEND_API_KEY')
        if not api_key:
            return self._send(500, {'error': 'Email service not configured (missing API key)'})

        try:
            import resend  # noqa: PLC0415
        except ImportError:
            return self._send(500, {'error': 'Email service not available'})

        resend.api_key = api_key

        try:
            # Get the first available audience
            audience_id = os.environ.get('RESEND_AUDIENCE_ID')
            if not audience_id:
                audiences = resend.Audiences.list()
                items = getattr(audiences, 'data', None) or []
                if not items:
                    return self._send(500, {'error': 'No audience configured in Resend'})
                first = items[0]
                # Support both dict and object styles
                audience_id = first.get('id') if isinstance(first, dict) else getattr(first, 'id', None)
                if not audience_id:
                    return self._send(500, {'error': 'Could not read audience ID from Resend'})

            resend.Contacts.create({
                'audience_id': audience_id,
                'email': email,
                'unsubscribed': False,
            })

            return self._send(200, {'success': True, 'message': "You're subscribed!"})

        except Exception as exc:
            return self._send(500, {'error': str(exc)})
