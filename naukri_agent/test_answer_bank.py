import os
import sys
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone
import json

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core import database as db
from naukri_agent.answer_bank import clean_text, match_stored_question, get_or_propose_answer, generate_openai_answer

def print_section(title):
    print("\n" + "=" * 80)
    print(f" {title.upper()}")
    print("=" * 80)

class TestAnswerBank(unittest.TestCase):
    user_id = 8888  # Test user ID

    @classmethod
    def setUpClass(cls):
        db.init_db()
        # Seed test user
        with db._connect() as conn:
            conn.execute("DELETE FROM users WHERE id = ?", (cls.user_id,))
            conn.execute(
                "INSERT INTO users (id, name, last_name, email, password_hash, submitted_at) VALUES (?, ?, ?, ?, ?, ?)",
                (cls.user_id, "Test", "Candidate", "answer_bank_test@example.com", "mock_hash", "2026-07-07T00:00:00")
            )
            # Seed mock CV
            mock_cv = {
                "personal": {
                    "name": "Ajay",
                    "last_name": "Singh",
                    "email": "ajay.singh@example.com",
                    "phone": "+91 9999999999",
                    "headline": "Software Engineer"
                },
                "skills": ["Python", "FastAPI", "SQL", "Docker"],
                "experience": [
                    {
                        "company": "Apple",
                        "role": "Senior Developer",
                        "responsibilities": ["FastAPI services", "SQL databases"]
                    }
                ]
            }
            conn.execute("DELETE FROM master_cv WHERE user_id = ?", (cls.user_id,))
            conn.execute(
                "INSERT INTO master_cv (user_id, cv_data, updated_at) VALUES (?, ?, ?)",
                (cls.user_id, json.dumps(mock_cv), "2026-07-07T00:00:00")
            )
            conn.commit()

    def setUp(self):
        # Clear answer bank table for test user
        with db._connect() as conn:
            conn.execute("DELETE FROM naukri_answer_bank WHERE user_id = ?", (self.user_id,))
            conn.commit()

    def test_01_clean_text(self):
        print_section("Test 1: clean_text normalization")
        self.assertEqual(clean_text("What is your notice period?"), "what is your notice period")
        self.assertEqual(clean_text("Python  & FastAPI...  "), "python fastapi")
        self.assertEqual(clean_text(""), "")
        print("[OK] Text cleaning works.")

    def test_02_match_stored_question(self):
        print_section("Test 2: Question Matching Algorithm")
        stored = [
            {"question": "What is your total years of experience?", "answer": "3 years", "status": "approved"},
            {"question": "Do you have experience in Python?", "answer": "Yes, 3 years of production experience", "status": "approved"}
        ]
        
        # Exact match (different case / punctuation)
        m1 = match_stored_question("What is your total years of experience?", stored)
        self.assertIsNotNone(m1)
        self.assertEqual(m1["answer"], "3 years")
        
        # Substring/overlap match (high similarity)
        m2 = match_stored_question("What is your total experience in years?", stored)
        self.assertIsNotNone(m2)
        self.assertEqual(m2["answer"], "3 years")
        
        # Non-matching question
        m3 = match_stored_question("Are you willing to relocate to Bangalore?", stored)
        self.assertIsNone(m3)
        print("[OK] Exact and fuzzy matching logic works.")

    @patch("openai.resources.chat.completions.Completions.create")
    def test_03_get_or_propose_answer(self, mock_openai_create):
        print_section("Test 3: get_or_propose_answer and OpenAI Mocking")
        
        # Mock OpenAI response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "I have 3 years of notice period."
        mock_openai_create.return_value = mock_response
        
        # Set dummy API key
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-dummy-key-for-testing"}):
            # Question is missing -> should invoke OpenAI and save as pending_review
            ans, status = get_or_propose_answer(self.user_id, "What is your notice period?")
            
            self.assertEqual(ans, "I have 3 years of notice period.")
            self.assertEqual(status, "pending_review")
            
            # Check DB insertion
            entries = db.get_naukri_answer_bank(self.user_id)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["question"], "What is your notice period?")
            self.assertEqual(entries[0]["answer"], "I have 3 years of notice period.")
            self.assertEqual(entries[0]["status"], "pending_review")
            
            # Second call with the same question -> should return from database (still pending_review)
            ans2, status2 = get_or_propose_answer(self.user_id, "What is your notice period?")
            self.assertEqual(ans2, "I have 3 years of notice period.")
            self.assertEqual(status2, "pending_review")
            
            # Change status to approved
            db.save_naukri_answer_bank_entry(self.user_id, "What is your notice period?", "Immediate", status="approved")
            
            # Third call -> should return approved answer
            ans3, status3 = get_or_propose_answer(self.user_id, "What is your notice period?")
            self.assertEqual(ans3, "Immediate")
            self.assertEqual(status3, "approved")
            
        print("[OK] get_or_propose_answer with database caching and review status works.")

    def test_04_flask_endpoints(self):
        print_section("Test 4: Flask API Endpoints")
        from core.app import app
        
        # Run Flask test client
        with app.test_client() as client:
            # 1. GET (should be empty)
            r1 = client.get(f"/api/users/{self.user_id}/answer-bank")
            self.assertEqual(r1.status_code, 200)
            data1 = r1.get_json()
            self.assertTrue(data1["ok"])
            self.assertEqual(len(data1["entries"]), 0)
            
            # 2. POST (add approved entry)
            payload = {
                "question": "What is your gender?",
                "answer": "Male",
                "status": "approved"
            }
            r2 = client.post(f"/api/users/{self.user_id}/answer-bank", json=payload)
            self.assertEqual(r2.status_code, 200)
            data2 = r2.get_json()
            self.assertTrue(data2["ok"])
            
            # Verify via GET
            r3 = client.get(f"/api/users/{self.user_id}/answer-bank")
            data3 = r3.get_json()
            self.assertEqual(len(data3["entries"]), 1)
            self.assertEqual(data3["entries"][0]["question"], "What is your gender?")
            self.assertEqual(data3["entries"][0]["answer"], "Male")
            self.assertEqual(data3["entries"][0]["status"], "approved")
            
            # 3. POST (update entry)
            payload_update = {
                "question": "What is your gender?",
                "answer": "Male (Updated)",
                "status": "pending_review"
            }
            r4 = client.post(f"/api/users/{self.user_id}/answer-bank", json=payload_update)
            self.assertEqual(r4.status_code, 200)
            
            r5 = client.get(f"/api/users/{self.user_id}/answer-bank")
            data5 = r5.get_json()
            self.assertEqual(data5["entries"][0]["answer"], "Male (Updated)")
            self.assertEqual(data5["entries"][0]["status"], "pending_review")
            
            # 4. DELETE entry
            r6 = client.delete(f"/api/users/{self.user_id}/answer-bank?question=What is your gender?")
            self.assertEqual(r6.status_code, 200)
            
            r7 = client.get(f"/api/users/{self.user_id}/answer-bank")
            data7 = r7.get_json()
            self.assertEqual(len(data7["entries"]), 0)
            
        print("[OK] Flask API CRUD endpoints work.")

if __name__ == "__main__":
    unittest.main()
