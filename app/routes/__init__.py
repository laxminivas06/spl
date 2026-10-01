from app.routes.auth import auth_bp
from app.routes.admin import admin_bp
from app.routes.franchise import franchise_bp
from app.routes.live import live_bp
from app.routes.api import api_bp
from app.routes.public import public_bp

__all__ = ['auth_bp', 'admin_bp', 'franchise_bp', 'live_bp', 'api_bp', 'public_bp']
