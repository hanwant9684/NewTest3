import os
import secrets
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load environment variables
load_dotenv("config.env")
load_dotenv(".env")  # Load .env as well for fallback

from logger import LOGGER
from database import db

PREMIUM_DOWNLOADS = 5
SESSION_VALIDITY_MINUTES = 30

class AdMonetization:
    def __init__(self):
        # Check all URL shortener API keys
        self.services = {
            'droplink': os.getenv('DROPLINK_API_KEY'),
            'gplinks': os.getenv('GPLINKS_API_KEY'),
            'arlinks': os.getenv('ARLINKS_API_KEY'),
            'upshrink': os.getenv('UPSHRINK_API_KEY')
        }
        
        configured_services = [name for name, key in self.services.items() if key]
        if configured_services:
            LOGGER(__name__).info(f"URL shortener services configured: {', '.join(configured_services)}")
        else:
            LOGGER(__name__).warning("No URL shortener API keys configured - ad monetization disabled")
    
    def create_ad_session(self, user_id: int) -> str:
        """Create a temporary session for ad watching"""
        session_id = secrets.token_hex(16)
        db.create_ad_session(session_id, user_id)
        
        LOGGER(__name__).info(f"Created ad session {session_id} for user {user_id}")
        return session_id
    
    def verify_ad_completion(self, session_id: str) -> tuple[bool, str, str]:
        """Verify that user clicked through droplink and generate verification code"""
        session_data = db.get_ad_session(session_id)
        
        if not session_data:
            return False, "", "❌ Invalid or expired session. Please start over with /getpremium"
        
        # Check if session expired (30 minutes max)
        elapsed_time = datetime.now() - session_data['created_at']
        if elapsed_time > timedelta(minutes=SESSION_VALIDITY_MINUTES):
            db.delete_ad_session(session_id)
            return False, "", "⏰ Session expired. Please start over with /getpremium"
        
        # Atomically mark session as used (prevents race condition)
        success = db.mark_ad_session_used(session_id)
        if not success:
            return False, "", "❌ This session has already been used. Please use /getpremium to get a new link."
        
        # Generate verification code
        verification_code = self._generate_verification_code(session_data['user_id'])
        
        # Delete session after successful verification
        db.delete_ad_session(session_id)
        
        LOGGER(__name__).info(f"User {session_data['user_id']} completed ad session {session_id}, generated code {verification_code}")
        return True, verification_code, "✅ Ad completed! Here's your verification code"
    
    def _generate_verification_code(self, user_id: int) -> str:
        """Generate verification code after ad is watched"""
        code = secrets.token_hex(4).upper()
        db.create_verification_code(code, user_id)
        
        LOGGER(__name__).info(f"Generated verification code {code} for user {user_id}")
        return code
    
    def verify_code(self, code: str, user_id: int) -> tuple[bool, str]:
        """Verify user's code and grant free downloads"""
        code = code.upper().strip()
        
        verification_data = db.get_verification_code(code)
        
        if not verification_data:
            return False, "❌ **Invalid verification code.**\n\nPlease make sure you entered the code correctly or get a new one with `/getpremium`"
        
        if verification_data['user_id'] != user_id:
            return False, "❌ **This verification code belongs to another user.**"
        
        created_at = verification_data['created_at']
        if datetime.now() - created_at > timedelta(minutes=30):
            db.delete_verification_code(code)
            return False, "⏰ **Verification code has expired.**\n\nCodes expire after 30 minutes. Please get a new one with `/getpremium`"
        
        db.delete_verification_code(code)
        
        # Grant ad downloads
        db.add_ad_downloads(user_id, PREMIUM_DOWNLOADS)
        
        LOGGER(__name__).info(f"User {user_id} successfully verified code {code}, granted {PREMIUM_DOWNLOADS} ad downloads")
        return True, f"✅ **Verification successful!**\n\nYou now have **{PREMIUM_DOWNLOADS} free download(s)**!"
    
    def _shorten_with_droplink(self, long_url: str) -> str:
        """Shorten URL using droplink.co API"""
        import requests
        
        api_key = self.services.get('droplink')
        if not api_key:
            LOGGER(__name__).warning("DROPLINK_API_KEY not configured, returning original URL")
            return long_url
        
        try:
            response = requests.get(
                "https://droplink.co/api",
                params={
                    "api": api_key,
                    "url": long_url
                },
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get("status") == "success":
                    short_url = data.get("shortenedUrl")
                    
                    if short_url:
                        LOGGER(__name__).info(f"Successfully shortened URL via droplink.co: {short_url}")
                        return short_url
                    else:
                        LOGGER(__name__).error(f"Droplink API response missing shortenedUrl: {data}")
                else:
                    LOGGER(__name__).error(f"Droplink API returned non-success status: {data}")
            else:
                LOGGER(__name__).error(f"Droplink API error {response.status_code}: {response.text}")
        
        except Exception as e:
            LOGGER(__name__).error(f"Failed to shorten URL with droplink.co: {e}")
        
        return long_url
    
    def _shorten_with_gplinks(self, long_url: str) -> str:
        """Shorten URL using gplinks.co API"""
        import requests
        
        api_key = self.services.get('gplinks')
        if not api_key:
            LOGGER(__name__).warning("GPLINKS_API_KEY not configured, falling back to droplink")
            return self._shorten_with_droplink(long_url)
        
        try:
            response = requests.get(
                "https://api.gplinks.com/api",
                params={
                    "api": api_key,
                    "url": long_url
                },
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get("status") == "success":
                    short_url = data.get("shortenedUrl")
                    
                    if short_url:
                        LOGGER(__name__).info(f"Successfully shortened URL via gplinks.com: {short_url}")
                        return short_url
                    else:
                        LOGGER(__name__).error(f"GPLinks API response missing shortenedUrl: {data}")
                else:
                    LOGGER(__name__).error(f"GPLinks API returned non-success status: {data}")
            else:
                LOGGER(__name__).error(f"GPLinks API error {response.status_code}: {response.text}")
        
        except Exception as e:
            LOGGER(__name__).error(f"Failed to shorten URL with gplinks.com: {e}")
        
        # Fallback to droplink on failure
        LOGGER(__name__).info("Falling back to droplink.co")
        return self._shorten_with_droplink(long_url)
    
    def _shorten_with_arlinks(self, long_url: str) -> str:
        """Shorten URL using arlinks.in API"""
        import requests
        
        api_key = self.services.get('arlinks')
        if not api_key:
            LOGGER(__name__).warning("ARLINKS_API_KEY not configured, falling back to droplink")
            return self._shorten_with_droplink(long_url)
        
        try:
            # ARLinks likely follows similar pattern to droplink/gplinks
            response = requests.get(
                "https://arlinks.in/api",
                params={
                    "api": api_key,
                    "url": long_url
                },
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get("status") == "success":
                    short_url = data.get("shortenedUrl")
                    
                    if short_url:
                        LOGGER(__name__).info(f"Successfully shortened URL via arlinks.in: {short_url}")
                        return short_url
                    else:
                        LOGGER(__name__).error(f"ARLinks API response missing shortenedUrl: {data}")
                else:
                    LOGGER(__name__).error(f"ARLinks API returned non-success status: {data}")
            else:
                LOGGER(__name__).error(f"ARLinks API error {response.status_code}: {response.text}")
        
        except Exception as e:
            LOGGER(__name__).error(f"Failed to shorten URL with arlinks.in: {e}")
        
        # Fallback to droplink on failure
        LOGGER(__name__).info("Falling back to droplink.co")
        return self._shorten_with_droplink(long_url)
    
    def _shorten_with_upshrink(self, long_url: str) -> str:
        """Shorten URL using upshrink.com API"""
        import requests
        
        api_key = self.services.get('upshrink')
        if not api_key:
            LOGGER(__name__).warning("UPSHRINK_API_KEY not configured, falling back to droplink")
            return self._shorten_with_droplink(long_url)
        
        try:
            # UpShrink likely follows similar pattern to droplink/gplinks
            response = requests.get(
                "https://upshrink.com/api",
                params={
                    "api": api_key,
                    "url": long_url
                },
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get("status") == "success":
                    short_url = data.get("shortenedUrl")
                    
                    if short_url:
                        LOGGER(__name__).info(f"Successfully shortened URL via upshrink.com: {short_url}")
                        return short_url
                    else:
                        LOGGER(__name__).error(f"UpShrink API response missing shortenedUrl: {data}")
                else:
                    LOGGER(__name__).error(f"UpShrink API returned non-success status: {data}")
            else:
                LOGGER(__name__).error(f"UpShrink API error {response.status_code}: {response.text}")
        
        except Exception as e:
            LOGGER(__name__).error(f"Failed to shorten URL with upshrink.com: {e}")
        
        # Fallback to droplink on failure
        LOGGER(__name__).info("Falling back to droplink.co")
        return self._shorten_with_droplink(long_url)
    
    def generate_droplink_ad_link(self, user_id: int, bot_domain: str | None = None) -> tuple[str, str]:
        """Generate monetized ad link using rotation system (droplink -> gplinks -> arlinks -> upshrink)"""
        session_id = self.create_ad_session(user_id)
        
        # Get current rotation state
        rotation_state = db.get_shortener_rotation_state()
        current_index = rotation_state.get('current_index', 0)
        
        # Map index to service
        service_map = {
            0: ('droplink', self._shorten_with_droplink),
            1: ('gplinks', self._shorten_with_gplinks),
            2: ('arlinks', self._shorten_with_arlinks),
            3: ('upshrink', self._shorten_with_upshrink)
        }
        
        service_name, shorten_func = service_map.get(current_index, ('droplink', self._shorten_with_droplink))
        
        LOGGER(__name__).info(f"Using {service_name} for ad link (rotation index: {current_index}, download {rotation_state.get('downloads_in_cycle', 0) + 1}/5)")
        
        # Increment rotation counter for next time
        db.increment_shortener_rotation()
        
        if bot_domain:
            verify_url = f"{bot_domain}/verify-ad?session={session_id}"
            short_url = shorten_func(verify_url)
            return session_id, short_url
        
        return session_id, "https://example.com/verify"
    
    def get_premium_downloads(self) -> int:
        """Get number of downloads given for watching ads"""
        return PREMIUM_DOWNLOADS

ad_monetization = AdMonetization()
