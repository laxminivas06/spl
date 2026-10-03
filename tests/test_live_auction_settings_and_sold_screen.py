import os
import json
import pytest
from datetime import datetime, timedelta
from app import create_app
from app.extensions import db
from app.models import User, Player, Franchise, PlayerStatus, PlayerRole, PlayerCategory, AuctionState, AuctionStatus, SystemSettings, Bid
from app.services.auction_service import (
    get_auction_state, activate_player, start_bidding, place_bid, finalize_sold,
    get_bid_increment_rules, add_bid_increment_rule, edit_bid_increment_rule,
    delete_bid_increment_rule, get_next_bid_increment
)

@pytest.fixture
def app(tmp_path):
    app = create_app('test')
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['JSON_DATA_DIR'] = str(tmp_path / 'data')
    app.config['UPLOAD_FOLDER'] = str(tmp_path / 'uploads')
    os.makedirs(app.config['JSON_DATA_DIR'], exist_ok=True)
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    with app.app_context():
        db.create_all()
    return app

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture
def admin_user(app):
    with app.app_context():
        admin = User(
            username='admin_test',
            email='admin_test@spl.com',
            role='ADMIN',
            is_active=True
        )
        admin.set_password('adminpass123')
        db.session.add(admin)
        db.session.commit()
        return admin.id

@pytest.fixture
def setup_auction_entities(app):
    with app.app_context():
        # Create 2 Franchises with captains
        f1 = Franchise(
            name='Royal Challengers',
            short_name='RC',
            starting_purse=550000.0,
            remaining_purse=500000.0,
            squad_limit=15,
            captain_name='Captain RC',
            captain_rule_number='CAP01',
            is_active=True
        )
        f2 = Franchise(
            name='Super Kings',
            short_name='SK',
            starting_purse=550000.0,
            remaining_purse=500000.0,
            squad_limit=15,
            captain_name='Captain SK',
            captain_rule_number='CAP02',
            is_active=True
        )
        db.session.add_all([f1, f2])
        db.session.commit()

        # Auctionable players
        p1 = Player(
            name='Player Alpha',
            roll_number='R01',
            role='BATSMAN',
            category='NORMAL',
            status=PlayerStatus.AVAILABLE,
            base_price=10000.0
        )
        p2 = Player(
            name='Player Beta',
            roll_number='R02',
            role='ALL_ROUNDER',
            category='NORMAL',
            status=PlayerStatus.AVAILABLE,
            base_price=10000.0
        )
        db.session.add_all([p1, p2])

        # Reset global auction state to pristine WAITING
        state = get_auction_state()
        state.status = AuctionStatus.WAITING
        state.active_player_id = None
        state.highest_bidder_id = None
        state.current_bid = 0.0
        state.timer_end = None
        state.sold_display_until = None

        db.session.commit()

        f1.recalculate_purse()
        f2.recalculate_purse()

        return {
            'f1_id': f1.id,
            'f2_id': f2.id,
            'p1_id': p1.id,
            'p2_id': p2.id
        }


def test_configurable_bid_timer(app, setup_auction_entities):
    """Test 1: Admin can configure bidding duration and it is dynamically used."""
    with app.app_context():
        entities = setup_auction_entities

        # Configure timer to 45 seconds
        SystemSettings.set_setting('timer_seconds', '45')
        assert SystemSettings.get_setting('timer_seconds') == '45'

        # Activate player and start bidding
        activate_player(entities['p1_id'])
        state = start_bidding()

        assert state.status == AuctionStatus.BIDDING
        assert state.timer_seconds == 45
        assert state.remaining_seconds >= 44
        assert state.sold_display_until is None

        # Change timer configuration to 20 seconds
        SystemSettings.set_setting('timer_seconds', '20')

        # Place a bid from franchise 1
        state = place_bid(entities['f1_id'], 10000.0)
        assert state.status == AuctionStatus.BIDDING
        assert state.timer_seconds == 20
        assert state.remaining_seconds >= 19


def test_bid_increment_rules_crud(app):
    """Test 2: Payment conditions / bid increment rules CRUD and validations."""
    with app.app_context():
        # Initial default rules: 4 rules
        rules = get_bid_increment_rules()
        assert len(rules) >= 4

        # Add condition: ₹1,00,00,000 to ₹5,00,00,000 with ₹50,000 increment
        rules, new_rule = add_bid_increment_rule(10000000, 50000000, 50000)
        assert new_rule['min_price'] == 10000000
        assert new_rule['max_price'] == 50000000
        assert new_rule['increment'] == 50000

        # Overlap prevention: Attempting to add an overlapping range should fail
        with pytest.raises(ValueError, match="overlaps with existing condition"):
            add_bid_increment_rule(20000000, 30000000, 10000)

        # Validation: Max price <= Min price should fail
        with pytest.raises(ValueError, match="strictly greater"):
            add_bid_increment_rule(60000000, 50000000, 5000)

        # Validation: Negative min price should fail
        with pytest.raises(ValueError, match="cannot be negative"):
            add_bid_increment_rule(-1000, 50000, 5000)

        # Validation: Non-positive increment should fail
        with pytest.raises(ValueError, match="positive number"):
            add_bid_increment_rule(60000000, 70000000, 0)

        # Edit condition
        updated_rules = edit_bid_increment_rule(new_rule['id'], 10000000, 50000000, 75000)
        edited_r = [r for r in updated_rules if r['id'] == new_rule['id']][0]
        assert edited_r['increment'] == 75000

        # Delete condition
        after_delete = delete_bid_increment_rule(new_rule['id'])
        assert not any(r['id'] == new_rule['id'] for r in after_delete)


def test_dynamic_bid_increment_boundary_values(app):
    """Test 3: Increment calculation dynamically applies to price ranges and handles boundaries."""
    with app.app_context():
        # Clean rules:
        # ₹10,000 – ₹20,000: ₹2,000
        # ₹20,000 – ₹50,000: ₹5,000
        # ₹50,000 – ₹1,00,000: ₹10,000
        # Above ₹1,00,000: ₹10,000
        test_rules = [
            {"id": 1, "min_price": 10000, "max_price": 20000, "increment": 2000},
            {"id": 2, "min_price": 20000, "max_price": 50000, "increment": 5000},
            {"id": 3, "min_price": 50000, "max_price": 100000, "increment": 10000},
            {"id": 4, "min_price": 100000, "max_price": 10000000, "increment": 10000}
        ]
        SystemSettings.set_setting('bid_increment_rules', json.dumps(test_rules))

        # Test within range 1 (10,000 to 20,000 -> 2,000)
        assert get_next_bid_increment(10000) == 2000
        assert get_next_bid_increment(15000) == 2000
        assert get_next_bid_increment(18000) == 2000

        # Boundary at 20,000: belongs to [20000, 50000) -> 5,000
        assert get_next_bid_increment(20000) == 5000
        assert get_next_bid_increment(35000) == 5000
        assert get_next_bid_increment(45000) == 5000

        # Boundary at 50,000: belongs to [50000, 100000) -> 10,000
        assert get_next_bid_increment(50000) == 10000
        assert get_next_bid_increment(75000) == 10000

        # Boundary at 1,00,000: belongs to [100000, 10000000) -> 10,000
        assert get_next_bid_increment(100000) == 10000
        assert get_next_bid_increment(250000) == 10000

        # Above highest range
        assert get_next_bid_increment(15000000) == 10000

        # Below lowest range
        assert get_next_bid_increment(5000) == 2000


def test_sold_player_screen_persistence(app, setup_auction_entities, client, admin_user):
    """Test 4: Sold player screen persists on screen and does not auto-clear to waiting."""
    with app.app_context():
        entities = setup_auction_entities

        # Sign in admin for API calls
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user)
            sess['_fresh'] = True

        # Activate player 1, start bidding, place winning bid
        activate_player(entities['p1_id'])
        start_bidding()
        place_bid(entities['f1_id'], 25000.0)

        # Finalize sold
        finalize_sold(admin_user)

        state = get_auction_state()
        assert state.status == AuctionStatus.SOLD
        assert state.sold_display_until is None  # No auto-clearing timer

        # Call GET /api/auction/state
        res = client.get('/api/auction/state')
        assert res.status_code == 200
        data = res.get_json()

        assert data['status'] == 'SOLD'
        assert data['active_player']['name'] == 'Player Alpha'
        assert data['sold_price'] == 25000.0
        assert data['winning_franchise']['name'] == 'Royal Challengers'
        assert data['last_sold'] is not None
        assert data['last_sold']['player']['name'] == 'Player Alpha'

        # Poll again to ensure it remains in SOLD state and does not auto-clear to WAITING
        res2 = client.get('/api/auction/state')
        data2 = res2.get_json()
        assert data2['status'] == 'SOLD'
        assert data2['active_player']['name'] == 'Player Alpha'

        # Now when the operator loads Player B (Player Beta):
        activate_player(entities['p2_id'])
        new_state = get_auction_state()
        assert new_state.status == AuctionStatus.PLAYER_PREVIEW
        assert new_state.active_player_id == entities['p2_id']

        # Verify state endpoint now transitions to new player
        res3 = client.get('/api/auction/state')
        data3 = res3.get_json()
        assert data3['status'] == 'PLAYER_PREVIEW'
        assert data3['active_player']['name'] == 'Player Beta'
        assert data3['last_sold']['player']['name'] == 'Player Alpha'
