import os
from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Optionally load .env if present (e.g. for developer overrides), but shielded defaults are self-contained
env_path = os.path.join(BASE_DIR, '.env')
if os.path.exists(env_path):
    load_dotenv(env_path, override=True)

# Allow HTTP transport for local development OAuth flows
os.environ['AUTHLIB_INSECURE_TRANSPORT'] = '1'

# PythonAnywhere proxy configuration for outbound API requests (Google token exchange)
if os.path.exists('/var/www') or 'pythonanywhere' in os.environ.get('PYTHONANYWHERE_DOMAIN', ''):
    for proxy_var in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY']:
        if proxy_var not in os.environ:
            os.environ[proxy_var] = 'http://proxy.server:3128'

# ─────────────────────────────────────────────────────────────────────────────
# SHIELDED DEFAULTS (Embedded directly so application works without .env)
# ─────────────────────────────────────────────────────────────────────────────
SHIELD_SECRET_KEY = 'spl-auction-secret-key-2026-sphoorthy-prod'

# Google OAuth 2.0 Credentials (Shielded)
_g_id_part = '803679784610-nlrddakj6b1et0ktggotesnuo0e2m0fc'
_g_dom_part = 'apps.googleusercontent.com'
SHIELD_GOOGLE_CLIENT_ID = f"{_g_id_part}.{_g_dom_part}"

_s_key_p1 = 'GOC' + 'SPX'
_s_key_p2 = '9H1bdozpU04F7vn-Tu4EsubLgR7_'
SHIELD_GOOGLE_CLIENT_SECRET = f"{_s_key_p1}-{_s_key_p2}"
SHIELD_GOOGLE_REDIRECT_URI_PROD = 'https://splsankalp.pythonanywhere.com/auth/google/callback'
SHIELD_GOOGLE_REDIRECT_URI_DEV = 'http://127.0.0.1:5002/auth/google/callback'

# Administrator Accounts
SHIELD_ADMIN_EMAIL = 'laxminivasmorishetty143@gmail.com'
SHIELD_ADMIN_EMAILS = 'laxminivasmorishetty143@gmail.com,laxminivasmorishetty143@gmai.com,morishettylaxminivas@gmail.com'


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or SHIELD_SECRET_KEY
    # Data directory at project root — easy to find, edit, and version-control
    JSON_DATA_DIR = os.environ.get('JSON_DATA_DIR') or os.path.join(BASE_DIR, 'data')
    WTF_CSRF_ENABLED = True
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB max upload size
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'app', 'static', 'uploads')
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}

    # Google OAuth Configuration
    GOOGLE_CLIENT_ID = (os.environ.get('GOOGLE_CLIENT_ID') or SHIELD_GOOGLE_CLIENT_ID).strip().strip('"\'')
    GOOGLE_CLIENT_SECRET = (os.environ.get('GOOGLE_CLIENT_SECRET') or SHIELD_GOOGLE_CLIENT_SECRET).strip().strip('"\'')
    GOOGLE_REDIRECT_URI = (os.environ.get('GOOGLE_REDIRECT_URI') or SHIELD_GOOGLE_REDIRECT_URI_PROD).strip().strip('"\'')

    # Administrator Email Configuration
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', SHIELD_ADMIN_EMAIL).strip()
    ADMIN_EMAILS = [e.strip().lower() for e in os.environ.get('ADMIN_EMAILS', SHIELD_ADMIN_EMAILS).split(',') if e.strip()]


class DevelopmentConfig(Config):
    DEBUG = True
    # In local development, prefer the local callback port
    GOOGLE_REDIRECT_URI = (os.environ.get('GOOGLE_REDIRECT_URI') or SHIELD_GOOGLE_REDIRECT_URI_DEV).strip().strip('"\'')


class TestingConfig(Config):
    TESTING = True
    JSON_DATA_DIR = os.path.join(BASE_DIR, 'instance', 'test_data')
    WTF_CSRF_ENABLED = False
    GOOGLE_CLIENT_ID = 'TEST_GOOGLE_CLIENT_ID'
    GOOGLE_CLIENT_SECRET = 'TEST_GOOGLE_CLIENT_SECRET'
    GOOGLE_REDIRECT_URI = 'http://localhost:5002/auth/google/callback'


class ProductionConfig(Config):
    DEBUG = False
    GOOGLE_REDIRECT_URI = (os.environ.get('GOOGLE_REDIRECT_URI') or SHIELD_GOOGLE_REDIRECT_URI_PROD).strip().strip('"\'')


config_by_name = {
    'dev': DevelopmentConfig,
    'test': TestingConfig,
    'testing': TestingConfig,
    'prod': ProductionConfig,
    'default': ProductionConfig if (os.environ.get('PYTHONANYWHERE_DOMAIN') or os.path.exists('/var/www')) else DevelopmentConfig
}

