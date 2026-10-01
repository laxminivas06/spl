from datetime import datetime
from app.extensions import db

class Transaction(db.Model):
    __tablename__ = 'transactions'

    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('players.id'), nullable=True)
    franchise_id = db.Column(db.Integer, db.ForeignKey('franchises.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    type = db.Column(db.String(50), nullable=False)  # PURCHASE, REFUND, ADJUSTMENT
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    admin_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    player = db.relationship('Player')
    franchise = db.relationship('Franchise')
    admin = db.relationship('User')

    @property
    def timestamp(self):
        return self.created_at

    def __repr__(self):
        return f'<Transaction franchise_id={self.franchise_id} amount={self.amount} type={self.type}>'
