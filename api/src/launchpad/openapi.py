"""Dump the OpenAPI schema: `python -m launchpad.openapi > ../web/openapi.json`."""

from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("JWT_SECRET", "x" * 32)


def main() -> None:
    from launchpad.main import app

    # Write bytes so Windows doesn't translate to CRLF; CI diffs this file byte-for-byte.
    text = json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
    sys.stdout.buffer.write(text.encode())


if __name__ == "__main__":
    main()
