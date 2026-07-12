import os
import sys
import unittest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core import database as db
from naukri_agent.applier import run_naukri_auto_apply
from naukri_agent.session_manager import save_session

class TestMilestone12(unittest.TestCase):
    user_id = 7777

    @classmethod
    def setUpClass(cls):
        db.init_db()
        with db._connect() as conn:
            conn.execute("DELETE FROM users WHERE id = ?", (cls.user_id,))
            conn.execute(
                "INSERT INTO users (id, name, last_name, email, password_hash, submitted_at) VALUES (?, ?, ?, ?, ?, ?)",
                (cls.user_id, "Milestone", "Tester", "milestone@example.com", "hash", "2026-07-09T00:00:00")
            )
            conn.commit()
        
        # Seed mock session
        mock_cookies = [{"name": "naukri_session", "value": "test_session", "domain": "naukri.com"}]
        save_session(cls.user_id, mock_cookies)

    def setUp(self):
        # Clear existing applications and logs for the user
        with db._connect_jobs() as conn:
            conn.execute("DELETE FROM naukri_applications WHERE user_id = ?", (self.user_id,))
            conn.execute("DELETE FROM naukri_application_logs WHERE user_id = ?", (self.user_id,))
            conn.execute("DELETE FROM naukri_jobs")
            conn.commit()

    @patch("naukri_agent.applier.load_session")
    @patch("naukri_agent.applier.get_or_propose_answer")
    @patch("naukri_agent.applier.is_session_valid", new_callable=AsyncMock)
    @patch("naukri_agent.applier.async_playwright")
    def test_milestone_1_2_criteria(self, mock_playwright, mock_session_valid, mock_get_answer, mock_load_session):
        print("\n" + "=" * 80)
        print(" RUNNING MILESTONE 1.2 VALIDATION SCENARIO")
        print("=" * 80)

        # Mock sessions and answers
        mock_load_session.return_value = [{"name": "naukri_session", "value": "test_session", "domain": "naukri.com"}]
        mock_session_valid.return_value = True

        # Let's seed 5 jobs:
        # - Job 1-4: All screening questions have "approved" answers (should apply end-to-end autonomously).
        # - Job 5: Will fail navigation (to simulate failure).
        jobs = []
        for i in range(1, 6):
            job_id = f"job-m12-{i}"
            jobs.append({
                "job_id": job_id,
                "title": f"Engineer Role {i}",
                "company": "Tech Corp",
                "url": f"https://naukri.com/{job_id}",
                "relevance_percent": 90
            })
            # Seed as surfaced in DB
            db.add_naukri_application(self.user_id, job_id, status="surfaced")
        
        db.save_naukri_jobs(jobs)

        # Mock answers: Notice period (approved)
        def get_answer_side_effect(user_id, question):
            return "Immediate", "approved"
        mock_get_answer.side_effect = get_answer_side_effect

        # Mock Playwright classes and methods
        mock_page = AsyncMock()
        
        # Simulate navigation error only for Job 5
        async def mock_goto(url, *args, **kwargs):
            if "job-m12-5" in url:
                raise Exception("Navigation Timeout Error")
            return None
        mock_page.goto.side_effect = mock_goto

        # Mock buttons and locators
        mock_apply_btn = MagicMock()
        mock_apply_btn.first = MagicMock()
        mock_apply_btn.first.count = AsyncMock(return_value=1)
        mock_apply_btn.first.inner_text = AsyncMock(return_value="Apply")
        mock_apply_btn.first.click = AsyncMock()

        mock_page.locator = MagicMock()
        def page_locator_side_effect(selector):
            locator_mock = MagicMock()
            locator_mock.first = MagicMock()
            if "button.apply-button" in selector:
                return mock_apply_btn
            locator_mock.first.count = AsyncMock(return_value=0)
            locator_mock.count = AsyncMock(return_value=0)
            return locator_mock
        mock_page.locator.side_effect = page_locator_side_effect

        mock_context = AsyncMock()
        mock_context.new_page.return_value = mock_page
        mock_browser = AsyncMock()
        mock_browser.new_context.return_value = mock_context

        mock_playwright_instance = MagicMock()
        mock_playwright_instance.chromium.launch = AsyncMock(return_value=mock_browser)
        async def enter_mock(*args, **kwargs):
            return mock_playwright_instance
        mock_playwright.return_value.__aenter__ = enter_mock

        # --- EXECUTE AUTO APPLY CYCLE ---
        # Run auto apply. We will execute 3 cycles to make sure Job 5 reaches terminal failure (3 retries).
        loop = asyncio.get_event_loop()
        
        print("\n--- Running Cycle 1 ---")
        res1 = loop.run_until_complete(run_naukri_auto_apply(self.user_id, max_daily_apps=10))
        
        print("\n--- Running Cycle 2 ---")
        res2 = loop.run_until_complete(run_naukri_auto_apply(self.user_id, max_daily_apps=10))
        
        print("\n--- Running Cycle 3 ---")
        res3 = loop.run_until_complete(run_naukri_auto_apply(self.user_id, max_daily_apps=10))

        # --- VALIDATE ACCEPTANCE CRITERIA ---
        print("\n" + "-" * 50)
        print(" VALIDATING CRITERIA...")
        print("-" * 50)

        # Retrieve all final applications for the user
        apps = db.get_naukri_applications(self.user_id)
        app_statuses = {a["job_id"]: a["status"] for a in apps}
        
        # 1. Verification of Criterion 1: At least 80% applied autonomously without human input
        # Job 1-4 successfully applied (4/5 = 80%)
        applied_jobs = [jid for jid, status in app_statuses.items() if status == "applied"]
        apply_rate = len(applied_jobs) / 5.0
        
        print(f"Criterion 1: Autonomous execution rate = {apply_rate * 100:.1f}% (Target >= 80%)")
        self.assertGreaterEqual(apply_rate, 0.80)
        self.assertIn("job-m12-1", applied_jobs)
        self.assertIn("job-m12-2", applied_jobs)
        self.assertIn("job-m12-3", applied_jobs)
        self.assertIn("job-m12-4", applied_jobs)

        # 2. Verification of Criterion 2: 100% of applications have a screenshot and status stored
        # Get all attempt logs
        all_logs = []
        for i in range(1, 6):
            logs = db.get_naukri_application_logs(self.user_id, f"job-m12-{i}")
            all_logs.extend(logs)
            
        print(f"Total application attempt logs recorded: {len(all_logs)}")
        self.assertGreater(len(all_logs), 0)
        
        # Verify every log has status, error details (if failed/retried), and screenshot path
        for log in all_logs:
            self.assertIn(log["status"], ("applied", "failed", "retrying"))
            self.assertIsNotNone(log["screenshot_path"])
            self.assertIsNotNone(log["attempted_at"])
            
        print("Criterion 2: 100% of attempts have status, attempt number, and screenshot paths. [OK]")

        # 3. Verification of Criterion 3: Failures surface in the dashboard within 5 minutes
        # Simulate querying the Flask REST API endpoint directly
        from core.app import app
        with app.test_client() as client:
            r = client.get(f"/api/users/{self.user_id}/naukri-failures")
            self.assertEqual(r.status_code, 200)
            data = r.get_json()
            self.assertTrue(data["ok"])
            failures = data["failures"]
            
            # Job 5 must be in the failure list with a clear reason and screenshot path
            self.assertEqual(len(failures), 1)
            fail_entry = failures[0]
            self.assertEqual(fail_entry["job_id"], "job-m12-5")
            self.assertEqual(fail_entry["status"], "failed")
            self.assertEqual(fail_entry["last_error"], "Navigation Timeout Error")
            self.assertIsNotNone(fail_entry["screenshot_path"])
            
        print("Criterion 3: Terminal failures successfully surfaced via API immediately with clear error reason. [OK]")
        print("=" * 80)

if __name__ == "__main__":
    unittest.main()
