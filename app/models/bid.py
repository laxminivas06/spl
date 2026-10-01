from datetime import datetime
from app.extensions import db

class Bid(db.Model):
    __tablename__ = 'bids'

    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('players.id'), nullable=False)
    franchise_id = db.Column(db.Integer, db.ForeignKey('franchises.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    player = db.relationship('Player')
    franchise = db.relationship('Franchise')

    def __repr__(self):
        return f'<Bid player_id={self.player_id} franchise_id={self.franchise_id} amount={self.amount}>'
