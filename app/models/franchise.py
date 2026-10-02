import json
from datetime import datetime
from app.extensions import db

DEFAULT_BRANCHES = [
    'CSE',
    'CSE (AI & ML)',
    'CSE (Data Science)',
    'CSE (Cyber Security)',
    'CSIT',
    'ECE',
    'EEE',
    'Mechanical',
    'Civil',
    'IT',
    'AI & DS',
    'MBA',
    'MCA'
]

def get_available_branches():
    """Retrieve available branches dynamically from SystemSettings, falling back to DEFAULT_BRANCHES."""
    try:
        from app.models.setting import SystemSettings
        setting = SystemSettings.get_setting('BRANCH_CHOICES')
        if setting:
            try:
                val = json.loads(setting)
                if isinstance(val, list) and val:
                    return [str(b).strip() for b in val if str(b).strip()]
            except Exception:
                parts = [b.strip() for b in setting.split(',') if b.strip()]
                if parts:
                    return parts
    except Exception:
        pass
    return list(DEFAULT_BRANCHES)


class TeamCaptain:
    """Independent captain entity decoupled from the Player database."""
    def __init__(self, franchise):
        self.franchise_id = franchise.id
        self.franchise = franchise
        self.id = f"cap_{franchise.id}"
        self.captain_id = self.id
        self.roll_number = franchise.captain_rule_number or ''
        self.rule_number = franchise.captain_rule_number or ''
        self.name = franchise.captain_name or f"{franchise.name} Captain"
        self.photo = franchise.captain_photo or 'default_player.png'
        self.branch = franchise.captain_department or 'CSE'
        self.department = franchise.captain_department or 'CSE'
        self.year = franchise.captain_year or '4'
        self.category = franchise.captain_category or 'Elite'
        self.role = 'ALL_ROUNDER'
        self.is_captain = True
        self.status = 'RETAINED'
        self.sold_price = 50000.0
        self.base_price = 0.0
        self.sold_to = franchise.id
        self.is_sold = True
        self.is_second_chance_eligible = False
        self.auction_type = 'RETAINED'

    def to_dict(self):
        return {
            'id': self.id,
            'roll_number': self.roll_number,
            'rule_number': self.rule_number,
            'name': self.name,
            'photo': self.photo,
            'branch': self.branch,
            'department': self.department,
            'year': self.year,
            'category': self.category,
            'role': self.role,
            'is_captain': True,
            'status': self.status,
            'sold_price': self.sold_price,
            'sold_to': self.franchise_id,
            'is_sold': True
        }

    def __repr__(self):
        return f"<TeamCaptain {self.name} ({self.roll_number}) - Franchise {self.franchise_id}>"


class Franchise(db.Model):
    __tablename__ = 'franchises'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    short_name = db.Column(db.String(20), nullable=False, unique=True)
    logo = db.Column(db.String(255), nullable=True)
    authorized_email = db.Column(db.String(120), unique=True, nullable=True, index=True)
    owner_name = db.Column(db.String(100), nullable=True)
    owners_data = db.Column(db.Text, nullable=True)  # JSON-encoded array of up to 3 owners: [{"name": ..., "email": ..., "phone": ...}]
    google_auth_enabled = db.Column(db.Boolean, default=True, nullable=False)
    starting_purse = db.Column(db.Float, nullable=False, default=550000.0)
    remaining_purse = db.Column(db.Float, nullable=False, default=500000.0)
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
        spent = sum((p.sold_price or 0.0) for p in self.sold_players)
        # Ensure captain 50,000 retention is counted
        if self.has_captain and not any(p.is_captain for p in self.sold_players):
            spent += 50000.0
        return spent

    def recalculate_purse(self):
        """Reconcile remaining purse accounting for 50,000 captain retention and purchased players."""
        spent = sum(float(p.sold_price or 0.0) for p in self.sold_players)
        if self.has_captain:
            spent += 50000.0
        self.remaining_purse = max(0.0, float(self.starting_purse or 550000.0) - spent)
        return self.remaining_purse

    @property
    def captain_player(self):
        """Returns the independent TeamCaptain object. Does NOT search or query the Player database."""
        if self.has_captain:
            return TeamCaptain(self)
        return None

    @property
    def squad_players(self):
        """Returns all players in squad, guaranteed with Team Captain placed first."""
        players = list(self.sold_players.all())
        if self.has_captain:
            cap = self.captain_player
            if cap:
                players.insert(0, cap)
        return players

    @property
    def has_captain(self):
        return bool(self.captain_name and str(self.captain_name).strip())

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

    @property
    def branch(self):
        return self.captain_department

    @branch.setter
    def branch(self, value):
        self.captain_department = value.strip() if value else None

    def get_owners(self):
        """Returns list of owner dicts: [{'name': ..., 'email': ..., 'phone': ...}] (max 3)."""
        if self.owners_data:
            try:
                data = json.loads(self.owners_data)
                if isinstance(data, list):
                    owners = []
                    for item in data[:3]:
                        if isinstance(item, dict) and (item.get('name') or item.get('email')):
                            owners.append({
                                'name': str(item.get('name', '')).strip(),
                                'email': str(item.get('email', '')).strip().lower(),
                                'phone': str(item.get('phone', '')).strip()
                            })
                    if owners:
                        return owners
            except Exception:
                pass
        # Fallback to single owner fields if owners_data not present
        if self.owner_name or self.authorized_email:
            return [{
                'name': self.owner_name or '',
                'email': self.authorized_email or '',
                'phone': ''
            }]
        return []

    def set_owners(self, owners_list):
        """Saves up to 3 owners, synchronizing Owner 1 to owner_name & authorized_email."""
        cleaned = []
        for o in (owners_list or [])[:3]:
            if isinstance(o, dict):
                name = str(o.get('name', '')).strip()
                email = str(o.get('email', '')).strip().lower()
                phone = str(o.get('phone', '')).strip()
                if name or email:
                    cleaned.append({
                        'name': name,
                        'email': email,
                        'phone': phone
                    })
        self.owners_data = json.dumps(cleaned) if cleaned else None
        if cleaned:
            self.owner_name = cleaned[0]['name'] or None
            self.authorized_email = cleaned[0]['email'] or None
        else:
            self.owner_name = None
            self.authorized_email = None

    @property
    def owners(self):
        return self.get_owners()

    @owners.setter
    def owners(self, val):
        self.set_owners(val)

    @property
    def max_elite_allowed(self):
        try:
            from app.models.setting import SystemSettings
            return int(SystemSettings.get_setting('max_elite_per_team', '4'))
        except Exception:
            return 4

    @property
    def min_auction_elite_required(self):
        try:
            from app.models.setting import SystemSettings
            return int(SystemSettings.get_setting('min_auction_elite_per_team', '1'))
        except Exception:
            return 1

    @property
    def max_auction_elite_allowed(self):
        try:
            from app.models.setting import SystemSettings
            return int(SystemSettings.get_setting('max_auction_elite_per_team', '3'))
        except Exception:
            return 3

    @property
    def is_captain_elite(self):
        cat = (self.captain_category or (self.captain_player.category if self.captain_player else 'Elite'))
        return str(cat).strip().lower() == 'elite'

    @property
    def elite_players(self):
        """Returns all players in squad classified as Elite."""
        res = []
        for p in self.squad_players:
            p_cat = (self.captain_category if ((self.captain_id and p.id == self.captain_id) or p.is_captain) else p.category) or 'Rookie'
            if str(p_cat).strip().lower() == 'elite':
                res.append(p)
        return res

    @property
    def elite_count(self):
        """Total count of Elite players in team (including Captain)."""
        count = len(self.elite_players)
        if self.has_captain and self.is_captain_elite and not any(p.id == self.captain_id or p.is_captain for p in self.sold_players):
            if not self.captain_player:
                count += 1
        return count

    @property
    def auction_elite_players(self):
        """Returns non-captain Elite players acquired in auction / added to squad."""
        res = []
        for p in self.sold_players:
            if p.is_captain or (self.captain_id and p.id == self.captain_id):
                continue
            if str(p.category or '').strip().lower() == 'elite':
                res.append(p)
        return res

    @property
    def auction_elite_count(self):
        return len(self.auction_elite_players)

    @property
    def can_add_elite(self):
        """
        Condition: Total Elite < max_elite_allowed (default 3)
                   AND Auction Elite < max_auction_elite_allowed (default 2).
        """
        if self.elite_count >= self.max_elite_allowed:
            return False
        if self.auction_elite_count >= self.max_auction_elite_allowed:
            return False
        return True

    @property
    def needs_mandatory_elite(self):
        return self.auction_elite_count < self.min_auction_elite_required

    @property
    def required_elite_slots_needed(self):
        return max(0, self.min_auction_elite_required - self.auction_elite_count)

    @property
    def available_auction_elite_slots(self):
        return max(0, self.max_auction_elite_allowed - self.auction_elite_count)

    @property
    def auction_elite_requirement_text(self):
        return f"{self.min_auction_elite_required}–{self.max_auction_elite_allowed} Elite Players"

    @property
    def elite_status_label(self):
        if self.auction_elite_count == 0:
            return f"Requires {self.auction_elite_requirement_text} (0/{self.max_auction_elite_allowed} Purchased)"
        elif self.auction_elite_count >= self.max_auction_elite_allowed:
            return f"Auction Elite Slots Full ({self.max_auction_elite_allowed}/{self.max_auction_elite_allowed})"
        else:
            return f"Requirement Met ({self.auction_elite_count}/{self.max_auction_elite_allowed} Auction Elites)"

    def to_dict(self):
        owners_list = self.get_owners()
        return {
            'id': self.id,
            'name': self.name,
            'short_name': self.short_name,
            'short_code': self.short_name,
            'logo': self.logo,
            'owner_name': self.owner_name,
            'owners': owners_list,
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
            'captain_status': 'RETAINED — ₹50,000' if self.has_captain else '✗ Team Captain Required',
            'franchisee_name': self.owner_name or self.name,
            'captain_name': self.captain_name or (self.captain.name if self.captain else None),
            'captain_display_name': f"{self.captain_name} (C)" if self.captain_name else (f"{self.captain.name} (C)" if self.captain else None),
            'captain_is_retained': True if self.has_captain else False,
            'captain_retained_amount': 50000.0 if self.has_captain else 0.0,
            'captain_rule_number': self.captain_rule_number or (self.captain.roll_number if self.captain else None),
            'captain_department': self.captain_department or (self.captain.branch if self.captain else None),
            'branch': self.captain_department or (self.captain.branch if self.captain else None),
            'captain_year': self.captain_year or (self.captain.year if self.captain else None),
            'captain_category': self.captain_category or (self.captain.category if self.captain else 'ALL_ROUNDER'),
            'captain_photo': self.captain_photo or (self.captain.photo if self.captain else 'default_player.png'),
            'is_captain_elite': self.is_captain_elite,
            'elite_count': self.elite_count,
            'auction_elite_count': self.auction_elite_count,
            'available_auction_elite_slots': self.available_auction_elite_slots,
            'auction_elite_requirement_text': self.auction_elite_requirement_text,
            'max_elite_allowed': self.max_elite_allowed,
            'min_auction_elite_required': self.min_auction_elite_required,
            'max_auction_elite_allowed': self.max_auction_elite_allowed,
            'can_add_elite': self.can_add_elite,
            'needs_mandatory_elite': self.needs_mandatory_elite,
            'elite_status_label': self.elite_status_label,
            'is_active': self.is_active
        }


    def __repr__(self):
        return f'<Franchise {self.short_name} - {self.name} ({self.authorized_email})>'
