from contextlib import closing
import sqlite3
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import app
from init_db import initialize_database
from streamlit.testing.v1 import AppTest


class ApplicationDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "placements.db"
        self.database_patch = patch.object(app, "DATABASE_PATH", self.database_path)
        self.database_patch.start()
        initialize_database(self.database_path)

    def tearDown(self):
        self.database_patch.stop()
        self.temp_dir.cleanup()

    def test_migrates_existing_database_without_losing_rows(self):
        legacy_path = Path(self.temp_dir.name) / "legacy.db"
        with closing(sqlite3.connect(legacy_path)) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE applications (
                        application_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        company_name TEXT NOT NULL,
                        job_role TEXT NOT NULL,
                        application_date TEXT,
                        status TEXT
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO applications (company_name, job_role, status)
                    VALUES ('Example Co', 'Engineer', 'Applied')
                    """
                )

        initialize_database(legacy_path)
        initialize_database(legacy_path)

        with closing(sqlite3.connect(legacy_path)) as connection:
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(applications)")
            }
            row = connection.execute(
                "SELECT company_name, interview_date FROM applications"
            ).fetchone()

        self.assertIn("interview_date", columns)
        self.assertEqual(row, ("Example Co", None))

    def test_add_update_delete_and_upcoming_interviews(self):
        app.add_application(
            "Acme", "Developer", "2026-11-01", "Interview Scheduled", "2026-11-20"
        )
        app.add_application(
            "Beta", "Analyst", "2026-11-02", "Applied", None
        )
        app.add_application(
            "Past Co", "Engineer", "2026-10-01", "Interview Scheduled", "2026-11-01"
        )

        interviews = app.get_upcoming_interviews(date(2026, 11, 12))
        self.assertEqual([row["company_name"] for row in interviews], ["Acme"])

        applications, _, _ = app.get_applications()
        acme_id = next(
            row["application_id"] for row in applications if row["company_name"] == "Acme"
        )
        beta_id = next(
            row["application_id"] for row in applications if row["company_name"] == "Beta"
        )

        app.update_application_status(beta_id, "Shortlisted")
        applications, _, _ = app.get_applications()
        beta = next(row for row in applications if row["application_id"] == beta_id)
        self.assertEqual(beta["status"], "Shortlisted")

        app.delete_application(acme_id)
        applications, _, _ = app.get_applications()
        self.assertNotIn(acme_id, [row["application_id"] for row in applications])

    def test_export_contains_filtered_records_and_interview_date(self):
        app.add_application(
            "Acme", "Developer", "2026-11-01", "Interview Scheduled", "2026-11-20"
        )
        applications, _, _ = app.get_applications()
        selected = app.filter_applications(
            applications, "acme", "Interview Scheduled"
        )
        csv_data = app.applications_to_csv(selected)

        self.assertIn("company_name", csv_data)
        self.assertIn("interview_date", csv_data)
        self.assertIn("Acme", csv_data)
        self.assertIn("2026-11-20", csv_data)

    def test_company_and_status_filters(self):
        app.add_application("Acme", "Developer", "2026-11-01", "Applied", None)
        app.add_application("Acme Labs", "Engineer", "2026-11-02", "Shortlisted", None)
        app.add_application("Beta", "Analyst", "2026-11-03", "Applied", None)
        applications, _, _ = app.get_applications()

        filtered = app.filter_applications(applications, "ACME", "Applied")

        self.assertEqual([row["company_name"] for row in filtered], ["Acme"])


class ApplicationUiTests(unittest.TestCase):
    def test_add_filter_update_upcoming_and_confirmed_delete(self):
        source_dir = Path(__file__).parent
        with tempfile.TemporaryDirectory() as temp_dir:
            app_path = Path(temp_dir) / "app.py"
            shutil.copy2(source_dir / "app.py", app_path)
            shutil.copy2(source_dir / "init_db.py", Path(temp_dir) / "init_db.py")

            streamlit_app = AppTest.from_file(str(app_path)).run(timeout=20)
            self.assertFalse(streamlit_app.exception)

            streamlit_app.text_input[0].set_value("Acme")
            streamlit_app.text_input[1].set_value("Engineer")
            streamlit_app.selectbox[0].select("Interview Scheduled")
            streamlit_app.date_input[1].set_value(date(2026, 11, 20))
            streamlit_app.button[0].click()
            streamlit_app.run(timeout=20)
            self.assertFalse(streamlit_app.exception)
            self.assertIn("Acme", str(streamlit_app.dataframe[0].value))
            self.assertIn("2026-11-20", str(streamlit_app.dataframe[0].value))
            self.assertIn(
                "Download filtered applications as CSV",
                [button.label for button in streamlit_app.get("download_button")],
            )

            search = next(
                widget
                for widget in streamlit_app.text_input
                if widget.label == "Search by company name"
            )
            search.set_value("Not found")
            streamlit_app.run(timeout=20)
            self.assertTrue(streamlit_app.dataframe[1].value.empty)

            search = next(
                widget
                for widget in streamlit_app.text_input
                if widget.label == "Search by company name"
            )
            search.set_value("Acme")
            streamlit_app.run(timeout=20)
            status_filter = next(
                widget
                for widget in streamlit_app.selectbox
                if widget.label == "Filter by status"
            )
            status_filter.select("Interview Scheduled")
            streamlit_app.run(timeout=20)
            self.assertIn("Acme", str(streamlit_app.dataframe[1].value))
            status_filter = next(
                widget
                for widget in streamlit_app.selectbox
                if widget.label == "Filter by status"
            )
            status_filter.select("All statuses")
            streamlit_app.run(timeout=20)

            status_editor = next(
                widget
                for widget in streamlit_app.selectbox
                if widget.key == "status_1"
            )
            status_editor.select("Selected")
            next(
                button
                for button in streamlit_app.button
                if button.key == "update_1"
            ).click()
            streamlit_app.run(timeout=20)
            self.assertFalse(streamlit_app.exception)

            delete_button = next(
                button
                for button in streamlit_app.button
                if button.key == "delete_1"
            )
            self.assertTrue(delete_button.disabled)
            next(
                checkbox
                for checkbox in streamlit_app.checkbox
                if checkbox.key == "confirm_delete_1"
            ).check()
            streamlit_app.run(timeout=20)
            next(
                button
                for button in streamlit_app.button
                if button.key == "delete_1"
            ).click()
            streamlit_app.run(timeout=20)
            self.assertFalse(streamlit_app.exception)

            with closing(sqlite3.connect(Path(temp_dir) / "placements.db")) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM applications"
                    ).fetchone()[0],
                    0,
                )


if __name__ == "__main__":
    unittest.main()
