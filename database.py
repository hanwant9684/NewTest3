# Copyright (C) @Wolfy004
# Channel: https://t.me/Wolfy004

import os
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure
from logger import LOGGER
from cache import get_cache

class DatabaseManager:
    def __init__(self, connection_string: Optional[str] = None):
        if not connection_string:
            connection_string = os.getenv("MONGODB_URI", "")
        
        if not connection_string:
            raise ValueError("MongoDB connection string is required. Set MONGODB_URI environment variable.")
        
        try:
            # Optimized connection settings for Render/Replit
            # Detect constrained environments
            IS_CONSTRAINED = bool(
                os.getenv('RENDER') or 
                os.getenv('RENDER_EXTERNAL_URL') or 
                os.getenv('REPLIT_DEPLOYMENT') or 
                os.getenv('REPL_ID')
            )
            
            # ULTRA-aggressive pool reduction for Render's 512MB (saves ~50-60MB)
            # 2 connections is enough for light concurrent usage
            pool_size = 2 if IS_CONSTRAINED else 10
            
            self.client = MongoClient(
                connection_string,
                maxPoolSize=pool_size,  # 3 for Render, 10 for VPS
                minPoolSize=1,
                maxIdleTimeMS=30000,  # Close idle connections faster (30s vs 45s)
                serverSelectionTimeoutMS=5000,  # Faster timeout
                connectTimeoutMS=10000,
                socketTimeoutMS=10000,
                retryWrites=True,
                w='majority'
            )
            self.client.admin.command('ping')
            LOGGER(__name__).info("Successfully connected to MongoDB!")
            
            self.db = self.client.get_database("telegram_bot")
            self.cache = get_cache()
            
            self.users = self.db['users']
            self.daily_usage = self.db['daily_usage']
            self.admins = self.db['admins']
            self.broadcasts = self.db['broadcasts']
            self.ad_sessions = self.db['ad_sessions']
            self.ad_verifications = self.db['ad_verifications']
            
            self.init_database()
            
        except ConnectionFailure as e:
            LOGGER(__name__).error(f"Failed to connect to MongoDB: {e}")
            raise
        except Exception as e:
            LOGGER(__name__).error(f"MongoDB initialization error: {e}")
            raise

    def init_database(self):
        """Initialize database indexes"""
        try:
            self.users.create_index("user_id", unique=True)
            self.daily_usage.create_index([("user_id", 1), ("date", 1)], unique=True)
            self.admins.create_index("user_id", unique=True)
            self.ad_sessions.create_index("session_id", unique=True)
            self.ad_sessions.create_index("created_at", expireAfterSeconds=300)
            self.ad_verifications.create_index("code", unique=True)
            self.ad_verifications.create_index("created_at", expireAfterSeconds=1800)
            
            LOGGER(__name__).info("Database indexes created successfully")
        except Exception as e:
            LOGGER(__name__).error(f"Error creating indexes: {e}")

    def add_user(self, user_id: int, username: Optional[str] = None, first_name: Optional[str] = None,
                 last_name: Optional[str] = None, user_type: str = 'free') -> bool:
        """Add new user or update basic profile information (preserves roles and settings)"""
        try:
            now = datetime.now()
            
            existing_user = self.users.find_one({"user_id": user_id})
            
            if not existing_user:
                user_doc = {
                    "user_id": user_id,
                    "username": username,
                    "first_name": first_name,
                    "last_name": last_name,
                    "user_type": user_type,
                    "subscription_end": None,
                    "premium_source": None,
                    "joined_date": now,
                    "last_activity": now,
                    "is_banned": False,
                    "session_string": None,
                    "custom_thumbnail": None,
                    "ad_downloads": 0,
                    "ad_downloads_reset_date": now.strftime('%Y-%m-%d')
                }
                self.users.insert_one(user_doc)
            else:
                update_fields = {
                    "last_activity": now
                }
                if username:
                    update_fields["username"] = username
                if first_name:
                    update_fields["first_name"] = first_name
                if last_name:
                    update_fields["last_name"] = last_name
                
                self.users.update_one(
                    {"user_id": user_id},
                    {"$set": update_fields}
                )
            
            return True
        except Exception as e:
            LOGGER(__name__).error(f"Error adding user {user_id}: {e}")
            return False

    def get_user(self, user_id: int) -> Optional[Dict]:
        """Get user information (with caching)"""
        cache_key = f"user_{user_id}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        
        try:
            user = self.users.find_one({"user_id": user_id})
            if user:
                user.pop('_id', None)
                self.cache.set(cache_key, user, ttl=180)  # Cache for 3 minutes
            return user
        except Exception as e:
            LOGGER(__name__).error(f"Error getting user {user_id}: {e}")
            return None

    def get_user_type(self, user_id: int) -> str:
        """Get user type (free, paid, admin)"""
        user = self.get_user(user_id)
        if not user:
            return 'free'

        if self.is_admin(user_id):
            return 'admin'

        if user.get('user_type') == 'paid' and user.get('subscription_end'):
            if isinstance(user['subscription_end'], str):
                # Try parsing with time first, fallback to date only
                try:
                    sub_end = datetime.strptime(user['subscription_end'], '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    sub_end = datetime.strptime(user['subscription_end'], '%Y-%m-%d')
            else:
                sub_end = user['subscription_end']
            
            if sub_end > datetime.now():
                return 'paid'
            else:
                # Premium expired, downgrade to free and clear subscription_end and premium_source
                premium_source = user.get('premium_source', 'unknown')
                self.users.update_one(
                    {"user_id": user_id},
                    {"$set": {"user_type": "free", "subscription_end": None, "premium_source": None}}
                )
                LOGGER(__name__).info(f"User {user_id} {premium_source} premium expired, downgraded to free")

        return 'free'

    def is_admin(self, user_id: int) -> bool:
        """Check if user is admin (with caching)"""
        cache_key = f"admin_{user_id}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        
        try:
            admin = self.admins.find_one({"user_id": user_id})
            is_admin = admin is not None
            self.cache.set(cache_key, is_admin, ttl=300)  # Cache for 5 minutes
            return is_admin
        except Exception as e:
            LOGGER(__name__).error(f"Error checking admin status for {user_id}: {e}")
            return False

    def add_admin(self, user_id: int, added_by: int) -> bool:
        """Add user as admin"""
        try:
            admin_doc = {
                "user_id": user_id,
                "added_by": added_by,
                "added_date": datetime.now()
            }
            self.admins.update_one(
                {"user_id": user_id},
                {"$set": admin_doc},
                upsert=True
            )
            # Invalidate cache
            self.cache.delete(f"admin_{user_id}")
            self.cache.delete(f"user_{user_id}")
            return True
        except Exception as e:
            LOGGER(__name__).error(f"Error adding admin {user_id}: {e}")
            return False

    def remove_admin(self, user_id: int) -> bool:
        """Remove admin privileges"""
        try:
            result = self.admins.delete_one({"user_id": user_id})
            # Invalidate cache
            self.cache.delete(f"admin_{user_id}")
            self.cache.delete(f"user_{user_id}")
            return result.deleted_count > 0
        except Exception as e:
            LOGGER(__name__).error(f"Error removing admin {user_id}: {e}")
            return False

    def set_user_type(self, user_id: int, user_type: str, days: int = 30) -> bool:
        """Set user type and subscription (for paid monthly subscriptions)"""
        try:
            update_data = {"user_type": user_type}
            
            if user_type == 'paid':
                subscription_end = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')
                update_data["subscription_end"] = subscription_end
                update_data["premium_source"] = "paid"
            else:
                update_data["subscription_end"] = None
                update_data["premium_source"] = None
            
            result = self.users.update_one(
                {"user_id": user_id},
                {"$set": update_data}
            )
            return result.modified_count > 0 or result.matched_count > 0
        except Exception as e:
            LOGGER(__name__).error(f"Error setting user type for {user_id}: {e}")
            return False

    def set_premium(self, user_id: int, expiry_datetime: str, source: str = "ads") -> bool:
        """Set premium subscription with specific expiry datetime (for ad-based premium)
        
        Args:
            user_id: User ID
            expiry_datetime: Expiry datetime string
            source: Premium source ('ads' or 'paid')
        
        Returns:
            bool: Success status
        """
        try:
            user = self.get_user(user_id)
            
            if user and user.get('user_type') == 'paid':
                existing_end = user.get('subscription_end')
                if existing_end:
                    if isinstance(existing_end, str):
                        try:
                            existing_expiry = datetime.strptime(existing_end, '%Y-%m-%d %H:%M:%S')
                        except ValueError:
                            existing_expiry = datetime.strptime(existing_end, '%Y-%m-%d')
                    else:
                        existing_expiry = existing_end
                    
                    if existing_expiry > datetime.now():
                        existing_source = user.get('premium_source')
                        
                        if source == 'ads' and existing_source != 'ads':
                            LOGGER(__name__).warning(
                                f"User {user_id} has active premium until {existing_end} (source: {existing_source or 'legacy/paid'}). "
                                f"Skipping ad-based premium to prevent overwriting non-ad subscription."
                            )
                            return False
            
            update_data = {
                "user_type": "paid",
                "subscription_end": expiry_datetime,
                "premium_source": source
            }
            
            result = self.users.update_one(
                {"user_id": user_id},
                {"$set": update_data}
            )
            return result.modified_count > 0 or result.matched_count > 0
        except Exception as e:
            LOGGER(__name__).error(f"Error setting premium for {user_id}: {e}")
            return False

    def get_daily_usage(self, user_id: int, date: Optional[str] = None) -> int:
        """Get daily file download count"""
        if not date:
            date = datetime.now().strftime('%Y-%m-%d')

        try:
            usage = self.daily_usage.find_one({"user_id": user_id, "date": date})
            return usage['files_downloaded'] if usage else 0
        except Exception as e:
            LOGGER(__name__).error(f"Error getting daily usage for {user_id}: {e}")
            return 0

    def increment_usage(self, user_id: int, count: int = 1) -> bool:
        """Increment usage count - uses ad downloads first, then daily usage (with limit validation)
        
        Args:
            user_id: User ID
            count: Number of files to increment (default 1)
            
        Returns:
            bool: True if increment successful, False if quota insufficient
        """
        try:
            user_type = self.get_user_type(user_id)
            
            # Admins and paid users have no limits
            if user_type in ['admin', 'paid']:
                return True
            
            # Reset ad downloads if it's a new day (must happen before reading ad_downloads)
            self.reset_ad_downloads_if_needed(user_id)
            
            # Check if user has ad downloads
            user = self.get_user(user_id)
            ad_downloads = user.get('ad_downloads', 0) if user else 0
            
            if ad_downloads > 0:
                # PRE-VALIDATE: Check if user has enough ad downloads BEFORE deducting
                if count > ad_downloads:
                    LOGGER(__name__).warning(f"User {user_id} has only {ad_downloads} ad downloads but needs {count}")
                    return False
                
                # Ad downloads bypass daily limits completely
                # Deduct the exact count (we already validated it's available)
                result = self.users.update_one(
                    {"user_id": user_id, "ad_downloads": {"$gte": count}},
                    {"$inc": {"ad_downloads": -count}}
                )
                
                if result.modified_count > 0:
                    LOGGER(__name__).info(f"User {user_id} used {count} ad download(s), {ad_downloads - count} remaining")
                    # CRITICAL: Clear cache to prevent stale ad_downloads from being reused
                    self.cache.delete(f"user_{user_id}")
                    return True
                else:
                    # Race condition: another process might have used the ad downloads
                    LOGGER(__name__).error(f"Failed to deduct {count} ad downloads for user {user_id} (race condition)")
                    return False
            
            # No ad downloads, use daily usage (validate limit)
            daily_usage = self.get_daily_usage(user_id)
            if daily_usage + count > 1:
                LOGGER(__name__).warning(f"User {user_id} tried to exceed daily limit: {daily_usage} + {count} > 1")
                return False
            
            date = datetime.now().strftime('%Y-%m-%d')
            self.daily_usage.update_one(
                {"user_id": user_id, "date": date},
                {"$inc": {"files_downloaded": count}},
                upsert=True
            )
            return True
        except Exception as e:
            LOGGER(__name__).error(f"Error incrementing usage for {user_id}: {e}")
            return False

    def can_download(self, user_id: int, count: int = 1) -> tuple[bool, str]:
        """Check if user can download (considering ad downloads and daily limits)
        
        Args:
            user_id: User ID
            count: Number of files to download (default 1, for media groups can be > 1)
            
        Returns:
            tuple: (can_download: bool, message: str)
        """
        user_type = self.get_user_type(user_id)

        if user_type in ['admin', 'paid']:
            return True, ""

        # Reset ad downloads if it's a new day (must happen before reading ad_downloads)
        self.reset_ad_downloads_if_needed(user_id)

        # Check ad downloads first
        user = self.get_user(user_id)
        ad_downloads = user.get('ad_downloads', 0) if user else 0
        
        if ad_downloads > 0:
            if ad_downloads < count:
                # Not enough ad downloads for this media group
                quota_message = f"❌ **Insufficient ad downloads**\n\n📊 You have {ad_downloads} ad download(s) but need {count} for this media group."
                return False, quota_message
            
            # User has enough ad downloads - allow download
            return True, ""

        daily_usage = self.get_daily_usage(user_id)
        if daily_usage + count > 1:
            quota_message = f"📊 **Daily limit reached**"
            return False, quota_message

        # Return True with empty message - completion message with buttons will be shown by main.py
        return True, ""

    def get_all_users(self) -> List[int]:
        """Get all user IDs"""
        try:
            users = self.users.find({"is_banned": False}, {"user_id": 1})
            return [user['user_id'] for user in users]
        except Exception as e:
            LOGGER(__name__).error(f"Error getting all users: {e}")
            return []

    def save_broadcast(self, message: str, sent_by: int, total_users: int, successful_sends: int) -> bool:
        """Save broadcast history"""
        try:
            broadcast_doc = {
                "message": message,
                "sent_by": sent_by,
                "sent_date": datetime.now(),
                "total_users": total_users,
                "successful_sends": successful_sends
            }
            self.broadcasts.insert_one(broadcast_doc)
            return True
        except Exception as e:
            LOGGER(__name__).error(f"Error saving broadcast: {e}")
            return False

    def ban_user(self, user_id: int) -> bool:
        """Ban a user"""
        try:
            result = self.users.update_one(
                {"user_id": user_id},
                {"$set": {"is_banned": True}}
            )
            # Invalidate cache
            self.cache.delete(f"banned_{user_id}")
            self.cache.delete(f"user_{user_id}")
            return result.modified_count > 0
        except Exception as e:
            LOGGER(__name__).error(f"Error banning user {user_id}: {e}")
            return False

    def unban_user(self, user_id: int) -> bool:
        """Unban a user"""
        try:
            result = self.users.update_one(
                {"user_id": user_id},
                {"$set": {"is_banned": False}}
            )
            # Invalidate cache
            self.cache.delete(f"banned_{user_id}")
            self.cache.delete(f"user_{user_id}")
            return result.modified_count > 0
        except Exception as e:
            LOGGER(__name__).error(f"Error unbanning user {user_id}: {e}")
            return False

    def is_banned(self, user_id: int) -> bool:
        """Check if user is banned (with caching)"""
        cache_key = f"banned_{user_id}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        
        user = self.get_user(user_id)
        is_banned = bool(user and user.get('is_banned', False))
        self.cache.set(cache_key, is_banned, ttl=300)  # Cache for 5 minutes
        return is_banned

    def set_user_session(self, user_id: int, session_string: Optional[str] = None) -> bool:
        """Set user's session string for accessing restricted content (None to logout)"""
        try:
            result = self.users.update_one(
                {"user_id": user_id},
                {"$set": {"session_string": session_string}}
            )
            # IMPORTANT: Invalidate cache so get_user_session returns updated data
            self.cache.delete(f"user_{user_id}")
            return result.modified_count > 0 or result.matched_count > 0
        except Exception as e:
            LOGGER(__name__).error(f"Error setting session for {user_id}: {e}")
            return False

    def get_user_session(self, user_id: int) -> Optional[str]:
        """Get user's session string"""
        user = self.get_user(user_id)
        return user.get('session_string') if user else None

    def get_stats(self) -> Dict:
        """Get bot statistics"""
        try:
            total_users = self.users.count_documents({})
            
            week_ago = datetime.now() - timedelta(days=7)
            active_users = self.users.count_documents({"last_activity": {"$gt": week_ago}})
            
            now = datetime.now()
            paid_users = self.users.count_documents({
                "user_type": "paid",
                "subscription_end": {"$gt": now.strftime('%Y-%m-%d')}
            })
            
            admin_count = self.admins.count_documents({})
            
            today = datetime.now().strftime('%Y-%m-%d')
            pipeline = [
                {"$match": {"date": today}},
                {"$group": {"_id": None, "total": {"$sum": "$files_downloaded"}}}
            ]
            result = list(self.daily_usage.aggregate(pipeline))
            today_downloads = result[0]['total'] if result else 0
            
            # Count new users registered today
            today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            today_new_users = self.users.count_documents({
                "joined_date": {"$gte": today_start}
            })
            
            return {
                'total_users': total_users,
                'active_users': active_users,
                'paid_users': paid_users,
                'admin_count': admin_count,
                'today_downloads': today_downloads,
                'today_new_users': today_new_users
            }
        except Exception as e:
            LOGGER(__name__).error(f"Error getting stats: {e}")
            return {}
    
    def set_custom_thumbnail(self, user_id: int, file_id: str) -> bool:
        """Set custom thumbnail for user"""
        try:
            result = self.users.update_one(
                {"user_id": user_id},
                {"$set": {"custom_thumbnail": file_id}}
            )
            return result.modified_count > 0
        except Exception as e:
            LOGGER(__name__).error(f"Error setting custom thumbnail for {user_id}: {e}")
            return False
    
    def get_custom_thumbnail(self, user_id: int) -> Optional[str]:
        """Get user's custom thumbnail file_id"""
        user = self.get_user(user_id)
        return user.get('custom_thumbnail') if user else None
    
    def delete_custom_thumbnail(self, user_id: int) -> bool:
        """Delete custom thumbnail for user"""
        try:
            result = self.users.update_one(
                {"user_id": user_id},
                {"$set": {"custom_thumbnail": None}}
            )
            return result.modified_count > 0
        except Exception as e:
            LOGGER(__name__).error(f"Error deleting custom thumbnail for {user_id}: {e}")
            return False
    
    def get_premium_users(self) -> List[Dict]:
        """Get list of all premium (paid) users with active subscriptions"""
        try:
            now = datetime.now().strftime('%Y-%m-%d')
            users = self.users.find({
                "user_type": "paid",
                "subscription_end": {"$gt": now}
            }).sort("subscription_end", -1)
            
            result = []
            for user in users:
                result.append({
                    "user_id": user['user_id'],
                    "username": user.get('username'),
                    "premium_expiry": user.get('subscription_end')
                })
            return result
        except Exception as e:
            LOGGER(__name__).error(f"Error getting premium users: {e}")
            return []
    
    def create_ad_session(self, session_id: str, user_id: int) -> bool:
        """Create ad watching session"""
        try:
            session_doc = {
                "session_id": session_id,
                "user_id": user_id,
                "created_at": datetime.now(),
                "ad_completed": False,
                "code_generated": False
            }
            self.ad_sessions.insert_one(session_doc)
            return True
        except Exception as e:
            LOGGER(__name__).error(f"Error creating ad session {session_id}: {e}")
            return False
    
    def get_ad_session(self, session_id: str) -> Optional[Dict]:
        """Get ad session data"""
        try:
            session = self.ad_sessions.find_one({"session_id": session_id})
            if session:
                session.pop('_id', None)
            return session
        except Exception as e:
            LOGGER(__name__).error(f"Error getting ad session {session_id}: {e}")
            return None
    
    def update_ad_session(self, session_id: str, updates: Dict) -> bool:
        """Update ad session"""
        try:
            result = self.ad_sessions.update_one(
                {"session_id": session_id},
                {"$set": updates}
            )
            return result.modified_count > 0
        except Exception as e:
            LOGGER(__name__).error(f"Error updating ad session {session_id}: {e}")
            return False
    
    def mark_ad_session_used(self, session_id: str) -> bool:
        """Atomically mark ad session as used (prevents race condition)"""
        try:
            result = self.ad_sessions.find_one_and_update(
                {"session_id": session_id, "code_generated": False},
                {"$set": {"ad_completed": True, "code_generated": True}},
                return_document=False
            )
            return result is not None
        except Exception as e:
            LOGGER(__name__).error(f"Error marking ad session as used {session_id}: {e}")
            return False
    
    def delete_ad_session(self, session_id: str) -> bool:
        """Delete ad session"""
        try:
            result = self.ad_sessions.delete_one({"session_id": session_id})
            return result.deleted_count > 0
        except Exception as e:
            LOGGER(__name__).error(f"Error deleting ad session {session_id}: {e}")
            return False
    
    def create_verification_code(self, code: str, user_id: int) -> bool:
        """Create verification code"""
        try:
            code_doc = {
                "code": code,
                "user_id": user_id,
                "created_at": datetime.now()
            }
            self.ad_verifications.insert_one(code_doc)
            return True
        except Exception as e:
            LOGGER(__name__).error(f"Error creating verification code {code}: {e}")
            return False
    
    def get_verification_code(self, code: str) -> Optional[Dict]:
        """Get verification code data"""
        try:
            verification = self.ad_verifications.find_one({"code": code})
            if verification:
                verification.pop('_id', None)
            return verification
        except Exception as e:
            LOGGER(__name__).error(f"Error getting verification code {code}: {e}")
            return None
    
    def delete_verification_code(self, code: str) -> bool:
        """Delete verification code"""
        try:
            result = self.ad_verifications.delete_one({"code": code})
            return result.deleted_count > 0
        except Exception as e:
            LOGGER(__name__).error(f"Error deleting verification code {code}: {e}")
            return False
    
    def add_ad_downloads(self, user_id: int, count: int) -> bool:
        """Add ad downloads to user account (resets to 0 first if it's a new day)"""
        try:
            # Reset ad downloads if it's a new day (must happen before adding new credits)
            self.reset_ad_downloads_if_needed(user_id)
            
            result = self.users.update_one(
                {"user_id": user_id},
                {"$inc": {"ad_downloads": count}},
                upsert=False
            )
            if result.modified_count > 0:
                LOGGER(__name__).info(f"Added {count} ad downloads to user {user_id}")
                # Clear cache to ensure fresh data on next read
                self.cache.delete(f"user_{user_id}")
                return True
            return False
        except Exception as e:
            LOGGER(__name__).error(f"Error adding ad downloads for {user_id}: {e}")
            return False
    
    def reset_ad_downloads_if_needed(self, user_id: int) -> None:
        """Reset ad downloads to 0 if it's a new day"""
        try:
            user = self.users.find_one({"user_id": user_id})
            if not user:
                return
            
            today = datetime.now().strftime('%Y-%m-%d')
            last_reset = user.get('ad_downloads_reset_date', '')
            
            # If it's a new day, reset ad downloads to 0
            if last_reset != today:
                self.users.update_one(
                    {"user_id": user_id},
                    {
                        "$set": {
                            "ad_downloads": 0,
                            "ad_downloads_reset_date": today
                        }
                    }
                )
                LOGGER(__name__).info(f"Reset ad downloads for user {user_id} (new day: {today})")
                # Clear cache so next get_user call fetches fresh data
                self.cache.delete(f"user_{user_id}")
        except Exception as e:
            LOGGER(__name__).error(f"Error resetting ad downloads for {user_id}: {e}")
    
    def get_ad_downloads(self, user_id: int) -> int:
        """Get user's remaining ad downloads (resets daily at midnight)"""
        try:
            # Reset ad downloads if it's a new day
            self.reset_ad_downloads_if_needed(user_id)
            
            user = self.get_user(user_id)
            return user.get('ad_downloads', 0) if user else 0
        except Exception as e:
            LOGGER(__name__).error(f"Error getting ad downloads for {user_id}: {e}")
            return 0

db = DatabaseManager()
