import os
from flask import Blueprint, render_template, request, jsonify, abort, flash, redirect, url_for, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app.extensions import db
from app.models import Franchise, Player, Bid, Transaction, AuctionState, AuctionStatus, PlayerRole, PlayerCategory
from app.utils.decorators import franchise_required
from app.services.audit_service import log_audit

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in current_app.config.get('ALLOWED_EXTENSIONS', {'png', 'jpg', 'jpeg', 'webp', 'svg'})


franchise_bp = Blueprint('franchise', __name__, url_prefix='/franchise')

def get_current_franchise():
    """Strictly retrieve authenticated user's assigned franchise from DB."""
    if not current_user.is_authenticated or not current_user.franchise_id:
        abort(403)
    franchise = Franchise.query.get(current_user.franchise_id)
    if not franchise or not franchise.is_active:
        abort(403)
    return franchise

# ==================== HTML DASHBOARD ROUTES ====================

@franchise_bp.route('/dashboard')
@login_required
@franchise_required
def dashboard():
    franchise = get_current_franchise()
    franchise.recalculate_purse()
    auction_state = AuctionState.query.first()
    auction_status = auction_state.status if auction_state else AuctionStatus.WAITING

    # Purse progress percentage
    spent_pct = (franchise.spent_purse / franchise.starting_purse * 100) if franchise.starting_purse > 0 else 0
    is_low_purse = (franchise.remaining_purse < 50000.0)

    # Squad slots
    slots_left = max(0, franchise.squad_limit - franchise.squad_count)

    # Average player price (excluding captain who has dash price)
    purchased_count = franchise.sold_players.filter(Player.sold_price > 0).count()
    avg_price = (franchise.spent_purse / purchased_count) if purchased_count > 0 else 0.0

    # Recent purchases (last 5)
    recent_purchases = franchise.sold_players.filter(Player.sold_price > 0).order_by(Player.created_at.desc()).limit(5).all()

    # Recent bids (last 5)
    recent_bids = Bid.query.filter_by(franchise_id=franchise.id).order_by(Bid.created_at.desc()).limit(5).all()

    return render_template(
        'franchise/dashboard.html',
        franchise=franchise,
        auction_status=auction_status,
        spent_pct=round(spent_pct, 1),
        is_low_purse=is_low_purse,
        slots_left=slots_left,
        avg_price=avg_price,
        recent_purchases=recent_purchases,
        recent_bids=recent_bids
    )

@franchise_bp.route('/squad')
@login_required
@franchise_required
def squad():
    franchise = get_current_franchise()
    franchise.recalculate_purse()
    sort_by = request.args.get('sort_by', 'latest').strip()

    query = Player.query.filter_by(sold_to=franchise.id)

    if sort_by == 'price_high':
        query = query.order_by(Player.sold_price.desc())
    elif sort_by == 'price_low':
        query = query.order_by(Player.sold_price.asc())
    elif sort_by == 'name':
        query = query.order_by(Player.name.asc())
    elif sort_by == 'role':
        query = query.order_by(Player.role.asc())
    else:  # latest
        query = query.order_by(Player.id.desc())

    players = list(query.all())

    # Ensure Captain is always included and at the top for default view
    cap = franchise.captain_player
    if cap and cap not in players:
        players.insert(0, cap)
    elif sort_by == 'latest':
        players.sort(key=lambda p: (0 if p.is_captain else 1, -p.id))

    # Role Composition Analytics
    role_counts = {
        PlayerRole.BATSMAN: sum(1 for p in players if p.role == PlayerRole.BATSMAN),
        PlayerRole.BOWLER: sum(1 for p in players if p.role == PlayerRole.BOWLER),
        PlayerRole.ALL_ROUNDER: sum(1 for p in players if p.role == PlayerRole.ALL_ROUNDER),
        PlayerRole.WICKETKEEPER: sum(1 for p in players if p.role == PlayerRole.WICKETKEEPER)
    }

    # Role Spending Analytics
    role_spending = {
        PlayerRole.BATSMAN: sum(p.sold_price or 0 for p in players if p.role == PlayerRole.BATSMAN),
        PlayerRole.BOWLER: sum(p.sold_price or 0 for p in players if p.role == PlayerRole.BOWLER),
        PlayerRole.ALL_ROUNDER: sum(p.sold_price or 0 for p in players if p.role == PlayerRole.ALL_ROUNDER),
        PlayerRole.WICKETKEEPER: sum(p.sold_price or 0 for p in players if p.role == PlayerRole.WICKETKEEPER)
    }

    purchased_players = [p for p in players if not p.is_captain and (p.sold_price or 0) > 0]
    avg_price = (franchise.spent_purse / len(purchased_players)) if purchased_players else 0.0
    highest_purchase = max([p.sold_price or 0 for p in purchased_players], default=0.0)
    lowest_purchase = min([p.sold_price or 0 for p in purchased_players], default=0.0) if purchased_players else 0.0

    return render_template(
        'franchise/squad.html',
        franchise=franchise,
        players=players,
        sort_by=sort_by,
        role_counts=role_counts,
        role_spending=role_spending,
        avg_price=avg_price,
        highest_purchase=highest_purchase,
        lowest_purchase=lowest_purchase
    )

@franchise_bp.route('/purchases')
@login_required
@franchise_required
def purchases():
    franchise = get_current_franchise()
    purchase_txs = Transaction.query.filter(
        Transaction.franchise_id == franchise.id,
        Transaction.type.in_(['PLAYER_PURCHASE', 'PURCHASE'])
    ).order_by(Transaction.created_at.desc()).all()

    return render_template(
        'franchise/purchases.html',
        franchise=franchise,
        purchases=purchase_txs
    )

@franchise_bp.route('/bids')
@login_required
@franchise_required
def bids():
    franchise = get_current_franchise()
    bid_list = Bid.query.filter_by(franchise_id=franchise.id).order_by(Bid.created_at.desc()).all()
    auction_state = AuctionState.query.first()

    # Calculate status for each bid record
    processed_bids = []
    for b in bid_list:
        if b.player and b.player.status == 'SOLD':
            result_status = 'SOLD' if b.player.sold_to == franchise.id and b.amount == b.player.sold_price else 'OUTBID'
        elif b.player and b.player.status == 'UNSOLD':
            result_status = 'UNSOLD'
        elif auction_state and auction_state.active_player_id == b.player_id:
            result_status = 'WINNING' if auction_state.highest_bidder_id == franchise.id and auction_state.current_bid == b.amount else 'OUTBID'
        else:
            result_status = 'OUTBID'

        processed_bids.append({
            'id': b.id,
            'player': b.player,
            'amount': b.amount,
            'created_at': b.created_at,
            'status': result_status
        })

    return render_template(
        'franchise/bids.html',
        franchise=franchise,
        bids=processed_bids
    )

@franchise_bp.route('/activity')
@login_required
@franchise_required
def activity():
    franchise = get_current_franchise()
    bids = Bid.query.filter_by(franchise_id=franchise.id).order_by(Bid.created_at.desc()).limit(20).all()
    txs = Transaction.query.filter_by(franchise_id=franchise.id).order_by(Transaction.created_at.desc()).limit(20).all()

    events = []
    for b in bids:
        events.append({
            'timestamp': b.created_at,
            'type': 'BID',
            'title': f"Placed bid of Rs. {b.amount:,.0f}",
            'subtitle': f"Player: {b.player.name if b.player else 'N/A'}"
        })
    for t in txs:
        events.append({
            'timestamp': t.created_at,
            'type': 'PURCHASE',
            'title': f"Acquired {t.player.name if t.player else 'Player'} for Rs. {t.amount:,.0f}",
            'subtitle': "Official Transaction Log"
        })

    events.sort(key=lambda x: x['timestamp'], reverse=True)

    return render_template(
        'franchise/activity.html',
        franchise=franchise,
        events=events
    )

@franchise_bp.route('/profile', methods=['GET', 'POST'])
@login_required
@franchise_required
def profile():
    franchise = get_current_franchise()
    if request.method == 'POST':
        captain_name = request.form.get('captain_name', '').strip()
        captain_rule_number = request.form.get('captain_rule_number', '').strip() or request.form.get('captain_roll_number', '').strip()
        captain_category = request.form.get('captain_category', '').strip().upper()
        captain_department = request.form.get('captain_department', '').strip() or request.form.get('captain_branch', '').strip()
        captain_year = request.form.get('captain_year', '').strip()

        # Logo file upload
        if 'logo_file' in request.files:
            logo_file = request.files.get('logo_file')
            if logo_file and logo_file.filename and allowed_file(logo_file.filename):
                logo_fname = secure_filename(f"logo_{franchise.short_name}_{logo_file.filename}")
                logo_file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], logo_fname))
                franchise.logo = logo_fname
        elif request.form.get('logo_url'):
            franchise.logo = request.form.get('logo_url').strip()

        # Captain photo upload
        captain_photo = None
        if 'captain_photo' in request.files:
            captain_file = request.files.get('captain_photo')
            if captain_file and captain_file.filename and allowed_file(captain_file.filename):
                cap_fname = secure_filename(f"captain_{franchise.short_name}_{captain_file.filename}")
                captain_file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], cap_fname))
                franchise.captain_photo = cap_fname
                captain_photo = cap_fname

        if captain_name:
            from app.services.team_service import add_team_captain
            try:
                add_team_captain(
                    franchise=franchise,
                    name=captain_name,
                    rule_number=captain_rule_number,
                    department=captain_department,
                    year=captain_year,
                    category=captain_category,
                    photo=captain_photo or franchise.captain_photo,
                    actor_id=current_user.id
                )
            except ValueError as e:
                flash(str(e), 'danger')
                return redirect(url_for('franchise.profile'))
        else:
            db.session.commit()

        log_audit(current_user.id, 'FRANCHISE_PROFILE_UPDATED', 'Franchise', franchise.id, None, f"Profile updated by {current_user.email}", franchise_id=franchise.id)
        flash('Franchisee profile updated successfully!', 'success')
        return redirect(url_for('franchise.profile'))

    return render_template('franchise/profile.html', franchise=franchise)

@franchise_bp.route('/add-captain', methods=['POST'])
@login_required
@franchise_required
def add_captain():
    franchise = get_current_franchise()
    name = request.form.get('captain_name', '').strip()
    rule_number = request.form.get('captain_rule_number', '').strip() or request.form.get('captain_roll_number', '').strip()
    department = request.form.get('captain_department', '').strip() or request.form.get('captain_branch', '').strip()
    year = request.form.get('captain_year', '').strip()
    category = request.form.get('captain_category', 'NORMAL').strip().upper()

    photo_fname = None
    if 'captain_photo' in request.files:
        photo_file = request.files.get('captain_photo')
        if photo_file and photo_file.filename and allowed_file(photo_file.filename):
            photo_fname = secure_filename(f"captain_{franchise.short_name}_{photo_file.filename}")
            photo_file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], photo_fname))

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
        flash(f'✓ Team Captain "{name}" added successfully! Team is now ELIGIBLE FOR BIDDING.', 'success')
    except ValueError as e:
        flash(str(e), 'danger')

    next_url = request.form.get('next') or request.referrer or url_for('franchise.squad')
    return redirect(next_url)

@franchise_bp.route('/add-member', methods=['POST'])
@login_required
@franchise_required
def add_member():
    franchise = get_current_franchise()
    name = request.form.get('name', '').strip()
    rule_number = request.form.get('rule_number', '').strip() or request.form.get('roll_number', '').strip()
    department = request.form.get('branch', '').strip() or request.form.get('department', '').strip()
    year = request.form.get('year', '').strip()
    role = request.form.get('role', 'BATSMAN').strip().upper()
    category = request.form.get('category', 'NORMAL').strip().upper()

    photo_fname = None
    if 'photo' in request.files:
        photo_file = request.files.get('photo')
        if photo_file and photo_file.filename and allowed_file(photo_file.filename):
            photo_fname = secure_filename(f"member_{franchise.short_name}_{photo_file.filename}")
            photo_file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], photo_fname))

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
        flash(f'Team Member "{player.name}" added successfully ({franchise.squad_count}/{franchise.squad_limit} Members).', 'success')
    except ValueError as e:
        flash(str(e), 'danger')

    next_url = request.form.get('next') or request.referrer or url_for('franchise.squad')
    return redirect(next_url)

# ==================== FRANCHISE JSON APIs ====================

@franchise_bp.route('/api/dashboard')
@login_required
@franchise_required
def api_dashboard():
    franchise = get_current_franchise()
    return jsonify({
        'id': franchise.id,
        'name': franchise.name,
        'short_name': franchise.short_name,
        'starting_purse': franchise.starting_purse,
        'spent_purse': franchise.spent_purse,
        'remaining_purse': franchise.remaining_purse,
        'squad_count': franchise.squad_count,
        'squad_limit': franchise.squad_limit,
        'authorized_email': franchise.authorized_email
    })

@franchise_bp.route('/api/squad')
@login_required
@franchise_required
def api_squad():
    franchise = get_current_franchise()
    players = [p.to_dict() for p in franchise.sold_players.all()]
    return jsonify({'squad': players})
