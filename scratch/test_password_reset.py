import os
import sys
import random
from datetime import datetime, timezone, timedelta

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Load environment variables
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

import core.database as db
from core.app import send_smtp_email

def main():
    print("=== SMTP and Password Reset Flow Test ===")
    
    # 1. Print current SMTP configurations (masked password)
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = os.environ.get("SMTP_PORT")
    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    smtp_from = os.environ.get("SMTP_FROM")
    
    print(f"SMTP Host: {smtp_host}")
    print(f"SMTP Port: {smtp_port}")
    print(f"SMTP User: {smtp_user}")
    print(f"SMTP Password: {smtp_password[:3] + '...' if smtp_password else 'Not set'}")
    print(f"SMTP From: {smtp_from}")
    print("-" * 40)

    target_email = "vibudhsharma24@gmail.com"
    
    # 2. Check if user exists, create if not
    print(f"Checking if user '{target_email}' exists in database...")
    db.init_db()
    user = db.get_user_by_email(target_email)
    
    if not user:
        print(f"User '{target_email}' not found. Creating user profile...")
        try:
            user = db.save_user(
                name="Vibudh",
                last_name="Sharma",
                email=target_email,
                password="OldPassword123",
                linkedin_url="https://www.linkedin.com/in/vibudhsharma",
                mobile_number="9999999999"
            )
            # Approve user status so they are active
            db.approve_user(user["id"])
            print(f"✅ User created successfully with ID: {user['id']}")
        except Exception as e:
            print(f"❌ Failed to create user: {e}")
            return
    else:
        print(f"✅ User found in database with ID: {user['id']}")

    # 3. Generate a random 6-digit OTP
    otp = f"{random.randint(100000, 999999)}"
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
    
    print(f"Generated OTP: {otp} (Expires at: {expires_at})")
    
    # 4. Save the OTP to the database
    print("Saving reset code to the database...")
    db.update_user_reset_code(target_email, otp, expires_at)
    print("✅ Reset code saved successfully.")

    # 5. Send the SMTP email
    print(f"Sending SMTP email with OTP to {target_email}...")
    email_subject = "Your Password Reset OTP"
    email_body = f"""
    <html>
      <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
          <h2 style="color: #2563eb; margin-top: 0;">Password Reset Request</h2>
          <p>This is your OTP code for resetting your password. Use it to complete the reset process:</p>
          <p style="font-size: 32px; font-weight: bold; color: #2563eb; letter-spacing: 4px; padding: 10px 0; margin: 10px 0; text-align: center; background-color: #f3f4f6; border-radius: 4px;">{otp}</p>
          <p style="color: #6b7280; font-size: 14px;">This code will expire in 15 minutes. If you did not request a password reset, please ignore this email.</p>
          <hr style="border: 0; border-top: 1px solid #e5e7eb; margin: 20px 0;" />
          <p style="font-size: 14px; color: #9ca3af;">Best regards,<br/>The IITIIMJobAssistant Team</p>
        </div>
      </body>
    </html>
    """
    
    sent = send_smtp_email(target_email, email_subject, email_body)
    if sent:
        print("✅ SMTP email sent successfully.")
    else:
        print("❌ SMTP email failed to send. Please check your configurations or Gmail credentials.")
        return

    # 6. Simulate changing the password and updating database
    new_password = "NewSecurePassword123"
    print(f"Simulating user changing password to '{new_password}'...")
    
    # Verify the code (normally done via API, we query and verify)
    updated_user = db.get_user_by_email(target_email)
    stored_code = updated_user.get("reset_code")
    stored_expires_at = updated_user.get("reset_code_expires_at")
    
    if stored_code == otp:
        print("OTP verified successfully against the database!")
        
        # Update user password in the database
        success = db.update_user_password(updated_user["id"], new_password)
        if success:
            db.clear_user_reset_code(target_email)
            print("✅ Password updated in the database and reset code cleared successfully.")
        else:
            print("❌ Failed to update password in the database.")
    else:
        print("❌ OTP verification failed (mismatch or not stored).")

if __name__ == "__main__":
    main()
