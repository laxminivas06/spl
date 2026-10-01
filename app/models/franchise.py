from datetime import datetime
from app.extensions import db

class Franchise(db.Model):
    __tablename__ = 'franchises'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    short_name = db.Column(db.String(20), nullable=False, unique=True)
    logo = db.Column(db.String(255), nullable=True)
    authorized_email = db.Column(db.String(120), unique=True, nullable=True, index=True)
    owner_name = db.Column(db.String(100), nullable=True)
    google_auth_enabled = db.Column(db.Boolean, default=True, nullable=False)
    starting_purse = db.Column(db.Float, nullable=False, default=300000.0)
    remaining_purse = db.Column(db.Float, nullable=False, default=300000.0)
    squad_limit = db.Column(db.Integer, nullable=False, default=15)
    captain_name = db.Column(db.String(100), nullable=True)
    captain_rule_number = db.Column(db.String(30), nullable=True)
    captain_department = db.Column(db.String(50), nullable=True)
    captain_year = db.Column(db.String(20), nullable=True)
    captain_category = db.Column(db.String(50), nullable=True)
    captain_photo = db.Column(db.String(255), nullable=True)
    captain_id = db.Column(db.Integer, db.ForeignKey('players.id'), nullable=True)
    vice_captain_id = db.Column(db.Integer, db.ForeignKey('players.id'), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    users = db.relationship('User', back_populates='franchise', lazy='dynamic')
    sold_players = db.relationship('Player', foreign_keys='Player.sold_to', back_populates='franchise', lazy='dynamic')
    captain = db.relationship('Player', foreign_keys=[captain_id])
    vice_captain = db.relationship('Player', foreign_keys=[vice_captain_id])

    @property
    def total_purse(self):
        return self.starting_purse

    @property
    def spent_purse(self):
        # Excludes 0-price or unpriced captains; strictly sums real purchase amounts
        return sum((p.sold_price or 0.0) for p in self.sold_players)

    def recalculate_purse(self):
        """Reconcile remaining purse directly from actual purchased players."""
        spent = sum((p.sold_price or 0.0) for p in self.sold_players)
        self.remaining_purse = max(0.0, float(self.starting_purse) - spent)
        return self.remaining_purse

    @property
    def captain_player(self):
        from app.models.player import Player
        if self.captain_id:
            cap = Player.query.get(self.captain_id)
            if cap:
                return cap
        if self.captain_rule_number:
            cap = Player.query.filter(Player.roll_number.ilike(self.captain_rule_number.strip())).first()
            if cap:
                return cap
        if self.captain_name:
            cap = Player.query.filter(Player.name.ilike(self.captain_name.strip()), Player.sold_to == self.id).first()
            if cap:
                return cap
        return None

    @property
    def squad_players(self):
        """Returns all players in squad, guaranteed with Team Captain placed first."""
        players = list(self.sold_players.all())
        cap = self.captain_player
        if cap and cap not in players:
            players.insert(0, cap)
        else:
            players.sort(key=lambda p: (0 if (cap and p.id == cap.id) or p.is_captain else 1, p.name or ''))
        return players

    @property
    def has_captain(self):
        return bool(self.captain_id or (self.captain_name and str(self.captain_name).strip()))

    @property
    def is_eligible_for_bidding(self):
        return bool(self.is_active and self.has_captain)

    @property
    def is_full(self):
        return self.squad_count >= self.squad_limit

    @property
    def squad_count(self):
        count = self.sold_players.count()
        if self.has_captain:
            from app.models.player import Player
            captain_in_squad = False
            if self.captain_id:
                captain_in_squad = self.sold_players.filter_by(id=self.captain_id).first() is not None
            elif self.captain_rule_number:
                captain_in_squad = self.sold_players.filter(Player.roll_number.ilike(self.captain_rule_number)).first() is not None
            if not captain_in_squad:
                count += 1
        return count

    @property
    def remaining_slots(self):
        return max(0, self.squad_limit - self.squad_count)

    @property
    def gmail(self):
        return self.authorized_email

    @gmail.setter
    def gmail(self, value):
        self.set_authorized_email(value)

    def set_authorized_email(self, email):
        if email:
            self.authorized_email = email.strip().lower()
        else:
            self.authorized_email = None

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'short_name': self.short_name,
            'short_code': self.short_name,
            'logo': self.logo,
            'owner_name': self.owner_name,
            'gmail': self.authorized_email,
            'authorized_email': self.authorized_email,
            'starting_purse': self.starting_purse,
            'remaining_purse': self.remaining_purse,
            'spent_purse': self.spent_purse,
            'squad_limit': self.squad_limit,
            'squad_count': self.squad_count,
            'remaining_slots': self.remaining_slots,
            'has_captain': self.has_captain,
            'is_eligible_for_bidding': self.is_eligible_for_bidding,
            'is_full': self.is_full,
            'bidding_eligibility_status': 'TEAM ELIGIBLE FOR BIDDING' if self.is_eligible_for_bidding else 'NOT ELIGIBLE FOR BIDDING',
            'captain_status': '✓ Captain Added' if self.has_captain else '✗ Team Captain Required',
            'captain_name': self.captain_name or (self.captain.name if self.captain else None),
            'captain_rule_number': self.captain_rule_number or (self.captain.roll_number if self.captain else None),
            'captain_department': self.captain_department or (self.captain.branch if self.captain else None),
            'captain_year': self.captain_year or (self.captain.year if self.captain else None),
            'captain_category': self.captain_category or (self.captain.category if self.captain else None),
            'captain_photo': self.captain_photo or (self.captain.photo if self.captain else None),
            'is_active': self.is_active
        }

    def __repr__(self):
        return f'<Franchise {self.short_name} - {self.name} ({self.authorized_email})>'
