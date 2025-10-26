# Restricted Content Downloader Telegram Bot

## Overview
This project is an advanced Telegram bot designed to download restricted content (photos, videos, audio files, documents) from Telegram private chats or channels. It features user authentication, database management, admin controls, and ad monetization. The bot offers both free (ad-supported) and premium ($1/month) access tiers, providing a robust solution for accessing and managing Telegram media efficiently. The business vision includes offering a robust solution for accessing and managing Telegram media, monetizing through ads and premium subscriptions, and aiming for efficient, secure, and user-friendly content access.

## User Preferences
I prefer the bot to be stateful and always running, deployed on a VM. I prioritize fast downloads and uploads, utilizing uvloop and parallel transfers. The development process should focus on iterative improvements, ensuring stability and performance. I expect the bot to handle user authentication securely and manage user data efficiently using MongoDB. I want to monetize the bot through Monetag ads, offering users free premium access in exchange for ad views. The bot should also support various payment methods for premium subscriptions.

## System Architecture

### UI/UX Decisions
The bot interacts primarily via Telegram commands. Ad verification uses droplink.co monetized URLs, redirecting users to a verification code page after viewing ads. Status messages are auto-deleting for a cleaner chat experience. UI for commands like `/stats` and `/adminstats` uses modern emoji-based layouts. Promotional videos are integrated into premium commands for an engaging user experience.

### Technical Implementations
The bot is developed in Python 3.11 with `uvloop` for asynchronous operations. It features adaptive concurrency (e.g., optimized for 512MB RAM environments) and an LRU cache (50 items, 120s TTL). Database operations are optimized with MongoDB connection pooling. Cryptographic operations use `TgCrypto`. The bot is designed for VM deployment with auto-detection for platforms like Railway.app, Render, and Replit, using a Flask wrapper. Monetization uses droplink.co URL shortener for CPM-based ad revenue. It supports 3 concurrent downloads and a 20-item waiting queue, prioritizing premium users. User authentication involves phone number login with OTP and 2FA, creating personal Telegram sessions. It supports Free, Premium, and Admin tiers with distinct access and download limits. Security features include encrypted session storage, individual user sessions, admin-only commands, a ban system, daily rate limiting, and atomic session verification. The bot downloads various media types from single posts or media groups with real-time progress bars and can copy text messages/captions. Batch downloads are a premium-only feature. Ad-based premium offers 1 free download per droplink ad view. Paid premium is a $1/month subscription for unlimited downloads. Admin controls include user management, bot statistics, broadcasting, logging, and download cancellation. An optional dump channel forwards all downloaded media. Memory optimizations include reduced download concurrency, cache size, MongoDB connection pool size, and queue capacity for constrained environments, along with periodic garbage collection. A `SessionManager` reuses user client sessions to prevent memory leaks.

### System Design Choices
The architecture is modular, separating core functionalities like phone authentication, access control, ad monetization, and queue management. MongoDB is exclusively used for all persistence. Error handling prevents race conditions and silently ignores non-critical errors. `Pyleaves` provides rich, real-time progress bars. The bot monitors its memory/CPU usage, active downloads, queue size, user counts, and daily download statistics. It incorporates memory optimizations for constrained environments, dynamically adjusting cache and queue sizes, and MongoDB connection pools, with automatic detection of these environments. A custom filter checks message timestamps against the bot's start time to prevent duplicate messages after bot restarts. The ad download system enforces "1 download per ad" and "1 free download per day", with ad downloads bypassing daily limits and clear inline buttons for users to watch ads or upgrade.

## External Dependencies
- **Database**: MongoDB
- **Telegram API Framework**: Pyrofork + Pyrogram
- **Cryptography**: TgCrypto
- **Progress Bars**: Pyleaves
- **Asynchronous Loop**: uvloop
- **Web Framework**: Flask + Flask-compress
- **WSGI Server**: Waitress
- **Environment Variables**: python-dotenv
- **System Utilities**: psutil
- **Monetization Platforms**: Droplink.co, GPLinks.com, ARLinks.in, UpShrink.com (rotating URL shorteners)
- **Payment Gateways**: PayPal, UPI, Amazon Pay/Gift Card, Cryptocurrency (USDT/BTC/ETH)

## Recent Changes

### Automatic Verification System (Oct 26, 2025)
**New Feature**: Implemented one-click automatic verification using Telegram deep links to improve user experience.

**Previous Flow**:
1. User completes ad session
2. Reaches verification page with code
3. Manually copies code
4. Types `/verifypremium <code>` in bot
5. Receives free downloads

**New Flow**:
1. User completes ad session
2. Reaches verification page with code
3. Clicks "Auto-Verify in Bot" button
4. Automatically opens bot and verifies
5. Instantly receives free downloads

**Implementation Details**:
1. **Telegram Deep Links**: Added button with format `https://t.me/<BOT_USERNAME>?start=verify_<CODE>` that automatically opens the bot with the verification code
2. **Start Command Handler**: Modified `/start` command in `main.py` to detect and process verification deep links (format: `/start verify_<CODE>`)
3. **HTML Template**: Updated `templates/verify_success.html` to show "Auto-Verify" button as primary option, with manual copy-paste as fallback
4. **Bot Username Config**: Added `BOT_USERNAME` environment variable to `config.py` for deep link generation
5. **Server Integration**: Updated `server.py` to pass bot username to verification template

**Benefits**:
- Eliminates manual copy-paste step
- Reduces user error from incorrect code entry
- Faster verification process (1 click vs multiple steps)
- Better mobile experience
- Maintains backward compatibility with manual verification

**Environment Variable Required**:
- `BOT_USERNAME` - Your bot's Telegram username (without @)

**Files Modified**:
- `main.py` - Added deep link verification handler in start command
- `config.py` - Added BOT_USERNAME configuration
- `server.py` - Pass bot_username to template rendering
- `templates/verify_success.html` - Added Auto-Verify button with Telegram deep link

### URL Shortener Rotation System (Oct 26, 2025)
**New Feature**: Implemented automatic rotation between 4 URL shortener services to maximize ad revenue and distribute traffic.

**Rotation Pattern** (resets daily):
- Downloads 1-5: Droplink.co
- Downloads 6-10: GPLinks.com
- Downloads 11-15: ARLinks.in
- Downloads 16-20: UpShrink.com
- Downloads 21+: Cycle repeats from Droplink

**Implementation Details**:
1. **Database Tracking**: New MongoDB collection `shortener_rotation` stores global rotation state with fields:
   - `current_index`: Current service index (0-3)
   - `downloads_in_cycle`: Download count for current service (0-4)
   - `date`: Current date for daily reset logic

2. **Service Integration**: Added API integration methods in `ad_monetization.py`:
   - `_shorten_with_droplink()` - Droplink.co API
   - `_shorten_with_gplinks()` - GPLinks.com API  
   - `_shorten_with_arlinks()` - ARLinks.in API
   - `_shorten_with_upshrink()` - UpShrink.com API

3. **Fallback Mechanism**: If any service fails (API error, timeout, invalid response), automatically falls back to Droplink.co

4. **Environment Variables Required**:
   - `DROPLINK_API_KEY` - Droplink.co API token
   - `GPLINKS_API_KEY` - GPLinks.com API token
   - `ARLINKS_API_KEY` - ARLinks.in API token
   - `UPSHRINK_API_KEY` - UpShrink.com API token

**Benefits**:
- Diversified ad revenue across multiple platforms
- Load balancing prevents service-specific rate limits
- Automatic daily reset ensures fair distribution
- Graceful degradation if any service is unavailable

**Files Modified**:
- `database.py` - Added `get_shortener_rotation_state()` and `increment_shortener_rotation()` methods
- `ad_monetization.py` - Added 3 new API integration methods, updated `generate_droplink_ad_link()` to use rotation
- `config.py` - Already supported multiple API keys via environment variables