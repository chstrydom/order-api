from pathlib import Path

import psycopg

SCHEMA_FILE = Path(__file__).with_name("schema.sql")


def initialise_database(database_url: str) -> None:
    schema = SCHEMA_FILE.read_text(encoding="utf-8")

    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(schema)
