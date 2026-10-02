import re
from datetime import datetime
from app.extensions import db

def normalize_photo_url(url):
    """
    Transforms any photo URL, converting Google Drive sharing/view/open links
    into direct image stream URLs (via Google CDN lh3).
    """
    if not url or not isinstance(url, str):
        return url
    u = url.strip()
    if not u:
        return u
    if any(k in u for k in ['drive.google.com', 'docs.google.com', 'drive.usercontent.google.com', 'lh3.googleusercontent.com']):
        m = re.search(r'/d/([a-zA-Z0-9_-]+)', u)
        if m:
            return f"https://lh3.googleusercontent.com/d/{m.group(1)}"
        m = re.search(r'[?&]id=([a-zA-Z0-9_-]+)', u)
        if m:
            return f"https://lh3.googleusercontent.com/d/{m.group(1)}"
    return u

class PlayerRole:
    BATSMAN = 'BATSMAN'
    BOWLER = 'BOWLER'
    ALL_ROUNDER = 'ALL_ROUNDER'
    WICKETKEEPER = 'WICKETKEEPER'

    CHOICES = [BATSMAN, BOWLER, ALL_ROUNDER, WICKETKEEPER]

class PlayerCategory:
    ELITE = 'Elite'
    SKILLED = 'Skilled'
    ROOKIE = 'Rookie'

    CHOICES = [ELITE, SKILLED, ROOKIE]

    @classmethod
    def normalize(cls, val):
        if not val:
            return cls.ROOKIE
        s = str(val).strip()
        for choice in cls.CHOICES:
            if s.lower() == choice.lower():
                return choice
        upper = s.upper()
        if upper in ['MARQUEE', 'PREMIUM', 'STAR', 'ELITE']:
            return cls.ELITE
        if upper in ['COMPETITIVE', 'PRO', 'SKILLED']:
            return cls.SKILLED
        return cls.ROOKIE

class PlayerStatus:
    AVAILABLE = 'AVAILABLE'
    SOLD = 'SOLD'
    UNSOLD = 'UNSOLD'
    FINAL_UNSOLD = 'FINAL_UNSOLD'
    RETAINED = 'RETAINED'

    CHOICES = [AVAILABLE, SOLD, UNSOLD, FINAL_UNSOLD, RETAINED]

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
    category = db.Column(db.String(50), nullable=False, default=PlayerCategory.ROOKIE)
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
        return str(self.status).upper() in ['SOLD', 'RETAINED'] or self.sold_to is not None

    @property
    def is_captain(self):
        if str(self.status).upper() == 'RETAINED':
            return True
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
    def display_name(self):
        if self.is_captain:
            return f"{self.name} (C)"
        return self.name

    @property
    def display_price(self):
        if self.is_captain or str(self.status).upper() == 'RETAINED':
            return "₹ 50,000 (RETAINED)"
        if self.sold_price is None or self.sold_price == 0:
            return "—"
        return f"₹ {self.sold_price:,.0f}"

    @property
    def base_price(self):
        """Common base price configured at the auction level in SystemSettings."""
        from app.models.setting import SystemSettings
        try:
            val = SystemSettings.get_setting('base_price', '10000')
            return float(val) if val else 10000.0
        except Exception:
            return 10000.0

    @base_price.setter
    def base_price(self, value):
        # Base price is configured at auction level and not stored per player
        pass

    @property
    def rule_number(self):
        return self.roll_number

    @rule_number.setter
    def rule_number(self, value):
        self.roll_number = str(value) if value is not None else None

    @property
    def role_icon(self):
        key = str(self.role or '').strip().upper().replace(' ', '_').replace('-', '_')
        if 'BOWL' in key or 'BALL' in key:
            return 'https://media.istockphoto.com/id/2026855771/vector/cricket-ball-icon-isolated-on-white-background.jpg?s=612x612&w=0&k=20&c=PITZXH3lkWfkNfsYtFqVajAWKntdiXteyTZEOr-o90I='
        if 'ALL' in key or 'ROUND' in key:
            return 'https://static.vecteezy.com/system/resources/previews/000/363/479/non_2x/vector-glyph-black-icon.jpg'
        if 'WICKET' in key or 'KEEP' in key or 'WK' in key:
            return 'https://static.thenounproject.com/png/2005527-200.png'
        return 'https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQ4saHQo4zw7BjytkA_qmWEUs8QViHyauRwpwqzANrRrQ&s=10'

    def to_dict(self):
        return {
            'id': self.id,
            'roll_number': self.roll_number,
            'rule_number': self.roll_number,
            'name': self.name,
            'display_name': self.display_name,
            'room_number': self.room_number,
            'photo': normalize_photo_url(self.photo),
            'role': self.role,
            'role_icon': self.role_icon,
            'category_icon': self.role_icon,
            'branch': self.branch,
            'year': self.year,
            'experience': self.experience,
            'category': self.category,
            'base_price': self.base_price,
            'status': 'RETAINED' if self.is_captain else self.status,
            'is_sold': self.is_sold,
            'is_retained': self.is_captain,
            'retained_amount': 50000.0 if self.is_captain else 0.0,
            'is_second_chance_eligible': self.is_second_chance_eligible,
            'auction_type': self.auction_type or 'PRIMARY',
            'auctionType': self.auction_type or 'PRIMARY',
            'sold_to': self.sold_to,
            'soldTo': self.sold_to,
            'sold_price': 50000.0 if self.is_captain else self.sold_price,
            'soldPrice': 50000.0 if self.is_captain else self.sold_price,
            'sold_at': self.sold_at.isoformat() if self.sold_at else None,
            'soldAt': self.sold_at.isoformat() if self.sold_at else None,
            'is_captain': self.is_captain,
            'display_price': self.display_price,
            'franchise_name': self.franchise.name if self.franchise else None,
            'franchise_short': self.franchise.short_name if self.franchise else None
        }

    def __repr__(self):
        return f'<Player {self.name} ({self.roll_number}) - {self.category}>'

