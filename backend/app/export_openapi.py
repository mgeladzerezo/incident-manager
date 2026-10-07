"""Write the OpenAPI document. The frontend generates its API types from this file.

python -m app.export_openapi ../frontend/openapi.json
"""

import json
import sys
from pathlib import Path

from app.config import Settings
from app.db import make_engine, make_session_factory
from app.main import create_app


def main(target: str) -> None:
    app = create_app(
        settings=Settings(),
        session_factory=make_session_factory(make_engine("sqlite://")),
        notifiers=[],
    )
    document = json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
    # Fixed line endings so the file is identical no matter which OS generated it.
    Path(target).write_text(document, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main(sys.argv[1])
