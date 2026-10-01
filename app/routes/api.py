from datetime import datetime
from flask import Blueprint, jsonify, request, current_app
from flask_login import current_user, login_required
from app.models import AuctionStatus, Franchise, Player, PlayerStatus, SystemSettings, Bid, AuditLog
from app.utils.decorators import admin_required, franchise_required
from app.services.auction_service import (
    get_auction_state, find_player_by_roll, activate_player, start_bidding,
    pause_auction, resume_auction, extend_timer, place_bid, finalize_sold, finalize_unsold, reset_to_waiting,
    clear_sold_player, update_player_rule_number,
    find_second_chance_player_by_roll, start_second_chance_auction, end_second_chance_auction, get_next_bid_increment
)

api_bp = Blueprint('api', __name__, url_prefix='/api')

@api_bp.route('/auction/state', methods=['GET'])
def get_state():
    """
    Role-customized live polling endpoint.
    Returns JSON state for public projector display, franchise dashboards, and admin console.
    Strictly prohibits exposing future players, player queues, or hidden database data.
    """
    state = get_auction_state()

    # Auto-finalize when 10-second timer expires during active bidding
    if state.status == AuctionStatus.BIDDING and state.remaining_seconds == 0 and state.timer_end is not None:
        admin_id = current_user.id if current_user.is_authenticated and current_user.is_admin else 1
        if state.highest_bidder_id:
            try:
                finalize_sold(admin_id)
            except Exception:
                pass
        else:
            try:
                finalize_unsold(admin_id)
            except Exception:
                pass
        state = get_auction_state()

    # Auto-clear sold player when 10-second post-sale timer expires (Requirements 1, 7, 8)
    if state.status == AuctionStatus.SOLD and state.sold_display_until:
        if datetime.utcnow() >= state.sold_display_until:
            admin_id = current_user.id if current_user.is_authenticated and hasattr(current_user, 'is_admin') and current_user.is_admin else 1
            try:
                clear_sold_player(admin_id)
            except Exception:
                pass
            state = get_auction_state()

    player = Player.query.get(state.active_player_id) if state.active_player_id else None
    highest_bidder = Franchise.query.get(state.highest_bidder_id) if state.highest_bidder_id else None

    # Version timestamp for polling optimization
    version_ts = int(state.updated_at.timestamp()) if state.updated_at else 0

    # Calculate Next Required Bid Amount
    increment = get_next_bid_increment(state.current_bid)
    if not highest_bidder and player:
        next_valid_bid = float(player.base_price or 10000.0)
    else:
        next_valid_bid = state.current_bid + increment

    # Determine Top Two Bidders for active player
    second_highest_bidder = None
    if state.active_player_id:
        recent_bids = Bid.query.filter_by(player_id=state.active_player_id).order_by(Bid.id.desc()).all()
        for b in recent_bids:
            if highest_bidder and b.franchise_id != highest_bidder.id:
                second_f = Franchise.query.get(b.franchise_id)
                if second_f:
                    second_highest_bidder = {
                        'id': second_f.id,
                        'name': second_f.name,
                        'short_name': second_f.short_name,
                        'logo': second_f.logo,
                        'amount': b.amount
                    }
                    break

    # Determine Winning Franchise if SOLD
    winning_franchise = None
    if player and player.status == 'SOLD':
        win_f = Franchise.query.get(player.sold_to) if player.sold_to else highest_bidder
        if win_f:
            winning_franchise = {
                'id': win_f.id,
                'name': win_f.name,
                'short_name': win_f.short_name,
                'logo': win_f.logo
            }
    elif state.status == 'SOLD' and highest_bidder:
        winning_franchise = {
            'id': highest_bidder.id,
            'name': highest_bidder.name,
            'short_name': highest_bidder.short_name,
            'logo': highest_bidder.logo
        }

    # Base Public State
    res = {
        'status': state.status,
        'current_bid': state.current_bid,
        'remaining_seconds': state.remaining_seconds,
        'event_name': SystemSettings.get_setting('event_name', 'SPL'),
        'event_subtitle': SystemSettings.get_setting('event_subtitle', 'Sphoorthy Premier League'),
        'version': version_ts,
        'increment': increment,
        'next_valid_bid': next_valid_bid,
        'active_player': player.to_dict() if player else None,
        'highest_bidder': {
            'id': highest_bidder.id,
            'name': highest_bidder.name,
            'short_name': highest_bidder.short_name,
            'logo': highest_bidder.logo,
            'amount': state.current_bid
        } if highest_bidder else None,
        'second_highest_bidder': second_highest_bidder,
        'sold_display_until': state.sold_display_until.isoformat() if state.sold_display_until else None,
        'sold_until_timestamp': int(state.sold_display_until.timestamp() * 1000) if state.sold_display_until else None,
        'sold_remaining_seconds': state.sold_remaining_seconds,
        'winning_franchise': winning_franchise,
        'sold_price': player.sold_price if player and player.status == 'SOLD' else state.current_bid
    }

    # All active registered franchises with real-time purse & eligibility
    # All active registered franchises with real-time purse & eligibility
    all_franchises = Franchise.query.filter_by(is_active=True).order_by(Franchise.id.asc()).all()
    res['franchises'] = []
    for f in all_franchises:
        can_bid = True
        cannot_reason = None

        if not f.has_captain:
            can_bid = False
            cannot_reason = 'Team Captain Required'
        elif state.highest_bidder_id == f.id:
            can_bid = False
            cannot_reason = 'Current Leader'
        elif f.squad_count >= f.squad_limit:
            can_bid = False
            cannot_reason = '15 / 15 Members (Team Full)'
        elif f.remaining_purse < next_valid_bid:
            can_bid = False
            cannot_reason = 'Low Purse'
        elif state.status != AuctionStatus.BIDDING or (state.remaining_seconds or 0) <= 0:
            can_bid = False
            cannot_reason = 'Auction Not Accepting Bids'

        res['franchises'].append({
            'id': f.id,
            'name': f.name,
            'short_name': f.short_name,
            'logo': f.logo,
            'remaining_purse': f.remaining_purse,
            'spent_purse': f.spent_purse,
            'squad_count': f.squad_count,
            'squad_limit': f.squad_limit,
            'has_captain': f.has_captain,
            'captain_name': f.captain_name or (f.captain.name if f.captain else None),
            'is_eligible_for_bidding': f.is_eligible_for_bidding,
            'can_bid': can_bid,
            'is_highest_bidder': (state.highest_bidder_id == f.id),
            'cannot_bid_reason': cannot_reason
        })

    # Franchise-Specific State Additions
    if current_user.is_authenticated and current_user.is_franchise and current_user.franchise_id:
        franchise = Franchise.query.get(current_user.franchise_id)
        if franchise:
            can_bid = True
            cannot_bid_reason = None

            if not franchise.has_captain:
                can_bid = False
                cannot_bid_reason = "Team Captain Required"
            elif state.status != AuctionStatus.BIDDING:
                can_bid = False
                cannot_bid_reason = f"Auction is currently {state.status}"
            elif state.remaining_seconds <= 0:
                can_bid = False
                cannot_bid_reason = "Time Expired"
            elif not franchise.is_active:
                can_bid = False
                cannot_bid_reason = "Franchise Inactive"
            elif franchise.squad_count >= franchise.squad_limit:
                can_bid = False
                cannot_bid_reason = f"Squad Limit Reached ({franchise.squad_count}/{franchise.squad_limit}) - Team Full"
            elif franchise.remaining_purse < next_valid_bid:
                can_bid = False
                cannot_bid_reason = f"Insufficient Purse (Need ₹{next_valid_bid:,.0f})"
            elif state.highest_bidder_id == franchise.id:
                can_bid = False
                cannot_bid_reason = "You are Highest Bidder"

            res['franchise_info'] = {
                'id': franchise.id,
                'name': franchise.name,
                'short_name': franchise.short_name,
                'remaining_purse': franchise.remaining_purse,
                'spent_purse': franchise.spent_purse,
                'squad_count': franchise.squad_count,
                'squad_limit': franchise.squad_limit,
                'can_bid': can_bid,
                'cannot_bid_reason': cannot_bid_reason,
                'is_highest_bidder': (state.highest_bidder_id == franchise.id)
            }

    # Admin-Specific Additions (Recent Bids for active player)
    if current_user.is_authenticated and current_user.is_admin and player:
        recent_bids = Bid.query.filter_by(player_id=player.id).order_by(Bid.created_at.desc()).limit(10).all()
        res['recent_bids'] = [{
            'id': b.id,
            'franchise_name': b.franchise.name if b.franchise else 'Unknown',
            'franchise_short': b.franchise.short_name if b.franchise else '---',
            'amount': b.amount,
            'timestamp': b.created_at.strftime('%H:%M:%S')
        } for b in recent_bids]

    return jsonify(res)

@api_bp.route('/auction/find-player', methods=['POST'])
@login_required
@admin_required
def api_find_player():
    data = request.get_json() or request.form
    roll_number = data.get('roll_number')
    try:
        player = find_player_by_roll(roll_number)
        return jsonify({'success': True, 'player': player.to_dict()})
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@api_bp.route('/auction/activate', methods=['POST'])
@login_required
@admin_required
def api_activate_player():
    data = request.get_json() or request.form
    player_id = data.get('player_id')
    try:
        state = activate_player(player_id, current_user.id)
        return jsonify({'success': True, 'status': state.status})
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@api_bp.route('/auction/start', methods=['POST'])
@login_required
@admin_required
def api_start_bidding():
    try:
        state = start_bidding(current_user.id)
        return jsonify({'success': True, 'status': state.status, 'timer_seconds': state.timer_seconds})
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@api_bp.route('/auction/pause', methods=['POST'])
@login_required
@admin_required
def api_pause_auction():
    try:
        state = pause_auction(current_user.id)
        return jsonify({'success': True, 'status': state.status, 'paused_seconds_left': state.paused_seconds_left})
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@api_bp.route('/auction/resume', methods=['POST'])
@login_required
@admin_required
def api_resume_auction():
    try:
        state = resume_auction(current_user.id)
        return jsonify({'success': True, 'status': state.status, 'remaining_seconds': state.remaining_seconds})
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@api_bp.route('/auction/extend', methods=['POST'])
@login_required
@admin_required
def api_extend_timer():
    data = request.get_json() or request.form
    try:
        seconds = int(data.get('seconds', 10))
        state = extend_timer(seconds, current_user.id)
        return jsonify({'success': True, 'remaining_seconds': state.remaining_seconds})
    except (ValueError, TypeError) as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@api_bp.route('/auction/bid', methods=['POST'])
@login_required
@franchise_required
def api_place_bid():
    data = request.get_json() or request.form
    try:
        amount = float(data.get('amount'))
        state = place_bid(current_user.franchise_id, amount)
        return jsonify({
            'success': True,
            'current_bid': state.current_bid,
            'highest_bidder_id': state.highest_bidder_id
        })
    except (ValueError, TypeError) as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@api_bp.route('/auction/admin-bid', methods=['POST'])
@login_required
@admin_required
def api_admin_place_bid():
    data = request.get_json() or request.form
    try:
        franchise_id = int(data.get('franchise_id'))
        amount_raw = data.get('amount')
        state = get_auction_state()
        if amount_raw is not None and str(amount_raw).strip() != '':
            amount = float(amount_raw)
        else:
            increment = get_next_bid_increment(state.current_bid)
            player = Player.query.get(state.active_player_id) if state.active_player_id else None
            if not state.highest_bidder_id and player:
                amount = float(player.base_price or 10000.0)
            else:
                amount = state.current_bid + increment

        state = place_bid(franchise_id, amount)
        return jsonify({
            'success': True,
            'current_bid': state.current_bid,
            'highest_bidder_id': state.highest_bidder_id
        })
    except (ValueError, TypeError) as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@api_bp.route('/auction/sold', methods=['POST'])
@login_required
@admin_required
def api_finalize_sold():
    try:
        player, franchise, sold_price = finalize_sold(current_user.id)
        return jsonify({
            'success': True,
            'message': f"Player {player.name} sold to {franchise.name} for Rs. {sold_price:,.0f}",
            'player_name': player.name,
            'franchise_name': franchise.name,
            'sold_price': sold_price
        })
    except (ValueError, RuntimeError) as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@api_bp.route('/auction/unsold', methods=['POST'])
@login_required
@admin_required
def api_finalize_unsold():
    try:
        player = finalize_unsold(current_user.id)
        return jsonify({
            'success': True,
            'message': f"Player {player.name} marked UNSOLD.",
            'player_name': player.name
        })
    except (ValueError, RuntimeError) as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@api_bp.route('/auction/reset', methods=['POST'])
@login_required
@admin_required
def api_reset_waiting():
    try:
        state = reset_to_waiting(current_user.id)
        return jsonify({'success': True, 'status': state.status})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@api_bp.route('/auction/second-chance/find-player', methods=['POST'])
@login_required
@admin_required
def api_find_second_chance_player():
    data = request.get_json() or request.form
    roll_number = data.get('roll_number')
    try:
        player = find_second_chance_player_by_roll(roll_number)
        return jsonify({'success': True, 'player': player.to_dict()})
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@api_bp.route('/auction/second-chance/start', methods=['POST'])
@login_required
@admin_required
def api_start_second_chance():
    try:
        state = start_second_chance_auction(current_user.id)
        return jsonify({'success': True, 'status': state.status})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@api_bp.route('/auction/second-chance/end', methods=['POST'])
@login_required
@admin_required
def api_end_second_chance():
    try:
        state = end_second_chance_auction(current_user.id)
        return jsonify({'success': True, 'status': state.status})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@api_bp.route('/auction/events', methods=['GET'])
@login_required
@admin_required
def api_get_audit_events():
    """Return recent auction audit events stream for Admin event monitor."""
    events = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(15).all()
    return jsonify({
        'events': [{
            'id': e.id,
            'time': e.created_at.strftime('%H:%M:%S'),
            'action': e.action,
            'details': e.new_value or e.old_value or ''
        } for e in events]
    })

@api_bp.route('/auction/clear-sold', methods=['POST'])
@login_required
@admin_required
def api_clear_sold():
    """Immediately clear sold player from live projection and console after 10 seconds (Requirements 1, 7, 8)."""
    try:
        state = clear_sold_player(current_user.id)
        return jsonify({'success': True, 'status': state.status})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@api_bp.route('/auction/search-player', methods=['GET', 'POST'])
@login_required
@admin_required
def api_search_player():
    """
    Search player by rule number for Primary or Second Chance auction (Requirements 3 & 5).
    Strictly checks and reports sold status (Requirements 2 & 6).
    """
    if request.method == 'POST':
        data = request.get_json() or request.form
        rule_number = (data.get('rule') or data.get('rule_number') or data.get('roll_number') or '').strip()
        mode = (data.get('mode') or 'PRIMARY').strip().upper()
    else:
        rule_number = (request.args.get('rule') or request.args.get('rule_number') or request.args.get('roll_number') or '').strip()
        mode = (request.args.get('mode') or 'PRIMARY').strip().upper()

    if not rule_number:
        return jsonify({'success': False, 'message': 'Please enter a Rule Number.'}), 400

    player = Player.query.filter(Player.roll_number.ilike(rule_number)).first()
    if not player:
        return jsonify({'success': False, 'message': f"Player with Rule Number '{rule_number}' not found."}), 404

    # Strict sold check (Requirements 2 & 6)
    if player.is_sold or str(player.status).upper() == 'SOLD' or player.sold_to is not None:
        winning_f = Franchise.query.get(player.sold_to) if player.sold_to else None
        f_name = winning_f.name if winning_f else 'another team'
        sold_price_fmt = f"Rs. {player.sold_price:,.0f}" if player.sold_price else "N/A"
        return jsonify({
            'success': True,
            'is_sold': True,
            'can_auction': False,
            'error_message': f"Already Sold: Player '{player.name}' has already been sold to {f_name} ({sold_price_fmt}). This player cannot be auctioned again.",
            'player': player.to_dict()
        })

    if mode == 'SECOND_CHANCE':
        if player.status != PlayerStatus.UNSOLD:
            return jsonify({
                'success': True,
                'is_sold': False,
                'can_auction': False,
                'error_message': f"Player '{player.name}' is currently {player.status}, not UNSOLD. Only unsold players can be auctioned in Second Chance.",
                'player': player.to_dict()
            })
        if not player.is_second_chance_eligible:
            return jsonify({
                'success': True,
                'is_sold': False,
                'can_auction': False,
                'error_message': f"Player '{player.name}' has not been marked eligible for Second Chance Auction.",
                'player': player.to_dict()
            })

    if mode == 'PRIMARY':
        if player.status != PlayerStatus.AVAILABLE:
            return jsonify({
                'success': True,
                'is_sold': False,
                'can_auction': False,
                'error_message': f"Player '{player.name}' is currently {player.status}. Only AVAILABLE players can be auctioned in Primary Auction.",
                'player': player.to_dict()
            })

    return jsonify({
        'success': True,
        'is_sold': False,
        'can_auction': True,
        'player': player.to_dict()
    })

@api_bp.route('/auction/update-rule-number', methods=['POST'])
@login_required
@admin_required
def api_update_rule_number():
    """
    Update a player's Rule Number with duplicate detection (Requirements 4 & 5).
    """
    data = request.get_json() or request.form
    player_id = data.get('player_id')
    new_rule_number = data.get('new_rule_number') or data.get('rule_number') or data.get('new_roll_number')

    if not player_id:
        return jsonify({'success': False, 'message': 'Player ID is required.'}), 400

    try:
        updated_player = update_player_rule_number(int(player_id), new_rule_number, current_user.id)
        return jsonify({
            'success': True,
            'message': f"Rule Number updated successfully to '{updated_player.roll_number}'.",
            'player': updated_player.to_dict()
        })
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': f"Failed to update Rule Number: {str(e)}"}), 500


