# How to Check What Happened When Render Runs Out of Memory

## The Solution: `memory_debug.log` File

Your bot now creates a **dedicated memory log file** called `memory_debug.log` that captures critical memory events. This file **persists after crashes** and shows exactly what happened before running out of RAM.

## How to Access It on Render

### Method 1: Download from Render Dashboard (Easiest)

1. Go to your Render dashboard
2. Click on your web service
3. Click **"Shell"** tab (opens terminal)
4. Run: `cat memory_debug.log`
5. Copy the entire output - this shows what happened before the crash

**Alternative**: Download the file
```bash
# In Render Shell
cat memory_debug.log > /tmp/memory_report.txt
```
Then copy/paste the contents.

### Method 2: View During Active Session

If the bot is still running (before crash):
1. Go to Render Dashboard → Shell
2. Run: `tail -100 memory_debug.log`
3. This shows the last 100 lines with recent events

## What's in the File?

### Example File After a Crash:

```
================================================================================
MEMORY DEBUG LOG - Telegram Bot on Render 512MB Plan
Started: 2025-10-27 14:30:15
================================================================================

This file captures critical memory events to help debug OOM crashes.
Check this file after crashes to see what happened before running out of RAM.

--------------------------------------------------------------------------------

[2025-10-27 14:35:22] 📊 Periodic Snapshot: 145.3 MB
   Sessions: 1 | Queue: 0 | Active DLs: 0 | Cache: 5

[2025-10-27 14:40:25] 📊 Periodic Snapshot: 178.2 MB
   Sessions: 2 | Queue: 1 | Active DLs: 1 | Cache: 8

[2025-10-27 14:42:10] ⚠️ MEMORY SPIKE: +87.5 MB
📊 MEMORY SNAPSHOT | Operation: Session Created
├─ RAM Usage: 265.7 MB (Virtual: 1024.3 MB)
├─ System: 52.1% used (245.2 MB available)
├─ Sessions: 2 | Queue: 1 | Active DLs: 1
├─ Cache: 8 items | Threads: 12 | Open files: 18
└─ Context: User 12345 - Total sessions: 2
Recent operations:
  1. [14:35:22] Periodic Check - 145.3 MB - Auto-check every 300s
  2. [14:40:25] Download Started - 178.2 MB - User 67890 | Active: 1
  3. [14:42:10] Session Created - 265.7 MB - User 12345 - Total sessions: 2
--------------------------------------------------------------------------------

[2025-10-27 14:45:18] ⚠️ HIGH MEMORY: 412.3 MB / 512 MB
📊 MEMORY SNAPSHOT | Operation: Download Started
├─ RAM Usage: 412.3 MB (Virtual: 1156.7 MB)
├─ System: 80.5% used (99.8 MB available)
├─ Sessions: 3 | Queue: 2 | Active DLs: 2
├─ Cache: 15 items | Threads: 14 | Open files: 24
└─ Context: User 99999 | Active: 2
--------------------------------------------------------------------------------

[2025-10-27 14:46:05] 🗑️ Auto GC triggered at 432.1 MB
   Collected 145 objects, freed 15.3 MB → now 416.8 MB
--------------------------------------------------------------------------------

[2025-10-27 14:47:33] 🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨
[2025-10-27 14:47:33] 🚨 CRITICAL MEMORY - CRASH IMMINENT: 498.7 MB / 512 MB
🚨 CRITICAL: CRASH IMMINENT! 498.7 MB / 512 MB
Sessions: 4 | Queue: 3 | Active DLs: 3 | Cache: 22
Last 5 operations before crash:
  1. [14:45:18] Download Started - 412.3 MB - User 99999 | Active: 2
  2. [14:46:05] Garbage Collection - 416.8 MB - Freed 145 objects
  3. [14:46:42] Session Created - 456.2 MB - User 77777 - Total sessions: 4
  4. [14:47:10] Download Started - 478.5 MB - User 88888 | Active: 3
  5. [14:47:33] Download Started - 498.7 MB - User 55555 | Active: 3
🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨

[Bot crashes here due to OOM]

================================================================================
🔄 BOT RESTARTED at 2025-10-27 14:50:12
Previous session may have crashed - check logs above
================================================================================
```

## Reading the File - What to Look For

### 1. Find the 🚨 CRITICAL MEMORY Section
This appears right before a crash and shows:
- **Exact memory usage** when crash was about to happen
- **Number of sessions** (should be ≤3 on Render)
- **Active downloads** (should be ≤3 on Render)
- **Last 5 operations** that led to the crash

### 2. Check the "Last 5 operations before crash"
This shows the sequence of events:
```
5. [14:47:33] Download Started - 498.7 MB - User 55555 | Active: 3
4. [14:47:10] Download Started - 478.5 MB - User 88888 | Active: 3
3. [14:46:42] Session Created - 456.2 MB - User 77777 - Total sessions: 4
```

**Problem identified**: Session #4 was created at 456MB, pushing total to 4 sessions when limit is 3!

### 3. Look for Patterns

**Too many sessions:**
```
Sessions: 4 | RAM: 480 MB
```
→ Session manager not working (should be max 3 on Render)

**Too many concurrent downloads:**
```
Active DLs: 5 | RAM: 490 MB
```
→ Queue manager allowing too many (should be max 3 on Render)

**Memory not freed after operations:**
```
[14:40] Download Started - 200 MB
[14:42] Download Completed - 200 MB  ← Should decrease!
[14:45] Still at 200 MB
```
→ Files not being cleaned up

**Gradual memory leak:**
```
[10:00] Periodic Snapshot: 150 MB
[11:00] Periodic Snapshot: 200 MB
[12:00] Periodic Snapshot: 250 MB
[13:00] Periodic Snapshot: 300 MB
```
→ Something accumulating over time

## Quick Troubleshooting Guide

Based on what you find in `memory_debug.log`:

| Problem Found | Solution |
|--------------|----------|
| `Sessions: 4` or more | Session limit not working - check `MAX_SESSIONS` in `helpers/session_manager.py` |
| `Active DLs: 4` or more | Download limit not working - check `max_concurrent` in `queue_manager.py` |
| Memory stays high after downloads | Cleanup not running - check cleanup task logs |
| Gradual increase every hour | Memory leak - check what operations repeated before each increase |
| Spike during specific operation | That operation is the problem - optimize or limit it |

## File Location on Render

The file is located in the root directory of your project:
```
/opt/render/project/src/memory_debug.log
```

## Automatic Features

1. **Persists after crashes** - The file is NOT deleted when the bot restarts
2. **Shows crash recovery** - When bot restarts, it adds a marker: "🔄 BOT RESTARTED"
3. **Critical warnings** - Automatically logs when memory > 480MB (crash imminent)
4. **Auto GC logging** - Shows when garbage collection runs and how much it freed
5. **Periodic snapshots** - Logs memory state every 5 minutes

## Example Debugging Session

**Problem**: Bot crashes every 2-3 hours on Render

**Steps**:
1. Go to Render Shell
2. Run: `cat memory_debug.log`
3. Find the 🚨 CRITICAL section
4. See: `Sessions: 4 | 498.7 MB`
5. **Root cause identified**: Too many sessions (should be 3 max)
6. Check if `RENDER` environment variable is set in Render dashboard
7. If not set, the code thinks it's not on Render and allows 5 sessions
8. Fix: Add environment variable `RENDER=true` in Render dashboard
9. Redeploy and monitor

## Summary

✅ **Dedicated log file** survives crashes  
✅ **Shows last operations** before running out of memory  
✅ **Critical warnings** when crash is imminent (>480MB)  
✅ **Periodic snapshots** every 5 minutes  
✅ **Easy to access** via Render Shell  
✅ **Clear patterns** to identify root cause  

No more guessing what caused memory issues - you have a complete record! 🎯
