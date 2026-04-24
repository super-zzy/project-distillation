from flask import Flask
from dotenv import load_dotenv

from .db import db
from .pages import pages
from .routes import api
from .utils import init_logging
from .worker import ensure_worker_started


def create_app() -> Flask:
    load_dotenv()
    init_logging()

    app = Flask(__name__)
    app.config["SECRET_KEY"] = app.config.get("SECRET_KEY", "dev-secret")

    mysql_user = _env("MYSQL_USER", "root")
    mysql_password = _env("MYSQL_PASSWORD", "")
    mysql_host = _env("MYSQL_HOST", "127.0.0.1")
    mysql_port = _env("MYSQL_PORT", "3306")
    mysql_db = _env("MYSQL_DATABASE", "project_distillation")

    app.config["SQLALCHEMY_DATABASE_URI"] = (
        f"mysql+pymysql://{mysql_user}:{mysql_password}@{mysql_host}:{mysql_port}/{mysql_db}"
        "?charset=utf8mb4"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"connect_args": {"connect_timeout": 5}}

    db.init_app(app)

    app.register_blueprint(pages)
    app.register_blueprint(api, url_prefix="/api")

    # Start background worker thread (unless disabled via env).
    ensure_worker_started(app)

    return app


def _env(key: str, default: str) -> str:
    import os

    val = os.getenv(key)
    return val if val is not None and val != "" else default
