# Restricted Content Downloader Telegram Bot

## Overview
This project is an advanced Telegram bot designed to download restricted content (photos, videos, audio files, documents) from Telegram private chats or channels. It includes features like user authentication, database management, admin controls, and ad monetization, offering both free (ad-supported) and premium ($1/month) access tiers. The bot aims to provide a robust solution for accessing and managing Telegram media efficiently.

## User Preferences
I prefer the bot to be stateful and always running, deployed on a VM. I prioritize fast downloads and uploads, utilizing uvloop and parallel transfers. The development process should focus on iterative improvements, ensuring stability and performance. I expect the bot to handle user authentication securely and manage user data efficiently using MongoDB. I want to monetize the bot through Monetag ads, offering users free premium access in exchange for ad views. The bot should also support various payment methods for premium subscriptions.

## System Architecture

### UI/UX Decisions
The bot operates as a backend Telegram bot, primarily interacting with users via commands. Ad verification is handled through a web interface with a 2-page auto-advancing flow, featuring 15-second timers per page (30 seconds total) with no manual buttons required. Smartlink ads open directly in new browser tabs for proper ad rendering. Status messages are designed to be auto-deleting for a cleaner chat experience.

### Technical Implementations
- **Language**: Python 3.11
- **Asynchronous Operations**: `uvloop` for 2-4x faster async.
- **Concurrency**: Parallel file transfers (`max_concurrent_transmissions=8`) and optimized worker threads (`workers=8`).
- **Cryptographic Operations**: `TgCrypto` for faster performance.
- **Deployment**: Designed for VM deployment, with auto-detection for platforms like Railway.app, Render, Heroku, and Replit. It uses a Flask wrapper (`server.py`) for web server deployment and `railway.json` for Railway-specific configurations.
- **Monetization**: Iframe-free ad integration using HTML/CSS banner ads and Adsterra smartlinks that open directly in new tabs for proper ad rendering.
- **Download Queue**: A robust system supporting 20 concurrent downloads and a 100-item waiting queue, with priority for premium users.
- **User Authentication**: Phone number login with OTP verification and 2FA support, creating personal Telegram sessions for each user.
- **User Management**: Free, Premium, and Admin user tiers with distinct access levels, daily download limits, and subscription management.
- **Security**: Encrypted session storage, individual user sessions, admin-only command decorators, ban system, daily rate limiting, and atomic session verification.

### Feature Specifications
- **Download Capabilities**: Supports downloading photos, videos, audio, and documents from single posts or media groups, with real-time progress bars.
- **Content Copying**: Ability to copy text messages or captions from Telegram posts.
- **Batch Downloads**: Premium-only feature for downloading multiple links.
- **Ad-Based Premium**: Users can watch a 2-page auto-advancing ad verification flow (15 seconds per page, 30 seconds total) with 4 banner ads and 2 Adsterra smartlinks to earn 5 free downloads.
- **Paid Premium**: Monthly subscription ($1) offering unlimited downloads via PayPal, UPI, Amazon Pay/Gift Card, or cryptocurrency.
- **Admin Controls**: Commands for user management (add/remove admin, set/remove premium, ban/unban, user info), bot statistics, broadcasting messages, logging, and canceling all pending downloads.

### System Design Choices
- **Modular Architecture**: Core functionalities are separated into modules (e.g., `phone_auth.py`, `access_control.py`, `ad_monetization.py`, `queue_manager.py`).
- **Database Schema**: MongoDB (ONLY) is used to store user profiles, admin privileges, daily usage, broadcast history, ad sessions, and verification codes. No local SQLite or file-based databases are used.
- **Error Handling**: Race conditions are prevented through atomic session verification.
- **Progress Display**: Pyleaves library provides rich, real-time progress bars for all file operations with download/upload speeds and ETAs.
- **Stats Monitoring**: Bot-specific metrics (not server-level) are tracked: bot memory/CPU usage, active downloads, queue size, user counts, and daily download statistics.

## External Dependencies
- **Database**: MongoDB (ONLY - for user data, sessions, ad sessions, statistics, all persistence)
  - ⚠️ **Note**: The bot uses MongoDB exclusively. No SQLite or local database files are used.
- **Telegram API Framework**: Pyrofork
- **Cryptography**: TgCrypto
- **Progress Bars**: Pyleaves (for rich upload/download progress display in Telegram)
  - Used via `Leaves.progress_for_pyrogram` to show real-time progress with speed, ETA, and percentage
  - Integrated in all file download/upload operations
- **Image Processing**: Pillow
- **Asynchronous Loop**: uvloop
- **Web Framework**: Flask (for `server.py` wrapper and ad verification pages)
- **Environment Variables**: python-dotenv
- **System Utilities**: psutil (for bot process monitoring - memory, CPU usage)
- **Monetization Platform**: Monetag (for ad-based premium access)
- **Payment Gateways**: PayPal, UPI, Amazon Pay/Gift Card, Cryptocurrency (USDT/BTC/ETH)