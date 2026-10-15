"""Key/value settings stored as JSON in the settings table."""

import json
from typing import Any

from sqlalchemy.orm import Session

from .models import Setting

DEFAULTS: dict[str, Any] = {
    "distributor_name": "Your Name",
    "arn": "ARN-000000",
    "firm_name": "",
}


def get(session: Session, key: str, default: Any = None) -> Any:
    row = session.get(Setting, key)
    if row is None or row.value is None:
        return DEFAULTS.get(key, default)
    return json.loads(row.value)


def put(session: Session, key: str, value: Any) -> None:
    row = session.get(Setting, key)
    data = json.dumps(value, default=str)
    if row is None:
        session.add(Setting(key=key, value=data))
    else:
        row.value = data
