"""Transactional Email Delivery Service for MIRAGE 3.0.

Dispatches official payment receipts, subscription invoices, and security alerts
via standard SMTP (Gmail SMTP, Resend, SendGrid, or AWS SES).
Fail-safe: Network errors or missing credentials log warnings without breaking payment flows.
"""

from __future__ import annotations

import smtplib
from datetime import UTC, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import structlog

from shared.config.settings import get_settings

logger = structlog.get_logger(__name__)


class EmailService:
    """Enterprise SMTP Email Delivery Service."""

    @classmethod
    def send_email(
        cls,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str | None = None,
    ) -> bool:
        """Send a MIME email via configured SMTP server with TLS encryption.

        Returns:
            True if delivered successfully, False if skipped or encountered error.
        """
        settings = get_settings()

        if not settings.smtp_user or not settings.smtp_password:
            logger.warning("SMTP email skipped: credentials not configured in settings")
            return False

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
            msg["To"] = to_email

            plain_text = text_body or f"MIRAGE 3.0 Notification: {subject}\n\nPlease view in an HTML-enabled client."
            msg.attach(MIMEText(plain_text, "plain", "utf-8"))
            msg.attach(MIMEText(html_body, "html", "utf-8"))

            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10.0) as server:
                server.starttls()
                server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(msg)

            logger.info("Transactional email dispatched successfully", recipient=to_email, subject=subject)
            return True
        except Exception as exc:
            logger.warning(
                "Transactional email dispatch failed (fail-safe bypassed)",
                recipient=to_email,
                subject=subject,
                error=str(exc),
            )
            return False

    @classmethod
    def send_invoice_receipt(
        cls,
        to_email: str,
        tenant_id: str,
        plan_name: str,
        amount_usd: float,
        invoice_id: str,
        payment_id: str,
    ) -> bool:
        """Construct and send an official branded subscription receipt."""
        now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        subject = f"[MIRAGE AI] Payment Receipt - {invoice_id} ({plan_name})"

        html_body = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      background-color: #0b0f19; color: #f1f5f9; margin: 0; padding: 24px;
    }}
    .card {{
      max-width: 600px; margin: 0 auto; background-color: #111827; border: 1px solid #1e293b;
      border-radius: 12px; padding: 32px; box-shadow: 0 10px 25px -5px rgba(0,0,0,0.5);
    }}
    .header {{ border-bottom: 1px solid #334155; padding-bottom: 20px; margin-bottom: 24px; }}
    .logo {{ font-size: 20px; font-weight: 800; color: #38bdf8; letter-spacing: -0.5px; }}
    .tagline {{ font-size: 13px; color: #94a3b8; margin-top: 4px; }}
    .title {{ font-size: 24px; font-weight: 700; color: #f8fafc; margin: 16px 0 8px 0; }}
    .badge {{
      display: inline-block; padding: 4px 10px; background-color: #065f46; color: #34d399;
      font-size: 12px; font-weight: 600; border-radius: 9999px; text-transform: uppercase;
    }}
    .table {{ width: 100%; border-collapse: collapse; margin: 24px 0; }}
    .table td {{ padding: 10px 0; border-bottom: 1px solid #1e293b; font-size: 14px; }}
    .table td.label {{ color: #94a3b8; }}
    .table td.value {{ text-align: right; color: #f8fafc; font-weight: 600; }}
    .total-row td {{
      font-size: 18px; color: #38bdf8; border-top: 2px solid #334155; border-bottom: none; padding-top: 16px;
    }}
    .footer {{
      margin-top: 32px; padding-top: 20px; border-top: 1px solid #1e293b;
      font-size: 12px; color: #64748b; text-align: center;
    }}
    .btn {{
      display: inline-block; background-color: #0284c7; color: #ffffff; text-decoration: none;
      padding: 12px 24px; border-radius: 8px; font-weight: 600; margin-top: 16px; text-align: center;
    }}
  </style>
</head>
<body>
  <div class="card">
    <div class="header">
      <div class="logo">🛡️ MIRAGE 3.0</div>
      <div class="tagline">Autonomous AI Execution Assurance Platform</div>
    </div>
    <div>
      <span class="badge">Payment Verified (PAID)</span>
      <h1 class="title">Subscription Receipt</h1>
      <p style="color: #94a3b8; font-size: 14px; margin: 0 0 20px 0;">
        Thank you for your purchase. Your AI Execution Assurance subscription is now active.
      </p>
    </div>

    <table class="table">
      <tr>
        <td class="label">Invoice Number</td>
        <td class="value"><code>{invoice_id}</code></td>
      </tr>
      <tr>
        <td class="label">Tenant ID</td>
        <td class="value"><code>{tenant_id}</code></td>
      </tr>
      <tr>
        <td class="label">Plan Tier</td>
        <td class="value">{plan_name}</td>
      </tr>
      <tr>
        <td class="label">Payment Processor</td>
        <td class="value">Stripe (USD)</td>
      </tr>
      <tr>
        <td class="label">Payment ID</td>
        <td class="value"><code>{payment_id}</code></td>
      </tr>
      <tr>
        <td class="label">Date & Time</td>
        <td class="value">{now_str}</td>
      </tr>
      <tr class="total-row">
        <td class="label" style="color: #f8fafc;">Total Paid</td>
        <td class="value">${amount_usd:,.2f} USD</td>
      </tr>
    </table>

    <div style="text-align: center;">
      <a href="http://localhost:3000/dashboard" class="btn">Open Operator Console</a>
    </div>

    <div class="footer">
      <p>This is an automated official transaction receipt issued by MIRAGE AI Execution Assurance.</p>
      <p>Questions or enterprise support? Contact <a href="mailto:{to_email}" style="color: #38bdf8;">{to_email}</a></p>
    </div>
  </div>
</body>
</html>
"""
        plain_text = f"""MIRAGE 3.0 Subscription Receipt
====================================
Invoice: {invoice_id}
Tenant: {tenant_id}
Plan: {plan_name}
Total Paid: ${amount_usd:,.2f} USD
Payment ID: {payment_id}
Date: {now_str}
Status: PAID (Verified via Stripe)

Open your dashboard to view active assurance gates and manage API keys:
http://localhost:3000/dashboard

Questions? Contact vedantwork1402@gmail.com
"""
        return cls.send_email(
            to_email=to_email,
            subject=subject,
            html_body=html_body,
            text_body=plain_text,
        )


email_service = EmailService()
