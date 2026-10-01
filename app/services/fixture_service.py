from datetime import datetime, timedelta
from app.extensions import db
from app.models import Franchise, Fixture, FixtureStage, FixtureStatus
from app.services.audit_service import log_audit

def generate_fixtures(format_type='SINGLE_ROUND_ROBIN', default_venue='College Ground', admin_id=None):
    """
    Generate draft fixtures for active franchises.
    Supports SINGLE_ROUND_ROBIN (15 matches for 6 teams) and DOUBLE_ROUND_ROBIN (30 matches).
    """
    franchises = Franchise.query.filter_by(is_active=True).order_by(Franchise.id.asc()).all()
    if len(franchises) < 2:
        raise ValueError("At least 2 active franchises are required to generate fixtures.")

    # Remove existing draft (unpublished) fixtures
    Fixture.query.filter_by(is_published=False).delete()
    db.session.commit()

    existing_max_match = db.session.query(db.func.max(Fixture.match_number)).scalar() or 0
    match_num = existing_max_match + 1

    generated = []
    base_date = datetime.now() + timedelta(days=1)

    # 1. Round Robin Generation
    if format_type in ['SINGLE_ROUND_ROBIN', 'DOUBLE_ROUND_ROBIN']:
        pairs = []
        n = len(franchises)
        for i in range(n):
            for j in range(i + 1, n):
                pairs.append((franchises[i], franchises[j]))

        for idx, (t1, t2) in enumerate(pairs):
            match_date_str = (base_date + timedelta(days=idx // 2)).strftime('%Y-%m-%d')
            match_time_str = "10:00 AM" if (idx % 2 == 0) else "02:30 PM"

            fixture = Fixture(
                match_number=match_num,
                team_a_id=t1.id,
                team_b_id=t2.id,
                match_date=match_date_str,
                match_time=match_time_str,
                venue=default_venue,
                stage=FixtureStage.LEAGUE,
                status=FixtureStatus.UPCOMING,
                is_published=False
            )
            db.session.add(fixture)
            generated.append(fixture)
            match_num += 1

        if format_type == 'DOUBLE_ROUND_ROBIN':
            for idx, (t1, t2) in enumerate(pairs):
                match_date_str = (base_date + timedelta(days=(len(pairs) + idx) // 2)).strftime('%Y-%m-%d')
                match_time_str = "10:00 AM" if (idx % 2 == 0) else "02:30 PM"

                fixture = Fixture(
                    match_number=match_num,
                    team_a_id=t2.id,  # Reverse home/away
                    team_b_id=t1.id,
                    match_date=match_date_str,
                    match_time=match_time_str,
                    venue=default_venue,
                    stage=FixtureStage.LEAGUE,
                    status=FixtureStatus.UPCOMING,
                    is_published=False
                )
                db.session.add(fixture)
                generated.append(fixture)
                match_num += 1

    db.session.commit()
    log_audit(admin_id, 'FIXTURE_GENERATED', 'Fixture', None, None, f"Generated {len(generated)} draft fixtures ({format_type})")
    return generated

def validate_fixtures():
    """
    Validate all fixtures in the database.
    Returns (is_valid: bool, errors: list)
    """
    fixtures = Fixture.query.order_by(Fixture.match_number.asc()).all()
    errors = []

    match_nums = set()
    seen_pairings = set()

    for f in fixtures:
        # Check match number uniqueness
        if f.match_number in match_nums:
            errors.append(f"Duplicate match number: Match #{f.match_number}")
        match_nums.add(f.match_number)

        # Check self match
        if f.team_a_id == f.team_b_id:
            errors.append(f"Match #{f.match_number}: Team cannot play against itself.")

        # Check team existence
        t1 = Franchise.query.get(f.team_a_id)
        t2 = Franchise.query.get(f.team_b_id)
        if not t1 or not t2:
            errors.append(f"Match #{f.match_number}: One or both teams do not exist in database.")

        # Check venue
        if not f.venue or not f.venue.strip():
            errors.append(f"Match #{f.match_number}: Missing venue.")

        # Check duplicate pairing in same stage
        pair_key = (f.stage, min(f.team_a_id, f.team_b_id), max(f.team_a_id, f.team_b_id))
        if f.stage == FixtureStage.LEAGUE:
            # For league, flag duplicate if same directional or exact pairing appears unnecessarily
            exact_pair = (f.team_a_id, f.team_b_id, f.stage)
            if exact_pair in seen_pairings:
                errors.append(f"Match #{f.match_number}: Duplicate matchup ({t1.short_name if t1 else 'A'} vs {t2.short_name if t2 else 'B'}).")
            seen_pairings.add(exact_pair)

    return len(errors) == 0, errors

def publish_fixtures(admin_id):
    """Publish all draft fixtures after validation."""
    is_valid, errors = validate_fixtures()
    if not is_valid:
        raise ValueError(f"Cannot publish fixtures due to validation errors: {'; '.join(errors)}")

    fixtures = Fixture.query.all()
    if not fixtures:
        raise ValueError("No fixtures available to publish.")

    for f in fixtures:
        f.is_published = True

    db.session.commit()
    log_audit(admin_id, 'FIXTURE_PUBLISHED', 'Fixture', None, None, f"Published {len(fixtures)} fixtures")
    return len(fixtures)

def unpublish_fixtures(admin_id):
    """Unpublish all fixtures."""
    fixtures = Fixture.query.all()
    for f in fixtures:
        f.is_published = False

    db.session.commit()
    log_audit(admin_id, 'FIXTURE_UNPUBLISHED', 'Fixture', None, None, f"Unpublished {len(fixtures)} fixtures")
    return len(fixtures)
