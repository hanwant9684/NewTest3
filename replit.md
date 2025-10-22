# Restricted Content Downloader Telegram Bot

## Overview
This project is an advanced Telegram bot designed to download restricted content (photos, videos, audio files, documents) from Telegram private chats or channels. It offers features like user authentication, database management, admin controls, and ad monetization. The bot provides both free (ad-supported) and premium ($1/month) access tiers, aiming to be a robust solution for efficient Telegram media access and management.

## User Preferences
I prefer the bot to be stateful and always running, deployed on a VM. I prioritize fast downloads and uploads, utilizing uvloop and parallel transfers. The development process should focus on iterative improvements, ensuring stability and performance. I expect the bot to handle user authentication securely and manage user data efficiently using MongoDB. I want to monetize the bot through Monetag ads, offering users free premium access in exchange for ad views. The bot should also support various payment methods for premium subscriptions.

## System Architecture

### UI/UX Decisions
The bot interacts with users primarily via Telegram commands. Ad verification uses a 2-page auto-advancing web interface with 15-second timers per page. Smartlink ads open directly in new browser tabs. Status messages are designed to be auto-deleting for a cleaner chat experience. The UI for commands like `/stats` and `/adminstats` uses modern emoji-based layouts for enhanced readability.

### Technical Implementations
- **Language**: Python 3.11 with `uvloop` for asynchronous operations and `TgCrypto` for cryptographic tasks.
- **Concurrency & Resource Management**: Per-user concurrency model allowing multiple users to download simultaneously. Adaptive resource allocation based on deployment platform:
  - **Render (512MB)**: Max 3 concurrent users, 1 download per user, 350MB memory limit
  - **Replit**: Max 5 concurrent users, 1 download per user, 380MB memory limit
  - **VPS/Railway**: Max 20 concurrent users, 1 download per user, 900MB memory limit
  - Memory circuit breaker prevents OOM errors by monitoring process memory and rejecting new downloads if limits are approached.
- **Caching**: An LRU cache (500 items, 180s TTL) reduces redundant database queries for frequently accessed data like admin status, ban status, user types, and sessions.
- **Database Optimization**: MongoDB connection pooling with optimized server selection and idle timeouts. No local SQLite or file-based databases are used.
- **Deployment**: Designed for VM deployment, with auto-detection for platforms like Railway.app, Render, Heroku, and Replit, using a Flask wrapper for web server deployment.
- **Monetization**: Iframe-free ad integration using HTML/CSS banner ads and Adsterra smartlinks. Monetag is used for ad-based premium access.
- **Download Queue**: Supports concurrent downloads (adaptive limits based on environment) and a waiting queue, with priority for premium users.
- **User Authentication**: Phone number login with OTP verification and 2FA, creating personal Telegram sessions.
- **User Management**: Free, Premium, and Admin user tiers with distinct access levels, daily download limits, and subscription management.
- **Security**: Encrypted session storage, individual user sessions, admin-only command decorators, ban system, daily rate limiting, and atomic session verification.
- **Progress Display**: `Pyleaves` library provides rich, real-time progress bars for file operations.
- **Stats Monitoring**: Tracks bot-specific metrics like memory/CPU usage, active downloads, queue size, user counts, and daily download statistics.

### System Design Choices
- **Modular Architecture**: Core functionalities are separated into modules (e.g., `phone_auth.py`, `access_control.py`, `ad_monetization.py`, `queue_manager.py`).
- **Database Schema**: MongoDB is exclusively used for all persistent data storage, including user profiles, admin privileges, daily usage, broadcast history, ad sessions, and verification codes.
- **Error Handling**: Race conditions are prevented through atomic session verification. A `safe_progress_callback` wrapper handles `Pyleaves` message editing errors gracefully, preventing message duplication.

## External Dependencies
- **Database**: MongoDB
- **Telegram API Framework**: Pyrofork
- **Cryptography**: TgCrypto
- **Progress Bars**: Pyleaves
- **Image Processing**: Pillow
- **Asynchronous Loop**: uvloop
- **Web Framework**: Flask
- **Environment Variables**: python-dotenv
- **System Utilities**: psutil
- **Monetization Platform**: Monetag
- **Payment Gateways**: PayPal, UPI, Amazon Pay/Gift Card, Cryptocurrency (USDT/BTC/ETH)