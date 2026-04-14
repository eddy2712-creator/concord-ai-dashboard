import math
from datetime import datetime, date
from flask import Blueprint, request, redirect, url_for, flash, current_app, jsonify
from app import db
from app.models import Client, Call, Invoice
from app.email_service import send_email
from app.dashboard import require_auth, get_month_range

billing_bp = Blueprint("billing", __name__)


def calculate_billing(client_id, year, month):
    """Calculate what a client owes for a given month."""
    client = Client.query.get(client_id)
    if not client:
        return None

    month_start, month_end = get_month_range(year, month)

    month_calls = Call.query.filter(
        Call.client_id == client_id,
        Call.created_at >= datetime.combine(month_start, datetime.min.time()),
        Call.created_at < datetime.combine(month_end, datetime.min.time()),
    ).all()

    total_minutes = sum(c.duration_ms for c in month_calls) / 60000
    total_cost_cents = sum(c.cost_cents for c in month_calls)
    call_count = len(month_calls)

    overage_minutes = 0
    overage_amount_cents = 0
    if client.overage_threshold_minutes > 0 and total_minutes > client.overage_threshold_minutes:
        overage_minutes = total_minutes - client.overage_threshold_minutes
        overage_amount_cents = math.ceil(overage_minutes) * client.overage_rate_cents

    total_cents = client.monthly_fee_cents + overage_amount_cents

    return {
        "client": client,
        "month_start": month_start,
        "month_end": month_end,
        "call_count": call_count,
        "total_minutes": round(total_minutes, 1),
        "total_cost_cents": total_cost_cents,
        "base_fee_cents": client.monthly_fee_cents,
        "overage_minutes": round(overage_minutes, 1),
        "overage_amount_cents": overage_amount_cents,
        "total_cents": total_cents,
    }


@billing_bp.route("/dashboard/generate-invoice/<int:client_id>", methods=["POST"])
@require_auth
def generate_invoice(client_id):
    year = int(request.form.get("year", date.today().year))
    month = int(request.form.get("month", date.today().month))

    billing = calculate_billing(client_id, year, month)
    if not billing:
        flash("Client not found", "error")
        return redirect(url_for("dashboard.overview"))

    client = billing["client"]

    # Create invoice record
    invoice = Invoice(
        client_id=client_id,
        billing_period_start=billing["month_start"],
        billing_period_end=billing["month_end"],
        base_fee_cents=billing["base_fee_cents"],
        total_minutes=billing["total_minutes"],
        overage_minutes=billing["overage_minutes"],
        overage_amount_cents=billing["overage_amount_cents"],
        total_cents=billing["total_cents"],
        status="draft",
    )

    # Try to create Stripe invoice if Stripe is configured
    stripe_key = current_app.config.get("STRIPE_SECRET_KEY")
    if stripe_key:
        try:
            import stripe
            stripe.api_key = stripe_key

            # Create or get Stripe customer
            if not client.stripe_customer_id:
                customer = stripe.Customer.create(
                    name=client.name,
                    email=client.email,
                )
                client.stripe_customer_id = customer.id

            # Create invoice items
            stripe.InvoiceItem.create(
                customer=client.stripe_customer_id,
                amount=billing["base_fee_cents"],
                currency="usd",
                description=f"Monthly AI Receptionist Service — {billing['month_start'].strftime('%B %Y')}",
            )

            if billing["overage_amount_cents"] > 0:
                stripe.InvoiceItem.create(
                    customer=client.stripe_customer_id,
                    amount=billing["overage_amount_cents"],
                    currency="usd",
                    description=f"Overage: {billing['overage_minutes']} minutes over threshold @ ${client.overage_rate_cents / 100:.2f}/min",
                )

            # Create and finalize the invoice
            stripe_invoice = stripe.Invoice.create(
                customer=client.stripe_customer_id,
                collection_method="send_invoice",
                days_until_due=14,
            )
            stripe_invoice = stripe.Invoice.finalize_invoice(stripe_invoice.id)

            invoice.stripe_invoice_id = stripe_invoice.id
            invoice.stripe_payment_url = stripe_invoice.hosted_invoice_url
            invoice.status = "sent"

        except Exception as e:
            flash(f"Stripe error: {str(e)}. Invoice saved as draft.", "error")

    db.session.add(invoice)
    db.session.commit()

    # Sync invoice to QuickBooks if connected
    try:
        from app.quickbooks import is_connected, create_qb_invoice
        if is_connected():
            line_items = [
                {"description": f"Monthly AI Receptionist Service — {billing['month_start'].strftime('%B %Y')}", "amount": billing["base_fee_cents"] / 100},
            ]
            if billing["overage_amount_cents"] > 0:
                line_items.append({
                    "description": f"Overage: {billing['overage_minutes']} minutes @ ${client.overage_rate_cents / 100:.2f}/min",
                    "amount": billing["overage_amount_cents"] / 100,
                })
            qb_id = create_qb_invoice(client.name, client.email, line_items)
            if qb_id:
                flash("Invoice synced to QuickBooks!", "success")
    except Exception:
        pass  # Don't let QB issues block the invoice

    # Send invoice email if we have a payment URL
    if invoice.stripe_payment_url:
        try:
            html = f"""
            <h2>Invoice from Concord AI</h2>
            <p>Hi {client.name},</p>
            <p>Here is your invoice for <strong>{billing['month_start'].strftime('%B %Y')}</strong>:</p>
            <table style="border-collapse: collapse;">
                <tr><td style="padding: 4px 12px 4px 0;"><strong>Base fee:</strong></td><td>${billing['base_fee_cents'] / 100:.2f}</td></tr>
                <tr><td style="padding: 4px 12px 4px 0;"><strong>Total minutes used:</strong></td><td>{billing['total_minutes']}</td></tr>
                <tr><td style="padding: 4px 12px 4px 0;"><strong>Overage:</strong></td><td>${billing['overage_amount_cents'] / 100:.2f}</td></tr>
                <tr><td style="padding: 4px 12px 4px 0;"><strong>Total due:</strong></td><td><strong>${billing['total_cents'] / 100:.2f}</strong></td></tr>
            </table>
            <br>
            <p><a href="{invoice.stripe_payment_url}" style="background-color: #4F46E5; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px;">Pay Now</a></p>
            <br>
            <p>Thank you for your business!</p>
            <p>— Concord AI</p>
            """
            send_email(
                client.email,
                f"Invoice — Concord AI — {billing['month_start'].strftime('%B %Y')}",
                html,
            )
            flash(f"Invoice created and emailed to {client.email}!", "success")
        except Exception as e:
            flash(f"Invoice created but email failed: {str(e)}", "error")
    else:
        flash("Invoice saved as draft (no Stripe configured).", "success")

    return redirect(url_for("dashboard.client_detail", client_id=client_id))
