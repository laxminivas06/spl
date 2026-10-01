from datetime import datetime
from app.extensions import db

class PlayerRole:
    BATSMAN = 'BATSMAN'
    BOWLER = 'BOWLER'
    ALL_ROUNDER = 'ALL_ROUNDER'
    WICKETKEEPER = 'WICKETKEEPER'

    CHOICES = [BATSMAN, BOWLER, ALL_ROUNDER, WICKETKEEPER]

class PlayerCategory:
    MARQUEE = 'MARQUEE'
    PREMIUM = 'PREMIUM'
    COMPETITIVE = 'COMPETITIVE'
    EMERGING = 'EMERGING'
    NORMAL = 'NORMAL'

    CHOICES = [MARQUEE, PREMIUM, COMPETITIVE, EMERGING, NORMAL]

class PlayerStatus:
    AVAILABLE = 'AVAILABLE'
    SOLD = 'SOLD'
    UNSOLD = 'UNSOLD'
    FINAL_UNSOLD = 'FINAL_UNSOLD'

    CHOICES = [AVAILABLE, SOLD, UNSOLD, FINAL_UNSOLD]

class Player(db.Model):
    __tablename__ = 'players'

    id = db.Column(db.Integer, primary_key=True)
    roll_number = db.Column(db.String(30), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    photo = db.Column(db.String(255), nullable=True)
    role = db.Column(db.String(50), nullable=False, default=PlayerRole.BATSMAN)
    branch = db.Column(db.String(50), nullable=True)
    year = db.Column(db.String(20), nullable=True)
    experience = db.Column(db.String(255), nullable=True)
    category = db.Column(db.String(50), nullable=False, default=PlayerCategory.NORMAL)
    base_price = db.Column(db.Float, default=10000.0, nullable=False)
    status = db.Column(db.String(30), default=PlayerStatus.AVAILABLE, nullable=False)
    is_second_chance_eligible = db.Column(db.Boolean, default=False, nullable=False)
    auction_type = db.Column(db.String(30), default='PRIMARY', nullable=False)  # PRIMARY or SECOND_CHANCE
    sold_to = db.Column(db.Integer, db.ForeignKey('franchises.id'), nullable=True)
    sold_price = db.Column(db.Float, nullable=True)
    sold_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    room_number = db.Column(db.String(50), nullable=True)
    franchise = db.relationship('Franchise', foreign_keys=[sold_to], back_populates='sold_players')

    @property
    def is_sold(self):
        return str(self.status).upper() == 'SOLD' or self.sold_to is not None

    @property
    def is_captain(self):
        if not self.franchise:
            return False
        if self.franchise.captain_id and self.franchise.captain_id == self.id:
            return True
        if self.franchise.captain_name and self.name and self.franchise.captain_name.strip().lower() == self.name.strip().lower():
            return True
        if self.franchise.captain_rule_number and self.roll_number and self.franchise.captain_rule_number.strip().lower() == self.roll_number.strip().lower():
            return True
        return False

    @property
    def display_price(self):
        if self.is_captain or self.sold_price is None or self.sold_price == 0:
            return "—"
        return f"₹ {self.sold_price:,.0f}"

    @property
    def rule_number(self):
        return self.roll_number

    @rule_number.setter
    def rule_number(self, value):
        self.roll_number = str(value) if value is not None else None

    def to_dict(self):
        return {
            'id': self.id,
            'roll_number': self.roll_number,
            'rule_number': self.roll_number,
            'name': self.name,
            'room_number': self.room_number,
            'photo': self.photo,
            'role': self.role,
            'branch': self.branch,
            'year': self.year,
            'experience': self.experience,
            'category': self.category,
            'base_price': self.base_price,
            'status': self.status,
            'is_sold': self.is_sold,
            'is_second_chance_eligible': self.is_second_chance_eligible,
            'auction_type': self.auction_type or 'PRIMARY',
            'auctionType': self.auction_type or 'PRIMARY',
            'sold_to': self.sold_to,
            'soldTo': self.sold_to,
            'sold_price': self.sold_price,
            'soldPrice': self.sold_price,
            'sold_at': self.sold_at.isoformat() if self.sold_at else None,
            'soldAt': self.sold_at.isoformat() if self.sold_at else None,
            'is_captain': self.is_captain,
            'display_price': self.display_price,
            'franchise_name': self.franchise.name if self.franchise else None,
            'franchise_short': self.franchise.short_name if self.franchise else None
        }

    def __repr__(self):
        return f'<Player {self.name} ({self.roll_number}) - {self.category}>'
