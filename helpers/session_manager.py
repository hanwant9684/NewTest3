# Session Manager for Pyrogram Client instances
# Limits active user sessions to reduce memory usage
# Each Pyrogram Client uses ~100MB, so we limit to max 5 concurrent users

import asyncio
from typing import Dict, Optional
from collections import OrderedDict
from pyrogram import Client
from logger import LOGGER

class SessionManager:
    """
    Manages Pyrogram Client instances with a maximum limit
    Automatically disconnects oldest sessions when limit is reached
    This prevents memory exhaustion from too many active user sessions
    """
    
    def __init__(self, max_sessions: int = 5):
        """
        Args:
            max_sessions: Maximum number of concurrent user sessions
                         Each session uses ~100MB, so 5 = ~500MB total
        """
        self.max_sessions = max_sessions
        self.active_sessions: OrderedDict[int, Client] = OrderedDict()
        self._lock = asyncio.Lock()
        LOGGER(__name__).info(f"Session Manager initialized: max {max_sessions} concurrent sessions")
    
    async def get_or_create_session(
        self, 
        user_id: int, 
        session_string: str,
        api_id: int,
        api_hash: str
    ) -> Optional[Client]:
        """
        Get existing session or create new one
        If max sessions reached, disconnects oldest session first
        """
        async with self._lock:
            # Check if user already has active session
            if user_id in self.active_sessions:
                # Move to end (most recently used)
                self.active_sessions.move_to_end(user_id)
                return self.active_sessions[user_id]
            
            # If at capacity, disconnect oldest session
            if len(self.active_sessions) >= self.max_sessions:
                oldest_user_id, oldest_client = self.active_sessions.popitem(last=False)
                try:
                    from memory_monitor import memory_monitor
                    memory_monitor.track_session_cleanup(oldest_user_id)
                    await oldest_client.stop()
                    LOGGER(__name__).info(f"Disconnected oldest session: user {oldest_user_id}")
                    memory_monitor.log_memory_snapshot("Session Disconnected", f"Freed session for user {oldest_user_id}")
                except Exception as e:
                    LOGGER(__name__).error(f"Error disconnecting session {oldest_user_id}: {e}")
            
            # Create new session
            try:
                import os
                from memory_monitor import memory_monitor
                
                memory_monitor.track_session_creation(user_id)
                
                IS_CONSTRAINED = bool(
                    os.getenv('RENDER') or 
                    os.getenv('RENDER_EXTERNAL_URL') or 
                    os.getenv('REPLIT_DEPLOYMENT') or 
                    os.getenv('REPL_ID')
                )
                
                client = Client(
                    f"user_{user_id}",
                    api_id=api_id,
                    api_hash=api_hash,
                    session_string=session_string,
                    workers=1 if IS_CONSTRAINED else 2,
                    max_concurrent_transmissions=2 if IS_CONSTRAINED else 4,
                    sleep_threshold=30,
                    in_memory=True
                )
                
                await client.start()
                self.active_sessions[user_id] = client
                LOGGER(__name__).info(f"Created new session for user {user_id} ({len(self.active_sessions)}/{self.max_sessions})")
                
                memory_monitor.log_memory_snapshot("Session Created", f"User {user_id} - Total sessions: {len(self.active_sessions)}")
                
                return client
                
            except Exception as e:
                LOGGER(__name__).error(f"Failed to create session for user {user_id}: {e}")
                return None
    
    async def remove_session(self, user_id: int):
        """Remove and disconnect a specific user session"""
        async with self._lock:
            if user_id in self.active_sessions:
                try:
                    from memory_monitor import memory_monitor
                    memory_monitor.track_session_cleanup(user_id)
                    await self.active_sessions[user_id].stop()
                    del self.active_sessions[user_id]
                    LOGGER(__name__).info(f"Removed session for user {user_id}")
                    memory_monitor.log_memory_snapshot("Session Removed", f"User {user_id}")
                except Exception as e:
                    LOGGER(__name__).error(f"Error removing session {user_id}: {e}")
    
    async def disconnect_all(self):
        """Disconnect all active sessions (for shutdown)"""
        async with self._lock:
            for user_id, client in list(self.active_sessions.items()):
                try:
                    await client.stop()
                except:
                    pass
            self.active_sessions.clear()
            LOGGER(__name__).info("All sessions disconnected")
    
    def get_active_count(self) -> int:
        """Get number of currently active sessions"""
        return len(self.active_sessions)

# Global session manager instance (import this in other modules)
# Limit to 3 sessions on Render (3 * 100MB = 300MB)
# Limit to 5 sessions on normal deployment (5 * 100MB = 500MB)
import os
IS_CONSTRAINED = bool(
    os.getenv('RENDER') or 
    os.getenv('RENDER_EXTERNAL_URL') or 
    os.getenv('REPLIT_DEPLOYMENT') or 
    os.getenv('REPL_ID')
)

MAX_SESSIONS = 3 if IS_CONSTRAINED else 5
session_manager = SessionManager(max_sessions=MAX_SESSIONS)
