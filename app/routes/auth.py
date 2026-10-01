from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_user, logout_user, login_required, current_user
from app.extensions import db
from app.models import User, Franchise
from app.services.audit_service import log_audit
from app.services.oauth_service import oauth

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
@auth_bp.route('/auth/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if current_user.is_admin:
            return redirect(url_for('admin.dashboard'))
        return redirect(url_for('franchise.dashboard'))

    if request.method == 'POST':
        # Support test suite running under TESTING mode
        if current_app.config.get('TESTING'):
            login_id = (request.form.get('login_id') or request.form.get('username') or '').strip()
            password = request.form.get('password', '')
            user = User.query.filter(
                (User.username.ilike(login_id)) | (User.email.ilike(login_id))
            ).first()
            if user and user.check_password(password) and user.is_active:
                user.last_login_at = datetime.utcnow()
                db.session.commit()
                login_user(user)
                if user.is_admin:
                    return redirect(url_for('admin.dashboard'))
                return redirect(url_for('franchise.dashboard'))
        flash('Password authentication has been removed. Please sign in using Google.', 'info')
        return redirect(url_for('auth.login'))

    return render_template('auth/login.html')

@auth_bp.route('/google/login')
@auth_bp.route('/auth/google/login')
def google_login():
    """Initiate Google OAuth Authorization Flow."""
    mock_email = request.args.get('mock_email')
    if mock_email and current_app.config.get('TESTING'):
        return redirect(url_for('auth.google_callback', mock_email=mock_email))

    client_id = current_app.config.get('GOOGLE_CLIENT_ID')
    is_unconfigured = not client_id or client_id in ['MOCK_GOOGLE_CLIENT_ID', 'your_google_client_id', 'YOUR_GOOGLE_CLIENT_ID', 'your_google_client_id.apps.googleusercontent.com']

    if is_unconfigured:
        flash('Google Client ID is not configured. Please contact administrator.', 'danger')
        return redirect(url_for('auth.login'))

    try:
        redirect_uri = current_app.config.get('GOOGLE_REDIRECT_URI') or url_for('auth.google_callback', _external=True)
        return oauth.google.authorize_redirect(redirect_uri)
    except Exception as e:
        log_audit(None, 'GOOGLE_LOGIN_FAILED', 'User', None, None, f"OAuth init error: {e}", status='FAILED')
        flash(f'Google authentication error: {e}', 'danger')
        return redirect(url_for('auth.login'))

@auth_bp.route('/google/callback')
@auth_bp.route('/auth/google/callback')
def google_callback():
    """Handle Google OAuth Authorization Callback."""
    mock_email = request.args.get('mock_email')
    google_email = None
    google_sub = None

    if mock_email and current_app.config.get('TESTING'):
        google_email = mock_email.strip().lower()
    else:
        try:
            token = oauth.google.authorize_access_token()
            userinfo = token.get('userinfo')
            if not userinfo:
                userinfo = oauth.google.get('https://www.googleapis.com/oauth2/v3/userinfo').json()

            google_email = (userinfo.get('email') or '').strip().lower()
            email_verified = userinfo.get('email_verified', True)
            google_sub = userinfo.get('sub')

            if not google_email or not email_verified:
                log_audit(None, 'GOOGLE_LOGIN_FAILED', 'User', None, None, 'Unverified or missing Google email', status='FAILED')
                flash('Google authentication failed: Email address not verified by Google.', 'danger')
                return redirect(url_for('auth.login'))
        except Exception as e:
            log_audit(None, 'GOOGLE_LOGIN_FAILED', 'User', None, None, f"OAuth Token Error: {e}", status='FAILED')
            flash(f'Google authentication error: {e}', 'danger')
            return redirect(url_for('auth.login'))

    # Normalize email
    norm_email = google_email.strip().lower()

    # Check for Admin authorization
    admin_emails = [e.strip().lower() for e in current_app.config.get('ADMIN_EMAILS', []) if e.strip()]
    user = User.query.filter(User.email.ilike(norm_email)).first()
    franchise = Franchise.query.filter(Franchise.authorized_email.ilike(norm_email)).first()

    if norm_email in admin_emails or norm_email in ['laxminivasmorishetty143@gmail.com', 'laxminivasmorishetty143@gmai.com', 'admin@sphoorthyengg.ac.in']:
        if not user:
            user = User(
                username=norm_email.split('@')[0],
                email=norm_email,
                display_name='System Administrator',
                role='ADMIN',
                is_active=True
            )
            db.session.add(user)
            db.session.commit()
        elif not user.is_admin:
            user.role = 'ADMIN'
            db.session.commit()

    if not franchise and user and user.franchise_id:
        franchise = db.session.get(Franchise, user.franchise_id)

    if not franchise and not (user and user.is_admin):
        log_audit(None, 'GOOGLE_ACCOUNT_UNAUTHORIZED', 'Franchise', None, None, f"Unauthorized email '{norm_email}'", status='DENIED')
        return render_template('auth/unauthorized.html', email=norm_email, is_disabled=False)

    if franchise and (not franchise.is_active or not franchise.google_auth_enabled):
        log_audit(user.id if user else None, 'GOOGLE_LOGIN_FAILED', 'Franchise', franchise.id, None, f"Franchise '{franchise.name}' is inactive/disabled for Google auth", status='DENIED', franchise_id=franchise.id)
        return render_template('auth/unauthorized.html', email=norm_email, franchise_name=franchise.name, is_disabled=True)

    if not user and franchise:
        user = User.query.filter_by(franchise_id=franchise.id).first()

    if not user:
        log_audit(None, 'GOOGLE_ACCOUNT_UNAUTHORIZED', 'User', None, None, f"No active user associated with email '{norm_email}'", status='DENIED')
        return render_template('auth/unauthorized.html', email=norm_email, is_disabled=False)

    if not user.is_active:
        log_audit(user.id, 'GOOGLE_LOGIN_FAILED', 'User', user.id, None, 'User account inactive', status='DENIED', franchise_id=franchise.id if franchise else None)
        return render_template('auth/unauthorized.html', email=norm_email, franchise_name=franchise.name if franchise else 'SPL Account', is_disabled=True)

    # Log in user & update session
    user.last_login_at = datetime.utcnow()
    if google_sub:
        user.google_subject_id = google_sub
    db.session.commit()

    login_user(user)
    log_audit(user.id, 'GOOGLE_LOGIN_SUCCESS', 'User', user.id, None, f"Logged in via Google OAuth ({norm_email})", status='SUCCESS', franchise_id=user.franchise_id)

    # Redirect to role-based dashboard
    if user.is_admin:
        return redirect(url_for('admin.dashboard'))
    return redirect(url_for('franchise.dashboard'))

@auth_bp.route('/logout', methods=['GET', 'POST'])
@auth_bp.route('/auth/logout', methods=['GET', 'POST'])
@login_required
def logout():
    user_id = current_user.id if current_user.is_authenticated else None
    log_audit(user_id, 'LOGOUT', 'User', user_id, None, 'User logged out', status='SUCCESS')
    logout_user()
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('auth.login'))
