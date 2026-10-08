import os

import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://access:access@localhost:5434/access"
)


def get_connection(database_url: str = DATABASE_URL) -> psycopg.Connection:
    try:
        return psycopg.connect(database_url, row_factory=dict_row, autocommit=True)
    except psycopg.OperationalError:
        # A raw psycopg traceback is the first thing a new contributor sees
        # if Postgres isn't running yet - fail fast with a clear pointer.
        raise SystemExit(
            "Could not connect to the database. Check DATABASE_URL and database availability."
        ) from None
