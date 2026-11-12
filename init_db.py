from contextlib import closing
from pathlib import Path
import sqlite3


DATABASE_PATH = Path(__file__).with_name("placements.db")


def initialize_database(database_path=DATABASE_PATH):
    """Create the applications table and migrate older databases in place."""
    with closing(sqlite3.connect(database_path)) as connection:
        with connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS applications (
                    application_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_name TEXT NOT NULL,
                    job_role TEXT NOT NULL,
                    application_date TEXT,
                    status TEXT,
                    interview_date TEXT
                )
                """
            )

            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(applications)")
            }
            if "interview_date" not in columns:
                connection.execute(
                    "ALTER TABLE applications ADD COLUMN interview_date TEXT"
                )


if __name__ == "__main__":
    initialize_database()
    print("Database and applications table created successfully.")
