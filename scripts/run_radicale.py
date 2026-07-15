"""Run the local development CalDAV server.

    uv run python scripts/run_radicale.py [--port 5232] [--storage ./data/radicale]

Then point any CalDAV client (Thunderbird, DAVx5, this project's
adapter) at http://127.0.0.1:5232 with any username/password.
Authentication is disabled: local development only.
"""

from __future__ import annotations

import argparse

from calendar_adapter.devserver import make_dev_server


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5232)
    parser.add_argument("--storage", default="./data/radicale")
    args = parser.parse_args()

    server = make_dev_server(args.storage, port=args.port)
    print(f"CalDAV dev server on http://127.0.0.1:{server.server_port} (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
