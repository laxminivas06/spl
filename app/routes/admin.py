import os
import csv
import io
import re
from datetime import datetime
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, Response, make_response, abort
from flask_login import login_required, current_user
from app.extensions import db
from app.models import User, Player, PlayerRole, PlayerCategory, PlayerStatus, Franchise, AuctionState, AuctionStatus, SystemSettings, AuditLog, Transaction, Bid, Fixture, FixtureStage, FixtureStatus
from app.models.player import normalize_photo_url
from app.utils.decorators import admin_required
from app.services.csv_service import (
    parse_and_import_players_csv, preview_players_csv,
    export_players_excel, export_players_csv,
    generate_player_template_excel, generate_player_template_csv,
    is_valid_image_url
)
from app.services.audit_service import log_audit
from app.services.auction_service import validate_squads_integrity, confirm_and_lock_squads, unlock_squads_override
from app.services.fixture_service import generate_fixtures, validate_fixtures, publish_fixtures, unpublish_fixtures
from app.services.backup_service import create_database_backup, list_backups, restore_database_backup, save_deleted_record, list_deleted_records
from app.services.health_service import run_deep_auction_check
from app.utils.image_utils import validate_and_save_image

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

@admin_bp.before_request
def require_admin_for_admin_bp():
    """Ensure unauthorized users cannot access any admin pages or endpoints directly by URL."""
    if not current_user.is_authenticated:
        flash('Please sign in with your authorized administrator Google account to access this page.', 'warning')
        return redirect(url_for('auth.login'))
    if not current_user.is_admin:
        abort(403)

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']

@admin_bp.route('')
@admin_bp.route('/')
@admin_bp.route('/dashboard')
@login_required
@admin_required
def dashboard():
    auction_state = AuctionState.query.first()
    auction_status = auction_state.status if auction_state else AuctionStatus.WAITING
    active_player = Player.query.get(auction_state.active_player_id) if auction_state and auction_state.active_player_id else None
    highest_bidder = Franchise.query.get(auction_state.highest_bidder_id) if auction_state and auction_state.highest_bidder_id else None

    total_players = Player.query.count()
    available_players = Player.query.filter_by(status=PlayerStatus.AVAILABLE).count()
    sold_players = Player.query.filter_by(status=PlayerStatus.SOLD).count()
    unsold_players = Player.query.filter_by(status=PlayerStatus.UNSOLD).count()

    all_franchises = Franchise.query.order_by(Franchise.id.asc()).all()
    active_franchises = [f for f in all_franchises if f.is_active]

    total_capacity = sum(f.squad_limit for f in active_franchises) if active_franchises else 90
    total_purse = sum(f.starting_purse for f in active_franchises) if active_franchises else 3000000.0

    # Primary & Second Chance Operational Data
    primary_available = Player.query.filter_by(status=PlayerStatus.AVAILABLE, auction_type='PRIMARY').count()
    second_chance_eligible = Player.query.filter_by(status=PlayerStatus.UNSOLD, is_second_chance_eligible=True).count()
    second_chance_sold = AuditLog.query.filter_by(action='SECOND_CHANCE_PLAYER_SOLD').count()
    is_second_chance_active = SystemSettings.get_setting('second_chance_active') == 'true'

    # Check if both Primary and Second Chance auctions are completed
    sc_completed_setting = SystemSettings.get_setting('second_chance_completed') == 'true'
    both_auctions_completed = (primary_available == 0 and (sc_completed_setting or (not is_second_chance_active and second_chance_eligible == 0)))

    # Team eligibility counts
    eligible_teams_count = sum(1 for f in active_franchises if f.is_eligible_for_bidding)
    ineligible_teams_count = len(active_franchises) - eligible_teams_count

    return render_template(
        'admin/dashboard.html',
        auction_status=auction_status,
        auction_state=auction_state,
        active_player=active_player,
        highest_bidder=highest_bidder,
        total_players=total_players,
        available_players=available_players,
        sold_players=sold_players,
        unsold_players=unsold_players,
        primary_available=primary_available,
        second_chance_eligible=second_chance_eligible,
        second_chance_sold=second_chance_sold,
        is_second_chance_active=is_second_chance_active,
        both_auctions_completed=both_auctions_completed,
        total_franchises=len(all_franchises),
        active_franchises_count=len(active_franchises),
        eligible_teams_count=eligible_teams_count,
        ineligible_teams_count=ineligible_teams_count,
        total_capacity=total_capacity,
        total_purse=total_purse,
        all_franchises=all_franchises
    )

# ==================== PLAYER MANAGEMENT ====================

@admin_bp.route('/players', methods=['GET'])
@login_required
@admin_required
def players():
    search = request.args.get('search', '').strip()
    role_filter = request.args.get('role', '').strip()
    category_filter = request.args.get('category', '').strip()
    status_filter = request.args.get('status', '').strip()

    query = Player.query

    if search:
        query = query.filter(
            (Player.name.ilike(f'%{search}%')) |
            (Player.roll_number.ilike(f'%{search}%')) |
            (Player.branch.ilike(f'%{search}%'))
        )
    if role_filter:
        query = query.filter_by(role=role_filter)
    if category_filter:
        query = query.filter_by(category=category_filter)
    if status_filter:
        query = query.filter_by(status=status_filter)

    player_list = query.order_by(Player.id.desc()).all()

    primary_available = Player.query.filter_by(status=PlayerStatus.AVAILABLE, auction_type='PRIMARY').count()
    second_chance_eligible = Player.query.filter_by(status=PlayerStatus.UNSOLD, is_second_chance_eligible=True).count()
    is_second_chance_active = SystemSettings.get_setting('second_chance_active') == 'true'
    sc_completed_setting = SystemSettings.get_setting('second_chance_completed') == 'true'
    both_auctions_completed = (primary_available == 0 and (sc_completed_setting or (not is_second_chance_active and second_chance_eligible == 0)))

    return render_template(
        'admin/players.html',
        players=player_list,
        roles=PlayerRole.CHOICES,
        categories=PlayerCategory.CHOICES,
        statuses=PlayerStatus.CHOICES,
        search=search,
        selected_role=role_filter,
        selected_category=category_filter,
        selected_status=status_filter,
        both_auctions_completed=both_auctions_completed
    )

@admin_bp.route('/players/add', methods=['POST'])
@login_required
@admin_required
def add_player():
    import re
    year = request.form.get('year', '').strip()
    roll_number = request.form.get('roll_number', '').strip().upper()
    name = request.form.get('name', '').strip()
    role = request.form.get('role', PlayerRole.BATSMAN).strip().upper()
    branch = request.form.get('branch', '').strip() or None
    category = PlayerCategory.normalize(request.form.get('category'))
    photo_url = normalize_photo_url(request.form.get('photo_url', '').strip())

    if not roll_number or len(roll_number) != 10 or not re.match(r'^[A-Z0-9]{10}$', roll_number):
        flash('Roll Number must be exactly 10 alphanumeric characters (e.g. SPL26A001X).', 'danger')
        return redirect(url_for('admin.players'))

    if not name:
        flash('Full Name is required.', 'danger')
        return redirect(url_for('admin.players'))

    if Player.query.filter((Player.roll_number == roll_number) | (Player.rule_number == roll_number)).first():
        flash(f'Player with Roll Number "{roll_number}" already exists.', 'danger')
        return redirect(url_for('admin.players'))

    photo_filename = 'default_player.png'
    file = request.files.get('photo_file') or request.files.get('photo')
    if file and file.filename and file.filename.strip():
        saved_photo, err = validate_and_save_image(file, prefix=f"player_{roll_number}")
        if err:
            flash(f"Player photo error: {err}", 'danger')
            return redirect(url_for('admin.players'))
        if saved_photo:
            photo_filename = saved_photo
    elif photo_url:
        photo_filename = photo_url

    player = Player(
        roll_number=roll_number,
        name=name,
        photo=photo_filename,
        role=role if role in PlayerRole.CHOICES else PlayerRole.BATSMAN,
        branch=branch,
        year=year or None,
        experience=None,
        category=category,
        status=PlayerStatus.AVAILABLE,
        auction_type='PRIMARY',
        room_number=None
    )

    db.session.add(player)
    db.session.commit()

    log_audit(current_user.id, 'ADD_PLAYER', 'Player', player.id, None, player.name)
    flash(f'Player "{name}" (Roll #{roll_number}) added successfully.', 'success')
    return redirect(url_for('admin.players'))

@admin_bp.route('/players/<int:id>/edit', methods=['POST'])
@login_required
@admin_required
def edit_player(id):
    import re
    player = Player.query.get_or_404(id)
    old_data = player.to_dict()

    new_rule = (request.form.get('roll_number') or request.form.get('rule_number') or player.roll_number or '').strip().upper()
    if new_rule:
        if len(new_rule) != 10 or not re.match(r'^[A-Z0-9]{10}$', new_rule):
            flash('Roll Number must be exactly 10 alphanumeric characters (e.g. SPL26A001X).', 'danger')
            return redirect(url_for('admin.players'))
        if new_rule != player.roll_number:
            existing = Player.query.filter((Player.roll_number == new_rule) | (Player.rule_number == new_rule)).first()
            if existing and existing.id != player.id:
                flash(f'Roll Number "{new_rule}" already belongs to another player.', 'danger')
                return redirect(url_for('admin.players'))
            player.roll_number = new_rule

    new_year = request.form.get('year', '').strip()
    if new_year:
        player.year = new_year

    new_branch = request.form.get('branch', '').strip()
    if new_branch is not None:
        player.branch = new_branch if new_branch else None

    new_name = request.form.get('name', '').strip()
    if new_name:
        player.name = new_name

    new_role = request.form.get('role', '').strip().upper()
    if new_role and new_role in PlayerRole.CHOICES:
        player.role = new_role

    new_cat = request.form.get('category')
    if new_cat:
        player.category = PlayerCategory.normalize(new_cat)

    raw_photo_url = request.form.get('photo_url', '').strip()
    new_photo_url = normalize_photo_url(raw_photo_url) if raw_photo_url else None
    file = request.files.get('photo_file') or request.files.get('photo')

    # Priority 1: Newly uploaded photo file takes precedence over any pre-filled or entered URL
    if file and file.filename and file.filename.strip():
        safe_prefix = player.roll_number or str(player.id)
        saved_photo, err = validate_and_save_image(file, prefix=f"player_{safe_prefix}")
        if err:
            flash(f"Player photo error: {err}", 'danger')
            return redirect(url_for('admin.players'))
        if saved_photo:
            player.photo = saved_photo
    # Priority 2: Photo URL if no new file is uploaded
    elif new_photo_url:
        player.photo = new_photo_url
    elif raw_photo_url == '' and player.photo and player.photo.startswith('http'):
        player.photo = None

    db.session.commit()
    log_audit(current_user.id, 'EDIT_PLAYER', 'Player', player.id, old_data, player.to_dict())
    flash(f'Player "{player.name}" updated successfully.', 'success')
    return redirect(url_for('admin.players'))

@admin_bp.route('/players/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_player(id):
    player = Player.query.get_or_404(id)
    name = player.name
    player_data = player.to_dict()

    # 1. Take database backup snapshot before deleting
    backup_file = create_database_backup(current_user.id)
    save_deleted_record('Player', player_data, current_user.id, backup_file)

    # 2. Safely clean up references
    franchises_to_recalc = set()
    if player.sold_to:
        f_sold = db.session.get(Franchise, player.sold_to)
        if f_sold:
            franchises_to_recalc.add(f_sold)

    all_franchises = Franchise.query.all()
    for f in all_franchises:
        modified = False
        if f.captain_id == player.id:
            f.captain_id = None
            modified = True
        if f.vice_captain_id == player.id:
            f.vice_captain_id = None
            modified = True
        if modified:
            franchises_to_recalc.add(f)

    # Auction state references
    auction_state = AuctionState.query.first()
    if auction_state and auction_state.active_player_id == player.id:
        auction_state.active_player_id = None
        auction_state.current_bid = 0.0
        auction_state.highest_bidder_id = None
        auction_state.status = AuctionStatus.WAITING

    # Clean up bids and transactions referencing this player
    for b in Bid.query.filter_by(player_id=player.id).all():
        db.session.delete(b)

    for t in Transaction.query.filter_by(player_id=player.id).all():
        t.player_id = None

    # Delete the player
    db.session.delete(player)

    # Recalculate affected franchises
    for f in franchises_to_recalc:
        f.recalculate_purse()

    db.session.commit()

    log_audit(current_user.id, 'DELETE_PLAYER', 'Player', id, name, f"Backup saved: {backup_file}")
    flash(f'Player "{name}" deleted successfully. Saved to backup snapshot "{backup_file}".', 'info')
    return redirect(url_for('admin.players'))

@admin_bp.route('/players/preview-csv', methods=['POST'])
@login_required
@admin_required
def preview_csv():
    file = request.files.get('csv_file')
    if not file or not file.filename:
        return jsonify({'success': False, 'message': 'Please select a valid Excel (.xlsx) or CSV file.'}), 400

    content = file.read()
    preview = preview_players_csv(content, filename=file.filename)
    return jsonify({'success': True, 'preview': preview})

@admin_bp.route('/players/import-csv', methods=['POST'])
@login_required
@admin_required
def import_csv():
    file = request.files.get('csv_file')
    if not file or not file.filename:
        flash('Please select a valid Excel (.xlsx) or CSV file.', 'danger')
        return redirect(url_for('admin.players'))

    content = file.read()
    import_result = parse_and_import_players_csv(content, filename=file.filename)

    log_audit(
        current_user.id, 'IMPORT_PLAYERS_EXCEL_CSV', 'Player', None,
        None, f"Imported: {import_result['imported']}, Skipped: {import_result['skipped']}, Duplicates: {import_result['duplicates']}"
    )

    flash(f"Import Summary: {import_result['imported']} Imported, {import_result['duplicates']} duplicates skipped, {import_result['skipped']} Skipped.", 'success' if import_result['imported'] > 0 else 'warning')
    return redirect(url_for('admin.players'))

@admin_bp.route('/players/export')
@login_required
@admin_required
def export_players():
    fmt = request.args.get('format', 'excel').lower()
    if fmt == 'csv':
        csv_text = export_players_csv()
        response = Response(csv_text, mimetype='text/csv')
        response.headers['Content-Disposition'] = 'attachment; filename=SPL_Players_Roster.csv'
        return response
    else:
        file_bytes, mimetype, filename = export_players_excel()
        response = Response(file_bytes, mimetype=mimetype)
        response.headers['Content-Disposition'] = f'attachment; filename={filename}'
        return response

@admin_bp.route('/players/download-template')
@login_required
@admin_required
def download_player_template():
    fmt = request.args.get('format', 'excel').lower()
    if fmt == 'csv':
        csv_text = generate_player_template_csv()
        response = Response(csv_text, mimetype='text/csv')
        response.headers['Content-Disposition'] = 'attachment; filename=SPL_Player_Import_Template.csv'
        return response
    else:
        file_bytes, mimetype, filename = generate_player_template_excel()
        response = Response(file_bytes, mimetype=mimetype)
        response.headers['Content-Disposition'] = f'attachment; filename={filename}'
        return response

@admin_bp.route('/players/<int:id>/json')
@login_required
@admin_required
def get_player_json(id):
    player = Player.query.get_or_404(id)
    return jsonify(player.to_dict())

@admin_bp.route('/players/by-rule/<rule_no>')
@login_required
@admin_required
def get_player_by_rule(rule_no):
    clean_rule = rule_no.strip()
    player = Player.query.filter(Player.roll_number.ilike(clean_rule)).first()
    if not player:
        return jsonify({'success': False, 'message': f"Player with Rule Number '{rule_no}' not found."}), 404
    return jsonify({'success': True, 'player': player.to_dict()})

# ==================== FRANCHISE MANAGEMENT ====================

import re

def is_valid_email(email):
    """Validate RFC email address format."""
    if not email or not isinstance(email, str):
        return False
    return bool(re.match(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$', email.strip()))

def extract_owners_from_request(req_form):
    """
    Extract up to 3 owners from form submission.
    Supports owner_name_1, owner_email_1, owner_phone_1 ...
    or owner_name[], owner_email[] list syntax,
    or legacy single fields.
    """
    owners = []
    # 1. Numbered fields (Owner 1, 2, 3)
    for idx in (1, 2, 3):
        name = req_form.get(f'owner_name_{idx}', '').strip()
        email = req_form.get(f'owner_email_{idx}', '').strip().lower()
        phone = req_form.get(f'owner_phone_{idx}', '').strip()
        if name or email or phone:
            owners.append({
                'name': name,
                'email': email,
                'phone': phone
            })

    # 2. List syntax fallback
    if not owners:
        names = req_form.getlist('owner_name[]') or req_form.getlist('owner_name')
        emails = req_form.getlist('owner_email[]') or req_form.getlist('authorized_email[]') or req_form.getlist('authorized_email')
        phones = req_form.getlist('owner_phone[]')
        for i in range(max(len(names), len(emails))):
            name = names[i].strip() if i < len(names) else ''
            email = emails[i].strip().lower() if i < len(emails) else ''
            phone = phones[i].strip() if i < len(phones) else ''
            if name or email:
                owners.append({'name': name, 'email': email, 'phone': phone})

    # 3. Single legacy fields fallback
    if not owners:
        single_name = req_form.get('owner_name', '').strip()
        single_email = (req_form.get('authorized_email') or req_form.get('gmail') or req_form.get('email') or '').strip().lower()
        single_phone = req_form.get('owner_phone', '').strip()
        if single_name or single_email:
            owners.append({'name': single_name, 'email': single_email, 'phone': single_phone})

    return owners[:3]

def validate_owners(owners, franchise_id=None):
    """
    Validates owners:
    - Owner 1 is mandatory (Name & Valid Email required).
    - Owner 2 and Owner 3 are optional. If added, both Name and valid Email are required.
    - No duplicate emails within the same franchise.
    - No duplicate emails across other franchises.
    Returns (cleaned_owners, error_message).
    """
    if not owners or not owners[0].get('name') or not owners[0].get('name').strip():
        return None, 'Owner 1 (Primary) Name is mandatory.'

    owner1_email = (owners[0].get('email') or '').strip().lower()
    if not owner1_email:
        return None, 'Owner 1 (Primary) Login Email is mandatory.'
    if not is_valid_email(owner1_email):
        return None, f"Owner 1 email '{owner1_email}' is not a valid email address."

    cleaned = [{
        'name': owners[0]['name'].strip(),
        'email': owner1_email,
        'phone': owners[0].get('phone', '').strip()
    }]

    for idx, o in enumerate(owners[1:], start=2):
        name = (o.get('name') or '').strip()
        email = (o.get('email') or '').strip().lower()
        phone = (o.get('phone') or '').strip()

        # If completely empty, skip optional owner
        if not name and not email and not phone:
            continue

        if not name:
            return None, f"Owner {idx} requires a Name if added."
        if not email:
            return None, f"Owner {idx} requires an Email if added."
        if not is_valid_email(email):
            return None, f"Owner {idx} email '{email}' is not a valid email address."

        cleaned.append({
            'name': name,
            'email': email,
            'phone': phone
        })

    # Duplicate check within this franchise
    emails = [o['email'] for o in cleaned if o.get('email')]
    if len(emails) != len(set(emails)):
        return None, 'Each owner in the franchise must have a unique email address.'

    # Collision check with other franchises
    for em in emails:
        for f in Franchise.query.all():
            if franchise_id and f.id == franchise_id:
                continue
            for existing_ow in f.get_owners():
                if existing_ow.get('email', '').strip().lower() == em:
                    return None, f"Email '{em}' is already assigned to franchise '{f.name}'."

    return cleaned, None

def sync_franchise_owner_users(franchise, cleaned_owners):
    """Synchronize User login accounts for all owners of the franchise."""
    new_emails = set(o['email'] for o in cleaned_owners if o.get('email'))

    # Provision / update user accounts for all owners
    for o in cleaned_owners:
        email = o.get('email')
        name = o.get('name')
        if not email:
            continue
        user = User.query.filter_by(email=email).first()
        if not user:
            uname = f"{franchise.short_name.lower()}_{email.split('@')[0]}"
            if User.query.filter_by(username=uname).first():
                uname = f"{franchise.short_name.lower()}_{franchise.id}_{len(uname)}"
            user = User(
                username=uname,
                email=email,
                display_name=name or franchise.name,
                role='FRANCHISE',
                franchise_id=franchise.id,
                is_active=franchise.is_active
            )
            user.set_password('SPL@2025')
            db.session.add(user)
        else:
            user.franchise_id = franchise.id
            user.role = 'FRANCHISE'
            user.is_active = franchise.is_active
            if name:
                user.display_name = name

    # Unlink any user accounts previously associated with this franchise whose email was removed
    existing_users = User.query.filter_by(franchise_id=franchise.id).all()
    for u in existing_users:
        if u.email.strip().lower() not in new_emails and not u.is_admin:
            u.franchise_id = None

@admin_bp.route('/franchises', methods=['GET'])
@login_required
@admin_required
def franchises():
    from app.models.franchise import get_available_branches
    franchise_list = Franchise.query.order_by(Franchise.id.asc()).all()
    categories = PlayerCategory.CHOICES
    branches = get_available_branches()
    return render_template('admin/franchises.html', franchises=franchise_list, categories=categories, branches=branches)

@admin_bp.route('/franchises/add', methods=['POST'])
@login_required
@admin_required
def add_franchise():
    name = request.form.get('name', '').strip()
    short_name = request.form.get('short_name', '').strip().upper()
    google_auth_enabled = request.form.get('google_auth_enabled') != 'false'

    if not name or not short_name:
        flash('Franchise name and short code are required.', 'danger')
        return redirect(url_for('admin.franchises'))

    if Franchise.query.filter_by(name=name).first():
        flash(f'Franchise name "{name}" already exists.', 'danger')
        return redirect(url_for('admin.franchises'))

    if Franchise.query.filter_by(short_name=short_name).first():
        flash(f'Franchise code "{short_name}" already exists.', 'danger')
        return redirect(url_for('admin.franchises'))

    raw_owners = extract_owners_from_request(request.form)
    cleaned_owners, err = validate_owners(raw_owners)
    if err:
        flash(err, 'danger')
        return redirect(url_for('admin.franchises'))

    captain_rule_number = request.form.get('captain_rule_number', '').strip()
    captain_name = request.form.get('captain_name', '').strip()
    captain_department = (request.form.get('captain_department', '') or request.form.get('branch', '')).strip()
    captain_year = request.form.get('captain_year', '').strip()
    captain_cat_raw = request.form.get('captain_category', '').strip()
    captain_category = PlayerCategory.normalize(captain_cat_raw) if captain_cat_raw else 'Elite'

    captain_photo = None
    cap_file = request.files.get('captain_photo_file') or request.files.get('captain_photo')
    if cap_file and cap_file.filename and cap_file.filename.strip():
        saved_cap, err = validate_and_save_image(cap_file, prefix=f"captain_{short_name}")
        if err:
            flash(f"Captain photo error: {err}", 'danger')
            return redirect(url_for('admin.franchises'))
        if saved_cap:
            captain_photo = saved_cap
    elif request.form.get('captain_photo_url'):
        captain_photo = normalize_photo_url(request.form.get('captain_photo_url').strip())

    if (captain_name or captain_rule_number) and not captain_photo:
        flash('Captain photo is mandatory. A captain record cannot be saved without a photo.', 'danger')
        return redirect(url_for('admin.franchises'))

    try:
        starting_purse = float(SystemSettings.get_setting('starting_purse', '550000'))
    except (ValueError, TypeError):
        starting_purse = 550000.0

    try:
        squad_limit = int(SystemSettings.get_setting('squad_limit', '15'))
    except (ValueError, TypeError):
        squad_limit = 15

    logo_filename = 'default_logo.png'
    file = request.files.get('logo_file')
    if file and file.filename and file.filename.strip():
        saved_logo, err = validate_and_save_image(file, prefix=f"logo_{short_name}")
        if err:
            flash(f"Franchise logo error: {err}", 'danger')
            return redirect(url_for('admin.franchises'))
        if saved_logo:
            logo_filename = saved_logo
    elif request.form.get('logo_url'):
        logo_filename = request.form.get('logo_url').strip()

    franchise = Franchise(
        name=name,
        short_name=short_name,
        google_auth_enabled=google_auth_enabled,
        starting_purse=starting_purse,
        remaining_purse=starting_purse,
        squad_limit=squad_limit,
        logo=logo_filename,
        captain_name=captain_name or None,
        captain_rule_number=captain_rule_number or None,
        captain_department=captain_department or None,
        captain_year=captain_year or None,
        captain_category=captain_category or None,
        captain_photo=captain_photo or None,
        is_active=True
    )
    franchise.set_owners(cleaned_owners)

    db.session.add(franchise)
    db.session.commit()

    sync_franchise_owner_users(franchise, cleaned_owners)
    db.session.commit()

    log_audit(current_user.id, 'FRANCHISE_CREATED', 'Franchise', franchise.id, None, franchise.name, franchise_id=franchise.id)
    flash(f'Franchisee "{name}" created successfully with {len(cleaned_owners)} owner(s).', 'success')
    return redirect(url_for('admin.franchises'))

@admin_bp.route('/franchises/<int:id>/edit', methods=['POST'])
@login_required
@admin_required
def edit_franchise(id):
    franchise = Franchise.query.get_or_404(id)
    old_data = franchise.to_dict()

    new_name = request.form.get('name', franchise.name).strip()
    new_short = request.form.get('short_name', franchise.short_name).strip().upper()

    if not new_name or not new_short:
        flash('Franchise name and short code cannot be empty.', 'danger')
        return redirect(url_for('admin.franchises'))

    if new_name.lower() != franchise.name.lower():
        existing_name = Franchise.query.filter(Franchise.name.ilike(new_name)).first()
        if existing_name and existing_name.id != franchise.id:
            flash(f'Franchise name "{new_name}" is already taken.', 'danger')
            return redirect(url_for('admin.franchises'))

    if new_short != franchise.short_name:
        existing_short = Franchise.query.filter_by(short_name=new_short).first()
        if existing_short and existing_short.id != franchise.id:
            flash(f'Franchise code "{new_short}" is already taken.', 'danger')
            return redirect(url_for('admin.franchises'))

    raw_owners = extract_owners_from_request(request.form)
    cleaned_owners, err = validate_owners(raw_owners, franchise_id=franchise.id)
    if err:
        flash(err, 'danger')
        return redirect(url_for('admin.franchises'))

    captain_rule_number = request.form.get('captain_rule_number', '').strip()
    captain_name = request.form.get('captain_name', '').strip()
    captain_department = (request.form.get('captain_department', '') or request.form.get('branch', '')).strip()
    captain_year = request.form.get('captain_year', '').strip()
    captain_cat_raw = request.form.get('captain_category', '').strip()
    captain_category = PlayerCategory.normalize(captain_cat_raw) if captain_cat_raw else (franchise.captain_category or 'Elite')

    # Handle Captain Photo (Mandatory)
    captain_photo = franchise.captain_photo
    cap_file = request.files.get('captain_photo_file') or request.files.get('captain_photo')
    if cap_file and cap_file.filename and cap_file.filename.strip():
        saved_cap, err = validate_and_save_image(cap_file, prefix=f"captain_{new_short}")
        if err:
            flash(f"Captain photo error: {err}", 'danger')
            return redirect(url_for('admin.franchises'))
        if saved_cap:
            captain_photo = saved_cap
    elif request.form.get('captain_photo_url'):
        captain_photo = normalize_photo_url(request.form.get('captain_photo_url').strip())

    # Validation: Captain Photo is strictly mandatory for any team captain
    if (captain_name or captain_rule_number or franchise.has_captain) and not captain_photo:
        flash('Captain photo is mandatory. A captain record cannot be saved or updated without a photo.', 'danger')
        return redirect(url_for('admin.franchises'))

    franchise.name = new_name
    franchise.short_name = new_short
    franchise.set_owners(cleaned_owners)
    franchise.captain_name = captain_name or None
    franchise.captain_rule_number = captain_rule_number or None
    franchise.captain_department = captain_department or None
    franchise.captain_year = captain_year or None
    franchise.captain_category = captain_category or 'Elite'
    franchise.captain_photo = captain_photo or None
    franchise.google_auth_enabled = request.form.get('google_auth_enabled') != 'false'
    franchise.is_active = 'is_active' in request.form or request.form.get('is_active') == 'true'

    try:
        new_starting = float(request.form.get('starting_purse', franchise.starting_purse))
        spent = franchise.spent_purse
        franchise.starting_purse = new_starting
        franchise.remaining_purse = max(0.0, new_starting - spent)
        franchise.squad_limit = int(request.form.get('squad_limit', franchise.squad_limit))
    except (ValueError, TypeError):
        pass

    file = request.files.get('logo_file')
    if file and file.filename and file.filename.strip():
        saved_logo, err = validate_and_save_image(file, prefix=f"logo_{franchise.short_name}")
        if err:
            flash(f"Franchise logo error: {err}", 'danger')
            return redirect(url_for('admin.franchises'))
        if saved_logo:
            franchise.logo = saved_logo
            log_audit(current_user.id, 'FRANCHISE_LOGO_UPLOADED', 'Franchise', franchise.id, None, saved_logo, franchise_id=franchise.id)
    elif request.form.get('logo_url'):
        franchise.logo = request.form.get('logo_url').strip()

    db.session.commit()

    sync_franchise_owner_users(franchise, cleaned_owners)
    db.session.commit()

    log_audit(
        current_user.id, 'FRANCHISE_UPDATED', 'Franchise', franchise.id,
        str(old_data), str(franchise.to_dict()),
        f"Franchisee '{franchise.name}' updated by Admin {current_user.username}",
        franchise_id=franchise.id
    )
    flash(f'Franchisee "{franchise.name}" updated successfully.', 'success')
    return redirect(url_for('admin.franchises'))

@admin_bp.route('/franchises/<int:id>/toggle-status', methods=['POST'])
@login_required
@admin_required
def toggle_franchise_status(id):
    franchise = Franchise.query.get_or_404(id)
    franchise.is_active = not franchise.is_active

    # Sync associated user accounts
    users = User.query.filter_by(franchise_id=franchise.id).all()
    for u in users:
        u.is_active = franchise.is_active

    db.session.commit()
    status_str = 'ACTIVE (Login Enabled)' if franchise.is_active else 'DISABLED (Login Blocked)'
    log_audit(current_user.id, 'FRANCHISE_STATUS_TOGGLED', 'Franchise', franchise.id, None, status_str, franchise_id=franchise.id)
    flash(f'Franchisee "{franchise.name}" status updated: {status_str}.', 'success')
    return redirect(url_for('admin.franchises'))

@admin_bp.route('/franchises/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_franchise(id):
    franchise = Franchise.query.get_or_404(id)
    name = franchise.name
    franchise_data = franchise.to_dict()

    # 1. Take database backup snapshot before deleting
    backup_file = create_database_backup(current_user.id)
    save_deleted_record('Franchise', franchise_data, current_user.id, backup_file)

    # 2. Release all players sold to this franchise
    sold_players = Player.query.filter_by(sold_to=franchise.id).all()
    for p in sold_players:
        p.sold_to = None
        p.sold_price = None
        p.sold_at = None
        p.status = PlayerStatus.AVAILABLE

    # If captain player was assigned
    if franchise.captain_id:
        cap_player = db.session.get(Player, franchise.captain_id)
        if cap_player:
            cap_player.sold_to = None
            cap_player.sold_price = None
            cap_player.status = PlayerStatus.AVAILABLE

    # 3. Dissociate users linked to this franchise
    users_linked = User.query.filter_by(franchise_id=franchise.id).all()
    for u in users_linked:
        u.franchise_id = None

    # 4. Clean up bids, transactions, and fixtures
    for b in Bid.query.filter_by(franchise_id=franchise.id).all():
        db.session.delete(b)

    for t in Transaction.query.filter_by(franchise_id=franchise.id).all():
        db.session.delete(t)

    fixtures = Fixture.query.filter((Fixture.team_a_id == franchise.id) | (Fixture.team_b_id == franchise.id)).all()
    for f in fixtures:
        db.session.delete(f)

    # 5. Clear auction state if this franchise was highest bidder
    auction_state = AuctionState.query.first()
    if auction_state and auction_state.highest_bidder_id == franchise.id:
        auction_state.highest_bidder_id = None
        auction_state.current_bid = 0.0

    # 6. Delete the franchise
    db.session.delete(franchise)
    db.session.commit()

    log_audit(current_user.id, 'DELETE_FRANCHISE', 'Franchise', id, name, f"Backup saved: {backup_file}")
    flash(f'Franchise "{name}" deleted successfully. Squad released and backup saved ({backup_file}).', 'success')
    return redirect(url_for('admin.franchises'))

@admin_bp.route('/franchises/<int:id>/remove-logo', methods=['POST'])
@login_required
@admin_required
def remove_franchise_logo(id):
    franchise = Franchise.query.get_or_404(id)
    old_logo = franchise.logo
    franchise.logo = 'default_logo.png'
    db.session.commit()

    log_audit(current_user.id, 'FRANCHISE_LOGO_REMOVED', 'Franchise', franchise.id, old_logo, 'default_logo.png', franchise_id=franchise.id)
    flash(f'Logo for franchise "{franchise.name}" reset to default.', 'info')
    return redirect(url_for('admin.franchises'))

@admin_bp.route('/franchises/<int:id>/toggle-google', methods=['POST'])
@login_required
@admin_required
def toggle_franchise_google(id):
    franchise = Franchise.query.get_or_404(id)
    franchise.google_auth_enabled = not franchise.google_auth_enabled
    db.session.commit()

    status_str = 'ENABLED' if franchise.google_auth_enabled else 'DISABLED'
    log_audit(current_user.id, 'GOOGLE_AUTH_TOGGLED', 'Franchise', franchise.id, None, status_str, franchise_id=franchise.id)
    flash(f'Google Authentication for "{franchise.name}" set to {status_str}.', 'success')
    return redirect(url_for('admin.franchises'))

@admin_bp.route('/franchises/<int:id>/inspect')
@login_required
@admin_required
def inspect_franchise(id):
    franchise = Franchise.query.get_or_404(id)
    players = Player.query.filter_by(sold_to=franchise.id).all()
    purchases = Transaction.query.filter(Transaction.franchise_id == franchise.id, Transaction.type.in_(['PLAYER_PURCHASE', 'PURCHASE'])).order_by(Transaction.created_at.desc()).all()
    bids = Bid.query.filter_by(franchise_id=franchise.id).order_by(Bid.created_at.desc()).all()

    role_counts = {
        PlayerRole.BATSMAN: sum(1 for p in players if p.role == PlayerRole.BATSMAN),
        PlayerRole.BOWLER: sum(1 for p in players if p.role == PlayerRole.BOWLER),
        PlayerRole.ALL_ROUNDER: sum(1 for p in players if p.role == PlayerRole.ALL_ROUNDER),
        PlayerRole.WICKETKEEPER: sum(1 for p in players if p.role == PlayerRole.WICKETKEEPER)
    }

    return render_template(
        'admin/franchise_inspect.html',
        franchise=franchise,
        players=players,
        purchases=purchases,
        bids=bids,
        role_counts=role_counts
    )

@admin_bp.route('/franchises/<int:id>/add-captain', methods=['POST'])
@login_required
@admin_required
def admin_add_captain(id):
    franchise = Franchise.query.get_or_404(id)
    name = request.form.get('captain_name', '').strip()
    rule_number = request.form.get('captain_rule_number', '').strip() or request.form.get('captain_roll_number', '').strip()
    department = request.form.get('captain_department', '').strip() or request.form.get('captain_branch', '').strip()
    year = request.form.get('captain_year', '').strip()
    category = PlayerCategory.normalize(request.form.get('captain_category', 'Elite'))

    photo_fname = None
    photo_file = request.files.get('captain_photo_file') or request.files.get('captain_photo')
    if photo_file and photo_file.filename and photo_file.filename.strip():
        saved_cap, err = validate_and_save_image(photo_file, prefix=f"captain_{franchise.short_name}")
        if err:
            flash(f"Captain photo error: {err}", 'danger')
            next_url = request.form.get('next') or request.referrer or url_for('admin.franchises')
            return redirect(next_url)
        photo_fname = saved_cap
    elif request.form.get('captain_photo_url'):
        photo_fname = normalize_photo_url(request.form.get('captain_photo_url').strip())
    elif franchise.captain_photo:
        photo_fname = franchise.captain_photo

    if not photo_fname:
        flash('Captain photo is mandatory. A captain record cannot be saved without a photo.', 'danger')
        next_url = request.form.get('next') or request.referrer or url_for('admin.franchises')
        return redirect(next_url)

    from app.services.team_service import add_team_captain
    try:
        add_team_captain(
            franchise=franchise,
            name=name,
            rule_number=rule_number,
            department=department,
            year=year,
            category=category,
            photo=photo_fname,
            actor_id=current_user.id
        )
        flash(f'✓ Team Captain "{name}" added successfully for {franchise.name}! Team is now ELIGIBLE FOR BIDDING.', 'success')
    except ValueError as e:
        flash(str(e), 'danger')

    next_url = request.form.get('next') or request.referrer or url_for('admin.franchises')
    return redirect(next_url)

@admin_bp.route('/franchises/<int:id>/add-member', methods=['POST'])
@login_required
@admin_required
def admin_add_member(id):
    franchise = Franchise.query.get_or_404(id)
    name = request.form.get('name', '').strip()
    rule_number = request.form.get('rule_number', '').strip() or request.form.get('roll_number', '').strip()
    department = request.form.get('branch', '').strip() or request.form.get('department', '').strip()
    year = request.form.get('year', '').strip()
    role = request.form.get('role', 'BATSMAN').strip().upper()
    category = request.form.get('category', 'NORMAL').strip().upper()

    photo_fname = None
    if 'photo' in request.files:
        photo_file = request.files.get('photo')
        if photo_file and photo_file.filename and photo_file.filename.strip():
            saved_mem, err = validate_and_save_image(photo_file, prefix=f"member_{franchise.short_name}")
            if err:
                flash(f"Player photo error: {err}", 'danger')
                next_url = request.form.get('next') or request.referrer or url_for('admin.inspect_franchise', id=franchise.id)
                return redirect(next_url)
            photo_fname = saved_mem

    from app.services.team_service import add_team_member
    try:
        player = add_team_member(
            franchise=franchise,
            name=name,
            rule_number=rule_number,
            department=department,
            year=year,
            role=role,
            category=category,
            photo=photo_fname,
            actor_id=current_user.id
        )
        flash(f'Member "{player.name}" added to {franchise.name} ({franchise.squad_count}/{franchise.squad_limit} Members).', 'success')
    except ValueError as e:
        flash(str(e), 'danger')

    next_url = request.form.get('next') or request.referrer or url_for('admin.inspect_franchise', id=franchise.id)
    return redirect(next_url)

# ==================== ADMIN AUDIT LOG PLATFORM ====================

@admin_bp.route('/audit-logs', methods=['GET'])
@login_required
@admin_required
def audit_logs():
    search = request.args.get('search', '').strip()
    action_filter = request.args.get('action', '').strip()
    category_filter = request.args.get('category', '').strip().upper()
    status_filter = request.args.get('status', '').strip()
    franchise_filter = request.args.get('franchise_id', '').strip()
    user_filter = request.args.get('user_id', '').strip()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 25

    query = AuditLog.query

    if search:
        query = query.filter(
            (AuditLog.action.ilike(f'%{search}%')) |
            (AuditLog.old_value.ilike(f'%{search}%')) |
            (AuditLog.new_value.ilike(f'%{search}%')) |
            (AuditLog.ip_address.ilike(f'%{search}%')) |
            (AuditLog.user_email.ilike(f'%{search}%'))
        )

    if category_filter:
        query = query.filter(AuditLog.category == category_filter)

    if action_filter:
        query = query.filter(AuditLog.action == action_filter)

    if status_filter:
        query = query.filter(AuditLog.status == status_filter)

    if franchise_filter and franchise_filter.isdigit():
        query = query.filter(AuditLog.franchise_id == int(franchise_filter))

    if user_filter and user_filter.isdigit():
        query = query.filter(AuditLog.admin_id == int(user_filter))

    if date_from:
        try:
            df = datetime.strptime(date_from, '%Y-%m-%d')
            query = query.filter(AuditLog.created_at >= df)
        except ValueError:
            pass

    if date_to:
        try:
            dt = datetime.strptime(date_to, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            query = query.filter(AuditLog.created_at <= dt)
        except ValueError:
            pass

    logs_list = query.order_by(AuditLog.created_at.desc()).all()
    total_matched = len(logs_list)
    total_pages = max(1, (total_matched + per_page - 1) // per_page)
    if page < 1:
        page = 1
    elif page > total_pages:
        page = total_pages
    paginated_logs = logs_list[(page - 1) * per_page : page * per_page]

    all_logs = AuditLog.query.all()
    total_events = len(all_logs)

    login_actions = {
        'LOGIN_SUCCESS', 'LOGIN_FAILED', 'GOOGLE_LOGIN_SUCCESS',
        'GOOGLE_LOGIN_FAILED', 'GOOGLE_ACCOUNT_UNAUTHORIZED',
        'ADMIN_LOGIN', 'LOGOUT'
    }
    auction_actions = {
        'BID_PLACED', 'PLAYER_SOLD', 'PLAYER_UNSOLD',
        'SECOND_CHANCE_STARTED', 'SECOND_CHANCE_SOLD', 'SECOND_CHANCE_ENDED'
    }
    security_actions = {
        'LOGIN_FAILED', 'GOOGLE_LOGIN_FAILED', 'GOOGLE_ACCOUNT_UNAUTHORIZED',
        'SETTINGS_CHANGED', 'ADMIN_PASSWORD_CHANGED', 'FRANCHISE_DISABLED',
        'USER_DISABLED', 'SECURITY_ALERT'
    }

    login_events = sum(1 for log in all_logs if log.action in login_actions or getattr(log, 'category', '') == 'AUTH')
    auction_events = sum(1 for log in all_logs if log.action in auction_actions or getattr(log, 'category', '') == 'AUCTION')
    admin_actions_count = sum(1 for log in all_logs if log.admin_id is not None)
    security_events = sum(1 for log in all_logs if log.action in security_actions or getattr(log, 'category', '') == 'SECURITY' or log.status in ['FAILED', 'DENIED'])

    franchises = Franchise.query.order_by(Franchise.name.asc()).all()
    users = User.query.order_by(User.username.asc()).all()

    distinct_actions = db.session.query(AuditLog.action).distinct().all()
    action_options = [a[0] for a in distinct_actions if a[0]]

    return render_template(
        'admin/audit_logs.html',
        logs=paginated_logs,
        page=page,
        total_pages=total_pages,
        total_matched=total_matched,
        per_page=per_page,
        total_events=total_events,
        login_events=login_events,
        auction_events=auction_events,
        admin_actions_count=admin_actions_count,
        security_events=security_events,
        franchises=franchises,
        users=users,
        action_options=action_options,
        search=search,
        selected_category=category_filter,
        selected_action=action_filter,
        selected_status=status_filter,
        selected_franchise=franchise_filter,
        selected_user=user_filter,
        date_from=date_from,
        date_to=date_to
    )

# ==================== SETTINGS MANAGEMENT ====================

@admin_bp.route('/settings', methods=['GET', 'POST'])
@login_required
@admin_required
def settings():
    if request.method == 'POST':
        event_name = request.form.get('event_name', 'SPL').strip()
        event_subtitle = request.form.get('event_subtitle', 'Sphoorthy Premier League').strip()
        starting_purse = request.form.get('starting_purse', '300000').strip()
        squad_limit = request.form.get('squad_limit', '15').strip()
        base_price = request.form.get('base_price', '10000').strip()
        timer_seconds = request.form.get('timer_seconds', '30').strip()
        theme_default = request.form.get('theme_default', 'dark').strip()
        show_price_public = 'true' if 'show_purchase_price_publicly' in request.form or request.form.get('show_purchase_price_publicly') == 'true' else 'false'

        # Elite Quota Options (Max 3 total, Min 1 / Max 2 from Auction)
        max_elite_per_team = request.form.get('max_elite_per_team', '3').strip()
        min_auction_elite_per_team = request.form.get('min_auction_elite_per_team', '1').strip()
        max_auction_elite_per_team = request.form.get('max_auction_elite_per_team', '2').strip()
        enforce_elite_limits = 'true' if 'enforce_elite_limits' in request.form or request.form.get('enforce_elite_limits') == 'true' else 'false'

        # Global Audit Settings
        audit_logging_enabled = 'true' if 'audit_logging_enabled' in request.form or request.form.get('audit_logging_enabled') == 'true' else 'false'
        audit_retention_days = request.form.get('audit_retention_days', '90').strip()
        audit_log_level = request.form.get('audit_log_level', 'ALL').strip().upper()
        audit_track_ip = 'true' if 'audit_track_ip' in request.form or request.form.get('audit_track_ip') == 'true' else 'false'

        SystemSettings.set_setting('event_name', event_name)
        SystemSettings.set_setting('event_subtitle', event_subtitle)
        SystemSettings.set_setting('starting_purse', starting_purse)
        SystemSettings.set_setting('squad_limit', squad_limit)
        SystemSettings.set_setting('base_price', base_price)
        SystemSettings.set_setting('timer_seconds', timer_seconds)
        SystemSettings.set_setting('theme_default', theme_default)
        SystemSettings.set_setting('SHOW_PURCHASE_PRICE_PUBLICLY', show_price_public)
        SystemSettings.set_setting('max_elite_per_team', max_elite_per_team)
        SystemSettings.set_setting('min_auction_elite_per_team', min_auction_elite_per_team)
        SystemSettings.set_setting('max_auction_elite_per_team', max_auction_elite_per_team)
        SystemSettings.set_setting('enforce_elite_limits', enforce_elite_limits)
        SystemSettings.set_setting('audit_logging_enabled', audit_logging_enabled)
        SystemSettings.set_setting('audit_retention_days', audit_retention_days)
        SystemSettings.set_setting('audit_log_level', audit_log_level)
        SystemSettings.set_setting('audit_track_ip', audit_track_ip)

        log_audit(current_user.id, 'UPDATE_SETTINGS', 'SystemSettings', None, None, f"Event: {event_name}, Elite Max: {max_elite_per_team}, Audit: {audit_log_level}")
        flash('System configuration and Global Audit settings saved successfully.', 'success')
        return redirect(url_for('admin.settings'))

    return render_template(
        'admin/settings.html',
        event_name=SystemSettings.get_setting('event_name', 'SPL'),
        event_subtitle=SystemSettings.get_setting('event_subtitle', 'Sphoorthy Premier League'),
        starting_purse=SystemSettings.get_setting('starting_purse', '300000'),
        squad_limit=SystemSettings.get_setting('squad_limit', '15'),
        base_price=SystemSettings.get_setting('base_price', '10000'),
        timer_seconds=SystemSettings.get_setting('timer_seconds', '10'),
        theme_default=SystemSettings.get_setting('theme_default', 'dark'),
        show_purchase_price_publicly=SystemSettings.get_setting('SHOW_PURCHASE_PRICE_PUBLICLY', 'true'),
        max_elite_per_team=SystemSettings.get_setting('max_elite_per_team', '3'),
        min_auction_elite_per_team=SystemSettings.get_setting('min_auction_elite_per_team', '1'),
        max_auction_elite_per_team=SystemSettings.get_setting('max_auction_elite_per_team', '2'),
        enforce_elite_limits=SystemSettings.get_setting('enforce_elite_limits', 'true'),
        audit_logging_enabled=SystemSettings.get_setting('audit_logging_enabled', 'true'),
        audit_retention_days=SystemSettings.get_setting('audit_retention_days', '90'),
        audit_log_level=SystemSettings.get_setting('audit_log_level', 'ALL'),
        audit_track_ip=SystemSettings.get_setting('audit_track_ip', 'true')
    )

# ==================== LIVE AUCTION CONTROL ====================

@admin_bp.route('/auction')
@login_required
@admin_required
def auction_control():
    franchises = Franchise.query.filter_by(is_active=True).order_by(Franchise.id.asc()).all()
    available_players = Player.query.filter(Player.status == PlayerStatus.AVAILABLE, Player.sold_to == None).order_by(Player.roll_number.asc()).all()
    return render_template('admin/auction.html', franchises=franchises, available_players=available_players)

@admin_bp.route('/auction/fresh-reset', methods=['POST'])
@login_required
@admin_required
def fresh_auction_reset():
    try:
        from app.services.auction_service import reset_auction_fresh
        reset_auction_fresh(current_user.id)
        flash('Fresh Auction Reset Completed! All previous auction data, bids, and spending have been reset. Master franchises, squads, and player profiles remain completely intact.', 'success')
    except Exception as e:
        flash(f'Auction reset failed: {str(e)}', 'danger')
    return redirect(url_for('admin.auction_control'))

# ==================== PHASE 6 MODULES ====================

# 1. UNSOLD PLAYER MANAGEMENT
@admin_bp.route('/unsold', methods=['GET'])
@login_required
@admin_required
def unsold_players():
    search = request.args.get('search', '').strip()
    role_filter = request.args.get('role', '').strip()
    category_filter = request.args.get('category', '').strip()

    query = Player.query.filter(Player.status.in_([PlayerStatus.UNSOLD, PlayerStatus.FINAL_UNSOLD]))

    if search:
        query = query.filter(
            (Player.name.ilike(f'%{search}%')) |
            (Player.roll_number.ilike(f'%{search}%'))
        )
    if role_filter:
        query = query.filter_by(role=role_filter)
    if category_filter:
        query = query.filter_by(category=category_filter)

    unsold_list = query.order_by(Player.roll_number.asc()).all()

    return render_template(
        'admin/unsold.html',
        players=unsold_list,
        roles=PlayerRole.CHOICES,
        categories=PlayerCategory.CHOICES,
        search=search,
        selected_role=role_filter,
        selected_category=category_filter
    )

@admin_bp.route('/unsold/toggle-eligibility/<int:id>', methods=['POST'])
@login_required
@admin_required
def toggle_unsold_eligibility(id):
    player = Player.query.get_or_404(id)
    if player.status not in [PlayerStatus.UNSOLD, PlayerStatus.FINAL_UNSOLD]:
        flash(f"Player {player.name} is not unsold.", 'warning')
        return redirect(url_for('admin.unsold_players'))

    player.is_second_chance_eligible = not player.is_second_chance_eligible
    db.session.commit()

    status_str = "ELIGIBLE for Second Chance" if player.is_second_chance_eligible else "REMOVED from Second Chance"
    log_audit(current_user.id, 'TOGGLE_SECOND_CHANCE_ELIGIBILITY', 'Player', player.id, None, status_str)
    flash(f"Player {player.name} is now {status_str}.", 'success')
    return redirect(url_for('admin.unsold_players'))

@admin_bp.route('/unsold/bulk-eligibility', methods=['POST'])
@login_required
@admin_required
def bulk_unsold_eligibility():
    action = request.form.get('action')
    unsold_players_list = Player.query.filter(Player.status.in_([PlayerStatus.UNSOLD, PlayerStatus.FINAL_UNSOLD])).all()

    count = 0
    if action == 'mark_all_eligible':
        for p in unsold_players_list:
            p.is_second_chance_eligible = True
            count += 1
        flash(f"Marked {count} unsold players as ELIGIBLE for second chance.", 'success')
    elif action == 'remove_all_eligibility':
        for p in unsold_players_list:
            p.is_second_chance_eligible = False
            count += 1
        flash(f"Removed second-chance eligibility from {count} unsold players.", 'info')

    db.session.commit()
    log_audit(current_user.id, 'BULK_SECOND_CHANCE_ELIGIBILITY', 'Player', None, None, f"Action: {action}, Affected: {count}")
    return redirect(url_for('admin.unsold_players'))

# 2. SECOND-CHANCE AUCTION DASHBOARD
@admin_bp.route('/second-chance', methods=['GET'])
@login_required
@admin_required
def second_chance_dashboard():
    total_unsold = Player.query.filter(Player.status.in_([PlayerStatus.UNSOLD, PlayerStatus.FINAL_UNSOLD])).count()
    eligible_unsold = Player.query.filter(Player.status == PlayerStatus.UNSOLD, Player.sold_to == None, Player.is_second_chance_eligible == True).count()
    second_chance_sold = AuditLog.query.filter_by(action='SECOND_CHANCE_PLAYER_SOLD').count()
    is_active = SystemSettings.get_setting('second_chance_active') == 'true'
    eligible_players = Player.query.filter(Player.status == PlayerStatus.UNSOLD, Player.sold_to == None, Player.is_second_chance_eligible == True).order_by(Player.roll_number.asc()).all()
    franchises = Franchise.query.order_by(Franchise.name.asc()).all()

    sc_completed = SystemSettings.get_setting('second_chance_completed') == 'true'

    return render_template(
        'admin/second_chance.html',
        total_unsold=total_unsold,
        eligible_unsold=eligible_unsold,
        second_chance_sold=second_chance_sold,
        is_active=is_active,
        sc_completed=sc_completed,
        eligible_players=eligible_players,
        franchises=franchises
    )

@admin_bp.route('/second-chance/complete', methods=['POST'])
@login_required
@admin_required
def complete_second_chance():
    SystemSettings.set_setting('second_chance_completed', 'true')
    log_audit(current_user.id, 'COMPLETE_SECOND_CHANCE', 'Auction', None, None, 'Second chance auction marked as completed')
    flash('Second Chance Auction marked as Completed. Post-Auction Player Addition is now unlocked!', 'success')
    return redirect(url_for('admin.players', post_auction=1))

# 3. FINAL SQUAD VERIFICATION & LOCKING
@admin_bp.route('/final-squads', methods=['GET'])
@login_required
@admin_required
def final_squads():
    franchises = Franchise.query.order_by(Franchise.id.asc()).all()

    # Build franchise breakdown with details
    squad_data = []
    for f in franchises:
        f.recalculate_purse()
        players = f.squad_players
        squad_data.append({
            'franchise': f,
            'players': players,
            'spent': f.spent_purse,
            'remaining': f.remaining_purse,
            'count': len(players)
        })

    is_valid, errors = validate_squads_integrity()
    is_locked = SystemSettings.get_setting('squads_locked') == 'true'

    return render_template(
        'admin/final_squads.html',
        squads=squad_data,
        is_valid=is_valid,
        validation_errors=errors,
        is_locked=is_locked
    )

@admin_bp.route('/final-squads/confirm', methods=['POST'])
@login_required
@admin_required
def confirm_squads():
    try:
        confirm_and_lock_squads(current_user.id)
        flash('FINAL SQUADS CONFIRMED AND LOCKED PERMANENTLY! 🏆', 'success')
    except ValueError as e:
        flash(f"Confirmation failed: {str(e)}", 'danger')

    return redirect(url_for('admin.final_squads'))

@admin_bp.route('/final-squads/unlock-override', methods=['POST'])
@login_required
@admin_required
def unlock_squads():
    reason = request.form.get('reason', '').strip()
    try:
        unlock_squads_override(current_user.id, reason)
        flash('Authorized Admin squad unlock override executed.', 'warning')
    except ValueError as e:
        flash(f"Unlock failed: {str(e)}", 'danger')

    return redirect(url_for('admin.final_squads'))

# 4. FIXTURE MANAGEMENT
@admin_bp.route('/fixtures', methods=['GET'])
@login_required
@admin_required
def fixtures_management():
    all_fixtures = Fixture.query.order_by(Fixture.match_number.asc()).all()
    franchises = Franchise.query.filter_by(is_active=True).all()
    is_valid, errors = validate_fixtures()
    is_published = any(f.is_published for f in all_fixtures) if all_fixtures else False

    return render_template(
        'admin/fixtures.html',
        fixtures=all_fixtures,
        franchises=franchises,
        is_valid=is_valid,
        validation_errors=errors,
        is_published=is_published,
        stages=FixtureStage.CHOICES,
        statuses=FixtureStatus.CHOICES
    )

@admin_bp.route('/fixtures/add', methods=['POST'])
@login_required
@admin_required
def add_fixture():
    try:
        match_number = int(request.form.get('match_number'))
        team_a_id = int(request.form.get('team_a_id'))
        team_b_id = int(request.form.get('team_b_id'))
        match_date = request.form.get('match_date', '').strip()
        match_time = request.form.get('match_time', '').strip()
        venue = request.form.get('venue', 'College Ground').strip()
        stage = request.form.get('stage', FixtureStage.LEAGUE).strip()

        if team_a_id == team_b_id:
            flash('Team A and Team B cannot be the same franchise.', 'danger')
            return redirect(url_for('admin.fixtures_management'))

        fixture = Fixture(
            match_number=match_number,
            team_a_id=team_a_id,
            team_b_id=team_b_id,
            match_date=match_date,
            match_time=match_time,
            venue=venue,
            stage=stage,
            is_published=False
        )
        db.session.add(fixture)
        db.session.commit()
        log_audit(current_user.id, 'ADD_FIXTURE', 'Fixture', fixture.id, None, f"Match #{match_number}")
        flash(f"Match #{match_number} added successfully.", 'success')
    except (ValueError, TypeError) as e:
        flash(f"Failed to add fixture: {str(e)}", 'danger')

    return redirect(url_for('admin.fixtures_management'))

@admin_bp.route('/fixtures/<int:id>/edit', methods=['POST'])
@login_required
@admin_required
def edit_fixture(id):
    fixture = Fixture.query.get_or_404(id)
    try:
        fixture.match_number = int(request.form.get('match_number', fixture.match_number))
        fixture.team_a_id = int(request.form.get('team_a_id', fixture.team_a_id))
        fixture.team_b_id = int(request.form.get('team_b_id', fixture.team_b_id))
        fixture.match_date = request.form.get('match_date', fixture.match_date).strip()
        fixture.match_time = request.form.get('match_time', fixture.match_time).strip()
        fixture.venue = request.form.get('venue', fixture.venue).strip()
        fixture.stage = request.form.get('stage', fixture.stage).strip()
        fixture.status = request.form.get('status', fixture.status).strip()

        db.session.commit()
        log_audit(current_user.id, 'FIXTURE_EDITED', 'Fixture', fixture.id, None, f"Updated Match #{fixture.match_number}")
        flash(f"Match #{fixture.match_number} updated.", 'success')
    except (ValueError, TypeError) as e:
        flash(f"Edit failed: {str(e)}", 'danger')

    return redirect(url_for('admin.fixtures_management'))

@admin_bp.route('/fixtures/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_fixture(id):
    fixture = Fixture.query.get_or_404(id)
    num = fixture.match_number
    db.session.delete(fixture)
    db.session.commit()
    log_audit(current_user.id, 'DELETE_FIXTURE', 'Fixture', id, f"Match #{num}", None)
    flash(f"Match #{num} deleted.", 'info')
    return redirect(url_for('admin.fixtures_management'))

@admin_bp.route('/fixtures/generate', methods=['POST'])
@login_required
@admin_required
def generate_draft_fixtures():
    format_type = request.form.get('format_type', 'SINGLE_ROUND_ROBIN')
    venue = request.form.get('venue', 'College Ground').strip()
    try:
        generated = generate_fixtures(format_type, venue, current_user.id)
        flash(f"Generated {len(generated)} draft fixtures using {format_type}. Please review before publishing.", 'success')
    except ValueError as e:
        flash(f"Fixture generation failed: {str(e)}", 'danger')

    return redirect(url_for('admin.fixtures_management'))

@admin_bp.route('/fixtures/publish', methods=['POST'])
@login_required
@admin_required
def publish_all_fixtures():
    try:
        count = publish_fixtures(current_user.id)
        flash(f"Successfully published {count} fixtures to public portal! 📅", 'success')
    except ValueError as e:
        flash(f"Publish failed: {str(e)}", 'danger')

    return redirect(url_for('admin.fixtures_management'))

@admin_bp.route('/fixtures/unpublish', methods=['POST'])
@login_required
@admin_required
def unpublish_all_fixtures():
    try:
        count = unpublish_fixtures(current_user.id)
        flash(f"Unpublished {count} fixtures.", 'info')
    except ValueError as e:
        flash(f"Unpublish failed: {str(e)}", 'danger')

    return redirect(url_for('admin.fixtures_management'))

# 5. FINAL AUCTION SUMMARY & REPORT
@admin_bp.route('/auction-summary', methods=['GET'])
@login_required
@admin_required
def auction_summary():
    total_registered = Player.query.count()
    total_sold = Player.query.filter_by(status=PlayerStatus.SOLD).count()
    total_unsold = Player.query.filter_by(status=PlayerStatus.UNSOLD).count()
    final_unsold = Player.query.filter_by(status=PlayerStatus.FINAL_UNSOLD).count()

    second_chance_sold = AuditLog.query.filter_by(action='SECOND_CHANCE_PLAYER_SOLD').count()

    franchises = Franchise.query.order_by(Franchise.id.asc()).all()
    franchise_summaries = []

    all_prices = []
    for f in franchises:
        players = Player.query.filter_by(sold_to=f.id).all()
        prices = [p.sold_price for p in players if p.sold_price is not None]
        all_prices.extend(prices)

        franchise_summaries.append({
            'franchise': f,
            'squad_count': len(players),
            'spent': f.spent_purse,
            'remaining': f.remaining_purse,
            'highest_purchase': max(prices) if prices else 0.0,
            'lowest_purchase': min(prices) if prices else 0.0
        })

    highest_purchase = max(all_prices) if all_prices else 0.0
    lowest_purchase = min(all_prices) if all_prices else 0.0
    total_money_spent = sum(all_prices)

    transactions = Transaction.query.order_by(Transaction.created_at.desc()).all()
    sold_players = Player.query.filter_by(status=PlayerStatus.SOLD).order_by(Player.id.desc()).all()

    return render_template(
        'admin/auction_summary.html',
        total_registered=total_registered,
        total_sold=total_sold,
        total_unsold=total_unsold,
        second_chance_sold=second_chance_sold,
        final_unsold=final_unsold,
        franchise_summaries=franchise_summaries,
        highest_purchase=highest_purchase,
        lowest_purchase=lowest_purchase,
        total_money_spent=total_money_spent,
        transactions=transactions,
        sold_players=sold_players
    )

@admin_bp.route('/auction-summary/download', methods=['GET'])
@login_required
@admin_required
def download_auction_report():
    players = Player.query.order_by(Player.roll_number.asc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Roll Number', 'Player Name', 'Role', 'Category', 'Branch', 'Year', 'Status', 'Franchise', 'Purchase Price'])

    for p in players:
        franchise_name = p.franchise.name if p.franchise else '---'
        if p.is_captain:
            role_str = f"{p.role} (CAPTAIN)"
            sold_price_str = "-"
        else:
            role_str = p.role
            sold_price_str = f"Rs. {p.sold_price:,.0f}" if p.sold_price is not None else 'N/A'

        writer.writerow([
            p.roll_number,
            p.name,
            role_str,
            p.category,
            p.branch or '---',
            p.year or '---',
            p.status,
            franchise_name,
            sold_price_str
        ])

    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = 'attachment; filename=SPL_Auction_Report.csv'
    response.headers['Content-type'] = 'text/csv'
    return response

# ==================== PHASE 7 MODULES ====================

# 1. ADMIN SECURITY & PASSWORD CHANGE
@admin_bp.route('/settings/security', methods=['GET', 'POST'])
@login_required
@admin_required
def security_settings():
    is_default_admin = current_user.check_password('SPLAdmin@2026!')

    if request.method == 'POST':
        current_pass = request.form.get('current_password', '')
        new_pass = request.form.get('new_password', '')
        confirm_pass = request.form.get('confirm_password', '')

        if not current_user.check_password(current_pass):
            flash('Current password is incorrect.', 'danger')
            return redirect(url_for('admin.security_settings'))

        if len(new_pass) < 10:
            flash('New password must be at least 10 characters in length.', 'danger')
            return redirect(url_for('admin.security_settings'))

        if not (re.search(r'[A-Z]', new_pass) and re.search(r'[a-z]', new_pass) and re.search(r'[0-9]', new_pass) and re.search(r'[^A-Za-z0-9]', new_pass)):
            flash('New password must contain uppercase, lowercase, number, and special character.', 'danger')
            return redirect(url_for('admin.security_settings'))

        if new_pass != confirm_pass:
            flash('New password and confirmation do not match.', 'danger')
            return redirect(url_for('admin.security_settings'))

        current_user.set_password(new_pass)
        db.session.commit()
        log_audit(current_user.id, 'PASSWORD_CHANGED', 'User', current_user.id, None, 'Admin password changed successfully')
        flash('Admin password updated successfully! Please keep your new credentials secure.', 'success')
        return redirect(url_for('admin.security_settings'))

    return render_template(
        'admin/change_password.html',
        is_default_admin=is_default_admin
    )

# 2. USER & FRANCHISE LOGIN MANAGEMENT
@admin_bp.route('/users', methods=['GET'])
@login_required
@admin_required
def users_management():
    users = User.query.order_by(User.id.asc()).all()
    franchises = Franchise.query.filter_by(is_active=True).all()
    return render_template(
        'admin/users.html',
        users=users,
        franchises=franchises
    )

@admin_bp.route('/users/create', methods=['POST'])
@login_required
@admin_required
def create_user():
    username = request.form.get('username', '').strip().lower()
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '').strip()
    role = request.form.get('role', 'FRANCHISE').strip().upper()
    franchise_id = request.form.get('franchise_id')

    if not username:
        flash('Username is required.', 'danger')
        return redirect(url_for('admin.users_management'))

    if not email:
        flash('Email address is required.', 'danger')
        return redirect(url_for('admin.users_management'))

    if User.query.filter_by(username=username).first():
        flash(f"Username '{username}' already exists.", 'danger')
        return redirect(url_for('admin.users_management'))

    if User.query.filter(User.email.ilike(email)).first():
        flash(f"Email '{email}' is already registered.", 'danger')
        return redirect(url_for('admin.users_management'))

    f_id = int(franchise_id) if franchise_id and franchise_id.isdigit() else None
    display_name = username.title()
    if f_id:
        f_obj = db.session.get(Franchise, f_id)
        if f_obj:
            display_name = f_obj.name

    user = User(
        username=username,
        email=email,
        display_name=display_name,
        role=role,
        franchise_id=f_id,
        is_active=True
    )
    if password and len(password) >= 6:
        user.set_password(password)

    db.session.add(user)
    db.session.commit()

    log_audit(current_user.id, 'USER_CREATED', 'User', user.id, None, f"User {username} created ({role})")
    flash(f"User account '{username}' created successfully.", 'success')
    return redirect(url_for('admin.users_management'))

@admin_bp.route('/users/<int:id>/edit', methods=['POST'])
@login_required
@admin_required
def edit_user(id):
    """Edit a user account atomically — syncs Franchise.authorized_email when email changes."""
    user = db.session.get(User, id)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('admin.users_management'))

    old_email = (user.email or '').strip().lower()
    old_data = {
        'email': user.email,
        'display_name': user.display_name,
        'role': user.role,
        'franchise_id': user.franchise_id,
    }

    new_email       = (request.form.get('email') or '').strip().lower()
    new_display_name = (request.form.get('display_name') or '').strip()
    new_role        = (request.form.get('role') or user.role).strip().upper()
    franchise_id_raw = request.form.get('franchise_id', '')
    new_franchise_id = int(franchise_id_raw) if franchise_id_raw and franchise_id_raw.isdigit() else None

    # ── Validation ────────────────────────────────────────────────────────────
    if not new_email:
        flash('Email address cannot be empty.', 'danger')
        return redirect(url_for('admin.users_management'))

    # Uniqueness check — ignore this user's current email
    conflict = User.query.filter(
        User.email.ilike(new_email),
        User.id != user.id
    ).first()
    if conflict:
        flash(
            f"Email '{new_email}' is already registered to account "
            f"'{conflict.username}'. Please use a different email.",
            'danger'
        )
        return redirect(url_for('admin.users_management'))

    # ── Atomic update (all changes in one transaction) ────────────────────────
    try:
        email_changed = (new_email != old_email)

        # 1. Update the User record
        user.email = new_email
        if new_display_name:
            user.display_name = new_display_name
        user.role = new_role
        user.franchise_id = new_franchise_id

        # 2. Sync Franchise.authorized_email when the email actually changed
        #    — update the franchise this user is currently assigned to
        if email_changed and new_franchise_id:
            franchise = db.session.get(Franchise, new_franchise_id)
            if franchise and (franchise.authorized_email or '').strip().lower() == old_email:
                franchise.authorized_email = new_email
                log_audit(
                    current_user.id, 'FRANCHISE_EMAIL_SYNCED', 'Franchise',
                    franchise.id, {'authorized_email': old_email},
                    {'authorized_email': new_email}
                )

        # 3. If the old email was the authorized email of a *different* franchise
        #    (e.g., user is being re-assigned), also update that franchise
        if email_changed and old_email:
            old_franchise = Franchise.query.filter(
                Franchise.authorized_email.ilike(old_email)
            ).first()
            if old_franchise and (new_franchise_id is None or old_franchise.id != new_franchise_id):
                old_franchise.authorized_email = new_email
                log_audit(
                    current_user.id, 'FRANCHISE_EMAIL_SYNCED', 'Franchise',
                    old_franchise.id, {'authorized_email': old_email},
                    {'authorized_email': new_email}
                )

        db.session.commit()

        log_audit(
            current_user.id, 'USER_EDITED', 'User', user.id, old_data,
            {
                'email': user.email,
                'display_name': user.display_name,
                'role': user.role,
                'franchise_id': user.franchise_id,
            }
        )
        flash(
            f"Account '{user.username}' updated successfully."
            + (" Email synced across franchise records." if email_changed else ""),
            'success'
        )

    except Exception as e:
        db.session.rollback()
        log_audit(
            current_user.id, 'USER_EDIT_FAILED', 'User', user.id, old_data,
            {'error': str(e)}, status='FAILED'
        )
        flash(f"Failed to update account: {e}", 'danger')

    return redirect(url_for('admin.users_management'))

@admin_bp.route('/users/<int:id>/toggle-status', methods=['POST'])
@login_required
@admin_required
def toggle_user_status(id):
    user = User.query.get_or_404(id)
    if user.id == current_user.id:
        flash('You cannot deactivate your own logged-in admin account.', 'danger')
        return redirect(url_for('admin.users_management'))

    user.is_active = not user.is_active
    db.session.commit()

    action_str = 'USER_ENABLED' if user.is_active else 'USER_DISABLED'
    log_audit(current_user.id, action_str, 'User', user.id, None, f"Status set to {user.is_active}")
    flash(f"User '{user.username}' status set to {'ACTIVE' if user.is_active else 'INACTIVE'}.", 'info')
    return redirect(url_for('admin.users_management'))

@admin_bp.route('/users/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_user(id):
    user = User.query.get_or_404(id)

    if user.id == current_user.id:
        flash('You cannot delete your own logged-in admin account.', 'danger')
        return redirect(url_for('admin.users_management'))

    if user.is_admin or user.role == 'ADMIN':
        active_admins_count = User.query.filter(User.role == 'ADMIN', User.id != user.id, User.is_active == True).count()
        if active_admins_count == 0:
            flash('Cannot delete the last active administrator account.', 'danger')
            return redirect(url_for('admin.users_management'))

    username = user.username
    user_data = user.to_dict()

    # 1. Take database backup snapshot before deleting
    backup_file = create_database_backup(current_user.id)
    save_deleted_record('User', user_data, current_user.id, backup_file)

    # 2. Detach franchise link if any
    user.franchise_id = None

    # 3. Delete user
    db.session.delete(user)
    db.session.commit()

    log_audit(current_user.id, 'DELETE_USER', 'User', id, username, f"Backup saved: {backup_file}")
    flash(f"User account '{username}' deleted successfully. Backup snapshot '{backup_file}' created.", 'success')
    return redirect(url_for('admin.users_management'))

# 3. AUCTION & PURSE INTEGRITY AUDIT
@admin_bp.route('/system/auction-check', methods=['GET'])
@login_required
@admin_required
def auction_integrity_audit():
    is_passed, report = run_deep_auction_check()
    return render_template(
        'admin/auction_check.html',
        is_passed=is_passed,
        report=report
    )


# 5. EVENT CONTROL PANEL
@admin_bp.route('/event-control', methods=['GET'])
@login_required
@admin_required
def event_control_panel():
    state_obj = AuctionState.query.first()
    player = Player.query.get(state_obj.active_player_id) if state_obj and state_obj.active_player_id else None
    highest_bidder = Franchise.query.get(state_obj.highest_bidder_id) if state_obj and state_obj.highest_bidder_id else None

    total_sold = Player.query.filter_by(status=PlayerStatus.SOLD).count()
    total_unsold = Player.query.filter_by(status=PlayerStatus.UNSOLD).count()
    is_sc = SystemSettings.get_setting('second_chance_active') == 'true'
    is_locked = SystemSettings.get_setting('squads_locked') == 'true'
    fixtures_published = Fixture.query.filter_by(is_published=True).count() > 0
    event_state = SystemSettings.get_setting('event_state', 'SETUP')

    franchises = Franchise.query.all()
    squad_stats = []
    for f in franchises:
        squad_stats.append({
            'franchise': f,
            'squad_count': f.squad_count,
            'remaining_purse': f.remaining_purse
        })

    return render_template(
        'admin/event_control.html',
        state=event_state,
        current_player=player,
        current_bid=state_obj.current_bid if state_obj else 0,
        highest_bidder=highest_bidder,
        total_sold=total_sold,
        total_unsold=total_unsold,
        is_sc=is_sc,
        is_locked=is_locked,
        fixtures_published=fixtures_published,
        squad_stats=squad_stats
    )


@admin_bp.route('/event-control/state', methods=['POST'])
@login_required
@admin_required
def update_event_state():
    new_state = request.form.get('state')
    if new_state:
        SystemSettings.set_setting('event_state', new_state)
        log_audit(current_user.id, 'UPDATE_EVENT_STATE', 'SystemSettings', None, None, f"Event state updated to {new_state}")
        flash(f"Event state successfully updated to {new_state}", "success")
    return redirect(url_for('admin.event_control_panel'))

# 6. DATABASE BACKUP & RESTORE
@admin_bp.route('/backup', methods=['GET'])
@login_required
@admin_required
def backup_dashboard():
    backups = list_backups()
    deleted_records = list_deleted_records()
    return render_template(
        'admin/backup.html',
        backups=backups,
        deleted_records=deleted_records
    )

@admin_bp.route('/backup/create', methods=['POST'])
@login_required
@admin_required
def trigger_backup():
    try:
        filename = create_database_backup(current_user.id)
        flash(f"Database backup snapshot '{filename}' created successfully in instance/backups directory.", 'success')
    except Exception as e:
        flash(f"Backup failed: {str(e)}", 'danger')

    return redirect(url_for('admin.backup_dashboard'))

@admin_bp.route('/backup/restore', methods=['POST'])
@login_required
@admin_required
def trigger_restore():
    filename = request.form.get('filename')
    reason = request.form.get('reason', '').strip()
    try:
        restore_database_backup(filename, current_user.id, reason)
        flash(f"Database restored successfully from '{filename}'.", 'warning')
    except Exception as e:
        flash(f"Restore failed: {str(e)}", 'danger')

    return redirect(url_for('admin.backup_dashboard'))


