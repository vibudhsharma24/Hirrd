"""
custom_adapter.py — AI-driven fallback adapter for unknown/custom ATS portals.

Uses browser-use Agent to interpret the page and fill forms via LLM.
When portal_memory is provided, injects it into the AI prompt to skip
re-exploration — this is the biggest credit saver.
On success, records discovered steps in portal_profiles for future use.
"""

import os
from adapters.base_adapter import ATSAdapter, ApplyResult

# Try loading .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class CustomAdapter(ATSAdapter):
    ats_type = "custom"

    async def fill_and_submit(self, session, url, profile, resume_path, cover_letter="", portal_memory=""):
        """Attempt to fill an unknown form using AI (browser-use) or graceful failure."""
        recorded_steps = []

        try:
            await session.goto(url, timeout=30000)
            await session.wait(3000)

            # First check: is this a 404 or error page?
            page_text = await session.get_page_text()
            error_indicators = ["page not found", "404", "this page doesn't exist",
                                "job has been removed", "position has been filled",
                                "no longer accepting", "this posting has expired"]
            for indicator in error_indicators:
                if indicator in page_text.lower():
                    ss = await session.screenshot("custom_expired")
                    return ApplyResult(
                        success=False, status="failed",
                        failure_type="network",
                        error_message=f"Job posting appears expired/removed: '{indicator}'",
                        screenshot_path=ss, page_url=await session.get_page_url(),
                        recorded_steps=recorded_steps,
                    )

            if await self._check_captcha(session):
                ss = await session.screenshot("custom_captcha")
                return ApplyResult(
                    success=False, status="paused",
                    failure_type="captcha",
                    error_message="CAPTCHA detected on unknown portal",
                    screenshot_path=ss, page_url=await session.get_page_url(),
                    recorded_steps=recorded_steps,
                )

            # Try using browser-use for AI-driven form filling
            anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
            openai_key = os.environ.get("OPENAI_API_KEY", "")

            if anthropic_key or openai_key:
                return await self._ai_fill(session, url, profile, resume_path, cover_letter, portal_memory)
            else:
                # No AI available — route to failure queue
                ss = await session.screenshot("custom_no_ai")
                return ApplyResult(
                    success=False, status="failed",
                    failure_type="unsupported_ats",
                    error_message="Unknown ATS portal and no LLM API key configured for AI-driven filling",
                    screenshot_path=ss, page_url=await session.get_page_url(),
                    recorded_steps=recorded_steps,
                )

        except Exception as e:
            ss = ""
            try:
                ss = await session.screenshot("custom_error")
            except Exception:
                pass
            return ApplyResult(
                success=False, status="failed",
                failure_type="unknown",
                error_message=f"Custom adapter error: {str(e)[:200]}",
                screenshot_path=ss, page_url=url,
                recorded_steps=recorded_steps,
            )

    async def _ai_fill(self, session, url, profile, resume_path, cover_letter, portal_memory=""):
        """Use browser-use Agent to fill an unknown form with AI.

        If portal_memory is provided, it is injected into the task prompt
        so the AI follows the cached flow instead of exploring from scratch.
        This dramatically reduces the number of LLM calls needed.
        """
        try:
            from browser_use import Agent, Browser
            from langchain_anthropic import ChatAnthropic

            name = profile.get("name", "")
            last_name = profile.get("last_name", "")
            email = profile.get("email", "")
            phone = profile.get("phone", "")
            linkedin = profile.get("linkedin_url", "")

            # Build the task prompt — with or without portal memory
            memory_section = ""
            if portal_memory:
                memory_section = f"""
IMPORTANT — CACHED PORTAL KNOWLEDGE:
You have previously interacted with this portal. Follow the cached steps below
EXACTLY instead of exploring the page from scratch. This saves time and credits.

--- BEGIN CACHED PORTAL KNOWLEDGE ---
{portal_memory}
--- END CACHED PORTAL KNOWLEDGE ---

Follow the step-by-step flow documented above. Only deviate if a selector
does not work (the portal may have been updated). If you must deviate,
note which steps changed so we can update the cache.
"""

            task = f"""
You are filling out a job application form. Navigate to this URL: {url}

{memory_section}

Fill in the following information wherever relevant fields exist:
- Full Name: {name} {last_name}
- First Name: {name}
- Last Name: {last_name}
- Email: {email}
- Phone: {phone or "Not provided"}
- LinkedIn: {linkedin or "Not provided"}

If there is a resume/CV upload field, upload the file from: {resume_path}

{"Add this cover letter if there is a cover letter field: " + cover_letter[:500] if cover_letter else "Skip the cover letter field if it is optional."}

After filling all visible fields, click the Submit/Apply button.

IMPORTANT RULES:
- Do NOT create any accounts or sign up for anything
- If asked to log in, STOP and report that login is required
- If you see a CAPTCHA, STOP and report it
- Fill only the fields you can see on the apply page
- Report what you did at the end
"""

            llm = ChatAnthropic(model="claude-sonnet-4-6")

            # browser-use 0.1.x uses Browser(config=BrowserConfig(...))
            from browser_use.browser.browser import BrowserConfig
            browser = Browser(
                config=BrowserConfig(
                    headless=False,          # Show the window so user can see it
                    disable_security=True,
                )
            )

            agent = Agent(
                task=task,
                llm=llm,
                browser=browser,
            )

            result = await agent.run(max_steps=20)

            ss = await session.screenshot("custom_ai_done")
            confirmation = await self._check_confirmation(session)
            dom = await session.get_dom_snapshot()

            # Close the browser-use browser
            try:
                await browser.close()
            except Exception:
                pass

            if confirmation:
                return ApplyResult(
                    success=True, status="applied",
                    confirmation_id=confirmation[:200],
                    screenshot_path=ss, dom_snapshot=dom[:5000],
                    page_url=await session.get_page_url(),
                )
            else:
                return ApplyResult(
                    success=False, status="failed",
                    failure_type="form_error",
                    error_message="AI agent completed but no confirmation detected",
                    screenshot_path=ss, dom_snapshot=dom[:5000],
                    page_url=await session.get_page_url(),
                )

        except ImportError:
            ss = await session.screenshot("custom_no_browseruse")
            return ApplyResult(
                success=False, status="failed",
                failure_type="unsupported_ats",
                error_message="browser-use package not installed. Run: pip install browser-use langchain-anthropic",
                screenshot_path=ss, page_url=url,
            )
        except Exception as e:
            ss = ""
            try:
                ss = await session.screenshot("custom_ai_error")
            except Exception:
                pass
            return ApplyResult(
                success=False, status="failed",
                failure_type="unknown",
                error_message=f"AI-driven fill error: {str(e)[:200]}",
                screenshot_path=ss, page_url=url,
            )
