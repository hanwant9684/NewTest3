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
from config import PyroConf

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

@app.route('/memory-debug')
def view_memory_debug():
    """
    View memory debug log - for Render free plan users who can't access Shell
    Access this at: https://your-app.onrender.com/memory-debug
    """
    try:
        import os
        memory_log_file = 'memory_debug.log'
        
        if not os.path.exists(memory_log_file):
            return """
            <html>
            <head><title>Memory Debug Log</title></head>
            <body style="font-family: monospace; padding: 20px; background: #1e1e1e; color: #d4d4d4;">
                <h1 style="color: #4ec9b0;">Memory Debug Log - Not Found</h1>
                <p style="color: #ce9178;">The memory log file hasn't been created yet. It will be created when the bot starts.</p>
                <p><a href="/" style="color: #569cd6;">← Back to home</a></p>
            </body>
            </html>
            """, 404
        
        # Read the entire log file
        with open(memory_log_file, 'r') as f:
            log_content = f.read()
        
        # Return as HTML with copy button
        html = f"""
        <html>
        <head>
            <title>Memory Debug Log - Render Free Plan</title>
            <meta charset="utf-8">
            <style>
                body {{
                    font-family: 'Courier New', monospace;
                    padding: 20px;
                    background: #1e1e1e;
                    color: #d4d4d4;
                    margin: 0;
                }}
                .header {{
                    background: #2d2d30;
                    padding: 20px;
                    margin: -20px -20px 20px -20px;
                    border-bottom: 2px solid #007acc;
                }}
                h1 {{
                    color: #4ec9b0;
                    margin: 0 0 10px 0;
                }}
                .info {{
                    color: #ce9178;
                    font-size: 14px;
                }}
                .actions {{
                    margin: 20px 0;
                }}
                button {{
                    background: #0e639c;
                    color: white;
                    border: none;
                    padding: 10px 20px;
                    font-size: 14px;
                    cursor: pointer;
                    border-radius: 3px;
                    margin-right: 10px;
                }}
                button:hover {{
                    background: #1177bb;
                }}
                #log-content {{
                    background: #252526;
                    padding: 20px;
                    border-radius: 5px;
                    white-space: pre-wrap;
                    word-wrap: break-word;
                    font-size: 13px;
                    line-height: 1.5;
                    border: 1px solid #3e3e42;
                    max-height: 600px;
                    overflow-y: auto;
                }}
                .alert {{
                    background: #d4a24c;
                    color: #000;
                    padding: 10px;
                    border-radius: 3px;
                    margin: 10px 0;
                    display: none;
                }}
                .success {{
                    background: #4ec9b0;
                }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>🔍 Memory Debug Log</h1>
                <p class="info">For Render Free Plan - No Shell Access Required</p>
                <p class="info">File size: {len(log_content)} bytes | Last updated: just now</p>
            </div>
            
            <div class="actions">
                <button onclick="copyToClipboard()">📋 Copy All to Clipboard</button>
                <button onclick="downloadFile()">💾 Download as File</button>
                <button onclick="location.reload()">🔄 Refresh</button>
            </div>
            
            <div id="alert" class="alert"></div>
            
            <h3 style="color: #569cd6;">Log Contents:</h3>
            <div id="log-content">{log_content}</div>
            
            <div style="margin-top: 20px; color: #858585; font-size: 12px;">
                <p><strong>Instructions for sharing with developer:</strong></p>
                <ol>
                    <li>Click "Copy All to Clipboard" button above</li>
                    <li>Paste into a text file or message</li>
                    <li>Share the contents to diagnose memory issues</li>
                </ol>
                <p><strong>What to look for:</strong></p>
                <ul>
                    <li>🚨 CRITICAL sections (right before crash)</li>
                    <li>⚠️ HIGH MEMORY warnings</li>
                    <li>Number of sessions, downloads, and cache items</li>
                    <li>Recent operations before memory spikes</li>
                </ul>
            </div>
            
            <script>
                function copyToClipboard() {{
                    const text = document.getElementById('log-content').innerText;
                    navigator.clipboard.writeText(text).then(function() {{
                        showAlert('✅ Copied to clipboard successfully!', true);
                    }}, function() {{
                        // Fallback for older browsers
                        const textArea = document.createElement('textarea');
                        textArea.value = text;
                        document.body.appendChild(textArea);
                        textArea.select();
                        document.execCommand('copy');
                        document.body.removeChild(textArea);
                        showAlert('✅ Copied to clipboard!', true);
                    }});
                }}
                
                function downloadFile() {{
                    const text = document.getElementById('log-content').innerText;
                    const blob = new Blob([text], {{ type: 'text/plain' }});
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = 'memory_debug_' + new Date().toISOString().slice(0,10) + '.log';
                    a.click();
                    window.URL.revokeObjectURL(url);
                    showAlert('✅ File downloaded!', true);
                }}
                
                function showAlert(message, success) {{
                    const alert = document.getElementById('alert');
                    alert.textContent = message;
                    alert.className = 'alert' + (success ? ' success' : '');
                    alert.style.display = 'block';
                    setTimeout(() => {{
                        alert.style.display = 'none';
                    }}, 3000);
                }}
            </script>
        </body>
        </html>
        """
        
        return html
        
    except Exception as e:
        from logger import LOGGER
        LOGGER(__name__).error(f"Error serving memory debug log: {e}")
        return f"""
        <html>
        <head><title>Error</title></head>
        <body style="font-family: monospace; padding: 20px; background: #1e1e1e; color: #d4d4d4;">
            <h1 style="color: #f48771;">Error Loading Memory Log</h1>
            <p style="color: #ce9178;">Error: {str(e)}</p>
            <p><a href="/" style="color: #569cd6;">← Back to home</a></p>
        </body>
        </html>
        """, 500

@app.route('/verify-ad')
def verify_ad():
    """GET endpoint to verify ad completion and show verification code page (for droplink.co)"""
    try:
        session_id = request.args.get('session', '').strip()
        
        if not session_id:
            response = app.make_response(render_template('verify_success.html',
                                                          title='Invalid Request',
                                                          message='No session ID provided. Please use the link from /getpremium command.',
                                                          code=None,
                                                          bot_username=PyroConf.BOT_USERNAME))
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
            return response
        
        success, code, message = ad_monetization.verify_ad_completion(session_id)
        
        bot_username = PyroConf.BOT_USERNAME or ''
        
        if success:
            from logger import LOGGER
            LOGGER(__name__).info(f"Ad verification successful for session {session_id[:8]}..., code: {code}")
            
            response = app.make_response(render_template('verify_success.html',
                                                          title='Ad Completed Successfully! 🎉',
                                                          message='Congratulations! You have successfully completed the ad verification.',
                                                          code=code,
                                                          bot_username=bot_username))
        else:
            from logger import LOGGER
            LOGGER(__name__).warning(f"Ad verification failed for session {session_id[:8] if session_id else 'empty'}...: {message}")
            
            response = app.make_response(render_template('verify_success.html',
                                                          title='Verification Failed',
                                                          message=message,
                                                          code=None,
                                                          bot_username=bot_username))
        
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        
        return response
        
    except Exception as e:
        from logger import LOGGER
        LOGGER(__name__).error(f"Error in verify_ad endpoint: {e}")
        
        response = app.make_response(render_template('verify_success.html',
                                                      title='Server Error',
                                                      message='An unexpected error occurred. Please try again or contact support.',
                                                      code=None,
                                                      bot_username=PyroConf.BOT_USERNAME or ''))
        
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        
        return response


async def periodic_gc_task():
    """Periodic garbage collection for memory-constrained environments (Render 512MB)"""
    import gc
    import asyncio
    from memory_monitor import memory_monitor
    
    while True:
        try:
            await asyncio.sleep(300)  # Run every 5 minutes
            # Force garbage collection to free memory from completed downloads
            collected = gc.collect()
            if collected > 0:
                from logger import LOGGER
                LOGGER(__name__).debug(f"Garbage collection freed {collected} objects")
                memory_monitor.log_memory_snapshot("Garbage Collection", f"Freed {collected} objects")
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
            
            # Start periodic memory monitoring for Render 512MB plan debugging
            # This logs memory usage every 5 minutes to help identify RAM issues
            from memory_monitor import memory_monitor
            asyncio.create_task(memory_monitor.periodic_monitor(interval=300))
            main.LOGGER(__name__).info("Started periodic memory monitoring (5-minute intervals)")
            
            # Log initial memory snapshot
            memory_monitor.log_memory_snapshot("Bot Startup", "Initial state after bot start")
            
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
