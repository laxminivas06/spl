from datetime import datetime
from app.extensions import db
from app.models import Franchise, Player, PlayerRole, PlayerCategory, PlayerStatus
from app.services.audit_service import log_audit

def add_team_captain(franchise, name, rule_number=None, department=None, year=None, category='NORMAL', photo=None, actor_id=None):
    """
    Add or assign the Team Captain (First Member of the team).
    Enforces that team becomes eligible for bidding once captain exists.
    """
    if not name or not str(name).strip():
        raise ValueError("Team Captain Name is required.")

    name = str(name).strip()
    rule_number = str(rule_number).strip() if rule_number else None
    department = str(department).strip() if department else None
    year = str(year).strip() if year else None
    category = str(category).strip().upper() if category else 'NORMAL'

    # Check 15-member cap
    if franchise.squad_count >= franchise.squad_limit:
        raise ValueError("Maximum 15 Members Allowed. Team Full.")

    # Update franchise captain profile
    franchise.captain_name = name
    franchise.captain_rule_number = rule_number
    franchise.captain_department = department
    franchise.captain_year = year
    franchise.captain_category = category
    if photo:
        franchise.captain_photo = photo

    # Look for existing player by rule number or captain_id
    player = None
    if rule_number:
        player = Player.query.filter(Player.roll_number.ilike(rule_number)).first()

    if not player and franchise.captain_id:
        player = Player.query.get(franchise.captain_id)

    if player:
        # Link existing player
        player.sold_to = franchise.id
        player.status = PlayerStatus.SOLD
        if player.sold_price is None:
            player.sold_price = 0.0
        if department and not player.branch:
            player.branch = department
        if year and not player.year:
            player.year = year
        if photo and not player.photo:
            player.photo = photo
        franchise.captain_id = player.id
    else:
        # Create Player record for Captain so they are officially Member 1 in the squad
        c_roll = rule_number or f"CAP-{franchise.short_name}"
        existing_p = Player.query.filter_by(roll_number=c_roll).first()
        if existing_p:
            c_roll = f"{c_roll}-{franchise.id}"

        new_player = Player(
            roll_number=c_roll,
            name=name,
            photo=photo or 'default_player.png',
            role=PlayerRole.ALL_ROUNDER,
            branch=department,
            year=year,
            category=category,
            base_price=10000.0,
            status=PlayerStatus.SOLD,
            sold_to=franchise.id,
            sold_price=0.0
        )
        db.session.add(new_player)
        db.session.flush()
        franchise.captain_id = new_player.id

    franchise.recalculate_purse()
    db.session.commit()
    log_audit(actor_id, 'TEAM_CAPTAIN_ADDED', 'Franchise', franchise.id, None, f"Team Captain '{name}' added to {franchise.name}. Team now eligible for bidding.", franchise_id=franchise.id)
    return franchise

def add_team_member(franchise, name, rule_number=None, department=None, year=None, role=PlayerRole.BATSMAN, category='NORMAL', photo=None, actor_id=None):
    """
    Add an additional member to the team (Members 2 to 15).
    Strictly blocked if captain does not exist, or if squad_count >= 15.
    """
    # Rule: First member MUST be Team Captain
    if not franchise.has_captain:
        raise ValueError("Initial setup required: Only Team Captain can be added as the first member.")

    # Rule: Maximum 15 members
    if franchise.squad_count >= franchise.squad_limit:
        raise ValueError("Maximum 15 Members Allowed. Team Full.")

    if not name or not str(name).strip():
        raise ValueError("Member Name is required.")

    name = str(name).strip()
    rule_number = str(rule_number).strip() if rule_number else None
    department = str(department).strip() if department else None
    year = str(year).strip() if year else None
    role = str(role).strip().upper() if role in PlayerRole.CHOICES else PlayerRole.BATSMAN
    category = str(category).strip().upper() if category in PlayerCategory.CHOICES else 'NORMAL'

    # Check if player exists by rule_number
    player = None
    if rule_number:
        player = Player.query.filter(Player.roll_number.ilike(rule_number)).first()

    if player:
        if player.sold_to and player.sold_to != franchise.id:
            raise ValueError(f"Player '{player.name}' (#{rule_number}) is already assigned to another team.")
        player.sold_to = franchise.id
        player.status = PlayerStatus.SOLD
        if player.sold_price is None:
            player.sold_price = 0.0
        if department and not player.branch:
            player.branch = department
        if year and not player.year:
            player.year = year
        if photo and not player.photo:
            player.photo = photo
    else:
        m_roll = rule_number or f"{franchise.short_name}-M{franchise.squad_count + 1}"
        if Player.query.filter_by(roll_number=m_roll).first():
            m_roll = f"{m_roll}-{datetime.utcnow().strftime('%S%f')[:4]}"

        player = Player(
            roll_number=m_roll,
            name=name,
            photo=photo or 'default_player.png',
            role=role,
            branch=department,
            year=year,
            category=category,
            base_price=10000.0,
            status=PlayerStatus.SOLD,
            sold_to=franchise.id,
            sold_price=0.0
        )
        db.session.add(player)

    db.session.commit()
    log_audit(actor_id, 'TEAM_MEMBER_ADDED', 'Franchise', franchise.id, player.id, f"Member '{name}' added to {franchise.name} ({franchise.squad_count}/{franchise.squad_limit})", franchise_id=franchise.id)
    return player
