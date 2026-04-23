# WANControl v2 - Quick Start Guide

This guide will help you get WANControl v2 up and running in minutes.

## Prerequisites

- Linux system (Debian/Ubuntu recommended)
- Python 3.10+
- At least two WAN interfaces
- Root or sudo access

## Step 1: Installation

```bash
# Clone the repository
git clone https://github.com/aditya-tripcuro/SDWANcontrol.git
cd SDWANcontrol

# Run the installer
sudo ./install.sh
```

The installer will:
- Install system dependencies (iproute2, ping, dig, curl)
- Create the `wancontrol` system user
- Set up Python virtual environment
- Copy application files to `/opt/wancontrol`
- Configure passwordless sudo for network commands
- Install systemd service
- Set up log rotation

## Step 2: Generate Secret Key

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Copy the output - you'll need it in the next step.

## Step 3: Discover Interfaces

```bash
python3 /opt/wancontrol/discover_interfaces.py
```

Example output:
```
┌────────┬──────────────┬────────────┬──────────────┬──────────────┐
│ Name   │ IPv4         │ Gateway    │ Carrier      │ Speed (Mb/s) │
├────────┼──────────────┼────────────┼──────────────┼──────────────┤
│ eth0   │ 192.168.1.10 │ 192.168.1.1│ yes          │ 1000         │
│ eth1   │ 10.0.0.5     │ 10.0.0.1   │ yes          │ 100          │
└────────┴──────────────┴────────────┴──────────────┴──────────────┘
```

## Step 4: Configure WANControl

Edit the configuration file:

```bash
sudo nano /etc/wancontrol/config.yaml
```

Minimal configuration example:

```yaml
interfaces:
  - name: "eth0"
    label: "Primary Fiber"
    expected_speed_mbps: 100
    gateway: "192.168.1.1"
    routing_table_id: 100

  - name: "eth1"
    label: "Backup DSL"
    expected_speed_mbps: 25
    gateway: "10.0.0.1"
    routing_table_id: 101

wan_mode: "failover"  # or "load_balance"

probes:
  interval_sec: 1
  dns_targets:
    - "8.8.8.8"
    - "1.1.1.1"
  icmp_targets:
    - "8.8.8.8"
  http_targets:
    - "http://connectivitycheck.gstatic.com/generate_204"

scoring:
  hard_fail_threshold: 20

server:
  host: "0.0.0.0"
  port: 5000
  secret_key: "PASTE_YOUR_SECRET_KEY_HERE"

db_path: "/var/lib/wancontrol/wan.db"
log_dir: "/var/lib/wancontrol/logs"
```

## Step 5: Start the Service

```bash
sudo systemctl start wancontrol
sudo systemctl enable wancontrol
```

## Step 6: Get Admin Password

On first startup, WANControl generates a temporary admin password:

```bash
journalctl -u wancontrol -n 50 --no-pager
```

Look for:
```
┌────────────────────────────────────────────────────────────┐
│  FIRST RUN SETUP                                           │
│  Admin username: admin                                     │
│  Admin password: <random_password>                         │
└────────────────────────────────────────────────────────────┘
```

## Step 7: Access the Dashboard

Open your browser and navigate to:

```
http://<your-server-ip>:5000
```

Log in with:
- **Username**: `admin`
- **Password**: (from previous step)

**Important**: Change the admin password immediately after first login!

## Step 8: Verify Operation

### Check Service Status

```bash
sudo systemctl status wancontrol
```

### View Live Logs

```bash
journalctl -u wancontrol -f
```

### Test API

```bash
# Health check (no auth required)
curl http://localhost:5000/api/health

# Login to get token
curl -X POST http://localhost:5000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<your-password>"}'

# Get status (use token from login response)
curl http://localhost:5000/api/status \
  -H "Authorization: Bearer <your-token>"
```

### Check Network Routes

```bash
# Show current default route
ip route show default

# Show all routing tables
ip route show table all
```

## Next Steps

### Configure Webhooks (Optional)

Set up alerts to be sent to notification services:

```yaml
alerting:
  enabled: true
  webhooks:
    - url: "https://ntfy.sh/your-topic"
      method: POST
      headers:
        Title: "WANControl Alert"
      on_events:
        - "link_down"
        - "link_up"
        - "gateway_switch"
```

### Create Additional Users

Through the dashboard:
1. Go to Settings → Users
2. Click "Add User"
3. Enter username, password, and role

Or via API:

```bash
curl -X POST http://localhost:5000/api/users \
  -H "Authorization: Bearer <admin-token>" \
  -H "Content-Type: application/json" \
  -d '{"username":"operator","password":"secure123","role":"operator"}'
```

### Create API Token for Automation

```bash
curl -X POST http://localhost:5000/api/tokens \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"label":"Monitoring Script","expires_in_days":365}'
```

Save the returned token securely - it cannot be retrieved again!

## Common Tasks

### Reload Configuration

After editing `/etc/wancontrol/config.yaml`:

```bash
# Via API
curl -X POST http://localhost:5000/api/config/reload \
  -H "Authorization: Bearer <token>"

# Or send SIGHUP
sudo kill -HUP $(pgrep -f "python -m wancontrol")
```

### View Metrics

```bash
curl http://localhost:5000/api/metrics/latest \
  -H "Authorization: Bearer <token>"
```

### Check Events

```bash
curl http://localhost:5000/api/events/switches \
  -H "Authorization: Bearer <token>"
```

## Troubleshooting

### Service Won't Start

```bash
# Check logs
journalctl -u wancontrol -n 100 --no-pager

# Verify config syntax
python3 -c "from wancontrol.config import AppConfig; AppConfig.load('/etc/wancontrol/config.yaml')"

# Check if port is in use
ss -tlnp | grep 5000
```

### Can't Access Dashboard

- Ensure firewall allows port 5000
- Check if service is running: `sudo systemctl status wancontrol`
- Verify bind address in config: `server.host` should be `0.0.0.0` for remote access

### Routes Not Changing

- Verify sudo configuration: `visudo -c -f /etc/sudoers.d/wancontrol`
- Test sudo access: `sudo -u wancontrol ip route show`
- Check logs for permission errors

## Learning More

- [Full Documentation](README.md) - Complete reference
- [API Reference](README.md#api-reference) - All endpoints
- [Configuration Guide](README.md#configuration-reference) - All options
- [Troubleshooting](README.md#troubleshooting) - Common issues

---

**Congratulations!** WANControl v2 is now managing your dual-WAN setup. Monitor the dashboard for real-time status and health metrics.
