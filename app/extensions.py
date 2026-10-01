from app.storage import JSONDB
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect

db = JSONDB()
login_manager = LoginManager()
csrf = CSRFProtect()

login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'warning'
