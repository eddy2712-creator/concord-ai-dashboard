from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

db = SQLAlchemy()
migrate = Migrate()


def create_app():
    app = Flask(__name__)
    app.config.from_object("config.Config")

    # Fix Railway's postgres:// URL (SQLAlchemy requires postgresql://)
    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if uri and uri.startswith("postgres://"):
        app.config["SQLALCHEMY_DATABASE_URI"] = uri.replace("postgres://", "postgresql://", 1)

    db.init_app(app)
    migrate.init_app(app, db)

    from app.api import api_bp
    from app.dashboard import dashboard_bp
    from app.billing import billing_bp
    from app.quickbooks import qb_bp

    app.register_blueprint(api_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(qb_bp)

    return app
