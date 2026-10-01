import os
from app.extensions import db
from app.models import User, Franchise, AuctionState, AuctionStatus, SystemSettings

INITIAL_FRANCHISES = [
    {
        "short_name": "F01",
        "name": "Cyber Vipers",
        "username": "cybervipers",
        "authorized_email": "cybervipers@sphoorthyengg.ac.in",
        "default_pass": "Vipers@2026!"
    },
    {
        "short_name": "F02",
        "name": "Tech Titans",
        "username": "techtitans",
        "authorized_email": "techtitans@sphoorthyengg.ac.in",
        "default_pass": "Titans@2026!"
    },
    {
        "short_name": "F03",
        "name": "Neural Hawks",
        "username": "neuralhawks",
        "authorized_email": "neuralhawks@sphoorthyengg.ac.in",
        "default_pass": "Hawks@2026!"
    },
    {
        "short_name": "F04",
        "name": "Data Phoenix",
        "username": "dataphoenix",
        "authorized_email": "dataphoenix@sphoorthyengg.ac.in",
        "default_pass": "Phoenix@2026!"
    },
    {
        "short_name": "F05",
        "name": "Circuit Chargers",
        "username": "circuitchargers",
        "authorized_email": "circuitchargers@sphoorthyengg.ac.in",
        "default_pass": "Chargers@2026!"
    },
    {
        "short_name": "F06",
        "name": "Iron Giants",
        "username": "irongiants",
        "authorized_email": "irongiants@sphoorthyengg.ac.in",
        "default_pass": "Giants@2026!"
    },
]

DEFAULT_PURSE = 300000.0
DEFAULT_SQUAD_LIMIT = 15

from app.services.db_sync_service import sync_database_schema

def seed_database():
    """Idempotently seed system settings, initial auction state, admin account, and 6 franchises."""
    sync_database_schema()

    # 1. System Settings Defaults
    for key, val in SystemSettings.DEFAULTS.items():
        existing = SystemSettings.query.filter_by(key=key).first()
        if not existing:
            setting = SystemSettings(key=key, value=val)
            db.session.add(setting)

    # 2. Auction State
    auction_state = AuctionState.query.first()
    if not auction_state:
        auction_state = AuctionState(status=AuctionStatus.WAITING)
        db.session.add(auction_state)

    # 3. Admin User
    admin_pass = os.environ.get('ADMIN_PASSWORD', 'SPLAdmin@2026!')
    admin_email = os.environ.get('ADMIN_EMAIL', 'laxminivasmorishetty143@gmail.com')
    admin_user = User.query.filter(
        (User.username == 'admin') | 
        (User.email == admin_email) | 
        (User.email == 'admin@sphoorthyengg.ac.in')
    ).first()
    if not admin_user:
        admin_user = User(
            username='admin',
            email=admin_email,
            display_name='System Administrator',
            role='ADMIN',
            is_active=True
        )
        admin_user.set_password(admin_pass)
        db.session.add(admin_user)
    else:
        admin_user.username = 'admin'
        admin_user.email = admin_email
        admin_user.role = 'ADMIN'
        admin_user.is_active = True
        if not admin_user.password_hash or not admin_user.check_password(admin_pass):
            admin_user.set_password(admin_pass)

    # 4. Franchises & User Accounts
    for item in INITIAL_FRANCHISES:
        franchise = Franchise.query.filter_by(short_name=item['short_name']).first()
        if not franchise:
            franchise = Franchise(
                short_name=item['short_name'],
                name=item['name'],
                authorized_email=item['authorized_email'].lower(),
                owner_name=item['name'] + " Owner",
                google_auth_enabled=True,
                starting_purse=DEFAULT_PURSE,
                remaining_purse=DEFAULT_PURSE,
                squad_limit=DEFAULT_SQUAD_LIMIT,
                is_active=True
            )
            db.session.add(franchise)
            db.session.flush()
        else:
            if not franchise.owner_name:
                franchise.owner_name = item['name'] + " Owner"
            franchise.google_auth_enabled = True

        # Link/Create user object for franchise
        email_val = item['authorized_email'].lower()
        user = User.query.filter((User.username == item['username']) | (User.email == email_val)).first()
        if not user:
            user = User(
                username=item['username'],
                email=email_val,
                display_name=item['name'],
                role='FRANCHISE',
                franchise_id=franchise.id,
                is_active=True
            )
            user.set_password(item['default_pass'])
            db.session.add(user)
        else:
            user.username = item['username']
            user.email = email_val
            user.franchise_id = franchise.id
            user.role = 'FRANCHISE'
            user.is_active = True
            if not user.password_hash or not user.check_password(item['default_pass']):
                user.set_password(item['default_pass'])

        # Enforce 3 Lakhs Starting Purse
        franchise.starting_purse = DEFAULT_PURSE

        # Enforce Mandatory Team Captain for every squad
        from app.models.player import Player, PlayerRole, PlayerCategory, PlayerStatus
        from app.services.team_service import add_team_captain

        if not franchise.has_captain:
            cap_name = f"{franchise.name} Captain"
            cap_roll = f"CAP-{franchise.short_name}"
            add_team_captain(
                franchise=franchise,
                name=cap_name,
                rule_number=cap_roll,
                department="Management",
                year="Senior",
                category="NORMAL",
                photo="default_player.png"
            )
        else:
            # Ensure existing captain has an official Player record in the squad
            cap_name = franchise.captain_name or f"{franchise.name} Captain"
            cap_roll = franchise.captain_rule_number or f"CAP-{franchise.short_name}"
            add_team_captain(
                franchise=franchise,
                name=cap_name,
                rule_number=cap_roll,
                department=franchise.captain_department or "Management",
                year=franchise.captain_year or "Senior",
                category=franchise.captain_category or "NORMAL",
                photo=franchise.captain_photo or "default_player.png"
            )

        franchise.recalculate_purse()

    # Deduplicate any duplicate transactions for players
    from app.models.transaction import Transaction
    all_txs = Transaction.query.filter_by(type='PLAYER_PURCHASE').order_by(Transaction.id.asc()).all()
    seen_purchases = set()
    for tx in all_txs:
        key = (tx.player_id, tx.franchise_id)
        if key in seen_purchases:
            db.session.delete(tx)
        else:
            seen_purchases.add(key)

    db.session.commit()

