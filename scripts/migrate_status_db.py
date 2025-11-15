"""Create the SQLite tables for status snapshots."""

from __future__ import annotations

import argparse

from config.settings import DATABASE_URL
from src.db.base import Base, create_sqlalchemy_engine
from src.db import models  # noqa: F401


def migrate(database_url: str) -> None:
    engine = create_sqlalchemy_engine(database_url)
    Base.metadata.create_all(bind=engine)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create database tables for status snapshots.")
    parser.add_argument(
        "--database-url",
        dest="database_url",
        default=DATABASE_URL,
        help="SQLAlchemy database URL (default: %(default)s)",
    )
    args = parser.parse_args()
    migrate(args.database_url)
    print(f"Database migrated at {args.database_url}")


if __name__ == "__main__":
    main()

