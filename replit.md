# Restricted Content Downloader Telegram Bot

## Overview
This project is an advanced Telegram bot designed to download restricted content (photos, videos, audio files, documents) from Telegram private chats or channels. It includes features like user authentication, database management, admin controls, and ad monetization, offering both free (ad-supported) and premium ($1/month) access tiers. The bot aims to provide a robust solution for accessing and managing Telegram media efficiently.

## User Preferences
I prefer the bot to be stateful and always running, deployed on a VM. I prioritize fast downloads and uploads, utilizing uvloop and parallel transfers. The development process should focus on iterative improvements, ensuring stability and performance. I expect the bot to handle user authentication securely and manage user data efficiently using MongoDB. I want to monetize the bot through Monetag ads, offering users free premium access in exchange for ad views. The bot should also support various payment methods for premium subscriptions.

## System Architecture

### UI/UX Decisions
The bot operates as a backend Telegram bot, interacting with users via commands. Ad verification is handled through a web interface with a 2-page auto-advancing flow (30 seconds total) with no manual buttons. Smartlink ads open directly in new browser tabs. Status messages are auto-deleting for a cleaner chat experience. The UI for commands and admin dashboards is modernized with emoji-based layouts for readability.

### Technical Implementations
- **Language & Asynchronous Operations**: Python 3.11 with `uvloop` for faster async.
- **Concurrency**: Adaptive resource allocation based on platform (Render/Replit) with reduced workers and concurrent transmissions for constrained environments.
- **Caching Layer**: LRU cache (500 items, 180s TTL) reduces redundant database queries.
- **Database Optimization**: MongoDB connection pooling (`maxPoolSize=10`) with optimized server selection and idle timeouts.
- **Cryptographic Operations**: `TgCrypto` for faster performance.
- **Deployment**: Designed for VM deployment with auto-detection for platforms like Railway.app, Render, Heroku, and Replit, using a Flask wrapper for web server deployment.
- **Monetization**: Iframe-free ad integration using HTML/CSS banner ads and Adsterra smartlinks. Ad-based premium offers 5 free downloads after watching a 30-second ad flow. Paid premium is a $1/month subscription.
- **Download Queue**: Supports 20 concurrent downloads and a 100-item waiting queue, prioritizing premium users.
- **User Authentication**: Phone number login with OTP verification and 2FA, creating personal Telegram sessions.
- **User Management**: Free, Premium, and Admin tiers with distinct access levels, daily download limits, and subscription management.
- **Security**: Encrypted session storage, individual user sessions, admin-only command decorators, ban system, daily rate limiting, and atomic session verification.
- **Download Capabilities**: Supports photos, videos, audio, and documents from single posts or media groups with real-time progress bars. Premium-only batch downloads.
- **Content Copying**: Ability to copy text messages or captions.
- **Admin Controls**: Commands for user management, bot statistics, broadcasting, logging, and canceling downloads.

### System Design Choices
- **Modular Architecture**: Core functionalities are separated into modules.
- **Database Schema**: MongoDB exclusively stores user profiles, admin privileges, daily usage, broadcast history, ad sessions, and verification codes. No local or file-based databases are used.
- **Error Handling**: Race conditions prevented via atomic session verification. Silent handling of `MessageIdInvalid` errors to prevent duplicate messages.
- **Progress Display**: Pyleaves library provides rich, real-time progress bars for file operations.
- **Stats Monitoring**: Tracks bot-specific metrics like memory/CPU usage, active downloads, queue size, user counts, and daily download statistics.
- **Resilience**: Comprehensive reconnection system with exponential backoff for Render network timeouts, ensuring bot recovery.

## External Dependencies
- **Database**: MongoDB (for all persistence)
- **Telegram API Framework**: Pyrofork
- **Cryptography**: TgCrypto
- **Progress Bars**: Pyleaves (for rich upload/download progress display)
- **Image Processing**: Pillow
- **Asynchronous Loop**: uvloop
- **Web Framework**: Flask (for `server.py` wrapper and ad verification pages)
- **Environment Variables**: python-dotenv
- **System Utilities**: psutil (for bot process monitoring)
- **Monetization Platform**: Monetag (for ad-based premium access)
- **Payment Gateways**: PayPal, UPI, Amazon Pay/Gift Card, Cryptocurrency (USDT/BTC/ETH)