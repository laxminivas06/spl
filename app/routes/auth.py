from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, session
from flask_login import login_user, logout_user, login_required, current_user
from app.extensions import db
from app.models import User, Franchise
from app.services.audit_service import log_audit
from app.services.oauth_service import oauth

auth_bp = Blueprint('auth', __name__)


def _is_oauth_unconfigured():
    """Return True when GOOGLE_CLIENT_ID is missing or still set to a placeholder value."""
    client_id = current_app.config.get('GOOGLE_CLIENT_ID', '')
    return not client_id or client_id in [
        'MOCK_GOOGLE_CLIENT_ID', 'your_google_client_id',
        'YOUR_GOOGLE_CLIENT_ID', 'your_google_client_id.apps.googleusercontent.com'
    ]


# ─────────────────────────────────────────────────────────────────────────────
# /login  — Show the Google Sign-In landing page
# ─────────────────────────────────────────────────────────────────────────────
@auth_bp.route('/login', methods=['GET'])
@auth_bp.route('/auth/login', methods=['GET'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin.dashboard') if current_user.is_admin else url_for('franchise.dashboard'))
    return render_template('auth/login.html', is_oauth_unconfigured=_is_oauth_unconfigured())


# ─────────────────────────────────────────────────────────────────────────────
# POST /login — Reject any form-based submissions cleanly
# ─────────────────────────────────────────────────────────────────────────────
@auth_bp.route('/login', methods=['POST'])
@auth_bp.route('/auth/login', methods=['POST'])
def login_post():
    # Support automated test-suite login (TESTING mode only)
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
            return redirect(url_for('admin.dashboard') if user.is_admin else url_for('franchise.dashboard'))
    flash('Please use the Google Sign-In button below.', 'info')
    return redirect(url_for('auth.login'))


# ─────────────────────────────────────────────────────────────────────────────
# /google/login  — Kick off Google OAuth redirect
# ─────────────────────────────────────────────────────────────────────────────
@auth_bp.route('/google/login')
@auth_bp.route('/auth/google/login')
def google_login():
    """Initiate the Google OAuth 2.0 Authorization Code flow."""
    if current_user.is_authenticated:
        return redirect(url_for('admin.dashboard') if current_user.is_admin else url_for('franchise.dashboard'))

    # Dev/test shortcut: ?mock_email=xxx bypasses real OAuth
    mock_email = request.args.get('mock_email')
    if mock_email and (current_app.debug or current_app.config.get('TESTING') or _is_oauth_unconfigured()):
        return redirect(url_for('auth.google_callback', mock_email=mock_email))

    # Unconfigured → show dev account selector
    if _is_oauth_unconfigured():
        franchises = Franchise.query.filter_by(is_active=True).all()
        admin_email = current_app.config.get('ADMIN_EMAIL', '')
        admin_emails = current_app.config.get('ADMIN_EMAILS', [admin_email])
        return render_template(
            'auth/google_auth_prompt.html',
            franchises=franchises,
            admin_email=admin_email,
            admin_emails=admin_emails
        )

    # Real OAuth
    try:
        redirect_uri = (
            current_app.config.get('GOOGLE_REDIRECT_URI')
            or url_for('auth.google_callback', _external=True)
        )
        return oauth.google.authorize_redirect(redirect_uri)
    except Exception as e:
        log_audit(None, 'GOOGLE_LOGIN_FAILED', 'User', None, None,
                  f"OAuth initiation error: {e}", status='FAILED')
        return render_template('auth/login.html',
                               is_oauth_unconfigured=False,
                               auth_error=f"Could not connect to Google Sign-In. Please try again.")


# ─────────────────────────────────────────────────────────────────────────────
# /auth/google/callback  — Google OAuth callback handler
# ─────────────────────────────────────────────────────────────────────────────
@auth_bp.route('/google/callback')
@auth_bp.route('/auth/google/callback')
def google_callback():
    """Handle the OAuth 2.0 callback from Google."""

    # ── Handle OAuth errors returned by Google (user denied, etc.) ───────────
    error = request.args.get('error')
    if error:
        error_desc = request.args.get('error_description', '')
        if error == 'access_denied':
            return render_template('auth/login.html',
                                   is_oauth_unconfigured=_is_oauth_unconfigured(),
                                   auth_error="Sign-in was cancelled. Please try again.")
        log_audit(None, 'GOOGLE_LOGIN_FAILED', 'User', None, None,
                  f"OAuth error: {error} — {error_desc}", status='FAILED')
        return render_template('auth/login.html',
                               is_oauth_unconfigured=_is_oauth_unconfigured(),
                               auth_error=f"Google authentication failed: {error_desc or error}. Please try again.")

    mock_email = request.args.get('mock_email')
    google_email = None
    google_sub = None
    google_name = None

    # ── Dev/test mock bypass ─────────────────────────────────────────────────
    if mock_email and (_is_oauth_unconfigured() or current_app.config.get('TESTING') or current_app.debug):
        google_email = mock_email.strip().lower()
    else:
        # ── Real OAuth token exchange ─────────────────────────────────────────
        try:
            token = oauth.google.authorize_access_token()
            userinfo = token.get('userinfo') or {}
            if not userinfo:
                userinfo = oauth.google.get(
                    'https://www.googleapis.com/oauth2/v3/userinfo'
                ).json()

            google_email = (userinfo.get('email') or '').strip().lower()
            email_verified = userinfo.get('email_verified', True)
            google_sub = userinfo.get('sub')
            google_name = userinfo.get('name', '')

            if not google_email:
                log_audit(None, 'GOOGLE_LOGIN_FAILED', 'User', None, None,
                          'Google returned no email address', status='FAILED')
                return render_template('auth/login.html',
                                       is_oauth_unconfigured=False,
                                       auth_error="Google did not return your email address. Please ensure your Google account has a verified email.")

            if not email_verified:
                log_audit(None, 'GOOGLE_LOGIN_FAILED', 'User', None, None,
                          f"Email not verified: {google_email}", status='FAILED')
                return render_template('auth/login.html',
                                       is_oauth_unconfigured=False,
                                       auth_error="Your Google email address is not verified. Please verify it in your Google account settings.")

        except Exception as e:
            err_str = str(e)
            log_audit(None, 'GOOGLE_LOGIN_FAILED', 'User', None, None,
                      f"OAuth token error: {err_str}", status='FAILED')
            # State mismatch usually means the user refreshed or the session expired
            if 'state' in err_str.lower() or 'csrf' in err_str.lower() or 'mismatching' in err_str.lower():
                return render_template('auth/login.html',
                                       is_oauth_unconfigured=False,
                                       auth_error="Session expired or security check failed. Please try signing in again.")
            return render_template('auth/login.html',
                                   is_oauth_unconfigured=False,
                                   auth_error="Google authentication failed. Please try again.")

    # ── Normalize email & look up user / franchise ───────────────────────────
    norm_email = google_email.strip().lower()

    admin_emails_cfg = [e.strip().lower() for e in current_app.config.get('ADMIN_EMAILS', []) if e.strip()]
    hardcoded_admins = {
        'laxminivasmorishetty143@gmail.com', 'laxminivasmorishetty143@gmai.com',
        'admin@sphoorthyengg.ac.in', 'morishettylaxminivas@gmail.com'
    }

    # Strategy 1: look up by google_subject_id (most stable — survives email changes)
    user = None
    if google_sub:
        user = User.query.filter_by(google_subject_id=google_sub).first()

    # Strategy 2: look up by email — prefer the one that has a franchise_id (not orphaned)
    if not user:
        candidates = User.query.filter(User.email.ilike(norm_email)).all()
        if len(candidates) == 1:
            user = candidates[0]
        elif len(candidates) > 1:
            # Prefer: active franchise user > any franchise user > any user
            user = (
                next((u for u in candidates if u.is_active and u.franchise_id), None)
                or next((u for u in candidates if u.franchise_id), None)
                or next((u for u in candidates if u.is_active and u.is_admin), None)
                or candidates[0]
            )

    # Strategy 3: find by Franchise.authorized_email
    franchise = Franchise.query.filter(Franchise.authorized_email.ilike(norm_email)).first()

    # ── Admin auto-provisioning ───────────────────────────────────────────────
    if norm_email in admin_emails_cfg or norm_email in hardcoded_admins:
        if not user:
            user = User(
                username=norm_email.split('@')[0],
                email=norm_email,
                display_name=google_name or 'System Administrator',
                role='ADMIN',
                is_active=True
            )
            db.session.add(user)
            db.session.commit()
        elif not user.is_admin:
            user.role = 'ADMIN'
            db.session.commit()

    # ── Resolve franchise from user's franchise_id (primary anchor) ───────────
    if not franchise and user and getattr(user, 'franchise_id', None):
        franchise = db.session.get(Franchise, user.franchise_id)

    # ── Unauthorized ─────────────────────────────────────────────────────────
    if not franchise and not (user and user.is_admin):
        log_audit(None, 'GOOGLE_ACCOUNT_UNAUTHORIZED', 'User', None, None,
                  f"Unauthorized Google account: {norm_email}", status='DENIED')
        return render_template('auth/unauthorized.html', email=norm_email, is_disabled=False)

    # ── Franchise inactive / Google auth disabled ─────────────────────────────
    # NOTE: Admin users bypass this check — only pure franchise accounts are gated
    if franchise and not (user and user.is_admin) and (not franchise.is_active or not franchise.google_auth_enabled):
        log_audit(user.id if user else None, 'GOOGLE_LOGIN_FAILED', 'Franchise',
                  franchise.id, None,
                  f"Franchise '{franchise.name}' inactive or Google auth disabled",
                  status='DENIED', franchise_id=franchise.id)
        return render_template('auth/unauthorized.html',
                               email=norm_email, franchise_name=franchise.name, is_disabled=True)

    # ── Auto-provision franchise user ─────────────────────────────────────────
    if not user and franchise:
        user = User.query.filter_by(franchise_id=franchise.id).first()
        if not user:
            user = User(
                username=franchise.short_name.lower().replace(' ', '_') if franchise.short_name else norm_email.split('@')[0],
                email=norm_email,
                display_name=google_name or franchise.name,
                role='FRANCHISE',
                franchise_id=franchise.id,
                is_active=True
            )
            db.session.add(user)
            db.session.commit()

    if not user:
        log_audit(None, 'GOOGLE_ACCOUNT_UNAUTHORIZED', 'User', None, None,
                  f"No user record for: {norm_email}", status='DENIED')
        return render_template('auth/unauthorized.html', email=norm_email, is_disabled=False)

    if not user.is_active:
        log_audit(user.id, 'GOOGLE_LOGIN_FAILED', 'User', user.id, None,
                  'User account deactivated', status='DENIED',
                  franchise_id=franchise.id if franchise else None)
        return render_template('auth/unauthorized.html',
                               email=norm_email,
                               franchise_name=franchise.name if franchise else 'SPL Account',
                               is_disabled=True)

    # ── Successful login ──────────────────────────────────────────────────────
    user.last_login_at = datetime.utcnow()
    if google_sub:
        user.google_subject_id = google_sub
    if google_name and not user.display_name:
        user.display_name = google_name
    db.session.commit()

    login_user(user, remember=False)
    log_audit(user.id, 'GOOGLE_LOGIN_SUCCESS', 'User', user.id, None,
              f"Signed in via Google OAuth ({norm_email})",
              status='SUCCESS', franchise_id=user.franchise_id)

    return redirect(url_for('admin.dashboard') if user.is_admin else url_for('franchise.dashboard'))


# ─────────────────────────────────────────────────────────────────────────────
# /logout
# ─────────────────────────────────────────────────────────────────────────────
@auth_bp.route('/logout', methods=['GET', 'POST'])
@auth_bp.route('/auth/logout', methods=['GET', 'POST'])
@login_required
def logout():
    user_id = current_user.id if current_user.is_authenticated else None
    log_audit(user_id, 'LOGOUT', 'User', user_id, None, 'User signed out', status='SUCCESS')
    logout_user()
    return redirect(url_for('auth.login'))


