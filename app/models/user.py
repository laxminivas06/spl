from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db

class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=True, index=True)
    display_name = db.Column(db.String(100), nullable=True)
    google_subject_id = db.Column(db.String(100), nullable=True, index=True)
    password_hash = db.Column(db.String(256), nullable=True)  # Nullable for OAuth users
    role = db.Column(db.String(20), nullable=False, default='FRANCHISE')  # ADMIN, FRANCHISE
    franchise_id = db.Column(db.Integer, db.ForeignKey('franchises.id'), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_login_at = db.Column(db.DateTime, nullable=True)

    franchise = db.relationship('Franchise', back_populates='users')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == 'ADMIN'

    @property
    def is_franchise(self):
        return self.role == 'FRANCHISE'

    def __repr__(self):
        return f'<User {self.username} ({self.email}) [{self.role}]>'
