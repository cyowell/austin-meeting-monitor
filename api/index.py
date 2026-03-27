from flask import Flask, request, jsonify
import os

try:
    import resend
except ImportError:
    resend = None

app = Flask(__name__)

CORS_ORIGIN = 'https://austincouncil.app'


def cors(response):
    response.headers['Access-Control-Allow-Origin'] = CORS_ORIGIN
    response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response


@app.route('/subscribe', methods=['OPTIONS'])
def subscribe_preflight():
    return cors(jsonify({}))


@app.route('/subscribe', methods=['POST'])
def subscribe():
    data = request.get_json(silent=True) or {}
    email = data.get('email', '').strip().lower()

    if not email or '@' not in email or '.' not in email.split('@')[-1]:
        return cors(jsonify({'error': 'Invalid email address'})), 400

    api_key = os.environ.get('RESEND_API_KEY')
    if not api_key or resend is None:
        return cors(jsonify({'error': 'Email service not configured'})), 500

    resend.api_key = api_key

    try:
        audiences = resend.Audiences.list()
        items = getattr(audiences, 'data', None) or []
        if not items:
            return cors(jsonify({'error': 'No audience configured'})), 500
        audience_id = items[0].get('id') or items[0].id

        resend.Contacts.create({
            'audience_id': audience_id,
            'email': email,
            'unsubscribed': False
        })

        return cors(jsonify({'success': True, 'message': "You're subscribed!"}))

    except Exception as e:
        return cors(jsonify({'error': str(e)})), 500
