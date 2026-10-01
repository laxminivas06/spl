try:
    from authlib.integrations.flask_client import OAuth
    oauth = OAuth()
except ImportError:
    oauth = None

def init_oauth(app):
    """Register Google OAuth client with Flask app."""
    if oauth is None:
        return
    oauth.init_app(app)
    
    # Avoid network calls during testing unless explicitly configured
    if not app.config.get('TESTING'):
        oauth.register(
            name='google',
            client_id=app.config.get('GOOGLE_CLIENT_ID'),
            client_secret=app.config.get('GOOGLE_CLIENT_SECRET'),
            server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
            client_kwargs={
                'scope': 'openid email profile'
            }
        )
    else:
        oauth.register(
            name='google',
            client_id='TEST_CLIENT_ID',
            client_secret='TEST_CLIENT_SECRET',
            authorize_url='https://accounts.google.com/o/oauth2/v2/auth',
            access_token_url='https://oauth2.googleapis.com/token',
            client_kwargs={
                'scope': 'openid email profile'
            }
        )
