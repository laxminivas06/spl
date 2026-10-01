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
        'starting_purse': '300000',
        'squad_limit': '15',
        'base_price': '10000',
        'timer_seconds': '10',
        'bid_increment_step': '5000',
        'theme_default': 'dark',
        'SHOW_PURCHASE_PRICE_PUBLICLY': 'true',
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
