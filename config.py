import os
from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, '.env'), override=True)

# Allow HTTP transport for local development OAuth flows
os.environ['AUTHLIB_INSECURE_TRANSPORT'] = '1'

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'spl-auction-secret-key-2026-sphoorthy'
    JSON_DATA_DIR = os.environ.get('JSON_DATA_DIR') or os.path.join(BASE_DIR, 'instance', 'data')
    WTF_CSRF_ENABLED = True
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB max upload size
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'app', 'static', 'uploads')
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}

    # Google OAuth Configuration
    GOOGLE_CLIENT_ID = (os.environ.get('GOOGLE_CLIENT_ID') or 'MOCK_GOOGLE_CLIENT_ID').strip().strip('"\'')
    GOOGLE_CLIENT_SECRET = (os.environ.get('GOOGLE_CLIENT_SECRET') or 'MOCK_GOOGLE_CLIENT_SECRET').strip().strip('"\'')
    GOOGLE_REDIRECT_URI = (os.environ.get('GOOGLE_REDIRECT_URI') or 'http://127.0.0.1:5001/auth/google/callback').strip().strip('"\'')

    # Administrator Email Configuration
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'laxminivasmorishetty143@gmail.com').strip()
    ADMIN_EMAILS = [e.strip().lower() for e in os.environ.get('ADMIN_EMAILS', 'laxminivasmorishetty143@gmail.com,laxminivasmorishetty143@gmai.com').split(',') if e.strip()]

class DevelopmentConfig(Config):
    DEBUG = True

class TestingConfig(Config):
    TESTING = True
    JSON_DATA_DIR = os.path.join(BASE_DIR, 'instance', 'test_data')
    WTF_CSRF_ENABLED = False
    GOOGLE_CLIENT_ID = 'TEST_GOOGLE_CLIENT_ID'
    GOOGLE_CLIENT_SECRET = 'TEST_GOOGLE_CLIENT_SECRET'
    GOOGLE_REDIRECT_URI = 'http://localhost:5000/auth/google/callback'

class ProductionConfig(Config):
    DEBUG = False

config_by_name = {
    'dev': DevelopmentConfig,
    'test': TestingConfig,
    'testing': TestingConfig,
    'prod': ProductionConfig,
    'default': DevelopmentConfig
}
