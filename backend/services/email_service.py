"""
Email Notification Service (ALERT-003)

Sends email notifications for alerts, visitor detections, daily summaries,
VIP alerts, and system health notifications.

Configurable via environment variables. Gracefully falls back to logging
when SMTP is not configured.
"""

import os
import logging
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, Dict, List
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "noreply@sentinelcv.local")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() in ("true", "1", "yes")
MAX_EMAILS_PER_HOUR = int(os.getenv("MAX_EMAILS_PER_HOUR", "100"))


class EmailService:
    """Email notification service with rate limiting and HTML templates."""

    def __init__(self):
        self._configured = bool(SMTP_HOST and SMTP_USER)
        self._sent_count = 0
        self._hour_start = time.time()

        if self._configured:
            logger.info(f"Email service configured: {SMTP_HOST}:{SMTP_PORT}")
        else:
            logger.info("Email service not configured (SMTP_HOST/SMTP_USER not set). "
                        "Emails will be logged instead of sent.")

    def _check_rate_limit(self) -> bool:
        """Check if we can send more emails this hour."""
        now = time.time()
        if now - self._hour_start > 3600:
            self._sent_count = 0
            self._hour_start = now
        return self._sent_count < MAX_EMAILS_PER_HOUR

    def _send_email(self, to: str, subject: str, html_body: str, text_body: str = "") -> bool:
        """Send an email via SMTP."""
        if not self._check_rate_limit():
            logger.warning(f"Email rate limit reached ({MAX_EMAILS_PER_HOUR}/hour)")
            return False

        if not self._configured:
            logger.info(f"[EMAIL LOG] To: {to} | Subject: {subject} | Body: {text_body[:200]}")
            self._sent_count += 1
            return True

        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = SMTP_FROM
            msg["To"] = to
            msg["Subject"] = subject

            if text_body:
                msg.attach(MIMEText(text_body, "plain"))
            msg.attach(MIMEText(html_body, "html"))

            if SMTP_USE_TLS:
                server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
                server.starttls()
            else:
                server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)

            if SMTP_USER and SMTP_PASSWORD:
                server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, [to], msg.as_string())
            server.quit()

            self._sent_count += 1
            logger.info(f"Email sent to {to}: {subject}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email to {to}: {e}")
            return False

    def _base_template(self, title: str, content: str) -> str:
        """Wrap content in base HTML email template."""
        return f"""
        <!DOCTYPE html>
        <html>
        <head><meta charset="utf-8"></head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                     max-width: 600px; margin: 0 auto; padding: 20px; color: #333;">
            <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        padding: 20px; border-radius: 8px 8px 0 0; text-align: center;">
                <h1 style="color: white; margin: 0; font-size: 24px;">SentinelCV</h1>
                <p style="color: rgba(255,255,255,0.8); margin: 5px 0 0 0; font-size: 14px;">{title}</p>
            </div>
            <div style="background: #fff; padding: 24px; border: 1px solid #e0e0e0; border-top: none;
                        border-radius: 0 0 8px 8px;">
                {content}
            </div>
            <p style="text-align: center; color: #999; font-size: 12px; margin-top: 16px;">
                Sent by SentinelCV Visitor Tracking System
            </p>
        </body>
        </html>
        """

    # ── Alert Emails ────────────────────────────────────────────────────

    def send_alert_email(self, to: str, subject: str, alert_data: dict) -> bool:
        """Send a generic alert notification."""
        content = f"""
        <h2 style="color: #e74c3c;">Alert Notification</h2>
        <table style="width: 100%; border-collapse: collapse;">
            <tr><td style="padding: 8px; font-weight: bold;">Type:</td>
                <td style="padding: 8px;">{alert_data.get('type', 'N/A')}</td></tr>
            <tr><td style="padding: 8px; font-weight: bold;">Severity:</td>
                <td style="padding: 8px;">{alert_data.get('severity', 'medium')}</td></tr>
            <tr><td style="padding: 8px; font-weight: bold;">Message:</td>
                <td style="padding: 8px;">{alert_data.get('message', '')}</td></tr>
            <tr><td style="padding: 8px; font-weight: bold;">Time:</td>
                <td style="padding: 8px;">{alert_data.get('timestamp', datetime.now(timezone.utc).isoformat())}</td></tr>
        </table>
        """
        html = self._base_template("Alert Notification", content)
        text = f"Alert: {alert_data.get('type', '')} - {alert_data.get('message', '')}"
        return self._send_email(to, subject, html, text)

    def send_visitor_detection_email(
        self, to: str, visitor_name: str, camera: str, timestamp: str, confidence: float
    ) -> bool:
        """Send visitor detection notification."""
        content = f"""
        <h2 style="color: #2196F3;">Visitor Detected</h2>
        <div style="background: #f8f9fa; padding: 16px; border-radius: 8px; margin: 16px 0;">
            <p style="margin: 4px 0;"><strong>Visitor:</strong> {visitor_name}</p>
            <p style="margin: 4px 0;"><strong>Camera:</strong> {camera}</p>
            <p style="margin: 4px 0;"><strong>Confidence:</strong> {confidence:.1%}</p>
            <p style="margin: 4px 0;"><strong>Time:</strong> {timestamp}</p>
        </div>
        """
        html = self._base_template("Visitor Detection", content)
        text = f"Visitor '{visitor_name}' detected at {camera} (confidence: {confidence:.1%})"
        return self._send_email(to, f"[SentinelCV] Visitor Detected: {visitor_name}", html, text)

    def send_vip_alert_email(
        self, to: str, visitor_name: str, camera: str, timestamp: str
    ) -> bool:
        """Send VIP visitor alert (high priority)."""
        content = f"""
        <h2 style="color: #ff9800;">⭐ VIP Visitor Alert</h2>
        <div style="background: #fff3e0; padding: 16px; border-radius: 8px; border-left: 4px solid #ff9800; margin: 16px 0;">
            <p style="margin: 4px 0; font-size: 18px;"><strong>{visitor_name}</strong></p>
            <p style="margin: 4px 0;">Detected at <strong>{camera}</strong></p>
            <p style="margin: 4px 0;">Time: {timestamp}</p>
        </div>
        <p>This visitor has been flagged as VIP. Please ensure appropriate welcome protocols.</p>
        """
        html = self._base_template("VIP Visitor Alert", content)
        text = f"VIP Alert: {visitor_name} detected at {camera} at {timestamp}"
        return self._send_email(to, f"[SentinelCV] VIP Alert: {visitor_name}", html, text)

    def send_daily_summary_email(self, to: str, org_name: str, stats: dict) -> bool:
        """Send daily detection summary."""
        content = f"""
        <h2 style="color: #4CAF50;">Daily Summary - {org_name}</h2>
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 16px 0;">
            <div style="background: #e8f5e9; padding: 16px; border-radius: 8px; text-align: center;">
                <p style="font-size: 28px; font-weight: bold; margin: 0; color: #4CAF50;">
                    {stats.get('total_detections', 0)}</p>
                <p style="margin: 4px 0; color: #666;">Total Detections</p>
            </div>
            <div style="background: #e3f2fd; padding: 16px; border-radius: 8px; text-align: center;">
                <p style="font-size: 28px; font-weight: bold; margin: 0; color: #2196F3;">
                    {stats.get('identified', 0)}</p>
                <p style="margin: 4px 0; color: #666;">Identified</p>
            </div>
            <div style="background: #fff3e0; padding: 16px; border-radius: 8px; text-align: center;">
                <p style="font-size: 28px; font-weight: bold; margin: 0; color: #ff9800;">
                    {stats.get('unidentified', 0)}</p>
                <p style="margin: 4px 0; color: #666;">Unidentified</p>
            </div>
            <div style="background: #fce4ec; padding: 16px; border-radius: 8px; text-align: center;">
                <p style="font-size: 28px; font-weight: bold; margin: 0; color: #e74c3c;">
                    {stats.get('spoofing_attempts', 0)}</p>
                <p style="margin: 4px 0; color: #666;">Spoof Attempts</p>
            </div>
        </div>
        <p><strong>Active Cameras:</strong> {stats.get('active_cameras', 0)}</p>
        <p><strong>Avg Confidence:</strong> {stats.get('avg_confidence', 0):.1%}</p>
        """
        html = self._base_template("Daily Summary", content)
        text = f"Daily Summary: {stats.get('total_detections', 0)} detections, {stats.get('identified', 0)} identified"
        return self._send_email(to, f"[SentinelCV] Daily Summary - {org_name}", html, text)

    def send_system_alert_email(self, to: str, alert_type: str, details: dict) -> bool:
        """Send system health alert."""
        severity_colors = {"critical": "#e74c3c", "high": "#ff9800", "medium": "#ffc107", "low": "#2196F3"}
        severity = details.get("severity", "medium")
        color = severity_colors.get(severity, "#2196F3")

        content = f"""
        <h2 style="color: {color};">System Alert: {alert_type}</h2>
        <div style="background: #f8f9fa; padding: 16px; border-radius: 8px;
                    border-left: 4px solid {color}; margin: 16px 0;">
            <p style="margin: 4px 0;"><strong>Severity:</strong> {severity.upper()}</p>
            <p style="margin: 4px 0;"><strong>Component:</strong> {details.get('component', 'Unknown')}</p>
            <p style="margin: 4px 0;"><strong>Details:</strong> {details.get('message', '')}</p>
            <p style="margin: 4px 0;"><strong>Time:</strong> {datetime.now(timezone.utc).isoformat()}</p>
        </div>
        """
        html = self._base_template(f"System Alert - {severity.upper()}", content)
        text = f"System Alert ({severity}): {alert_type} - {details.get('message', '')}"
        return self._send_email(to, f"[SentinelCV] System Alert: {alert_type}", html, text)

    def get_status(self) -> dict:
        """Get email service status."""
        return {
            "configured": self._configured,
            "smtp_host": SMTP_HOST if self._configured else None,
            "emails_sent_this_hour": self._sent_count,
            "rate_limit": MAX_EMAILS_PER_HOUR,
        }


# Singleton
email_service = EmailService()
