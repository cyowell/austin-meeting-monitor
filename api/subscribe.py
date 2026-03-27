from http.server import BaseHTTPRequestHandler
import json
import os

try:
    import resend
except ImportError:
    resend = None


class handler(BaseHTTPRequestHandler):

    def _cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', 'https://austincouncil.app')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length))
            email = body.get('email', '').strip().lower()

            if not email or '@' not in email or '.' not in email:
                self._respond(400, {'error': 'Invalid email address'})
                return

            api_key = os.environ.get('RESEND_API_KEY')
            if not api_key or resend is None:
                self._respond(500, {'error': 'Email service not configured'})
                return

            resend.api_key = api_key

            # Auto-discover the audience
            audiences = resend.Audiences.list()
            items = getattr(audiences, 'data', None) or []
            if not items:
                self._respond(500, {'error': 'No audience configured'})
                return
            audience_id = items[0].get('id') or items[0].id

            # Add contact (idempotent — Resend ignores duplicates)
            resend.Contacts.create({
                'audience_id': audience_id,
                'email': email,
                'unsubscribed': False
            })

            self._respond(200, {'success': True, 'message': 'You\'re subscribed!'})

        except Exception as e:
            self._respond(500, {'error': str(e)})

    def _respond(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # Suppress default request logging
