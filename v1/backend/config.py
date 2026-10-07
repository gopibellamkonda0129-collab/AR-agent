"""App configuration.

Reads from environment (or v1/backend/.env):

  AR_DEMO       = "1"            -> run with bundled synthetic email data, no
                                    real Gmail/Outlook/Supabase needed.
  SUPABASE_URL  = "https://xxx.supabase.co"
  SUPABASE_KEY  = "service-role key"
  OPENAI_API_KEY = "sk-..."      -> LLM-powered email analysis (optional)
  GMAIL_CLIENT_SECRET / OUTLOOK_CLIENT_SECRET -> OAuth files for prod connect
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    demo: bool = os.environ.get("AR_DEMO", "1") == "1"
    supabase_url: str = os.environ.get("SUPABASE_URL", "")
    supabase_key: str = os.environ.get("SUPABASE_KEY", "")
    openai_api_key: str = os.environ.get("OPENAI_API_KEY", "")
    gmail_credentials_file: str = os.environ.get("GMAIL_CLIENT_SECRET", "gmail_client_secret.json")
    outlook_credentials_file: str = os.environ.get("OUTLOOK_CLIENT_SECRET", "outlook_client_secret.json")
    # background poll interval for connected inboxes (seconds). 0 disables.
    sync_interval_seconds: int = int(os.environ.get("AR_SYNC_INTERVAL", "300"))
    # public base URL used for the Gmail OAuth redirect. Set to your domain in prod.
    base_url: str = os.environ.get("AR_BASE_URL", "http://127.0.0.1:8000")
    # absolute path to the V0 ar_agent package (for the invoice importers)
    v0_dir: str = os.environ.get(
        "AR_V0_DIR",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "ar_agent"),
    )
    # follow-up drafts signature + who the emails come from
    sender_name: str = os.environ.get("AR_SENDER_NAME", "Gopi")
    sender_email: str = os.environ.get("AR_SENDER_EMAIL", "ar@yourcompany.com")
    # outgoing email. V1 NEVER sends without explicit user approval; even then,
    # sending only works when AR_ALLOW_SEND=1 and SMTP creds are present.
    allow_send: bool = os.environ.get("AR_ALLOW_SEND", "0") == "1"
    smtp_host: str = os.environ.get("AR_SMTP_HOST", "")
    smtp_port: int = int(os.environ.get("AR_SMTP_PORT", "587"))
    smtp_user: str = os.environ.get("AR_SMTP_USER", "")
    smtp_password: str = os.environ.get("AR_SMTP_PASSWORD", "")
    # business timezone-ish window used for labels like "follow up today"
    business_days_per_week: int = 5


settings = Settings()