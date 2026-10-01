import secrets
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, session
from flask_login import login_user, logout_user, login_required, current_user
from app.extensions import db
from app.models import User, Franchise
from app.services.audit_service import log_audit
from app.services.oauth_service import oauth, build_google_auth_url, exchange_google_code

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

    auth_error = request.args.get('auth_error') or request.args.get('error')
    auth_error_title = request.args.get('auth_error_title')
    auth_email = request.args.get('auth_email') or request.args.get('email')

    return render_template(
        'auth/login.html',
        is_oauth_unconfigured=_is_oauth_unconfigured(),
        auth_error=auth_error,
        auth_error_title=auth_error_title,
        auth_email=auth_email
    )


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

    # Unconfigured → do not expose application data; show clean error on login page
    if _is_oauth_unconfigured():
        return render_template(
            'auth/login.html',
            is_oauth_unconfigured=True,
            auth_error="Google Sign-In is currently being configured on this server. Please contact your administrator.",
            auth_error_title="Configuration Notice"
        )

    # Real OAuth
    try:
        # Dynamically adapt redirect_uri to the active request host (PythonAnywhere vs localhost)
        if 'pythonanywhere' in request.host:
            redirect_uri = 'https://splsankalp.pythonanywhere.com/auth/google/callback'
        elif '127.0.0.1' in request.host or 'localhost' in request.host:
            port_suffix = f":{request.host.split(':')[1]}" if ':' in request.host else ""
            redirect_uri = f"http://127.0.0.1{port_suffix}/auth/google/callback"
        else:
            redirect_uri = (
                current_app.config.get('GOOGLE_REDIRECT_URI')
                or url_for('auth.google_callback', _external=True)
            )

        client_id = current_app.config.get('GOOGLE_CLIENT_ID')
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        session['oauth_state'] = state
        session['oauth_nonce'] = nonce
        session['oauth_redirect_uri'] = redirect_uri

        # If Authlib is installed and functional, attempt it first
        if oauth and hasattr(oauth, 'google') and getattr(oauth, 'google', None) is not None:
            try:
                return oauth.google.authorize_redirect(redirect_uri)
            except Exception as oauth_err:
                pass

        # Direct Google OAuth 2.0 Authorization URL (Zero network call, 100% reliable)
        auth_url = build_google_auth_url(client_id, redirect_uri, state, nonce)
        return redirect(auth_url)

    except Exception as e:
        log_audit(None, 'GOOGLE_LOGIN_FAILED', 'User', None, None,
                  f"OAuth initiation error: {e}", status='FAILED')
        return render_template(
            'auth/login.html',
            is_oauth_unconfigured=False,
            auth_error="Could not connect to Google Sign-In service. Please verify your internet connection and try again.",
            auth_error_title="Connection Error"
        )


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
            return render_template(
                'auth/login.html',
                is_oauth_unconfigured=_is_oauth_unconfigured(),
                auth_error="Google sign-in was cancelled. Please try signing in again with your authorized Google account.",
                auth_error_title="Sign-In Cancelled"
            )
        log_audit(None, 'GOOGLE_LOGIN_FAILED', 'User', None, None,
                  f"OAuth error: {error} — {error_desc}", status='FAILED')
        return render_template(
            'auth/login.html',
            is_oauth_unconfigured=_is_oauth_unconfigured(),
            auth_error=f"Google authentication failed: {error_desc or error}. Please try again.",
            auth_error_title="Authentication Failed"
        )

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
            returned_state = request.args.get('state')
            saved_state = session.pop('oauth_state', None)
            saved_redirect_uri = session.pop('oauth_redirect_uri', None)

            # Determine redirect URI matching what was used during authorization
            if saved_redirect_uri:
                redirect_uri = saved_redirect_uri
            elif 'pythonanywhere' in request.host:
                redirect_uri = 'https://splsankalp.pythonanywhere.com/auth/google/callback'
            elif '127.0.0.1' in request.host or 'localhost' in request.host:
                port_suffix = f":{request.host.split(':')[1]}" if ':' in request.host else ""
                redirect_uri = f"http://127.0.0.1{port_suffix}/auth/google/callback"
            else:
                redirect_uri = (
                    current_app.config.get('GOOGLE_REDIRECT_URI')
                    or url_for('auth.google_callback', _external=True)
                )

            code = request.args.get('code')
            userinfo = {}

            # Strategy A: If Authlib is installed and functional, attempt it
            if oauth and hasattr(oauth, 'google') and getattr(oauth, 'google', None) is not None:
                try:
                    token = oauth.google.authorize_access_token()
                    userinfo = token.get('userinfo') or {}
                    if not userinfo:
                        userinfo = oauth.google.get(
                            'https://www.googleapis.com/oauth2/v3/userinfo'
                        ).json()
                except Exception as oauth_err:
                    userinfo = {}

            # Strategy B: Resilient direct token exchange (works without Authlib and with PythonAnywhere proxy)
            if not userinfo.get('email') and code:
                client_id = current_app.config.get('GOOGLE_CLIENT_ID')
                client_secret = current_app.config.get('GOOGLE_CLIENT_SECRET')
                userinfo = exchange_google_code(code, redirect_uri, client_id, client_secret)

            google_email = (userinfo.get('email') or '').strip().lower()
            email_verified = userinfo.get('email_verified', True)
            google_sub = userinfo.get('sub')
            google_name = userinfo.get('name', '')

            if not google_email:
                log_audit(None, 'GOOGLE_LOGIN_FAILED', 'User', None, None,
                          'Google returned no email address', status='FAILED')
                return render_template(
                    'auth/login.html',
                    is_oauth_unconfigured=False,
                    auth_error="Google did not return an email address. Please ensure your Google account has a verified primary email.",
                    auth_error_title="Authentication Incomplete"
                )

            if not email_verified:
                log_audit(None, 'GOOGLE_LOGIN_FAILED', 'User', None, None,
                          f"Email not verified: {google_email}", status='FAILED')
                return render_template(
                    'auth/login.html',
                    is_oauth_unconfigured=False,
                    auth_error=f"The Google account email ({google_email}) is not verified. Please verify it in your Google account settings.",
                    auth_error_title="Email Not Verified",
                    auth_email=google_email
                )

        except Exception as e:
            err_str = str(e)
            log_audit(None, 'GOOGLE_LOGIN_FAILED', 'User', None, None,
                      f"OAuth token error: {err_str}", status='FAILED')
            if 'state' in err_str.lower() or 'csrf' in err_str.lower() or 'mismatching' in err_str.lower():
                return render_template(
                    'auth/login.html',
                    is_oauth_unconfigured=False,
                    auth_error="Your sign-in session expired or the security check failed. Please click Continue with Google to try again.",
                    auth_error_title="Session Expired"
                )
            return render_template(
                'auth/login.html',
                is_oauth_unconfigured=False,
                auth_error=f"Google authentication could not be completed. Please try again.",
                auth_error_title="Authentication Error"
            )

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

    # ── Admin auto-provisioning / assignment ──────────────────────────────────
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

    # ── Unauthorized / Unassigned Google account ─────────────────────────────
    # If the user is neither an admin, nor has an assigned franchise, nor is an existing active user:
    if not franchise and not (user and user.is_admin):
        # Also check if existing user has another valid role
        if not (user and user.is_active and user.role):
            log_audit(None, 'GOOGLE_ACCOUNT_UNAUTHORIZED', 'User', None, None,
                      f"Unauthorized Google account: {norm_email}", status='DENIED')
            return render_template(
                'auth/login.html',
                is_oauth_unconfigured=_is_oauth_unconfigured(),
                auth_error=f"Access Denied: The Google account <strong>{norm_email}</strong> is not assigned to any franchise or role. Please contact the SPL Administrator to request access.",
                auth_error_title="Access Denied: Account Not Assigned",
                auth_email=norm_email
            )

    # ── Franchise inactive / Google auth disabled ─────────────────────────────
    # NOTE: Admin users bypass this check — only pure franchise accounts are gated
    if franchise and not (user and user.is_admin) and (not franchise.is_active or not franchise.google_auth_enabled):
        log_audit(user.id if user else None, 'GOOGLE_LOGIN_FAILED', 'Franchise',
                  franchise.id, None,
                  f"Franchise '{franchise.name}' inactive or Google auth disabled",
                  status='DENIED', franchise_id=franchise.id)
        return render_template(
            'auth/login.html',
            is_oauth_unconfigured=_is_oauth_unconfigured(),
            auth_error=f"Access Denied: Franchise account for '<strong>{franchise.name}</strong>' ({norm_email}) is currently deactivated or Google Sign-In is disabled by the administrator.",
            auth_error_title="Franchise Account Inactive",
            auth_email=norm_email
        )

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
        return render_template(
            'auth/login.html',
            is_oauth_unconfigured=_is_oauth_unconfigured(),
            auth_error=f"Access Denied: No active user profile found for Google account <strong>{norm_email}</strong>. Please contact the administrator.",
            auth_error_title="Account Not Found",
            auth_email=norm_email
        )

    if not user.is_active:
        log_audit(user.id, 'GOOGLE_LOGIN_FAILED', 'User', user.id, None,
                  'User account deactivated', status='DENIED',
                  franchise_id=franchise.id if franchise else None)
        return render_template(
            'auth/login.html',
            is_oauth_unconfigured=_is_oauth_unconfigured(),
            auth_error=f"Access Denied: Your account (<strong>{norm_email}</strong>) has been deactivated by the administrator.",
            auth_error_title="Account Deactivated",
            auth_email=norm_email
        )

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

    # Verify role and redirect to correct authorized dashboard
    if user.is_admin or user.role == 'ADMIN':
        return redirect(url_for('admin.dashboard'))
    elif user.is_franchise or user.role == 'FRANCHISE':
        return redirect(url_for('franchise.dashboard'))
    elif user.role in ['OFFICIAL', 'AUCTIONEER']:
        return redirect(url_for('admin.dashboard'))
    else:
        # Other configured roles: redirect to franchise dashboard if assigned or public teams
        return redirect(url_for('franchise.dashboard') if user.franchise_id else url_for('public.public_teams'))


# ─────────────────────────────────────────────────────────────────────────────
# /logout  — Terminate authenticated session and return to login screen
# ─────────────────────────────────────────────────────────────────────────────
@auth_bp.route('/logout', methods=['GET', 'POST'])
@auth_bp.route('/auth/logout', methods=['GET', 'POST'])
def logout():
    user_id = current_user.id if current_user.is_authenticated else None
    if user_id:
        log_audit(user_id, 'LOGOUT', 'User', user_id, None, 'User signed out', status='SUCCESS')
    logout_user()
    session.clear()
    flash('You have been logged out successfully.', 'info')
    response = redirect(url_for('auth.login'))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


