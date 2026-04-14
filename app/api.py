import math
from flask import Blueprint, request, jsonify, current_app
from app import db
from app.models import Call, AgentMapping

api_bp = Blueprint("api", __name__)


@api_bp.route("/api/call", methods=["POST"])
def receive_call():
    """Receives call data from agent apps (like E&E Agent)."""
    # Check API key
    api_key = request.headers.get("X-API-Key")
    if api_key != current_app.config["API_KEY"]:
        return jsonify({"error": "unauthorized"}), 401

    data = request.json

    retell_agent_id = data.get("agent_id")
    retell_call_id = data.get("call_id")
    from_number = data.get("from_number", "Unknown")
    duration_ms = data.get("duration_ms", 0)
    call_summary = data.get("call_summary")
    user_sentiment = data.get("user_sentiment")
    support_type = data.get("support_type")
    call_successful = data.get("call_successful", False)

    # Find which client this agent belongs to
    client_id = None
    mapping = AgentMapping.query.filter_by(retell_agent_id=retell_agent_id).first()
    if mapping:
        client_id = mapping.client_id

    # Calculate cost: round up to nearest minute × cost per minute
    duration_min = math.ceil(duration_ms / 60000) if duration_ms > 0 else 0
    cost_cents = duration_min * current_app.config["DEFAULT_COST_PER_MIN_CENTS"]

    # Check for duplicate
    if retell_call_id:
        existing = Call.query.filter_by(retell_call_id=retell_call_id).first()
        if existing:
            return jsonify({"status": "duplicate"}), 200

    call = Call(
        client_id=client_id,
        retell_agent_id=retell_agent_id,
        retell_call_id=retell_call_id,
        from_number=from_number,
        duration_ms=duration_ms,
        call_summary=call_summary,
        user_sentiment=user_sentiment,
        support_type=support_type,
        call_successful=call_successful,
        cost_cents=cost_cents,
    )
    db.session.add(call)
    db.session.commit()

    return jsonify({"status": "recorded", "call_id": call.id}), 200


@api_bp.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200
