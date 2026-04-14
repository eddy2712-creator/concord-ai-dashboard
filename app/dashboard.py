from datetime import datetime, timezone, date
from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, flash, Response, current_app
from sqlalchemy import func
from app import db
from app.models import Client, AgentMapping, Call, Invoice, PlatformCost
from app.twilio_service import get_twilio_costs

dashboard_bp = Blueprint("dashboard", __name__)


def check_auth(username, password):
    return (username == current_app.config["DASHBOARD_USERNAME"] and
            password == current_app.config["DASHBOARD_PASSWORD"])


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return Response(
                "Login required", 401,
                {"WWW-Authenticate": 'Basic realm="Concord AI Dashboard"'}
            )
        return f(*args, **kwargs)
    return decorated


def get_month_range(year=None, month=None):
    today = date.today()
    if not year:
        year = today.year
    if not month:
        month = today.month
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    return start, end


@dashboard_bp.route("/")
@require_auth
def index():
    return redirect(url_for("dashboard.overview"))


@dashboard_bp.route("/dashboard")
@require_auth
def overview():
    clients = Client.query.filter_by(is_active=True).all()
    month_start, month_end = get_month_range()

    # Calculate platform costs split across active clients
    platform_costs = PlatformCost.query.filter_by(is_active=True).all()
    total_platform_cents = sum(p.monthly_cost_cents for p in platform_costs)
    num_clients = len(clients) if clients else 1
    platform_per_client_cents = total_platform_cents // num_clients if num_clients > 0 else 0

    client_stats = []
    for client in clients:
        # Get this month's calls
        month_calls = Call.query.filter(
            Call.client_id == client.id,
            Call.created_at >= datetime.combine(month_start, datetime.min.time()),
            Call.created_at < datetime.combine(month_end, datetime.min.time()),
        ).all()

        total_minutes = sum(c.duration_ms for c in month_calls) / 60000
        total_cost_cents = sum(c.cost_cents for c in month_calls)
        call_count = len(month_calls)

        threshold = client.overage_threshold_minutes
        percent_used = (total_minutes / threshold * 100) if threshold > 0 else 0
        is_over = total_minutes > threshold if threshold > 0 else False

        # Get Twilio costs for this client
        twilio = get_twilio_costs(client.twilio_phone_number, month_start, month_end)
        retell_cost_cents = total_cost_cents
        twilio_cost_cents = twilio["total_cents"]
        combined_cost_cents = retell_cost_cents + twilio_cost_cents + platform_per_client_cents

        client_stats.append({
            "client": client,
            "call_count": call_count,
            "total_minutes": round(total_minutes, 1),
            "retell_cost_dollars": retell_cost_cents / 100,
            "twilio_cost_dollars": twilio_cost_cents / 100,
            "platform_cost_dollars": platform_per_client_cents / 100,
            "total_cost_dollars": combined_cost_cents / 100,
            "percent_used": round(percent_used, 1),
            "is_over": is_over,
        })

    return render_template("dashboard.html",
                           client_stats=client_stats,
                           platform_costs=platform_costs,
                           total_platform_dollars=total_platform_cents / 100,
                           month=month_start.strftime("%B %Y"))


@dashboard_bp.route("/dashboard/client/<int:client_id>")
@require_auth
def client_detail(client_id):
    client = Client.query.get_or_404(client_id)
    month_start, month_end = get_month_range()

    calls = Call.query.filter(
        Call.client_id == client.id,
    ).order_by(Call.created_at.desc()).limit(50).all()

    month_calls = [c for c in calls
                   if c.created_at >= datetime.combine(month_start, datetime.min.time())
                   and c.created_at < datetime.combine(month_end, datetime.min.time())]

    total_minutes = sum(c.duration_ms for c in month_calls) / 60000
    total_cost_cents = sum(c.cost_cents for c in month_calls)

    agents = AgentMapping.query.filter_by(client_id=client.id).all()
    invoices = Invoice.query.filter_by(client_id=client.id).order_by(Invoice.created_at.desc()).limit(12).all()

    twilio = get_twilio_costs(client.twilio_phone_number, month_start, month_end)

    return render_template("client_detail.html",
                           client=client,
                           calls=calls,
                           agents=agents,
                           invoices=invoices,
                           total_minutes=round(total_minutes, 1),
                           retell_cost_dollars=total_cost_cents / 100,
                           twilio_cost_dollars=twilio["total_cents"] / 100,
                           total_cost_dollars=(total_cost_cents + twilio["total_cents"]) / 100,
                           month=month_start.strftime("%B %Y"))


@dashboard_bp.route("/dashboard/clients/add", methods=["GET", "POST"])
@require_auth
def add_client():
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        monthly_fee = int(float(request.form.get("monthly_fee", 0)) * 100)
        threshold = int(request.form.get("threshold_minutes", 0))
        overage_rate = int(float(request.form.get("overage_rate", 0.10)) * 100)
        twilio_phone = request.form.get("twilio_phone_number", "").strip()
        agent_id = request.form.get("retell_agent_id", "").strip()
        agent_label = request.form.get("agent_label", "").strip()

        client = Client(
            name=name,
            email=email,
            monthly_fee_cents=monthly_fee,
            overage_threshold_minutes=threshold,
            overage_rate_cents=overage_rate,
            twilio_phone_number=twilio_phone or None,
        )
        db.session.add(client)
        db.session.flush()

        if agent_id:
            mapping = AgentMapping(
                client_id=client.id,
                retell_agent_id=agent_id,
                label=agent_label or None,
            )
            db.session.add(mapping)

        db.session.commit()
        flash(f"Client '{name}' added successfully!", "success")
        return redirect(url_for("dashboard.overview"))

    return render_template("add_client.html")


@dashboard_bp.route("/dashboard/platform-costs", methods=["GET", "POST"])
@require_auth
def platform_costs_page():
    if request.method == "POST":
        name = request.form["name"].strip()
        cost = int(float(request.form.get("monthly_cost", 0)) * 100)
        if name:
            pc = PlatformCost(name=name, monthly_cost_cents=cost)
            db.session.add(pc)
            db.session.commit()
            flash(f"Added '{name}' — ${cost / 100:.2f}/month", "success")
        return redirect(url_for("dashboard.platform_costs_page"))

    costs = PlatformCost.query.filter_by(is_active=True).all()
    total_cents = sum(c.monthly_cost_cents for c in costs)
    num_clients = Client.query.filter_by(is_active=True).count() or 1
    return render_template("platform_costs.html",
                           costs=costs,
                           total_dollars=total_cents / 100,
                           per_client_dollars=(total_cents // num_clients) / 100,
                           num_clients=num_clients)


@dashboard_bp.route("/dashboard/platform-costs/delete/<int:cost_id>", methods=["POST"])
@require_auth
def delete_platform_cost(cost_id):
    pc = PlatformCost.query.get_or_404(cost_id)
    pc.is_active = False
    db.session.commit()
    flash(f"Removed '{pc.name}'", "success")
    return redirect(url_for("dashboard.platform_costs_page"))


@dashboard_bp.route("/dashboard/settings")
@require_auth
def settings_page():
    from app.quickbooks import is_connected, get_qb_company_info
    qb_connected = is_connected()
    qb_company = None
    if qb_connected:
        info = get_qb_company_info()
        if info:
            qb_company = info.get("CompanyName", "Connected")
    return render_template("settings.html",
                           qb_connected=qb_connected,
                           qb_company=qb_company,
                           username=current_app.config["DASHBOARD_USERNAME"])


@dashboard_bp.route("/dashboard/invoices")
@require_auth
def invoices():
    all_invoices = Invoice.query.order_by(Invoice.created_at.desc()).all()
    return render_template("invoices.html", invoices=all_invoices)
