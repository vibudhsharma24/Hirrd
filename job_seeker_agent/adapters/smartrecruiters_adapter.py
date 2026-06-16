"""
smartrecruiters_adapter.py — SmartRecruiters ATS form filler.

Handles multi-step forms on jobs.smartrecruiters.com.
"""

from adapters.base_adapter import ATSAdapter, ApplyResult


class SmartRecruitersAdapter(ATSAdapter):
    ats_type = "smartrecruiters"

    async def fill_and_submit(self, session, url, profile, resume_path, cover_letter="", portal_memory=""):
        try:
            await session.goto(url, timeout=30000)
            await session.wait(2000)

            if await self._check_captcha(session):
                ss = await session.screenshot("sr_captcha")
                return ApplyResult(
                    success=False, status="paused",
                    failure_type="captcha",
                    error_message="CAPTCHA detected on SmartRecruiters",
                    screenshot_path=ss, page_url=await session.get_page_url(),
                )

            # Click Apply button
            for sel in ['button:has-text("Apply")', '.st-apply-button',
                        'a:has-text("Apply Now")', 'button:has-text("Apply Now")']:
                if await self._safe_click(session, sel, timeout=5000):
                    await session.wait(2000)
                    break

            await session.screenshot("sr_before_fill")

            # Fill fields
            name = profile.get("name", "")
            last_name = profile.get("last_name", "")

            for sel in ['input[name="firstName"]', 'input[id*="firstName"]',
                        'input[aria-label*="First"]', '#firstName']:
                if await self._safe_fill(session, sel, name):
                    break

            for sel in ['input[name="lastName"]', 'input[id*="lastName"]',
                        'input[aria-label*="Last"]', '#lastName']:
                if await self._safe_fill(session, sel, last_name):
                    break

            for sel in ['input[name="email"]', 'input[type="email"]', '#email']:
                if await self._safe_fill(session, sel, profile.get("email", "")):
                    break

            for sel in ['input[name="phoneNumber"]', 'input[type="tel"]', '#phone']:
                if await self._safe_fill(session, sel, profile.get("phone", "")):
                    break

            # Resume upload
            for sel in ['input[type="file"]', 'input[name*="resume"]']:
                if await self._safe_upload(session, sel, resume_path):
                    await session.wait(2000)
                    break

            # Cover letter
            if cover_letter:
                for sel in ['textarea[name*="cover"]', 'textarea[id*="cover"]', 'textarea']:
                    if await self._safe_fill(session, sel, cover_letter):
                        break

            # LinkedIn
            for sel in ['input[name*="linkedin"]', 'input[placeholder*="LinkedIn"]']:
                await self._safe_fill(session, sel, profile.get("linkedin_url", ""))

            ss_filled = await session.screenshot("sr_filled")

            # Navigate through multi-step form
            for _ in range(3):  # Max 3 "Next" pages
                for sel in ['button:has-text("Next")', 'button:has-text("Continue")',
                            'button[type="submit"]']:
                    if await self._safe_click(session, sel, timeout=3000):
                        await session.wait(2000)
                        break

            # Final submit
            for sel in ['button:has-text("Submit")',
                        'button:has-text("Submit Application")',
                        'button[type="submit"]']:
                if await self._safe_click(session, sel, timeout=5000):
                    break

            await session.wait(3000)
            ss_confirm = await session.screenshot("sr_confirmed")
            confirmation = await self._check_confirmation(session)
            dom = await session.get_dom_snapshot()

            if confirmation:
                return ApplyResult(
                    success=True, status="applied",
                    confirmation_id=confirmation[:200],
                    screenshot_path=ss_confirm, dom_snapshot=dom[:5000],
                    page_url=await session.get_page_url(),
                )
            else:
                return ApplyResult(
                    success=True, status="applied",
                    confirmation_id="Submitted (SmartRecruiters)",
                    screenshot_path=ss_confirm, dom_snapshot=dom[:5000],
                    page_url=await session.get_page_url(),
                )

        except Exception as e:
            ss = ""
            try:
                ss = await session.screenshot("sr_error")
            except Exception:
                pass
            return ApplyResult(
                success=False, status="failed",
                failure_type="unknown",
                error_message=f"SmartRecruiters adapter error: {str(e)[:200]}",
                screenshot_path=ss, page_url=url,
            )
