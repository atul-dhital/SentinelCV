import os

from services import password_reset_email_service


def _clear_smtp_env(monkeypatch):
    for key in (
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USER",
        "SMTP_PASSWORD",
        "PASSWORD_RESET_FROM_EMAIL",
        "SMTP_USE_TLS",
        "SMTP_USE_SSL",
    ):
        monkeypatch.delenv(key, raising=False)


def test_password_reset_email_config_accepts_no_auth_smtp(monkeypatch):
    _clear_smtp_env(monkeypatch)
    monkeypatch.setenv("SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("SMTP_PORT", "1025")
    monkeypatch.setenv("PASSWORD_RESET_FROM_EMAIL", "noreply@example.com")

    config = password_reset_email_service.get_password_reset_email_config()

    assert config["configured"] is True
    assert config["missing"] == []
    assert config["auth_enabled"] is False


def test_password_reset_email_config_requires_complete_auth_pair(monkeypatch):
    _clear_smtp_env(monkeypatch)
    monkeypatch.setenv("SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("SMTP_PORT", "1025")
    monkeypatch.setenv("PASSWORD_RESET_FROM_EMAIL", "noreply@example.com")
    monkeypatch.setenv("SMTP_USER", "mailer")

    config = password_reset_email_service.get_password_reset_email_config()

    assert config["configured"] is False
    assert "SMTP_PASSWORD" in config["missing"]
