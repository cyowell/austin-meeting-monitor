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

        import urllib.request
        import urllib.error

        # Build contact params
        params = {'email': email, 'unsubscribed': False}

        headers = {
            'Authorization': f'Bearer {api_key}', 
            'Content-Type': 'application/json',
            'User-Agent': 'resend-python/2.1.0'
        }

        # Resolve audience ID: use environment variable first, otherwise query live audiences
        audience_id = os.environ.get('RESEND_AUDIENCE_ID')
        if not audience_id:
            try:
                req = urllib.request.Request(
                    'https://api.resend.com/audiences',
                    headers=headers
                )
                with urllib.request.urlopen(req) as response:
                    res_body = json.loads(response.read().decode('utf-8'))
                    items = res_body.get('data', [])
                    if items:
                        # Look for audience named 'General' (case-insensitive)
                        general_audience = None
                        for item in items:
                            if str(item.get('name', '')).strip().lower() == 'general':
                                general_audience = item
                                break
                        
                        if general_audience:
                            audience_id = general_audience.get('id')
                        else:
                            # Fallback to first available audience
                            audience_id = items[0].get('id')
            except Exception:
                pass

        if audience_id:
            params['audience_id'] = audience_id

        def _fail(err_msg):
            slack_url = os.environ.get('SLACK_WEBHOOK_URL')
            if slack_url:
                try:
                    payload = {
                        "text": f"🚨 *Email Subscription Error*\n*Email:* `{email}`\n*Error:* ```{err_msg}```"
                    }
                    slack_req = urllib.request.Request(
                        slack_url,
                        data=json.dumps(payload).encode('utf-8'),
                        headers={'Content-Type': 'application/json'},
                        method='POST'
                    )
                    with urllib.request.urlopen(slack_req, timeout=5):
                        pass
                except Exception:
                    pass
            return self._send(500, {'error': err_msg})

        try:
            req = urllib.request.Request(
                'https://api.resend.com/contacts',
                data=json.dumps(params).encode('utf-8'),
                headers=headers,
                method='POST'
            )
            with urllib.request.urlopen(req) as response:
                pass  # success
            return self._send(200, {'success': True, 'message': "You're subscribed!"})
        except urllib.error.HTTPError as exc:
            # If the new /contacts endpoint fails with 404 (legacy account), fallback to /audiences/{id}/contacts
            if exc.code == 404 and audience_id:
                try:
                    fallback_url = f'https://api.resend.com/audiences/{audience_id}/contacts'
                    req = urllib.request.Request(
                        fallback_url,
                        data=json.dumps(params).encode('utf-8'),
                        headers=headers,
                        method='POST'
                    )
                    with urllib.request.urlopen(req) as response:
                        pass
                    return self._send(200, {'success': True, 'message': "You're subscribed!"})
                except urllib.error.HTTPError as exc2:
                    return _fail(f'Subscription failed: {exc2.read().decode("utf-8")}')
            else:
                return _fail(f'Subscription failed: {exc.read().decode("utf-8")}')
        except Exception as exc:
            return _fail(str(exc))
