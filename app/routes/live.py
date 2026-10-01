from flask import Blueprint, render_template
from flask_login import login_required
from app.utils.decorators import admin_required
from app.models import AuctionState, AuctionStatus

live_bp = Blueprint('live', __name__)

@live_bp.route('/live')
@live_bp.route('/projector')
@live_bp.route('/live/projector')
@live_bp.route('/live/screen')
@login_required
@admin_required
def auction_live():
    auction_state = AuctionState.query.first()
    status = auction_state.status if auction_state else AuctionStatus.WAITING

    return render_template(
        'live/auction.html',
        status=status
    )
