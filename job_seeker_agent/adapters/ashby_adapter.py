"""
ashby_adapter.py — Ashby ATS form filler.

Ashby is React-based. Waits for hydration before interacting.
Uses label text matching for field discovery.
"""

from adapters.base_adapter import ATSAdapter, ApplyResult


class AshbyAdapter(ATSAdapter):
    ats_type = "ashby"

    async def fill_and_submit(self, session, url, profile, resume_path, cover_letter="", portal_memory=""):
        try:
            await session.goto(url, timeout=30000)
            await session.wait(3000)  # Wait for React hydration

            if await self._check_captcha(session):
                ss = await session.screenshot("ashby_captcha")
                return ApplyResult(
                    success=False, status="paused",
                    failure_type="captcha",
                    error_message="CAPTCHA detected on Ashby form",
                    screenshot_path=ss, page_url=await session.get_page_url(),
                )

            # Click Apply button
            for sel in ['button:has-text("Apply")',
                        'a:has-text("Apply")',
                        '[data-ashby-apply-button]']:
                if await self._safe_click(session, sel, timeout=5000):
                    await session.wait(2000)
                    break

            await session.screenshot("ashby_before_fill")

            # Ashby uses label-based matching — try common patterns
            name = profile.get("name", "")
            last_name = profile.get("last_name", "")

            # Name fields
            page = await session.get_page()
            for label_text, value in [
                ("First Name", name), ("First name", name),
                ("Last Name", last_name), ("Last name", last_name),
                ("Full Name", f"{name} {last_name}".strip()),
                ("Name", f"{name} {last_name}".strip()),
            ]:
                try:
                    label = page.locator(f'label:has-text("{label_text}")').first
                    if await label.count() > 0:
                        input_id = await label.get_attribute("for")
                        if input_id:
                            await self._safe_fill(session, f"#{input_id}", value)
                        else:
                            # Try next sibling input
                            sibling = label.locator(".. input").first
                            if await sibling.count() > 0:
                                await sibling.fill(value)
                except Exception:
                    pass

            # Email
            for sel in ['input[type="email"]', 'input[name*="email"]',
                        'input[placeholder*="email"]', 'input[placeholder*="Email"]']:
                if await self._safe_fill(session, sel, profile.get("email", "")):
                    break

            # Phone
            for sel in ['input[type="tel"]', 'input[name*="phone"]',
                        'input[placeholder*="phone"]', 'input[placeholder*="Phone"]']:
                if await self._safe_fill(session, sel, profile.get("phone", "")):
                    break

            # LinkedIn
            for sel in ['input[name*="linkedin"]', 'input[placeholder*="LinkedIn"]',
                        'input[placeholder*="linkedin"]']:
                if await self._safe_fill(session, sel, profile.get("linkedin_url", "")):
                    break

            # Resume upload
            for sel in ['input[type="file"]',
                        'input[accept*=".pdf"]']:
                if await self._safe_upload(session, sel, resume_path):
                    await session.wait(2000)
                    break

            # Cover letter
            if cover_letter:
                for sel in ['textarea[name*="cover"]', 'textarea[placeholder*="Cover"]',
                            'textarea']:
                    if await self._safe_fill(session, sel, cover_letter):
                        break

            ss_filled = await session.screenshot("ashby_filled")
            await session.wait(1000)

            # Submit
            submitted = False
            for sel in ['button:has-text("Submit")',
                        'button:has-text("Submit Application")',
                        'button[type="submit"]',
                        'input[type="submit"]']:
                if await self._safe_click(session, sel, timeout=5000):
                    submitted = True
                    break

            if not submitted:
                dom = await session.get_dom_snapshot()
                return ApplyResult(
                    success=False, status="failed",
                    failure_type="form_error",
                    error_message="Could not find submit button on Ashby form",
                    screenshot_path=ss_filled, dom_snapshot=dom[:5000],
                    page_url=await session.get_page_url(),
                )

            await session.wait(3000)
            ss_confirm = await session.screenshot("ashby_confirmed")
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
                    confirmation_id="Submitted (Ashby)",
                    screenshot_path=ss_confirm, dom_snapshot=dom[:5000],
                    page_url=await session.get_page_url(),
                )

        except Exception as e:
            ss = ""
            try:
                ss = await session.screenshot("ashby_error")
            except Exception:
                pass
            return ApplyResult(
                success=False, status="failed",
                failure_type="unknown",
                error_message=f"Ashby adapter error: {str(e)[:200]}",
                screenshot_path=ss, page_url=url,
            )
