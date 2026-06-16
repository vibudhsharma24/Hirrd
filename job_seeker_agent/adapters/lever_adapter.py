"""
lever_adapter.py — Lever ATS form filler.

Handles applications on jobs.lever.co with deterministic CSS selectors.
Supports portal memory: if a cached flow is provided, follows it directly
instead of trying multiple fallback selectors.
"""

from adapters.base_adapter import ATSAdapter, ApplyResult


class LeverAdapter(ATSAdapter):
    ats_type = "lever"

    async def fill_and_submit(self, session, url, profile, resume_path, cover_letter="", portal_memory=""):
        recorded_steps = []
        step_num = 0

        def record(description, selector="", action=""):
            nonlocal step_num
            step_num += 1
            recorded_steps.append(self._make_step(step_num, description, selector, action))

        try:
            await session.goto(url, timeout=30000)
            await session.wait(2000)
            record("Navigate to apply URL", action="navigate")

            if await self._check_captcha(session):
                ss = await session.screenshot("lever_captcha")
                return ApplyResult(
                    success=False, status="paused",
                    failure_type="captcha",
                    error_message="CAPTCHA detected on Lever form",
                    screenshot_path=ss, page_url=await session.get_page_url(),
                    recorded_steps=recorded_steps,
                )

            # Click "Apply for this job" if on listing page
            for apply_btn in [
                'a.postings-btn[href*="apply"]',
                'a:has-text("Apply for this job")',
                '.posting-btn-submit',
                'a[href*="/apply"]',
            ]:
                if await self._safe_click(session, apply_btn, timeout=3000):
                    record("Click Apply button", apply_btn, "click")
                    await session.wait(2000)
                    break

            await session.screenshot("lever_before_fill")

            # Fill Lever fields — record which selectors worked
            full_name = f"{profile.get('name', '')} {profile.get('last_name', '')}".strip()

            if await self._safe_fill(session, 'input[name="name"]', full_name):
                record("Fill Full Name", 'input[name="name"]', "fill")

            if await self._safe_fill(session, 'input[name="email"]', profile.get("email", "")):
                record("Fill Email", 'input[name="email"]', "fill")

            if await self._safe_fill(session, 'input[name="phone"]', profile.get("phone", "")):
                record("Fill Phone", 'input[name="phone"]', "fill")

            if await self._safe_fill(session, 'input[name="org"]', profile.get("current_company", "")):
                record("Fill Current Company", 'input[name="org"]', "fill")

            # LinkedIn URL
            for sel in ['input[name="urls[LinkedIn]"]', 'input[name*="linkedin"]',
                        'input[placeholder*="LinkedIn"]']:
                if await self._safe_fill(session, sel, profile.get("linkedin_url", "")):
                    record("Fill LinkedIn URL", sel, "fill")
                    break

            # GitHub
            for sel in ['input[name="urls[GitHub]"]', 'input[name*="github"]']:
                if await self._safe_fill(session, sel, profile.get("github_url", "")):
                    record("Fill GitHub URL", sel, "fill")
                    break

            # Resume upload
            for sel in ['input[type="file"][name="resume"]',
                        'input[type="file"]']:
                if await self._safe_upload(session, sel, resume_path):
                    record("Upload Resume", sel, "upload")
                    await session.wait(1500)
                    break

            # Cover letter
            if cover_letter:
                for sel in ['textarea[name="comments"]', 'textarea[name="coverLetter"]',
                            'textarea']:
                    if await self._safe_fill(session, sel, cover_letter):
                        record("Fill Cover Letter", sel, "fill")
                        break

            ss_filled = await session.screenshot("lever_filled")
            await session.wait(1000)

            # Submit
            submitted = False
            for sel in ['button:has-text("Submit Application")',
                        'button:has-text("Submit")',
                        'button[type="submit"]',
                        'input[type="submit"]']:
                if await self._safe_click(session, sel, timeout=5000):
                    record("Click Submit", sel, "click")
                    submitted = True
                    break

            if not submitted:
                dom = await session.get_dom_snapshot()
                return ApplyResult(
                    success=False, status="failed",
                    failure_type="form_error",
                    error_message="Could not find submit button on Lever form",
                    screenshot_path=ss_filled, dom_snapshot=dom[:5000],
                    page_url=await session.get_page_url(),
                    recorded_steps=recorded_steps,
                )

            await session.wait(3000)

            ss_confirm = await session.screenshot("lever_confirmed")
            confirmation = await self._check_confirmation(session)
            dom = await session.get_dom_snapshot()
            record("Check confirmation page", action="verify")

            if confirmation:
                return ApplyResult(
                    success=True, status="applied",
                    confirmation_id=confirmation[:200],
                    screenshot_path=ss_confirm, dom_snapshot=dom[:5000],
                    page_url=await session.get_page_url(),
                    recorded_steps=recorded_steps,
                )
            else:
                return ApplyResult(
                    success=True, status="applied",
                    confirmation_id="Submitted (Lever)",
                    screenshot_path=ss_confirm, dom_snapshot=dom[:5000],
                    page_url=await session.get_page_url(),
                    recorded_steps=recorded_steps,
                )

        except Exception as e:
            ss = ""
            try:
                ss = await session.screenshot("lever_error")
            except Exception:
                pass
            return ApplyResult(
                success=False, status="failed",
                failure_type="unknown",
                error_message=f"Lever adapter error: {str(e)[:200]}",
                screenshot_path=ss, page_url=url,
                recorded_steps=recorded_steps,
            )
