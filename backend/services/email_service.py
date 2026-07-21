"""
Email notification service using Gmail SMTP (App Password).
Sends HTML email with human-readable policy change summary.
"""
from __future__ import annotations

import logging
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from dotenv import load_dotenv

load_dotenv()

from core.config import get_settings
from services.change_analysis import analyze_changes
from services.diff_service import StructuredDiff

logger = logging.getLogger(__name__)


def _markdown_to_simple_html(markdown_text: str) -> str:
    """
    Minimal Markdown → HTML conversion for email bodies.
    Handles headers, bold, bullet lists, horizontal rules.
    """
    import re
    html = markdown_text

    # Headers
    html = re.sub(r"^### (.+)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)
    html = re.sub(r"^## (.+)$", r"<h2>\1</h2>", html, flags=re.MULTILINE)
    html = re.sub(r"^# (.+)$", r"<h1>\1</h1>", html, flags=re.MULTILINE)

    # Bold
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)

    # Bullet items
    html = re.sub(r"^[-*] (.+)$", r"<li>\1</li>", html, flags=re.MULTILINE)
    html = re.sub(r"(<li>.*?</li>\n?)+", lambda m: f"<ul>{m.group()}</ul>", html, flags=re.DOTALL)

    # Horizontal rule
    html = re.sub(r"^---$", "<hr/>", html, flags=re.MULTILINE)

    # Paragraphs (double newline)
    paragraphs = re.split(r"\n\n+", html)
    html = "".join(
        p if p.startswith("<") else f"<p>{p.strip()}</p>"
        for p in paragraphs if p.strip()
    )

    return html


def generate_change_summary(diff: StructuredDiff) -> str:
    """
    Generate human-readable change summary from StructuredDiff.
    Uses intelligent filtering to show only meaningful policy changes.
    """
    analysis = analyze_changes(diff)
    return analysis.get_detailed_summary()


def build_email_html(
    base_name: str,
    old_version: int,
    new_version: int,
    diff_summary: str,
) -> tuple[str, str]:
    """Returns (subject, html_body)."""
    policy_title = base_name.replace("_", " ").title()
    subject = (
        f"[HR Policy Update] {policy_title}: "
        f"v{old_version} → v{new_version} — Action Required"
    )
    diff_html = _markdown_to_simple_html(diff_summary)
    timestamp = datetime.utcnow().strftime("%d %b %Y, %H:%M UTC")

    html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8"/>
  <style>
    body {{ font-family: Arial, sans-serif; background: #f4f6f9; margin: 0; padding: 0; }}
    .container {{ max-width: 680px; margin: 30px auto; background: #fff;
                  border-radius: 8px; overflow: hidden;
                  box-shadow: 0 2px 10px rgba(0,0,0,.1); }}
    .header {{ background: #1a3c5e; color: #fff; padding: 28px 32px; }}
    .header h1 {{ margin: 0; font-size: 22px; }}
    .header p  {{ margin: 6px 0 0; opacity: .8; font-size: 13px; }}
    .badge {{ display: inline-block; background: #e74c3c; color: #fff;
              border-radius: 4px; padding: 2px 10px; font-size: 12px;
              font-weight: bold; margin-left: 10px; }}
    .body {{ padding: 28px 32px; color: #333; line-height: 1.6; }}
    .diff-box {{ background: #f8f9fa; border-left: 4px solid #1a3c5e;
                 padding: 18px 20px; border-radius: 4px; margin: 18px 0; }}
    .diff-box h2, .diff-box h3 {{ color: #1a3c5e; }}
    .diff-box ul {{ padding-left: 20px; }}
    .cta {{ background: #1a3c5e; color: #fff; padding: 12px 24px;
            border-radius: 6px; text-decoration: none; display: inline-block;
            margin-top: 16px; font-weight: bold; }}
    .footer {{ background: #f4f6f9; padding: 16px 32px;
               font-size: 12px; color: #888; text-align: center; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>HR Policy Update <span class="badge">REVIEW REQUIRED</span></h1>
      <p>Automated notification · {timestamp}</p>
    </div>
    <div class="body">
      <p>
        A new version of the <strong>{policy_title}</strong> policy has been uploaded.
        The system has detected changes between <strong>Version {old_version}</strong>
        and <strong>Version {new_version}</strong>.
      </p>
      <p>Please review the changes summarised below and update affected employees accordingly.</p>

      <div class="diff-box">
        <h2>📋 Change Summary</h2>
        {diff_html}
      </div>

      <p>You can also ask the HR Chatbot: <em>"What changed in the {policy_title}?"</em>
         to get an interactive explanation.</p>

      <a class="cta" href="#">Open HR Chatbot →</a>
    </div>
    <div class="footer">
      This is an automated message from the HR Policy Management System.<br/>
      Do not reply to this email.
    </div>
  </div>
</body>
</html>
"""
    return subject, html


def send_policy_change_email(
    base_name: str,
    old_version: int,
    new_version: int,
    diff_summary: str | StructuredDiff = None,
    max_retries: int = 3,
) -> bool:
    """
    Send a policy-change notification email via Gmail SMTP with retry logic.
    Returns True on success, False on repeated failures.
    diff_summary can be either a StructuredDiff object or a string.
    """
    import time
    
    settings = get_settings()
    
    # Validate credentials are configured
    if not settings.gmail_sender or not settings.gmail_app_password:
        logger.warning(
            "Email credentials not configured. Cannot send policy change notification for %s v%s→v%s. "
            "Set GMAIL_SENDER and GMAIL_APP_PASSWORD env vars.",
            base_name, old_version, new_version
        )
        return False
    
    # Generate human-readable summary if StructuredDiff object is passed
    # Use duck typing since import paths may differ between test and service
    if hasattr(diff_summary, 'paragraph_diffs') and hasattr(diff_summary, 'table_diffs'):
        # This is a StructuredDiff object, convert to readable summary
        diff_summary = generate_change_summary(diff_summary)
    elif not isinstance(diff_summary, str):
        logger.error("diff_summary must be StructuredDiff or string, got %s", type(diff_summary))
        return False
    
    subject, html_body = build_email_html(base_name, old_version, new_version, diff_summary)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.gmail_sender
    msg["To"] = settings.gmail_notify_recipient

    # Plain text fallback
    plain = (
        f"HR Policy Update: {base_name.replace('_', ' ').title()} "
        f"v{old_version} → v{new_version}\n\n{diff_summary}"
    )
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    
    # Retry logic with exponential backoff
    for attempt in range(max_retries):
        try:
            # Use SMTP with STARTTLS for port 587, or SMTP_SSL for port 465
            if SMTP_PORT == 465:
                server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
            else:
                server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
                server.starttls()
            
            with server:
                server.login(settings.gmail_sender, settings.gmail_app_password)
                server.sendmail(
                    settings.gmail_sender,
                    settings.gmail_notify_recipient,
                    msg.as_string(),
                )
            logger.info(
                "Policy change email sent to %s for %s v%s→v%s",
                settings.gmail_notify_recipient, base_name, old_version, new_version,
            )
            return True
        except Exception as exc:
            if attempt < max_retries - 1:
                # Exponential backoff: 1s, 2s, 4s, etc.
                wait_time = 2 ** attempt
                logger.warning(
                    "Failed to send policy change email (attempt %d/%d): %s. Retrying in %ds...",
                    attempt + 1, max_retries, exc, wait_time
                )
                time.sleep(wait_time)
            else:
                logger.error(
                    "Failed to send policy change email after %d attempts for %s v%s→v%s: %s",
                    max_retries, base_name, old_version, new_version, exc
                )
                return False
    
    return False
