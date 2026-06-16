"""
runner.py — Background agent runner for IITIIMJobAssistant.

This module is the entry point for per-user background job agent threads.
It uses APScheduler to run job discovery (via Linkup API) and auto-apply
cycles at configurable intervals.
"""

import os
import sys
import threading
import asyncio
from datetime import datetime, timezone

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Registry of active agent threads per user_id
_active_agents: dict[int, dict] = {}
_lock = threading.Lock()


def start_agent(user_id: int, config: dict | None = None) -> bool:
    """Start a background agent thread for a given user.

    Args:
        user_id: The user ID to run the agent for.
        config: Optional overrides (job_preferences, daily_limit, etc.)

    Returns:
        True if agent started, False if already running.
    """
    with _lock:
        if user_id in _active_agents and _active_agents[user_id].get("running"):
            return False  # Already running

    config = config or {}
    thread = threading.Thread(
        target=_agent_loop,
        args=(user_id, config),
        name=f"agent-{user_id}",
        daemon=True,
    )

    with _lock:
        _active_agents[user_id] = {
            "thread": thread,
            "running": True,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "config": config,
        }

    thread.start()

    # Update DB status
    try:
        from core.database import update_user_agent_status
        update_user_agent_status(user_id, "running")
    except Exception as e:
        print(f"[Agent] Warning: Could not update DB status for user {user_id}: {e}")

    print(f"[Agent] Started for user {user_id}")
    return True


def stop_agent(user_id: int) -> bool:
    """Signal an agent thread to stop."""
    with _lock:
        entry = _active_agents.get(user_id)
        if not entry or not entry.get("running"):
            return False
        entry["running"] = False

    try:
        from core.database import update_user_agent_status
        update_user_agent_status(user_id, "inactive")
    except Exception:
        pass

    print(f"[Agent] Stop signal sent to user {user_id}")
    return True


def get_agent_status(user_id: int) -> dict:
    """Return the current agent status for a user."""
    with _lock:
        entry = _active_agents.get(user_id, {})
    return {
        "running": entry.get("running", False),
        "started_at": entry.get("started_at", ""),
        "config": entry.get("config", {}),
    }


def _agent_loop(user_id: int, config: dict):
    """Main agent loop — runs discovery + apply cycles.

    This runs in its own thread with its own event loop.
    """
    import time

    interval_minutes = config.get("interval_minutes", 60)
    daily_limit = config.get("daily_limit", 5)

    print(f"[Agent] Loop started for user {user_id} (interval={interval_minutes}m, limit={daily_limit})")

    while True:
        # Check if we should stop
        with _lock:
            entry = _active_agents.get(user_id, {})
            if not entry.get("running"):
                break

        try:
            _run_cycle(user_id, daily_limit)
        except Exception as e:
            print(f"[Agent] Error in cycle for user {user_id}: {e}")
            try:
                from core.database import update_user_agent_status
                update_user_agent_status(user_id, "error")
            except Exception:
                pass

        # Sleep for interval
        for _ in range(interval_minutes * 60):
            with _lock:
                if not _active_agents.get(user_id, {}).get("running"):
                    break
            time.sleep(1)

    # Cleanup
    with _lock:
        _active_agents.pop(user_id, None)
    print(f"[Agent] Loop ended for user {user_id}")


def _run_cycle(user_id: int, daily_limit: int):
    """Run one complete pipeline cycle: scrape → apply → connect."""
    from core.database import get_user, update_user_activity

    user = get_user(user_id)
    if not user:
        print(f"[Agent] User {user_id} not found, stopping")
        stop_agent(user_id)
        return

    # Run the full pipeline (scrape LinkedIn → apply → connection requests)
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        from job_seeker_agent.applier import run_full_pipeline
        loop.run_until_complete(
            run_full_pipeline(
                user_id=user_id,
                dry_run=False,
                headed=False,
                limit=daily_limit,
            )
        )
        loop.close()
    except Exception as e:
        print(f"[Agent] Full pipeline failed for user {user_id}: {e}")

    # Track activity
    update_user_activity(user_id)

