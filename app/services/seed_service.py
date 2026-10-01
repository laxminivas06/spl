import os
from app.extensions import db
from app.models import User, AuctionState, AuctionStatus, SystemSettings

from app.services.db_sync_service import sync_database_schema


def seed_database():
    """Seed only the system essentials: system settings, auction state, and the admin account.
    Franchises, franchise users, and players are created manually by the admin via the UI.
    """
    sync_database_schema()

    # 1. System Settings Defaults
    for key, val in SystemSettings.DEFAULTS.items():
        existing = SystemSettings.query.filter_by(key=key).first()
        if not existing:
            setting = SystemSettings(key=key, value=val)
            db.session.add(setting)

    # 2. Auction State (exactly one row)
    auction_state = AuctionState.query.first()
    if not auction_state:
        auction_state = AuctionState(status=AuctionStatus.WAITING)
        db.session.add(auction_state)

    # 3. Admin User — only laxminivasmorishetty143@gmail.com
    admin_email = os.environ.get('ADMIN_EMAIL', 'laxminivasmorishetty143@gmail.com')
    admin_user = User.query.filter(
        (User.username == 'admin') |
        (User.email == admin_email)
    ).first()
    if not admin_user:
        admin_user = User(
            username='admin',
            email=admin_email,
            display_name='Lakshmi Nivas Morishetty',
            role='ADMIN',
            is_active=True
        )
        db.session.add(admin_user)
    else:
        # Keep admin email/role current
        admin_user.email = admin_email
        admin_user.role = 'ADMIN'
        admin_user.is_active = True
        if not admin_user.display_name:
            admin_user.display_name = 'Lakshmi Nivas Morishetty'

    db.session.commit()
