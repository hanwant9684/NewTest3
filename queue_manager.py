import os
import asyncio
import psutil
from datetime import datetime
from typing import Dict, Set, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import IntEnum
from logger import LOGGER

class Priority(IntEnum):
    PREMIUM = 1
    FREE = 2

@dataclass(order=True)
class QueueItem:
    priority: int
    timestamp: float = field(compare=True)
    user_id: int = field(compare=False)
    download_coro: Any = field(compare=False)
    message: Any = field(compare=False)
    post_url: str = field(compare=False)

class DownloadQueueManager:
    def __init__(
        self, 
        max_concurrent_users: int = 20, 
        max_concurrent_per_user: int = 1,
        max_queue: int = 100, 
        memory_limit_mb: int = 400
    ):
        self.max_concurrent_users = max_concurrent_users  # How many users can download simultaneously
        self.max_concurrent_per_user = max_concurrent_per_user  # Downloads per user
        self.max_queue = max_queue
        self.memory_limit_mb = memory_limit_mb  # Circuit breaker threshold (MB)
        
        # Track active downloads per user: {user_id: count}
        self.active_downloads: Dict[int, int] = {}
        self.waiting_queue: list[QueueItem] = []
        
        self.user_queue_positions: Dict[int, QueueItem] = {}
        # Track tasks per user: {user_id: [task1, task2, ...]}
        self.active_tasks: Dict[int, list[asyncio.Task]] = {}
        
        self._lock = asyncio.Lock()
        self._processing = False
        self._processor_task: Optional[asyncio.Task] = None
        
        LOGGER(__name__).info(
            f"Queue Manager initialized: {max_concurrent_users} max users, "
            f"{max_concurrent_per_user} per user, {max_queue} max queue, "
            f"{memory_limit_mb}MB memory limit"
        )
    
    def _check_memory_usage(self) -> tuple[bool, int]:
        """Check if memory usage is within safe limits. Returns (is_safe, current_mb)"""
        try:
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            is_safe = memory_mb < self.memory_limit_mb
            return is_safe, int(memory_mb)
        except Exception as e:
            LOGGER(__name__).warning(f"Failed to check memory usage: {e}")
            return True, 0  # Assume safe if can't check
    
    async def start_processor(self):
        if not self._processing:
            self._processing = True
            self._processor_task = asyncio.create_task(self._process_queue())
            LOGGER(__name__).info("Queue processor started")
    
    async def stop_processor(self):
        self._processing = False
        if self._processor_task:
            self._processor_task.cancel()
            try:
                await self._processor_task
            except asyncio.CancelledError:
                pass
        LOGGER(__name__).info("Queue processor stopped")
    
    async def add_to_queue(
        self, 
        user_id: int, 
        download_coro, 
        message,
        post_url: str,
        is_premium: bool = False
    ) -> Tuple[bool, str]:
        async with self._lock:
            # Circuit breaker: Check memory usage before accepting new downloads
            memory_safe, current_mb = self._check_memory_usage()
            if not memory_safe:
                total_active = sum(self.active_downloads.values())
                LOGGER(__name__).warning(
                    f"Memory limit reached: {current_mb}MB / {self.memory_limit_mb}MB - rejecting new download"
                )
                return False, (
                    f"⚠️ **System memory limit reached!**\n\n"
                    f"📊 **Current Usage:** {current_mb}MB / {self.memory_limit_mb}MB\n"
                    f"🔄 **Active Downloads:** {total_active} across {len(self.active_downloads)} users\n\n"
                    f"Please try again in a few minutes when some downloads complete."
                )
            
            # Check if user already has downloads in progress
            user_active_count = self.active_downloads.get(user_id, 0)
            if user_active_count >= self.max_concurrent_per_user:
                return False, (
                    f"❌ **You already have {user_active_count} download(s) in progress!**\n\n"
                    f"⏳ Please wait for it to complete.\n\n"
                    f"💡 **Want to download this instead?**\n"
                    f"Use `/canceldownload` to cancel the current download."
                )
            
            # Check if user has item in queue
            if user_id in self.user_queue_positions:
                position = self.get_queue_position(user_id)
                return False, (
                    f"❌ **You already have a download in the queue!**\n\n"
                    f"📍 **Position:** #{position}/{len(self.waiting_queue)}\n\n"
                    f"💡 **Want to cancel it?**\n"
                    f"Use `/canceldownload` to remove from queue."
                )
            
            # Check global concurrent users limit
            total_users = len(self.active_downloads)
            if total_users >= self.max_concurrent_users and user_id not in self.active_downloads:
                # Queue is needed
                if len(self.waiting_queue) >= self.max_queue:
                    total_active = sum(self.active_downloads.values())
                    return False, (
                        f"❌ **Download queue is full!**\n\n"
                        f"🔄 **Active Downloads:** {total_active} across {total_users} users\n"
                        f"⏳ **Waiting in Queue:** {len(self.waiting_queue)}/{self.max_queue}\n\n"
                        f"Please try again later."
                    )
                
                priority = Priority.PREMIUM if is_premium else Priority.FREE
                queue_item = QueueItem(
                    priority=priority,
                    timestamp=datetime.now().timestamp(),
                    user_id=user_id,
                    download_coro=download_coro,
                    message=message,
                    post_url=post_url
                )
                
                self.waiting_queue.append(queue_item)
                self.waiting_queue.sort()
                self.user_queue_positions[user_id] = queue_item
                
                position = self.get_queue_position(user_id)
                premium_badge = "👑 **PREMIUM**" if is_premium else "🆓 **FREE**"
                total_active = sum(self.active_downloads.values())
                
                return True, (
                    f"⏳ **Download added to queue!**\n\n"
                    f"{premium_badge}\n"
                    f"📍 **Your Position:** #{position}/{len(self.waiting_queue)}\n"
                    f"🔄 **Active Users:** {total_users}/{self.max_concurrent_users} ({total_active} downloads)\n\n"
                    f"💡 You'll be notified when your download starts!"
                )
            else:
                # Start download immediately
                self.active_downloads[user_id] = self.active_downloads.get(user_id, 0) + 1
                if user_id not in self.active_tasks:
                    self.active_tasks[user_id] = []
                
                task = asyncio.create_task(self._execute_download(user_id, download_coro, message))
                self.active_tasks[user_id].append(task)
                
                total_active = sum(self.active_downloads.values())
                status_msg = (
                    f"✅ **Download started!**\n\n"
                    f"🔄 **Active Users:** {len(self.active_downloads)}/{self.max_concurrent_users} ({total_active} downloads)"
                )
                asyncio.create_task(self._send_auto_delete_message(message, status_msg, 10))
                
                return True, ""
    
    async def _send_auto_delete_message(self, message, text: str, delete_after: int):
        """Send a message and auto-delete it after specified seconds"""
        try:
            sent_msg = await message.reply(text)
            await asyncio.sleep(delete_after)
            await sent_msg.delete()
        except Exception as e:
            LOGGER(__name__).debug(f"Failed to auto-delete message: {e}")
    
    async def _execute_download(self, user_id: int, download_coro, message):
        try:
            await download_coro
        except Exception as e:
            LOGGER(__name__).error(f"Download error for user {user_id}: {e}")
            try:
                await message.reply(f"❌ **Download failed:** {str(e)}")
            except:
                pass
        finally:
            async with self._lock:
                # Decrement user's active download count
                if user_id in self.active_downloads:
                    self.active_downloads[user_id] -= 1
                    if self.active_downloads[user_id] <= 0:
                        del self.active_downloads[user_id]
                
                # Remove completed task from user's task list
                if user_id in self.active_tasks:
                    task = asyncio.current_task()
                    if task in self.active_tasks[user_id]:
                        self.active_tasks[user_id].remove(task)
                    if not self.active_tasks[user_id]:
                        del self.active_tasks[user_id]
            
            # Log memory usage after download completes (important for Render's 512MB limit)
            memory_safe, current_mb = self._check_memory_usage()
            total_active = sum(self.active_downloads.values())
            LOGGER(__name__).info(
                f"Download completed for user {user_id}. Active: {total_active} downloads "
                f"across {len(self.active_downloads)} users. Memory: {current_mb}MB/{self.memory_limit_mb}MB"
            )
            
            # Force garbage collection after download to free memory
            import gc
            gc.collect()
    
    async def _process_queue(self):
        while self._processing:
            try:
                await asyncio.sleep(1)
                
                async with self._lock:
                    # Process queue while we have capacity for more users
                    while len(self.active_downloads) < self.max_concurrent_users and self.waiting_queue:
                        # Circuit breaker: Check memory before promoting queued downloads
                        memory_safe, current_mb = self._check_memory_usage()
                        if not memory_safe:
                            LOGGER(__name__).warning(
                                f"Memory limit reached during queue processing: {current_mb}MB / {self.memory_limit_mb}MB "
                                f"- skipping promotion of queued downloads until memory decreases"
                            )
                            break  # Stop promoting downloads until memory drops
                        
                        queue_item = self.waiting_queue.pop(0)
                        user_id = queue_item.user_id
                        
                        self.user_queue_positions.pop(user_id, None)
                        
                        # Skip if user already has active downloads (shouldn't happen but safety check)
                        if user_id in self.active_downloads:
                            LOGGER(__name__).warning(f"User {user_id} already active, skipping queue promotion")
                            continue
                        
                        # Start download for this user
                        self.active_downloads[user_id] = 1
                        if user_id not in self.active_tasks:
                            self.active_tasks[user_id] = []
                        
                        try:
                            status_msg = f"🚀 **Your download is starting now!**\n\n📥 Downloading: `{queue_item.post_url}`"
                            asyncio.create_task(self._send_auto_delete_message(queue_item.message, status_msg, 10))
                        except:
                            pass
                        
                        task = asyncio.create_task(
                            self._execute_download(user_id, queue_item.download_coro, queue_item.message)
                        )
                        self.active_tasks[user_id].append(task)
                        
                        total_active = sum(self.active_downloads.values())
                        LOGGER(__name__).info(
                            f"Started queued download for user {user_id}. "
                            f"Active: {total_active} downloads across {len(self.active_downloads)} users, "
                            f"Queue: {len(self.waiting_queue)}"
                        )
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                LOGGER(__name__).error(f"Queue processor error: {e}")
    
    def get_queue_position(self, user_id: int) -> int:
        for idx, item in enumerate(self.waiting_queue, 1):
            if item.user_id == user_id:
                return idx
        return 0
    
    async def get_queue_status(self, user_id: int) -> str:
        async with self._lock:
            user_active_count = self.active_downloads.get(user_id, 0)
            total_active = sum(self.active_downloads.values())
            
            if user_active_count > 0:
                return (
                    f"📥 **You have {user_active_count} download(s) active!**\n\n"
                    f"🔄 **Total Active:** {total_active} downloads across {len(self.active_downloads)} users\n"
                    f"⏳ **Waiting in Queue:** {len(self.waiting_queue)}/{self.max_queue}"
                )
            
            position = self.get_queue_position(user_id)
            if position > 0:
                queue_item = self.user_queue_positions.get(user_id)
                priority_text = "👑 **PREMIUM**" if queue_item and queue_item.priority == Priority.PREMIUM else "🆓 **FREE**"
                
                return (
                    f"⏳ **You're in the queue!**\n\n"
                    f"{priority_text}\n"
                    f"📍 **Your Position:** #{position}/{len(self.waiting_queue)}\n"
                    f"🔄 **Active Users:** {len(self.active_downloads)}/{self.max_concurrent_users} ({total_active} downloads)\n\n"
                    f"💡 Estimated wait: ~{position * 2} minutes"
                )
            
            return (
                f"✅ **No active downloads**\n\n"
                f"🔄 **Active Users:** {len(self.active_downloads)}/{self.max_concurrent_users} ({total_active} downloads)\n"
                f"⏳ **Waiting in Queue:** {len(self.waiting_queue)}/{self.max_queue}\n\n"
                f"💡 Send a download link to get started!"
            )
    
    async def get_global_status(self) -> str:
        async with self._lock:
            total_active = sum(self.active_downloads.values())
            premium_in_queue = sum(1 for item in self.waiting_queue if item.priority == Priority.PREMIUM)
            free_in_queue = len(self.waiting_queue) - premium_in_queue
            
            return (
                f"📊 **Queue System Status**\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"👥 **Active Users:** {len(self.active_downloads)}/{self.max_concurrent_users}\n"
                f"🔄 **Total Downloads:** {total_active}\n"
                f"⏳ **Waiting in Queue:** {len(self.waiting_queue)}/{self.max_queue}\n\n"
                f"👑 Premium in queue: {premium_in_queue}\n"
                f"🆓 Free in queue: {free_in_queue}\n\n"
                f"💡 Premium users get priority!"
            )
    
    async def cancel_user_download(self, user_id: int) -> Tuple[bool, str]:
        async with self._lock:
            user_active_count = self.active_downloads.get(user_id, 0)
            if user_active_count > 0:
                # Cancel all active downloads for this user
                tasks = self.active_tasks.get(user_id, [])
                for task in tasks:
                    if not task.done():
                        task.cancel()
                
                del self.active_downloads[user_id]
                self.active_tasks.pop(user_id, None)
                
                plural = "downloads" if user_active_count > 1 else "download"
                return True, f"✅ **{user_active_count} active {plural} cancelled!**"
            
            queue_item = self.user_queue_positions.get(user_id)
            if queue_item and queue_item in self.waiting_queue:
                self.waiting_queue.remove(queue_item)
                self.user_queue_positions.pop(user_id, None)
                return True, "✅ **Removed from download queue!**"
            
            return False, "❌ **No active download or queue entry found.**"
    
    async def cancel_all_downloads(self) -> int:
        async with self._lock:
            cancelled = 0
            
            # Cancel all active tasks
            for user_tasks in self.active_tasks.values():
                for task in user_tasks:
                    if not task.done():
                        task.cancel()
                        cancelled += 1
            
            self.active_downloads.clear()
            self.active_tasks.clear()
            
            cancelled += len(self.waiting_queue)
            self.waiting_queue.clear()
            self.user_queue_positions.clear()
            
            LOGGER(__name__).info(f"Cancelled all downloads: {cancelled} total")
            return cancelled

# Detect constrained environments (Render 512MB RAM, Replit)
IS_RENDER = bool(os.getenv('RENDER') or os.getenv('RENDER_EXTERNAL_URL'))
IS_REPLIT = bool(os.getenv('REPLIT_DEPLOYMENT') or os.getenv('REPL_ID'))
IS_CONSTRAINED = IS_RENDER or IS_REPLIT

# Adaptive queue limits based on environment - PER-USER CONCURRENCY MODEL
# Each user limited to 1 concurrent download, but multiple users can download simultaneously
# Render (512MB): 3 max users, 10 queue, 350MB memory (conservative for 512MB RAM)
# Replit: 5 max users, 15 queue, 380MB memory
# Unconstrained (VPS/Railway): 20 max users, 100 queue, 900MB memory
if IS_RENDER:
    max_concurrent_users = 3  # Max 3 users downloading simultaneously
    max_concurrent_per_user = 1  # Each user can download 1 file at a time
    max_queue = 10
    memory_limit_mb = 350
elif IS_REPLIT:
    max_concurrent_users = 5  # Max 5 users downloading simultaneously
    max_concurrent_per_user = 1  # Each user can download 1 file at a time
    max_queue = 15
    memory_limit_mb = 380
else:
    max_concurrent_users = 20  # Max 20 users downloading simultaneously
    max_concurrent_per_user = 1  # Each user can download 1 file at a time
    max_queue = 100
    memory_limit_mb = 900

LOGGER(__name__).info(
    f"Queue limits: max_concurrent_users={max_concurrent_users}, "
    f"max_concurrent_per_user={max_concurrent_per_user}, max_queue={max_queue}, "
    f"memory_limit={memory_limit_mb}MB (constrained={IS_CONSTRAINED}, "
    f"render={IS_RENDER}, replit={IS_REPLIT})"
)

download_queue = DownloadQueueManager(
    max_concurrent_users=max_concurrent_users,
    max_concurrent_per_user=max_concurrent_per_user,
    max_queue=max_queue,
    memory_limit_mb=memory_limit_mb
)
