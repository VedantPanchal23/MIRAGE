"""Transactional Email Delivery Service for MIRAGE 3.0.

Dispatches official payment receipts, subscription invoices, and security alerts
via standard SMTP (Gmail SMTP, Resend, SendGrid, or AWS SES).
Features a responsive, high-contrast, professional light-theme receipt optimized for desktop and mobile.
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
        amount: float,
        invoice_id: str,
        payment_id: str,
        currency: str = "INR",
        payment_method: str = "Razorpay (UPI, Netbanking, Cards)",
    ) -> bool:
        """Construct and send an official branded subscription receipt with a clean light theme."""
        now_str = datetime.now(UTC).strftime("%d %B %Y, %H:%M:%S UTC")
        formatted_amount = f"₹{amount:,.2f} INR" if currency.upper() == "INR" else f"${amount:,.2f} USD"
        subject = f"[MIRAGE AI] Payment Receipt - {invoice_id} ({plan_name})"

        html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Payment Receipt - {invoice_id}</title>
  <style>
    body {{
      margin: 0;
      padding: 0;
      background-color: #f1f5f9;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      color: #0f172a;
      -webkit-font-smoothing: antialiased;
    }}
    table {{ border-collapse: collapse; }}
    .wrapper {{
      width: 100%;
      background-color: #f1f5f9;
      padding: 32px 12px;
    }}
    .card {{
      max-width: 580px;
      margin: 0 auto;
      background-color: #ffffff;
      border: 1px solid #e2e8f0;
      border-radius: 14px;
      padding: 36px 32px;
      box-shadow: 0 4px 12px rgba(15, 23, 42, 0.05);
    }}
    .brand-header {{
      display: flex;
      align-items: center;
      border-bottom: 1px solid #e2e8f0;
      padding-bottom: 20px;
      margin-bottom: 24px;
    }}
    .brand-title {{
      font-size: 20px;
      font-weight: 800;
      color: #0284c7;
      letter-spacing: -0.5px;
      margin: 0;
    }}
    .brand-sub {{
      font-size: 13px;
      color: #64748b;
      margin: 3px 0 0 0;
    }}
    .status-badge {{
      display: inline-block;
      background-color: #ecfdf5;
      color: #059669;
      border: 1px solid #a7f3d0;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.5px;
      padding: 4px 12px;
      border-radius: 9999px;
      text-transform: uppercase;
      margin-bottom: 12px;
    }}
    .receipt-title {{
      font-size: 24px;
      font-weight: 800;
      color: #0f172a;
      margin: 0 0 6px 0;
      letter-spacing: -0.5px;
    }}
    .receipt-desc {{
      font-size: 14px;
      color: #475569;
      margin: 0 0 24px 0;
      line-height: 1.5;
    }}
    .info-table {{
      width: 100%;
      margin: 20px 0;
    }}
    .info-table td {{
      padding: 11px 0;
      border-bottom: 1px solid #f1f5f9;
      font-size: 14px;
      line-height: 1.4;
    }}
    .info-label {{
      color: #64748b;
      font-weight: 500;
      width: 40%;
    }}
    .info-value {{
      color: #0f172a;
      font-weight: 600;
      text-align: right;
    }}
    .total-box {{
      background-color: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 10px;
      padding: 16px 20px;
      margin: 24px 0;
    }}
    .total-label {{
      font-size: 14px;
      font-weight: 600;
      color: #475569;
    }}
    .total-amount {{
      font-size: 26px;
      font-weight: 800;
      color: #0284c7;
      text-align: right;
    }}
    .cta-btn {{
      display: block;
      background-color: #0284c7;
      color: #ffffff !important;
      text-decoration: none;
      font-size: 14px;
      font-weight: 700;
      text-align: center;
      padding: 13px 24px;
      border-radius: 10px;
      margin: 28px 0 16px 0;
    }}
    .footer {{
      margin-top: 28px;
      padding-top: 20px;
      border-top: 1px solid #f1f5f9;
      font-size: 12px;
      color: #94a3b8;
      text-align: center;
      line-height: 1.5;
    }}
    @media only screen and (max-width: 600px) {{
      .card {{
        padding: 24px 18px !important;
      }}
      .receipt-title {{
        font-size: 20px !important;
      }}
      .total-amount {{
        font-size: 22px !important;
      }}
      .info-label, .info-value {{
        font-size: 13px !important;
      }}
    }}
  </style>
</head>
<body>
  <div class="wrapper">
    <div class="card">
      <div class="brand-header">
        <div>
          <h1 class="brand-title">🛡️ MIRAGE 3.0</h1>
          <p class="brand-sub">AI Execution Assurance Platform</p>
        </div>
      </div>

      <div>
        <span class="status-badge">&#10003; PAID &amp; VERIFIED</span>
        <h2 class="receipt-title">Payment Confirmation Receipt</h2>
        <p class="receipt-desc">
          Your payment has been successfully settled and verified. Your active AI Execution Assurance subscription
          and lease quotas are now online.
        </p>
      </div>

      <table class="info-table">
        <tr>
          <td class="info-label">Invoice Number</td>
          <td class="info-value"><code>{invoice_id}</code></td>
        </tr>
        <tr>
          <td class="info-label">Tenant ID</td>
          <td class="info-value"><code>{tenant_id}</code></td>
        </tr>
        <tr>
          <td class="info-label">Plan Tier</td>
          <td class="info-value">{plan_name}</td>
        </tr>
        <tr>
          <td class="info-label">Payment Gateway</td>
          <td class="info-value">{payment_method}</td>
        </tr>
        <tr>
          <td class="info-label">Transaction / Order ID</td>
          <td class="info-value"><code>{payment_id}</code></td>
        </tr>
        <tr>
          <td class="info-label">Issued At</td>
          <td class="info-value">{now_str}</td>
        </tr>
      </table>

      <div class="total-box">
        <table style="width: 100%;">
          <tr>
            <td class="total-label">Total Amount Paid</td>
            <td class="total-amount">{formatted_amount}</td>
          </tr>
        </table>
      </div>

      <a href="http://localhost:3000/dashboard" class="cta-btn">Access Operator Console &rarr;</a>

      <div class="footer">
        <p>This is an automated transaction receipt for your subscription with MIRAGE AI.</p>
        <p>
          Need assistance or enterprise invoice customizations?
          Contact support at
          <a href="mailto:vedantwork1402@gmail.com" style="color: #0284c7; text-decoration: none;">
            vedantwork1402@gmail.com
          </a>
        </p>
      </div>
    </div>
  </div>
</body>
</html>
"""
        plain_text = f"""MIRAGE 3.0 - Payment Confirmation Receipt
================================================
Invoice Number: {invoice_id}
Tenant ID:      {tenant_id}
Plan Tier:      {plan_name}
Amount Paid:    {formatted_amount}
Gateway:        {payment_method}
Transaction ID: {payment_id}
Date & Time:    {now_str}
Status:         PAID & VERIFIED

Your subscription and Gate 3 lease quotas are active.
Access your Operator Console:
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
