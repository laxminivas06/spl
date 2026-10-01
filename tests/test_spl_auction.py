import os
import shutil
import pytest
from datetime import datetime, timedelta
from app import create_app
from app.extensions import db
from app.models import (
    User, Franchise, Player, PlayerStatus, PlayerRole,
    AuctionState, AuctionStatus
)
from app.services import auction_service

@pytest.fixture(scope='session')
def app():
    # Setup test app
    test_data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'instance', 'test_data')
    if os.path.exists(test_data_dir):
        shutil.rmtree(test_data_dir, ignore_errors=True)

    app = create_app('testing')
    app.config['JSON_DATA_DIR'] = test_data_dir
    app.config['WTF_CSRF_ENABLED'] = False

    with app.app_context():
        # Initialize test data
        db.create_all()

        # Create Admin
        admin = User(
            username='admin_test',
            email='admin@test.com',
            role='ADMIN',
            is_active=True
        )
        db.session.add(admin)

        # Create Franchise with captain
        franchise = Franchise(
            name='Test Warriors',
            short_name='TW',
            owner_name='Test Owner',
            registered_email='owner@test.com',
            purse_amount=300000,
            remaining_purse=300000,
            squad_limit=15,
            captain_name='Test Captain',
            captain_rule_number='23-0001'
        )
        db.session.add(franchise)

        # Create Players
        p1 = Player(
            name='Rohit Sharma',
            roll_number='23-0101',
            role=PlayerRole.BATSMAN,
            category='NORMAL',
            branch='CSE',
            year='4th',
            base_price=10000,
            status=PlayerStatus.AVAILABLE
        )
        p2 = Player(
            name='Jasprit Bumrah',
            roll_number='23-0102',
            role=PlayerRole.BOWLER,
            category='NORMAL',
            branch='ECE',
            year='3rd',
            base_price=10000,
            status=PlayerStatus.UNSOLD,
            is_second_chance_eligible=True
        )
        p3 = Player(
            name='Virat Kohli',
            roll_number='23-0103',
            role=PlayerRole.BATSMAN,
            category='NORMAL',
            branch='IT',
            year='4th',
            base_price=10000,
            status=PlayerStatus.AVAILABLE
        )
        db.session.add_all([p1, p2, p3])
        db.session.commit()

        # Initialize auction state
        auction_service.get_auction_state()

        yield app

        # Teardown
        if os.path.exists(test_data_dir):
            shutil.rmtree(test_data_dir, ignore_errors=True)

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture
def auth_admin(client, app):
    with client.session_transaction() as sess:
        with app.app_context():
            admin = User.query.filter_by(role='ADMIN').first()
            sess['_user_id'] = str(admin.id)
            sess['user_role'] = 'admin'
    return client


def test_player_sold_properties(app):
    with app.app_context():
        p = Player.query.filter_by(roll_number='23-0101').first()
        assert not p.is_sold
        p_dict = p.to_dict()
        assert 'sold_to' in p_dict
        assert 'soldTo' in p_dict
        assert 'sold_price' in p_dict
        assert 'soldPrice' in p_dict
        assert 'sold_at' in p_dict
        assert 'soldAt' in p_dict
        assert 'is_sold' in p_dict
        assert p_dict['is_sold'] is False


def test_finalize_sold_sets_10s_timer_and_status(app):
    with app.app_context():
        p = Player.query.filter_by(roll_number='23-0101').first()
        f = Franchise.query.first()
        
        # Activate player
        state = auction_service.activate_player(p.id)
        assert state.active_player_id == p.id
        
        # Start bidding
        state = auction_service.start_bidding()
        assert state.status == AuctionStatus.BIDDING
        
        # Place bid
        state = auction_service.place_bid(f.id, 20000)
        assert state.current_bid == 20000
        assert state.highest_bidder_id == f.id
        
        # Finalize sold
        player, winner, price = auction_service.finalize_sold()
        assert player.id == p.id
        assert price == 20000
        
        # Reload player and state
        p = Player.query.get(p.id)
        state = auction_service.get_auction_state()
        
        # Requirement 2: Status permanently marked SOLD with metadata
        assert p.status == PlayerStatus.SOLD
        assert p.is_sold is True
        assert p.sold_to == f.id
        assert p.sold_price == 20000
        assert p.sold_at is not None
        
        # Requirement 1 & 8: 10-second timer set
        assert state.status == AuctionStatus.SOLD
        assert state.sold_display_until is not None
        assert 0 < state.sold_remaining_seconds <= 10


def test_clear_sold_player_resets_state(app):
    with app.app_context():
        # Clear sold player
        state = auction_service.clear_sold_player()
        assert state.status == AuctionStatus.WAITING
        assert state.active_player_id is None
        assert state.sold_display_until is None
        assert state.current_bid == 0


def test_sold_player_rejected_from_auction(app):
    with app.app_context():
        # Requirement 2: Strict rejection at data/logic level
        p = Player.query.filter_by(roll_number='23-0101').first()
        assert p.is_sold is True
        
        # Primary lookup must reject
        with pytest.raises(ValueError) as excinfo:
            auction_service.find_player_by_roll('23-0101')
        assert 'already been sold' in str(excinfo.value).lower()
        
        # Activation must reject
        with pytest.raises(ValueError) as excinfo2:
            auction_service.activate_player(p.id)
        assert 'already sold' in str(excinfo2.value).lower()
        
        # Second-chance lookup must reject (Requirement 6)
        with pytest.raises(ValueError) as excinfo3:
            auction_service.find_second_chance_player_by_roll('23-0101')
        assert 'already sold' in str(excinfo3.value).lower()


def test_update_rule_number_and_duplicate_prevention(app):
    with app.app_context():
        p3 = Player.query.filter_by(roll_number='23-0103').first()
        
        # Duplicate test: attempting to update to 23-0102 (Bumrah)
        with pytest.raises(ValueError) as excinfo:
            auction_service.update_player_rule_number(p3.id, '23-0102')
        assert 'already in use' in str(excinfo.value).lower()
        
        # Successful update: 23-0103 -> 23-0789
        updated_p = auction_service.update_player_rule_number(p3.id, '23-0789')
        assert updated_p.roll_number == '23-0789'
        assert updated_p.rule_number == '23-0789'
        
        # Verify persistence
        p_reloaded = Player.query.get(p3.id)
        assert p_reloaded.roll_number == '23-0789'
        assert p_reloaded.rule_number == '23-0789'


def test_api_search_player_primary_and_second_chance(auth_admin):
    # Requirement 3: Search by Rule Number for sold player
    res = auth_admin.get('/api/auction/search-player?rule=23-0101&mode=primary')
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert data['player']['name'] == 'Rohit Sharma'
    assert data['is_sold'] is True
    assert data['can_auction'] is False
    assert data['player']['sold_to'] is not None

    # Requirement 5 & 6: Second-Chance search for sold player must be blocked
    res_sc = auth_admin.get('/api/auction/search-player?rule=23-0101&mode=second_chance')
    assert res_sc.status_code == 200
    data_sc = res_sc.get_json()
    assert data_sc['success'] is True
    assert data_sc['is_sold'] is True
    assert data_sc['can_auction'] is False

    # Second-chance search for eligible unsold player (23-0102)
    res_sc_ok = auth_admin.get('/api/auction/search-player?rule=23-0102&mode=second_chance')
    assert res_sc_ok.status_code == 200
    data_sc_ok = res_sc_ok.get_json()
    assert data_sc_ok['success'] is True
    assert data_sc_ok['player']['name'] == 'Jasprit Bumrah'
    assert data_sc_ok['is_sold'] is False
    assert data_sc_ok['can_auction'] is True


def test_api_update_rule_number_endpoint(auth_admin):
    # Find player 23-0789
    res = auth_admin.get('/api/auction/search-player?rule=23-0789&mode=primary')
    assert res.status_code == 200
    player_id = res.get_json()['player']['id']

    # Update to 23-0999
    post_res = auth_admin.post('/api/auction/update-rule-number', json={
        'player_id': player_id,
        'new_rule_number': '23-0999'
    })
    assert post_res.status_code == 200
    data = post_res.get_json()
    assert data['success'] is True
    assert data['player']['rule_number'] == '23-0999'

    # Verify search with new rule number
    new_search = auth_admin.get('/api/auction/search-player?rule=23-0999&mode=primary')
    assert new_search.status_code == 200
    assert new_search.get_json()['success'] is True
    assert new_search.get_json()['player']['id'] == player_id


def test_api_state_auto_clears_expired_sold_player(app, auth_admin):
    with app.app_context():
        # Set state to sold with sold_display_until in the past
        state = auction_service.get_auction_state()
        p = Player.query.filter_by(roll_number='23-0101').first()
        state.status = AuctionStatus.SOLD
        state.active_player_id = p.id
        state.sold_display_until = datetime.utcnow() - timedelta(seconds=2)
        db.session.commit()

    # Query /api/auction/state -> Should auto-clear
    res = auth_admin.get('/api/auction/state')
    assert res.status_code == 200
    data = res.get_json()
    assert data['status'] == 'WAITING'
    assert data['active_player'] is None


def test_admin_auction_views(auth_admin):
    # Test GET /admin/auction (Primary Auction Console)
    res = auth_admin.get('/admin/auction')
    assert res.status_code == 200
    assert b'Search by Rule Number' in res.data

    # Test GET /admin/second-chance (Second Chance Auction Console)
    res_sc = auth_admin.get('/admin/second-chance')
    assert res_sc.status_code == 200
    assert b'Search by Rule Number' in res_sc.data


def test_purse_starts_at_3_lakhs_and_single_32k_deduction(app):
    with app.app_context():
        f = Franchise.query.first()
        f.starting_purse = 300000.0
        f.recalculate_purse()
        assert f.starting_purse == 300000.0
        initial_remaining = f.remaining_purse

        # Create fresh player for test
        p = Player(
            name='Virat Kohli',
            roll_number='23-9999',
            role=PlayerRole.BATSMAN,
            category='NORMAL',
            base_price=10000,
            status=PlayerStatus.AVAILABLE
        )
        db.session.add(p)
        db.session.commit()

        initial_spent = f.spent_purse
        initial_remaining = f.remaining_purse

        # Place bid for 32,000
        auction_service.activate_player(p.id)
        auction_service.start_bidding()
        auction_service.place_bid(f.id, 32000.0)

        # Finalize sold
        auction_service.finalize_sold()

        # Spent must increase by exactly 32,000 and remaining decrease by 32,000
        assert f.spent_purse == initial_spent + 32000.0
        assert f.remaining_purse == initial_remaining - 32000.0

        # Repeated finalize call must NOT double deduct
        auction_service.finalize_sold()
        assert f.spent_purse == initial_spent + 32000.0
        assert f.remaining_purse == initial_remaining - 32000.0


def test_mandatory_team_captain_has_dash_price(app):
    with app.app_context():
        f = Franchise.query.first()
        from app.services.team_service import add_team_captain
        add_team_captain(
            franchise=f,
            name="Squad Captain",
            rule_number="CAP-TEST",
            department="CSE",
            year="4th"
        )

        assert f.has_captain is True
        cap = f.captain_player
        assert cap is not None
        assert cap.is_captain is True
        assert cap.display_price == "—"
        assert cap.sold_price == 0.0

        # Squad players list includes captain at top
        squad = f.squad_players
        assert squad[0].id == cap.id
        assert squad[0].is_captain is True
        assert squad[0].display_price == "—"

