"""
Wrapper to run Telegram bot with Flask web server for Render deployment
This satisfies Render's port binding requirement while keeping the bot running
Optimized for Render's 100GB/month bandwidth limit
"""
import os
import sys
from flask import Flask, jsonify, render_template, request, Response
from flask_compress import Compress
from ad_monetization import ad_monetization

app = Flask(__name__)

# Enable gzip compression to reduce bandwidth (saves ~70% on text responses)
compress = Compress()
compress.init_app(app)

@app.route('/')
def index():
    return jsonify({
        'status': 'online',
        'message': 'Telegram Bot is running!',
        'bot': 'Restricted Content Downloader'
    })

@app.route('/health')
def health():
    """
    Health check endpoint for Render monitoring
    Returns 204 if bot is connected, 503 if disconnected (triggers Render alerts)
    """
    global bot_connected, last_heartbeat_time
    from time import time as current_time
    
    # Check if bot is connected and heartbeat is recent (within 15 minutes)
    # Relaxed window tolerates one missed heartbeat (5min interval + margin)
    heartbeat_age = current_time() - last_heartbeat_time
    is_healthy = bot_connected and heartbeat_age < 900
    
    if is_healthy:
        # HTTP 204 No Content = healthy, minimal bandwidth
        return '', 204
    else:
        # HTTP 503 Service Unavailable = unhealthy, triggers Render alerts
        return jsonify({
            'status': 'unhealthy',
            'bot_connected': bot_connected,
            'last_heartbeat_age': int(heartbeat_age)
        }), 503

@app.route('/watch-ad')
def watch_ad():
    session_id = request.args.get('session', '')
    
    # Get ad codes from config (these are safe as they're from env vars, not user input)
    from config import PyroConf
    ad_code_1 = getattr(PyroConf, 'AD_CODE_1', '')
    ad_code_2 = getattr(PyroConf, 'AD_CODE_2', '')
    ad_code_3 = getattr(PyroConf, 'AD_CODE_3', '')
    
    response = app.make_response(render_template('ad_verify.html', 
                         session=session_id,
                         ad_code_1=ad_code_1,
                         ad_code_2=ad_code_2,
                         ad_code_3=ad_code_3))
    
    # Add security headers
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['Content-Security-Policy'] = "default-src 'self' 'unsafe-inline' https:; frame-src https:; script-src 'self' 'unsafe-inline' https:;"
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    
    # Cache ad page for 1 hour to reduce bandwidth
    response.headers['Cache-Control'] = 'public, max-age=3600'
    
    return response

@app.route('/verify-ad')
def verify_ad():
    """GET endpoint to verify ad completion and get verification code"""
    session_id = request.args.get('session', '')
    
    success, code, message = ad_monetization.verify_ad_completion(session_id)
    
    return jsonify({
        'success': success,
        'code': code,
        'message': message
    })

@app.route('/api/verify-session', methods=['POST'])
def verify_session():
    """API endpoint to verify ad completion and get verification code"""
    data = request.get_json()
    session_id = data.get('session', '')
    
    success, code, message = ad_monetization.verify_ad_completion(session_id)
    
    return jsonify({
        'success': success,
        'code': code,
        'message': message
    })

def run_bot():
    """Run the Telegram bot in a background thread with long polling and auto-reconnection"""
    import asyncio
    from time import time as current_time
    
    # Set uvloop policy for better performance (before creating loop)
    try:
        import uvloop
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    except ImportError:
        pass
    
    # Create and set event loop BEFORE importing main
    # This ensures Pyrogram Client has an event loop during initialization
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Now import main - Pyrogram will see the event loop
    import main
    
    # Global variable to track bot connection status for /health endpoint
    global bot_connected, last_heartbeat_time
    bot_connected = False
    last_heartbeat_time = current_time()
    
    async def idle_with_heartbeat():
        """Keep bot alive and monitor connection health with periodic heartbeats"""
        global bot_connected, last_heartbeat_time
        heartbeat_interval = 300  # Check connection every 5 minutes
        heartbeat_failures = 0
        max_failures = 2
        
        while True:
            try:
                await asyncio.sleep(heartbeat_interval)
                
                # Heartbeat: check if bot is still connected
                if hasattr(main.bot, 'is_connected') and main.bot.is_connected:
                    # Try a lightweight API call to verify connection
                    await main.bot.get_me()
                    bot_connected = True
                    last_heartbeat_time = current_time()
                    heartbeat_failures = 0
                    main.LOGGER(__name__).debug(f"Heartbeat: Bot connection healthy")
                else:
                    raise ConnectionError("Bot is not connected")
                    
            except Exception as e:
                heartbeat_failures += 1
                bot_connected = False
                main.LOGGER(__name__).warning(f"Heartbeat failed ({heartbeat_failures}/{max_failures}): {e}")
                
                if heartbeat_failures >= max_failures:
                    main.LOGGER(__name__).error("Heartbeat failed too many times, triggering reconnection")
                    raise ConnectionError("Heartbeat monitoring detected connection loss")
    
    async def run_bot_forever():
        """Run bot with automatic reconnection on timeout/network errors"""
        global bot_connected, last_heartbeat_time
        retry_count = 0
        base_delay = 5  # Start with 5 seconds
        max_delay = 300  # Cap at 5 minutes
        stable_run_threshold = 900  # 15 minutes of stable operation resets backoff
        
        while True:
            start_time = current_time()
            current_delay = min(base_delay * (2 ** retry_count), max_delay)
            
            try:
                main.LOGGER(__name__).info(f"Starting Telegram bot (attempt {retry_count + 1})")
                await main.bot.start()
                bot_connected = True
                last_heartbeat_time = current_time()  # Initialize heartbeat timestamp on successful start
                main.LOGGER(__name__).info("Bot started successfully, monitoring connection...")
                
                # Run bot with heartbeat monitoring
                await idle_with_heartbeat()
                
            except (TimeoutError, OSError, ConnectionError) as e:
                # Network/timeout errors - expected on Render, retry with backoff
                bot_connected = False
                retry_count += 1
                
                main.LOGGER(__name__).warning(
                    f"Bot connection error (attempt {retry_count}): {type(e).__name__}: {e}. "
                    f"Retrying in {current_delay}s..."
                )
                
                # Graceful shutdown before retry
                try:
                    if main.bot.is_connected:
                        await main.bot.stop()
                except:
                    pass
                
                await asyncio.sleep(current_delay)
                
            except Exception as e:
                # Unexpected errors - log and retry with backoff
                bot_connected = False
                retry_count += 1
                
                main.LOGGER(__name__).error(
                    f"Unexpected bot error (attempt {retry_count}): {type(e).__name__}: {e}. "
                    f"Retrying in {current_delay}s...",
                    exc_info=True
                )
                
                # Graceful shutdown before retry
                try:
                    if main.bot.is_connected:
                        await main.bot.stop()
                except:
                    pass
                
                await asyncio.sleep(current_delay)
            
            finally:
                # Check if bot ran stably for threshold period - reset backoff
                run_duration = current_time() - start_time
                if run_duration >= stable_run_threshold:
                    main.LOGGER(__name__).info(
                        f"Bot ran stably for {run_duration:.0f}s, resetting reconnection backoff"
                    )
                    retry_count = 0
    
    # Run the resilient bot loop
    loop.run_until_complete(run_bot_forever())

# Global variables for bot status tracking
bot_connected = False
last_heartbeat_time = 0

# Start bot process when app initializes (for Gunicorn workers)
import threading
bot_started = False
bot_lock = threading.Lock()

def start_bot_once():
    """Start bot only once across all workers"""
    global bot_started
    with bot_lock:
        if not bot_started:
            print(f"Starting Telegram bot in background thread...")
            bot_thread = threading.Thread(target=run_bot, daemon=True)
            bot_thread.start()
            bot_started = True

# Start bot when module loads (for Gunicorn)
start_bot_once()

if __name__ == '__main__':
    # This runs only for development (Replit, local testing)
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting Flask development server on 0.0.0.0:{port}")
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False, threaded=True)
