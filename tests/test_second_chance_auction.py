import os
import json
import pytest
from datetime import datetime, timedelta
from app import create_app
from app.extensions import db
from app.models import (
    User, Player, Franchise, PlayerStatus, PlayerRole, PlayerCategory,
    AuctionState, AuctionStatus, SystemSettings, Bid
)
from app.services.auction_service import (
    get_auction_state, activate_player, start_bidding, place_bid, finalize_sold,
    get_bid_increment_rules, get_next_bid_increment, start_second_chance_auction
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
def setup_sc_entities(app):
    with app.app_context():
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

        # Eligible unsold players for second chance
        p1 = Player(
            name='Unsold Player Alpha',
            roll_number='SC01',
            role='BATSMAN',
            category='NORMAL',
            status=PlayerStatus.UNSOLD,
            is_second_chance_eligible=True,
            base_price=10000.0
        )
        p2 = Player(
            name='Unsold Player Beta',
            roll_number='SC02',
            role='ALL_ROUNDER',
            category='NORMAL',
            status=PlayerStatus.UNSOLD,
            is_second_chance_eligible=True,
            base_price=10000.0
        )
        db.session.add_all([p1, p2])

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

def test_second_chance_dynamic_timer_and_start_button_workflow(app, setup_sc_entities, client, admin_user):
    """
    Test: Second chance auction uses the same workflow as primary auction:
    1. Dynamic timer duration (e.g. 25s instead of hardcoded 10s).
    2. Player activation enters PLAYER_PREVIEW without ticking.
    3. Explicit start_bidding transitions to BIDDING and starts countdown with configured duration.
    4. Bids reset timer to configured duration.
    """
    with app.app_context():
        entities = setup_sc_entities

        # Configure dynamic timer to 25 seconds
        SystemSettings.set_setting('timer_seconds', '25')

        # Sign in admin for API calls
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user)
            sess['_fresh'] = True

        # Activate player without auto-start (loads in preview with Start Auction ready)
        res = client.post('/api/auction/activate', json={
            'player_id': entities['p1_id'],
            'auto_start': False
        })
        assert res.status_code == 200
        data = res.get_json()
        assert data['success'] is True
        assert data['status'] == 'PLAYER_PREVIEW'

        # Check state: timer is not running yet
        state_res = client.get('/api/auction/state')
        state_data = state_res.get_json()
        assert state_data['status'] == 'PLAYER_PREVIEW'
        assert state_data['active_player']['id'] == entities['p1_id']
        assert state_data['timer_seconds'] == 25
        assert state_data['remaining_seconds'] is None

        # Operator clicks "Start Auction" button -> POST /api/auction/start
        start_res = client.post('/api/auction/start')
        assert start_res.status_code == 200
        start_data = start_res.get_json()
        assert start_data['success'] is True
        assert start_data['status'] == 'BIDDING'
        assert start_data['timer_seconds'] == 25

        # Live state now shows BIDDING with remaining seconds <= 25 and >= 24
        live_res = client.get('/api/auction/state')
        live_data = live_res.get_json()
        assert live_data['status'] == 'BIDDING'
        assert live_data['remaining_seconds'] >= 24

        # Place bid from franchise 1 -> resets timer to configured 25s
        bid_res = client.post('/api/auction/admin-bid', json={
            'franchise_id': entities['f1_id']
        })
        assert bid_res.status_code == 200
        bid_state_res = client.get('/api/auction/state')
        bid_state_data = bid_state_res.get_json()
        assert bid_state_data['highest_bidder']['id'] == entities['f1_id']
        assert bid_state_data['current_bid'] == 10000.0
        assert bid_state_data['remaining_seconds'] >= 24

def test_second_chance_dynamic_intervals(app, setup_sc_entities, client, admin_user):
    """
    Test: Dynamic bid increment interval rules configured in SystemSettings apply to second chance auction.
    """
    with app.app_context():
        entities = setup_sc_entities

        # Configure custom intervals:
        # ₹10,000 - ₹30,000: +₹3,000
        # ₹30,000 - ₹100,000: +₹7,000
        rules = [
            {"id": 1, "min_price": 10000, "max_price": 30000, "increment": 3000},
            {"id": 2, "min_price": 30000, "max_price": 100000, "increment": 7000}
        ]
        SystemSettings.set_setting('bid_increment_rules', json.dumps(rules))

        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user)
            sess['_fresh'] = True

        client.post('/api/auction/activate', json={'player_id': entities['p1_id'], 'auto_start': False})
        client.post('/api/auction/start')

        # Check increment at opening bid 10,000
        state = client.get('/api/auction/state').get_json()
        assert state['increment'] == 3000.0

        # Franchise 1 places opening bid (10,000)
        client.post('/api/auction/admin-bid', json={'franchise_id': entities['f1_id']})
        state = client.get('/api/auction/state').get_json()
        assert state['current_bid'] == 10000.0
        # Next valid bid should be 10,000 + 3,000 = 13,000
        assert state['next_valid_bid'] == 13000.0

        # Franchise 2 bids -> 13,000
        client.post('/api/auction/admin-bid', json={'franchise_id': entities['f2_id']})
        state = client.get('/api/auction/state').get_json()
        assert state['current_bid'] == 13000.0
        assert state['next_valid_bid'] == 16000.0

def test_second_chance_sold_persistence(app, setup_sc_entities, client, admin_user):
    """
    Test: Sold player screen persists on screen and does not auto-clear after 10s (matching primary auction update).
    """
    with app.app_context():
        entities = setup_sc_entities

        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user)
            sess['_fresh'] = True

        client.post('/api/auction/activate', json={'player_id': entities['p1_id'], 'auto_start': False})
        client.post('/api/auction/start')
        client.post('/api/auction/admin-bid', json={'franchise_id': entities['f1_id']})

        # Finalize sold
        sold_res = client.post('/api/auction/sold')
        assert sold_res.status_code == 200

        # Verify state: SOLD, and sold_display_until is None (persistent, no 10-second auto-clear timer)
        state_data = client.get('/api/auction/state').get_json()
        assert state_data['status'] == 'SOLD'
        assert state_data['sold_until_timestamp'] is None
        assert state_data['winning_franchise']['name'] == 'Royal Challengers'

        # Loading next player replaces the sold screen into PREVIEW
        client.post('/api/auction/activate', json={'player_id': entities['p2_id'], 'auto_start': False})
        new_state = client.get('/api/auction/state').get_json()
        assert new_state['status'] == 'PLAYER_PREVIEW'
        assert new_state['active_player']['id'] == entities['p2_id']

def test_second_chance_search_and_validations(app, setup_sc_entities, client, admin_user):
    """
    Test: Search player for second chance auction enforces eligibility and sold checks.
    """
    with app.app_context():
        entities = setup_sc_entities

        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user)
            sess['_fresh'] = True

        # Search existing eligible unsold player by roll number
        res = client.get('/api/auction/search-player?query=SC01&mode=SECOND_CHANCE')
        assert res.status_code == 200
        data = res.get_json()
        assert data['success'] is True
        assert data['player']['name'] == 'Unsold Player Alpha'

        # Search non-existent player
        res_not_found = client.get('/api/auction/search-player?query=NONEXISTENT&mode=SECOND_CHANCE')
        assert res_not_found.status_code == 404

def test_second_chance_dashboard_rendering(app, setup_sc_entities, client, admin_user):
    """
    Test: GET /admin/second-chance renders the updated second chance console successfully.
    """
    with app.app_context():
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user)
            sess['_fresh'] = True

        res = client.get('/admin/second-chance')
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert 'Second-Chance Auction Console' in html
        assert 'sc-start-auction-prompt-banner' in html
        assert 'Start Auction' in html
        assert 'sc-franchise-cards-container' in html
        assert 'sc-roster-players-table' in html

