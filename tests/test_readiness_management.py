import os
import tempfile
import unittest
from unittest.mock import patch

from app.main import create_app, get_db, month_data


class ReadinessManagementTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        with patch.dict(os.environ, {"DATABASE_PATH": os.path.join(self.temp.name, "test.sqlite")}):
            self.app = create_app()
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()
        with self.app.app_context():
            db = get_db()
            self.user_id = db.execute("SELECT id FROM users LIMIT 1").fetchone()[0]
            self.type_id = db.execute(
                "INSERT INTO readiness_types (name, display_name) VALUES ('Empty profile', 'Empty')"
            ).lastrowid
            db.commit()
        with self.client.session_transaction() as session:
            session["user_id"] = self.user_id

    def add_readiness(self, type_id=None, user_id=None, start='2026-09-01', end='2026-09-02'):
        with self.app.app_context():
            db = get_db()
            item_id = db.execute(
                """INSERT INTO readiness
                   (user_id, readiness_type_id, start_date, end_date, kind, start_time, end_time, hours_per_day)
                   VALUES (?, ?, ?, ?, 'Legacy test', '06:00', '18:00', 12)""",
                (user_id or self.user_id, type_id, start, end),
            ).lastrowid
            db.commit()
            return item_id

    def test_legacy_and_empty_profile_are_visible_and_deletable(self):
        legacy = self.add_readiness()
        empty = self.add_readiness(self.type_id)
        with self.app.app_context():
            data = month_data(self.user_id, 2026, 9)
            self.assertEqual(data['readiness'], [])
            self.assertEqual({r['id'] for r in data['readiness_records']}, {legacy, empty})
        response = self.client.get('/?year=2026&month=9')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Keine Bereitschaftsart zugeordnet', response.get_data(as_text=True))
        self.assertIn('Keine Zeiten im Monat hinterlegt', response.get_data(as_text=True))
        for item_id in (legacy, empty):
            self.assertIn(f'/readiness/{item_id}/delete', response.get_data(as_text=True))
            deleted = self.client.post(
                f'/readiness/{item_id}/delete', data={'year': '2026', 'month': '9'}, follow_redirects=True
            )
            self.assertEqual(deleted.status_code, 200)
            self.assertNotIn(f'/readiness/{item_id}/delete', deleted.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(month_data(self.user_id, 2026, 9)['readiness_records'], [])

    def test_cross_month_record_appears_once_and_other_users_are_protected(self):
        own = self.add_readiness(start='2026-08-30', end='2026-10-02')
        with self.app.app_context():
            db = get_db()
            other_user = db.execute(
                "INSERT INTO users (username, password_hash) VALUES ('other', 'unused')"
            ).lastrowid
            db.commit()
        foreign = self.add_readiness(user_id=other_user)
        response = self.client.get('/?year=2026&month=9')
        html = response.get_data(as_text=True)
        self.assertEqual(html.count(f'/readiness/{own}/delete'), 1)
        self.assertNotIn(f'/readiness/{foreign}/delete', html)
        self.client.post(f'/readiness/{foreign}/delete', data={'year': '2026', 'month': '9'})
        with self.app.app_context():
            self.assertIsNotNone(get_db().execute('SELECT id FROM readiness WHERE id = ?', (foreign,)).fetchone())

    def test_normal_profile_keeps_daily_hours_and_one_delete_button(self):
        with self.app.app_context():
            db = get_db()
            db.execute(
                "UPDATE readiness_types SET weekday_start = '06:00', weekday_end = '18:00' WHERE id = ?",
                (self.type_id,),
            )
            db.commit()
        item_id = self.add_readiness(self.type_id)
        with self.app.app_context():
            data = month_data(self.user_id, 2026, 9)
            self.assertEqual(len(data['readiness']), 2)
            self.assertEqual(data['sum_soll'], 24)
            self.assertEqual(len(data['readiness_records']), 1)
            self.assertTrue(data['readiness_records'][0]['has_times'])
        response = self.client.get('/?year=2026&month=9')
        self.assertEqual(response.get_data(as_text=True).count(f'/readiness/{item_id}/delete'), 1)


if __name__ == '__main__':
    unittest.main()
