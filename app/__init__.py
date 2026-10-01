import os
from flask import Flask, redirect, url_for, render_template
from config import config_by_name
from app.extensions import db, login_manager, csrf
from app.services.oauth_service import init_oauth
from app.models import User, SystemSettings

def create_app(config_name=None):
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'dev')

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_by_name.get(config_name, config_by_name['default']))

    # Ensure instance & upload folders exist
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    try:
        os.makedirs(app.config['UPLOAD_FOLDER'])
    except OSError:
        pass

    # Initialize extensions & services
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    init_oauth(app)

    # User loader callback for Flask-Login
    @login_manager.user_loader
    def load_user(user_id):
        try:
            return db.session.get(User, int(user_id))
        except (ValueError, TypeError):
            return None

    # Global Jinja Context Processor
    @app.context_processor
    def inject_global_vars():
        return {
            'event_name': SystemSettings.get_setting('event_name', 'SPL'),
            'event_subtitle': SystemSettings.get_setting('event_subtitle', 'Sphoorthy Premier League'),
            'get_setting': SystemSettings.get_setting
        }

    # Custom Jinja filters
    @app.template_filter('currency')
    def format_currency(value):
        try:
            val = int(round(float(value)))
            s = str(val)
            if len(s) <= 3:
                return s
            last_three = s[-3:]
            remaining = s[:-3]
            groups = []
            while len(remaining) > 2:
                groups.insert(0, remaining[-2:])
                remaining = remaining[:-2]
            if remaining:
                groups.insert(0, remaining)
            return f"{','.join(groups)},{last_three}"
        except (ValueError, TypeError):
            return str(value or '0')

    # Register Blueprints
    from app.routes import auth_bp, admin_bp, franchise_bp, live_bp, api_bp, public_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(franchise_bp)
    app.register_blueprint(live_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(public_bp)

    # Root & Auth aliases
    @app.route('/')
    def index():
        return redirect(url_for('auth.login'))

    @app.route('/login', methods=['GET', 'POST'])
    def login_alias():
        from app.routes.auth import login
        return login()

    @app.route('/logout', methods=['GET', 'POST'])
    def logout_alias():
        from app.routes.auth import logout
        return logout()

    # Custom error handlers
    @app.errorhandler(400)
    def bad_request_error(error):
        return render_template('errors/400.html'), 400

    @app.errorhandler(401)
    def unauthorized_error(error):
        return render_template('errors/401.html'), 401

    @app.errorhandler(403)
    def forbidden_error(error):
        return render_template('errors/403.html'), 403

    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('errors/404.html'), 404

    @app.errorhandler(429)
    def ratelimit_error(error):
        return render_template('errors/429.html'), 429

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        return render_template('errors/500.html'), 500

    return app
