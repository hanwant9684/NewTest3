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
    # Return minimal response to save bandwidth (8,640 pings/month from UptimeRobot)
    # HTTP 204 No Content = 0 bytes body vs JSON = ~20 bytes
    return '', 204

@app.route('/verify-ad')
def verify_ad():
    """GET endpoint to verify ad completion and show verification code page (for droplink.co)"""
    session_id = request.args.get('session', '')
    
    success, code, message = ad_monetization.verify_ad_completion(session_id)
    
    if success:
        response = app.make_response(render_template('verify_success.html',
                                                      title='Ad Completed!',
                                                      message='Thank you for watching the ad. Here is your verification code:',
                                                      code=code))
    else:
        response = app.make_response(render_template('verify_success.html',
                                                      title='Verification Failed',
                                                      message=message,
                                                      code=None))
    
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    
    return response


async def periodic_gc_task():
    """Periodic garbage collection for memory-constrained environments (Render 512MB)"""
    import gc
    import asyncio
    
    while True:
        try:
            await asyncio.sleep(300)  # Run every 5 minutes
            # Force garbage collection to free memory from completed downloads
            collected = gc.collect()
            if collected > 0:
                from logger import LOGGER
                LOGGER(__name__).debug(f"Garbage collection freed {collected} objects")
        except Exception as e:
            from logger import LOGGER
            LOGGER(__name__).error(f"Garbage collection error: {e}")

def run_bot():
    """Run the Telegram bot in a background thread with long polling"""
    import asyncio
    
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
    
    async def start_bot():
        """Start bot without signal handlers (thread-safe)"""
        try:
            main.LOGGER(__name__).info("Starting Telegram bot from server.py (long polling)")
            await main.bot.start()
            
            # Set bot start time to ignore old pending updates
            import time
            main.bot.start_time = time.time()
            
            main.LOGGER(__name__).info("Bot started successfully, waiting for updates...")
            
            # Start auth session cleanup task (prevents memory leaks)
            main.phone_auth_handler.start_cleanup_task()
            
            # Start periodic download cleanup task (frees disk space)
            from helpers.cleanup import start_periodic_cleanup
            asyncio.create_task(start_periodic_cleanup(interval_minutes=30))
            main.LOGGER(__name__).info("Started periodic download cleanup task")
            
            # Start periodic garbage collection for Render's 512MB RAM limit
            # This helps prevent memory buildup from completed downloads
            asyncio.create_task(periodic_gc_task())
            main.LOGGER(__name__).info("Started periodic garbage collection task")
            
            # Verify dump channel after bot starts
            await main.verify_dump_channel()
            
            # Keep the bot running without signal handlers (thread-safe alternative to idle())
            await asyncio.Event().wait()
        finally:
            # Gracefully disconnect all user sessions before shutdown
            try:
                from helpers.session_manager import session_manager
                await session_manager.disconnect_all()
                main.LOGGER(__name__).info("Disconnected all user sessions")
            except Exception as e:
                main.LOGGER(__name__).error(f"Error disconnecting sessions: {e}")
            
            await main.bot.stop()
            main.LOGGER(__name__).info("Bot stopped")
    
    # Run the async coroutine on this thread's event loop
    loop.run_until_complete(start_bot())

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
