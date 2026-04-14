import requests
from datetime import date
from flask import current_app


def get_twilio_costs(phone_number, start_date, end_date):
    """Pull usage costs from Twilio for a specific phone number."""
    sid = current_app.config.get("TWILIO_ACCOUNT_SID")
    token = current_app.config.get("TWILIO_AUTH_TOKEN")

    if not sid or not token or not phone_number:
        return {"phone_cost_cents": 0, "call_cost_cents": 0, "total_cents": 0, "minutes": 0}

    # Monthly phone number cost (~$1.15/month for US numbers)
    phone_cost_cents = 115

    # Get call usage for this number
    call_cost_cents = 0
    total_minutes = 0
    try:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Calls.json"
        params = {
            "To": phone_number,
            "StartTime>": start_date.strftime("%Y-%m-%d"),
            "StartTime<": end_date.strftime("%Y-%m-%d"),
            "PageSize": 1000,
        }
        resp = requests.get(url, auth=(sid, token), params=params, timeout=10)
        if resp.status_code == 200:
            calls = resp.json().get("calls", [])
            for call in calls:
                duration = int(call.get("duration", 0))
                total_minutes += duration / 60
                price = call.get("price")
                if price:
                    call_cost_cents += abs(int(float(price) * 100))

        # Also check outbound calls from this number
        params["From"] = phone_number
        del params["To"]
        resp = requests.get(url, auth=(sid, token), params=params, timeout=10)
        if resp.status_code == 200:
            calls = resp.json().get("calls", [])
            for call in calls:
                duration = int(call.get("duration", 0))
                total_minutes += duration / 60
                price = call.get("price")
                if price:
                    call_cost_cents += abs(int(float(price) * 100))

    except Exception:
        pass

    total_cents = phone_cost_cents + call_cost_cents

    return {
        "phone_cost_cents": phone_cost_cents,
        "call_cost_cents": call_cost_cents,
        "total_cents": total_cents,
        "minutes": round(total_minutes, 1),
    }
