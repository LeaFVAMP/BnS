from __future__ import annotations

import json
from pathlib import Path
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_bcrypt import Bcrypt
from sqlalchemy import MetaData

convention = {
    "ix":  "ix_%(column_0_label)s",
    "uq":  "uq_%(table_name)s_%(column_0_name)s",
    "ck":  "ck_%(table_name)s_%(constraint_name)s",
    "fk":  "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk":  "pk_%(table_name)s",
}
db = SQLAlchemy(metadata=MetaData(naming_convention=convention))
migrate = Migrate()
login_manager = LoginManager()
bcrypt = Bcrypt()

def create_app() -> Flask:
    app = Flask(__name__)
    # Config
    try:
        app.config.from_object("config.Config")
    except Exception:
        base_dir = Path(__file__).resolve().parent.parent
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{base_dir / 'app.db'}"
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        app.config["SECRET_KEY"] = "dev-secret"

    # Extensiones
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    bcrypt.init_app(app)

    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "warning"

    # Modelos para Alembic
    from app import models  # noqa: F401

    from app.models import User

    @login_manager.user_loader
    def load_user(user_id: str):
        try:
            return db.session.get(User, int(user_id))
        except Exception:
            return None

    # Filtro jinja: |loads
    @app.template_filter("loads")
    def _json_loads_filter(s):
        try:
            return json.loads(s) if s else []
        except Exception:
            return []

    # Blueprints
    from app.routes.auth import bp as auth_bp
    from app.routes.ventas import bp as ventas_bp
    from app.routes.pricing import bp as pricing_bp

    app.register_blueprint(auth_bp)          # asumiendo que auth_bp ya trae su url_prefix (p.ej. "/auth")
    app.register_blueprint(ventas_bp)        # si ventas_bp NO tiene url_prefix, cámbialo a: url_prefix="/ventas"
    app.register_blueprint(pricing_bp)       # NO pasar url_prefix aquí: ya está en el blueprint

    
    # CLI
    from app.cli import register_cli
    register_cli(app)

    return app
