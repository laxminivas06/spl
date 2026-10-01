import os
import json
import base64
import urllib.parse
import secrets
import requests

try:
    from authlib.integrations.flask_client import OAuth
    oauth = OAuth()
except ImportError:
    oauth = None

def init_oauth(app):
    """Register Google OAuth client with Flask app if Authlib is available."""
    if oauth is None:
        return
    try:
        oauth.init_app(app)
        oauth.register(
            name='google',
            client_id=app.config.get('GOOGLE_CLIENT_ID'),
            client_secret=app.config.get('GOOGLE_CLIENT_SECRET'),
            authorize_url='https://accounts.google.com/o/oauth2/v2/auth',
            access_token_url='https://oauth2.googleapis.com/token',
            userinfo_endpoint='https://openidconnect.googleapis.com/v1/userinfo',
            jwks_uri='https://www.googleapis.com/oauth2/v3/certs',
            client_kwargs={
                'scope': 'openid email profile'
            }
        )
    except Exception as e:
        # Prevent app startup failure if Authlib encounters registration issue
        print(f"[WARN] Authlib Google OAuth registration warning: {e}")


def build_google_auth_url(client_id, redirect_uri, state, nonce=None):
    """
    Generate Google OAuth 2.0 Authorization URL directly.
    Requires ZERO network calls or external OAuth libraries.
    Guarantees no Connection Error during initiation.
    """
    params = {
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': state,
        'prompt': 'select_account',
        'access_type': 'online'
    }
    if nonce:
        params['nonce'] = nonce
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"


def decode_id_token_payload(id_token):
    """Decode Google id_token JWT payload without requiring third-party JWT libraries."""
    try:
        parts = id_token.split('.')
        if len(parts) >= 2:
            payload_b64 = parts[1]
            padded = payload_b64 + '=' * (-len(payload_b64) % 4)
            return json.loads(base64.urlsafe_b64decode(padded.encode('utf-8')).decode('utf-8'))
    except Exception:
        pass
    return {}


def exchange_google_code(code, redirect_uri, client_id, client_secret):
    """
    Exchange Google authorization code for tokens and extract verified userinfo.
    Uses standard requests with automatic PythonAnywhere proxy configuration.
    """
    token_url = 'https://oauth2.googleapis.com/token'
    payload = {
        'code': code,
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': redirect_uri,
        'grant_type': 'authorization_code'
    }

    # PythonAnywhere proxy routing for outbound API requests
    proxies = None
    if os.path.exists('/var/www') or 'pythonanywhere' in os.environ.get('PYTHONANYWHERE_DOMAIN', ''):
        proxies = {
            'http': 'http://proxy.server:3128',
            'https': 'http://proxy.server:3128'
        }

    resp = requests.post(token_url, data=payload, proxies=proxies, timeout=15)
    if resp.status_code != 200:
        err_detail = resp.text
        try:
            err_json = resp.json()
            err_detail = err_json.get('error_description') or err_json.get('error') or resp.text
        except Exception:
            pass
        raise RuntimeError(f"Google token exchange failed ({resp.status_code}): {err_detail}")

    token_data = resp.json()
    id_token = token_data.get('id_token')
    access_token = token_data.get('access_token')

    userinfo = {}
    if id_token:
        userinfo = decode_id_token_payload(id_token)

    # Supplement or verify from userinfo endpoint if needed
    if (not userinfo.get('email') or not userinfo.get('name')) and access_token:
        try:
            u_resp = requests.get(
                'https://openidconnect.googleapis.com/v1/userinfo',
                headers={'Authorization': f'Bearer {access_token}'},
                proxies=proxies,
                timeout=15
            )
            if u_resp.status_code == 200:
                userinfo.update(u_resp.json())
        except Exception:
            pass

    return userinfo


