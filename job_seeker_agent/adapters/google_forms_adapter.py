"""
google_forms_adapter.py — Google Forms auto-fill adapter.

Extracted from agent.py into the standard adapter pipeline.
Uses Claude AI to map form field labels to profile data, then fills
the form using Playwright. Supports portal memory for caching the
scraping strategy and field-mapping patterns.
"""

import os
import json
import time
from adapters.base_adapter import ATSAdapter, ApplyResult

# Try loading .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class GoogleFormsAdapter(ATSAdapter):
    ats_type = "google_forms"

    async def fill_and_submit(self, session, url, profile, resume_path, cover_letter="", portal_memory=""):
        """Scrape Google Form fields, map via Claude, and auto-fill."""
        recorded_steps = []
        step_num = 0

        def record(description, selector="", action=""):
            nonlocal step_num
            step_num += 1
            recorded_steps.append(self._make_step(step_num, description, selector, action))

        try:
            await session.goto(url, wait_until="domcontentloaded", timeout=30000)
            await session.wait(3000)
            record("Navigate to Google Form", action="navigate")

            # Check if sign-in is required
            page_text = await session.get_page_text()
            if "sign in to google" in page_text.lower() or "sign in with google" in page_text.lower():
                ss = await session.screenshot("gforms_signin_required")
                record("Google sign-in required", action="blocked")
                return ApplyResult(
                    success=False, status="failed",
                    failure_type="auth_required",
                    error_message="Google Form requires sign-in",
                    screenshot_path=ss, page_url=await session.get_page_url(),
                    recorded_steps=recorded_steps,
                )

            if await self._check_captcha(session):
                ss = await session.screenshot("gforms_captcha")
                return ApplyResult(
                    success=False, status="paused",
                    failure_type="captcha",
                    error_message="CAPTCHA detected on Google Form",
                    screenshot_path=ss, page_url=await session.get_page_url(),
                    recorded_steps=recorded_steps,
                )

            # Scrape form fields
            page = await session.get_page()
            form_fields = await self._scrape_form_fields(page)
            record(f"Scraped {len(form_fields)} form fields", action="scrape")

            if not form_fields:
                ss = await session.screenshot("gforms_no_fields")
                return ApplyResult(
                    success=False, status="failed",
                    failure_type="form_error",
                    error_message="Could not detect form fields. Form may require sign-in or uses custom layout.",
                    screenshot_path=ss, page_url=await session.get_page_url(),
                    recorded_steps=recorded_steps,
                )

            # Build profile dict for Claude
            resume_data = self._build_resume_context(profile)

            # Get Claude to map fields to answers
            answers = self._get_form_answers(form_fields, resume_data, profile)
            record(f"Claude mapped {len(answers)} answers", action="ai_map")

            # Fill each field
            filled_count = 0
            for field in form_fields:
                label = field["label"]
                answer = answers.get(label, "")
                if not answer:
                    continue

                try:
                    if field["type"] in ("text", "textarea"):
                        input_el = page.locator(f"text={label}").locator("..").locator("input, textarea").first
                        await input_el.fill(str(answer))
                        await page.wait_for_timeout(300)
                        record(f"Fill '{label[:30]}'", f"text={label} >> input/textarea", "fill")
                        filled_count += 1

                    elif field["type"] == "radio_checkbox":
                        option_el = page.locator(f'[aria-label="{answer}"]').first
                        await option_el.click()
                        await page.wait_for_timeout(300)
                        record(f"Select '{answer[:30]}' for '{label[:20]}'", f'[aria-label="{answer}"]', "click")
                        filled_count += 1

                    elif field["type"] == "dropdown":
                        dropdown = page.locator(f"text={label}").locator("..").locator('[role="listbox"], select').first
                        await dropdown.click()
                        await page.wait_for_timeout(500)
                        option = page.locator(f'[role="option"]:has-text("{answer}")').first
                        await option.click()
                        await page.wait_for_timeout(300)
                        record(f"Select dropdown '{answer[:30]}'", f'[role="option"]:has-text("{answer}")', "click")
                        filled_count += 1

                except Exception as e:
                    # Field fill failed — continue with others
                    pass

            # Try file upload if resume_path exists
            try:
                file_input = page.locator('input[type="file"]').first
                if await file_input.count() > 0 and resume_path and os.path.exists(resume_path):
                    await file_input.set_input_files(resume_path)
                    await page.wait_for_timeout(1000)
                    record("Upload resume file", 'input[type="file"]', "upload")
            except Exception:
                pass  # File upload not present or failed

            # Screenshot before submit
            ss_filled = await session.screenshot("gforms_filled")

            # Submit
            submitted = False
            for sel in [
                '[role="button"]:has-text("Submit")',
                'input[type="submit"]',
                'button:has-text("Submit")',
                '[role="button"]:has-text("send")',
            ]:
                if await self._safe_click(session, sel, timeout=5000):
                    record("Click Submit", sel, "click")
                    submitted = True
                    break

            if not submitted:
                dom = await session.get_dom_snapshot()
                return ApplyResult(
                    success=False, status="failed",
                    failure_type="form_error",
                    error_message="Could not find Submit button on Google Form",
                    screenshot_path=ss_filled, dom_snapshot=dom[:5000],
                    page_url=await session.get_page_url(),
                    recorded_steps=recorded_steps,
                )

            await session.wait(3000)

            # Check confirmation
            ss_confirm = await session.screenshot("gforms_confirmed")
            confirmation = await self._check_confirmation(
                session,
                keywords=["your response has been recorded", "response has been submitted",
                           "thank you", "form submitted"],
            )
            dom = await session.get_dom_snapshot()
            record("Check confirmation", action="verify")

            if confirmation:
                return ApplyResult(
                    success=True, status="applied",
                    confirmation_id=confirmation[:200],
                    screenshot_path=ss_confirm, dom_snapshot=dom[:5000],
                    page_url=await session.get_page_url(),
                    recorded_steps=recorded_steps,
                )
            else:
                # Google Forms usually show confirmation — if not, might be multi-page
                return ApplyResult(
                    success=False, status="failed",
                    failure_type="form_error",
                    error_message=f"Form submitted but no confirmation detected (filled {filled_count} fields)",
                    screenshot_path=ss_confirm, dom_snapshot=dom[:5000],
                    page_url=await session.get_page_url(),
                    recorded_steps=recorded_steps,
                )

        except Exception as e:
            ss = ""
            try:
                ss = await session.screenshot("gforms_error")
            except Exception:
                pass
            return ApplyResult(
                success=False, status="failed",
                failure_type="unknown",
                error_message=f"Google Forms adapter error: {str(e)[:200]}",
                screenshot_path=ss, page_url=url,
                recorded_steps=recorded_steps,
            )

    async def _scrape_form_fields(self, page) -> list[dict]:
        """Scrape all form fields from a Google Form page.

        Returns a list of dicts with keys: label, type, options
        """
        # Primary scraper: [data-params] containers
        form_fields = await page.evaluate("""() => {
            const fields = [];

            document.querySelectorAll('[data-params]').forEach(container => {
                const label = container.querySelector('[role="heading"]')?.innerText?.trim()
                            || container.querySelector('label')?.innerText?.trim()
                            || container.querySelector('.freebirdFormviewerComponentsQuestionBaseTitle')?.innerText?.trim();

                if (!label) return;

                const options = [...container.querySelectorAll('[role="radio"], [role="checkbox"]')]
                    .map(el => el.getAttribute('aria-label') || el.innerText?.trim())
                    .filter(Boolean);

                const dropdownOptions = [...container.querySelectorAll('[role="option"]')]
                    .map(el => el.innerText?.trim())
                    .filter(Boolean);

                const inputType = container.querySelector('input[type="text"]')    ? 'text'
                                : container.querySelector('textarea')              ? 'textarea'
                                : options.length > 0                               ? 'radio_checkbox'
                                : dropdownOptions.length > 0                       ? 'dropdown'
                                : 'unknown';

                fields.push({
                    label,
                    type: inputType,
                    options: [...options, ...dropdownOptions],
                });
            });

            return fields;
        }""")

        if not form_fields:
            # Fallback: newer Google Forms layout
            form_fields = await page.evaluate("""() => {
                const fields = [];
                document.querySelectorAll('.freebirdFormviewerComponentsQuestionBaseRoot').forEach(q => {
                    const label = q.querySelector('.freebirdFormviewerComponentsQuestionBaseTitle')?.innerText?.trim();
                    if (!label) return;
                    const options = [...q.querySelectorAll('.docssharedWizToggleLabeledLabelText')]
                        .map(el => el.innerText?.trim()).filter(Boolean);
                    const isTextarea = !!q.querySelector('textarea');
                    const isText = !!q.querySelector('input[type="text"]');
                    fields.push({
                        label,
                        type: isTextarea ? 'textarea' : isText ? 'text' : options.length ? 'radio_checkbox' : 'unknown',
                        options,
                    });
                });
                return fields;
            }""")

        return form_fields or []

    def _build_resume_context(self, profile: dict) -> dict:
        """Build a resume-like context dict from the profile for Claude."""
        return {
            "full_name": f"{profile.get('name', '')} {profile.get('last_name', '')}".strip(),
            "email": profile.get("email", ""),
            "phone": profile.get("phone", ""),
            "linkedin_url": profile.get("linkedin_url", ""),
            "github_url": profile.get("github_url", ""),
            "current_company": profile.get("current_company", ""),
            "current_title": profile.get("current_title", ""),
        }

    def _get_form_answers(self, form_fields: list[dict], resume_data: dict, user_data: dict) -> dict:
        """Use Claude to map form field labels to the best answers from the profile.

        Returns: { "field_label": "answer", ... }
        """
        try:
            import anthropic

            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            if not api_key or api_key == "your_claude_api_key":
                return self._fallback_mapping(form_fields, resume_data)

            client = anthropic.Anthropic(api_key=api_key)

            combined_profile = {
                "resume": resume_data,
                "user_profile": user_data,
            }

            prompt = f"""You are an expert job application assistant. 
You have a candidate's full profile and a list of Google Form fields to fill.

Your job:
1. For each form field, find the best matching answer from the candidate profile.
2. Keep answers concise and professional.
3. For Yes/No or multiple-choice fields, pick the closest matching option from the "options" list.
4. If information is genuinely not available, use an empty string "".
5. Return ONLY a JSON object: {{ "field_label": "your_answer", ... }}

CANDIDATE PROFILE:
{json.dumps(combined_profile, indent=2)}

FORM FIELDS TO FILL:
{json.dumps(form_fields, indent=2)}

Return ONLY valid JSON. No markdown, no explanation."""

            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )

            raw = response.content[0].text.strip()
            # Strip markdown fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            return json.loads(raw.strip())

        except Exception as e:
            print(f"  [GForms] Claude mapping failed: {e}. Using fallback.")
            return self._fallback_mapping(form_fields, resume_data)

    def _fallback_mapping(self, form_fields: list[dict], resume_data: dict) -> dict:
        """Simple keyword-based field mapping when Claude is unavailable."""
        answers = {}
        for field in form_fields:
            label_lower = field["label"].lower()
            if any(kw in label_lower for kw in ["name", "full name"]):
                answers[field["label"]] = resume_data.get("full_name", "")
            elif "email" in label_lower:
                answers[field["label"]] = resume_data.get("email", "")
            elif "phone" in label_lower or "mobile" in label_lower:
                answers[field["label"]] = resume_data.get("phone", "")
            elif "linkedin" in label_lower:
                answers[field["label"]] = resume_data.get("linkedin_url", "")
            elif "github" in label_lower:
                answers[field["label"]] = resume_data.get("github_url", "")
        return answers
