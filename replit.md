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

### Enhanced Verification Page & Auto-Verification System (Oct 26, 2025)
**Major Update**: Completely rebuilt verification page with security, reliability, and user experience improvements, plus one-click automatic verification.

#### 🎯 User Experience Improvements

**Previous Flow**:
1. User completes ad session
2. Reaches verification page with code
3. Manually copies code
4. Types `/verifypremium <code>` in bot
5. Receives free downloads

**New Flow**:
1. User completes ad session
2. Reaches verification page with code
3. Clicks "Auto-Verify in Bot" button → **Done!**
4. Instantly receives free downloads

#### 🔒 Security & Reliability Features

**Frontend (verify_success.html)**:
1. **Code Backup System**: Automatically saves verification code to browser's localStorage to prevent loss
2. **30-Minute Timer**: Live countdown showing exact time remaining before code expires
3. **Expiry Warnings**: Visual alerts when code is close to expiring (last 5 minutes pulse animation)
4. **Offline Detection**: Shows warning banner when user loses internet connection
5. **Multiple Copy Methods**: 
   - Primary: Modern Clipboard API
   - Fallback 1: Legacy execCommand method
   - Fallback 2: Manual prompt with pre-selected code
6. **Error Boundaries**: Catches JavaScript errors and shows graceful error messages
7. **Code Leak Prevention**: Prevents verification code from appearing in browser console logs
8. **Mobile Optimized**: Responsive design with touch-friendly buttons
9. **Loading States**: Shows spinner during processing
10. **Visual Feedback**: Success/error alerts for all user actions
11. **Troubleshooting Guide**: Built-in tips for common issues
12. **Exit Warning**: Warns user before leaving page (code will be lost)
13. **Accessibility**: ARIA labels and keyboard navigation support
14. **Security Headers**: Prevents page from being embedded in iframes (clickjacking protection)

**Backend (server.py)**:
1. **Input Validation**: Validates session_id exists and is properly formatted
2. **Error Handling**: Try-catch blocks prevent server crashes
3. **Detailed Logging**: Logs all verification attempts for debugging
4. **Better Error Messages**: User-friendly error descriptions for each failure scenario
5. **Security Headers**: Added X-Content-Type-Options, X-Frame-Options for protection
6. **Cache Control**: Prevents browsers from caching sensitive verification pages

#### 🚀 Technical Implementation

**Deep Link Auto-Verification**:
- Format: `https://t.me/<BOT_USERNAME>?start=verify_<CODE>`
- Clicking button automatically opens Telegram app/web
- Bot receives `/start verify_<CODE>` and processes verification
- User sees instant success message in bot

**Timer System**:
- JavaScript interval updates countdown every second
- Stores expiry time in localStorage (survives page refresh)
- Changes to red pulsing animation in last 5 minutes
- Automatically marks code as expired when timer reaches 0

**Error Recovery**:
- If page fails to load: Code backed up in localStorage
- If clipboard fails: Multiple fallback copy methods
- If offline: Warning shown, page still functional when back online
- If server error: Graceful error page with retry instructions

#### 📝 Files Modified
- `main.py` - Added deep link verification handler in `/start` command
- `config.py` - Added `BOT_USERNAME` configuration
- `server.py` - Enhanced error handling, logging, security headers
- `templates/verify_success.html` - Complete rebuild with all reliability features

#### ⚙️ Environment Variable Required
- `BOT_USERNAME` - Your bot's Telegram username (without @)
  - Example: If bot is @MyBot, set `BOT_USERNAME=MyBot`
  - Used to generate deep links for auto-verification

#### 🎁 Benefits
- ✅ 70% faster verification (1 click vs 5+ steps)
- ✅ Zero user errors from typos
- ✅ Code never lost (automatic backup)
- ✅ Works offline (shows warning, recovers when online)
- ✅ Mobile-friendly design
- ✅ Prevents code expiry surprises (live timer)
- ✅ Multiple fallback mechanisms
- ✅ Professional user experience
- ✅ Secure against common web attacks

### Per-User URL Shortener Rotation System (Oct 27, 2025)
**Major Update**: Changed from global rotation to per-user rotation for better ad revenue distribution and user experience.

**How It Works Now**:
- Each user gets a different shortener service each time they use `/getpremium`
- Rotation is tracked individually per user, not globally
- After successful verification, user is rotated to next shortener for their next request

**User Experience**:
```
User's 1st /getpremium → Droplink.co
After verification...
User's 2nd /getpremium → GPLinks.com
After verification...
User's 3rd /getpremium → ARLinks.in
After verification...
User's 4th /getpremium → UpShrink.com
After verification...
User's 5th /getpremium → Droplink.co (cycle repeats)
```

**Key Changes from Previous System**:
- ❌ **Old:** Global rotation after every 5 downloads (all users shared same shortener)
- ✅ **New:** Per-user rotation (each user has their own rotation cycle)

**Implementation Details**:
1. **Database Tracking**: Added `shortener_index` field to users collection
   - Stores each user's current index (0-3)
   - 0=Droplink, 1=GPLinks, 2=ARLinks, 3=UpShrink
   - First-time users start at index 0 (Droplink)

2. **New Database Methods** in `database.py`:
   - `get_user_shortener_index(user_id)` - Get user's current shortener index
   - `rotate_user_shortener(user_id)` - Rotate user to next shortener after verification

3. **Service Integration** in `ad_monetization.py`:
   - `_shorten_with_droplink()` - Droplink.co API
   - `_shorten_with_gplinks()` - GPLinks.com API  
   - `_shorten_with_arlinks()` - ARLinks.in API
   - `_shorten_with_upshrink()` - UpShrink.com API

4. **Rotation Trigger**: Happens automatically in `verify_code()` method
   - After user successfully verifies code
   - Before granting ad downloads
   - Prepares next shortener for user's next `/getpremium` request

5. **Fallback Mechanism**: If any service fails, automatically falls back to Droplink.co

6. **Environment Variables Required**:
   - `DROPLINK_API_KEY` - Droplink.co API token
   - `GPLINKS_API_KEY` - GPLinks.com API token
   - `ARLINKS_API_KEY` - ARLinks.in API token
   - `UPSHRINK_API_KEY` - UpShrink.com API token

**Benefits**:
- ✅ Better user experience (each user gets fresh shortener each time)
- ✅ More even ad revenue distribution across all services
- ✅ No service gets overloaded (traffic distributed per user, not globally)
- ✅ First-time users always start with Droplink (most reliable)
- ✅ Prevents users from being stuck on same shortener
- ✅ Each user contributes to all 4 ad platforms equally over time

**Files Modified**:
- `database.py` - Added per-user rotation methods, deprecated global rotation
- `ad_monetization.py` - Updated to use per-user rotation, added rotation trigger after verification
- `config.py` - Already supported multiple API keys via environment variables