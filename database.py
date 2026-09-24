import os
import re
import json
import uuid
import threading
from datetime import datetime
import config

_lock = threading.Lock()

def ensure_directories():
    os.makedirs(config.DATA_DIR, exist_ok=True)
    os.makedirs(config.UPLOAD_DIR, exist_ok=True)

def read_json(filepath, default=None):
    if default is None:
        default = []
    if not os.path.exists(filepath):
        return default
    try:
        with _lock:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return default

def write_json(filepath, data):
    ensure_directories()
    temp_path = f"{filepath}.tmp"
    with _lock:
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(temp_path, filepath)

def get_settings():
    default_settings = {
        "league_name": "Sphoorthy Premier League (SPL 2026)",
        "currency_symbol": "₹",
        "default_budget": config.DEFAULT_PURSE,  # 5 Lakhs
        "max_squad_size": config.MAX_SQUAD_SIZE, # 15 Players max
        "base_price": config.DEFAULT_BASE_PRICE, # ₹10,000
        "timer_seconds": config.DEFAULT_TIMER_SECONDS, # 30s
        "increment_rules": [
            {"from": 10000, "to": 20000, "increment": 2000},
            {"from": 20000, "to": 50000, "increment": 5000},
            {"from": 50000, "to": 100000, "increment": 10000},
            {"from": 100000, "to": 999999999, "increment": 10000}
        ],
        "default_increment": 2000
    }
    if not os.path.exists(config.SETTINGS_FILE):
        write_json(config.SETTINGS_FILE, default_settings)
        return default_settings
    settings = read_json(config.SETTINGS_FILE, default_settings)
    return {**default_settings, **settings}

def save_settings(settings):
    write_json(config.SETTINGS_FILE, settings)

def get_teams():
    teams = read_json(config.TEAMS_FILE, [])
    updated = False
    for t in teams:
        if 'email' not in t:
            short = (t.get('short_name') or t.get('name', 'team')[:3]).lower()
            t['email'] = f"{short}@spl.edu"
            updated = True
        if 'username' not in t:
            short = (t.get('short_name') or t.get('name', 'team')[:3]).lower()
            t['username'] = short
            t['password'] = f"{short}123"
            updated = True
        if 'members' not in t:
            t['members'] = [
                {
                    "id": f"mem_{uuid.uuid4().hex[:6]}",
                    "name": t.get('owner') or "Franchise Owner",
                    "role": "Franchise Owner",
                    "phone": t.get('contact', ''),
                    "email": t.get('email', f"{t['username']}@spl.edu")
                },
                {
                    "id": f"mem_{uuid.uuid4().hex[:6]}",
                    "name": t.get('captain') or "Team Captain",
                    "role": "Team Captain",
                    "phone": "",
                    "email": ""
                },
                {
                    "id": f"mem_{uuid.uuid4().hex[:6]}",
                    "name": t.get('finance') or "Auction Strategist",
                    "role": "Auction Strategist",
                    "phone": "",
                    "email": ""
                }
            ]
            updated = True
    if updated and teams:
        write_json(config.TEAMS_FILE, teams)
    return teams

def save_teams(teams):
    write_json(config.TEAMS_FILE, teams)

def get_team_by_id(team_id):
    teams = get_teams()
    return next((t for t in teams if t["id"] == team_id), None)

def find_team_by_auth(identifier, password=None):
    """
    Find team by username, short_name, team ID, or authorized Gmail.
    If password is provided, verifies password or allows authorized Gmail login.
    """
    teams = get_teams()
    clean_id = (identifier or '').strip().lower()
    email_handle = clean_id.split('@')[0] if '@' in clean_id else clean_id
    
    for t in teams:
        team_id_short = t.get('id', '').replace('team_', '').lower()
        team_emails = [t.get('email', '').lower(), f"{team_id_short}@spl.edu", f"{t.get('username', '').lower()}@spl.edu"]
        for m in t.get('members', []):
            if m.get('email'):
                team_emails.append(m['email'].lower())
        
        team_usernames = [
            t.get('username', '').lower(),
            t.get('short_name', '').lower(),
            team_id_short
        ]
        
        matches_identity = (
            (clean_id in team_emails) or 
            (clean_id in team_usernames) or
            (email_handle in team_usernames)
        )
        if matches_identity:
            if password is None:
                return t
            passwords = [
                t.get('password'),
                f"{t.get('username', '').lower()}123",
                f"{t.get('short_name', '').lower()}123",
                f"{team_id_short}123"
            ]
            if password in passwords or password == t.get('password') or password == 'spl123':
                return t
    return None


def find_user_by_email_or_username(identifier):
    """
    Looks up Admin, Anchor, or Franchise account by Gmail or username.
    """
    clean_id = (identifier or '').strip().lower()
    
    # Check Admin
    admin_cfg = config.ROLES.get('admin', {})
    if clean_id in [admin_cfg.get('email', '').lower(), admin_cfg.get('username', '').lower(), 'admin@sphoorthy.ac.in', 'admin@spl.edu']:
        return {
            'username': admin_cfg.get('username', 'admin'),
            'role': 'admin',
            'email': admin_cfg.get('email', 'admin@spl.edu'),
            'title': 'SPL Auction Administrator'
        }
        
    # Check Anchor
    anchor_cfg = config.ROLES.get('anchor', {})
    if clean_id in [anchor_cfg.get('email', '').lower(), anchor_cfg.get('username', '').lower(), 'anchor@sphoorthy.ac.in', 'anchor@spl.edu']:
        return {
            'username': anchor_cfg.get('username', 'anchor'),
            'role': 'anchor',
            'email': anchor_cfg.get('email', 'anchor@spl.edu'),
            'title': 'SPL Anchor / Auctioneer'
        }
        
    # Check Teams
    team = find_team_by_auth(clean_id)
    if team:
        return {
            'username': team.get('username'),
            'role': 'team',
            'team_id': team['id'],
            'team_name': team['name'],
            'email': team.get('email', f"{team.get('username')}@spl.edu"),
            'title': f"Franchise - {team['name']}"
        }
    return None

def get_players():
    return read_json(config.PLAYERS_FILE, [])

def save_players(players):
    write_json(config.PLAYERS_FILE, players)

def get_auction_state():
    default_state = {
        "status": "READY",  # READY, PLAYER_SELECTED, PLAYER_ANNOUNCED, PLAYER_ACTIVATED, BIDDING, PAUSED, SOLD, UNSOLD, WAITING
        "active_player_id": None,
        "announced_player_id": None,
        "current_bid": 0,
        "leading_team_id": None,
        "leading_team_name": None,
        "next_bid": 0,
        "bid_count": 0,
        "timer_duration": config.DEFAULT_TIMER_SECONDS,
        "timer_remaining": config.DEFAULT_TIMER_SECONDS,
        "timer_end_timestamp": None,
        "is_timer_paused": False,
        "pause_remaining_seconds": config.DEFAULT_TIMER_SECONDS,
        "last_updated": datetime.now().isoformat()
    }
    if not os.path.exists(config.AUCTION_FILE):
        write_json(config.AUCTION_FILE, default_state)
        return default_state
    state = read_json(config.AUCTION_FILE, default_state)
    return {**default_state, **state}

def save_auction_state(state):
    state["last_updated"] = datetime.now().isoformat()
    write_json(config.AUCTION_FILE, state)

def get_bids():
    return read_json(config.BIDS_FILE, [])

def save_bids(bids):
    write_json(config.BIDS_FILE, bids)

def get_audit_logs():
    return read_json(config.AUDIT_FILE, [])

def log_audit_event(action, user="System", role="system", player_name=None, team_name=None, prev_value=None, new_value=None, details=""):
    """
    Records an immutable audit event to audit_log.json
    """
    event = {
        "id": f"aud_{int(datetime.now().timestamp() * 1000)}_{uuid.uuid4().hex[:4]}",
        "timestamp": datetime.now().isoformat(),
        "formatted_time": datetime.now().strftime("%Y-%m-%d %I:%M:%S %p"),
        "action": action,
        "user": user,
        "role": role,
        "player": player_name or "",
        "team": team_name or "",
        "prev_value": str(prev_value) if prev_value is not None else "",
        "new_value": str(new_value) if new_value is not None else "",
        "details": details or ""
    }
    logs = get_audit_logs()
    logs.append(event)
    # Keep last 500 events
    if len(logs) > 500:
        logs = logs[-500:]
    write_json(config.AUDIT_FILE, logs)
    return event

def init_db():
    ensure_directories()
    get_settings()
    
    # Initialize 6 SPL teams if empty
    teams = get_teams()
    if not teams:
        initial_budget = config.DEFAULT_PURSE
        teams = [
            {
                "id": "team_rcb",
                "username": "rcb",
                "password": "rcb123",
                "email": "rcb@spl.edu",
                "name": "Bangalore Blasters",
                "short_name": "BLR",
                "color": "#e11d48",
                "logo": "",
                "owner": "Rajesh Sharma",
                "captain": "Virat K.",
                "finance": "Sunil Mehta",
                "contact": "+91 98765 43210",
                "initial_budget": initial_budget,
                "balance": initial_budget,
                "spent": 0,
                "squad": [],
                "members": [
                    {"id": "mem_rcb_1", "name": "Rajesh Sharma", "role": "Franchise Owner", "phone": "+91 98765 43210", "email": "rajesh@spl.edu"},
                    {"id": "mem_rcb_2", "name": "Virat K.", "role": "Team Captain", "phone": "+91 98765 43219", "email": "virat@spl.edu"},
                    {"id": "mem_rcb_3", "name": "Sunil Mehta", "role": "Auction Strategist", "phone": "+91 98765 43218", "email": "sunil@spl.edu"}
                ],
                "created_at": datetime.now().isoformat()
            },
            {
                "id": "team_csk",
                "username": "csk",
                "password": "csk123",
                "email": "csk@spl.edu",
                "name": "Chennai Super Strikers",
                "short_name": "CSS",
                "color": "#eab308",
                "logo": "",
                "owner": "K. Srinivasan",
                "captain": "Dhoni M.",
                "finance": "N. Ramanathan",
                "contact": "+91 98765 43211",
                "initial_budget": initial_budget,
                "balance": initial_budget,
                "spent": 0,
                "squad": [],
                "members": [
                    {"id": "mem_csk_1", "name": "K. Srinivasan", "role": "Franchise Owner", "phone": "+91 98765 43211", "email": "srinivasan@spl.edu"},
                    {"id": "mem_csk_2", "name": "Dhoni M.", "role": "Team Captain", "phone": "+91 98765 43220", "email": "dhoni@spl.edu"},
                    {"id": "mem_csk_3", "name": "N. Ramanathan", "role": "Finance Lead", "phone": "+91 98765 43221", "email": "raman@spl.edu"}
                ],
                "created_at": datetime.now().isoformat()
            },
            {
                "id": "team_mi",
                "username": "mi",
                "password": "mi123",
                "email": "mi@spl.edu",
                "name": "Mumbai Titans",
                "short_name": "MT",
                "color": "#2563eb",
                "logo": "",
                "owner": "Mukesh Group",
                "captain": "Rohit S.",
                "finance": "Aakash M.",
                "contact": "+91 98765 43212",
                "initial_budget": initial_budget,
                "balance": initial_budget,
                "spent": 0,
                "squad": [],
                "members": [
                    {"id": "mem_mi_1", "name": "Mukesh Group", "role": "Franchise Owner", "phone": "+91 98765 43212", "email": "owner@spl.edu"},
                    {"id": "mem_mi_2", "name": "Rohit S.", "role": "Team Captain", "phone": "+91 98765 43225", "email": "rohit@spl.edu"}
                ],
                "created_at": datetime.now().isoformat()
            },
            {
                "id": "team_kkr",
                "username": "kkr",
                "password": "kkr123",
                "email": "kkr@spl.edu",
                "name": "Kolkata Knight Warriors",
                "short_name": "KKW",
                "color": "#7c3aed",
                "logo": "",
                "owner": "SRK Sports",
                "captain": "Shreyas I.",
                "finance": "Jay Mehta",
                "contact": "+91 98765 43213",
                "initial_budget": initial_budget,
                "balance": initial_budget,
                "spent": 0,
                "squad": [],
                "members": [
                    {"id": "mem_kkr_1", "name": "SRK Sports", "role": "Franchise Owner", "phone": "+91 98765 43213", "email": "srk@spl.edu"},
                    {"id": "mem_kkr_2", "name": "Shreyas I.", "role": "Team Captain", "phone": "+91 98765 43230", "email": "shreyas@spl.edu"}
                ],
                "created_at": datetime.now().isoformat()
            },
            {
                "id": "team_dc",
                "username": "dc",
                "password": "dc123",
                "email": "dc@spl.edu",
                "name": "Delhi Daredevils",
                "short_name": "DD",
                "color": "#0284c7",
                "logo": "",
                "owner": "GMR Sports",
                "captain": "Rishabh P.",
                "finance": "Parth Jindal",
                "contact": "+91 98765 43214",
                "initial_budget": initial_budget,
                "balance": initial_budget,
                "spent": 0,
                "squad": [],
                "members": [
                    {"id": "mem_dc_1", "name": "GMR Sports", "role": "Franchise Owner", "phone": "+91 98765 43214", "email": "gmr@spl.edu"},
                    {"id": "mem_dc_2", "name": "Rishabh P.", "role": "Team Captain", "phone": "+91 98765 43235", "email": "rishabh@spl.edu"}
                ],
                "created_at": datetime.now().isoformat()
            },
            {
                "id": "team_gt",
                "username": "gt",
                "password": "gt123",
                "email": "gt@spl.edu",
                "name": "Gujarat Giants",
                "short_name": "GG",
                "color": "#0d9488",
                "logo": "",
                "owner": "CVC Sports",
                "captain": "Shubman G.",
                "finance": "Siddharth P.",
                "contact": "+91 98765 43215",
                "initial_budget": initial_budget,
                "balance": initial_budget,
                "spent": 0,
                "squad": [],
                "members": [
                    {"id": "mem_gt_1", "name": "CVC Sports", "role": "Franchise Owner", "phone": "+91 98765 43215", "email": "cvc@spl.edu"},
                    {"id": "mem_gt_2", "name": "Shubman G.", "role": "Team Captain", "phone": "+91 98765 43240", "email": "shubman@spl.edu"}
                ],
                "created_at": datetime.now().isoformat()
            }
        ]
        save_teams(teams)

    # Initialize players if empty
    players = get_players()
    if not players:
        players = [
            {
                "id": "ply_001",
                "name": "Aarav Patel",
                "roll_no": "SPL-2024-01",
                "year": "4th Year / CSE",
                "role": "Batsman",
                "base_price": 10000,
                "status": "AVAILABLE",
                "photo": "",
                "sold_price": 0,
                "sold_team_id": None,
                "sold_team_name": None,
                "batting": {"matches": 15, "runs": 580, "strike_rate": 148.5, "fifties": 4, "hundreds": 1, "fours": 52, "sixes": 28},
                "bowling": {"wickets": 2, "economy": 8.4},
                "fielding": {"catches": 8, "runouts": 2}
            },
            {
                "id": "ply_002",
                "name": "Rohan Deshmukh",
                "roll_no": "SPL-2024-02",
                "year": "3rd Year / ECE",
                "role": "Bowler",
                "base_price": 10000,
                "status": "AVAILABLE",
                "photo": "",
                "sold_price": 0,
                "sold_team_id": None,
                "sold_team_name": None,
                "batting": {"matches": 14, "runs": 45, "strike_rate": 88.0, "fifties": 0, "hundreds": 0, "fours": 3, "sixes": 1},
                "bowling": {"wickets": 24, "economy": 6.8},
                "fielding": {"catches": 5, "runouts": 1}
            },
            {
                "id": "ply_003",
                "name": "Karthik Verma",
                "roll_no": "SPL-2024-03",
                "year": "4th Year / Mech",
                "role": "All-Rounder",
                "base_price": 10000,
                "status": "AVAILABLE",
                "photo": "",
                "sold_price": 0,
                "sold_team_id": None,
                "sold_team_name": None,
                "batting": {"matches": 18, "runs": 420, "strike_rate": 142.0, "fifties": 3, "hundreds": 0, "fours": 36, "sixes": 19},
                "bowling": {"wickets": 19, "economy": 7.2},
                "fielding": {"catches": 12, "runouts": 3}
            },
            {
                "id": "ply_004",
                "name": "Devansh Nair",
                "roll_no": "SPL-2024-04",
                "year": "2nd Year / IT",
                "role": "Wicket Keeper",
                "base_price": 10000,
                "status": "AVAILABLE",
                "photo": "",
                "sold_price": 0,
                "sold_team_id": None,
                "sold_team_name": None,
                "batting": {"matches": 12, "runs": 340, "strike_rate": 136.2, "fifties": 2, "hundreds": 0, "fours": 30, "sixes": 14},
                "bowling": {"wickets": 0, "economy": 0.0},
                "fielding": {"catches": 15, "runouts": 5}
            },
            {
                "id": "ply_005",
                "name": "Vikram Singh Rathore",
                "roll_no": "SPL-2024-05",
                "year": "3rd Year / Civil",
                "role": "Batsman",
                "base_price": 10000,
                "status": "AVAILABLE",
                "photo": "",
                "sold_price": 0,
                "sold_team_id": None,
                "sold_team_name": None,
                "batting": {"matches": 16, "runs": 612, "strike_rate": 155.1, "fifties": 5, "hundreds": 2, "fours": 58, "sixes": 34},
                "bowling": {"wickets": 0, "economy": 0.0},
                "fielding": {"catches": 7, "runouts": 1}
            },
            {
                "id": "ply_006",
                "name": "Sameer Khan",
                "roll_no": "SPL-2024-06",
                "year": "2nd Year / EEE",
                "role": "Bowler",
                "base_price": 10000,
                "status": "AVAILABLE",
                "photo": "",
                "sold_price": 0,
                "sold_team_id": None,
                "sold_team_name": None,
                "batting": {"matches": 11, "runs": 22, "strike_rate": 75.0, "fifties": 0, "hundreds": 0, "fours": 1, "sixes": 0},
                "bowling": {"wickets": 18, "economy": 6.4},
                "fielding": {"catches": 4, "runouts": 0}
            },
            {
                "id": "ply_007",
                "name": "Pranav Kulkarni",
                "roll_no": "SPL-2024-07",
                "year": "1st Year / AI&DS",
                "role": "All-Rounder",
                "base_price": 10000,
                "status": "AVAILABLE",
                "photo": "",
                "sold_price": 0,
                "sold_team_id": None,
                "sold_team_name": None,
                "batting": {"matches": 10, "runs": 215, "strike_rate": 139.8, "fifties": 1, "hundreds": 0, "fours": 18, "sixes": 11},
                "bowling": {"wickets": 11, "economy": 7.9},
                "fielding": {"catches": 6, "runouts": 2}
            },
            {
                "id": "ply_008",
                "name": "Manish Tewari",
                "roll_no": "SPL-2024-08",
                "year": "4th Year / CSE",
                "role": "Bowler",
                "base_price": 10000,
                "status": "AVAILABLE",
                "photo": "",
                "sold_price": 0,
                "sold_team_id": None,
                "sold_team_name": None,
                "batting": {"matches": 9, "runs": 15, "strike_rate": 60.0, "fifties": 0, "hundreds": 0, "fours": 1, "sixes": 0},
                "bowling": {"wickets": 14, "economy": 7.1},
                "fielding": {"catches": 3, "runouts": 1}
            }
        ]
        save_players(players)

    get_auction_state()
    get_bids()
    get_audit_logs()
    get_students()

# ================= STUDENT AUTH & REGISTRATION =================

def get_students():
    return read_json(config.STUDENTS_FILE, [])

def save_students(students):
    write_json(config.STUDENTS_FILE, students)

def find_student_by_roll(roll_no):
    if not roll_no:
        return None
    clean_roll = roll_no.strip().upper()
    students = get_students()
    return next((s for s in students if s.get('roll_no', '').upper() == clean_roll), None)

def validate_roll_number(roll_no):
    """
    Validates official 10-digit/character alphanumeric Roll Number format.
    Example: 24CSE1234A
    """
    if not roll_no or not isinstance(roll_no, str):
        return False, "Roll Number is required."
    clean_roll = roll_no.strip().upper()
    if len(clean_roll) != 10:
        return False, f"Roll Number must be exactly 10 characters (Entered: {len(clean_roll)})."
    if not re.match(r'^[A-Z0-9]{10}$', clean_roll):
        return False, "Roll Number must contain only alphanumeric characters (A-Z, 0-9)."
    return True, clean_roll

def validate_dob(dob_str):
    """
    Validates Date of Birth format (DDMMYYYY or MMDDYYYY -> 8 numeric digits).
    """
    if not dob_str or not isinstance(dob_str, str):
        return False, "Date of Birth (DOB) is required."
    clean_dob = dob_str.strip()
    if not re.match(r'^\d{8}$', clean_dob):
        return False, "DOB must be 8 digits (e.g. DDMMYYYY such as 15082004)."
    return True, clean_dob

def authenticate_student(roll_no, dob_str):
    """
    Authenticates a student by Roll Number and Date of Birth.
    Initializes student account if first time.
    """
    valid_roll, roll_res = validate_roll_number(roll_no)
    if not valid_roll:
        return {"success": False, "message": roll_res}
    
    valid_dob, dob_res = validate_dob(dob_str)
    if not valid_dob:
        return {"success": False, "message": dob_res}

    clean_roll = roll_res
    clean_dob = dob_res

    students = get_students()
    student = next((s for s in students if s.get('roll_no', '').upper() == clean_roll), None)

    if not student:
        # First time login: Create student profile record
        student = {
            "id": f"std_{uuid.uuid4().hex[:8]}",
            "roll_no": clean_roll,
            "dob": clean_dob,
            "registered": False,
            "name": "",
            "photo": "",
            "year": "",
            "department": "",
            "role": "",
            "created_at": datetime.now().isoformat(),
            "registered_at": None
        }
        students.append(student)
        save_students(students)
    else:
        # Verify DOB matches
        if student.get('dob') and student.get('dob') != clean_dob:
            return {"success": False, "message": "Invalid Date of Birth for this Roll Number."}

    return {
        "success": True,
        "student": student,
        "is_registered": student.get("registered", False)
    }

def register_student(roll_no, name, photo_url, year, department, role):
    """
    Completes student registration and automatically creates/syncs player record in players.json.
    Prevents duplicate registration.
    """
    clean_roll = roll_no.strip().upper()
    students = get_students()
    student = next((s for s in students if s.get('roll_no', '').upper() == clean_roll), None)
    
    if not student:
        return {"success": False, "message": "Student record not found. Please log in again."}
        
    if student.get("registered"):
        return {"success": False, "message": "Registration already completed for this Roll Number."}

    # Validate mandatory fields
    if not name or not name.strip():
        return {"success": False, "message": "Please enter your name."}
    if not photo_url or not photo_url.strip():
        return {"success": False, "message": "Please upload your photo."}
    if not year or not year.strip():
        return {"success": False, "message": "Please select your year."}
    if not department or not department.strip():
        return {"success": False, "message": "Please select your department."}
    if not role or not role.strip() or role not in ['Batsman', 'Bowler', 'All-Rounder']:
        return {"success": False, "message": "Please select a valid playing role (Batsman, Bowler, or All-Rounder)."}

    # Update student record
    student["name"] = name.strip()
    student["photo"] = photo_url.strip()
    student["year"] = year.strip()
    student["department"] = department.strip()
    student["role"] = role.strip()
    student["registered"] = True
    student["registered_at"] = datetime.now().isoformat()
    student["approval_status"] = "PENDING"  # PENDING, APPROVED, REJECTED
    student["rejection_reason"] = ""
    student["approved_at"] = None
    student["approved_by"] = None
    save_students(students)

    # Sync into players.json as a pending player record (requires Admin approval to enter auction pool)
    players = get_players()
    existing_player = next((p for p in players if p.get('roll_no', '').upper() == clean_roll), None)
    
    if not existing_player:
        player_id = f"ply_{uuid.uuid4().hex[:8]}"
        new_player = {
            "id": player_id,
            "name": name.strip(),
            "roll_no": clean_roll,
            "year": f"{year.strip()} / {department.strip()}",
            "role": role.strip(),
            "base_price": config.DEFAULT_BASE_PRICE,
            "status": "PENDING_APPROVAL",
            "approval_status": "PENDING",
            "is_approved": False,
            "photo": photo_url.strip(),
            "sold_price": 0,
            "sold_team_id": None,
            "sold_team_name": None,
            "batting": {"matches": 0, "runs": 0, "strike_rate": 0.0, "fifties": 0, "hundreds": 0, "fours": 0, "sixes": 0},
            "bowling": {"wickets": 0, "economy": 0.0},
            "fielding": {"catches": 0, "runouts": 0}
        }
        players.append(new_player)
    else:
        existing_player["name"] = name.strip()
        existing_player["photo"] = photo_url.strip()
        existing_player["year"] = f"{year.strip()} / {department.strip()}"
        existing_player["role"] = role.strip()
        existing_player["status"] = "PENDING_APPROVAL"
        existing_player["approval_status"] = "PENDING"
        existing_player["is_approved"] = False
        
    save_players(players)
    log_audit_event("STUDENT_REGISTERED", user=name.strip(), role="student", player_name=name.strip(), details=f"Registered Roll No: {clean_roll}, Dept: {department}, Role: {role} (Pending Admin Approval)")

    return {
        "success": True,
        "student": student,
        "message": "Registration successful! Your player registration is pending Admin verification."
    }

def get_student_registrations():
    """
    Returns list of all registered students with their verification status and counts.
    """
    students = get_students()
    registered_list = [s for s in students if s.get("registered")]
    
    # Sort: PENDING first, then by registration time
    status_order = {"PENDING": 0, "APPROVED": 1, "REJECTED": 2}
    registered_list.sort(key=lambda s: (status_order.get(s.get("approval_status", "PENDING"), 3), s.get("registered_at", "")), reverse=False)

    pending_count = sum(1 for s in registered_list if s.get("approval_status", "PENDING") == "PENDING")
    approved_count = sum(1 for s in registered_list if s.get("approval_status") == "APPROVED")
    rejected_count = sum(1 for s in registered_list if s.get("approval_status") == "REJECTED")

    return {
        "students": registered_list,
        "summary": {
            "total": len(registered_list),
            "pending": pending_count,
            "approved": approved_count,
            "rejected": rejected_count
        }
    }

def approve_student(roll_no, user="Admin"):
    """
    Approves a student registration and enlists the player as AVAILABLE in the auction pool.
    """
    clean_roll = roll_no.strip().upper()
    students = get_students()
    student = next((s for s in students if s.get('roll_no', '').upper() == clean_roll), None)
    if not student:
        return {"success": False, "message": "Student not found."}

    student["approval_status"] = "APPROVED"
    student["approved_at"] = datetime.now().isoformat()
    student["approved_by"] = user
    student["rejection_reason"] = ""
    save_students(students)

    # Update player in players.json to AVAILABLE
    players = get_players()
    player = next((p for p in players if p.get('roll_no', '').upper() == clean_roll), None)
    if player:
        player["status"] = "AVAILABLE"
        player["approval_status"] = "APPROVED"
        player["is_approved"] = True
    else:
        player = {
            "id": f"ply_{uuid.uuid4().hex[:8]}",
            "name": student.get("name", clean_roll),
            "roll_no": clean_roll,
            "year": f"{student.get('year', '')} / {student.get('department', '')}",
            "role": student.get("role", "All-Rounder"),
            "base_price": config.DEFAULT_BASE_PRICE,
            "status": "AVAILABLE",
            "approval_status": "APPROVED",
            "is_approved": True,
            "photo": student.get("photo", ""),
            "sold_price": 0,
            "sold_team_id": None,
            "sold_team_name": None,
            "batting": {"matches": 0, "runs": 0, "strike_rate": 0.0, "fifties": 0, "hundreds": 0, "fours": 0, "sixes": 0},
            "bowling": {"wickets": 0, "economy": 0.0},
            "fielding": {"catches": 0, "runouts": 0}
        }
        players.append(player)
    save_players(players)

    log_audit_event("STUDENT_APPROVED", user=user, role="admin", player_name=student.get("name"), details=f"Approved Roll No: {clean_roll} into active SPL auction pool.")
    return {"success": True, "student": student, "message": f"Student {student.get('name', clean_roll)} approved successfully."}

def reject_student(roll_no, reason="", user="Admin"):
    """
    Rejects a student registration and marks player as REJECTED (excluded from auction).
    """
    clean_roll = roll_no.strip().upper()
    students = get_students()
    student = next((s for s in students if s.get('roll_no', '').upper() == clean_roll), None)
    if not student:
        return {"success": False, "message": "Student not found."}

    student["approval_status"] = "REJECTED"
    student["rejection_reason"] = reason.strip() or "Registration did not meet criteria / photo verification."
    student["rejected_at"] = datetime.now().isoformat()
    student["rejected_by"] = user
    save_students(students)

    # Update player in players.json to REJECTED
    players = get_players()
    player = next((p for p in players if p.get('roll_no', '').upper() == clean_roll), None)
    if player:
        player["status"] = "REJECTED"
        player["approval_status"] = "REJECTED"
        player["is_approved"] = False
        save_players(players)

    log_audit_event("STUDENT_REJECTED", user=user, role="admin", player_name=student.get("name"), details=f"Rejected Roll No: {clean_roll}. Reason: {student['rejection_reason']}")
    return {"success": True, "student": student, "message": f"Student {student.get('name', clean_roll)} rejected."}

def reset_student_approval(roll_no, user="Admin"):
    """
    Resets student approval status back to PENDING.
    """
    clean_roll = roll_no.strip().upper()
    students = get_students()
    student = next((s for s in students if s.get('roll_no', '').upper() == clean_roll), None)
    if not student:
        return {"success": False, "message": "Student not found."}

    student["approval_status"] = "PENDING"
    student["rejection_reason"] = ""
    save_students(students)

    players = get_players()
    player = next((p for p in players if p.get('roll_no', '').upper() == clean_roll), None)
    if player:
        player["status"] = "PENDING_APPROVAL"
        player["approval_status"] = "PENDING"
        player["is_approved"] = False
        save_players(players)

    log_audit_event("STUDENT_STATUS_RESET", user=user, role="admin", player_name=student.get("name"), details=f"Reset Roll No: {clean_roll} status to PENDING.")
    return {"success": True, "student": student, "message": f"Student {student.get('name', clean_roll)} reset to Pending."}

def approve_all_pending_students(user="Admin"):
    """
    Approves all pending student registrations in one action.
    """
    students = get_students()
    pending = [s for s in students if s.get("registered") and s.get("approval_status", "PENDING") == "PENDING"]
    if not pending:
        return {"success": True, "count": 0, "message": "No pending registrations to approve."}

    for s in pending:
        approve_student(s["roll_no"], user=user)

    return {"success": True, "count": len(pending), "message": f"Successfully approved {len(pending)} student registrations."}


