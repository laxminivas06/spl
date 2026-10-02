import os
import io
import pytest
from PIL import Image
from werkzeug.datastructures import FileStorage
from app import create_app
from app.extensions import db
from app.models import User, Player, Franchise, PlayerStatus, PlayerRole, PlayerCategory
from app.services.backup_service import list_backups, list_deleted_records
from app.utils.image_utils import validate_and_save_image, MAX_IMAGE_BYTES

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
        # Clean users
        for u in User.query.all():
            db.session.delete(u)
        db.session.commit()

        admin = User(
            username='admin1',
            email='admin1@test.com',
            role='ADMIN',
            is_active=True
        )
        admin.set_password('password123')
        db.session.add(admin)

        admin2 = User(
            username='admin2',
            email='admin2@test.com',
            role='ADMIN',
            is_active=True
        )
        admin2.set_password('password123')
        db.session.add(admin2)

        user_franchise = User(
            username='fuser',
            email='fuser@test.com',
            role='FRANCHISE',
            is_active=True
        )
        user_franchise.set_password('password123')
        db.session.add(user_franchise)

        db.session.commit()
        return admin

def login_admin(client):
    return client.get('/auth/google/callback?mock_email=admin1@test.com')

def test_delete_user_and_backup(app, client, admin_user):
    with app.app_context():
        login_admin(client)
        target_user = User.query.filter_by(username='fuser').first()
        target_id = target_user.id

        backups_before = len(list_backups())
        deleted_records_before = len(list_deleted_records())

        res = client.post(f'/admin/users/{target_id}/delete', follow_redirects=True)
        assert res.status_code == 200

        # Verify user is deleted
        deleted_user = db.session.get(User, target_id)
        assert deleted_user is None

        # Verify backup was created
        backups_after = len(list_backups())
        assert backups_after > backups_before

        # Verify record in deleted archive
        deleted_records = list_deleted_records()
        assert len(deleted_records) > deleted_records_before
        assert deleted_records[0]['entity_type'] == 'User'
        assert deleted_records[0]['data']['username'] == 'fuser'

def test_cannot_delete_self(app, client, admin_user):
    with app.app_context():
        login_admin(client)
        admin = User.query.filter_by(username='admin1').first()

        res = client.post(f'/admin/users/{admin.id}/delete', follow_redirects=True)
        assert res.status_code == 200
        assert b'You cannot delete your own' in res.data

        # Verify admin still exists
        assert db.session.get(User, admin.id) is not None

def test_delete_player_and_backup(app, client, admin_user):
    with app.app_context():
        login_admin(client)

        franchise = Franchise(
            name='Alpha Team',
            short_name='AT',
            starting_purse=550000.0,
            remaining_purse=500000.0
        )
        db.session.add(franchise)
        db.session.commit()

        player = Player(
            roll_number='TEST000001',
            name='Captain Player',
            role=PlayerRole.BATSMAN,
            category=PlayerCategory.ELITE,
            base_price=10000.0,
            status=PlayerStatus.RETAINED,
            sold_to=franchise.id,
            sold_price=50000.0
        )
        db.session.add(player)
        db.session.commit()

        franchise.captain_id = player.id
        franchise.captain_name = player.name
        db.session.commit()

        backups_before = len(list_backups())

        # Delete player
        res = client.post(f'/admin/players/{player.id}/delete', follow_redirects=True)
        assert res.status_code == 200

        # Verify player is deleted
        assert db.session.get(Player, player.id) is None

        # Verify franchise captain is cleared
        updated_f = db.session.get(Franchise, franchise.id)
        assert updated_f.captain_id is None

        # Verify backup was saved
        backups_after = len(list_backups())
        assert backups_after > backups_before

        deleted_records = list_deleted_records()
        assert deleted_records[0]['entity_type'] == 'Player'
        assert deleted_records[0]['data']['name'] == 'Captain Player'

def test_delete_franchise_and_backup(app, client, admin_user):
    with app.app_context():
        login_admin(client)

        franchise = Franchise(
            name='Beta Team',
            short_name='BT',
            starting_purse=550000.0,
            remaining_purse=500000.0
        )
        db.session.add(franchise)
        db.session.commit()

        # Add a player sold to this franchise
        player = Player(
            roll_number='TEST000002',
            name='Squad Player',
            role=PlayerRole.BOWLER,
            category=PlayerCategory.ROOKIE,
            status=PlayerStatus.SOLD,
            sold_to=franchise.id,
            sold_price=25000.0
        )
        db.session.add(player)
        db.session.commit()

        backups_before = len(list_backups())

        res = client.post(f'/admin/franchises/{franchise.id}/delete', follow_redirects=True)
        assert res.status_code == 200

        # Verify franchise is deleted
        assert db.session.get(Franchise, franchise.id) is None

        # Verify player is released back to AVAILABLE
        updated_player = db.session.get(Player, player.id)
        assert updated_player.sold_to is None
        assert updated_player.status == PlayerStatus.AVAILABLE
        assert updated_player.sold_price is None

        # Verify backup was created
        backups_after = len(list_backups())
        assert backups_after > backups_before

        deleted_records = list_deleted_records()
        assert deleted_records[0]['entity_type'] == 'Franchise'
        assert deleted_records[0]['data']['name'] == 'Beta Team'

def test_image_validation_100kb_limit(app):
    with app.app_context():
        # 1. Test small image <= 100KB
        img_small = Image.new('RGB', (100, 100), color='green')
        buf_small = io.BytesIO()
        img_small.save(buf_small, format='JPEG')
        buf_small.seek(0)
        file_small = FileStorage(stream=buf_small, filename='test_small.jpg', content_type='image/jpeg')

        saved_name, err = validate_and_save_image(file_small, prefix='small')
        assert err is None
        assert saved_name is not None
        saved_path = os.path.join(app.config['UPLOAD_FOLDER'], saved_name)
        assert os.path.exists(saved_path)
        assert os.path.getsize(saved_path) <= MAX_IMAGE_BYTES

        # 2. Test large image > 100KB (e.g. 1500x1500 image with random noise)
        import random
        img_large = Image.new('RGB', (1600, 1600))
        # Draw some colors so it doesn't compress to 1KB
        pixels = img_large.load()
        for x in range(0, 1600, 5):
            for y in range(0, 1600, 5):
                pixels[x, y] = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
        buf_large = io.BytesIO()
        img_large.save(buf_large, format='JPEG', quality=95)
        raw_size = len(buf_large.getvalue())
        buf_large.seek(0)
        file_large = FileStorage(stream=buf_large, filename='test_large.jpg', content_type='image/jpeg')

        saved_large_name, large_err = validate_and_save_image(file_large, prefix='large')
        assert large_err is None
        assert saved_large_name is not None

        large_path = os.path.join(app.config['UPLOAD_FOLDER'], saved_large_name)
        saved_size = os.path.getsize(large_path)
        # MUST strictly be under 100KB limit (102,400 bytes)
        assert saved_size <= MAX_IMAGE_BYTES
        assert saved_size <= 100 * 1024
