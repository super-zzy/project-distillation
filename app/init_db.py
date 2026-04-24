from __future__ import annotations

import os

from dotenv import load_dotenv

from . import create_app
from .db import db


def _create_database_if_missing() -> None:
    """
    Ensure MYSQL_DATABASE exists before SQLAlchemy connects to it.
    """
    import pymysql

    host = os.getenv("MYSQL_HOST", "127.0.0.1")
    port = int(os.getenv("MYSQL_PORT", "3306"))
    user = os.getenv("MYSQL_USER", "root")
    password = os.getenv("MYSQL_PASSWORD", "")
    database = os.getenv("MYSQL_DATABASE", "project_distillation")

    err: list[str] = []

    def _do() -> None:
        try:
            conn = pymysql.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                charset="utf8mb4",
                autocommit=True,
                connect_timeout=5,
                read_timeout=5,
                write_timeout=5,
            )
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        f"CREATE DATABASE IF NOT EXISTS `{database}` "
                        "DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE utf8mb4_unicode_ci"
                    )
            finally:
                conn.close()
        except Exception as e:  # noqa: BLE001
            err.append(str(e))

    import threading

    t = threading.Thread(target=_do, daemon=True)
    t.start()
    t.join(timeout=6)
    if t.is_alive():
        raise RuntimeError("Timeout connecting to MySQL to ensure database exists.")
    if err:
        raise RuntimeError(err[0])


def main() -> None:
    load_dotenv()
    print("init_db: env loaded")
    try:
        _create_database_if_missing()
        print("init_db: database ensured")
    except Exception as e:  # noqa: BLE001
        print(f"init_db: WARN could not ensure database exists: {e}")
    # init_db should not start background worker threads
    os.environ["DISABLE_WORKER"] = "1"
    app = create_app()
    with app.app_context():
        print("init_db: creating tables...")
        db.create_all()
        print("init_db: tables created")
        # Minimal migration for MySQL ENUM changes without Alembic.
        try:
            engine = db.get_engine()
            with engine.connect() as conn:
                conn.exec_driver_sql(
                    "ALTER TABLE tasks MODIFY status "
                    "ENUM('queued','running','paused','completed','failed','stopped') "
                    "NOT NULL"
                )
        except Exception:
            # ignore if already applied or table absent
            pass
        print("DB initialized.")


if __name__ == "__main__":
    main()

