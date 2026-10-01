"""Dump the OpenAPI schema: `python -m launchpad.openapi > ../web/openapi.json`."""

from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("JWT_SECRET", "x" * 32)


def main() -> None:
    from launchpad.main import app

    json.dump(app.openapi(), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
