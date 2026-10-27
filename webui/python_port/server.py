"""Production server entry point."""

import os
from waitress import serve

from python_port.app import create_app


def main():
    app = create_app(start_scheduler=True)
    serve(app, host=os.getenv("BILI_PY_HOST", "127.0.0.1"),
          port=int(os.getenv("BILI_PY_PORT", "8080")), threads=8)


if __name__ == "__main__":
    main()
