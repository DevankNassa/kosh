import pytest

from kosh import db


@pytest.fixture()
def session():
    db.reset_engine()
    from kosh import models  # noqa: F401
    db.Base.metadata.create_all(db.get_engine())
    with db.session_scope() as s:
        yield s
