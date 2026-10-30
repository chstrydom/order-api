from pathlib import Path

import psycopg


def initialise_database(database_url: str) -> None:
    schema = (Path(__file__).parent / "schema.sql").read_text()
    with psycopg.connect(database_url) as connection:
        connection.execute(schema)
