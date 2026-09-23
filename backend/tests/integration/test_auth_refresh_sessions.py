from models.models import AuditLog, RefreshTokenSession


API = "/api/v1/auth"


def _login(client):
    response = client.post(
        f"{API}/login",
        json={"email": "admin@test.com", "password": "Admin123!"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _clear_refresh_sessions(db, user_id):
    db.query(RefreshTokenSession).filter(
        RefreshTokenSession.user_id == user_id
    ).delete()
    db.commit()


def test_refresh_rotates_session_and_revokes_previous_token(client, db, admin_user):
    _clear_refresh_sessions(db, admin_user.id)
    tokens = _login(client)
    original_refresh = tokens["refresh_token"]

    first_session = db.query(RefreshTokenSession).filter(
        RefreshTokenSession.user_id == admin_user.id
    ).one()
    assert first_session.revoked_at is None

    refresh_response = client.post(
        f"{API}/refresh",
        json={"refresh_token": original_refresh},
    )
    assert refresh_response.status_code == 200, refresh_response.text
    refreshed = refresh_response.json()
    assert refreshed["refresh_token"] != original_refresh

    sessions = (
        db.query(RefreshTokenSession)
        .filter(RefreshTokenSession.user_id == admin_user.id)
        .order_by(RefreshTokenSession.created_at.asc())
        .all()
    )
    assert len(sessions) == 2

    db.refresh(first_session)
    assert first_session.revoked_at is not None
    assert first_session.revoke_reason == "rotated"
    assert first_session.replaced_by_token_hash is not None

    second_session = sessions[-1]
    assert second_session.revoked_at is None

    replay_response = client.post(
        f"{API}/refresh",
        json={"refresh_token": original_refresh},
    )
    assert replay_response.status_code == 401, replay_response.text
    assert replay_response.json()["detail"] == "Refresh token has been revoked"

    audit_actions = [
        row.action
        for row in db.query(AuditLog)
        .filter(AuditLog.user_id == admin_user.id)
        .order_by(AuditLog.timestamp.asc())
        .all()
    ]
    assert "login" in audit_actions
    assert "token_refresh" in audit_actions


def test_logout_revokes_only_supplied_refresh_session(client, db, admin_user):
    _clear_refresh_sessions(db, admin_user.id)
    first_login = _login(client)
    second_login = _login(client)

    active_sessions = db.query(RefreshTokenSession).filter(
        RefreshTokenSession.user_id == admin_user.id,
        RefreshTokenSession.revoked_at.is_(None),
    ).all()
    assert len(active_sessions) == 2

    logout_response = client.post(
        f"{API}/logout",
        headers={"Authorization": f"Bearer {first_login['access_token']}"},
        json={"refresh_token": first_login["refresh_token"]},
    )
    assert logout_response.status_code == 200, logout_response.text
    assert logout_response.json()["revoked_sessions"] == 1
    db.expire_all()

    sessions = (
        db.query(RefreshTokenSession)
        .filter(RefreshTokenSession.user_id == admin_user.id)
        .order_by(RefreshTokenSession.created_at.asc())
        .all()
    )
    revoked = [session for session in sessions if session.revoked_at is not None]
    active = [session for session in sessions if session.revoked_at is None]
    assert len(revoked) == 1
    assert revoked[0].revoke_reason == "logout"
    assert len(active) == 1

    second_refresh = client.post(
        f"{API}/refresh",
        json={"refresh_token": second_login["refresh_token"]},
    )
    assert second_refresh.status_code == 200, second_refresh.text


def test_logout_without_refresh_token_revokes_all_active_sessions(client, db, admin_user):
    _clear_refresh_sessions(db, admin_user.id)
    login_tokens = _login(client)
    refreshed = client.post(
        f"{API}/refresh",
        json={"refresh_token": login_tokens["refresh_token"]},
    )
    assert refreshed.status_code == 200, refreshed.text

    logout_response = client.post(
        f"{API}/logout",
        headers={"Authorization": f"Bearer {refreshed.json()['access_token']}"},
    )
    assert logout_response.status_code == 200, logout_response.text
    assert logout_response.json()["revoked_sessions"] == 1
    db.expire_all()

    remaining_active = db.query(RefreshTokenSession).filter(
        RefreshTokenSession.user_id == admin_user.id,
        RefreshTokenSession.revoked_at.is_(None),
    ).count()
    assert remaining_active == 0
