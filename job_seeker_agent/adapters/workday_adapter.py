"""
workday_adapter.py — Workday ATS form filler.

Workday is complex: multi-page, requires account creation, has CAPTCHA.
This adapter handles what it can and routes to failure queue when blocked.
Supports portal memory for recording discovered selectors.
"""

from adapters.base_adapter import ATSAdapter, ApplyResult


class WorkdayAdapter(ATSAdapter):
    ats_type = "workday"

    async def fill_and_submit(self, session, url, profile, resume_path, cover_letter="", portal_memory=""):
        recorded_steps = []
        step_num = 0

        def record(description, selector="", action=""):
            nonlocal step_num
            step_num += 1
            recorded_steps.append(self._make_step(step_num, description, selector, action))

        try:
            await session.goto(url, timeout=45000)
            await session.wait(3000)
            record("Navigate to apply URL", action="navigate")

            if await self._check_captcha(session):
                ss = await session.screenshot("workday_captcha")
                return ApplyResult(
                    success=False, status="paused",
                    failure_type="captcha",
                    error_message="CAPTCHA detected on Workday",
                    screenshot_path=ss, page_url=await session.get_page_url(),
                    recorded_steps=recorded_steps,
                )

            # Check if login/account creation is required
            page_text = await session.get_page_text()
            login_indicators = ["sign in", "create account", "create your account",
                                "log in", "email verification"]
            for indicator in login_indicators:
                if indicator in page_text.lower():
                    ss = await session.screenshot("workday_login_required")
                    record("Login wall detected", action="blocked")
                    return ApplyResult(
                        success=False, status="failed",
                        failure_type="auth_required",
                        error_message=f"Workday requires login/account creation: '{indicator}' detected",
                        screenshot_path=ss, page_url=await session.get_page_url(),
                        recorded_steps=recorded_steps,
                    )

            await session.screenshot("workday_before_fill")

            # Click Apply button
            for sel in ['button:has-text("Apply")', 'a:has-text("Apply")',
                        '[data-automation-id="jobPostingApplyButton"]',
                        'button[data-automation-id*="apply"]']:
                if await self._safe_click(session, sel, timeout=5000):
                    record("Click Apply button", sel, "click")
                    await session.wait(3000)
                    break

            # Check again for login wall after clicking Apply
            page_text = await session.get_page_text()
            for indicator in login_indicators:
                if indicator in page_text.lower():
                    ss = await session.screenshot("workday_login_wall")
                    record("Login wall after Apply click", action="blocked")
                    return ApplyResult(
                        success=False, status="failed",
                        failure_type="auth_required",
                        error_message="Workday login wall appeared after clicking Apply",
                        screenshot_path=ss, page_url=await session.get_page_url(),
                        recorded_steps=recorded_steps,
                    )

            # Try to fill the resume upload section
            for sel in ['input[type="file"]',
                        'input[data-automation-id*="resume"]',
                        'input[data-automation-id="file-upload-input-ref"]']:
                if await self._safe_upload(session, sel, resume_path):
                    record("Upload Resume", sel, "upload")
                    await session.wait(3000)
                    break

            # Fill personal info (Workday uses data-automation-id attributes)
            name = profile.get("name", "")
            last_name = profile.get("last_name", "")

            for sel in ['input[data-automation-id="legalNameSection_firstName"]',
                        'input[aria-label*="First Name"]',
                        'input[name*="firstName"]']:
                if await self._safe_fill(session, sel, name):
                    record("Fill First Name", sel, "fill")
                    break

            for sel in ['input[data-automation-id="legalNameSection_lastName"]',
                        'input[aria-label*="Last Name"]',
                        'input[name*="lastName"]']:
                if await self._safe_fill(session, sel, last_name):
                    record("Fill Last Name", sel, "fill")
                    break

            for sel in ['input[data-automation-id="email"]',
                        'input[type="email"]',
                        'input[aria-label*="Email"]']:
                if await self._safe_fill(session, sel, profile.get("email", "")):
                    record("Fill Email", sel, "fill")
                    break

            for sel in ['input[data-automation-id="phone-number"]',
                        'input[aria-label*="Phone"]',
                        'input[type="tel"]']:
                if await self._safe_fill(session, sel, profile.get("phone", "")):
                    record("Fill Phone", sel, "fill")
                    break

            ss_filled = await session.screenshot("workday_filled")

            # Try Save and Continue / Next / Submit
            for sel in ['button:has-text("Save and Continue")',
                        'button:has-text("Next")',
                        'button:has-text("Submit")',
                        'button[data-automation-id="bottom-navigation-next-button"]']:
                if await self._safe_click(session, sel, timeout=5000):
                    record("Click Save/Continue/Submit", sel, "click")
                    await session.wait(3000)
                    break

            # Take final screenshot
            ss_final = await session.screenshot("workday_after_submit")
            confirmation = await self._check_confirmation(session)
            dom = await session.get_dom_snapshot()

            if confirmation:
                record("Confirmation detected", action="verify")
                return ApplyResult(
                    success=True, status="applied",
                    confirmation_id=confirmation[:200],
                    screenshot_path=ss_final, dom_snapshot=dom[:5000],
                    page_url=await session.get_page_url(),
                    recorded_steps=recorded_steps,
                )

            # Workday is multi-page — if we got this far without errors,
            # we may need human follow-through for remaining pages
            record("Multi-page form — partial fill", action="incomplete")
            return ApplyResult(
                success=False, status="failed",
                failure_type="form_error",
                error_message="Workday multi-page form: partially filled, needs human completion",
                screenshot_path=ss_final, dom_snapshot=dom[:5000],
                page_url=await session.get_page_url(),
                recorded_steps=recorded_steps,
            )

        except Exception as e:
            ss = ""
            try:
                ss = await session.screenshot("workday_error")
            except Exception:
                pass
            return ApplyResult(
                success=False, status="failed",
                failure_type="unknown",
                error_message=f"Workday adapter error: {str(e)[:200]}",
                screenshot_path=ss, page_url=url,
                recorded_steps=recorded_steps,
            )
