"""
adapters — Per-ATS auto-apply form-filling adapters.
"""

from adapters.base_adapter import ATSAdapter, ApplyResult
from adapters.greenhouse_adapter import GreenhouseAdapter
from adapters.lever_adapter import LeverAdapter
from adapters.workday_adapter import WorkdayAdapter
from adapters.ashby_adapter import AshbyAdapter
from adapters.smartrecruiters_adapter import SmartRecruitersAdapter
from adapters.custom_adapter import CustomAdapter
from adapters.google_forms_adapter import GoogleFormsAdapter


def get_adapter(ats_type: str) -> ATSAdapter:
    """Factory: return the appropriate adapter for a given ATS type."""
    adapters = {
        "greenhouse": GreenhouseAdapter,
        "lever": LeverAdapter,
        "workday": WorkdayAdapter,
        "ashby": AshbyAdapter,
        "smartrecruiters": SmartRecruitersAdapter,
        "google_forms": GoogleFormsAdapter,
        "custom": CustomAdapter,
    }
    adapter_class = adapters.get(ats_type, CustomAdapter)
    return adapter_class()


__all__ = [
    "ATSAdapter", "ApplyResult", "get_adapter",
    "GreenhouseAdapter", "LeverAdapter", "WorkdayAdapter",
    "AshbyAdapter", "SmartRecruitersAdapter", "CustomAdapter",
    "GoogleFormsAdapter",
]
