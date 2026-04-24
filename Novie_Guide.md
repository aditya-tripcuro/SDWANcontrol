# WANControl v2 - Beginner's Guide

## Welcome! 👋

If you're new to networking or Linux, don't worry! This guide will walk you through everything step-by-step.

---

## What is WANControl?

Imagine you have **two internet connections** at your home or office. WANControl is like a **smart traffic cop** that:

1. **Watches** both connections constantly
2. **Decides** which one is working better
3. **Switches** automatically if one fails
4. **Shows** you what's happening on a nice dashboard

### Real-World Example

You have:
- **Connection A**: Fiber optic (fast, reliable)
- **Connection B**: Cable backup (slower, but works when fiber fails)

WANControl ensures you **stay online** even if one connection breaks!

---

## Before You Start

### What You Need

✅ **A computer/server with:**
- At least 2 network cables plugged in
- Linux installed (Ubuntu or Debian recommended)
- Internet access on both connections

✅ **Basic knowledge of:**
- Using terminal/command line
- Editing text files
- Understanding IP addresses (helpful but not required)

✅ **Time:** About 30-60 minutes for first setup

### What This Guide Covers

1. Installing WANControl
2. Setting up your configuration
3. Starting the service
4. Using the dashboard
5. Common tasks and troubleshooting

---

## Part 1: Installation

### Step 1: Open Terminal

Press `Ctrl+Alt+T` or search for "Terminal" in your applications.

### Step 2: Download WANControl

Type these commands (press Enter after each line):

```bash
# Go to your home directory
cd ~

# Download WANControl
git clone https://github.com/aditya-tripcuro/SDWANcontrol.git

# Go into the folder
cd SDWANcontrol
```

**What just happened?**
- You downloaded the WANControl software from GitHub
- You're now in the folder containing all the files

### Step 3: Run the Installer

```bash
sudo ./install.sh
```

**Important notes:**
- `sudo` means "run as administrator"
- You'll be asked for your password (nothing shows while typing - this is normal!)
- The installer takes 2-5 minutes

**What the installer does:**
- Installs required software packages
- Creates a special user for WANControl
- Sets up the service to run automatically
- Creates configuration files

### Step 4: Check Installation

After installation completes, you should see:

```
✓ WANControl installed and running.
Access: http://192.168.x.x:5000
Logs:   journalctl -u wancontrol -f
Config: /etc/wancontrol/config.yaml
```

**Write down that IP address!** You'll need it for the dashboard.

---

## Part 2: Configuration

### Step 1: Find Your Network Interfaces

Before configuring, you need to know your network interface names.

```bash
python3 /opt/wancontrol/discover_interfaces.py
```

You'll see output like:

```
┌────────┬──────────────┬────────────┬──────────────┬──────────────┐
│ Name   │ IPv4         │ Gateway    │ Carrier      │ Speed (Mb/s) │
├────────┼──────────────┼────────────┼──────────────┼──────────────┤
│ enp2s0 │ 192.0.2.10   │ 192.0.2.1  │ yes          │ 1000         │
│ enp3s0 │ 198.51.100.9 │ 198.51.100.1│ yes         │ 500          │
└────────┴──────────────┴────────────┴──────────────┴──────────────┘
```

**Important columns:**
- **Name**: Interface name (you need this!)
- **Gateway**: Router address (you need this!)
- **Carrier**: "yes" means cable is connected

### Step 2: Edit Configuration File

Open the config file:

```bash
sudo nano /etc/wancontrol/config.yaml
```

**Nano basics:**
- Arrow keys to move
- Type to edit
- `Ctrl+O` then `Enter` to save
- `Ctrl+X` to exit

### Step 3: Update Interface Settings

Find the `interfaces:` section and update with YOUR information:

```yaml
interfaces:
  - name: "enp2s0"              # ← Your first interface name
    label: "Primary ISP"        # ← Any name you want
    expected_speed_mbps: 1000   # ← Your internet speed
    gateway: "192.168.1.1"      # ← Your gateway from discover script
    
  - name: "enp3s0"              # ← Your second interface name
    label: "Backup ISP"         # ← Any name you want
    expected_speed_mbps: 500    # ← Your backup speed
    gateway: "192.168.2.1"      # ← Your backup gateway
```

**⚠️ IMPORTANT:** Replace the example values with YOUR actual values!

### Step 4: Choose Your Mode

Find this line:

```yaml
wan_mode: "load_balance"
```

Change to one of:

**Option A: Failover** (recommended for beginners)
```yaml
wan_mode: "failover"
```
- Uses primary connection
- Switches to backup only if primary fails
- Like having a spare tire

**Option B: Load Balance**
```yaml
wan_mode: "load_balance"
```
- Uses BOTH connections simultaneously
- Spreads traffic across both
- Like having two lanes on a highway

### Step 5: Save and Restart

After editing:
1. Press `Ctrl+O`, then `Enter` to save
2. Press `Ctrl+X` to exit
3. Restart WANControl:

```bash
sudo systemctl restart wancontrol
```

---

## Part 3: Using the Dashboard

### Step 1: Open Your Browser

Open Firefox, Chrome, or any web browser.

### Step 2: Go to the Dashboard

Type the address from installation:

```
http://YOUR-IP-ADDRESS:5000
```

Example: `http://192.168.1.100:5000`

### Step 3: First Login

On first startup, WANControl creates an admin account automatically.

**Find your password:**

```bash
journalctl -u wancontrol | grep "Password"
```

You'll see:
```
│  Username : admin
│  Password : abc123xyz...  │
```

**Login with:**
- Username: `admin`
- Password: (the one from logs)

### Step 4: Explore the Dashboard

You'll see several sections:

#### 📊 Dashboard (Home)
- Shows current status of all connections
- Green = Good, Red = Problem
- Live health scores

#### 📈 Metrics
- Historical graphs
- See latency over time
- Track packet loss

#### 📋 Events
- Log of everything that happened
- When switches occurred
- System messages

#### ⚠️ Alerts
- Warnings and errors
- Click to acknowledge
- Mark as resolved

#### ⚙️ Config
- View current settings
- Reload configuration
- System management

---

## Part 4: Daily Operations

### Checking Status

Quick status check:

```bash
sudo systemctl status wancontrol
```

Look for: `active (running)` ✅

### Viewing Logs

See what's happening:

```bash
journalctl -u wancontrol -f
```

Press `Ctrl+C` to stop watching.

### Testing Failover (if using failover mode)

Want to see it work? Try this:

1. **Unplug** your primary network cable
2. **Watch** the dashboard - should switch to backup within 5 seconds
3. **Plug** cable back in
4. **Watch** it switch back to primary

### Adding a New User

Through the dashboard:
1. Go to Config/Users
2. Click "Add User"
3. Enter username, password, role
4. Click Save

**User Roles:**
- **Viewer**: Can only look (read-only)
- **Operator**: Can resolve alerts
- **Admin**: Full control

### Changing Your Password

After first login:
1. Click your username (top right)
2. Select "Change Password"
3. Enter old and new password
4. Click Save

**Password requirements:**
- At least 12 characters
- Mix of letters, numbers recommended

---

## Part 5: Common Tasks

### Task 1: Update Configuration

Whenever you change `/etc/wancontrol/config.yaml`:

```bash
# Edit config
sudo nano /etc/wancontrol/config.yaml

# After saving, reload WANControl
sudo systemctl restart wancontrol

# Or use the API (no restart needed!)
curl -X POST http://localhost:5000/api/config/reload \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Task 2: Check Which Connection is Active

```bash
# Quick check
ip route | grep default

# Or view dashboard - shows active interface
```

### Task 3: Create API Token (for automation)

Through dashboard:
1. Go to Config/API Tokens
2. Click "Create Token"
3. Give it a name (e.g., "Monitoring Script")
4. Copy the token (**shown only once!**)

Use in scripts:
```bash
curl -H "X-API-Token: YOUR_TOKEN" \
  http://localhost:5000/api/status
```

### Task 4: Backup Your Database

```bash
# Copy database to backup location
sudo cp /var/lib/wancontrol/wan.db ~/wan.db.backup.$(date +%Y%m%d)
```

### Task 5: View Interface Statistics

```bash
# Detailed interface info
ip addr show

# Routing table
ip route show

# WANControl specific status
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:5000/api/status/interfaces
```

---

## Part 6: Troubleshooting

### Problem: Can't Access Dashboard

**Check 1: Is service running?**
```bash
sudo systemctl status wancontrol
```

**Check 2: Is firewall blocking?**
```bash
sudo ufw allow 5000/tcp
```

**Check 3: Correct IP address?**
```bash
hostname -I
```

### Problem: "Config file not found"

**Solution:**
```bash
# Check if file exists
ls -la /etc/wancontrol/config.yaml

# If missing, copy default
sudo cp /opt/wancontrol/config.yaml /etc/wancontrol/config.yaml
```

### Problem: No Metrics Showing

**Possible causes:**

1. **Interfaces misconfigured**
   ```bash
   # Verify interface names
   ip addr show
   
   # Compare with config
   sudo cat /etc/wancontrol/config.yaml
   ```

2. **Probes failing**
   ```bash
   # Test manually
   ping -I enp2s0 8.8.8.8
   ```

3. **Firewall blocking**
   ```bash
   # Temporarily disable to test
   sudo ufw disable
   # Re-enable after testing
   sudo ufw enable
   ```

### Problem: High Latency Scores

**This is normal** if your internet is slow! But you can adjust thresholds:

Edit `/etc/wancontrol/config.yaml`:

```yaml
scoring:
  latency_penalty_per_ms: 0.1  # Lower = less penalty
  hard_fail_threshold: 10      # Lower = more tolerant
```

### Problem: Service Won't Start

**Check logs:**
```bash
journalctl -u wancontrol --since "10 minutes ago"
```

**Common fixes:**

1. **Secret key issue:**
   ```bash
   # Generate new secret
   python3 -c "import secrets; print(secrets.token_hex(32))"
   
   # Edit config and replace secret_key
   sudo nano /etc/wancontrol/config.yaml
   ```

2. **Port already in use:**
   ```bash
   # Check what's using port 5000
   sudo netstat -tlnp | grep 5000
   
   # Change port in config
   sudo nano /etc/wancontrol/config.yaml
   # server.port: 5001
   ```

3. **Permission issues:**
   ```bash
   # Fix permissions
   sudo chown -R wancontrol:wancontrol /var/lib/wancontrol
   sudo chmod 755 /var/lib/wancontrol
   ```

### Problem: Forgot Admin Password

**Reset procedure:**

1. Stop service:
   ```bash
   sudo systemctl stop wancontrol
   ```

2. Delete database (⚠️ loses all data!):
   ```bash
   sudo rm /var/lib/wancontrol/wan.db
   ```

3. Start service:
   ```bash
   sudo systemctl start wancontrol
   ```

4. Get new password from logs:
   ```bash
   journalctl -u wancontrol | grep "Password"
   ```

---

## Part 7: Best Practices

### ✅ Do These

1. **Change admin password immediately**
2. **Regular backups** (weekly recommended)
3. **Monitor logs** periodically
4. **Test failover** monthly
5. **Keep system updated**:
   ```bash
   sudo apt-get update && sudo apt-get upgrade
   ```

### ❌ Avoid These

1. **Don't edit database directly** (use API)
2. **Don't disable logging** (needed for troubleshooting)
3. **Don't ignore alerts** (address issues promptly)
4. **Don't share API tokens** (like passwords)
5. **Don't skip config validation** (test changes)

---

## Part 8: Learning More

### Understanding Key Concepts

#### What is a Gateway?
Your gateway is your router's address. It's the "door" to the internet.

#### What is Routing?
Routing is how your computer decides which path to send data.

#### What is Failover?
Automatic switching to backup when primary fails.

#### What is Load Balancing?
Using multiple connections simultaneously to increase total bandwidth.

### Helpful Commands Cheat Sheet

```bash
# Service control
sudo systemctl start wancontrol
sudo systemctl stop wancontrol
sudo systemctl restart wancontrol
sudo systemctl status wancontrol

# View logs
journalctl -u wancontrol -f
journalctl -u wancontrol --since "1 hour ago"

# Network info
ip addr show          # Show interfaces
ip route show         # Show routes
ping -I enp2s0 8.8.8.8  # Test specific interface

# Config management
sudo nano /etc/wancontrol/config.yaml  # Edit config
sudo systemctl restart wancontrol       # Apply changes

# Discovery
python3 /opt/wancontrol/discover_interfaces.py  # Find interfaces
```

### Where to Get Help

1. **This guide** - Start here!
2. **README.md** - Project overview
3. **WIKI.md** - Detailed documentation  
4. **GitHub Issues** - Report bugs, ask questions
5. **Logs** - Often contain error messages

---

## Part 9: Next Steps

### Week 1: Get Comfortable
- [ ] Install and configure WANControl
- [ ] Login to dashboard daily
- [ ] Understand what metrics mean
- [ ] Test basic failover

### Week 2: Customize
- [ ] Adjust scoring thresholds for your network
- [ ] Set up alert notifications
- [ ] Create additional user accounts
- [ ] Configure webhook integrations

### Week 3: Automate
- [ ] Create API tokens for scripts
- [ ] Write simple monitoring script
- [ ] Set up automated backups
- [ ] Integrate with existing tools

### Month 2: Advanced
- [ ] Review historical data trends
- [ ] Optimize configuration
- [ ] Document your setup
- [ ] Train team members

---

## Appendix A: Glossary

| Term | Meaning |
|------|---------|
| **WAN** | Wide Area Network (internet connection) |
| **Interface** | Network port/connection |
| **Gateway** | Router address |
| **Latency** | Delay in milliseconds |
| **Packet Loss** | Percentage of data lost |
| **Failover** | Automatic switch to backup |
| **Load Balance** | Distributing traffic across connections |
| **API** | Programming interface for automation |
| **JWT** | Secure token for authentication |
| **SSE** | Server-Sent Events (real-time updates) |

---

## Appendix B: Default Values

### Default Configuration Locations

| Item | Path |
|------|------|
| Config file | `/etc/wancontrol/config.yaml` |
| Database | `/var/lib/wancontrol/wan.db` |
| Logs | `/var/lib/wancontrol/logs/` |
| Service | `/etc/systemd/system/wancontrol.service` |
| Application | `/opt/wancontrol/` |

### Default Ports

| Service | Port |
|---------|------|
| Web Dashboard | 5000 |
| API | 5000 (same) |

### Default Credentials

| Item | Value |
|------|-------|
| Admin username | `admin` |
| Admin password | Generated on first run (check logs) |

---

## Appendix C: Quick Reference Card

Print this for easy reference!

```
┌─────────────────────────────────────────────────────────┐
│              WANControl Quick Reference                 │
├─────────────────────────────────────────────────────────┤
│ Dashboard: http://YOUR-IP:5000                          │
│                                                         │
│ Start:   sudo systemctl start wancontrol                │
│ Stop:    sudo systemctl stop wancontrol                 │
│ Restart: sudo systemctl restart wancontrol              │
│ Status:  sudo systemctl status wancontrol               │
│                                                         │
│ Logs:    journalctl -u wancontrol -f                    │
│ Config:  sudo nano /etc/wancontrol/config.yaml          │
│                                                         │
│ Discover interfaces:                                    │
│   python3 /opt/wancontrol/discover_interfaces.py        │
│                                                         │
│ Emergency reset:                                        │
│   sudo systemctl stop wancontrol                        │
│   sudo rm /var/lib/wancontrol/wan.db                    │
│   sudo systemctl start wancontrol                       │
└─────────────────────────────────────────────────────────┘
```

---

## Congratulations! 🎉

You've completed the beginner's guide! You now have:

✅ WANControl installed and running
✅ Dashboard accessible
✅ Basic configuration complete
✅ Knowledge to troubleshoot common issues

**Remember:** Take your time, experiment safely, and don't hesitate to check the logs when something doesn't work as expected.

Happy networking! 🌐
