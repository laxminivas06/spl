from datetime import datetime
from app.extensions import db

class AuctionStatus:
    WAITING = 'WAITING'
    PLAYER_PREVIEW = 'PLAYER_PREVIEW'
    BIDDING = 'BIDDING'
    PAUSED = 'PAUSED'
    SOLD = 'SOLD'
    UNSOLD = 'UNSOLD'
    SECOND_CHANCE = 'SECOND_CHANCE'
    SQUADS_LOCKED = 'SQUADS_LOCKED'
    COMPLETED = 'COMPLETED'

    VALID_STATES = [WAITING, PLAYER_PREVIEW, BIDDING, PAUSED, SOLD, UNSOLD, SECOND_CHANCE, SQUADS_LOCKED, COMPLETED]

class AuctionState(db.Model):
    __tablename__ = 'auction_state'

    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(30), nullable=False, default=AuctionStatus.WAITING)
    active_player_id = db.Column(db.Integer, db.ForeignKey('players.id'), nullable=True)
    current_bid = db.Column(db.Float, default=0.0)
    highest_bidder_id = db.Column(db.Integer, db.ForeignKey('franchises.id'), nullable=True)
    timer_seconds = db.Column(db.Integer, default=30, nullable=False)
    timer_end = db.Column(db.DateTime, nullable=True)
    sold_display_until = db.Column(db.DateTime, nullable=True)
    paused_seconds_left = db.Column(db.Integer, nullable=True)
    last_bid_at = db.Column(db.DateTime, nullable=True)
    started_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    active_player = db.relationship('Player', foreign_keys=[active_player_id])
    highest_bidder = db.relationship('Franchise', foreign_keys=[highest_bidder_id])

    @property
    def sold_remaining_seconds(self):
        """Calculate remaining seconds for reliable 10-second post-sold display (Requirement 8)."""
        if self.status == AuctionStatus.SOLD and self.sold_display_until:
            now = datetime.utcnow()
            if now >= self.sold_display_until:
                return 0
            return max(0, int((self.sold_display_until - now).total_seconds()))
        return 0

    @property
    def remaining_seconds(self):
        """Calculate remaining timer seconds server-side."""
        if self.status == AuctionStatus.PAUSED and self.paused_seconds_left is not None:
            return max(0, self.paused_seconds_left)

        if self.status == AuctionStatus.BIDDING and self.timer_end:
            now = datetime.utcnow()
            if now >= self.timer_end:
                return 0
            return int((self.timer_end - now).total_seconds())

        if self.status == AuctionStatus.SOLD:
            return self.sold_remaining_seconds

        return 0

    def __repr__(self):
        return f'<AuctionState status={self.status} active_player_id={self.active_player_id} bid={self.current_bid}>'
