from datetime import datetime
from app.extensions import db

class FixtureStage:
    LEAGUE = 'LEAGUE'
    SEMI_FINAL = 'SEMI_FINAL'
    FINAL = 'FINAL'
    CHOICES = [LEAGUE, SEMI_FINAL, FINAL]

class FixtureStatus:
    UPCOMING = 'UPCOMING'
    LIVE = 'LIVE'
    COMPLETED = 'COMPLETED'
    CHOICES = [UPCOMING, LIVE, COMPLETED]

class Fixture(db.Model):
    __tablename__ = 'fixtures'

    id = db.Column(db.Integer, primary_key=True)
    match_number = db.Column(db.Integer, nullable=False, index=True)
    team_a_id = db.Column(db.Integer, db.ForeignKey('franchises.id'), nullable=False)
    team_b_id = db.Column(db.Integer, db.ForeignKey('franchises.id'), nullable=False)
    match_date = db.Column(db.String(50), nullable=True)
    match_time = db.Column(db.String(50), nullable=True)
    venue = db.Column(db.String(100), default='College Ground', nullable=False)
    stage = db.Column(db.String(50), default=FixtureStage.LEAGUE, nullable=False)
    status = db.Column(db.String(30), default=FixtureStatus.UPCOMING, nullable=False)
    is_published = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    team_a = db.relationship('Franchise', foreign_keys=[team_a_id])
    team_b = db.relationship('Franchise', foreign_keys=[team_b_id])

    def to_dict(self):
        return {
            'id': self.id,
            'match_number': self.match_number,
            'team_a_id': self.team_a_id,
            'team_a_name': self.team_a.name if self.team_a else '',
            'team_a_short': self.team_a.short_name if self.team_a else '',
            'team_b_id': self.team_b_id,
            'team_b_name': self.team_b.name if self.team_b else '',
            'team_b_short': self.team_b.short_name if self.team_b else '',
            'match_date': self.match_date,
            'match_time': self.match_time,
            'venue': self.venue,
            'stage': self.stage,
            'status': self.status,
            'is_published': self.is_published
        }

    def __repr__(self):
        return f'<Fixture #{self.match_number}: {self.team_a_id} vs {self.team_b_id}>'
