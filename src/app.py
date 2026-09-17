# src/app.py
"""Flask application for RoomPilot AI booking assistant."""

import os
import uuid
from pathlib import Path
from flask import Flask, request, jsonify, session, redirect, url_for, send_from_directory
from langchain_core.messages import HumanMessage

from src.config import FlaskConfig, logger
from src.booking_agent.workflow import get_compiled_agent

app = Flask(__name__)
app.config.from_object(FlaskConfig)

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

# Ensure data directory exists for checkpoints database
os.makedirs("data", exist_ok=True)
AGENT = get_compiled_agent(db_path="data/checkpoints.sqlite")


# ── 4.5: Structured JSON error handlers ───────────────────────────────────

@app.errorhandler(400)
def bad_request(e):
    return jsonify({"error": "Bad request", "detail": str(e), "code": 400}), 400


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found", "detail": str(e), "code": 404}), 404


@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({"error": "Method not allowed", "detail": str(e), "code": 405}), 405


@app.errorhandler(500)
def internal_error(e):
    logger.exception("Unhandled 500 error")
    return jsonify({"error": "Internal server error", "code": 500, "retry": True}), 500


# ── Routes ─────────────────────────────────────────────────────────────────

@app.route("/")
def home():
    if (FRONTEND_DIST / "index.html").exists():
        return send_from_directory(FRONTEND_DIST, "index.html")
    return jsonify({"error": "Frontend not built. Run `npm run build`."}), 404


@app.route("/assets/<path:filename>")
def frontend_assets(filename):
    return send_from_directory(FRONTEND_DIST / "assets", filename)


@app.route("/api/booking", methods=["GET", "POST"])
def api_booking():
    """
    GET  → return current thread message history (for page reload restore).
    POST → send a user message, get agent reply.
    All conversation state lives in SQLite via LangGraph SqliteSaver.
    Flask session holds ONLY thread_id (~50 bytes).
    """
    # Ensure thread_id exists
    thread_id = session.get("thread_id")
    if not thread_id:
        thread_id = str(uuid.uuid4())
        session["thread_id"] = thread_id
        logger.info("New conversation: thread_id=%s", thread_id)

    config = {"configurable": {"thread_id": thread_id}}

    if request.method == "GET":
        # Return full message history from checkpointer for page-reload restore
        try:
            state = AGENT.get_state(config)
            messages = [
                {"type": m.type, "content": m.content}
                for m in state.values.get("messages", [])
            ] if state and state.values else []
            return jsonify({
                "messages": messages,
                "thread_id": thread_id,
                "phase": state.values.get("phase", "idle") if state and state.values else "idle",
                "ui": state.values.get("ui_payload") if state and state.values else None,
            })
        except Exception:
            logger.exception("GET state failed thread=%s", thread_id)
            return jsonify({"messages": [], "thread_id": thread_id})

    # POST — invoke agent
    try:
        data = request.get_json(silent=True) or {}
        user_message = (data.get("user_input") or data.get("message") or "").strip()
        if not user_message:
            return jsonify({"error": "Empty message", "code": 400}), 400

        logger.info("Agent invoke | thread=%s | input=%r", thread_id, user_message[:80])

        result = AGENT.invoke(
            {"messages": [HumanMessage(content=user_message)]},
            config=config,
        )

        # Return full message list so the frontend can render the full history
        messages = [
            {"type": m.type, "content": m.content}
            for m in result.get("messages", [])
        ]

        return jsonify({
            "thread_id": thread_id,
            "messages": messages,
            "phase": result.get("phase", "idle"),
            "ui": result.get("ui_payload"),
            "selected_room": result.get("selected_room"),
        })

    except Exception as exc:
        logger.exception("Chat error | thread=%s", thread_id)
        # 4.5: structured error with retry flag so frontend can surface a retry button
        error_text = str(exc)
        if "quota" in error_text.lower() or "resourceexhausted" in error_text.lower():
            error_message = "Gemini quota is exhausted. Try again after the quota resets or switch to LLM_PROVIDER=fake for UI work."
            error_reason = "quota"
        elif "unauthenticated" in error_text.lower() or "invalid authentication" in error_text.lower():
            error_message = "Gemini authentication failed. Check GEMINI_API_KEY and restart Flask."
            error_reason = "authentication"
        else:
            error_message = "The booking request could not be completed. Please try again."
            error_reason = "server"
        status_code = 429 if error_reason == "quota" else 401 if error_reason == "authentication" else 500
        return jsonify({
            "error": error_message,
            "code": status_code,
            "reason": error_reason,
            "retry": True,
        }), status_code


@app.route("/reset")
@app.route("/api/reset", methods=["GET", "POST"])
def api_reset():
    """Clear thread_id so next message starts a fresh conversation."""
    old = session.pop("thread_id", None)
    logger.info("Reset conversation: thread=%s", old)
    if request.path == "/reset":
        return redirect(url_for("home"))
    return jsonify({"ok": True})


if __name__ == "__main__":
    host = os.getenv("HOST") or os.getenv("FLASK_HOST", "127.0.0.1")
    port = int(os.getenv("PORT") or os.getenv("FLASK_PORT", 5001))
    app.run(host=host, port=port, debug=False)
