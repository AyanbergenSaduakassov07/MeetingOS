"""A fresh install must accept its first upload without any manual setup."""

from __future__ import annotations

from backend import database
from backend.database.models import Organization


def test_fresh_database_gets_one_default_org(db):
    database.ensure_default_org()
    database.ensure_default_org()  # restarts must not add more

    assert db.query(Organization).count() == 1


def test_existing_orgs_are_left_alone(db):
    db.add_all([Organization(name="A", slug="a"), Organization(name="B", slug="b")])
    db.commit()

    database.ensure_default_org()

    assert {o.slug for o in db.query(Organization).all()} == {"a", "b"}
