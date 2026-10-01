from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from app.utils.decorators import admin_required
from app.models import AuctionState, AuctionStatus

live_bp = Blueprint('live', __name__)

@live_bp.before_request
def require_auth_for_live():
    """Ensure unauthorized users cannot view the live auction or projector display."""
    if not current_user.is_authenticated:
        flash('Please sign in with your authorized Google account to view the Live Auction Console or Projector.', 'warning')
        return redirect(url_for('auth.login'))

@live_bp.route('/live')
@live_bp.route('/live/auction')
@live_bp.route('/projector')
@live_bp.route('/live/projector')
@live_bp.route('/live/screen')
@login_required
def auction_live():
    auction_state = AuctionState.query.first()
    status = auction_state.status if auction_state else AuctionStatus.WAITING

    return render_template(
        'live/auction.html',
        status=status
    )
