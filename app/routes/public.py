from flask import Blueprint, render_template, current_app, redirect, url_for, flash
from flask_login import login_required, current_user
from app.models import Franchise, Player, PlayerRole, SystemSettings, Fixture, FixtureStatus

public_bp = Blueprint('public', __name__)

@public_bp.before_request
def require_auth_for_public():
    """Ensure unauthorized users cannot access public data routes directly by URL."""
    if not current_user.is_authenticated:
        flash('Please sign in with your authorized Google account to access this page.', 'warning')
        return redirect(url_for('auth.login'))

@public_bp.route('/teams')
@login_required
def public_teams():
    franchises = Franchise.query.order_by(Franchise.id.asc()).all()
    show_prices = SystemSettings.get_setting('SHOW_PURCHASE_PRICE_PUBLICLY', 'true').lower() == 'true'

    teams_data = []
    for f in franchises:
        f.recalculate_purse()
        players = f.squad_players

        role_counts = {
            PlayerRole.BATSMAN: sum(1 for p in players if p.role == PlayerRole.BATSMAN),
            PlayerRole.BOWLER: sum(1 for p in players if p.role == PlayerRole.BOWLER),
            PlayerRole.ALL_ROUNDER: sum(1 for p in players if p.role == PlayerRole.ALL_ROUNDER),
            PlayerRole.WICKETKEEPER: sum(1 for p in players if p.role == PlayerRole.WICKETKEEPER)
        }

        # Exclude captains (dash price) from bid averages
        prices = [p.sold_price for p in players if p.sold_price is not None and not p.is_captain and p.sold_price > 0]
        avg_price = sum(prices) / len(prices) if prices else 0.0
        max_price = max(prices) if prices else 0.0
        min_price = min(prices) if prices else 0.0

        teams_data.append({
            'franchise': f,
            'players': players,
            'role_counts': role_counts,
            'avg_price': avg_price,
            'max_price': max_price,
            'min_price': min_price
        })

    return render_template(
        'public/teams.html',
        teams=teams_data,
        show_prices=show_prices
    )

@public_bp.route('/fixtures')
@login_required
def public_fixtures():
    fixtures = Fixture.query.filter_by(is_published=True).order_by(Fixture.match_number.asc()).all()
    return render_template(
        'public/fixtures.html',
        fixtures=fixtures
    )

@public_bp.route('/ui')
@login_required
def live_ui():
    franchises = Franchise.query.order_by(Franchise.id.asc()).all()
    return render_template('ui.html', franchises=franchises)

def get_captains_data():
    franchises = Franchise.query.order_by(Franchise.id.asc()).all()
    captains_list = []
    for f in franchises:
        f.recalculate_purse()
        cap_player = f.captain_player
        cap_name = f.captain_name or (cap_player.name if cap_player else f"{f.name} Captain")
        cap_photo = (cap_player.photo if cap_player and cap_player.photo else None) or f.captain_photo or 'default_player.png'
        cap_dept = (cap_player.branch if cap_player and cap_player.branch else None) or f.captain_department or 'CSE'
        cap_year = (cap_player.year if cap_player and cap_player.year else None) or f.captain_year or '4th Year'
        cap_cat = (cap_player.category if cap_player and cap_player.category else None) or f.captain_category or 'Elite'
        cap_roll = (cap_player.roll_number if cap_player and cap_player.roll_number else None) or f.captain_rule_number
        from app.models import PlayerCategory
        cap_cat = PlayerCategory.normalize(cap_cat)
        franchisee_name = f.owner_name or f.name

        captains_list.append({
            'team_name': f.name,
            'team_short': f.short_name,
            'franchisee_name': franchisee_name,
            'captain_name': cap_name,
            'captain_display_name': f"{cap_name} (C)",
            'captain_photo': cap_photo,
            'roll_number': cap_roll,
            'category': cap_cat,
            'year': cap_year,
            'department': cap_dept,
            'retained_amount': 50000.0,
            'retained_status': 'RETAINED',
            'franchise': f,
            'player': cap_player
        })
    return captains_list

@public_bp.route('/captains')
@login_required
def public_captains():
    captains = get_captains_data()
    return render_template('public/captains.html', captains=captains)

@public_bp.route('/captains/projector')
@public_bp.route('/live/captains')
@login_required
def captains_projector():
    captains = get_captains_data()
    return render_template('public/captains_projector.html', captains=captains)


