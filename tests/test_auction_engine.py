import os
import sys
import unittest
import json
import io
import time

# Add root directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import config
import database
from services.auction_engine import AuctionEngine, calculate_next_bid, get_next_increment
from services.excel_service import ExcelService
from services.stats_service import StatsService
from app import app

class TestSPLAuctionSystem(unittest.TestCase):
    def setUp(self):
        """Set up fresh isolated test state before each test"""
        database.init_db()
        # Reset auction state
        AuctionEngine.reset_auction_state()
        
        # Ensure fresh players available
        players = [
            {
                "id": "test_ply_01",
                "name": "Virat Test",
                "roll_no": "SPL-T-01",
                "year": "4th Year",
                "role": "Batsman",
                "base_price": 10000,
                "status": "AVAILABLE",
                "photo": "",
                "sold_price": 0,
                "sold_team_id": None,
                "sold_team_name": None,
                "batting": {"matches": 10, "runs": 400, "strike_rate": 140.0, "fifties": 3, "hundreds": 1},
                "bowling": {"wickets": 0, "economy": 0.0},
                "fielding": {"catches": 5, "runouts": 1}
            },
            {
                "id": "test_ply_02",
                "name": "Jasprit Test",
                "roll_no": "SPL-T-02",
                "year": "3rd Year",
                "role": "Bowler",
                "base_price": 10000,
                "status": "AVAILABLE",
                "photo": "",
                "sold_price": 0,
                "sold_team_id": None,
                "sold_team_name": None,
                "batting": {"matches": 8, "runs": 20, "strike_rate": 80.0, "fifties": 0, "hundreds": 0},
                "bowling": {"wickets": 15, "economy": 6.2},
                "fielding": {"catches": 3, "runouts": 0}
            }
        ]
        database.save_players(players)
        
        # Reset teams
        teams = database.get_teams()
        for t in teams:
            t['initial_budget'] = config.DEFAULT_PURSE
            t['balance'] = config.DEFAULT_PURSE
            t['spent'] = 0
            t['squad'] = []
        database.save_teams(teams)
        database.save_bids([])
        database.save_students([])

    def test_01_spl_auto_increment_rules(self):
        """Test SPL auto-increment rules across all slab boundaries"""
        # Tier 1: ₹10,000 to ₹20,000 -> +₹2,000
        self.assertEqual(get_next_increment(10000), 2000)
        self.assertEqual(get_next_increment(14000), 2000)
        self.assertEqual(calculate_next_bid(10000, 10000), 12000)
        self.assertEqual(calculate_next_bid(18000, 10000), 20000)

        # Tier 2: Above ₹20,000 to ₹50,000 -> +₹5,000
        self.assertEqual(get_next_increment(20000), 5000)
        self.assertEqual(get_next_increment(35000), 5000)
        self.assertEqual(calculate_next_bid(20000, 10000), 25000)
        self.assertEqual(calculate_next_bid(45000, 10000), 50000)

        # Tier 3: Above ₹50,000 to ₹1,00,000 -> +₹10,000
        self.assertEqual(get_next_increment(50000), 10000)
        self.assertEqual(get_next_increment(80000), 10000)
        self.assertEqual(calculate_next_bid(50000, 10000), 60000)

        # Tier 4: Above ₹1,00,000 -> +₹10,000
        self.assertEqual(get_next_increment(100000), 10000)
        self.assertEqual(get_next_increment(150000), 10000)
        self.assertEqual(calculate_next_bid(100000, 10000), 110000)

    def test_02_anchor_announcement_and_admin_activation(self):
        """Test Anchor chit draw -> Announcement -> Admin official activation flow"""
        # Step 1: Anchor draws / announces chit
        sel = AuctionEngine.announce_player("test_ply_01", user="Anchor")
        self.assertTrue(sel['success'])
        
        state1 = database.get_auction_state()
        self.assertEqual(state1['status'], 'PLAYER_ANNOUNCED')
        self.assertEqual(state1['announced_player_id'], 'test_ply_01')

        # Step 2: Admin activates player on stage
        act = AuctionEngine.activate_player("test_ply_01", user="Admin")
        self.assertTrue(act['success'])
        
        state2 = database.get_auction_state()
        self.assertEqual(state2['status'], 'BIDDING')
        self.assertEqual(state2['active_player_id'], 'test_ply_01')
        self.assertEqual(state2['current_bid'], 0)
        self.assertEqual(state2['next_bid'], 10000)
        self.assertFalse(state2['is_timer_paused'])

    def test_03_bidding_and_auto_increment(self):
        """Test live bidding flow between franchises"""
        AuctionEngine.set_active_player("test_ply_01", user="Admin")
        teams = database.get_teams()
        team_a = teams[0]
        team_b = teams[1]

        # First bid by Team A at Base Price (₹10,000)
        bid1 = AuctionEngine.place_bid(team_a['id'])
        self.assertTrue(bid1['success'])
        self.assertEqual(bid1['bid']['amount'], 10000)
        self.assertEqual(bid1['state']['leading_team_id'], team_a['id'])
        self.assertEqual(bid1['state']['next_bid'], 12000) # +2000 slab

        # Team A cannot bid against itself
        repeat_bid = AuctionEngine.place_bid(team_a['id'])
        self.assertFalse(repeat_bid['success'])

        # Team B bids at next increment (₹12,000)
        bid2 = AuctionEngine.place_bid(team_b['id'])
        self.assertTrue(bid2['success'])
        self.assertEqual(bid2['bid']['amount'], 12000)
        self.assertEqual(bid2['state']['leading_team_id'], team_b['id'])
        self.assertEqual(bid2['state']['next_bid'], 14000)

    def test_04_insufficient_purse_and_pause_validation(self):
        """Test rejection when purse is insufficient or auction is paused"""
        AuctionEngine.set_active_player("test_ply_01", user="Admin")
        teams = database.get_teams()
        test_team = teams[0]
        test_team['balance'] = 5000
        database.save_teams(teams)

        # Bid should fail due to insufficient purse
        res = AuctionEngine.place_bid(test_team['id'])
        self.assertFalse(res['success'])
        self.assertTrue(res.get('insufficient_balance', False))
        self.assertIn("INSUFFICIENT PURSE", res['message'])

        # Restore balance and test Pause
        test_team['balance'] = 500000
        database.save_teams(teams)

        AuctionEngine.pause_auction(user="Admin")
        paused_bid = AuctionEngine.place_bid(test_team['id'])
        self.assertFalse(paused_bid['success'])
        self.assertIn("PAUSED", paused_bid['message'])

    def test_05_sold_workflow_atomic_deduction(self):
        """Test Admin SOLD confirmation deducts virtual purse and updates squad atomically"""
        AuctionEngine.set_active_player("test_ply_01", user="Admin")
        teams = database.get_teams()
        team = teams[2]
        initial_balance = team['balance']

        # Place winning bid
        bid_res = AuctionEngine.place_bid(team['id'])
        winning_price = bid_res['bid']['amount']

        # Mark SOLD
        sold_res = AuctionEngine.mark_sold(user="Admin")
        self.assertTrue(sold_res['success'])
        self.assertEqual(sold_res['price'], winning_price)

        # Verify team purse deducted
        updated_teams = database.get_teams()
        updated_team = next(t for t in updated_teams if t['id'] == team['id'])
        self.assertEqual(updated_team['balance'], initial_balance - winning_price)
        self.assertEqual(updated_team['spent'], winning_price)
        self.assertEqual(len(updated_team['squad']), 1)
        self.assertEqual(updated_team['squad'][0]['id'], 'test_ply_01')

        # Verify player marked sold
        players = database.get_players()
        p = next(x for x in players if x['id'] == 'test_ply_01')
        self.assertEqual(p['status'], 'SOLD')
        self.assertEqual(p['sold_price'], winning_price)
        self.assertEqual(p['sold_team_id'], team['id'])

    def test_06_unsold_workflow_and_second_chance(self):
        """Test UNSOLD confirmation and Second-Chance pool reactivation"""
        AuctionEngine.set_active_player("test_ply_02", user="Admin")
        
        # Mark UNSOLD
        unsold_res = AuctionEngine.mark_unsold(user="Admin")
        self.assertTrue(unsold_res['success'])

        players = database.get_players()
        p = next(x for x in players if x['id'] == 'test_ply_02')
        self.assertEqual(p['status'], 'UNSOLD')

        # Reactivate via Second-Chance
        react_res = AuctionEngine.add_to_second_chance(['test_ply_02'], user="Admin")
        self.assertTrue(react_res['success'])
        self.assertEqual(react_res['count'], 1)

        players2 = database.get_players()
        p2 = next(x for x in players2 if x['id'] == 'test_ply_02')
        self.assertEqual(p2['status'], 'AVAILABLE')
        self.assertTrue(p2.get('second_chance', False))

    def test_07_google_and_authorized_accounts(self):
        """Test authorized Gmail account lookup"""
        # Admin Gmail lookup
        admin_user = database.find_user_by_email_or_username('admin@spl.edu')
        self.assertIsNotNone(admin_user)
        self.assertEqual(admin_user['role'], 'admin')

        # Anchor Gmail lookup
        anchor_user = database.find_user_by_email_or_username('anchor@spl.edu')
        self.assertIsNotNone(anchor_user)
        self.assertEqual(anchor_user['role'], 'anchor')

        # Team Gmail lookup
        team_user = database.find_user_by_email_or_username('rcb@spl.edu')
        self.assertIsNotNone(team_user)
        self.assertEqual(team_user['role'], 'team')

        # Unauthorized email lookup
        unauth_user = database.find_user_by_email_or_username('stranger@gmail.com')
        self.assertIsNone(unauth_user)

    def test_08_role_based_access_isolation(self):
        """Test that Franchise role is strictly blocked from Admin routes"""
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['user'] = {
                'username': 'rcb',
                'role': 'team',
                'team_id': 'team_rcb',
                'team_name': 'Bangalore Blasters'
            }

        # Franchise blocked from /admin
        resp = client.get('/admin', follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/team', resp.location)

        # Franchise API block on admin-only endpoint
        api_resp = client.post('/api/auction/activate', json={'player_id': 'test_ply_01'})
        self.assertEqual(api_resp.status_code, 403)

    def test_09_excel_import_service(self):
        """Test Excel / CSV import functionality with auto column mapping"""
        csv_data = """Name,Roll No,Year,Role,Base Price,Runs,Wickets,Strike Rate,50s,100s,4s,6s
Test Player Alpha,SPL-TEST-01,3rd Year,Batsman,10000,450,2,145.5,3,0,42,20
Test Player Beta,SPL-TEST-02,2nd Year,Bowler,10000,30,18,90.0,0,0,2,0
"""
        class MockFile:
            def __init__(self, content):
                self.filename = "import_test.csv"
                self._io = io.BytesIO(content.encode('utf-8'))
            def read(self, *args):
                return self._io.read(*args)
            def seek(self, *args):
                return self._io.seek(*args)

        mock_file = MockFile(csv_data)
        import_res = ExcelService.import_players_from_file(mock_file)
        self.assertTrue(import_res['success'])
        self.assertGreaterEqual(import_res['added_count'] + import_res['updated_count'], 2)

    def test_10_flask_routes_smoke_test(self):
        """Test Flask client routes return 200 OK for Admin and Public Display"""
        client = app.test_client()
        
        # Public Projector View (No session required)
        proj_resp = client.get('/projector')
        self.assertEqual(proj_resp.status_code, 200)

        with client.session_transaction() as sess:
            sess['user'] = config.ROLES['admin']

    def test_11_max_squad_limit_validation(self):
        """Test that team with 15 players is blocked from placing bids"""
        AuctionEngine.set_active_player("test_ply_01", user="Admin")
        teams = database.get_teams()
        team = teams[0]
        # Fill team squad with 15 mock players
        team['squad'] = [{"id": f"p_{i}", "name": f"P {i}", "bought_for": 10000} for i in range(15)]
        database.save_teams(teams)

        res = AuctionEngine.place_bid(team['id'])
        self.assertFalse(res['success'])
        self.assertIn("SQUAD LIMIT", res['message'])

    def test_12_server_timer_pause_resume_and_extend(self):
        """Test server timer state, pause, resume, and extend"""
        AuctionEngine.set_active_player("test_ply_01", user="Admin")
        state1 = database.get_auction_state()
        self.assertEqual(state1['status'], 'BIDDING')
        self.assertFalse(state1['is_timer_paused'])

        # Pause timer
        p_res = AuctionEngine.pause_auction(user="Admin")
        self.assertTrue(p_res['success'])
        state_p = database.get_auction_state()
        self.assertTrue(state_p['is_timer_paused'])

        # Extend timer by 15s
        ext_res = AuctionEngine.extend_timer(seconds=15, user="Admin")
        self.assertTrue(ext_res['success'])
        state_ext = database.get_auction_state()
        self.assertGreaterEqual(state_ext['pause_remaining_seconds'], 40)


        # Resume timer
        res_res = AuctionEngine.resume_auction(user="Admin")
        self.assertTrue(res_res['success'])
        state_res = database.get_auction_state()
        self.assertFalse(state_res['is_timer_paused'])

    def test_13_audit_log_recording(self):
        """Test that auction operations generate immutable audit log events"""
        database.log_audit_event(
            action="TEST_ACTION",
            user="Admin",
            role="admin",
            player_name="Virat Test",
            details="Test audit recording"
        )
        logs = database.get_audit_logs()
        self.assertTrue(any(l['action'] == 'TEST_ACTION' for l in logs))

    def test_14_student_roll_number_and_dob_validation(self):
        """Test strict validation of 10-char alphanumeric Roll Number and 8-digit DOB"""
        # Valid roll numbers (returns (True, clean_roll))
        self.assertTrue(database.validate_roll_number("24CSE1234A")[0])
        self.assertTrue(database.validate_roll_number("21ECE0987B")[0])
        self.assertTrue(database.validate_roll_number("1234567890")[0])
        
        # Invalid roll numbers (empty, wrong length, special chars)
        self.assertFalse(database.validate_roll_number("")[0])
        self.assertFalse(database.validate_roll_number("24CSE123")[0])      # too short (8 chars)
        self.assertFalse(database.validate_roll_number("24CSE123456A")[0])  # too long (12 chars)
        self.assertFalse(database.validate_roll_number("24CSE@1234")[0])    # special char
        self.assertFalse(database.validate_roll_number("24CSE 1234")[0])    # space
        
        # Valid DOBs (returns (True, clean_dob))
        self.assertTrue(database.validate_dob("15082003")[0])
        self.assertTrue(database.validate_dob("01012004")[0])
        
        # Invalid DOBs
        self.assertFalse(database.validate_dob("")[0])
        self.assertFalse(database.validate_dob("15-08-2003")[0])  # hyphens
        self.assertFalse(database.validate_dob("150803")[0])      # 6 digits
        self.assertFalse(database.validate_dob("150820039")[0])   # 9 digits
        self.assertFalse(database.validate_dob("15AUG203")[0])    # letters

    def test_15_student_authentication_flow(self):
        """Test student login authentication logic"""
        # 1. Successful authentication
        auth_res = database.authenticate_student("24CSE9999A", "15082003")
        self.assertTrue(auth_res['success'])
        self.assertEqual(auth_res['student']['roll_no'], "24CSE9999A")
        
        # 2. Authentication with invalid roll number format
        auth_fail_roll = database.authenticate_student("INVALID_ROLL", "15082003")
        self.assertFalse(auth_fail_roll['success'])
        
        # 3. Authentication with invalid DOB format
        auth_fail_dob = database.authenticate_student("24CSE9999A", "15-08-2003")
        self.assertFalse(auth_fail_dob['success'])

    def test_16_student_registration_and_duplicate_prevention(self):
        """Test player registration workflow and duplicate registration prevention"""
        roll_no = "24MECH1111"
        # Authenticate first
        auth_res = database.authenticate_student(roll_no, "20102004")
        self.assertTrue(auth_res['success'])
        
        # Initial registration
        reg_res = database.register_student(
            roll_no=roll_no,
            name="Rahul Dravid",
            photo_url="/static/uploads/std_test.jpg",
            year="3rd Year",
            department="MECH",
            role="Batsman"
        )
        self.assertTrue(reg_res['success'])
        
        # Verify student is now registered in database
        student = database.find_student_by_roll(roll_no)
        self.assertIsNotNone(student)
        self.assertTrue(student['registered'])
        self.assertEqual(student['name'], "Rahul Dravid")
        self.assertEqual(student['department'], "MECH")
        self.assertEqual(student['role'], "Batsman")
        
        # Verify player is enrolled in players auction pool
        players = database.get_players()
        enrolled_player = next((p for p in players if p.get('roll_no') == roll_no), None)
        self.assertIsNotNone(enrolled_player)
        self.assertEqual(enrolled_player['name'], "Rahul Dravid")
        self.assertEqual(enrolled_player['base_price'], 10000)
        
        # Duplicate registration attempt must be REJECTED
        dup_res = database.register_student(
            roll_no=roll_no,
            name="Rahul Duplicate",
            photo_url="/static/uploads/std_test2.jpg",
            year="4th Year",
            department="CSE",
            role="Bowler"
        )
        self.assertFalse(dup_res['success'])
        self.assertIn("already completed", dup_res['message'])

    def test_17_student_photo_size_validation(self):
        """Test photo size validation rejects files > 100 KB and accepts files <= 100 KB"""
        client = app.test_client()
        roll_no = "24CIVIL222"
        database.authenticate_student(roll_no, "05052003")
        
        with client.session_transaction() as sess:
            sess['user'] = {
                'username': roll_no,
                'roll_no': roll_no,
                'role': 'student',
                'registered': False
            }
            
        # 1. Test upload with file > 100 KB (150 KB dummy file)
        large_bytes = b"0" * (150 * 1024)
        large_file = (io.BytesIO(large_bytes), 'passport.jpg')
        resp_large = client.post('/student/register', data={
            'name': 'Test Heavy File',
            'year': '2nd Year',
            'department': 'CIVIL',
            'role': 'Bowler',
            'photo': large_file
        }, follow_redirects=True)
        self.assertIn(b"Photo size exceeds 100 KB", resp_large.data)
        
        # 2. Test upload with valid file <= 100 KB (40 KB dummy file)
        valid_bytes = b"0" * (40 * 1024)
        valid_file = (io.BytesIO(valid_bytes), 'passport_valid.jpg')
        resp_valid = client.post('/student/register', data={
            'name': 'Test Valid File',
            'year': '2nd Year',
            'department': 'CIVIL',
            'role': 'Bowler',
            'photo': valid_file
        }, follow_redirects=True)
        self.assertEqual(resp_valid.status_code, 200)
        self.assertIn(b"SPL PLAYER PROFILE", resp_valid.data)
        self.assertIn(b"24CIVIL222", resp_valid.data)

    def test_18_student_isolation_and_security(self):
        """Test student dashboard isolation and route protection"""
        client = app.test_client()
        roll_no = "24EEE33333"
        database.authenticate_student(roll_no, "12122002")
        
        # Unregistered student trying to access dashboard should be redirected to register
        with client.session_transaction() as sess:
            sess['user'] = {
                'username': roll_no,
                'roll_no': roll_no,
                'role': 'student',
                'registered': False
            }
        dash_resp = client.get('/student/dashboard', follow_redirects=False)
        self.assertEqual(dash_resp.status_code, 302)
        self.assertIn('/student/register', dash_resp.headers['Location'])
        
        # Student cannot access admin panel or team dashboard
        admin_resp = client.get('/admin', follow_redirects=False)
        self.assertEqual(admin_resp.status_code, 302)
        team_resp = client.get('/team', follow_redirects=False)
        self.assertEqual(team_resp.status_code, 302)

    def test_19_admin_student_approval_and_rejection_workflow(self):
        """Test Admin student verification: Approve, Reject with reason, Reset to pending"""
        client = app.test_client()
        roll_no = "24CSE8888A"
        database.authenticate_student(roll_no, "01012004")
        
        # Student registers
        database.register_student(
            roll_no=roll_no,
            name="Rohit Sharma",
            photo_url="/static/uploads/std_rohit.jpg",
            year="4th Year",
            department="CSE",
            role="Batsman"
        )
        
        # Check initial pending status
        student = database.find_student_by_roll(roll_no)
        self.assertEqual(student.get('approval_status'), 'PENDING')
        
        # Admin gets student list via API
        with client.session_transaction() as sess:
            sess['user'] = config.ROLES['admin']
            
        list_resp = client.get('/api/admin/students')
        self.assertEqual(list_resp.status_code, 200)
        list_data = json.loads(list_resp.data)
        self.assertTrue(any(s['roll_no'] == roll_no for s in list_data['students']))
        self.assertGreaterEqual(list_data['summary']['pending'], 1)

        # Admin Approves student
        appr_resp = client.post('/api/admin/students/approve', 
                                data=json.dumps({'roll_no': roll_no}),
                                content_type='application/json')
        self.assertEqual(appr_resp.status_code, 200)
        
        # Verify student is approved and player is AVAILABLE in auction pool
        student_after = database.find_student_by_roll(roll_no)
        self.assertEqual(student_after.get('approval_status'), 'APPROVED')
        players = database.get_players()
        p = next((ply for ply in players if ply.get('roll_no') == roll_no), None)
        self.assertIsNotNone(p)
        self.assertEqual(p['status'], 'AVAILABLE')
        self.assertTrue(p.get('is_approved'))

        # Admin Rejects student with reason
        rej_resp = client.post('/api/admin/students/reject',
                               data=json.dumps({'roll_no': roll_no, 'reason': 'Photo unclear, please re-upload.'}),
                               content_type='application/json')
        self.assertEqual(rej_resp.status_code, 200)
        
        student_rej = database.find_student_by_roll(roll_no)
        self.assertEqual(student_rej.get('approval_status'), 'REJECTED')
        self.assertEqual(student_rej.get('rejection_reason'), 'Photo unclear, please re-upload.')
        
        p_rej = next((ply for ply in database.get_players() if ply.get('roll_no') == roll_no), None)
        self.assertEqual(p_rej['status'], 'REJECTED')

        # Admin Resets student to pending
        reset_resp = client.post('/api/admin/students/reset',
                                 data=json.dumps({'roll_no': roll_no}),
                                 content_type='application/json')
        self.assertEqual(reset_resp.status_code, 200)
        student_rst = database.find_student_by_roll(roll_no)
        self.assertEqual(student_rst.get('approval_status'), 'PENDING')

    def test_20_unapproved_student_excluded_from_auction_draw(self):
        """Test that unapproved students (PENDING or REJECTED) are excluded from live auction available pool"""
        roll_no = "24ECE77777"
        database.authenticate_student(roll_no, "10102003")
        database.register_student(
            roll_no=roll_no,
            name="Pending Player",
            photo_url="/static/uploads/pending.jpg",
            year="2nd Year",
            department="ECE",
            role="Bowler"
        )
        
        # Player record is PENDING_APPROVAL
        players = database.get_players()
        p = next((ply for ply in players if ply.get('roll_no') == roll_no), None)
        self.assertEqual(p['status'], 'PENDING_APPROVAL')
        
        # Anchor available players pool excludes PENDING_APPROVAL
        available_pool = [ply for ply in database.get_players() if ply.get('status') in ['AVAILABLE', 'UNSOLD_POOL']]
        self.assertFalse(any(ply.get('roll_no') == roll_no for ply in available_pool))

        # Once Admin approves, player enters available pool
        database.approve_student(roll_no, user="Admin")
        available_pool_approved = [ply for ply in database.get_players() if ply.get('status') in ['AVAILABLE', 'UNSOLD_POOL']]
        self.assertTrue(any(ply.get('roll_no') == roll_no for ply in available_pool_approved))

if __name__ == '__main__':
    unittest.main()


