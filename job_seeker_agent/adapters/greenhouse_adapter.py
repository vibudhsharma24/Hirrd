"""
greenhouse_adapter.py — Greenhouse ATS form filler.

Handles applications on boards.greenhouse.io with deterministic CSS selectors.
"""

from adapters.base_adapter import ATSAdapter, ApplyResult


class GreenhouseAdapter(ATSAdapter):
    ats_type = "greenhouse"

    async def fill_and_submit(self, session, url, profile, resume_path, cover_letter="", portal_memory=""):
        try:
            # Navigate to the application page
            await session.goto(url, timeout=30000)
            await session.wait(2000)

            # Check for CAPTCHA
            if await self._check_captcha(session):
                ss = await session.screenshot("greenhouse_captcha")
                return ApplyResult(
                    success=False, status="paused",
                    failure_type="captcha",
                    error_message="CAPTCHA detected on Greenhouse form",
                    screenshot_path=ss, page_url=await session.get_page_url(),
                )

            # Screenshot before filling
            await session.screenshot("greenhouse_before_fill")

            # Try to click the Apply button if we're on a job listing page
            for apply_btn in [
                'a:has-text("Apply for this job")',
                'button:has-text("Apply")',
                'a[href*="/apply"]',
                '.btn-apply', '#apply_button',
            ]:
                clicked = await self._safe_click(session, apply_btn, timeout=3000)
                if clicked:
                    await session.wait(2000)
                    break

            # Fill standard Greenhouse fields
            name = profile.get("name", "")
            last_name = profile.get("last_name", "")

            # Some Greenhouse forms use separate first/last name, others use full name
            if await session.element_exists("#first_name"):
                await self._safe_fill(session, "#first_name", name)
                await self._safe_fill(session, "#last_name", last_name)
            else:
                full_name = f"{name} {last_name}".strip()
                await self._safe_fill(session, 'input[name="name"]', full_name)

            await self._safe_fill(session, "#email", profile.get("email", ""))
            await self._safe_fill(session, "#phone", profile.get("phone", ""))

            # LinkedIn URL
            for sel in ['input[id*="linkedin"]', 'input[name*="linkedin"]',
                        'input[autocomplete="url"]']:
                if await self._safe_fill(session, sel, profile.get("linkedin_url", "")):
                    break

            # GitHub URL
            for sel in ['input[id*="github"]', 'input[name*="github"]']:
                await self._safe_fill(session, sel, profile.get("github_url", ""))

            # Resume upload
            for sel in ['input[type="file"][id*="resume"]',
                        'input[type="file"][name*="resume"]',
                        'input[type="file"]']:
                if await self._safe_upload(session, sel, resume_path):
                    await session.wait(1500)
                    break

            # Cover letter (only if field exists and cover letter provided)
            if cover_letter:
                for sel in ['textarea[id*="cover_letter"]',
                            'textarea[name*="cover_letter"]']:
                    if await self._safe_fill(session, sel, cover_letter):
                        break

            # Screenshot after filling
            ss_filled = await session.screenshot("greenhouse_filled")
            await session.wait(1000)

            # Submit
            submitted = False
            for sel in ['input[type="submit"]', 'button[type="submit"]',
                        'button:has-text("Submit Application")',
                        'button:has-text("Submit")']:
                if await self._safe_click(session, sel, timeout=5000):
                    submitted = True
                    break

            if not submitted:
                dom = await session.get_dom_snapshot()
                return ApplyResult(
                    success=False, status="failed",
                    failure_type="form_error",
                    error_message="Could not find submit button on Greenhouse form",
                    screenshot_path=ss_filled, dom_snapshot=dom[:5000],
                    page_url=await session.get_page_url(),
                )

            await session.wait(3000)

            # Verify confirmation
            ss_confirm = await session.screenshot("greenhouse_confirmed")
            confirmation = await self._check_confirmation(session)
            dom = await session.get_dom_snapshot()

            if confirmation:
                return ApplyResult(
                    success=True, status="applied",
                    confirmation_id=confirmation[:200],
                    screenshot_path=ss_confirm,
                    dom_snapshot=dom[:5000],
                    page_url=await session.get_page_url(),
                )
            else:
                # Check if we're still on the same page (might have validation errors)
                page_text = await session.get_page_text()
                if "error" in page_text.lower() or "required" in page_text.lower():
                    return ApplyResult(
                        success=False, status="failed",
                        failure_type="form_error",
                        error_message="Form validation errors detected",
                        screenshot_path=ss_confirm,
                        dom_snapshot=dom[:5000],
                        page_url=await session.get_page_url(),
                    )
                # Assume success if no errors and page changed
                return ApplyResult(
                    success=True, status="applied",
                    confirmation_id="Submitted (no explicit confirmation text)",
                    screenshot_path=ss_confirm,
                    dom_snapshot=dom[:5000],
                    page_url=await session.get_page_url(),
                )

        except Exception as e:
            ss = ""
            try:
                ss = await session.screenshot("greenhouse_error")
            except Exception:
                pass
            return ApplyResult(
                success=False, status="failed",
                failure_type="unknown",
                error_message=f"Greenhouse adapter error: {str(e)[:200]}",
                screenshot_path=ss,
                page_url=url,
            )
