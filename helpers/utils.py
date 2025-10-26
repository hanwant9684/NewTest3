# Copyright (C) @TheSmartBisnu

import os
from time import time
from logger import LOGGER
from typing import Optional
from asyncio.subprocess import PIPE
from asyncio import create_subprocess_exec, create_subprocess_shell, wait_for

from pyleaves import Leaves
from pyrogram.parser import Parser
from pyrogram.utils import get_channel_id
from pyrogram.types import (
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaDocument,
    InputMediaAudio,
    Voice,
)

from helpers.files import (
    fileSizeLimit,
    cleanup_download
)

from helpers.msg import (
    get_parsed_msg
)

# Try to import PIL for thumbnail processing (optional)
try:
    from PIL import Image as PILImage
    PIL_AVAILABLE = True
except ImportError:
    PILImage = None
    PIL_AVAILABLE = False
    LOGGER(__name__).info("PIL not available - thumbnails will be skipped for better RAM efficiency")

async def process_thumbnail(thumb_path, max_size_kb=200):
    """
    Process thumbnail to meet Telegram requirements (optional - requires PIL):
    - JPEG format
    - <= 200 KB
    - Max 320px width/height
    
    Returns False if PIL is not available or processing fails.
    """
    if not PIL_AVAILABLE or PILImage is None:
        return False
    
    try:
        with PILImage.open(thumb_path) as img:
            # Convert to RGB (remove alpha channel if present)
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Resize to fit within 320x320 while maintaining aspect ratio
            img.thumbnail((320, 320), PILImage.Resampling.LANCZOS)
            
            # Save with compression, iteratively reduce quality if needed
            quality = 95
            while quality > 10:
                img.save(thumb_path, 'JPEG', quality=quality, optimize=True)
                
                # Check file size
                file_size_kb = os.path.getsize(thumb_path) / 1024
                if file_size_kb <= max_size_kb:
                    return True
                
                quality -= 10
            
            # If still too large after minimum quality, return False
            file_size_kb = os.path.getsize(thumb_path) / 1024
            if file_size_kb > max_size_kb:
                LOGGER(__name__).warning(f"Thumbnail still {file_size_kb:.2f} KB after compression")
                return False
            
            return True
    except Exception as e:
        LOGGER(__name__).error(f"Error processing thumbnail: {e}")
        return False

# Simplified progress bar template (reduced RAM usage)
PROGRESS_BAR = "{percentage:.0f}% | {speed}/s"

async def cmd_exec(cmd, shell=False):
    if shell:
        proc = await create_subprocess_shell(cmd, stdout=PIPE, stderr=PIPE)
    else:
        proc = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
    stdout, stderr = await proc.communicate()
    try:
        stdout = stdout.decode().strip()
    except:
        stdout = "Unable to decode the response!"
    try:
        stderr = stderr.decode().strip()
    except:
        stderr = "Unable to decode the error!"
    return stdout, stderr, proc.returncode


async def get_media_info(path):
    try:
        result = await cmd_exec([
            "ffprobe", "-hide_banner", "-loglevel", "error",
            "-print_format", "json", "-show_format", "-show_streams", path,
        ])
    except Exception as e:
        print(f"Get Media Info: {e}. Mostly File not found! - File: {path}")
        return 0, None, None
    
    if result[0] and result[2] == 0:
        try:
            import json
            data = json.loads(result[0])
        except json.JSONDecodeError as e:
            LOGGER(__name__).error(f"Failed to parse ffprobe JSON: {e}")
            return 0, None, None
        
        duration = 0
        artist = None
        title = None
        
        # Try to get duration from format first
        format_info = data.get("format", {})
        if format_info:
            try:
                duration_str = format_info.get("duration", "0")
                if duration_str and duration_str != "N/A":
                    duration = round(float(duration_str))
            except (ValueError, TypeError):
                pass
            
            # Get tags from format
            tags = format_info.get("tags", {})
            artist = tags.get("artist") or tags.get("ARTIST") or tags.get("Artist")
            title = tags.get("title") or tags.get("TITLE") or tags.get("Title")
        
        # If format duration is 0 or missing, try to get from video stream
        if duration == 0:
            streams = data.get("streams", [])
            for stream in streams:
                if stream.get("codec_type") == "video":
                    try:
                        stream_duration = stream.get("duration")
                        if stream_duration and stream_duration != "N/A":
                            duration = round(float(stream_duration))
                            LOGGER(__name__).info(f"Got duration from video stream: {duration}s")
                            break
                    except (ValueError, TypeError):
                        continue
        
        return duration, artist, title
    return 0, None, None


async def get_video_thumbnail(video_file, duration):
    output = os.path.join("Assets", "video_thumb.jpg")
    if duration is None:
        duration = (await get_media_info(video_file))[0]
    if not duration:
        duration = 3
    duration //= 2
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-ss", str(duration), "-i", video_file,
        "-vf", "thumbnail", "-q:v", "1", "-frames:v", "1",
        "-threads", str((os.cpu_count() or 4) // 2), output,
    ]
    try:
        _, err, code = await wait_for(cmd_exec(cmd), timeout=60)
        if code != 0 or not os.path.exists(output):
            return None
    except:
        return None
    return output


# Safe progress wrapper to handle deleted messages
async def safe_progress_callback(current, total, *args):
    """
    Wrapper around Pyleaves progress that catches MessageIdInvalid errors
    to prevent duplicate messages when progress messages are deleted
    """
    try:
        await Leaves.progress_for_pyrogram(current, total, *args)
    except Exception as e:
        error_str = str(e)
        # Silently ignore errors related to deleted or invalid messages
        if any(err in error_str.lower() for err in ['message_id_invalid', 'message not found', 'message to edit not found', 'message can\'t be edited']):
            LOGGER(__name__).debug(f"Progress message was deleted or invalid, ignoring: {e}")
        else:
            # Log other errors but don't raise to avoid interrupting downloads
            LOGGER(__name__).warning(f"Progress callback error: {e}")


async def send_to_dump_channel(bot, media_path, media_type, caption, user_id, thumb=None, duration=None):
    """
    Send media to dump channel for monitoring (if configured).
    This runs silently in the background and won't affect user downloads.
    
    Args:
        bot: Pyrogram Client instance
        media_path: Path to the media file
        media_type: Type of media (photo, video, audio, document)
        caption: Original caption
        user_id: User ID who downloaded this
        thumb: Optional thumbnail path (for videos)
        duration: Optional duration (for videos/audio)
    """
    from config import PyroConf
    
    # Only send if dump channel is configured
    if not PyroConf.DUMP_CHANNEL_ID:
        return
    
    try:
        # Add user info to caption
        dump_caption = f"👤 User ID: `{user_id}`\n"
        if caption:
            dump_caption += f"\n📝 Original Caption:\n{caption[:800]}"  # Limit caption length
        
        # Convert channel ID to integer format
        channel_id = int(PyroConf.DUMP_CHANNEL_ID)
        
        # Send based on media type
        if media_type == "photo":
            await bot.send_photo(
                chat_id=channel_id,
                photo=media_path,
                caption=dump_caption
            )
        elif media_type == "video":
            kwargs = {"caption": dump_caption}
            if thumb and thumb != "none":
                kwargs["thumb"] = thumb
            if duration and duration > 0:
                kwargs["duration"] = duration
            await bot.send_video(
                chat_id=channel_id,
                video=media_path,
                **kwargs
            )
        elif media_type == "audio":
            kwargs = {"caption": dump_caption}
            if duration and duration > 0:
                kwargs["duration"] = duration
            await bot.send_audio(
                chat_id=channel_id,
                audio=media_path,
                **kwargs
            )
        elif media_type == "document":
            await bot.send_document(
                chat_id=channel_id,
                document=media_path,
                caption=dump_caption
            )
        
        LOGGER(__name__).info(f"Sent {media_type} to dump channel for user {user_id}")
    except Exception as e:
        # Silently log errors - don't interrupt user's download
        LOGGER(__name__).warning(f"Failed to send to dump channel: {e}")

# Generate progress bar for downloading/uploading
def progressArgs(action: str, progress_message, start_time):
    return (action, progress_message, start_time, PROGRESS_BAR, "▓", "░")


async def send_media(
    bot, message, media_path, media_type, caption, progress_message, start_time, user_id=None
):
    file_size = os.path.getsize(media_path)

    if not await fileSizeLimit(file_size, message, "upload"):
        return

    progress_args = progressArgs("📥 Uploading Progress", progress_message, start_time)
    LOGGER(__name__).info(f"Uploading media: {media_path} ({media_type})")

    if media_type == "photo":
        await message.reply_photo(
            media_path,
            caption=caption or "",
            progress=safe_progress_callback,
            progress_args=progress_args,
        )
        # Send to dump channel if configured
        if user_id:
            await send_to_dump_channel(bot, media_path, media_type, caption, user_id)
    elif media_type == "video":
        # Check for custom thumbnail first
        thumb = None
        custom_thumb_path = None
        fallback_thumb = None
        
        if user_id:
            from database import db
            custom_thumb_file_id = db.get_custom_thumbnail(user_id)
            if custom_thumb_file_id:
                try:
                    # Use unique temp path to avoid race conditions
                    import time as time_module
                    timestamp = int(time_module.time() * 1000)
                    os.makedirs("Assets/thumbs", exist_ok=True)
                    custom_thumb_path = f"Assets/thumbs/user_{user_id}_{timestamp}.jpg"
                    
                    # Download the thumbnail from Telegram
                    await bot.download_media(custom_thumb_file_id, file_name=custom_thumb_path)
                    
                    # Process thumbnail to meet Telegram requirements
                    if await process_thumbnail(custom_thumb_path):
                        thumb = custom_thumb_path
                        LOGGER(__name__).info(f"Using custom thumbnail for user {user_id}")
                    else:
                        LOGGER(__name__).warning(f"Failed to process custom thumbnail for user {user_id}, will try fallback")
                        thumb = None
                except Exception as e:
                    LOGGER(__name__).error(f"Failed to download custom thumbnail for user {user_id}: {e}")
                    thumb = None
        
        # Get video duration
        duration = (await get_media_info(media_path))[0]
        
        # If no custom thumbnail, prepare unique fallback thumbnail
        if not thumb:
            import time as time_module
            timestamp = int(time_module.time() * 1000)
            os.makedirs("Assets/thumbs", exist_ok=True)
            fallback_thumb = f"Assets/thumbs/fb_{user_id or 0}_{timestamp}.jpg"
            
            # Extract thumbnail from video to unique path
            cmd = [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-ss", str(duration // 2 if duration else 3), "-i", media_path,
                "-vf", "thumbnail", "-q:v", "1", "-frames:v", "1",
                "-threads", str((os.cpu_count() or 4) // 2), fallback_thumb,
            ]
            try:
                _, err, code = await wait_for(cmd_exec(cmd), timeout=60)
                if code == 0 and os.path.exists(fallback_thumb):
                    thumb = fallback_thumb
                else:
                    thumb = None
            except:
                thumb = None
        
        # Get video dimensions
        if thumb and thumb != "none" and os.path.exists(str(thumb)) and PIL_AVAILABLE and PILImage:
            try:
                with PILImage.open(thumb) as img:
                    width, height = img.size
            except:
                width = 480
                height = 320
        else:
            width = 480
            height = 320

        if thumb == "none":
            thumb = None

        # Try uploading with thumbnail, fallback on error
        # Only include duration if > 0, otherwise let Telegram compute it
        video_kwargs = {
            "width": width,
            "height": height,
            "thumb": thumb,
            "caption": caption or "",
            "progress": safe_progress_callback,
            "progress_args": progress_args,
        }
        if duration > 0:
            video_kwargs["duration"] = duration
        
        sent_successfully = False
        try:
            await message.reply_video(media_path, **video_kwargs)
            sent_successfully = True
        except Exception as e:
            # If thumbnail causes error, try with fallback or no thumb
            LOGGER(__name__).error(f"Upload failed with thumbnail: {e}")
            
            # If custom thumbnail was used, generate fallback now
            if custom_thumb_path and not fallback_thumb:
                LOGGER(__name__).info("Custom thumbnail failed, generating fallback thumbnail")
                try:
                    import time as time_module
                    timestamp = int(time_module.time() * 1000)
                    fallback_thumb = f"Assets/thumbs/fb_{user_id or 0}_{timestamp}.jpg"
                    
                    cmd = [
                        "ffmpeg", "-hide_banner", "-loglevel", "error",
                        "-ss", str(duration // 2 if duration else 3), "-i", media_path,
                        "-vf", "thumbnail", "-q:v", "1", "-frames:v", "1",
                        "-threads", str((os.cpu_count() or 4) // 2), fallback_thumb,
                    ]
                    _, err, code = await wait_for(cmd_exec(cmd), timeout=60)
                    if code != 0 or not os.path.exists(fallback_thumb):
                        fallback_thumb = None
                except:
                    fallback_thumb = None
            
            # Try with fallback thumbnail
            if fallback_thumb:
                LOGGER(__name__).info("Retrying with auto-extracted thumbnail")
                try:
                    video_kwargs["thumb"] = fallback_thumb
                    await message.reply_video(media_path, **video_kwargs)
                    sent_successfully = True
                except Exception as e2:
                    LOGGER(__name__).error(f"Upload failed with fallback: {e2}, trying without thumbnail")
                    video_kwargs["thumb"] = None
                    await message.reply_video(media_path, **video_kwargs)
                    sent_successfully = True
            else:
                LOGGER(__name__).info("Retrying without thumbnail")
                video_kwargs["thumb"] = None
                await message.reply_video(media_path, **video_kwargs)
                sent_successfully = True
        
        # Send to dump channel if upload was successful
        if sent_successfully and user_id:
            # Use the final thumbnail that worked (or None)
            final_thumb = video_kwargs.get("thumb")
            await send_to_dump_channel(bot, media_path, media_type, caption, user_id, thumb=final_thumb, duration=duration)
        
        # Clean up thumbnails after upload
        if custom_thumb_path and os.path.exists(custom_thumb_path):
            try:
                os.remove(custom_thumb_path)
            except:
                pass
        if fallback_thumb and os.path.exists(fallback_thumb):
            try:
                os.remove(fallback_thumb)
            except:
                pass
    elif media_type == "audio":
        duration, artist, title = await get_media_info(media_path)
        await message.reply_audio(
            media_path,
            duration=duration,
            performer=artist,
            title=title,
            caption=caption or "",
            progress=safe_progress_callback,
            progress_args=progress_args,
        )
        # Send to dump channel if configured
        if user_id:
            await send_to_dump_channel(bot, media_path, media_type, caption, user_id, duration=duration)
    elif media_type == "document":
        await message.reply_document(
            media_path,
            caption=caption or "",
            progress=safe_progress_callback,
            progress_args=progress_args,
        )
        # Send to dump channel if configured
        if user_id:
            await send_to_dump_channel(bot, media_path, media_type, caption, user_id)


async def processMediaGroup(chat_message, bot, message, user_id=None):
    """Process and download a media group (multiple files in one post)
    
    Args:
        chat_message: The Telegram message containing the media group
        bot: Bot client
        message: User's message
        user_id: User ID for dump channel tracking
        
    Returns:
        int: Number of files successfully downloaded and sent (0 if failed)
    """
    media_group_messages = await chat_message.get_media_group()
    valid_media = []
    temp_paths = []
    invalid_paths = []

    start_time = time()
    progress_message = await message.reply("📥 Downloading media group...")
    LOGGER(__name__).info(
        f"Downloading media group with {len(media_group_messages)} items..."
    )

    for msg in media_group_messages:
        if msg.photo or msg.video or msg.document or msg.audio:
            try:
                media_path = await msg.download(
                    progress=safe_progress_callback,
                    progress_args=progressArgs(
                        "📥 Downloading Progress", progress_message, start_time
                    ),
                )
                temp_paths.append(media_path)

                if msg.photo:
                    valid_media.append(
                        InputMediaPhoto(
                            media=media_path,
                            caption=await get_parsed_msg(
                                msg.caption or "", msg.caption_entities
                            ),
                        )
                    )
                elif msg.video:
                    duration = (await get_media_info(media_path))[0]
                    valid_media.append(
                        InputMediaVideo(
                            media=media_path,
                            duration=duration,
                            caption=await get_parsed_msg(
                                msg.caption or "", msg.caption_entities
                            ),
                        )
                    )
                elif msg.document:
                    valid_media.append(
                        InputMediaDocument(
                            media=media_path,
                            caption=await get_parsed_msg(
                                msg.caption or "", msg.caption_entities
                            ),
                        )
                    )
                elif msg.audio:
                    valid_media.append(
                        InputMediaAudio(
                            media=media_path,
                            caption=await get_parsed_msg(
                                msg.caption or "", msg.caption_entities
                            ),
                        )
                    )

            except Exception as e:
                LOGGER(__name__).info(f"Error downloading media: {e}")
                media_path = None
                continue

    LOGGER(__name__).info(f"Valid media count: {len(valid_media)}")

    try:
        if valid_media:
            try:
                await bot.send_media_group(chat_id=message.chat.id, media=valid_media)
                
                # Send to dump channel if configured
                if user_id:
                    from config import PyroConf
                    if PyroConf.DUMP_CHANNEL_ID:
                        try:
                            # Prepare media group for dump channel with user info
                            dump_media = []
                            for idx, media in enumerate(valid_media):
                                dump_caption = f"👤 User ID: `{user_id}`"
                                if media.caption:
                                    dump_caption += f"\n\n📝 Original Caption:\n{media.caption[:700]}"
                                
                                if isinstance(media, InputMediaPhoto):
                                    dump_media.append(InputMediaPhoto(media=media.media, caption=dump_caption if idx == 0 else ""))
                                elif isinstance(media, InputMediaVideo):
                                    dump_media.append(InputMediaVideo(media=media.media, caption=dump_caption if idx == 0 else ""))
                                elif isinstance(media, InputMediaDocument):
                                    dump_media.append(InputMediaDocument(media=media.media, caption=dump_caption if idx == 0 else ""))
                                elif isinstance(media, InputMediaAudio):
                                    dump_media.append(InputMediaAudio(media=media.media, caption=dump_caption if idx == 0 else ""))
                            
                            await bot.send_media_group(chat_id=PyroConf.DUMP_CHANNEL_ID, media=dump_media)
                            LOGGER(__name__).info(f"Sent media group to dump channel for user {user_id}")
                        except Exception as e:
                            LOGGER(__name__).warning(f"Failed to send media group to dump channel: {e}")
                
                await progress_message.delete()
            except Exception:
                await message.reply(
                    "**❌ Failed to send media group, trying individual uploads**"
                )
                for media in valid_media:
                    try:
                        if isinstance(media, InputMediaPhoto):
                            await bot.send_photo(
                                chat_id=message.chat.id,
                                photo=media.media,
                                caption=media.caption,
                            )
                        elif isinstance(media, InputMediaVideo):
                            await bot.send_video(
                                chat_id=message.chat.id,
                                video=media.media,
                                duration=media.duration,
                                caption=media.caption,
                            )
                        elif isinstance(media, InputMediaDocument):
                            await bot.send_document(
                                chat_id=message.chat.id,
                                document=media.media,
                                caption=media.caption,
                            )
                        elif isinstance(media, InputMediaAudio):
                            await bot.send_audio(
                                chat_id=message.chat.id,
                                audio=media.media,
                                caption=media.caption,
                            )
                        elif isinstance(media, Voice):
                            await bot.send_voice(
                                chat_id=message.chat.id,
                                voice=media.media,
                                caption=media.caption,
                            )
                    except Exception as individual_e:
                        await message.reply(
                            f"Failed to upload individual media: {individual_e}"
                        )

                await progress_message.delete()

            return len(valid_media)  # Return count of successfully sent files

        await progress_message.delete()
        await message.reply("❌ No valid media found in the media group.")
        return 0  # Return 0 if no files were sent
    finally:
        # CRITICAL: Always cleanup all downloaded files, even if errors occur during upload
        for path in temp_paths + invalid_paths:
            cleanup_download(path)
