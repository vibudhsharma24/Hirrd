import os
import sys
import unittest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone
import json

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core import database as db
from naukri_agent.applier import run_naukri_auto_apply
from naukri_agent.session_manager import save_session

def print_section(title):
    print("\n" + "=" * 80)
    print(f" {title.upper()}")
    print("=" * 80)

class TestApplier(unittest.TestCase):
    user_id = 8888  # Test user ID

    @classmethod
    def setUpClass(cls):
        db.init_db()
        
        # Register user in DB to satisfy foreign keys
        with db._connect() as conn:
            conn.execute("DELETE FROM users WHERE id = ?", (cls.user_id,))
            conn.execute(
                "INSERT INTO users (id, name, last_name, email, password_hash, submitted_at) VALUES (?, ?, ?, ?, ?, ?)",
                (cls.user_id, "Test", "Candidate", "applier_test@example.com", "mock_hash", "2026-07-07T00:00:00")
            )
            conn.commit()
            
        # Save a mock session to satisfy SESSIONS load check
        mock_cookies = [{"name": "naukri_session", "value": "active_session", "domain": "naukri.com"}]
        save_session(cls.user_id, mock_cookies)

    def setUp(self):
        # Clean database state
        with db._connect_jobs() as conn:
            conn.execute("DELETE FROM naukri_applications WHERE user_id = ?", (self.user_id,))
            conn.execute("DELETE FROM naukri_application_logs WHERE user_id = ?", (self.user_id,))
            conn.execute("DELETE FROM naukri_jobs")
            conn.commit()

    @patch("naukri_agent.applier.is_session_valid", new_callable=AsyncMock)
    @patch("naukri_agent.applier.async_playwright")
    def test_01_daily_throttling(self, mock_playwright, mock_session_valid):
        print_section("Test 1: Daily Throttling Limits")
        
        # 1. Seed 5 already applied applications today
        today_str = datetime.now().strftime("%Y-%m-%d")
        for i in range(5):
            db.add_naukri_application(self.user_id, f"job-today-{i}", status="applied")
            
        # Override applied_at timestamps to match today's date format
        with db._connect_jobs() as conn:
            conn.execute(
                "UPDATE naukri_applications SET applied_at = ? WHERE user_id = ?",
                (f"{today_str}T12:00:00", self.user_id)
            )
            conn.commit()
            
        # Run auto apply with limit = 5
        # It should hit throttling immediately without launching playwright
        loop = asyncio.get_event_loop()
        res = loop.run_until_complete(run_naukri_auto_apply(self.user_id, max_daily_apps=5))
        
        self.assertTrue(res["success"])
        self.assertIn("throttling limit reached", res["message"].lower())
        self.assertEqual(res["applied_count"], 0)
        self.assertFalse(mock_playwright.called)
        print("[OK] Daily throttling limit correctly prevents extra runs.")

    @patch("naukri_agent.applier.load_session")
    @patch("naukri_agent.applier.get_or_propose_answer")
    @patch("naukri_agent.applier.is_session_valid", new_callable=AsyncMock)
    @patch("naukri_agent.applier.async_playwright")
    def test_02_auto_apply_flow(self, mock_playwright, mock_session_valid, mock_get_answer, mock_load_session):
        print_section("Test 2: Auto-Apply Flow with Mocks")
        
        # Mock load_session
        mock_load_session.return_value = [{"name": "naukri_session", "value": "active_session", "domain": "naukri.com"}]
        
        # Set up mock session validity
        mock_session_valid.return_value = True
        
        # Mock answers: Notice period is approved, Relocate is pending_review
        def get_answer_side_effect(user_id, question):
            if "notice" in question.lower():
                return "Immediate", "approved"
            return "Yes, willing to relocate", "pending_review"
        mock_get_answer.side_effect = get_answer_side_effect
        
        # Seed 2 mock surfaced jobs in database
        job1 = {
            "job_id": "job-approved-1",
            "title": "Backend Python Developer",
            "company": "TechCorp",
            "url": "https://naukri.com/job-approved-1",
            "relevance_percent": 85
        }
        job2 = {
            "job_id": "job-pending-2",
            "title": "Software Engineer",
            "company": "InnoSoft",
            "url": "https://naukri.com/job-pending-2",
            "relevance_percent": 75
        }
        db.save_naukri_jobs([job1, job2])
        db.add_naukri_application(self.user_id, "job-approved-1", status="surfaced", tailored_resume_path="/resumes/gen1.pdf")
        db.add_naukri_application(self.user_id, "job-pending-2", status="surfaced", tailored_resume_path="/resumes/gen2.pdf")
        
        # Mock Playwright classes and methods
        mock_page = AsyncMock()
        
        # Mock locator counts for already applied checks (0)
        mock_already_applied = MagicMock()
        mock_already_applied.first = MagicMock()
        mock_already_applied.first.count = AsyncMock(return_value=0)
        
        # Mock Apply button (count 1, inner_text "Apply")
        mock_apply_btn = MagicMock()
        mock_apply_btn.first = MagicMock()
        mock_apply_btn.first.count = AsyncMock(return_value=1)
        mock_apply_btn.first.inner_text = AsyncMock(return_value="Apply")
        mock_apply_btn.first.click = AsyncMock()
        
        # Page locator mocking using regular MagicMock
        mock_page.locator = MagicMock()
        
        def page_locator_side_effect(selector):
            locator_mock = MagicMock()
            locator_mock.first = MagicMock()
            
            if "button.applied" in selector or "already-applied" in selector:
                locator_mock.first.count = AsyncMock(return_value=0)
                return locator_mock
            elif "button.apply-button" in selector:
                return mock_apply_btn
            elif "question" in selector or "chatbot-message" in selector:
                # We need to distinguish between approved and pending_review jobs
                current_url = mock_page.goto.call_args[0][0]
                locator_mock.count = AsyncMock(return_value=1)
                
                nth_mock = MagicMock()
                if "job-approved-1" in current_url:
                    nth_mock.inner_text = AsyncMock(return_value="What is your notice period?")
                else:
                    nth_mock.inner_text = AsyncMock(return_value="Will you relocate?")
                
                # Input elements inside nth_mock
                input_mock = MagicMock()
                input_mock.first = MagicMock()
                input_mock.first.count = AsyncMock(return_value=1)
                input_mock.first.fill = AsyncMock()
                input_mock.first.select_option = AsyncMock()
                input_mock.first.click = AsyncMock()
                
                nth_mock.locator = MagicMock(return_value=input_mock)
                locator_mock.nth = MagicMock(return_value=nth_mock)
                return locator_mock
            else:
                locator_mock.first.count = AsyncMock(return_value=0)
                locator_mock.count = AsyncMock(return_value=0)
                return locator_mock
                
        mock_page.locator.side_effect = page_locator_side_effect
        
        mock_context = AsyncMock()
        mock_context.new_page.return_value = mock_page
        
        mock_browser = AsyncMock()
        mock_browser.new_context.return_value = mock_context
        
        # Context manager mock setup
        mock_playwright_instance = MagicMock()
        mock_playwright_instance.chromium.launch = AsyncMock(return_value=mock_browser)
        
        async def enter_mock(*args, **kwargs):
            return mock_playwright_instance
            
        mock_playwright.return_value.__aenter__ = enter_mock
        
        # Run auto apply
        loop = asyncio.get_event_loop()
        res = loop.run_until_complete(run_naukri_auto_apply(self.user_id, max_daily_apps=5))
        
        self.assertTrue(res["success"])
        self.assertEqual(res["applied_count"], 1) # job-approved-1 succeeds
        self.assertEqual(res["flagged_count"], 1) # job-pending-2 gets flagged
        
        # Verify DB updates
        apps = db.get_naukri_applications(self.user_id)
        app_map = {a["job_id"]: a["status"] for a in apps}
        
        self.assertEqual(app_map["job-approved-1"], "applied")
        self.assertEqual(app_map["job-pending-2"], "pending_review")
        
        # Verify page interactions
        self.assertTrue(mock_page.screenshot.called) # Took screenshot for pending_review
        print("[OK] Auto-apply correctly submits approved forms and flags review-pending questions.")

    @patch("naukri_agent.applier.load_session")
    @patch("naukri_agent.applier.is_session_valid", new_callable=AsyncMock)
    @patch("naukri_agent.applier.async_playwright")
    def test_03_flask_endpoint(self, mock_playwright, mock_session_valid, mock_load_session):
        print_section("Test 3: Flask API Auto-Apply Trigger Endpoint")
        from core.app import app
        
        # Mock load_session
        mock_load_session.return_value = [{"name": "naukri_session", "value": "active_session", "domain": "naukri.com"}]
        
        # Mock session to bypass playwright execution
        mock_session_valid.return_value = True
        
        # Mock browser to prevent actual Playwright instantiation
        mock_browser = AsyncMock()
        mock_context = AsyncMock()
        mock_page = AsyncMock()
        mock_context.new_page.return_value = mock_page
        mock_browser.new_context.return_value = mock_context
        
        mock_playwright_instance = MagicMock()
        mock_playwright_instance.chromium.launch = AsyncMock(return_value=mock_browser)
        
        async def enter_mock(*args, **kwargs):
            return mock_playwright_instance
        mock_playwright.return_value.__aenter__ = enter_mock
        
        # Seed 1 surfaced application
        db.add_naukri_application(self.user_id, "job-flask-1", status="surfaced")
        
        with app.test_client() as client:
            payload = {"max_daily_apps": 2}
            r = client.post(f"/api/users/{self.user_id}/naukri-apply", json=payload)
            self.assertEqual(r.status_code, 200)
            data = r.get_json()
            self.assertTrue(data["ok"])
            self.assertIn("result", data)
            
        print("[OK] Flask API auto-apply trigger endpoint works.")

    @patch("naukri_agent.applier.load_session")
    @patch("naukri_agent.applier.is_session_valid", new_callable=AsyncMock)
    @patch("naukri_agent.applier.async_playwright")
    def test_04_retry_and_terminal_failure(self, mock_playwright, mock_session_valid, mock_load_session):
        print_section("Test 4: Retry Logic & Terminal Failure Promotion")
        
        # 1. Setup mock session and valid check
        mock_load_session.return_value = [{"name": "naukri_session", "value": "active_session", "domain": "naukri.com"}]
        mock_session_valid.return_value = True
        
        # Mock locator counts for already applied checks (0)
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock(side_effect=Exception("Navigation Timeout")) # Simulate exception
        
        mock_context = AsyncMock()
        mock_context.new_page.return_value = mock_page
        mock_browser = AsyncMock()
        mock_browser.new_context.return_value = mock_context
        
        mock_playwright_instance = MagicMock()
        mock_playwright_instance.chromium.launch = AsyncMock(return_value=mock_browser)
        async def enter_mock(*args, **kwargs):
            return mock_playwright_instance
        mock_playwright.return_value.__aenter__ = enter_mock
        
        # Seed 1 job and 1 surfaced application with retry_count = 0
        job_retry = {
            "job_id": "job-retry-1",
            "title": "React Engineer",
            "company": "FastDev",
            "url": "https://naukri.com/job-retry-1",
            "relevance_percent": 90
        }
        db.save_naukri_jobs([job_retry])
        db.add_naukri_application(self.user_id, "job-retry-1", status="surfaced")
        
        loop = asyncio.new_event_loop()
        
        # Run 1st attempt: Should fail, update status to 'retrying', and set retry_count = 1
        res1 = loop.run_until_complete(run_naukri_auto_apply(self.user_id, max_daily_apps=5))
        self.assertTrue(res1["success"])
        apps1 = db.get_naukri_applications(self.user_id)
        app1 = next(a for a in apps1 if a["job_id"] == "job-retry-1")
        self.assertEqual(app1["status"], "retrying")
        self.assertEqual(app1["retry_count"], 1)
        self.assertEqual(app1["last_error"], "Navigation Timeout")
        
        # Run 2nd attempt (mock retry_count is 1 in DB): Should set retry_count = 2, status 'retrying'
        res2 = loop.run_until_complete(run_naukri_auto_apply(self.user_id, max_daily_apps=5))
        apps2 = db.get_naukri_applications(self.user_id)
        app2 = next(a for a in apps2 if a["job_id"] == "job-retry-1")
        self.assertEqual(app2["status"], "retrying")
        self.assertEqual(app2["retry_count"], 2)
        
        # Run 3rd attempt (mock retry_count is 2 in DB): Should transition to 'failed' (terminal), retry_count = 3
        res3 = loop.run_until_complete(run_naukri_auto_apply(self.user_id, max_daily_apps=5))
        apps3 = db.get_naukri_applications(self.user_id)
        app3 = next(a for a in apps3 if a["job_id"] == "job-retry-1")
        self.assertEqual(app3["status"], "failed")
        self.assertEqual(app3["retry_count"], 3)
        
        # Verify attempt logs in database
        logs = db.get_naukri_application_logs(self.user_id, "job-retry-1")
        self.assertEqual(len(logs), 3)
        self.assertEqual(logs[0]["status"], "failed") # latest first
        self.assertEqual(logs[1]["status"], "retrying")
        self.assertEqual(logs[2]["status"], "retrying")
        
        print("[OK] Retry count correctly increments and promotes to terminal 'failed' after 3 failures.")

    @patch("naukri_agent.applier.load_session")
    @patch("naukri_agent.applier.is_session_valid", new_callable=AsyncMock)
    @patch("naukri_agent.applier.async_playwright")
    def test_05_failure_queue_and_actions(self, mock_playwright, mock_session_valid, mock_load_session):
        print_section("Test 5: Flask Failure Queue & Action Endpoints")
        from core.app import app
        
        # Seed a terminal failure
        job_fail = {
            "job_id": "job-fail-1",
            "title": "Machine Learning Engineer",
            "company": "AI Labs",
            "url": "https://naukri.com/job-fail-1",
            "relevance_percent": 95
        }
        db.save_naukri_jobs([job_fail])
        db.add_naukri_application(self.user_id, "job-fail-1", status="failed")
        db.update_naukri_application_retry(self.user_id, "job-fail-1", "failed", 3, "Playwright Error")
        db.add_naukri_application_attempt(self.user_id, "job-fail-1", 3, "failed", "Playwright Error", "/screenshots/dummy.png")
        
        with app.test_client() as client:
            # 1. Query failures
            r_fail = client.get(f"/api/users/{self.user_id}/naukri-failures")
            self.assertEqual(r_fail.status_code, 200)
            data_fail = r_fail.get_json()
            self.assertTrue(data_fail["ok"])
            self.assertEqual(len(data_fail["failures"]), 1)
            self.assertEqual(data_fail["failures"][0]["job_id"], "job-fail-1")
            self.assertEqual(data_fail["failures"][0]["screenshot_path"], "/screenshots/dummy.png")
            
            # Fetch application ID
            app_id = data_fail["failures"][0]["id"]
            
            # 2. Get screenshot (should return 404 because file dummy.png doesn't exist, but route must execute)
            r_ss = client.get(f"/api/users/{self.user_id}/naukri-applications/{app_id}/screenshot")
            self.assertEqual(r_ss.status_code, 404)
            
            # 3. Dismiss application
            r_dismiss = client.post(f"/api/users/{self.user_id}/naukri-applications/{app_id}/dismiss")
            self.assertEqual(r_dismiss.status_code, 200)
            data_dismiss = r_dismiss.get_json()
            self.assertTrue(data_dismiss["ok"])
            
            # Verify status in DB is now 'dismissed'
            apps = db.get_naukri_applications(self.user_id)
            app_entry = next(a for a in apps if a["job_id"] == "job-fail-1")
            self.assertEqual(app_entry["status"], "dismissed")
            
            # 4. Retry action (should set to 'retrying', and attempt to run auto-apply)
            # Mock session validity for auto-apply triggered by retry
            mock_load_session.return_value = [{"name": "naukri_session", "value": "active_session", "domain": "naukri.com"}]
            mock_session_valid.return_value = True
            
            # Mock Playwright to abort instantly
            mock_playwright.return_value.__aenter__.side_effect = Exception("Abort auto-apply run")
            
            r_retry = client.post(f"/api/users/{self.user_id}/naukri-applications/{app_id}/retry")
            # Since playwright fails on launch, check status in DB is 'retrying'
            apps_retry = db.get_naukri_applications(self.user_id)
            app_entry_retry = next(a for a in apps_retry if a["job_id"] == "job-fail-1")
            self.assertEqual(app_entry_retry["status"], "retrying")
            self.assertEqual(app_entry_retry["retry_count"], 0)
            self.assertIsNone(app_entry_retry["last_error"])
            
        print("[OK] Flask failure queue, screenshot lookup, dismiss, and retry APIs validated.")

if __name__ == "__main__":
    unittest.main()
