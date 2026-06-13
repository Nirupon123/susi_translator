import pytest

def _seed_user(ts, email, password, is_admin=False):
    with ts.app.app_context():
        from auth.models import Organizer
        pw_hash = ts.bcrypt.generate_password_hash(password).decode("utf-8")
        user = Organizer(email=email, password_hash=pw_hash, is_admin=is_admin)
        ts.db.session.add(user)
        ts.db.session.commit()

def test_signup_success(unauth_client, ts):
    resp = unauth_client.post("/auth/api/signup", json={
        "email": "newuser@test.com",
        "password": "password123",
        "name": "New User"
    })
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["status"] == "success"
    assert "access_token_cookie" in resp.headers.get("Set-Cookie", "")

def test_signup_rejects_missing_fields(unauth_client):
    resp = unauth_client.post("/auth/api/signup", json={"email": "missingpass@test.com"})
    assert resp.status_code == 400

def test_signup_rejects_short_password(unauth_client):
    resp = unauth_client.post("/auth/api/signup", json={"email": "short@test.com", "password": "short"})
    assert resp.status_code == 400

def test_signup_rejects_duplicate_email(unauth_client, ts):
    _seed_user(ts, "duplicate@test.com", "password123")
    resp = unauth_client.post("/auth/api/signup", json={
        "email": "duplicate@test.com",
        "password": "password123"
    })
    assert resp.status_code == 409

def test_login_success(unauth_client, ts):
    _seed_user(ts, "login@test.com", "password123")
    resp = unauth_client.post("/auth/api/login", json={
        "email": "login@test.com",
        "password": "password123"
    })
    assert resp.status_code == 200
    assert "access_token_cookie" in resp.headers.get("Set-Cookie", "")

def test_login_rejects_bad_password(unauth_client, ts):
    _seed_user(ts, "badpass@test.com", "password123")
    resp = unauth_client.post("/auth/api/login", json={
        "email": "badpass@test.com",
        "password": "wrongpassword"
    })
    assert resp.status_code == 401

def test_logout_clears_cookie(unauth_client, ts):
    _seed_user(ts, "logout@test.com", "password123")
    unauth_client.post("/auth/api/login", json={"email": "logout@test.com", "password": "password123"})
    resp = unauth_client.post("/auth/api/logout")
    assert resp.status_code == 200
    assert "access_token_cookie=;" in resp.headers.get("Set-Cookie", "")

def test_protected_api_blocks_unauth(unauth_client):
    resp = unauth_client.post("/api/v1/translate/configure", json={"tenant_id": "x"})
    assert resp.status_code == 401

def test_admin_panel_blocks_unauth(unauth_client):
    resp = unauth_client.get("/admin/")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers.get("Location", "")

def test_admin_panel_allows_admin(client):
    # client fixture is pre-authenticated as admin
    resp = client.get("/admin/")
    assert resp.status_code == 200

def test_admin_panel_blocks_non_admin(unauth_client, ts):
    _seed_user(ts, "nonadmin@test.com", "password123", is_admin=False)
    unauth_client.post("/auth/api/login", json={"email": "nonadmin@test.com", "password": "password123"})
    resp = unauth_client.get("/admin/")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers.get("Location", "")
