import requests
from datetime import datetime, timezone, timedelta
from flask import Blueprint, redirect, request, flash, url_for, current_app, session
from app import db
from app.models import QBToken
from app.dashboard import require_auth

qb_bp = Blueprint("quickbooks", __name__)

QB_AUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
QB_TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
QB_API_BASE_SANDBOX = "https://sandbox-quickbooks.api.intuit.com/v3"
QB_API_BASE_PRODUCTION = "https://quickbooks.api.intuit.com/v3"


def get_api_base():
    if current_app.config.get("QB_ENVIRONMENT") == "production":
        return QB_API_BASE_PRODUCTION
    return QB_API_BASE_SANDBOX


def get_stored_token():
    """Get the stored QuickBooks token, refresh if expired."""
    token = QBToken.query.first()
    if not token:
        return None

    # Refresh if expired or about to expire (within 5 min)
    if datetime.now(timezone.utc) >= token.expires_at - timedelta(minutes=5):
        refreshed = refresh_token(token)
        if not refreshed:
            return None

    return token


def refresh_token(token):
    """Refresh the QuickBooks access token."""
    try:
        resp = requests.post(QB_TOKEN_URL, data={
            "grant_type": "refresh_token",
            "refresh_token": token.refresh_token,
        }, auth=(
            current_app.config["QB_CLIENT_ID"],
            current_app.config["QB_CLIENT_SECRET"],
        ), timeout=10)

        if resp.status_code != 200:
            return False

        data = resp.json()
        token.access_token = data["access_token"]
        token.refresh_token = data["refresh_token"]
        token.expires_at = datetime.now(timezone.utc) + timedelta(seconds=data["expires_in"])
        token.updated_at = datetime.now(timezone.utc)
        db.session.commit()
        return True
    except Exception:
        return False


def qb_request(method, endpoint, json_data=None):
    """Make an authenticated request to the QuickBooks API."""
    token = get_stored_token()
    if not token:
        return None

    url = f"{get_api_base()}/company/{token.realm_id}/{endpoint}"
    headers = {
        "Authorization": f"Bearer {token.access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    try:
        if method == "GET":
            resp = requests.get(url, headers=headers, timeout=10)
        elif method == "POST":
            resp = requests.post(url, headers=headers, json=json_data, timeout=10)

        if resp.status_code in (200, 201):
            return resp.json()
        return None
    except Exception:
        return None


# --- OAuth Routes ---

@qb_bp.route("/qb/connect")
@require_auth
def connect():
    """Start the QuickBooks OAuth flow."""
    client_id = current_app.config["QB_CLIENT_ID"]
    redirect_uri = current_app.config["QB_REDIRECT_URI"]
    scope = "com.intuit.quickbooks.accounting"

    auth_url = (
        f"{QB_AUTH_URL}?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&scope={scope}"
        f"&state=concord"
    )
    return redirect(auth_url)


@qb_bp.route("/qb/callback")
def callback():
    """Handle the QuickBooks OAuth callback."""
    code = request.args.get("code")
    realm_id = request.args.get("realmId")

    if not code or not realm_id:
        flash("QuickBooks connection failed — no authorization code received.", "error")
        return redirect(url_for("dashboard.settings_page"))

    # Exchange code for tokens
    try:
        resp = requests.post(QB_TOKEN_URL, data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": current_app.config["QB_REDIRECT_URI"],
        }, auth=(
            current_app.config["QB_CLIENT_ID"],
            current_app.config["QB_CLIENT_SECRET"],
        ), timeout=10)

        if resp.status_code != 200:
            flash(f"QuickBooks connection failed — token exchange error.", "error")
            return redirect(url_for("dashboard.settings_page"))

        data = resp.json()

        # Store or update the token
        token = QBToken.query.first()
        if token:
            token.access_token = data["access_token"]
            token.refresh_token = data["refresh_token"]
            token.realm_id = realm_id
            token.expires_at = datetime.now(timezone.utc) + timedelta(seconds=data["expires_in"])
            token.updated_at = datetime.now(timezone.utc)
        else:
            token = QBToken(
                access_token=data["access_token"],
                refresh_token=data["refresh_token"],
                realm_id=realm_id,
                expires_at=datetime.now(timezone.utc) + timedelta(seconds=data["expires_in"]),
            )
            db.session.add(token)

        db.session.commit()
        flash("QuickBooks connected successfully!", "success")

    except Exception as e:
        flash(f"QuickBooks connection failed: {str(e)}", "error")

    return redirect(url_for("dashboard.settings_page"))


@qb_bp.route("/qb/disconnect", methods=["POST"])
@require_auth
def disconnect():
    """Disconnect QuickBooks."""
    token = QBToken.query.first()
    if token:
        db.session.delete(token)
        db.session.commit()
    flash("QuickBooks disconnected.", "success")
    return redirect(url_for("dashboard.settings_page"))


# --- QuickBooks Business Functions ---

def is_connected():
    """Check if QuickBooks is connected."""
    return get_stored_token() is not None


def find_or_create_customer(name, email):
    """Find a customer in QuickBooks by name, or create one."""
    # Search for existing customer
    query = f"select * from Customer where DisplayName = '{name}'"
    result = qb_request("GET", f"query?query={query}")
    if result and result.get("QueryResponse", {}).get("Customer"):
        return result["QueryResponse"]["Customer"][0]["Id"]

    # Create new customer
    customer_data = {
        "DisplayName": name,
        "PrimaryEmailAddr": {"Address": email},
    }
    result = qb_request("POST", "customer", customer_data)
    if result and result.get("Customer"):
        return result["Customer"]["Id"]

    return None


def create_qb_invoice(client_name, client_email, line_items, due_date=None):
    """Create an invoice in QuickBooks.

    line_items: list of dicts with 'description' and 'amount' (in dollars)
    """
    customer_id = find_or_create_customer(client_name, client_email)
    if not customer_id:
        return None

    lines = []
    for i, item in enumerate(line_items):
        lines.append({
            "LineNum": i + 1,
            "Amount": item["amount"],
            "DetailType": "SalesItemLineDetail",
            "Description": item["description"],
            "SalesItemLineDetail": {
                "ItemRef": {"value": "1", "name": "Services"},
                "Qty": 1,
                "UnitPrice": item["amount"],
            },
        })

    invoice_data = {
        "CustomerRef": {"value": customer_id},
        "Line": lines,
    }

    if due_date:
        invoice_data["DueDate"] = due_date.strftime("%Y-%m-%d")

    result = qb_request("POST", "invoice", invoice_data)
    if result and result.get("Invoice"):
        return result["Invoice"]["Id"]

    return None


def create_qb_expense(description, amount_dollars, account_name="Operating Expenses"):
    """Log an expense in QuickBooks as a purchase/expense entry."""
    # Find or use default expense account
    query = f"select * from Account where AccountType = 'Expense' MAXRESULTS 1"
    result = qb_request("GET", f"query?query={query}")
    account_id = "1"  # fallback
    if result and result.get("QueryResponse", {}).get("Account"):
        account_id = result["QueryResponse"]["Account"][0]["Id"]

    # Find or create a vendor for Concord AI internal
    query = "select * from Vendor where DisplayName = 'Platform Costs'"
    result = qb_request("GET", f"query?query={query}")
    vendor_id = None
    if result and result.get("QueryResponse", {}).get("Vendor"):
        vendor_id = result["QueryResponse"]["Vendor"][0]["Id"]
    else:
        vendor_result = qb_request("POST", "vendor", {"DisplayName": "Platform Costs"})
        if vendor_result and vendor_result.get("Vendor"):
            vendor_id = vendor_result["Vendor"]["Id"]

    if not vendor_id:
        return None

    purchase_data = {
        "PaymentType": "Cash",
        "TotalAmt": amount_dollars,
        "Line": [{
            "Amount": amount_dollars,
            "DetailType": "AccountBasedExpenseLineDetail",
            "Description": description,
            "AccountBasedExpenseLineDetail": {
                "AccountRef": {"value": account_id},
            },
        }],
        "AccountRef": {"value": account_id},
        "EntityRef": {"value": vendor_id, "type": "Vendor"},
    }

    result = qb_request("POST", "purchase", purchase_data)
    if result and result.get("Purchase"):
        return result["Purchase"]["Id"]

    return None


def get_qb_profit_loss():
    """Pull a profit & loss report from QuickBooks."""
    result = qb_request("GET", "reports/ProfitAndLoss?date_macro=This Month")
    return result


def get_qb_company_info():
    """Get basic company info to verify the connection."""
    result = qb_request("GET", "companyinfo")
    if result and result.get("CompanyInfo"):
        return result["CompanyInfo"]
    # Try alternate response format
    for key in result or {}:
        if key.startswith("CompanyInfo"):
            return result[key]
    return None
