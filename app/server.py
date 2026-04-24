from __future__ import annotations

import os

from . import create_app


def main() -> None:
    app = create_app()
    host = os.getenv("APP_HOST", "127.0.0.1")
    port = int(os.getenv("APP_PORT", "5000"))
    app.run(host=host, port=port, threaded=True)


if __name__ == "__main__":
    main()

