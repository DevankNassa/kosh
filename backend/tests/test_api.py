from datetime import date

from fastapi.testclient import TestClient

from kosh.api.app import app


def test_create_event_accepts_a_date(session):
    """Regression test: EventIn.date used to be declared as `Optional[date]`
    with a default of None, which pydantic v2 silently resolves to
    `Optional[NoneType]` because the field is named the same as its type and
    the default value shadows it in the class namespace — every POST with a
    real date then failed validation. Fixed by qualifying as datetime.date."""
    client = TestClient(app)
    today = date.today().isoformat()
    r = client.post("/api/events", json={"title": "Test event", "kind": "market", "date": today, "tags": {}})
    assert r.status_code == 200, r.text
    assert r.json()["date"] == today
