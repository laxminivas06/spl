import os
from flask import Flask, redirect, url_for, render_template, request, jsonify, flash
from flask_login import current_user
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

    # Unauthorized handler for Flask-Login
    @login_manager.unauthorized_handler
    def unauthorized_callback():
        if request.path.startswith('/api/') or request.is_json or request.headers.get('Accept') == 'application/json':
            return jsonify({
                'error': 'Unauthorized',
                'message': 'Authentication required. Please sign in with your authorized Google account.'
            }), 401
        flash('Please sign in with your authorized Google account to access this page.', 'warning')
        return redirect(url_for('auth.login'))

    # User loader callback for Flask-Login
    @login_manager.user_loader
    def load_user(user_id):
        try:
            return db.session.get(User, int(user_id))
        except (ValueError, TypeError):
            return None

    # Category Icons (Requirement 1 & Category Logic)
    CATEGORY_ICONS = {
        'BATSMAN': 'https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQ4saHQo4zw7BjytkA_qmWEUs8QViHyauRwpwqzANrRrQ&s=10',
        'BOWLER': 'https://media.istockphoto.com/id/2026855771/vector/cricket-ball-icon-isolated-on-white-background.jpg?s=612x612&w=0&k=20&c=PITZXH3lkWfkNfsYtFqVajAWKntdiXteyTZEOr-o90I=',
        'ALL_ROUNDER': 'https://static.vecteezy.com/system/resources/previews/000/363/479/non_2x/vector-glyph-black-icon.jpg',
        'WICKETKEEPER': 'https://static.thenounproject.com/png/2005527-200.png',
        'ELITE': 'https://cdn-icons-png.flaticon.com/512/2583/2583342.png',
        'SKILLED': 'https://cdn-icons-png.flaticon.com/512/2583/2583319.png',
        'ROOKIE': 'https://cdn-icons-png.flaticon.com/512/2583/2583434.png',
    }

    CATEGORY_FALLBACKS = {
        'BATSMAN': '/static/images/categories/batsman.png',
        'BOWLER': '/static/images/categories/bowler.jpg',
        'ALL_ROUNDER': '/static/images/categories/all_rounder.jpg',
        'WICKETKEEPER': '/static/images/categories/wicketkeeper.png',
        'ELITE': '/static/images/categories/batsman.png',
        'SKILLED': '/static/images/categories/all_rounder.jpg',
        'ROOKIE': '/static/images/categories/bowler.jpg',
    }

    def get_category_icon(role_or_cat):
        key = str(role_or_cat or '').strip().upper().replace(' ', '_').replace('-', '_')
        if 'ELITE' in key:
            return CATEGORY_ICONS['ELITE']
        elif 'SKILL' in key:
            return CATEGORY_ICONS['SKILLED']
        elif 'ROOKIE' in key:
            return CATEGORY_ICONS['ROOKIE']
        elif 'BOWL' in key or 'BALL' in key:
            return CATEGORY_ICONS['BOWLER']
        elif 'ALL' in key or 'ROUND' in key:
            return CATEGORY_ICONS['ALL_ROUNDER']
        elif 'WICKET' in key or 'KEEP' in key or 'WK' in key:
            return CATEGORY_ICONS['WICKETKEEPER']
        else:
            return CATEGORY_ICONS['BATSMAN']

    def get_category_fallback(role_or_cat):
        key = str(role_or_cat or '').strip().upper().replace(' ', '_').replace('-', '_')
        if 'ELITE' in key:
            return CATEGORY_FALLBACKS['ELITE']
        elif 'SKILL' in key:
            return CATEGORY_FALLBACKS['SKILLED']
        elif 'ROOKIE' in key:
            return CATEGORY_FALLBACKS['ROOKIE']
        elif 'BOWL' in key or 'BALL' in key:
            return CATEGORY_FALLBACKS['BOWLER']
        elif 'ALL' in key or 'ROUND' in key:
            return CATEGORY_FALLBACKS['ALL_ROUNDER']
        elif 'WICKET' in key or 'KEEP' in key or 'WK' in key:
            return CATEGORY_FALLBACKS['WICKETKEEPER']
        else:
            return CATEGORY_FALLBACKS['BATSMAN']

    # Global Jinja Context Processor
    @app.context_processor
    def inject_global_vars():
        from app.models.franchise import get_available_branches
        from app.models.player import PlayerCategory
        branch_list = get_available_branches()
        cat_list = PlayerCategory.CHOICES
        return {
            'event_name': SystemSettings.get_setting('event_name', 'SPL'),
            'event_subtitle': SystemSettings.get_setting('event_subtitle', 'Sphoorthy Premier League'),
            'get_setting': SystemSettings.get_setting,
            'CATEGORY_ICONS': CATEGORY_ICONS,
            'CATEGORY_FALLBACKS': CATEGORY_FALLBACKS,
            'get_category_icon': get_category_icon,
            'get_category_fallback': get_category_fallback,
            'branches': branch_list,
            'available_branches': branch_list,
            'categories': cat_list,
            'available_categories': cat_list
        }

    # Custom Jinja filters
    @app.template_filter('category_icon')
    def filter_category_icon(role):
        return get_category_icon(role)

    @app.template_filter('category_fallback')
    def filter_category_fallback(role):
        return get_category_fallback(role)

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

    # Enforce global authentication across the application
    @app.before_request
    def enforce_global_authentication():
        # Static assets are freely accessible
        if request.path.startswith('/static/'):
            return None

        # Only login/OAuth endpoints and aliases are public
        public_endpoints = {
            'static',
            'auth.login',
            'auth.login_post',
            'auth.google_login',
            'auth.google_callback',
            'auth.logout',
            'login_alias',
            'logout_alias',
            'index'
        }

        if request.endpoint in public_endpoints:
            return None

        if not current_user.is_authenticated:
            if request.path.startswith('/api/') or request.is_json or request.headers.get('Accept') == 'application/json':
                return jsonify({
                    'error': 'Unauthorized',
                    'message': 'Authentication required. Please sign in with your authorized Google account.'
                }), 401
            flash('Please sign in with your authorized Google account to access this page.', 'warning')
            return redirect(url_for('auth.login'))

    # Security & Cache-Control: prevent back-button caching of protected pages
    @app.after_request
    def set_security_headers(response):
        if not request.path.startswith('/static/'):
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
        return response

    # Root & Auth aliases
    @app.route('/')
    def index():
        if current_user.is_authenticated:
            return redirect(url_for('admin.dashboard') if current_user.is_admin else url_for('franchise.dashboard'))
        return redirect(url_for('auth.login'))

    @app.route('/login', methods=['GET', 'POST'])
    def login_alias():
        from app.routes.auth import login, login_post
        if request.method == 'POST':
            return login_post()
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
        if request.path.startswith('/api/') or request.is_json or request.headers.get('Accept') == 'application/json':
            return jsonify({'error': 'Unauthorized', 'message': 'Authentication required.'}), 401
        flash('Please sign in with your authorized Google account to access this page.', 'warning')
        return redirect(url_for('auth.login'))

    @app.errorhandler(403)
    def forbidden_error(error):
        if request.path.startswith('/api/') or request.is_json or request.headers.get('Accept') == 'application/json':
            return jsonify({'error': 'Forbidden', 'message': 'Access forbidden. You do not have permission for this resource.'}), 403
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
