# Phone Number Authentication Handler
# Copyright (C) @Wolfy004

import os
import time
import asyncio
from pyrogram import Client
from pyrogram.errors import SessionPasswordNeeded, PhoneCodeInvalid, PhoneCodeExpired, PasswordHashInvalid, FloodWait
from logger import LOGGER

class PhoneAuthHandler:
    """Handle phone number based authentication for users"""

    def __init__(self, api_id, api_hash):
        self.api_id = api_id
        self.api_hash = api_hash
        self.pending_auth = {}
        self._cleanup_task = None

    async def send_otp(self, user_id: int, phone_number: str):
        """
        Send OTP to user's phone number
        Returns: (success: bool, message: str, phone_code_hash: str or None)
        """
        try:
            # Use minimal resources for auth clients to save RAM
            IS_CONSTRAINED = bool(os.getenv('RENDER') or os.getenv('RENDER_EXTERNAL_URL') or os.getenv('REPLIT_DEPLOYMENT') or os.getenv('REPL_ID'))
            
            session_name = f"user_{user_id}"

            client = Client(
                session_name,
                api_id=self.api_id,
                api_hash=self.api_hash,
                workers=1 if IS_CONSTRAINED else 2,
                max_concurrent_transmissions=1 if IS_CONSTRAINED else 2,
                sleep_threshold=30,
                in_memory=True  # Don't write to disk - saves I/O and cleanup
            )

            await client.connect()

            sent_code_info = await client.send_code(phone_number)
            phone_code_hash = sent_code_info.phone_code_hash

            self.pending_auth[user_id] = {
                'phone_number': phone_number,
                'phone_code_hash': phone_code_hash,
                'client': client,
                'session_name': session_name,
                'created_at': time.time()  # Track creation time for cleanup
            }

            LOGGER(__name__).info(f"OTP sent to {phone_number} for user {user_id}")

            return True, f"✅ **OTP sent to {phone_number}**\n\nPlease send the code using:\n`/verify 1 2 3 4 5` (with spaces between each digit)\n\n**Example:** If code is 12345, send:\n`/verify 1 2 3 4 5`", phone_code_hash

        except FloodWait as e:
            LOGGER(__name__).error(f"FloodWait error: {e}")
            return False, f"❌ **Rate limit exceeded. Please wait {e.value} seconds before trying again.**", None

        except Exception as e:
            LOGGER(__name__).error(f"Error sending OTP to {phone_number}: {e}")
            return False, f"❌ **Failed to send OTP: {str(e)}**\n\nMake sure the phone number is in international format (e.g., +1234567890)", None

    async def verify_otp(self, user_id: int, otp_code: str):
        """
        Verify OTP code
        Returns: (success: bool, message: str, needs_2fa: bool)
        """
        if user_id not in self.pending_auth:
            return False, "❌ **No pending authentication found.**\n\nPlease start with `/login <phone_number>` first.", False

        auth_data = self.pending_auth[user_id]
        client = auth_data['client']
        phone_number = auth_data['phone_number']
        phone_code_hash = auth_data['phone_code_hash']

        # Strip spaces and any non-digit characters from OTP code
        # This allows users to enter codes like "1 2 3 4 5" or "12345"
        cleaned_code = ''.join(filter(str.isdigit, otp_code))

        try:
            LOGGER(__name__).info(f"Attempting sign_in for user {user_id}")
            await client.sign_in(
                phone_number=phone_number,
                phone_code_hash=phone_code_hash,
                phone_code=cleaned_code
            )
            LOGGER(__name__).info(f"Sign_in successful for user {user_id}, exporting session...")

            session_string = await client.export_session_string()
            LOGGER(__name__).info(f"Session string exported for user {user_id}, length: {len(session_string) if session_string else 0}")

            await client.disconnect()
            LOGGER(__name__).info(f"Client disconnected for user {user_id}")

            del self.pending_auth[user_id]
            LOGGER(__name__).info(f"Removed from pending_auth for user {user_id}")

            LOGGER(__name__).info(f"User {user_id} successfully authenticated with phone {phone_number}, returning session_string")

            return True, "✅ **Authentication successful!**\n\nYou can now download content from channels you've joined.", False, session_string

        except SessionPasswordNeeded:
            LOGGER(__name__).info(f"2FA required for user {user_id}")
            return False, "🔐 **Two-Factor Authentication (2FA) detected!**\n\nPlease send your 2FA password using:\n`/password <YOUR_2FA_PASSWORD>`", True, None

        except PhoneCodeInvalid:
            LOGGER(__name__).error(f"Invalid OTP for user {user_id}")
            return False, "❌ **Invalid OTP code.**\n\nPlease try again with `/verify 1 2 3 4 5` (spaces between digits)\n\nOr restart the process with `/login <phone_number>`", False, None

        except PhoneCodeExpired:
            LOGGER(__name__).warning(f"OTP code expired for user {user_id}")
            
            if user_id in self.pending_auth:
                try:
                    await self.pending_auth[user_id]['client'].disconnect()
                except:
                    pass
                del self.pending_auth[user_id]
            
            return False, "⏰ **OTP code has expired!**\n\nTelegram OTP codes expire after a few minutes.\n\nPlease get a new code with:\n`/login <phone_number>`", False, None

        except Exception as e:
            LOGGER(__name__).error(f"Error verifying OTP for user {user_id}: {e}")

            if user_id in self.pending_auth:
                try:
                    await self.pending_auth[user_id]['client'].disconnect()
                except:
                    pass
                del self.pending_auth[user_id]

            return False, f"❌ **Verification failed: {str(e)}**\n\nPlease restart with `/login <phone_number>`", False, None

    async def verify_2fa_password(self, user_id: int, password: str):
        """
        Verify 2FA password
        Returns: (success: bool, message: str, session_string: str or None)
        """
        if user_id not in self.pending_auth:
            return False, "❌ **No pending authentication found.**\n\nPlease start with `/login <phone_number>` first.", None

        auth_data = self.pending_auth[user_id]
        client = auth_data['client']

        try:
            await client.check_password(password)

            session_string = await client.export_session_string()

            await client.disconnect()

            del self.pending_auth[user_id]

            LOGGER(__name__).info(f"User {user_id} successfully authenticated with 2FA")

            return True, "✅ **Authentication successful!**\n\nYou can now download content from channels you've joined.", session_string

        except PasswordHashInvalid:
            LOGGER(__name__).error(f"Invalid 2FA password for user {user_id}")
            return False, "❌ **Invalid 2FA password.**\n\nPlease try again with `/password <YOUR_2FA_PASSWORD>`\n\nOr restart the process with `/login <phone_number>`", None

        except Exception as e:
            LOGGER(__name__).error(f"Error verifying 2FA for user {user_id}: {e}")

            if user_id in self.pending_auth:
                try:
                    await self.pending_auth[user_id]['client'].disconnect()
                except:
                    pass
                del self.pending_auth[user_id]

            return False, f"❌ **2FA verification failed: {str(e)}**\n\nPlease restart with `/login <phone_number>`", None

    async def cancel_auth(self, user_id: int):
        """Cancel pending authentication"""
        if user_id in self.pending_auth:
            try:
                await self.pending_auth[user_id]['client'].disconnect()
            except:
                pass
            del self.pending_auth[user_id]
            return True, "✅ **Authentication cancelled.**"
        return False, "❌ **No pending authentication to cancel.**"

    def has_pending_auth(self, user_id: int) -> bool:
        """Check if user has pending authentication"""
        return user_id in self.pending_auth
    
    def start_cleanup_task(self):
        """Start the cleanup task (call this after event loop is running)"""
        if not self._cleanup_task:
            self._cleanup_task = asyncio.create_task(self._cleanup_stale_sessions())
            LOGGER(__name__).info("Started auth session cleanup task")
    
    async def _cleanup_stale_sessions(self):
        """
        Background task to cleanup stale auth sessions (memory leak prevention)
        OTP codes expire after ~10 minutes, so we cleanup sessions older than 15 minutes
        This prevents memory leaks from users who start login but never finish
        Each pending session holds a Pyrogram Client (~100MB), so this is critical for Render
        """
        while True:
            try:
                await asyncio.sleep(300)  # Check every 5 minutes
                
                current_time = time.time()
                stale_timeout = 900  # 15 minutes in seconds
                
                stale_users = []
                for user_id, auth_data in self.pending_auth.items():
                    if current_time - auth_data.get('created_at', 0) > stale_timeout:
                        stale_users.append(user_id)
                
                # Cleanup stale sessions
                for user_id in stale_users:
                    try:
                        LOGGER(__name__).info(f"Cleaning up stale auth session for user {user_id}")
                        await self.pending_auth[user_id]['client'].disconnect()
                        del self.pending_auth[user_id]
                    except Exception as e:
                        LOGGER(__name__).error(f"Error cleaning up session for user {user_id}: {e}")
                
                if stale_users:
                    LOGGER(__name__).info(f"Cleaned up {len(stale_users)} stale auth session(s)")
                    
            except Exception as e:
                LOGGER(__name__).error(f"Error in auth session cleanup task: {e}")
                await asyncio.sleep(60)  # Wait 1 minute before retry on error