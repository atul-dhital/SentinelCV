from __future__ import annotations

from email.message import EmailMessage
import os
import smtplib
from typing import Dict, Tuple


def _env_flag(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def get_password_reset_email_config() -> Dict[str, str | bool | list[str]]:
    required = [
        "SMTP_HOST",
        "SMTP_PORT",
        "PASSWORD_RESET_FROM_EMAIL",
    ]
    missing = [key for key in required if not (os.getenv(key) or "").strip()]
    smtp_user = (os.getenv("SMTP_USER") or "").strip()
    smtp_password = (os.getenv("SMTP_PASSWORD") or "").strip()
    if bool(smtp_user) != bool(smtp_password):
        if not smtp_user:
            missing.append("SMTP_USER")
        if not smtp_password:
            missing.append("SMTP_PASSWORD")
    return {
        "configured": len(missing) == 0,
        "missing": missing,
        "use_tls": _env_flag("SMTP_USE_TLS", True),
        "use_ssl": _env_flag("SMTP_USE_SSL", False),
        "auth_enabled": bool(smtp_user and smtp_password),
    }


def _build_reset_message(to_email: str, token: str) -> EmailMessage:
    from_email = (os.getenv("PASSWORD_RESET_FROM_EMAIL") or "").strip() or "no-reply@sentinelcv.local"
    reset_base_url = (os.getenv("PASSWORD_RESET_URL") or "").strip() or "http://localhost:3001/login"
    reset_link = f"{reset_base_url}?mode=reset&token={token}"

    message = EmailMessage()
    message["Subject"] = "SentinelCV password reset"
    message["From"] = from_email
    message["To"] = to_email
    message.set_content(
        "\n".join(
            [
                "A password reset request was received for your SentinelCV account.",
                "",
                f"Reset link: {reset_link}",
                f"Reset token: {token}",
                "",
                "If you did not request this reset, you can ignore this email.",
            ]
        )
    )
    return message


def send_password_reset_email(to_email: str, token: str) -> Tuple[bool, str]:
    config = get_password_reset_email_config()
    if not config["configured"]:
        return False, f"missing SMTP configuration: {', '.join(config['missing'])}"

    smtp_host = str(os.getenv("SMTP_HOST") or "").strip()
    smtp_port_raw = str(os.getenv("SMTP_PORT") or "").strip()
    smtp_user = str(os.getenv("SMTP_USER") or "").strip()
    smtp_password = str(os.getenv("SMTP_PASSWORD") or "").strip()

    try:
        smtp_port = int(smtp_port_raw)
    except ValueError:
        return False, "SMTP_PORT must be a valid integer"

    message = _build_reset_message(to_email, token)
    use_ssl = bool(config["use_ssl"])
    use_tls = bool(config["use_tls"])

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20) as smtp:
                if smtp_user and smtp_password:
                    smtp.login(smtp_user, smtp_password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as smtp:
                smtp.ehlo()
                if use_tls:
                    smtp.starttls()
                    smtp.ehlo()
                if smtp_user and smtp_password:
                    smtp.login(smtp_user, smtp_password)
                smtp.send_message(message)
    except Exception as exc:
        return False, str(exc)

    return True, "sent"
