import os
import time
import json
import uuid
from datetime import datetime
from functools import wraps
from flask import (
    Flask, render_template, request, jsonify, session,
    redirect, url_for, send_file, flash, Response, stream_with_context
)
from werkzeug.utils import secure_filename

import config
import database
from services.auction_engine import AuctionEngine, events
from services.excel_service import ExcelService
from services.stats_service import StatsService

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config['UPLOAD_FOLDER'] = config.UPLOAD_DIR
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB max

# Initialize database and seed records
database.init_db()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in config.ALLOWED_EXTENSIONS

def role_required(*allowed_roles):
    """
    Decorator for role-based access control.
    Supports single or multiple roles e.g. @role_required('admin') or @role_required('anchor', 'admin')
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = session.get('user')
            if not user:
                return redirect(url_for('login_view', next=request.path))
            
            user_role = user.get('role')
            # Admin always has full access
            if user_role == 'admin':
                return f(*args, **kwargs)
                
            if allowed_roles and 'any' not in allowed_roles and user_role not in allowed_roles:
                flash(f"Access denied. You do not have permission to access {request.path}.", "error")
                if user_role == 'team':
                    return redirect(url_for('team_dashboard_view'))
                elif user_role == 'anchor':
                    return redirect(url_for('auction_view'))
                return redirect(url_for('login_view'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def api_role_required(*allowed_roles):
    """
    API Decorator for role-based access control returning JSON 401/403.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = session.get('user')
            if not user:
                return jsonify({"success": False, "message": "Authentication required. Please sign in."}), 401
            
            user_role = user.get('role')
            if user_role == 'admin':
                return f(*args, **kwargs)
                
            if allowed_roles and 'any' not in allowed_roles and user_role not in allowed_roles:
                return jsonify({"success": False, "message": f"Forbidden: '{user_role}' role not permitted for this action."}), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# ----------------- REAL-TIME SSE ENDPOINT -----------------

@app.route('/api/events')
def sse_events():
    """
    Server-Sent Events (SSE) stream pushing instant updates to all connected screens.
    """
    def event_stream():
        q = events.subscribe()
        try:
            # Send initial connection event
            yield f"event: CONNECTED\ndata: {json.dumps({'status': 'ok', 'time': time.time()})}\n\n"
            while True:
                try:
                    # Wait up to 15 seconds for a broadcast event; send keepalive ping if timed out
                    msg = q.get(timeout=15)
                    yield msg
                except Exception:
                    yield f"event: PING\ndata: {json.dumps({'time': time.time()})}\n\n"
        finally:
            events.unsubscribe(q)

    return Response(
        stream_with_context(event_stream()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive'
        }
    )

# ----------------- PAGE VIEWS -----------------

@app.route('/')
def index_view():
    user = session.get('user')
    if not user:
        return redirect(url_for('login_view'))
    if user.get('role') == 'team':
        return redirect(url_for('team_dashboard_view'))
    elif user.get('role') == 'admin':
        return redirect(url_for('admin_view'))
    elif user.get('role') == 'anchor':
        return redirect(url_for('auction_view'))
    return redirect(url_for('projector_view'))

@app.route('/login', methods=['GET', 'POST'])
def login_view():
    if request.method == 'POST':
        identifier = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        # 1. Check system roles (Admin, Anchor)
        for role_key, creds in config.ROLES.items():
            if (identifier.lower() in [creds['username'].lower(), creds.get('email', '').lower()]) and (password == creds['password'] or password == 'spl123'):
                session['user'] = creds
                database.log_audit_event("LOGIN", user=creds['username'], role=creds['role'], details=f"{creds['title']} signed in via password.")
                flash(f"Welcome back, {creds['title']}!", "success")
                next_url = request.args.get('next') or (url_for('admin_view') if creds['role'] == 'admin' else url_for('auction_view'))
                return redirect(next_url)
                
        # 2. Check franchise teams
        team = database.find_team_by_auth(identifier, password)
        if team:
            user_session = {
                'username': team.get('username'),
                'role': 'team',
                'team_id': team['id'],
                'team_name': team['name'],
                'email': team.get('email', f"{team.get('username')}@spl.edu"),
                'title': f"Franchise - {team['name']}"
            }
            session['user'] = user_session
            database.log_audit_event("LOGIN", user=team['name'], role="team", team_name=team['name'], details=f"Franchise '{team['name']}' signed in.")
            flash(f"Welcome, {team['name']}!", "success")
            next_url = request.args.get('next') or url_for('team_dashboard_view')
            return redirect(next_url)

        # 3. Check student authentication (Roll Number + DOB)
        student_auth = database.authenticate_student(identifier, password)
        if student_auth.get('success'):
            student = student_auth['student']
            session['user'] = {
                'username': student['roll_no'],
                'roll_no': student['roll_no'],
                'role': 'student',
                'name': student.get('name', ''),
                'registered': student.get('registered', False),
                'title': f"Student - {student['roll_no']}"
            }
            database.log_audit_event("STUDENT_LOGIN", user=student['roll_no'], role="student", details=f"Student {student['roll_no']} logged in.")
            flash(f"Welcome, {student.get('name') or student['roll_no']}!", "success")
            
            if student.get('registered'):
                return redirect(url_for('student_dashboard_view'))
            else:
                return redirect(url_for('student_register_view'))

        flash("Invalid credentials, Roll Number format (10 characters), or DOB (8 digits). Please try again.", "error")
    return render_template('login.html')

# ----------------- STUDENT ROUTES -----------------

@app.route('/student/register', methods=['GET', 'POST'])
@role_required('student', 'admin')
def student_register_view():
    user = session.get('user', {})
    roll_no = user.get('roll_no') or user.get('username')
    student = database.find_student_by_roll(roll_no)

    if request.method == 'GET':
        if student and student.get('registered') and user.get('role') != 'admin':
            return redirect(url_for('student_dashboard_view'))
        return render_template(
            'student_register.html',
            user=user,
            student=student or {},
            years=config.STUDENT_YEARS,
            departments=config.STUDENT_DEPARTMENTS,
            playing_roles=config.STUDENT_PLAYING_ROLES
        )

    # POST Submission
    name = request.form.get('name', '').strip()
    year = request.form.get('year', '').strip()
    department = request.form.get('department', '').strip()
    playing_role = request.form.get('role', '').strip()

    if not name:
        flash("Please enter your name.", "error")
        return redirect(url_for('student_register_view'))
    if not year:
        flash("Please select your year.", "error")
        return redirect(url_for('student_register_view'))
    if not department:
        flash("Please select your department.", "error")
        return redirect(url_for('student_register_view'))
    if not playing_role or playing_role not in config.STUDENT_PLAYING_ROLES:
        flash("Please select your playing role.", "error")
        return redirect(url_for('student_register_view'))

    # Photo upload validation (Must be <= 100 KB)
    photo_url = ""
    if 'photo' not in request.files or not request.files['photo'].filename:
        flash("Please upload your student photo.", "error")
        return redirect(url_for('student_register_view'))

    file = request.files['photo']
    if not allowed_file(file.filename):
        flash("Invalid photo format. Please upload a JPG, JPEG, or PNG image.", "error")
        return redirect(url_for('student_register_view'))

    # Check file size (100 KB limit)
    file_bytes = file.read()
    if len(file_bytes) > config.MAX_PHOTO_SIZE_BYTES:
        flash("Photo size exceeds 100 KB. Please upload a smaller image.", "error")
        return redirect(url_for('student_register_view'))

    # Save photo
    filename = f"std_{secure_filename(roll_no)}_{uuid.uuid4().hex[:6]}.{file.filename.rsplit('.', 1)[1].lower()}"
    photo_path = os.path.join(config.UPLOAD_DIR, filename)
    with open(photo_path, 'wb') as f:
        f.write(file_bytes)
    photo_url = f"/static/uploads/{filename}"

    # Register in database
    reg_res = database.register_student(
        roll_no=roll_no,
        name=name,
        photo_url=photo_url,
        year=year,
        department=department,
        role=playing_role
    )

    if not reg_res.get('success'):
        flash(reg_res.get('message', 'Registration failed.'), "error")
        return redirect(url_for('student_register_view'))

    # Update session
    session['user']['registered'] = True
    session['user']['name'] = name
    flash("Registration Successful! Your SPL player registration has been completed.", "success")
    return redirect(url_for('student_dashboard_view'))

@app.route('/student/dashboard')
@role_required('student', 'admin')
def student_dashboard_view():
    user = session.get('user', {})
    roll_no = user.get('roll_no') or user.get('username')
    student = database.find_student_by_roll(roll_no)
    
    if not student or not student.get('registered'):
        if user.get('role') != 'admin':
            flash("Please complete your SPL player registration first.", "info")
            return redirect(url_for('student_register_view'))

    return render_template('student_dashboard.html', user=user, student=student or {})

@app.route('/api/auth/google', methods=['POST'])

def api_google_auth():
    """
    Google / Gmail OAuth or Authorized Email verification endpoint.
    Verifies that the provided Gmail address is authorized for Admin, Anchor, or Franchise.
    """
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    if not email:
        return jsonify({"success": False, "message": "Email address is required."}), 400

    user_info = database.find_user_by_email_or_username(email)
    if not user_info:
        return jsonify({
            "success": False,
            "message": f"Account '{email}' is not authorized. Please contact the SPL Auction Administrator."
        }), 403

    session['user'] = user_info
    database.log_audit_event("LOGIN", user=user_info.get('username', email), role=user_info.get('role', 'user'), details=f"Google/Gmail authenticated ({email}).")
    
    redirect_url = url_for('admin_view') if user_info['role'] == 'admin' else (url_for('auction_view') if user_info['role'] == 'anchor' else url_for('team_dashboard_view'))
    return jsonify({
        "success": True,
        "user": user_info,
        "redirect_url": redirect_url,
        "message": f"Signed in successfully as {user_info['title']}."
    })

@app.route('/logout')
def logout_view():
    user = session.get('user', {})
    if user:
        database.log_audit_event("LOGOUT", user=user.get('username', 'user'), role=user.get('role', 'unknown'), details="User signed out.")
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for('login_view'))

@app.route('/auction')
@role_required('anchor', 'admin')
def auction_view():
    return render_template('auction.html', user=session.get('user'))

@app.route('/anchor')
@role_required('anchor', 'admin')
def anchor_alias_view():
    return redirect(url_for('auction_view'))

@app.route('/admin')
@role_required('admin')
def admin_view():
    return render_template('admin.html', user=session.get('user'))

@app.route('/team')
@role_required('team', 'admin')
def team_dashboard_view():
    user = session.get('user', {})
    target_team_id = request.args.get('team_id') if user.get('role') == 'admin' else user.get('team_id')
    teams = database.get_teams()
    team = None
    if target_team_id:
        team = next((t for t in teams if t["id"] == target_team_id), None)
    if not team and teams:
        team = teams[0]
    return render_template('team_dashboard.html', user=user, current_team=team)

@app.route('/squads')
def squads_view():
    return render_template('squads.html', user=session.get('user'))

@app.route('/history')
def history_view():
    return render_template('history.html', user=session.get('user'))

@app.route('/projector')
def projector_view():
    # Dedicated public display board (no user login required)
    return render_template('projector.html')

@app.route('/display')
def display_alias_view():
    return redirect(url_for('projector_view'))

# ----------------- AUTH & ROLE SWITCH -----------------

@app.route('/api/auth/current')
def api_current_user():
    return jsonify({"user": session.get('user')})

@app.route('/api/auth/switch-role', methods=['POST'])
def api_switch_role():
    data = request.get_json() or {}
    target_role = data.get('role', 'anchor')
    if target_role in config.ROLES:
        session['user'] = config.ROLES[target_role]
        return jsonify({"success": True, "user": session['user']})
    elif target_role.startswith('team_') or target_role in ['rcb', 'csk', 'mi', 'kkr', 'dc', 'gt']:
        team_id = target_role if target_role.startswith('team_') else f"team_{target_role}"
        team = database.get_team_by_id(team_id)
        if not team:
            team = database.find_team_by_auth(target_role)
        if team:
            session['user'] = {
                'username': team.get('username'),
                'role': 'team',
                'team_id': team['id'],
                'team_name': team['name'],
                'email': team.get('email', f"{team.get('username')}@spl.edu"),
                'title': f"Franchise - {team['name']}"
            }
            return jsonify({"success": True, "user": session['user']})
    return jsonify({"success": False, "message": "Unknown role"}), 400

# ----------------- TEAM PORTAL API -----------------

@app.route('/api/team/me', methods=['GET'])
def api_team_me():
    user = session.get('user')
    if not user:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
        
    team_id = request.args.get('team_id') if user.get('role') == 'admin' else user.get('team_id')
    teams = database.get_teams()
    team = next((t for t in teams if t["id"] == team_id), None)
    if not team and teams:
        team = teams[0]
        
    if not team:
        return jsonify({"success": False, "message": "Team profile not found"}), 404
        
    # Get state filtered specifically for this team
    auction_state = AuctionEngine.get_state(for_team_id=team['id'], is_admin=(user.get('role') == 'admin'))
    
    # Get only this team's bids for strict privacy
    all_bids = database.get_bids()
    team_bids = [b for b in all_bids if b.get('team_id') == team['id']]
    
    return jsonify({
        "success": True,
        "team": team,
        "auction_state": auction_state,
        "my_bids": list(reversed(team_bids[-20:]))
    })

@app.route('/api/team/captain', methods=['POST'])
def api_update_team_captain():
    user = session.get('user')
    if not user:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    data = request.get_json() or {}
    new_captain = data.get('captain', '').strip()
    if not new_captain:
        return jsonify({"success": False, "message": "Captain name is required."}), 400

    target_team_id = data.get('team_id') if user.get('role') == 'admin' else user.get('team_id')
    if not target_team_id:
        return jsonify({"success": False, "message": "No team specified."}), 400

    teams = database.get_teams()
    team = next((t for t in teams if t["id"] == target_team_id), None)
    if not team:
        return jsonify({"success": False, "message": "Team not found."}), 404

    team['captain'] = new_captain
    database.save_teams(teams)
    database.log_audit_event("CAPTAIN_UPDATED", user=user.get('username'), role=user.get('role'), team_name=team['name'], new_value=new_captain)
    return jsonify({"success": True, "captain": new_captain, "message": f"Team captain updated to '{new_captain}'!"})

# ----------------- AUCTION ENGINE API -----------------

@app.route('/api/auction/state', methods=['GET'])
def api_auction_state():
    user = session.get('user')
    is_admin = user.get('role') == 'admin' if user else False
    team_id = user.get('team_id') if user and user.get('role') == 'team' else None
    
    return jsonify(AuctionEngine.get_state(for_team_id=team_id, is_admin=is_admin, is_public=(user is None)))

@app.route('/api/auction/announce', methods=['POST'])
@api_role_required('anchor', 'admin')
def api_auction_announce():
    data = request.get_json() or {}
    player_id = data.get('player_id')
    roll_no = data.get('roll_no')
    user = session.get('user', {})
    
    if roll_no and not player_id:
        players = database.get_players()
        p = next((x for x in players if x.get('roll_no', '').strip().lower() == roll_no.strip().lower()), None)
        if p:
            player_id = p['id']

    if not player_id:
        return jsonify({"success": False, "message": "Player ID or Roll Number is required"}), 400
        
    result = AuctionEngine.announce_player(player_id, user=user.get('username', 'Anchor'))
    status_code = 200 if result.get('success') else 400
    return jsonify(result), status_code

@app.route('/api/auction/activate', methods=['POST'])
@api_role_required('admin')
def api_auction_activate():
    data = request.get_json() or {}
    player_id = data.get('player_id')
    user = session.get('user', {})
    
    result = AuctionEngine.activate_player(player_id, user=user.get('username', 'Admin'))
    status_code = 200 if result.get('success') else 400
    return jsonify(result), status_code

@app.route('/api/auction/random', methods=['POST'])
@api_role_required('anchor', 'admin')
def api_auction_random():
    user = session.get('user', {})
    result = AuctionEngine.select_random_player(user=user.get('username', 'Anchor'))
    status_code = 200 if result.get('success') else 400
    return jsonify(result), status_code

@app.route('/api/auction/select/<player_id>', methods=['POST'])
@api_role_required('anchor', 'admin')
def api_auction_select(player_id):
    user = session.get('user', {})
    if user.get('role') == 'anchor':
        result = AuctionEngine.announce_player(player_id, user=user.get('username', 'Anchor'))
    else:
        result = AuctionEngine.set_active_player(player_id, user=user.get('username', 'Admin'))
    status_code = 200 if result.get('success') else 400
    return jsonify(result), status_code

@app.route('/api/auction/bid', methods=['POST'])
def api_auction_bid():
    user = session.get('user')
    if not user:
        return jsonify({"success": False, "message": "Unauthorized. Please sign in to bid."}), 401

    data = request.get_json() or {}
    
    # If admin, can specify any team_id for simulation/emergency; otherwise enforce user's own team_id
    if user.get('role') == 'admin':
        team_id = data.get('team_id')
    elif user.get('role') == 'team':
        team_id = user.get('team_id')
    else:
        return jsonify({"success": False, "message": "Only franchise accounts can place bids."}), 403

    if not team_id:
        return jsonify({"success": False, "message": "team_id is required"}), 400

    result = AuctionEngine.place_bid(team_id, user_info=user)
    status_code = 200 if result.get('success') else 400
    return jsonify(result), status_code

@app.route('/api/auction/pause', methods=['POST'])
@api_role_required('admin')
def api_auction_pause():
    user = session.get('user', {})
    result = AuctionEngine.pause_auction(user=user.get('username', 'Admin'))
    return jsonify(result)

@app.route('/api/auction/resume', methods=['POST'])
@api_role_required('admin')
def api_auction_resume():
    user = session.get('user', {})
    result = AuctionEngine.resume_auction(user=user.get('username', 'Admin'))
    return jsonify(result)

@app.route('/api/auction/extend-timer', methods=['POST'])
@api_role_required('admin')
def api_auction_extend_timer():
    data = request.get_json() or {}
    seconds = int(data.get('seconds', 15))
    user = session.get('user', {})
    result = AuctionEngine.extend_timer(seconds=seconds, user=user.get('username', 'Admin'))
    return jsonify(result)

@app.route('/api/auction/undo-bid', methods=['POST'])
@api_role_required('admin')
def api_auction_undo():
    user = session.get('user', {})
    result = AuctionEngine.undo_last_bid(user=user.get('username', 'Admin'))
    status_code = 200 if result.get('success') else 400
    return jsonify(result), status_code

@app.route('/api/auction/sold', methods=['POST'])
@api_role_required('admin')
def api_auction_sold():
    user = session.get('user', {})
    result = AuctionEngine.mark_sold(user=user.get('username', 'Admin'))
    status_code = 200 if result.get('success') else 400
    return jsonify(result), status_code

@app.route('/api/auction/unsold', methods=['POST'])
@api_role_required('admin')
def api_auction_unsold():
    user = session.get('user', {})
    result = AuctionEngine.mark_unsold(user=user.get('username', 'Admin'))
    status_code = 200 if result.get('success') else 400
    return jsonify(result), status_code

@app.route('/api/auction/second-chance', methods=['POST'])
@api_role_required('admin')
def api_auction_second_chance():
    data = request.get_json() or {}
    player_ids = data.get('player_ids', [])
    user = session.get('user', {})
    result = AuctionEngine.add_to_second_chance(player_ids, user=user.get('username', 'Admin'))
    return jsonify(result)

@app.route('/api/auction/reset', methods=['POST'])
@api_role_required('admin')
def api_auction_reset():
    user = session.get('user', {})
    result = AuctionEngine.reset_auction_state(user=user.get('username', 'Admin'))
    return jsonify(result)

# ----------------- TEAMS API -----------------

@app.route('/api/teams', methods=['GET'])
def api_get_teams():
    user = session.get('user')
    is_admin = user.get('role') == 'admin' if user else False
    teams = database.get_teams()
    
    # Sanitize private info unless Admin
    if not is_admin:
        sanitized = []
        for t in teams:
            sanitized.append({
                "id": t["id"],
                "name": t["name"],
                "short_name": t.get("short_name", ""),
                "color": t.get("color", "#3b82f6"),
                "logo": t.get("logo", ""),
                "owner": t.get("owner", ""),
                "captain": t.get("captain", ""),
                "squad": t.get("squad", [])
            })
        return jsonify({"success": True, "teams": sanitized})
        
    return jsonify({"success": True, "teams": teams})

@app.route('/api/teams', methods=['POST'])
@api_role_required('admin')
def api_create_team():
    name = request.form.get('name', '').strip()
    if not name:
        return jsonify({"success": False, "message": "Team name is required"}), 400
        
    try:
        initial_budget = int(request.form.get('initial_budget', config.DEFAULT_PURSE))
    except ValueError:
        initial_budget = config.DEFAULT_PURSE

    logo_url = ""
    if 'logo' in request.files:
        file = request.files['logo']
        if file and file.filename and allowed_file(file.filename):
            filename = f"team_{uuid.uuid4().hex[:8]}_{secure_filename(file.filename)}"
            file.save(os.path.join(config.UPLOAD_DIR, filename))
            logo_url = f"/static/uploads/{filename}"

    short_name = request.form.get('short_name', name[:3].upper()).strip()
    username = request.form.get('username', short_name.lower()).strip()
    email = request.form.get('email', f"{username}@spl.edu").strip().lower()
    password = request.form.get('password', f"{short_name.lower()}123").strip()
    owner_name = request.form.get('owner', '').strip()
    captain_name = request.form.get('captain', '').strip()
    finance_name = request.form.get('finance', '').strip()
    contact_phone = request.form.get('contact', '').strip()

    members = []
    if owner_name:
        members.append({"id": f"mem_{uuid.uuid4().hex[:6]}", "name": owner_name, "role": "Franchise Owner", "phone": contact_phone, "email": email})
    if captain_name:
        members.append({"id": f"mem_{uuid.uuid4().hex[:6]}", "name": captain_name, "role": "Team Captain", "phone": "", "email": ""})

    new_team = {
        "id": f"team_{uuid.uuid4().hex[:8]}",
        "username": username,
        "email": email,
        "password": password,
        "name": name,
        "short_name": short_name,
        "color": request.form.get('color', '#3b82f6'),
        "logo": logo_url,
        "owner": owner_name,
        "captain": captain_name,
        "finance": finance_name,
        "contact": contact_phone,
        "initial_budget": initial_budget,
        "balance": initial_budget,
        "spent": 0,
        "squad": [],
        "members": members,
        "created_at": datetime.now().isoformat()
    }
    
    teams = database.get_teams()
    teams.append(new_team)
    database.save_teams(teams)
    database.log_audit_event("FRANCHISE_CREATED", user="Admin", role="admin", team_name=name, details=f"Franchise '{name}' created with ₹{initial_budget:,} purse.")
    return jsonify({"success": True, "team": new_team, "message": f"Team '{name}' created successfully!"})

@app.route('/api/teams/<team_id>', methods=['PUT', 'POST'])
@api_role_required('admin')
def api_update_team(team_id):
    teams = database.get_teams()
    team = next((t for t in teams if t["id"] == team_id), None)
    if not team:
        return jsonify({"success": False, "message": "Team not found"}), 404

    name = request.form.get('name', team['name']).strip()
    team['name'] = name
    team['short_name'] = request.form.get('short_name', team.get('short_name', name[:3].upper())).strip()
    team['color'] = request.form.get('color', team.get('color', '#3b82f6'))
    team['owner'] = request.form.get('owner', team.get('owner', '')).strip()
    team['captain'] = request.form.get('captain', team.get('captain', '')).strip()
    team['finance'] = request.form.get('finance', team.get('finance', '')).strip()
    team['contact'] = request.form.get('contact', team.get('contact', '')).strip()
    
    if 'email' in request.form and request.form.get('email').strip():
        team['email'] = request.form.get('email').strip().lower()
    if 'username' in request.form and request.form.get('username').strip():
        team['username'] = request.form.get('username').strip().lower()
    if 'password' in request.form and request.form.get('password').strip():
        team['password'] = request.form.get('password').strip()

    if 'initial_budget' in request.form:
        try:
            new_initial = int(request.form.get('initial_budget'))
            spent = team.get('spent', 0)
            team['initial_budget'] = new_initial
            team['balance'] = max(0, new_initial - spent)
        except ValueError:
            pass

    if 'logo' in request.files:
        file = request.files['logo']
        if file and file.filename and allowed_file(file.filename):
            filename = f"team_{uuid.uuid4().hex[:8]}_{secure_filename(file.filename)}"
            file.save(os.path.join(config.UPLOAD_DIR, filename))
            team['logo'] = f"/static/uploads/{filename}"

    database.save_teams(teams)
    database.log_audit_event("FRANCHISE_UPDATED", user="Admin", role="admin", team_name=name, details=f"Franchise '{name}' details updated.")
    return jsonify({"success": True, "team": team, "message": f"Team '{name}' updated successfully!"})

@app.route('/api/teams/<team_id>', methods=['DELETE'])
@api_role_required('admin')
def api_delete_team(team_id):
    teams = database.get_teams()
    team = next((t for t in teams if t["id"] == team_id), None)
    if not team:
        return jsonify({"success": False, "message": "Team not found"}), 404
        
    if team.get("squad") and len(team["squad"]) > 0:
        return jsonify({
            "success": False,
            "message": f"Cannot delete '{team['name']}' because it has {len(team['squad'])} purchased players. Re-assign or reset players first."
        }), 400

    teams = [t for t in teams if t["id"] != team_id]
    database.save_teams(teams)
    database.log_audit_event("FRANCHISE_DELETED", user="Admin", role="admin", team_name=team['name'])
    return jsonify({"success": True, "message": f"Team '{team['name']}' deleted."})

# ----------------- PLAYERS API -----------------

@app.route('/api/players', methods=['GET'])
def api_get_players():
    players = database.get_players()
    status_filter = request.args.get('status')
    role_filter = request.args.get('role')
    search_query = request.args.get('q', '').lower()

    if status_filter:
        if status_filter == 'SECOND_CHANCE':
            players = [p for p in players if p.get('second_chance') or p.get('status') in ['UNSOLD', 'UNSOLD_POOL']]
        else:
            players = [p for p in players if p.get('status') == status_filter]
            
    if role_filter:
        players = [p for p in players if p.get('role') == role_filter]
        
    if search_query:
        players = [
            p for p in players if (
                search_query in p.get('name', '').lower() or
                search_query in p.get('roll_no', '').lower() or
                search_query in p.get('role', '').lower() or
                search_query in p.get('year', '').lower()
            )
        ]

    return jsonify({"success": True, "count": len(players), "players": players})

@app.route('/api/players', methods=['POST'])
@api_role_required('admin')
def api_create_player():
    name = request.form.get('name', '').strip()
    if not name:
        return jsonify({"success": False, "message": "Player name is required"}), 400

    photo_url = ""
    if 'photo' in request.files:
        file = request.files['photo']
        if file and file.filename and allowed_file(file.filename):
            filename = f"player_{uuid.uuid4().hex[:8]}_{secure_filename(file.filename)}"
            file.save(os.path.join(config.UPLOAD_DIR, filename))
            photo_url = f"/static/uploads/{filename}"

    try:
        base_price = int(request.form.get('base_price', config.DEFAULT_BASE_PRICE))
    except ValueError:
        base_price = config.DEFAULT_BASE_PRICE

    def parse_num(field, default=0, is_float=False):
        val = request.form.get(field, default)
        try:
            return float(val) if is_float else int(float(val))
        except (ValueError, TypeError):
            return default

    new_player = {
        "id": f"ply_{uuid.uuid4().hex[:8]}",
        "name": name,
        "roll_no": request.form.get('roll_no', f"SPL-{int(datetime.now().timestamp())}").strip(),
        "year": request.form.get('year', '1st Year').strip(),
        "role": request.form.get('role', 'All-Rounder').strip(),
        "base_price": base_price,
        "status": "AVAILABLE",
        "photo": photo_url,
        "sold_price": 0,
        "sold_team_id": None,
        "sold_team_name": None,
        "batting": {
            "matches": parse_num('matches', 0),
            "runs": parse_num('runs', 0),
            "strike_rate": parse_num('strike_rate', 0.0, is_float=True),
            "fifties": parse_num('fifties', 0),
            "hundreds": parse_num('hundreds', 0),
            "fours": parse_num('fours', 0),
            "sixes": parse_num('sixes', 0)
        },
        "bowling": {
            "wickets": parse_num('wickets', 0),
            "economy": parse_num('economy', 0.0, is_float=True)
        },
        "fielding": {
            "catches": parse_num('catches', 0),
            "runouts": parse_num('runouts', 0)
        }
    }

    players = database.get_players()
    players.append(new_player)
    database.save_players(players)
    database.log_audit_event("PLAYER_CREATED", user="Admin", role="admin", player_name=name, details=f"Added '{name}' (Roll No: {new_player['roll_no']}).")
    return jsonify({"success": True, "player": new_player, "message": f"Player '{name}' added successfully!"})

@app.route('/api/players/<player_id>', methods=['PUT', 'POST'])
@api_role_required('admin')
def api_update_player(player_id):
    players = database.get_players()
    player = next((p for p in players if p["id"] == player_id), None)
    if not player:
        return jsonify({"success": False, "message": "Player not found"}), 404

    name = request.form.get('name', player['name']).strip()
    player['name'] = name
    player['roll_no'] = request.form.get('roll_no', player.get('roll_no', '')).strip()
    player['year'] = request.form.get('year', player.get('year', '')).strip()
    player['role'] = request.form.get('role', player.get('role', 'All-Rounder')).strip()
    
    if 'base_price' in request.form:
        try:
            player['base_price'] = int(request.form.get('base_price'))
        except ValueError:
            pass

    if 'status' in request.form:
        player['status'] = request.form.get('status')

    if 'photo' in request.files:
        file = request.files['photo']
        if file and file.filename and allowed_file(file.filename):
            filename = f"player_{uuid.uuid4().hex[:8]}_{secure_filename(file.filename)}"
            file.save(os.path.join(config.UPLOAD_DIR, filename))
            player['photo'] = f"/static/uploads/{filename}"

    def parse_num(field, default=0, is_float=False):
        val = request.form.get(field, default)
        try:
            return float(val) if is_float else int(float(val))
        except (ValueError, TypeError):
            return default

    if 'runs' in request.form or 'matches' in request.form:
        player['batting'] = {
            "matches": parse_num('matches', player.get('batting', {}).get('matches', 0)),
            "runs": parse_num('runs', player.get('batting', {}).get('runs', 0)),
            "strike_rate": parse_num('strike_rate', player.get('batting', {}).get('strike_rate', 0.0), is_float=True),
            "fifties": parse_num('fifties', player.get('batting', {}).get('fifties', 0)),
            "hundreds": parse_num('hundreds', player.get('batting', {}).get('hundreds', 0)),
            "fours": parse_num('fours', player.get('batting', {}).get('fours', 0)),
            "sixes": parse_num('sixes', player.get('batting', {}).get('sixes', 0))
        }
        player['bowling'] = {
            "wickets": parse_num('wickets', player.get('bowling', {}).get('wickets', 0)),
            "economy": parse_num('economy', player.get('bowling', {}).get('economy', 0.0), is_float=True)
        }
        player['fielding'] = {
            "catches": parse_num('catches', player.get('fielding', {}).get('catches', 0)),
            "runouts": parse_num('runouts', player.get('fielding', {}).get('runouts', 0))
        }

    database.save_players(players)
    database.log_audit_event("PLAYER_UPDATED", user="Admin", role="admin", player_name=name)
    return jsonify({"success": True, "player": player, "message": f"Player '{name}' updated successfully!"})

@app.route('/api/players/<player_id>', methods=['DELETE'])
@api_role_required('admin')
def api_delete_player(player_id):
    players = database.get_players()
    player = next((p for p in players if p["id"] == player_id), None)
    if not player:
        return jsonify({"success": False, "message": "Player not found"}), 404

    if player.get("sold_team_id"):
        teams = database.get_teams()
        for t in teams:
            if t["id"] == player["sold_team_id"]:
                t["squad"] = [sq for sq in t.get("squad", []) if sq["id"] != player_id]
                t["spent"] = sum(sq.get("bought_for", 0) for sq in t["squad"])
                t["balance"] = max(0, t.get("initial_budget", config.DEFAULT_PURSE) - t["spent"])
        database.save_teams(teams)

    players = [p for p in players if p["id"] != player_id]
    database.save_players(players)
    database.log_audit_event("PLAYER_DELETED", user="Admin", role="admin", player_name=player['name'])
    return jsonify({"success": True, "message": f"Player '{player['name']}' deleted."})

# ----------------- EXCEL IMPORT & TEMPLATE -----------------

@app.route('/api/players/import', methods=['POST'])
@api_role_required('admin')
def api_import_players():
    if 'file' not in request.files:
        return jsonify({"success": False, "message": "No file uploaded"}), 400
    file = request.files['file']
    if not file or not file.filename:
        return jsonify({"success": False, "message": "No file selected"}), 400

    result = ExcelService.import_players_from_file(file)
    status_code = 200 if result.get('success') else 400
    if result.get('success'):
        database.log_audit_event("PLAYERS_IMPORTED", user="Admin", role="admin", details=f"Imported {result.get('added_count', 0)} added, {result.get('updated_count', 0)} updated.")
    return jsonify(result), status_code

@app.route('/api/players/sample-template', methods=['GET'])
def api_download_sample_template():
    buffer = ExcelService.generate_sample_excel_buffer()
    return send_file(
        buffer,
        as_attachment=True,
        download_name='spl_players_template.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

# ----------------- STUDENT VERIFICATION & APPROVAL API -----------------

@app.route('/api/admin/students', methods=['GET'])
@api_role_required('admin')
def api_admin_get_students():
    data = database.get_student_registrations()
    return jsonify({"success": True, **data})

@app.route('/api/admin/students/approve', methods=['POST'])
@api_role_required('admin')
def api_admin_approve_student():
    data = request.get_json() or {}
    roll_no = data.get('roll_no', '').strip()
    if not roll_no:
        return jsonify({"success": False, "message": "Roll Number is required."}), 400
    user = session.get('user', {})
    res = database.approve_student(roll_no, user=user.get('username', 'Admin'))
    if res.get('success'):
        events.broadcast('student_verification_updated', {
            'action': 'APPROVED',
            'roll_no': roll_no,
            'student': res.get('student')
        })
    status_code = 200 if res.get('success') else 400
    return jsonify(res), status_code

@app.route('/api/admin/students/reject', methods=['POST'])
@api_role_required('admin')
def api_admin_reject_student():
    data = request.get_json() or {}
    roll_no = data.get('roll_no', '').strip()
    reason = data.get('reason', '').strip()
    if not roll_no:
        return jsonify({"success": False, "message": "Roll Number is required."}), 400
    user = session.get('user', {})
    res = database.reject_student(roll_no, reason=reason, user=user.get('username', 'Admin'))
    if res.get('success'):
        events.broadcast('student_verification_updated', {
            'action': 'REJECTED',
            'roll_no': roll_no,
            'student': res.get('student')
        })
    status_code = 200 if res.get('success') else 400
    return jsonify(res), status_code

@app.route('/api/admin/students/reset', methods=['POST'])
@api_role_required('admin')
def api_admin_reset_student():
    data = request.get_json() or {}
    roll_no = data.get('roll_no', '').strip()
    if not roll_no:
        return jsonify({"success": False, "message": "Roll Number is required."}), 400
    user = session.get('user', {})
    res = database.reset_student_approval(roll_no, user=user.get('username', 'Admin'))
    if res.get('success'):
        events.broadcast('student_verification_updated', {
            'action': 'RESET',
            'roll_no': roll_no,
            'student': res.get('student')
        })
    status_code = 200 if res.get('success') else 400
    return jsonify(res), status_code

@app.route('/api/admin/students/approve-all', methods=['POST'])
@api_role_required('admin')
def api_admin_approve_all_students():
    user = session.get('user', {})
    res = database.approve_all_pending_students(user=user.get('username', 'Admin'))
    if res.get('success'):
        events.broadcast('student_verification_updated', {
            'action': 'APPROVED_ALL',
            'count': res.get('count')
        })
    return jsonify(res)

# ----------------- AUDIT LOGS & STATS -----------------

@app.route('/api/audit-logs', methods=['GET'])
@api_role_required('admin')
def api_get_audit_logs():
    logs = database.get_audit_logs()
    return jsonify({"success": True, "count": len(logs), "logs": list(reversed(logs))})

@app.route('/api/admin/stats', methods=['GET'])
def api_get_admin_stats():
    return jsonify(StatsService.get_dashboard_stats())

@app.route('/api/auction/history', methods=['GET'])
def api_get_auction_history():
    bids = database.get_bids()
    players = database.get_players()
    sold_players = [p for p in players if p.get("status") == "SOLD"]
    unsold_players = [p for p in players if p.get("status") == "UNSOLD"]
    return jsonify({
        "success": True,
        "total_bids": len(bids),
        "bids": list(reversed(bids)),
        "sold_players": sold_players,
        "unsold_players": unsold_players
    })

@app.route('/api/admin/reset-auction', methods=['POST'])
@api_role_required('admin')
def api_admin_reset_auction():
    data = request.get_json() or {}
    reset_type = data.get('type', 'state_only')

    if reset_type == 'full_reset':
        players = database.get_players()
        for p in players:
            p['status'] = 'AVAILABLE'
            p['sold_price'] = 0
            p['sold_team_id'] = None
            p['sold_team_name'] = None
            if 'second_chance' in p:
                del p['second_chance']
        database.save_players(players)

        teams = database.get_teams()
        for t in teams:
            t['balance'] = t.get('initial_budget', config.DEFAULT_PURSE)
            t['spent'] = 0
            t['squad'] = []
        database.save_teams(teams)

        database.save_bids([])
        database.log_audit_event("FULL_AUCTION_RESET", user="Admin", role="admin", details="All teams, budgets, squads and players reset.")

    AuctionEngine.reset_auction_state(user="Admin")

    return jsonify({
        "success": True,
        "message": "Full auction data and team budgets have been reset to initial state!" if reset_type == 'full_reset' else "Active player state reset."
    })

@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    if request.method == 'POST':
        user = session.get('user')
        if not user or user.get('role') != 'admin':
            return jsonify({"success": False, "message": "Admin privileges required"}), 403
        data = request.get_json() or {}
        database.save_settings(data)
        database.log_audit_event("SETTINGS_UPDATED", user="Admin", role="admin", details="Auction configuration updated.")
        return jsonify({"success": True, "settings": data, "message": "Settings updated successfully."})
    return jsonify({"success": True, "settings": database.get_settings()})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5005))
    app.run(host='0.0.0.0', port=port, debug=config.DEBUG)
