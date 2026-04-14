import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///concord.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Resend
    RESEND_API_KEY = os.getenv("RESEND_API_KEY")
    EMAIL_FROM = os.getenv("EMAIL_FROM", "onboarding@resend.dev")

    # Stripe
    STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
    STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

    # Dashboard auth
    DASHBOARD_USERNAME = os.getenv("DASHBOARD_USERNAME", "admin")
    DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "changeme")

    # Default cost per minute in cents (Retell ~$0.08/min)
    DEFAULT_COST_PER_MIN_CENTS = int(os.getenv("DEFAULT_COST_PER_MIN_CENTS", "8"))

    # Twilio
    TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
    TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")

    # QuickBooks
    QB_CLIENT_ID = os.getenv("QB_CLIENT_ID")
    QB_CLIENT_SECRET = os.getenv("QB_CLIENT_SECRET")
    QB_REDIRECT_URI = os.getenv("QB_REDIRECT_URI", "http://localhost:5000/qb/callback")
    QB_ENVIRONMENT = os.getenv("QB_ENVIRONMENT", "sandbox")

    # API key for agent apps to send data
    API_KEY = os.getenv("API_KEY", "change-me")
