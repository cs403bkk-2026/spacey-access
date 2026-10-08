import os

import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://access:access@localhost:5434/access"
)


def get_connection(database_url: str = DATABASE_URL) -> psycopg.Connection:
    try:
        return psycopg.connect(database_url, row_factory=dict_row, autocommit=True)
    except psycopg.OperationalError as error:
        # A raw psycopg traceback is the first thing a new contributor sees
        # if Postgres isn't running yet - fail fast with a clear pointer.
        raise SystemExit(
            f"Could not connect to the database at DATABASE_URL={database_url!r}\n"
            f"{error}\n"
            "Is Postgres running? Try: docker compose up db -d"
        ) from None
