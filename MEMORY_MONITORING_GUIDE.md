# Memory Monitoring Guide for Render 512MB Deployment

## Overview
This bot includes comprehensive memory monitoring to help identify what's causing RAM issues on your Render 512MB plan. The system tracks memory usage before/after operations and logs detailed snapshots to help you debug memory problems.

## How It Works

### 1. Automatic Memory Tracking
The memory monitor automatically tracks:
- **Session Creation**: When users login and create Telegram sessions (~100MB each)
- **Session Cleanup**: When old sessions are disconnected to free memory
- **Downloads**: Memory usage before/after each download
- **Uploads**: Memory usage during file uploads
- **Garbage Collection**: When Python's GC runs and how much it frees
- **Periodic Checks**: Every 5 minutes, logs current memory state

### 2. Memory Snapshot Format
Each snapshot shows:
```
📊 MEMORY SNAPSHOT | Operation: Download Started
├─ RAM Usage: 287.5 MB (Virtual: 1024.3 MB)
├─ System: 56.2% used (223.8 MB available)
├─ Sessions: 2 | Queue: 0 | Active DLs: 1
├─ Cache: 12 items | Threads: 8 | Open files: 15
└─ Context: User 12345 | Active: 1
```

**Understanding the metrics:**
- **RAM Usage (RSS)**: Actual physical RAM being used by the bot
- **Virtual**: Virtual memory (usually higher, not a concern)
- **System**: Overall system memory usage percentage
- **Sessions**: Number of active user Telegram sessions (each ~100MB)
- **Queue**: Downloads waiting in queue
- **Active DLs**: Currently downloading files
- **Cache**: Cached database items
- **Threads**: Number of threads running
- **Open files**: File descriptors currently open

### 3. Automatic Alerts

#### Memory Spike Detection
If memory increases by **50MB+ suddenly**, you'll see:
```
⚠️ MEMORY SPIKE DETECTED: +75.3 MB increase!
📜 Recent operations (last 20): [shows what happened before the spike]
```

#### High Memory Warning
If memory exceeds **400MB (on 512MB plan)**, you'll see:
```
⚠️ HIGH MEMORY USAGE: 421.7 MB / 512 MB
```

## Reading the Logs

### Normal Operations
Look for these patterns in `logs.txt`:

**Healthy pattern:**
```
[INFO] Session Created | User 123 - Total sessions: 1 | Memory: 150.2 MB
[INFO] Download Started | User 123 | Memory: 152.5 MB
[INFO] Download Completed | User 123 | Memory: 153.1 MB (small increase = good)
[INFO] Session Disconnected | Freed session for user 456 | Memory: 148.7 MB (decrease = good)
```

**Problem pattern:**
```
[WARNING] ⚠️ MEMORY SPIKE DETECTED: +120.5 MB increase!
[WARNING] Session Created | User 789 - Total sessions: 4 | Memory: 450.3 MB
```

### Common Memory Issues & Solutions

#### Issue 1: Too Many Sessions
**Symptom:**
```
Sessions: 5 | Memory: 480 MB
⚠️ HIGH MEMORY USAGE
```

**Cause**: Each Telegram session uses ~100MB. 5 sessions = 500MB.

**Solution**: The bot already limits to 3 sessions on Render. If you see more than 3:
- Check `helpers/session_manager.py` - line 123 should say `MAX_SESSIONS = 3 if IS_CONSTRAINED else 5`
- Verify `RENDER` or `RENDER_EXTERNAL_URL` env variable is set

#### Issue 2: Memory Not Freed After Download
**Symptom:**
```
Download Started | Memory: 200 MB
Download Completed | Memory: 280 MB  (didn't decrease!)
```

**Cause**: Large files staying in memory, Python GC not running.

**Solution**:
- Check if garbage collection is running (you should see GC logs every 5 minutes)
- The bot automatically forces GC when memory > 400MB
- Files should auto-cleanup from `Assets/` folder every 30 minutes

#### Issue 3: Queue Building Up
**Symptom:**
```
Queue: 15 | Active DLs: 3 | Memory: 350 MB
```

**Cause**: Too many downloads queued, each consuming some memory.

**Solution**:
- Queue is capped at 20 items (see `queue_manager.py`)
- Premium users have priority, free users wait
- Users can `/canceldownload` to free queue space

#### Issue 4: Memory Leak (Continuous Growth)
**Symptom:**
```
Periodic Check | Memory: 150 MB (hour 1)
Periodic Check | Memory: 200 MB (hour 2)
Periodic Check | Memory: 250 MB (hour 3)
Periodic Check | Memory: 300 MB (hour 4)
```

**Cause**: Something is not being cleaned up.

**Solution**:
1. Check the "Recent operations" log to see what happened before each increase
2. Look for patterns: Does memory increase after specific operations?
3. Common culprits:
   - User sessions not being disconnected (check session_manager logs)
   - Downloaded files not being cleaned up (check cleanup task logs)
   - Database cache growing unbounded (check cache size in snapshots)

## Using Memory Logs for Debugging on Render

### Step 1: Reproduce the Issue
1. Deploy to Render with memory monitoring enabled (done automatically)
2. Wait for the memory issue to occur (crash, slowdown, etc.)
3. Check Render logs for the last hour before the crash

### Step 2: Find the Memory Snapshots
Search logs for:
```bash
grep "MEMORY SNAPSHOT" logs.txt
grep "MEMORY SPIKE" logs.txt
grep "HIGH MEMORY" logs.txt
```

### Step 3: Identify the Pattern
Look at the timestamps and operations:
- What operation caused the spike?
- How many sessions were active?
- Was the queue full?
- Were there many cached items?

### Step 4: Check Recent Operations
When you see a spike, look for:
```
📜 Recent operations (last 20):
  1. [10:15:23] Session Created - 150.2 MB - User 123
  2. [10:15:45] Download Started - 152.5 MB - User 123 | File size: 45.3 MB
  3. [10:16:30] Download Completed - 198.7 MB - User 123
  4. [10:16:31] Upload Started - 200.1 MB - User 123 | File size: 45.3 MB
```

This shows exactly what sequence of operations led to the memory spike.

### Step 5: Fix the Root Cause
Based on patterns:
- **Many sessions**: Reduce `MAX_SESSIONS` in `session_manager.py`
- **Large downloads**: Reduce `max_concurrent` in `queue_manager.py`
- **Cache growth**: Reduce cache size in `cache.py`
- **GC not running**: Check if periodic GC task is starting (should log at startup)

## Configuration Options

### Adjust Memory Monitoring Sensitivity
Edit `memory_monitor.py`:

```python
self.memory_threshold_mb = 400  # Alert if memory exceeds 400MB (change to 350 for earlier warnings)
self.spike_threshold_mb = 50    # Alert if memory increases by 50MB (change to 30 for more sensitive)
```

### Change Monitoring Interval
Edit `server.py` line 167:
```python
asyncio.create_task(memory_monitor.periodic_monitor(interval=300))  # Change 300 to 600 for 10-minute intervals
```

### Add Custom Tracking
To track memory for your own operations:

```python
from memory_monitor import memory_monitor

# Simple snapshot
memory_monitor.log_memory_snapshot("My Operation", "Additional context here")

# Track operation with before/after
async def my_operation():
    await memory_monitor.log_operation(
        "My Custom Operation",
        my_function,
        arg1, arg2,
        memory_context="Processing large file"
    )
```

## Expected Memory Usage on Render 512MB

**Baseline (bot idle):**
- Bot process: ~80-100 MB
- 0 sessions: ~80 MB
- 1 session: ~180 MB
- 2 sessions: ~280 MB
- 3 sessions: ~380 MB

**During downloads:**
- +10-50 MB per active download (depends on file size)
- Downloads are cleaned up immediately after upload
- Should drop back to baseline quickly

**Safe operating range:**
- 0-350 MB: ✅ Healthy
- 350-450 MB: ⚠️ Getting high (monitor closely)
- 450-500 MB: 🔴 Critical (may crash soon)
- 500+ MB: ❌ Imminent crash

## Troubleshooting Commands

Check current memory state:
```bash
# On Render, view live logs and search for "MEMORY SNAPSHOT"
# Most recent snapshot shows current state
```

Force garbage collection:
```bash
# The bot does this automatically every 5 minutes
# Also runs automatically when memory > 400MB
```

View session count:
```bash
# Search logs for "active_sessions" in memory snapshots
# Should never exceed 3 on Render
```

## Summary
The memory monitoring system gives you complete visibility into RAM usage on your Render 512MB deployment. Use the logs to:
1. **Identify** what operations consume the most memory
2. **Detect** memory spikes and leaks before they crash the bot
3. **Debug** memory issues by seeing the exact sequence of events
4. **Optimize** by adjusting session limits, queue sizes, and cache settings

If you see persistent memory issues, check the logs for patterns and adjust the configuration accordingly.
