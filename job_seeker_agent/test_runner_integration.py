import os
import sys
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from job_seeker_agent.runner import _run_cycle

class TestRunnerIntegration(unittest.TestCase):
    user_id = 9999
    daily_limit = 5

    @patch("core.database.get_user")
    @patch("core.database.update_user_activity")
    @patch("job_seeker_agent.applier.run_full_pipeline", new_callable=AsyncMock)
    @patch("naukri_agent.applier.run_naukri_auto_apply", new_callable=AsyncMock)
    def test_run_cycle_success(self, mock_naukri, mock_standard, mock_update_activity, mock_get_user):
        # Setup mock user
        mock_get_user.return_value = {"id": self.user_id, "is_agent_buyer": 1}

        # Run the cycle
        _run_cycle(self.user_id, self.daily_limit)

        # Assert standard pipeline was called
        mock_standard.assert_called_once_with(
            user_id=self.user_id,
            dry_run=False,
            headed=False,
            limit=self.daily_limit
        )

        # Assert Naukri pipeline was called
        mock_naukri.assert_called_once_with(
            user_id=self.user_id,
            max_daily_apps=self.daily_limit
        )

        # Assert user activity was tracked
        mock_update_activity.assert_called_once_with(self.user_id)

    @patch("core.database.get_user")
    @patch("core.database.update_user_activity")
    @patch("job_seeker_agent.applier.run_full_pipeline", new_callable=AsyncMock)
    @patch("naukri_agent.applier.run_naukri_auto_apply", new_callable=AsyncMock)
    def test_run_cycle_standard_pipeline_fails(self, mock_naukri, mock_standard, mock_update_activity, mock_get_user):
        # Setup mock user
        mock_get_user.return_value = {"id": self.user_id, "is_agent_buyer": 1}
        
        # Make standard pipeline fail
        mock_standard.side_effect = Exception("LinkedIn Scraper Error")

        # Run the cycle — it should not crash and still run the Naukri pipeline
        _run_cycle(self.user_id, self.daily_limit)

        # Confirm standard was called and failed
        mock_standard.assert_called_once()
        
        # Confirm Naukri was still called
        mock_naukri.assert_called_once_with(
            user_id=self.user_id,
            max_daily_apps=self.daily_limit
        )
        
        # Confirm activity was still updated
        mock_update_activity.assert_called_once_with(self.user_id)

    @patch("core.database.get_user")
    @patch("core.database.update_user_activity")
    @patch("job_seeker_agent.applier.run_full_pipeline", new_callable=AsyncMock)
    @patch("naukri_agent.applier.run_naukri_auto_apply", new_callable=AsyncMock)
    def test_run_cycle_naukri_pipeline_fails(self, mock_naukri, mock_standard, mock_update_activity, mock_get_user):
        # Setup mock user
        mock_get_user.return_value = {"id": self.user_id, "is_agent_buyer": 1}
        
        # Make Naukri pipeline fail
        mock_naukri.side_effect = Exception("Naukri Login expired")

        # Run the cycle — it should catch the exception and finish gracefully
        _run_cycle(self.user_id, self.daily_limit)

        # Confirm both pipelines were called
        mock_standard.assert_called_once()
        mock_naukri.assert_called_once()
        
        # Confirm activity was still updated
        mock_update_activity.assert_called_once_with(self.user_id)

if __name__ == "__main__":
    unittest.main()
