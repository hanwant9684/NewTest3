# Copyright (C) @Wolfy004
# Channel: https://t.me/Wolfy004

import asyncio
from functools import wraps
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import UserNotParticipant, ChatAdminRequired, ChannelPrivate
from database import db
from logger import LOGGER
from config import PyroConf

# Helper function to avoid redundant DB calls in decorators
async def _register_and_check_user(message: Message) -> tuple[int, bool]:
    """
    Register user and check ban status in one go.
    Returns (user_id, is_banned)
    """
    user_id = message.from_user.id
    
    # Add user to database if not exists
    db.add_user(
        user_id=user_id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name
    )
    
    # Check if banned (uses cache)
    is_banned = db.is_banned(user_id)
    return user_id, is_banned

def admin_only(func):
    """Decorator to restrict command to admins only (optimized)"""
    @wraps(func)
    async def wrapper(client, message: Message, *args, **kwargs):
        user_id, is_banned = await _register_and_check_user(message)
        
        if is_banned:
            await message.reply("❌ **You are banned from using this bot.**")
            return

        # Check admin status (uses cache)
        if not db.is_admin(user_id):
            await message.reply("❌ **This command is restricted to administrators only.**")
            return

        return await func(client, message, *args, **kwargs)
    return wrapper

def paid_or_admin_only(func):
    """Decorator to restrict command to paid users and admins (optimized)"""
    @wraps(func)
    async def wrapper(client, message: Message, *args, **kwargs):
        user_id, is_banned = await _register_and_check_user(message)
        
        if is_banned:
            await message.reply("❌ **You are banned from using this bot.**")
            return

        user_type = db.get_user_type(user_id)
        if user_type not in ['paid', 'admin']:
            await message.reply(
                "❌ **This feature is available for premium users only.**\n\n"
                "💎 **Get Premium Access:**\n\n"
                "🎁 **FREE Option:** Use `/getpremium` - Watch a quick ad!\n"
                "💰 **Paid Option:** Use `/upgrade` - Only $1/month\n\n"
                "✅ **Premium Benefits:**\n"
                "• Unlimited downloads\n"
                "• Batch download feature\n"
                "• Priority support"
            )
            return

        return await func(client, message, *args, **kwargs)
    return wrapper

def check_download_limit(func):
    """Decorator to check download limits for free users (optimized)"""
    @wraps(func)
    async def wrapper(client, message: Message):
        user_id, is_banned = await _register_and_check_user(message)
        
        if is_banned:
            await message.reply("❌ **You are banned from using this bot.**")
            return

        # Check download limits
        can_download, message_text = db.can_download(user_id)
        if not can_download:
            from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            from ad_monetization import PREMIUM_DOWNLOADS
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"🎁 Watch Ad & Get {PREMIUM_DOWNLOADS} Downloads", callback_data="watch_ad_now")],
                [InlineKeyboardButton("💰 Upgrade to Premium", callback_data="upgrade_premium")]
            ])
            sent_msg = await message.reply(message_text, reply_markup=keyboard)
            
            # Auto-delete after 30 seconds
            async def delete_after_delay():
                try:
                    await asyncio.sleep(30)
                    await sent_msg.delete()
                except Exception as e:
                    LOGGER(__name__).debug(f"Could not delete daily limit message: {e}")
            
            asyncio.create_task(delete_after_delay())
            return

        return await func(client, message)
    return wrapper

def register_user(func):
    """Decorator to register user in database (optimized)"""
    @wraps(func)
    async def wrapper(client, message: Message):
        user_id, is_banned = await _register_and_check_user(message)
        
        if is_banned:
            await message.reply("❌ **You are banned from using this bot.**")
            return

        return await func(client, message)
    return wrapper

async def check_user_session(user_id: int):
    """Check if user has their own session string"""
    session = db.get_user_session(user_id)
    return session is not None

async def get_user_client(user_id: int):
    """
    Get user's personal client if they have session
    
    CRITICAL: Uses SessionManager to limit concurrent sessions and prevent memory exhaustion
    On Render (512MB RAM), limits to 3 concurrent user sessions (3 * 100MB = 300MB)
    Sessions are reused across downloads - DO NOT call client.stop() after each download!
    """
    session = db.get_user_session(user_id)
    if session:
        from config import PyroConf
        from helpers.session_manager import session_manager
        import traceback

        try:
            # Use SessionManager to get or create session
            # This prevents memory leaks by limiting concurrent sessions and reusing existing ones
            user_client = await session_manager.get_or_create_session(
                user_id=user_id,
                session_string=session,
                api_id=PyroConf.API_ID,
                api_hash=PyroConf.API_HASH
            )
            
            if user_client:
                LOGGER(__name__).info(f"Got user client for {user_id} from SessionManager")
            return user_client
        except Exception as e:
            LOGGER(__name__).error(f"Failed to get user client for {user_id}: {e}")
            LOGGER(__name__).error(f"Full traceback: {traceback.format_exc()}")
            # Don't immediately clear session - it might be a temporary network issue
            # Only clear if it's an authorization error
            error_msg = str(e).lower()
            if 'auth' in error_msg or 'session' in error_msg or 'expired' in error_msg:
                LOGGER(__name__).warning(f"Clearing invalid session for user {user_id}")
                db.set_user_session(user_id, None)
                # Remove from session manager
                from helpers.session_manager import session_manager
                await session_manager.remove_session(user_id)
            return None
    return None

def force_subscribe(func):
    """Decorator to enforce channel subscription before using bot features"""
    @wraps(func)
    async def wrapper(client, message: Message):
        # Skip if no force subscribe channel is configured
        if not PyroConf.FORCE_SUBSCRIBE_CHANNEL:
            return await func(client, message)
        
        user_id = message.from_user.id
        
        # Admins and owner bypass force subscribe
        if db.is_admin(user_id) or user_id == PyroConf.OWNER_ID:
            return await func(client, message)
        
        # Check if user is member of the channel
        try:
            channel = PyroConf.FORCE_SUBSCRIBE_CHANNEL
            # Remove @ if present
            if channel.startswith('@'):
                channel = channel[1:]
            
            member = await client.get_chat_member(f"@{channel}", user_id)
            
            # If user is member (any status except kicked/left), allow access
            if member.status not in ["kicked", "left"]:
                return await func(client, message)
                
        except UserNotParticipant:
            pass  # User not in channel, show join message
        except (ChatAdminRequired, ChannelPrivate) as e:
            LOGGER(__name__).error(f"Bot lacks permission to check channel membership: {e}")
            # If bot can't check, allow access (don't block users due to config error)
            return await func(client, message)
        except Exception as e:
            LOGGER(__name__).error(f"Error checking channel membership: {e}")
            return await func(client, message)
        
        # User is not subscribed, show join message
        channel_username = PyroConf.FORCE_SUBSCRIBE_CHANNEL
        if not channel_username.startswith('@'):
            channel_username = f"@{channel_username}"
        
        join_button = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{channel_username.replace('@', '')}")]
        ])
        
        await message.reply(
            f"❌ **Access Denied!**\n\n"
            f"🔒 You must join our channel to use this bot.\n\n"
            f"👉 **Channel:** {channel_username}\n\n"
            f"After joining, try your command again!",
            reply_markup=join_button
        )
    
    return wrapper