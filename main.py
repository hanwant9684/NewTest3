# Copyright (C) @Wolfy004
# Channel: https://t.me/Wolfy004

import os
import psutil
import asyncio
from time import time
from attribution import verify_attribution, get_channel_link, get_creator_username

try:
    import uvloop
    # Only set uvloop policy if not already set (prevents overwriting thread-local loops)
    if not isinstance(asyncio.get_event_loop_policy(), uvloop.EventLoopPolicy):
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass

from pyleaves import Leaves
from pyrogram.enums import ParseMode
from pyrogram import Client, filters
from pyrogram.errors import PeerIdInvalid, BadRequest
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from helpers.utils import (
    processMediaGroup,
    progressArgs,
    send_media,
    safe_progress_callback
)

from helpers.files import (
    get_download_path,
    fileSizeLimit,
    get_readable_file_size,
    get_readable_time,
    cleanup_download
)

from helpers.msg import (
    getChatMsgID,
    get_file_name,
    get_parsed_msg
)

from config import PyroConf
from logger import LOGGER
from database import db
from phone_auth import PhoneAuthHandler
from ad_monetization import ad_monetization, PREMIUM_DOWNLOADS
from access_control import admin_only, paid_or_admin_only, check_download_limit, register_user, check_user_session, get_user_client, force_subscribe
from memory_monitor import memory_monitor
from admin_commands import (
    add_admin_command,
    remove_admin_command,
    set_premium_command,
    remove_premium_command,
    ban_user_command,
    unban_user_command,
    broadcast_command,
    admin_stats_command,
    user_info_command,
    broadcast_callback_handler
)
from queue_manager import download_queue

# Initialize the bot client with settings optimized for Render's 512MB RAM / Replit resource limits
# Detect platform for optimal resource allocation
IS_RENDER = bool(os.getenv('RENDER') or os.getenv('RENDER_EXTERNAL_URL'))
IS_REPLIT = bool(os.getenv('REPLIT_DEPLOYMENT') or os.getenv('REPL_ID'))
IS_CONSTRAINED = IS_RENDER or IS_REPLIT  # Low RAM environments

# Aggressively reduce workers for constrained environments
workers = 1 if IS_CONSTRAINED else 4
concurrent = 2 if IS_CONSTRAINED else 4

bot = Client(
    "media_bot",
    api_id=PyroConf.API_ID,
    api_hash=PyroConf.API_HASH,
    bot_token=PyroConf.BOT_TOKEN,
    workers=workers,
    max_concurrent_transmissions=concurrent,
    parse_mode=ParseMode.MARKDOWN,
    sleep_threshold=30,  # Reduce API call frequency
    in_memory=True  # Don't write session files to disk
)

# REMOVED: Global user client was bypassing SessionManager and wasting 30-100MB RAM
# All users (including admins) must login with /login command to use SessionManager
# This ensures proper memory limits (max 3 sessions on Render = 300MB)

# Phone authentication handler
phone_auth_handler = PhoneAuthHandler(PyroConf.API_ID, PyroConf.API_HASH)

RUNNING_TASKS = set()
USER_TASKS = {}

# Custom filter to ignore old pending updates (prevents duplicate messages after bot restart)
def is_new_update(_, __, message: Message):
    """Filter to ignore messages older than bot start time"""
    if not hasattr(bot, 'start_time'):
        return True  # If start_time not set yet, allow all messages
    
    # Check if message date is newer than bot start time
    if message.date:
        return message.date.timestamp() >= bot.start_time
    return True  # Allow messages without date

# Create the filter
new_updates_only = filters.create(is_new_update)

def track_task(coro, user_id=None):
    task = asyncio.create_task(coro)
    RUNNING_TASKS.add(task)
    
    if user_id:
        if user_id not in USER_TASKS:
            USER_TASKS[user_id] = set()
        USER_TASKS[user_id].add(task)
    
    def _remove(_):
        RUNNING_TASKS.discard(task)
        if user_id and user_id in USER_TASKS:
            USER_TASKS[user_id].discard(task)
            if not USER_TASKS[user_id]:
                del USER_TASKS[user_id]
    
    task.add_done_callback(_remove)
    return task

def get_user_tasks(user_id):
    return USER_TASKS.get(user_id, set())

def cancel_user_tasks(user_id):
    tasks = get_user_tasks(user_id)
    cancelled = 0
    for task in list(tasks):
        if not task.done():
            task.cancel()
            cancelled += 1
    return cancelled

async def send_video_message(message_obj, video_message_id: int, caption: str, markup=None, log_context: str = ""):
    """Helper function to send video message with fallback to text"""
    try:
        video_message = await bot.get_messages(chat_id="Wolfy004", message_ids=video_message_id)
        if video_message and video_message.video:
            return await message_obj.reply_video(
                video=video_message.video.file_id,
                caption=caption,
                reply_markup=markup
            )
        else:
            return await message_obj.reply(caption, reply_markup=markup, disable_web_page_preview=True)
    except Exception as e:
        LOGGER(__name__).warning(f"Could not send video in {log_context}: {e}")
        return await message_obj.reply(caption, reply_markup=markup, disable_web_page_preview=True)

# Auto-add OWNER_ID as admin on startup
@bot.on_message(filters.command("start") & filters.create(lambda _, __, m: m.from_user.id == PyroConf.OWNER_ID), group=-1)
async def auto_add_owner_as_admin(_, message: Message):
    if PyroConf.OWNER_ID and not db.is_admin(PyroConf.OWNER_ID):
        db.add_admin(PyroConf.OWNER_ID, PyroConf.OWNER_ID)
        LOGGER(__name__).info(f"Auto-added owner {PyroConf.OWNER_ID} as admin")

@bot.on_message(filters.command("start") & filters.private & new_updates_only)
@register_user
async def start(_, message: Message):
    # Check if this is a verification deep link (format: /start verify_CODE)
    if len(message.command) > 1 and message.command[1].startswith("verify_"):
        verification_code = message.command[1].replace("verify_", "").strip()
        LOGGER(__name__).info(f"Auto-verification triggered for user {message.from_user.id} with code {verification_code}")
        
        success, msg = ad_monetization.verify_code(verification_code, message.from_user.id)
        
        if success:
            await message.reply(
                f"✅ **Automatic Verification Successful!**\n\n{msg}\n\n"
                "🎉 You can now start downloading!\n"
                "📥 Just paste any Telegram link to begin."
            )
            LOGGER(__name__).info(f"User {message.from_user.id} successfully auto-verified and received downloads")
        else:
            await message.reply(
                f"❌ **Verification Failed**\n\n{msg}\n\n"
                "Please try getting a new code with `/getpremium`"
            )
        return
    
    welcome_text = (
        "🎉 **Welcome to Save Restricted Content Bot!**\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🚀 **Quick Start Guide:**\n\n"
        "**Step 1:** Login with your phone\n"
        "   📱 Use: `/login +1234567890`\n\n"
        "**Step 2:** Verify with OTP\n"
        "   🔐 Enter the code you receive\n\n"
        "**Step 3:** Start downloading!\n"
        "   📥 Just paste any Telegram link\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "💎 **Get Free Downloads:**\n\n"
        "🎁 **Option 1: FREE (Watch Ads)**\n"
        "   📥 5 free download per ad session\n"
        "   📺 Complete quick verification steps\n"
        "   ♻️ Repeat anytime!\n"
        "   👉 Use: `/getpremium`\n\n"
        "💰 **Option 2: Paid ($1/month)**\n"
        "   ⭐ 30 days unlimited access\n"
        "   🚀 Priority downloads\n"
        "   📦 Batch download support\n"
        "   👉 Use: `/upgrade`\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "ℹ️ **Need help?** Use `/help` for all commands\n\n"
        "🔑 **Ready to start?** Login now with `/login <phone>`"
    )

    # Verify attribution
    verify_attribution()
    
    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("📢 Update Channel", url=get_channel_link(primary=True))]]
    )
    
    # Add creator attribution to welcome message
    welcome_text += f"\n\n💡 **Created by:** {get_creator_username()}"
    
    await send_video_message(message, 41, welcome_text, markup, "start command")

@bot.on_message(filters.command("help") & filters.private)
@register_user
async def help_command(_, message: Message):
    user_id = message.from_user.id
    user_type = db.get_user_type(user_id)
    is_premium = user_type == 'paid'
    
    if is_premium:
        help_text = (
            "👑 **Premium User - Help Guide**\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📥 **Download Commands:**\n\n"
            "**Single Download:**\n"
            "   `/dl <link>` or just paste a link\n"
            "   📺 Videos • 🖼️ Photos • 🎵 Audio • 📄 Documents\n\n"
            "**Batch Download:**\n"
            "   `/bdl <start_link> <end_link>`\n"
            "   💡 Example: `/bdl https://t.me/channel/100 https://t.me/channel/120`\n"
            "   📦 Downloads all posts from 100 to 120 (max 20)\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🚀 **Queue System:**\n\n"
            "   👑 **Premium Priority** - Jump ahead in queue!\n"
            "   `/queue` - Check your position\n"
            "   `/canceldownload` - Cancel current download\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🔐 **Authentication:**\n\n"
            "   `/login +1234567890` - Login with phone\n"
            "   `/verify 1 2 3 4 5` - Enter OTP code\n"
            "   `/password <2FA>` - Enter 2FA password\n"
            "   `/logout` - Logout from account\n"
            "   `/cancel` - Cancel pending auth\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "ℹ️ **Other Commands:**\n\n"
            "   `/myinfo` - View account details\n"
            "   `/stats` - Bot statistics\n\n"
            "💡 **Your Benefits:**\n"
            "   ✅ Unlimited downloads\n"
            "   ✅ Priority queue access\n"
            "   ✅ Batch download (up to 20 posts)\n"
            "   ✅ No daily limits"
        )
    else:
        help_text = (
            "🆓 **Free User - Help Guide**\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📥 **Download Commands:**\n\n"
            "**Single Download:**\n"
            "   `/dl <link>` or just paste a link\n"
            "   📺 Videos • 🖼️ Photos • 🎵 Audio • 📄 Documents\n\n"
            "⚠️ **Your Limits:**\n"
            "   📊 1 download per day\n"
            "   ⏳ Normal queue priority\n"
            "   ❌ No batch downloads\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "💎 **Get More Downloads:**\n\n"
            "🎁 **FREE Downloads (Watch Ads):**\n"
            "   `/getpremium` - Get 5 free download\n"
            "   📺 Complete verification steps\n"
            "   ♻️ Repeat anytime!\n\n"
            "💰 **Paid Premium ($1/month):**\n"
            "   `/upgrade` - View payment options\n"
            "   ⭐ 30 days unlimited access\n"
            "   🚀 Priority downloads\n"
            "   📦 Batch download support\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🚀 **Queue System:**\n\n"
            "   `/queue` - Check your position\n"
            "   `/canceldownload` - Cancel download\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🔐 **Authentication:**\n\n"
            "   `/login +1234567890` - Login with phone\n"
            "   `/verify 1 2 3 4 5` - Enter OTP code\n"
            "   `/password <2FA>` - Enter 2FA password\n"
            "   `/logout` - Logout from account\n"
            "   `/cancel` - Cancel pending auth\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "ℹ️ **Other Commands:**\n\n"
            "   `/myinfo` - View account details\n"
            "   `/stats` - Bot statistics"
        )

    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("📢 Update Channel", url=get_channel_link(primary=True))]]
    )
    
    help_text += f"\n\n💡 **Bot by:** {get_creator_username()} | {get_channel_link(primary=True)}"
    
    await message.reply(help_text, reply_markup=markup, disable_web_page_preview=True)

async def handle_download(bot: Client, message: Message, post_url: str, user_client=None, increment_usage=True):
    """
    Handle downloading media from Telegram posts
    
    IMPORTANT: user_client is managed by SessionManager - DO NOT call .stop() on it!
    The SessionManager will automatically reuse and cleanup sessions to prevent memory leaks.
    """
    # Cut off URL at '?' if present
    if "?" in post_url:
        post_url = post_url.split("?", 1)[0]

    try:
        chat_id, message_id = getChatMsgID(post_url)

        # Use user's personal session (required for all users, including admins)
        client_to_use = user_client
        
        if not client_to_use:
                await message.reply(
                    "❌ **No active session found.**\n\n"
                    "Please login with your phone number:\n"
                    "`/login +1234567890`"
                )
                return

        chat_message = await client_to_use.get_messages(chat_id=chat_id, message_ids=message_id)

        LOGGER(__name__).info(f"Downloading media from URL: {post_url}")

        if chat_message.document or chat_message.video or chat_message.audio:
            file_size = (
                chat_message.document.file_size
                if chat_message.document
                else chat_message.video.file_size
                if chat_message.video
                else chat_message.audio.file_size
            )

            # Check file size limit based on actual client being used
            try:
                # Check if user's Telegram account has premium
                me = await client_to_use.get_me()
                is_premium = getattr(me, 'is_premium', False)
            except:
                is_premium = False

            if not await fileSizeLimit(file_size, message, "download", is_premium):
                return

        parsed_caption = await get_parsed_msg(
            chat_message.caption or "", chat_message.caption_entities
        )
        parsed_text = await get_parsed_msg(
            chat_message.text or "", chat_message.entities
        )

        if chat_message.media_group_id:
            # Count files in media group first for quota check
            media_group_messages = await chat_message.get_media_group()
            file_count = sum(1 for msg in media_group_messages if msg.photo or msg.video or msg.document or msg.audio)
            
            LOGGER(__name__).info(f"Media group detected with {file_count} files for user {message.from_user.id}")
            
            # Pre-flight quota check before downloading
            if increment_usage:
                can_dl, quota_msg = db.can_download(message.from_user.id, file_count)
                if not can_dl:
                    from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                    keyboard = InlineKeyboardMarkup([
                        [InlineKeyboardButton(f"🎁 Watch Ad & Get {PREMIUM_DOWNLOADS} Downloads", callback_data="watch_ad_now")],
                        [InlineKeyboardButton("💰 Upgrade to Premium", callback_data="upgrade_premium")]
                    ])
                    await message.reply(quota_msg, reply_markup=keyboard)
                    return
            
            # Download media group
            files_sent = await processMediaGroup(chat_message, bot, message, message.from_user.id)
            
            if files_sent == 0:
                await message.reply("**Could not extract any valid media from the media group.**")
                return
            
            # Increment usage by actual file count after successful download
            if increment_usage:
                success = db.increment_usage(message.from_user.id, files_sent)
                if not success:
                    LOGGER(__name__).error(f"Failed to increment usage for user {message.from_user.id} after media group download")
                
                # Show completion message with buttons for all free users
                user_type = db.get_user_type(message.from_user.id)
                if user_type == 'free':
                    from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                    upgrade_keyboard = InlineKeyboardMarkup([
                        [InlineKeyboardButton(f"🎁 Watch Ad & Get {PREMIUM_DOWNLOADS} Downloads", callback_data="watch_ad_now")],
                        [InlineKeyboardButton("💰 Upgrade to Premium", callback_data="upgrade_premium")]
                    ])
                    
                    await message.reply(
                        "✅ **Download complete**",
                        reply_markup=upgrade_keyboard
                    )
            
            return

        elif chat_message.media:
            start_time = time()
            progress_message = await message.reply("**📥 Downloading Progress...**")

            filename = get_file_name(message_id, chat_message)
            download_path = get_download_path(message.id, filename)

            media_path = await chat_message.download(
                file_name=download_path,
                progress=safe_progress_callback,
                progress_args=progressArgs(
                    "📥 Downloading Progress", progress_message, start_time
                ),
            )

            LOGGER(__name__).info(f"Downloaded media: {media_path}")

            try:
                media_type = (
                    "photo"
                    if chat_message.photo
                    else "video"
                    if chat_message.video
                    else "audio"
                    if chat_message.audio
                    else "document"
                )
                await send_media(
                    bot,
                    message,
                    media_path,
                    media_type,
                    parsed_caption,
                    progress_message,
                    start_time,
                    message.from_user.id,
                )

                await progress_message.delete()

                # Only increment usage after successful download
                if increment_usage:
                    db.increment_usage(message.from_user.id)
                    
                    # Show completion message with buttons for all free users
                    user_type = db.get_user_type(message.from_user.id)
                    if user_type == 'free':
                        from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                        upgrade_markup = InlineKeyboardMarkup([
                            [InlineKeyboardButton(f"🎁 Watch Ad & Get {PREMIUM_DOWNLOADS} Downloads", callback_data="watch_ad_now")],
                            [InlineKeyboardButton("💰 Upgrade to Premium", callback_data="upgrade_premium")]
                        ])
                        await message.reply(
                            "✅ **Download complete**",
                            reply_markup=upgrade_markup
                        )
            finally:
                # CRITICAL: Always cleanup downloaded file, even if errors occur during upload
                cleanup_download(media_path)

        elif chat_message.text or chat_message.caption:
            await message.reply(parsed_text or parsed_caption)
        else:
            await message.reply("**No media or text found in the post URL.**")

    except (PeerIdInvalid, BadRequest, KeyError):
        await message.reply("**Make sure the user client is part of the chat.**")
    except Exception as e:
        error_message = f"**❌ {str(e)}**"
        await message.reply(error_message)
        LOGGER(__name__).error(e)

@bot.on_message(filters.command("dl") & filters.private)
@force_subscribe
@check_download_limit
async def download_media(bot: Client, message: Message):
    if len(message.command) < 2:
        await message.reply("**Provide a post URL after the /dl command.**")
        return

    post_url = message.command[1]

    # Check if user has personal session
    user_client = await get_user_client(message.from_user.id)
    
    # Check if user is premium for queue priority
    is_premium = db.get_user_type(message.from_user.id) in ['premium', 'admin']
    
    # Add to download queue
    download_coro = handle_download(bot, message, post_url, user_client, True)
    success, msg = await download_queue.add_to_queue(
        message.from_user.id,
        download_coro,
        message,
        post_url,
        is_premium
    )
    
    await message.reply(msg)

@bot.on_message(filters.command("bdl") & filters.private)
@force_subscribe
@paid_or_admin_only
async def download_range(bot: Client, message: Message):
    args = message.text.split()

    if len(args) != 3 or not all(arg.startswith("https://t.me/") for arg in args[1:]):
        await message.reply(
            "🚀 **Batch Download Process**\n"
            "`/bdl start_link end_link`\n\n"
            "💡 **Example:**\n"
            "`/bdl https://t.me/mychannel/100 https://t.me/mychannel/120`"
        )
        return

    # Check if user already has a batch running
    user_tasks = get_user_tasks(message.from_user.id)
    if user_tasks:
        running_count = sum(1 for task in user_tasks if not task.done())
        if running_count > 0:
            await message.reply(
                f"❌ **You already have {running_count} download(s) running!**\n\n"
                "Please wait for them to finish or use `/canceldownload` to cancel them."
            )
            return

    try:
        start_chat, start_id = getChatMsgID(args[1])
        end_chat,   end_id   = getChatMsgID(args[2])
    except Exception as e:
        return await message.reply(f"**❌ Error parsing links:\n{e}**")

    if start_chat != end_chat:
        return await message.reply("**❌ Both links must be from the same channel.**")
    if start_id > end_id:
        return await message.reply("**❌ Invalid range: start ID cannot exceed end ID.**")
    
    # Limit batch to 20 posts at a time
    batch_count = end_id - start_id + 1
    if batch_count > 20:
        return await message.reply(
            f"**❌ Batch limit exceeded!**\n\n"
            f"You requested `{batch_count}` posts, but the maximum is **20 posts** at a time.\n\n"
            f"Please reduce your range and try again."
        )

    # Check if user has personal session (required for all users, including admins)
    user_client = await get_user_client(message.from_user.id)
    client_to_use = user_client
    
    if not client_to_use:
            await message.reply(
                "❌ **No active session found.**\n\n"
                "Please login with your phone number:\n"
                "`/login +1234567890`"
            )
            return

    try:
        await client_to_use.get_chat(start_chat)
    except Exception:
        pass

    prefix = args[1].rsplit("/", 1)[0]
    loading = await message.reply(f"📥 **Downloading posts {start_id}–{end_id}…**")

    downloaded = skipped = failed = 0

    for msg_id in range(start_id, end_id + 1):
        url = f"{prefix}/{msg_id}"
        try:
            chat_msg = await client_to_use.get_messages(chat_id=start_chat, message_ids=msg_id)
            if not chat_msg:
                skipped += 1
                continue

            has_media = bool(chat_msg.media_group_id or chat_msg.media)
            has_text  = bool(chat_msg.text or chat_msg.caption)
            if not (has_media or has_text):
                skipped += 1
                continue

            task = track_task(handle_download(bot, message, url, client_to_use, False), message.from_user.id)
            try:
                await task
                downloaded += 1
                # Increment usage count for batch downloads after success
                db.increment_usage(message.from_user.id)
            except asyncio.CancelledError:
                await loading.delete()
                # SessionManager will handle client cleanup - no need to stop() here
                return await message.reply(
                    f"**❌ Batch canceled** after downloading `{downloaded}` posts."
                )

        except Exception as e:
            failed += 1
            LOGGER(__name__).error(f"Error at {url}: {e}")

        await asyncio.sleep(3)

    await loading.delete()
    
    # SessionManager will handle client cleanup - no need to stop() here
    
    await message.reply(
        "**✅ Batch Process Complete!**\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"📥 **Downloaded** : `{downloaded}` post(s)\n"
        f"⏭️ **Skipped**    : `{skipped}` (no content)\n"
        f"❌ **Failed**     : `{failed}` error(s)"
    )

# Phone authentication commands
@bot.on_message(filters.command("login") & filters.private)
@register_user
async def login_command(client: Client, message: Message):
    """Start login process with phone number"""
    try:
        if len(message.command) < 2:
            await message.reply(
                "**Usage:** `/login +1234567890`\n\n"
                "**Example:** `/login +919876543210`\n\n"
                "Make sure to include country code with +"
            )
            return

        phone_number = message.command[1].strip()

        if not phone_number.startswith('+'):
            await message.reply("❌ **Please include country code with + sign.**\n\n**Example:** `/login +1234567890`")
            return

        # Send OTP
        success, msg, _ = await phone_auth_handler.send_otp(message.from_user.id, phone_number)
        await message.reply(msg)

    except Exception as e:
        await message.reply(f"❌ **Error: {str(e)}**")
        LOGGER(__name__).error(f"Error in login_command: {e}")

@bot.on_message(filters.command("verify") & filters.private)
@register_user
async def verify_command(client: Client, message: Message):
    """Verify OTP code"""
    try:
        if len(message.command) < 2:
            await message.reply(
                "**Usage:** `/verify 1 2 3 4 5` (with spaces between digits)\n\n"
                "**Example:** If code is 12345, send:\n"
                "`/verify 1 2 3 4 5`"
            )
            return

        # Get OTP code (all arguments after /verify)
        otp_code = ' '.join(message.command[1:])

        # Verify OTP
        LOGGER(__name__).info(f"Calling verify_otp for user {message.from_user.id}")
        result = await phone_auth_handler.verify_otp(message.from_user.id, otp_code)
        LOGGER(__name__).info(f"verify_otp returned {len(result)} items for user {message.from_user.id}")

        if len(result) == 4:
            success, msg, needs_2fa, session_string = result
            LOGGER(__name__).info(f"Received session_string for user {message.from_user.id}, length: {len(session_string) if session_string else 0}")
        else:
            success, msg, needs_2fa = result
            session_string = None
            LOGGER(__name__).warning(f"No session_string in result for user {message.from_user.id}")

        await message.reply(msg)

        # Save session string if authentication successful
        if success and session_string:
            LOGGER(__name__).info(f"Attempting to save session for user {message.from_user.id}")
            result = db.set_user_session(message.from_user.id, session_string)
            LOGGER(__name__).info(f"Session save result for user {message.from_user.id}: {result}")
            # Verify it was saved
            saved_session = db.get_user_session(message.from_user.id)
            if saved_session:
                LOGGER(__name__).info(f"✅ Verified: Session successfully saved and retrieved for user {message.from_user.id}")
            else:
                LOGGER(__name__).error(f"❌ ERROR: Session save failed! Could not retrieve session for user {message.from_user.id}")
        else:
            LOGGER(__name__).info(f"Not saving session for user {message.from_user.id} - success: {success}, has_session_string: {session_string is not None}")

    except Exception as e:
        await message.reply(f"❌ **Error: {str(e)}**")
        LOGGER(__name__).error(f"Error in verify_command: {e}")

@bot.on_message(filters.command("password") & filters.private)
@register_user
async def password_command(client: Client, message: Message):
    """Enter 2FA password"""
    try:
        if len(message.command) < 2:
            await message.reply(
                "**Usage:** `/password <YOUR_2FA_PASSWORD>`\n\n"
                "**Example:** `/password MySecretPassword123`"
            )
            return

        # Get password (everything after /password)
        password = message.text.split(' ', 1)[1]

        # Verify 2FA
        success, msg, session_string = await phone_auth_handler.verify_2fa_password(message.from_user.id, password)
        await message.reply(msg)

        # Save session string if successful
        if success and session_string:
            db.set_user_session(message.from_user.id, session_string)
            LOGGER(__name__).info(f"Saved session for user {message.from_user.id} after 2FA")

    except Exception as e:
        await message.reply(f"❌ **Error: {str(e)}**")
        LOGGER(__name__).error(f"Error in password_command: {e}")

@bot.on_message(filters.command("logout") & filters.private)
@register_user
async def logout_command(client: Client, message: Message):
    """Logout from account"""
    try:
        if db.set_user_session(message.from_user.id, None):
            # Also remove from SessionManager to free memory immediately
            from helpers.session_manager import session_manager
            await session_manager.remove_session(message.from_user.id)
            
            await message.reply(
                "✅ **Successfully logged out!**\n\n"
                "Use `/login <phone_number>` to login again."
            )
            LOGGER(__name__).info(f"User {message.from_user.id} logged out")
        else:
            await message.reply("❌ **You are not logged in.**")

    except Exception as e:
        await message.reply(f"❌ **Error: {str(e)}**")

@bot.on_message(filters.command("cancel") & filters.private)
@register_user
async def cancel_command(client: Client, message: Message):
    """Cancel pending authentication"""
    success, msg = await phone_auth_handler.cancel_auth(message.from_user.id)
    await message.reply(msg)

@bot.on_message(filters.command("canceldownload") & filters.private)
@register_user
async def cancel_download_command(client: Client, message: Message):
    """Cancel user's running downloads"""
    success, msg = await download_queue.cancel_user_download(message.from_user.id)
    await message.reply(msg)
    if success:
        LOGGER(__name__).info(f"User {message.from_user.id} cancelled download")

@bot.on_message(filters.command("queue") & filters.private)
@register_user
async def queue_status_command(client: Client, message: Message):
    """Check your download queue status"""
    status = await download_queue.get_queue_status(message.from_user.id)
    await message.reply(status)

@bot.on_message(filters.command("qstatus") & filters.private)
@admin_only
async def global_queue_status_command(client: Client, message: Message):
    """Check global download queue status (admin only)"""
    status = await download_queue.get_global_status()
    await message.reply(status)

@bot.on_message(filters.private & new_updates_only & ~filters.command(["start", "help", "dl", "stats", "logs", "killall", "bdl", "myinfo", "upgrade", "premiumlist", "getpremium", "verifypremium", "login", "verify", "password", "logout", "cancel", "canceldownload", "queue", "qstatus", "setthumb", "delthumb", "viewthumb", "addadmin", "removeadmin", "setpremium", "removepremium", "ban", "unban", "broadcast", "adminstats", "userinfo", "testdump"]))
@force_subscribe
@check_download_limit
async def handle_any_message(bot: Client, message: Message):
    if message.text and not message.text.startswith("/"):
        # Check if user is premium for queue priority
        is_premium = db.get_user_type(message.from_user.id) in ['premium', 'admin']
        
        # Check if user already has an active download (quick check before getting client)
        async with download_queue._lock:
            if message.from_user.id in download_queue.user_queue_positions or message.from_user.id in download_queue.active_downloads:
                position = download_queue.get_queue_position(message.from_user.id)
                if message.from_user.id in download_queue.active_downloads:
                    await message.reply(
                        "❌ **You already have a download in progress!**\n\n"
                        "⏳ Please wait for it to complete.\n\n"
                        "💡 **Want to download this instead?**\n"
                        "Use `/canceldownload` to cancel the current download."
                    )
                    return
                else:
                    await message.reply(
                        f"❌ **You already have a download in the queue!**\n\n"
                        f"📍 **Position:** #{position}/{len(download_queue.waiting_queue)}\n\n"
                        f"💡 **Want to cancel it?**\n"
                        f"Use `/canceldownload` to remove from queue."
                    )
                    return
        
        # Check if user has personal session
        user_client = await get_user_client(message.from_user.id)
        
        # Add to download queue
        download_coro = handle_download(bot, message, message.text, user_client, True)
        success, msg = await download_queue.add_to_queue(
            message.from_user.id,
            download_coro,
            message,
            message.text,
            is_premium
        )
        
        if msg:  # Only reply if there's a message to send
            await message.reply(msg)

@bot.on_message(filters.command("stats") & filters.private)
@register_user
async def stats(_, message: Message):
    currentTime = get_readable_time(int(time() - PyroConf.BOT_START_TIME))
    process = psutil.Process(os.getpid())
    
    bot_memory_mb = round(process.memory_info()[0] / 1024**2)
    cpu_percent = process.cpu_percent(interval=0.1)

    stats_text = (
        "🤖 **BOT STATUS**\n"
        "—————————————————————\n\n"
        "✨ **Status:** Online & Running\n\n"
        "📊 **System Metrics:**\n"
        f"⏱️ Uptime: `{currentTime}`\n"
        f"💾 Memory: `{bot_memory_mb} MiB`\n"
        f"⚡ CPU: `{cpu_percent}%`\n\n"
        "—————————————————————\n\n"
        "💡 **Quick Access:**\n"
        "• `/queue` - Check downloads\n"
        "• `/myinfo` - Your account\n"
        "• `/help` - All commands"
    )
    await message.reply(stats_text)

@bot.on_message(filters.command("logs") & filters.private)
@admin_only
async def logs(_, message: Message):
    await message.reply(
        "**📋 Bot Logging**\n\n"
        "Logs are stored in MongoDB and can be viewed via:\n"
        "• Database admin panel\n"
        "• Cloud hosting logs (Render/Railway dashboard)\n\n"
        "Use `/adminstats` for bot statistics."
    )

@bot.on_message(filters.command("killall") & filters.private)
@admin_only
async def cancel_all_tasks(_, message: Message):
    queue_cancelled = await download_queue.cancel_all_downloads()
    task_cancelled = 0
    for task in list(RUNNING_TASKS):
        if not task.done():
            task.cancel()
            task_cancelled += 1
    total_cancelled = queue_cancelled + task_cancelled
    await message.reply(
        f"✅ **All downloads cancelled!**\n\n"
        f"📊 **Queue downloads:** {queue_cancelled}\n"
        f"📊 **Other tasks:** {task_cancelled}\n"
        f"📊 **Total:** {total_cancelled}"
    )

# Thumbnail commands
@bot.on_message(filters.command("setthumb") & filters.private)
@register_user
async def set_thumbnail(_, message: Message):
    """Set custom thumbnail for video uploads"""
    if message.reply_to_message and message.reply_to_message.photo:
        # User replied to a photo
        photo = message.reply_to_message.photo
        file_id = photo.file_id
        
        if db.set_custom_thumbnail(message.from_user.id, file_id):
            await message.reply(
                "✅ **Custom thumbnail saved successfully!**\n\n"
                "This thumbnail will be used for all your video downloads.\n\n"
                "Use `/delthumb` to remove it."
            )
            LOGGER(__name__).info(f"User {message.from_user.id} set custom thumbnail")
        else:
            await message.reply("❌ **Failed to save thumbnail. Please try again.**")
    else:
        await message.reply(
            "📸 **How to set a custom thumbnail:**\n\n"
            "1. Send or forward a photo to the bot\n"
            "2. Reply to that photo with `/setthumb`\n\n"
            "The photo will be used as thumbnail for all your video downloads."
        )

@bot.on_message(filters.command("delthumb") & filters.private)
@register_user
async def delete_thumbnail(_, message: Message):
    """Delete custom thumbnail"""
    if db.delete_custom_thumbnail(message.from_user.id):
        await message.reply(
            "✅ **Custom thumbnail removed!**\n\n"
            "Videos will now use auto-generated thumbnails from the video itself."
        )
        LOGGER(__name__).info(f"User {message.from_user.id} deleted custom thumbnail")
    else:
        await message.reply("ℹ️ **You don't have a custom thumbnail set.**")

@bot.on_message(filters.command("viewthumb") & filters.private)
@register_user
async def view_thumbnail(_, message: Message):
    """View current custom thumbnail"""
    thumb_id = db.get_custom_thumbnail(message.from_user.id)
    if thumb_id:
        try:
            await message.reply_photo(
                thumb_id,
                caption="**Your current custom thumbnail**\n\nUse `/delthumb` to remove it."
            )
        except:
            await message.reply(
                "⚠️ **Thumbnail exists but couldn't be displayed.**\n\n"
                "It might have expired. Please set a new one with `/setthumb`"
            )
    else:
        await message.reply(
            "ℹ️ **You don't have a custom thumbnail set.**\n\n"
            "Use `/setthumb` to set one."
        )

# Admin commands
@bot.on_message(filters.command("addadmin") & filters.private)
async def add_admin_handler(client: Client, message: Message):
    await add_admin_command(client, message)

@bot.on_message(filters.command("removeadmin") & filters.private)
async def remove_admin_handler(client: Client, message: Message):
    await remove_admin_command(client, message)

@bot.on_message(filters.command("setpremium") & filters.private)
async def set_premium_handler(client: Client, message: Message):
    await set_premium_command(client, message)

@bot.on_message(filters.command("removepremium") & filters.private)
async def remove_premium_handler(client: Client, message: Message):
    await remove_premium_command(client, message)

@bot.on_message(filters.command("ban") & filters.private)
async def ban_user_handler(client: Client, message: Message):
    await ban_user_command(client, message)

@bot.on_message(filters.command("unban") & filters.private)
async def unban_user_handler(client: Client, message: Message):
    await unban_user_command(client, message)

@bot.on_message(filters.command("broadcast") & filters.private)
async def broadcast_handler(client: Client, message: Message):
    await broadcast_command(client, message)

@bot.on_message(filters.command("testdump") & filters.private)
@admin_only
async def test_dump_channel(bot: Client, message: Message):
    """Test dump channel configuration (admin only)"""
    from config import PyroConf
    
    if not PyroConf.DUMP_CHANNEL_ID:
        await message.reply("❌ **Dump channel not configured**\n\nSet DUMP_CHANNEL_ID in your environment variables.")
        return
    
    try:
        channel_id = int(PyroConf.DUMP_CHANNEL_ID)
        # Try to get chat info
        chat = await bot.get_chat(channel_id)
        
        # Try sending a test message
        test_msg = await bot.send_message(
            chat_id=channel_id,
            text=f"✅ **Dump Channel Test**\n\n👤 Test by Admin: {message.from_user.id}\n\nDump channel is working correctly!"
        )
        
        await message.reply(
            f"✅ **Dump Channel Working!**\n\n"
            f"📱 **Channel:** {chat.title}\n"
            f"🆔 **ID:** `{channel_id}`\n"
            f"✉️ **Test message sent successfully**\n\n"
            f"All downloaded media will be forwarded to this channel."
        )
    except Exception as e:
        await message.reply(
            f"❌ **Dump Channel Error**\n\n"
            f"**Error:** {str(e)}\n\n"
            f"**How to fix:**\n"
            f"1. Forward any message from your channel to @userinfobot to get the correct channel ID\n"
            f"2. Make sure bot is added to the channel\n"
            f"3. Make bot an administrator with 'Post Messages' permission\n"
            f"4. Update DUMP_CHANNEL_ID in Replit Secrets"
        )

@bot.on_message(filters.command("adminstats") & filters.private)
async def admin_stats_handler(client: Client, message: Message):
    await admin_stats_command(client, message, queue_manager=download_queue)

@bot.on_message(filters.command("getpremium") & filters.private)
@register_user
async def get_premium_command(client: Client, message: Message):
    """Generate ad link for temporary premium access"""
    LOGGER(__name__).info(f"get_premium_command triggered by user {message.from_user.id}")
    try:
        user_type = db.get_user_type(message.from_user.id)
        
        if user_type == 'paid':
            user = db.get_user(message.from_user.id)
            expiry_date_str = user.get('subscription_end', 'N/A')
            
            # Calculate time remaining
            time_left_msg = ""
            if expiry_date_str != 'N/A':
                try:
                    from datetime import datetime
                    expiry_date = datetime.strptime(expiry_date_str, '%Y-%m-%d %H:%M:%S')
                    time_remaining = expiry_date - datetime.now()
                    
                    days = time_remaining.days
                    hours = time_remaining.seconds // 3600
                    minutes = (time_remaining.seconds % 3600) // 60
                    
                    if days > 0:
                        time_left_msg = f"⏱️ **Expires in:** {days} days, {hours} hours"
                    elif hours > 0:
                        time_left_msg = f"⏱️ **Expires in:** {hours} hours, {minutes} minutes"
                    else:
                        time_left_msg = f"⏱️ **Expires in:** {minutes} minutes"
                except:
                    time_left_msg = f"📅 **Valid until:** {expiry_date_str}"
            else:
                time_left_msg = "📅 **Permanent premium**"
            
            await message.reply(
                f"✅ **You already have premium subscription!**\n\n"
                f"{time_left_msg}\n\n"
                f"No need to watch ads! Enjoy your unlimited downloads."
            )
            return
        
        bot_domain = PyroConf.get_app_url()
        
        verification_code, ad_url = ad_monetization.generate_droplink_ad_link(message.from_user.id, bot_domain)
        
        premium_text = (
            f"🎬 **Get {PREMIUM_DOWNLOADS} FREE downloads!**\n\n"
            "**How it works:**\n"
            "1️⃣ Click the button below\n"
            "2️⃣ View the short ad (5-10 seconds)\n"
            "3️⃣ Your verification code will appear automatically\n"
            "4️⃣ Copy the code and send: `/verifypremium <code>`\n\n"
            "⚠️ **Note:** Please wait for the ad page to fully load!\n\n"
            "⏱️ Code expires in 30 minutes"
        )
        
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"🎁 Watch Ad & Get {PREMIUM_DOWNLOADS} Downloads", url=ad_url)]
        ])
        
        # Send with video (message ID 42)
        await send_video_message(message, 42, premium_text, markup, "getpremium command")
        LOGGER(__name__).info(f"User {message.from_user.id} requested ad-based premium")
        
    except Exception as e:
        await message.reply(f"❌ **Error generating premium link:** {str(e)}")
        LOGGER(__name__).error(f"Error in get_premium_command: {e}")

@bot.on_message(filters.command("verifypremium") & filters.private)
@register_user
async def verify_premium_command(client: Client, message: Message):
    """Verify ad completion code and grant temporary premium"""
    LOGGER(__name__).info(f"verify_premium_command triggered by user {message.from_user.id}")
    try:
        if len(message.command) < 2:
            await message.reply(
                "**Usage:** `/verifypremium <code>`\n\n"
                "**Example:** `/verifypremium ABC123DEF456`\n\n"
                "Get your code by using `/getpremium` first!"
            )
            return
        
        verification_code = message.command[1].strip()
        
        success, msg = ad_monetization.verify_code(verification_code, message.from_user.id)
        
        if success:
            await message.reply(msg)
            LOGGER(__name__).info(f"User {message.from_user.id} successfully verified ad code and received downloads")
        else:
            await message.reply(msg)
            
    except Exception as e:
        await message.reply(f"❌ **Error verifying code:** {str(e)}")
        LOGGER(__name__).error(f"Error in verify_premium_command: {e}")

@bot.on_message(filters.command("upgrade") & filters.private)
@register_user
async def upgrade_command(client: Client, message: Message):
    """Show premium upgrade information with pricing and payment details"""
    upgrade_text = (
        "💎 **Upgrade to Premium**\n\n"
        "**Premium Features:**\n"
        "✅ Unlimited downloads per day\n"
        "✅ Batch download support (/bdl command)\n"
        "✅ Download up to 20 posts at once\n"
        "✅ Priority support\n"
        "✅ No daily limits\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "**🎯 Option 1: Watch Ads (FREE)**\n"
        f"📥 **{PREMIUM_DOWNLOADS} Free Downloads**\n"
        "📺 Complete quick verification steps!\n\n"
        "**How it works:**\n"
        "1️⃣ Use `/getpremium` command\n"
        "2️⃣ Click the link and complete 3 steps\n"
        "3️⃣ Get verification code\n"
        "4️⃣ Send code back to bot\n"
        f"5️⃣ Enjoy {PREMIUM_DOWNLOADS} free downloads! 🎉\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "**💰 Option 2: Monthly Subscription**\n"
        "💵 **30 Days Premium = $1 USD**\n\n"
        "**How to Subscribe:**\n"
    )
    
    # Add payment information if configured
    payment_methods_available = PyroConf.PAYPAL_URL or PyroConf.UPI_ID or PyroConf.TELEGRAM_TON or PyroConf.CRYPTO_ADDRESS
    
    if payment_methods_available:
        upgrade_text += "1️⃣ **Make Payment (Choose any method):**\n"
        
        if PyroConf.PAYPAL_URL:
            upgrade_text += f"   💳 **PayPal:** {PyroConf.PAYPAL_URL}\n"
        
        if PyroConf.UPI_ID:
            upgrade_text += f"   📱 **UPI (India):** `{PyroConf.UPI_ID}`\n"
        
        if PyroConf.TELEGRAM_TON:
            upgrade_text += f"   🛒 **Telegram Pay (TON):** `{PyroConf.TELEGRAM_TON}`\n"
        
        if PyroConf.CRYPTO_ADDRESS:
            upgrade_text += f"   ₿ **Crypto (USDT/BTC/ETH):** `{PyroConf.CRYPTO_ADDRESS}`\n"
        
        upgrade_text += "\n"
    
    # Add contact information
    if PyroConf.ADMIN_USERNAME:
        upgrade_text += f"2️⃣ **Contact Admin:**\n   👤 @{PyroConf.ADMIN_USERNAME}\n\n"
    else:
        upgrade_text += f"2️⃣ **Contact Admin:**\n   👤 Contact the bot owner\n\n"
    
    upgrade_text += (
        "3️⃣ **Send Payment Proof:**\n"
        "   Send screenshot/transaction ID to admin\n\n"
        "4️⃣ **Get Activated:**\n"
        "   Admin will activate your premium within 24 hours!"
    )
    
    await message.reply(upgrade_text, disable_web_page_preview=True)

@bot.on_message(filters.command("premiumlist") & filters.private)
async def premium_list_command(client: Client, message: Message):
    """Show list of all premium users (Owner only)"""
    if message.from_user.id != PyroConf.OWNER_ID:
        await message.reply("❌ **This command is only available to the bot owner.**")
        return
    
    premium_users = db.get_premium_users()
    
    if not premium_users:
        await message.reply("ℹ️ **No premium users found.**")
        return
    
    premium_text = "💎 **Premium Users List**\n\n"
    
    for idx, user in enumerate(premium_users, 1):
        user_id = user.get('user_id', 'Unknown')
        username = user.get('username', 'N/A')
        expiry_date = user.get('premium_expiry', 'N/A')
        
        premium_text += f"{idx}. **User ID:** `{user_id}`\n"
        if username and username != 'N/A':
            premium_text += f"   **Username:** @{username}\n"
        premium_text += f"   **Expires:** {expiry_date}\n\n"
    
    premium_text += f"**Total Premium Users:** {len(premium_users)}"
    
    await message.reply(premium_text)

@bot.on_message(filters.command("myinfo") & filters.private)
async def myinfo_handler(client: Client, message: Message):
    await user_info_command(client, message)

# Callback query handler
@bot.on_callback_query()
async def callback_handler(client: Client, callback_query: CallbackQuery):
    data = callback_query.data
    
    if data == "get_free_premium":
        user_id = callback_query.from_user.id
        user_type = db.get_user_type(user_id)
        
        if user_type == 'paid':
            await callback_query.answer("You already have premium subscription!", show_alert=True)
            return
        
        bot_domain = PyroConf.get_app_url()
        verification_code, ad_url = ad_monetization.generate_droplink_ad_link(user_id, bot_domain)
        
        premium_text = (
            f"🎬 **Get {PREMIUM_DOWNLOADS} FREE downloads!**\n\n"
            "**How it works:**\n"
            "1️⃣ Click the button below\n"
            "2️⃣ View the short ad (5-10 seconds)\n"
            "3️⃣ Your verification code will appear automatically\n"
            "4️⃣ Copy the code and send: `/verifypremium <code>`\n\n"
            "⚠️ **Note:** Please wait for the ad page to fully load!\n\n"
            "⏱️ Code expires in 30 minutes"
        )
        
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"🎁 Watch Ad & Get {PREMIUM_DOWNLOADS} Downloads", url=ad_url)]
        ])
        
        await callback_query.answer()
        
        # Send with video (message ID 42)
        await send_video_message(callback_query.message, 42, premium_text, markup, "get_free_premium callback")
        LOGGER(__name__).info(f"User {user_id} requested ad-based premium via button")
        
    elif data == "get_paid_premium":
        await callback_query.answer()
        
        upgrade_text = (
            "💎 **Upgrade to Premium**\n\n"
            "**Premium Features:**\n"
            "✅ Unlimited downloads per day\n"
            "✅ Batch download support (/bdl command)\n"
            "✅ Download up to 20 posts at once\n"
            "✅ Priority support\n"
            "✅ No daily limits\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "**🎯 Option 1: Watch Ads (FREE)**\n"
            f"🎁 **Get {PREMIUM_DOWNLOADS} FREE Downloads**\n"
            "📺 Just watch a short ad!\n\n"
            "**How it works:**\n"
            "1️⃣ Use `/getpremium` command\n"
            "2️⃣ Complete 3 verification steps\n"
            "3️⃣ Get verification code\n"
            "4️⃣ Send code back to bot\n"
            f"5️⃣ Enjoy {PREMIUM_DOWNLOADS} free downloads! 🎉\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "**💰 Option 2: Monthly Subscription**\n"
            "💵 **30 Days Premium = $1 USD**\n\n"
            "**How to Subscribe:**\n"
        )
        
        payment_methods_available = PyroConf.PAYPAL_URL or PyroConf.UPI_ID or PyroConf.TELEGRAM_TON or PyroConf.CRYPTO_ADDRESS
        
        if payment_methods_available:
            upgrade_text += "1️⃣ **Make Payment (Choose any method):**\n"
            
            if PyroConf.PAYPAL_URL:
                upgrade_text += f"   💳 **PayPal:** {PyroConf.PAYPAL_URL}\n"
            
            if PyroConf.UPI_ID:
                upgrade_text += f"   📱 **UPI (India):** `{PyroConf.UPI_ID}`\n"
            
            if PyroConf.TELEGRAM_TON:
                upgrade_text += f"   🛒 **Telegram Pay (TON):** `{PyroConf.TELEGRAM_TON}`\n"
            
            if PyroConf.CRYPTO_ADDRESS:
                upgrade_text += f"   ₿ **Crypto (USDT/BTC/ETH):** `{PyroConf.CRYPTO_ADDRESS}`\n"
            
            upgrade_text += "\n"
        
        if PyroConf.ADMIN_USERNAME:
            upgrade_text += f"2️⃣ **Contact Admin:**\n   👤 @{PyroConf.ADMIN_USERNAME}\n\n"
        else:
            upgrade_text += f"2️⃣ **Contact Admin:**\n   👤 Contact the bot owner\n\n"
        
        upgrade_text += (
            "3️⃣ **Send Payment Proof:**\n"
            "   Send screenshot/transaction ID to admin\n\n"
            "4️⃣ **Get Activated:**\n"
            "   Admin will activate your premium within 24 hours!"
        )
        
        await callback_query.message.reply(upgrade_text, disable_web_page_preview=True)
    
    elif data == "watch_ad_now":
        user_id = callback_query.from_user.id
        user_type = db.get_user_type(user_id)
        
        if user_type == 'paid':
            await callback_query.answer("You already have premium subscription!", show_alert=True)
            return
        
        bot_domain = PyroConf.get_app_url()
        verification_code, ad_url = ad_monetization.generate_droplink_ad_link(user_id, bot_domain)
        
        premium_text = (
            f"🎬 **Get {PREMIUM_DOWNLOADS} FREE downloads!**\n\n"
            "**How it works:**\n"
            "1️⃣ Click the button below\n"
            "2️⃣ View the short ad (5-10 seconds)\n"
            "3️⃣ Your verification code will appear automatically\n"
            "4️⃣ Copy the code and send: `/verifypremium <code>`\n\n"
            "⚠️ **Note:** Please wait for the ad page to fully load!\n\n"
            "⏱️ Code expires in 30 minutes"
        )
        
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"🎁 Watch Ad & Get {PREMIUM_DOWNLOADS} Downloads", url=ad_url)]
        ])
        
        await callback_query.answer()
        
        # Send with video (message ID 42)
        await send_video_message(callback_query.message, 42, premium_text, markup, "watch_ad_now callback")
        LOGGER(__name__).info(f"User {user_id} requested ad-based download via button")
    
    elif data == "upgrade_premium":
        await callback_query.answer()
        
        upgrade_text = (
            "💎 **Upgrade to Premium**\n\n"
            "**Premium Features:**\n"
            "✅ Unlimited downloads per day\n"
            "✅ Batch download support (/bdl command)\n"
            "✅ Download up to 20 posts at once\n"
            "✅ Priority support\n"
            "✅ No daily limits\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "**🎯 Option 1: Watch Ads (FREE)**\n"
            f"🎁 **Get {PREMIUM_DOWNLOADS} FREE Download**\n"
            "📺 Just watch a short ad!\n\n"
            "**How it works:**\n"
            "1️⃣ Use `/getpremium` command\n"
            "2️⃣ Complete 3 verification steps\n"
            "3️⃣ Get verification code\n"
            "4️⃣ Send code back to bot\n"
            f"5️⃣ Enjoy {PREMIUM_DOWNLOADS} free download! 🎉\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "**💰 Option 2: Monthly Subscription**\n"
            "💵 **30 Days Premium = $1 USD**\n\n"
            "**How to Subscribe:**\n"
        )
        
        payment_methods_available = PyroConf.PAYPAL_URL or PyroConf.UPI_ID or PyroConf.TELEGRAM_TON or PyroConf.CRYPTO_ADDRESS
        
        if payment_methods_available:
            upgrade_text += "1️⃣ **Make Payment (Choose any method):**\n"
            
            if PyroConf.PAYPAL_URL:
                upgrade_text += f"   💳 **PayPal:** {PyroConf.PAYPAL_URL}\n"
            
            if PyroConf.UPI_ID:
                upgrade_text += f"   📱 **UPI (India):** `{PyroConf.UPI_ID}`\n"
            
            if PyroConf.TELEGRAM_TON:
                upgrade_text += f"   🛒 **Telegram Pay (TON):** `{PyroConf.TELEGRAM_TON}`\n"
            
            if PyroConf.CRYPTO_ADDRESS:
                upgrade_text += f"   ₿ **Crypto (USDT/BTC/ETH):** `{PyroConf.CRYPTO_ADDRESS}`\n"
            
            upgrade_text += "\n"
        
        if PyroConf.ADMIN_USERNAME:
            upgrade_text += f"2️⃣ **Contact Admin:**\n   👤 @{PyroConf.ADMIN_USERNAME}\n\n"
        else:
            upgrade_text += f"2️⃣ **Contact Admin:**\n   👤 Contact the bot owner\n\n"
        
        upgrade_text += (
            "3️⃣ **Send Payment Proof:**\n"
            "   Send screenshot/transaction ID to admin\n\n"
            "4️⃣ **Get Activated:**\n"
            "   Admin will activate your premium within 24 hours!"
        )
        
        await callback_query.message.reply(upgrade_text, disable_web_page_preview=True)
        
    else:
        await broadcast_callback_handler(client, callback_query)

# Start queue processor in background when module loads
def _init_queue():
    """Initialize queue processor on module load"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(download_queue.start_processor())
    LOGGER(__name__).info("Download queue processor initialized")

# Schedule queue processor startup
try:
    import threading
    threading.Thread(target=_init_queue, daemon=True).start()
except:
    LOGGER(__name__).warning("Could not start queue processor thread")

# Verify bot attribution on startup
verify_attribution()

# Verify dump channel configuration on startup
async def verify_dump_channel():
    """Verify that dump channel is accessible if configured"""
    from config import PyroConf
    
    if not PyroConf.DUMP_CHANNEL_ID:
        LOGGER(__name__).info("Dump channel not configured (optional feature)")
        return
    
    try:
        channel_id = int(PyroConf.DUMP_CHANNEL_ID)
        # Try to get channel info to verify bot has access
        chat = await bot.get_chat(channel_id)
        LOGGER(__name__).info(f"✅ Dump channel verified: {chat.title} (ID: {channel_id})")
        LOGGER(__name__).info("All downloaded media will be forwarded to dump channel")
    except Exception as e:
        LOGGER(__name__).error(f"❌ Dump channel configuration error: {e}")
        LOGGER(__name__).error(f"Make sure:")
        LOGGER(__name__).error(f"  1. DUMP_CHANNEL_ID is correct (e.g., -1001234567890)")
        LOGGER(__name__).error(f"  2. Bot is added to the channel as administrator")
        LOGGER(__name__).error(f"  3. Bot has permission to post messages")
        LOGGER(__name__).error(f"Dump channel feature will be disabled until fixed")

# Note: Periodic cleanup task is started from server.py when bot initializes
# This ensures downloaded files are cleaned up every 30 minutes to prevent memory/disk leaks

if __name__ == "__main__":
    try:
        LOGGER(__name__).info("Bot Started!")
        bot.run()
    except KeyboardInterrupt:
        pass
    except Exception as err:
        LOGGER(__name__).error(err)
    finally:
        # Gracefully disconnect all user sessions before shutdown
        try:
            import asyncio
            from helpers.session_manager import session_manager
            loop = asyncio.get_event_loop()
            if not loop.is_closed():
                loop.run_until_complete(session_manager.disconnect_all())
                LOGGER(__name__).info("Disconnected all user sessions")
        except Exception as e:
            LOGGER(__name__).error(f"Error disconnecting sessions: {e}")
        
        LOGGER(__name__).info("Bot Stopped")
