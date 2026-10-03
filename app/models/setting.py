from datetime import datetime
from app.extensions import db

class SystemSettings(db.Model):
    __tablename__ = 'system_settings'

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False, index=True)
    value = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    DEFAULTS = {
        'event_name': 'SPL',
        'event_subtitle': 'Sphoorthy Premier League',
        'starting_purse': '550000',
        'squad_limit': '15',
        'base_price': '10000',
        'timer_seconds': '30',
        'bid_increment_rules': '[{"id": 1, "min_price": 10000, "max_price": 20000, "increment": 2000}, {"id": 2, "min_price": 20000, "max_price": 50000, "increment": 5000}, {"id": 3, "min_price": 50000, "max_price": 100000, "increment": 10000}, {"id": 4, "min_price": 100000, "max_price": 10000000, "increment": 10000}]',
        'theme_default': 'dark',
        'SHOW_PURCHASE_PRICE_PUBLICLY': 'true',
        'max_elite_per_team': '4',
        'min_auction_elite_per_team': '1',
        'max_auction_elite_per_team': '3',
        'enforce_elite_limits': 'true',
        'audit_logging_enabled': 'true',
        'audit_retention_days': '90',
        'audit_log_level': 'ALL',
        'audit_track_ip': 'true'
    }

    @classmethod
    def get_setting(cls, key, default=None):
        setting = cls.query.filter_by(key=key).first()
        if setting and setting.value is not None:
            return setting.value
        if default is not None:
            return str(default)
        return cls.DEFAULTS.get(key, '')

    @classmethod
    def set_setting(cls, key, value):
        setting = cls.query.filter_by(key=key).first()
        if not setting:
            setting = cls(key=key, value=str(value))
            db.session.add(setting)
        else:
            setting.value = str(value)
        db.session.commit()
        return setting

    def __repr__(self):
        return f'<SystemSettings {self.key}={self.value}>'
