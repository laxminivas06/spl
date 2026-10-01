from datetime import datetime
from app.extensions import db

class AuditLog(db.Model):
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    franchise_id = db.Column(db.Integer, db.ForeignKey('franchises.id'), nullable=True)
    action = db.Column(db.String(100), nullable=False)
    target_type = db.Column(db.String(50), nullable=True)
    target_id = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(20), default='SUCCESS', nullable=False)
    ip_address = db.Column(db.String(45), nullable=True)
    user_email = db.Column(db.String(120), nullable=True)
    category = db.Column(db.String(50), nullable=True)  # AUTH, PLAYER, FRANCHISE, AUCTION, PURSE, SQUAD, SECURITY, SETTINGS
    old_value = db.Column(db.Text, nullable=True)
    new_value = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    admin = db.relationship('User', foreign_keys=[admin_id])
    franchise = db.relationship('Franchise', foreign_keys=[franchise_id])

    @classmethod
    def record(cls, action, category=None, admin_id=None, franchise_id=None, target_type=None, target_id=None,
               status='SUCCESS', ip_address=None, user_email=None, old_value=None, new_value=None):
        try:
            log = cls(
                action=action,
                category=category or 'GENERAL',
                admin_id=admin_id,
                franchise_id=franchise_id,
                target_type=target_type,
                target_id=target_id,
                status=status,
                ip_address=ip_address,
                user_email=user_email,
                old_value=str(old_value) if old_value is not None else None,
                new_value=str(new_value) if new_value is not None else None
            )
            db.session.add(log)
            db.session.commit()
            return log
        except Exception:
            db.session.rollback()
            return None

    def __repr__(self):
        return f'<AuditLog id={self.id} action={self.action} status={self.status}>'
