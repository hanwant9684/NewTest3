# Restricted Content Downloader Telegram Bot

## Overview
This project is an advanced Telegram bot designed to download restricted content (photos, videos, audio files, documents) from Telegram private chats or channels. It features user authentication, database management, admin controls, and ad monetization. The bot offers both free (ad-supported) and premium ($1/month) access tiers, providing a robust solution for accessing and managing Telegram media efficiently.

## User Preferences
I prefer the bot to be stateful and always running, deployed on a VM. I prioritize fast downloads and uploads, utilizing uvloop and parallel transfers. The development process should focus on iterative improvements, ensuring stability and performance. I expect the bot to handle user authentication securely and manage user data efficiently using MongoDB. I want to monetize the bot through Monetag ads, offering users free premium access in exchange for ad views. The bot should also support various payment methods for premium subscriptions.

## System Architecture

### UI/UX Decisions
The bot interacts with users primarily via Telegram commands. Ad verification uses a 2-page auto-advancing web interface with 15-second timers per page (30 seconds total). Smartlink ads open in new browser tabs. Status messages are auto-deleting for a cleaner chat experience. The UI for commands like `/stats` and `/adminstats` uses modern emoji-based layouts for clarity.

### Technical Implementations
- **Language**: Python 3.11 with `uvloop` for asynchronous operations.
- **Concurrency**: Adaptive resource allocation based on deployment environment (e.g., 1 worker, 2 concurrent transmissions for 512MB RAM environments like Render/Replit).
- **Caching**: LRU cache (500 items, 180s TTL) for frequently accessed data (admin status, ban status, user types, sessions) to reduce database queries.
- **Database Optimization**: MongoDB connection pooling (`maxPoolSize=10`) with optimized server selection and idle timeouts.
- **Cryptographic Operations**: `TgCrypto` for enhanced performance.
- **Deployment**: Designed for VM deployment, with auto-detection for platforms like Railway.app, Render, and Replit, using a Flask wrapper for web server deployment.
- **Monetization**: Iframe-free ad integration using HTML/CSS banner ads and Adsterra smartlinks.
- **Download Queue**: Supports 20 concurrent downloads and a 100-item waiting queue, prioritizing premium users.
- **User Authentication**: Phone number login with OTP verification and 2FA, creating personal Telegram sessions for each user.
- **User Management**: Free, Premium, and Admin tiers with distinct access, daily download limits, and subscription management.
- **Security**: Encrypted session storage, individual user sessions, admin-only command decorators, ban system, daily rate limiting, and atomic session verification.
- **Download Capabilities**: Supports photos, videos, audio, and documents from single posts or media groups, with real-time progress bars.
- **Content Copying**: Ability to copy text messages or captions.
- **Batch Downloads**: Premium-only feature.
- **Ad-Based Premium**: Users can earn 1 free download by completing a 45-second ad verification flow (1 download per ad session).
- **Paid Premium**: Monthly subscription ($1) via various payment methods for unlimited downloads.
- **Admin Controls**: Commands for user management, bot statistics, broadcasting, logging, and canceling downloads.
- **Dump Channel**: Optional feature to forward all downloaded media to a specified channel for monitoring.

### System Design Choices
- **Modular Architecture**: Core functionalities are separated into modules (e.g., `phone_auth.py`, `access_control.py`, `ad_monetization.py`, `queue_manager.py`).
- **Database Schema**: MongoDB is exclusively used for all persistence (user profiles, admin privileges, usage, broadcast history, ad sessions, verification codes).
- **Error Handling**: Race conditions prevented via atomic session verification. Progress bar errors (e.g., `MessageIdInvalid`) are silently ignored to prevent duplicate messages.
- **Progress Display**: `Pyleaves` library provides rich, real-time progress bars for file operations.
- **Stats Monitoring**: Tracks bot memory/CPU usage, active downloads, queue size, user counts, and daily download statistics.

## External Dependencies
- **Database**: MongoDB (exclusive use for all persistent data)
- **Telegram API Framework**: Pyrofork
- **Cryptography**: TgCrypto
- **Progress Bars**: Pyleaves
- **Image Processing**: Pillow
- **Asynchronous Loop**: uvloop
- **Web Framework**: Flask (for web server wrapper and ad verification pages)
- **Environment Variables**: python-dotenv
- **System Utilities**: psutil (for bot process monitoring)
- **Monetization Platform**: Monetag
- **Payment Gateways**: PayPal, UPI, Amazon Pay/Gift Card, Cryptocurrency (USDT/BTC/ETH)

## Recent Changes

### Download System Overhaul (October 23, 2025)
Implemented a new "1 download per ad" system to increase ad engagement and revenue:

**Changes Made:**
- **Ad Downloads**: Changed from 5 downloads per ad view to 1 download per ad view (updated PREMIUM_DOWNLOADS constant)
- **Daily Free Limit**: Reduced from 5 downloads/day to 1 download/day for free users
- **Independent Ad Credits**: Ad downloads now completely bypass daily limits - they're tracked separately and don't fall back to daily quota
- **Inline Buttons**: When users exhaust their daily free download, they now see inline keyboard buttons to:
  - Watch ad and get 1 more download
  - Upgrade to premium for unlimited downloads
- **Messaging Updates**: All user-facing messages updated to reflect "1 download" system:
  - /start command
  - /help command
  - Download limit notifications
  - Ad verification prompts
  - Success messages

**Technical Details:**
- Modified `increment_usage()` in database.py to make ad downloads independent of daily quota
- Added callback handlers for "watch_ad_now" and "upgrade_premium" buttons
- Updated `check_download_limit` decorator in access_control.py to show inline buttons
- Updated all references to "5 downloads" throughout the codebase

**User Flow:**
1. User gets 1 free download per day (daily quota)
2. When exhausted, user sees button to watch ad or upgrade
3. User clicks "Watch Ad" button → completes 45-second ad flow
4. User gets verification code → sends /verifypremium code
5. Bot adds 1 ad download to user's account (independent of daily limit)
6. User can download 1 file using ad download
7. Process repeatable - user can watch ads multiple times per day

**Benefits:**
- Increased ad views per download (5x increase)
- Better monetization potential
- Clearer value proposition for premium upgrades
- More predictable download costs for free users
- Simplified tracking and accounting

**Status:** ✅ Implemented and tested, architect-reviewed and approved