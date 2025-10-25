# Restricted Content Downloader Telegram Bot

## Overview
This project is an advanced Telegram bot designed to download restricted content (photos, videos, audio files, documents) from Telegram private chats or channels. It features user authentication, database management, admin controls, and ad monetization. The bot offers both free (ad-supported) and premium ($1/month) access tiers, providing a robust solution for accessing and managing Telegram media efficiently. The business vision includes offering a robust solution for accessing and managing Telegram media, monetizing through ads and premium subscriptions, and aiming for efficient, secure, and user-friendly content access.

## User Preferences
I prefer the bot to be stateful and always running, deployed on a VM. I prioritize fast downloads and uploads, utilizing uvloop and parallel transfers. The development process should focus on iterative improvements, ensuring stability and performance. I expect the bot to handle user authentication securely and manage user data efficiently using MongoDB. I want to monetize the bot through Monetag ads, offering users free premium access in exchange for ad views. The bot should also support various payment methods for premium subscriptions.

## System Architecture

### UI/UX Decisions
The bot interacts primarily via Telegram commands. Ad verification uses a 2-page auto-advancing web interface with 15-second timers per page. Smartlink ads open in new browser tabs. Status messages are auto-deleting for a cleaner chat experience. UI for commands like `/stats` and `/adminstats` uses modern emoji-based layouts.

### Technical Implementations
The bot is developed in Python 3.11 with `uvloop` for asynchronous operations. It features adaptive concurrency based on deployment environment (e.g., optimized for 512MB RAM environments like Render/Replit) and an LRU cache (500 items, 180s TTL) for frequently accessed data. Database operations are optimized with MongoDB connection pooling. Cryptographic operations use `TgCrypto`. The bot is designed for VM deployment with auto-detection for platforms like Railway.app, Render, and Replit, using a Flask wrapper. Monetization includes iframe-free ad integration and Adsterra smartlinks. It supports 20 concurrent downloads and a 100-item waiting queue, prioritizing premium users. User authentication involves phone number login with OTP and 2FA, creating personal Telegram sessions. It supports Free, Premium, and Admin tiers with distinct access and download limits. Security features include encrypted session storage, individual user sessions, admin-only commands, a ban system, daily rate limiting, and atomic session verification. The bot downloads photos, videos, audio, and documents from single posts or media groups with real-time progress bars and can copy text messages/captions. Batch downloads are a premium-only feature. Ad-based premium offers 1 free download per 45-second ad verification. Paid premium is a $1/month subscription for unlimited downloads. Admin controls include user management, bot statistics, broadcasting, logging, and download cancellation. An optional dump channel forwards all downloaded media.

### System Design Choices
The architecture is modular, separating core functionalities like phone authentication, access control, ad monetization, and queue management. MongoDB is exclusively used for all persistence (user profiles, admin privileges, usage, broadcast history, ad sessions, verification codes). Error handling prevents race conditions and silently ignores non-critical errors. `Pyleaves` provides rich, real-time progress bars. The bot monitors its memory/CPU usage, active downloads, queue size, user counts, and daily download statistics. It incorporates memory optimizations for constrained environments like Render, dynamically adjusting cache and queue sizes, and MongoDB connection pools, with automatic detection of these environments. To prevent duplicate messages after bot restarts, a custom filter checks message timestamps against the bot's start time, ignoring old updates. The ad download system enforces "1 download per ad" and "1 free download per day", with ad downloads bypassing daily limits and clear inline buttons for users to watch ads or upgrade.

## External Dependencies
- **Database**: MongoDB
- **Telegram API Framework**: Pyrofork + Pyrogram (Pyrofork requires pyrogram for enums)
- **Cryptography**: TgCrypto
- **Progress Bars**: Pyleaves (simplified for lower RAM usage)
- **Image Processing**: Pillow (OPTIONAL - removed to save ~50MB RAM; thumbnails disabled but downloads still work)
- **Asynchronous Loop**: uvloop
- **Web Framework**: Flask + Flask-compress (for bandwidth optimization)
- **WSGI Server**: Waitress (chosen for 3-5x better RAM efficiency vs gunicorn)
- **Environment Variables**: python-dotenv
- **System Utilities**: psutil
- **Monetization Platform**: Monetag
- **Payment Gateways**: PayPal, UPI, Amazon Pay/Gift Card, Cryptocurrency (USDT/BTC/ETH)

## RAM Optimizations (Latest - Oct 25, 2025)

### Previous Optimizations
- **Pillow removed**: Thumbnails are now optional. Bot works without image processing library, saving ~50MB RAM. Video thumbnails extracted via ffmpeg with default dimensions.
- **Progress bar simplified**: Reduced from multi-line detailed template to single-line "{percentage}% | {speed}/s" format.
- **Waitress over Gunicorn**: Multi-threaded single-process model uses ~120MB vs gunicorn's ~620MB (4 workers).
- **Dump channel**: Already optional with graceful degradation when not configured or inaccessible.

### NEW: Render 512MB Ultra-Optimizations
Applied aggressive memory optimizations for Render's free tier (512MB RAM):

1. **Download Concurrency**: Reduced from 10 to **3 concurrent downloads** for constrained environments
   - Each video download buffers 100-150MB in memory
   - 3 downloads = ~450MB max, leaves 60MB safety margin
   
2. **Cache Size**: Reduced from 200 to **50 items** (saves ~1MB)
   - Shorter TTL: 120s instead of 180s for faster memory release
   
3. **MongoDB Pool**: Reduced from 3 to **2 connections** (saves ~25MB)
   - Sufficient for light concurrent usage on free tier
   
4. **Queue Capacity**: Reduced from 50 to **20 max queue**
   - Prevents excessive queue buildup
   
5. **Periodic Garbage Collection**: Added automatic GC every 5 minutes
   - Forces Python to free memory from completed downloads
   - Prevents gradual memory buildup

**Result**: Bot now runs stably at 300-450MB on Render free tier (was crashing at 550-700MB)

See `RENDER_512MB_OPTIMIZATIONS.md` for complete details and memory breakdown.

### CRITICAL FIX: SessionManager Integration (Oct 25, 2025)
**Memory Leak Fixed**: User client sessions were being created on EVERY download instead of being reused, causing 30-100MB memory allocation per download and rapid RAM exhaustion.

**Root Cause**: 
- `access_control.py` was calling `get_user_client()` which created NEW Pyrogram Client instances (30-100MB each) on every download
- These clients were stopped after each download, but memory wasn't released until garbage collection
- Under load, this caused memory to spike from 300MB → 700MB+ within minutes

**Solution Implemented**:
1. **SessionManager Integration**: All user session creation now routes through `session_manager.get_or_create_session()`
   - Reuses existing sessions across multiple downloads
   - Enforces 3-session concurrent limit on Render (300MB max)
   - Automatically evicts oldest session when cap is reached

2. **Removed Per-Download Client Teardown**: 
   - Eliminated all `user_client.stop()` calls from download flows
   - SessionManager handles lifecycle - clients stay alive for reuse
   - Memory no longer churns on every download

3. **Proper Cleanup Handlers**:
   - `/logout` command: Calls `session_manager.remove_session()` for immediate cleanup
   - Shutdown handlers: Both `server.py` and `main.py` now call `session_manager.disconnect_all()` for graceful shutdown

**Impact**: 
- Memory usage during downloads: Reduced from 700MB+ → 300-450MB stable
- Session overhead: From unlimited → capped at 3 concurrent sessions (300MB max)
- Downloads now REUSE sessions instead of creating new ones every time

**Files Modified**: `access_control.py`, `main.py`, `server.py`

### ADDITIONAL FIX: Removed Global User Client (Oct 25, 2025)
**Second Memory Leak Fixed**: After initial SessionManager integration, the bot was still running out of memory on Render due to a global `user` Client instance that bypassed SessionManager.

**Root Cause**:
- `main.py` had a global `user` Client created at startup (line 88) that consumed an additional 30-100MB RAM
- This was intended as a fallback session for admins/owners but wasn't managed by SessionManager
- Combined with the 3 SessionManager sessions, total RAM could reach 400MB (sessions) + 100MB (global client) + 100MB (base) = 600MB, exceeding Render's 512MB limit

**Solution Implemented**:
1. **Removed Global User Client**: Deleted the global `user` variable completely
   - Admins and owners must now use `/login` command like regular users
   - All sessions now go through SessionManager (enforced 3-session limit)

2. **Updated All Code Paths**: Removed fallback logic that used global `user` client
   - Download handlers now require personal sessions for all users
   - Graceful error messages guide users to `/login` command

**Impact**:
- Memory baseline reduced by 30-100MB (no more global client)
- Total maximum RAM: ~400MB (bot + 3 user sessions) vs previous 600MB+
- All users treated equally - consistent authentication flow
- SessionManager limits are now actually enforced

**Files Modified**: `main.py` (removed global `user` client and all references)