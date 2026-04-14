from datetime import datetime, timezone
from app import db


class Client(db.Model):
    __tablename__ = "clients"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(200), nullable=False)
    monthly_fee_cents = db.Column(db.Integer, default=0)
    overage_threshold_minutes = db.Column(db.Integer, default=0)
    overage_rate_cents = db.Column(db.Integer, default=10)
    twilio_phone_number = db.Column(db.String(50), nullable=True)
    stripe_customer_id = db.Column(db.String(200), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    agents = db.relationship("AgentMapping", backref="client", lazy=True)
    calls = db.relationship("Call", backref="client", lazy=True)
    invoices = db.relationship("Invoice", backref="client", lazy=True)


class AgentMapping(db.Model):
    __tablename__ = "agent_mappings"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False)
    retell_agent_id = db.Column(db.String(200), unique=True, nullable=False)
    label = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class Call(db.Model):
    __tablename__ = "calls"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=True)
    retell_agent_id = db.Column(db.String(200), nullable=True)
    retell_call_id = db.Column(db.String(200), unique=True, nullable=True)
    from_number = db.Column(db.String(50), default="Unknown")
    duration_ms = db.Column(db.Integer, default=0)
    call_summary = db.Column(db.Text, nullable=True)
    user_sentiment = db.Column(db.String(50), nullable=True)
    support_type = db.Column(db.String(100), nullable=True)
    call_successful = db.Column(db.Boolean, default=False)
    cost_cents = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class PlatformCost(db.Model):
    __tablename__ = "platform_costs"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    monthly_cost_cents = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class QBToken(db.Model):
    __tablename__ = "qb_tokens"

    id = db.Column(db.Integer, primary_key=True)
    access_token = db.Column(db.Text, nullable=False)
    refresh_token = db.Column(db.Text, nullable=False)
    realm_id = db.Column(db.String(200), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class Invoice(db.Model):
    __tablename__ = "invoices"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False)
    billing_period_start = db.Column(db.Date, nullable=False)
    billing_period_end = db.Column(db.Date, nullable=False)
    base_fee_cents = db.Column(db.Integer, default=0)
    total_minutes = db.Column(db.Float, default=0)
    overage_minutes = db.Column(db.Float, default=0)
    overage_amount_cents = db.Column(db.Integer, default=0)
    total_cents = db.Column(db.Integer, default=0)
    stripe_invoice_id = db.Column(db.String(200), nullable=True)
    stripe_payment_url = db.Column(db.String(500), nullable=True)
    status = db.Column(db.String(50), default="draft")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
