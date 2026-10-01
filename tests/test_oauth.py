import pytest
from app import create_app
from app.services import oauth_service

@pytest.fixture
def app():
    app = create_app('test')
    return app

@pytest.fixture
def client(app):
    return app.test_client()

def test_google_login_redirect_local(client):
    res = client.get('/google/login')
    assert res.status_code == 302
    loc = res.headers.get('Location')
    assert 'accounts.google.com/o/oauth2/v2/auth' in loc
    assert 'client_id=' in loc
    assert 'redirect_uri=' in loc

def test_google_login_redirect_pythonanywhere(client):
    res = client.get('/google/login', headers={'Host': 'splsankalp.pythonanywhere.com'})
    assert res.status_code == 302
    loc = res.headers.get('Location')
    assert 'accounts.google.com/o/oauth2/v2/auth' in loc
    assert 'splsankalp.pythonanywhere.com' in loc

def test_google_login_without_authlib(client, monkeypatch):
    monkeypatch.setattr(oauth_service, 'oauth', None)
    res = client.get('/google/login', headers={'Host': 'splsankalp.pythonanywhere.com'})
    assert res.status_code == 302
    loc = res.headers.get('Location')
    assert 'accounts.google.com/o/oauth2/v2/auth' in loc

def test_google_callback_access_denied(client):
    res = client.get('/auth/google/callback?error=access_denied')
    assert res.status_code == 200
    assert b'Sign-In Cancelled' in res.data or b'cancelled' in res.data.lower()

def test_google_callback_mock_email(client):
    res = client.get('/auth/google/callback?mock_email=laxminivasmorishetty143@gmail.com')
    assert res.status_code == 302
    assert '/admin/dashboard' in res.headers.get('Location')
