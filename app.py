"""
F&O Risk Intelligence Web App - Main Application Entry Point
============================================================
Flask application that serves the risk intelligence dashboard for
active derivatives traders. Provides REST APIs consumed by the frontend.

Author: F&O Risk Intelligence Team
"""

from flask import Flask, jsonify, request, render_template, send_from_directory
import os
import logging

from backend.routes.portfolio import portfolio_bp
from backend.routes.analytics import analytics_bp
from backend.routes.stress import stress_bp
from backend.routes.market import market_bp
from backend.routes.ai_summary import ai_bp

# ---------------------------------------------------------------------------
# App Factory
# ---------------------------------------------------------------------------

def create_app():
    """Create and configure the Flask application."""
    app = Flask(
        __name__,
        template_folder="frontend/templates",
        static_folder="frontend/static"
    )

    # Basic config
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-fo-risk"),
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,   # 5 MB max upload
        JSON_SORT_KEYS=False,
    )

    # Logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s"
    )

    # Register blueprints
    app.register_blueprint(portfolio_bp, url_prefix="/api/portfolio")
    app.register_blueprint(analytics_bp, url_prefix="/api/analytics")
    app.register_blueprint(stress_bp,    url_prefix="/api/stress")
    app.register_blueprint(market_bp,    url_prefix="/api/market")
    app.register_blueprint(ai_bp,        url_prefix="/api/ai")

    # ---------------------------------------------------------------------------
    # Root route — serves the SPA shell
    # ---------------------------------------------------------------------------
    @app.route("/")
    def index():
        return render_template("index.html")

    # ---------------------------------------------------------------------------
    # Health check
    # ---------------------------------------------------------------------------
    @app.route("/health")
    def health():
        return jsonify({"status": "ok", "service": "fo-risk-intelligence"})

    return app


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------
app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
