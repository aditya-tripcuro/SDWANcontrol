# WANControl v2 - Claude.md

## Project Overview

WANControl v2 is an industrial-grade SD-WAN (Software-Defined Wide Area Network) controller for Linux systems with multiple WAN interfaces. It provides intelligent traffic management through automated failover and load balancing.

**Repository**: https://github.com/aditya-tripcuro/SDWANcontrol

**Core Purpose**: Monitor multiple internet connections and automatically route traffic through the healthiest path.

---

## Quick Reference

### Key Commands

```bash
# Install
sudo ./install.sh

# Check status
sudo systemctl status wancontrol

# View logs
journalctl -u wancontrol -f

# Edit config
sudo nano /etc/wancontrol/config.yaml

# Restart service
sudo systemctl restart wancontrol

# Discover interfaces
python3 /opt/wancontrol/discover_interfaces.py
```

### Important Paths

| Component | Path |
|-----------|------|
| Config | `/etc/wancontrol/config.yaml` |
| Database | `/var/lib/wancontrol/wan.db` |
| Application | `/opt/wancontrol/` |
| Logs | `/var/lib/wancontrol/logs/` |
| Service | `/etc/systemd/system/wancontrol.service` |

### Default Ports

- **Web Dashboard/API**: Port 5000

---

## Architecture Summary

### Components

1. **Flask API** (`wancontrol/app.py`) - REST API + serves React frontend
2. **Controller** (`wancontrol/controller.py`) - Lifecycle management
3. **Network Layer** (`wancontrol/network.py`) - Routing table/policy management
4. **Database** (`wancontrol/database.py`) - SQLite with WAL mode
5. **Auth** (`wancontrol/auth.py`) - JWT + API token authentication
6. **Config** (`wancontrol/config.py`) - YAML configuration loader
7. **Frontend** (`frontend/`) - React + TypeScript + Tailwind CSS

### Operational Modes

- **failover**: One active WAN, automatic switch on failure
- **load_balance**: All healthy WANs active, weighted distribution

### Health Probing

- **ICMP**: Ping tests (5 packets, configurable)
- **DNS**: Query multiple DNS servers
- **HTTP**: Fetch connectivity check URLs
- **Interval**: 1 second (configurable)

### Scoring Algorithm

```
base_score = 100
final_score = base_score 
            - (latency_ms × latency_penalty_per_ms)
            - (loss_pct × loss_penalty_per_percent)
            - (dns_fail ? dns_fail_penalty : 0)
            - (http_fail ? http_fail_penalty : 0)
```

---

## Configuration Essentials

### Minimal Working Config

```yaml
interfaces:
  - name: "enp2s0"
    label: "Primary"
    expected_speed_mbps: 1000
    gateway: "192.168.1.1"
    routing_table_id: 100
    
  - name: "enp3s0"
    label: "Backup"
    expected_speed_mbps: 500
    gateway: "192.168.2.1"
    routing_table_id: 101

wan_mode: "failover"  # or "load_balance"

server:
  host: "0.0.0.0"
  port: 5000
  secret_key: "<generate-with-secrets.token_hex(32)>"
```

### Critical Settings

| Setting | Purpose | Default |
|---------|---------|---------|
| `wan_mode` | Operating mode | `load_balance` |
| `probes.interval_sec` | Health check frequency | 1 |
| `scoring.hard_fail_threshold` | Failure threshold | 20 |
| `scoring.hysteresis_switch_to_backup` | Failover hysteresis | 25 |
| `server.secret_key` | JWT signing key | Must generate |

---

## API Quick Reference

### Authentication

```bash
# Login
curl -X POST http://localhost:5000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"..."}'

# Use token
curl -H "Authorization: Bearer <token>" http://localhost:5000/api/status

# Or API token
curl -H "X-API-Token: <raw_token>" http://localhost:5000/api/status
```

### Key Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/health` | GET | No | Liveness check |
| `/api/status` | GET | Viewer | Controller status |
| `/api/metrics` | GET | Viewer | Historical metrics |
| `/api/events/switches` | GET | Viewer | Switch events |
| `/api/alerts` | GET | Viewer | Recent alerts |
| `/api/config/reload` | POST | Admin | Reload config |
| `/api/stream` | GET | Viewer | SSE real-time feed |

### Role Hierarchy

- **viewer** (1): Read-only access
- **operator** (2): Can resolve alerts
- **admin** (3): Full control

---

## Development

### Tech Stack

**Backend:**
- Python 3.10+
- Flask 3.1.0
- SQLite with WAL mode
- bcrypt for passwords
- PyJWT for tokens

**Frontend:**
- React 18+
- TypeScript
- Vite
- Tailwind CSS
- Recharts

### Running Locally

```bash
# Development mode (no root needed)
WANCONTROL_DRY_RUN=1 python -m wancontrol

# Frontend development
cd frontend
npm install
npm run dev
```

### Testing

```bash
# Unit tests
pytest tests/unit/

# Integration tests
pytest tests/integration/

# With coverage
pytest --cov=wancontrol
```

### Code Style

- Type hints required
- Docstrings for all public functions
- Logging via `logger` with `component` extra
- Error handling with specific exceptions

---

## Deployment

### System Requirements

- Debian 11+ or Ubuntu 20.04+
- Python 3.10+
- 2+ WAN interfaces
- Packages: `iproute2`, `iputils-ping`, `bind9-dnsutils`, `curl`

### Installation Checklist

- [ ] Run `sudo ./install.sh`
- [ ] Generate secret key in config
- [ ] Configure interfaces with correct gateways
- [ ] Set appropriate `wan_mode`
- [ ] Verify sudoers: `sudo visudo -c -f /etc/sudoers.d/wancontrol`
- [ ] Start service: `sudo systemctl start wancontrol`
- [ ] Get admin password from logs
- [ ] Change admin password after first login

### Capabilities Required

The service needs:
- `CAP_NET_ADMIN`: Modify routing tables
- `CAP_NET_RAW`: Bind sockets to interfaces

Configured in systemd unit via `AmbientCapabilities`.

---

## Troubleshooting Quick Fixes

### Service Won't Start

```bash
# Check logs
journalctl -u wancontrol --since "10 minutes ago"

# Common issue: missing secret key
python3 -c "import secrets; print(secrets.token_hex(32))"
# Edit /etc/wancontrol/config.yaml and replace secret_key
```

### No Metrics Appearing

```bash
# Test probes manually
ping -I enp2s0 8.8.8.8
dig @8.8.8.8 google.com

# Check interface config matches system
ip addr show
cat /etc/wancontrol/config.yaml
```

### Dashboard Inaccessible

```bash
# Check service
sudo systemctl status wancontrol

# Check firewall
sudo ufw allow 5000/tcp

# Verify port
sudo netstat -tlnp | grep 5000
```

### Routing Issues

```bash
# View current routes
ip route show

# View policy rules
ip rule list

# Restore routes (emergency)
sudo python3 /opt/wancontrol/wancontrol/network.py --restore-routes
```

---

## Database Schema

### Tables

- `metrics`: Probe results (latency, loss, score)
- `switch_events`: WAN failover events
- `controller_events`: System event log
- `state`: Key-value runtime state
- `users`: User accounts
- `api_tokens`: API tokens (SHA-256 hashed)
- `alerts`: System alerts

### Retention Defaults

- Metrics: 72 hours
- Events: 30 days
- Prune interval: 60 minutes

---

## Security Considerations

### Authentication

- Passwords: bcrypt with 12 rounds
- JWT: HS256 algorithm, configurable expiry (default 24h)
- API tokens: SHA-256 hashed in database
- Minimum password length: 12 characters

### Authorization

- All endpoints except `/health` and `/auth/login` require auth
- Role-based access control enforced
- Tokens never logged or exposed in errors

### Network Security

- Process runs as `wancontrol` user (not root)
- Capabilities restricted via systemd
- Sudoers fragment limits allowed commands
- Socket binding requires CAP_NET_RAW

---

## File Structure

```
/workspace/
├── wancontrol/           # Python package
│   ├── __init__.py
│   ├── __main__.py      # Entry point
│   ├── app.py           # Flask API
│   ├── auth.py          # Authentication
│   ├── config.py        # Configuration
│   ├── controller.py    # Lifecycle
│   ├── database.py      # SQLite layer
│   ├── logging_config.py
│   ├── monitor.py       # Health probing
│   ├── network.py       # Network ops
│   └── watchdog.py
├── frontend/            # React application
│   ├── src/
│   ├── tests/
│   └── package.json
├── tests/
│   ├── unit/
│   └── integration/
├── deploy/              # Systemd, sudoers, logrotate
├── config.yaml          # Default config
├── requirements.txt
├── install.sh
├── uninstall.sh
├── discover_interfaces.py
├── README.md
├── DESIGN.md
├── WIKI.md              # Comprehensive wiki
├── DOCUMENTATION.md     # Technical docs
└── NOVICE_GUIDE.md      # Beginner guide
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `WANCONTROL_CONFIG` | `/etc/wancontrol/config.yaml` | Config file path |
| `WANCONTROL_DRY_RUN` | `0` | Skip network operations |

---

## Common Workflows

### Adding New Interface

1. Run discovery: `python3 /opt/wancontrol/discover_interfaces.py`
2. Note interface name and gateway
3. Edit config: add new interface block
4. Assign unique `routing_table_id`
5. Reload: `sudo systemctl restart wancontrol`

### Creating Automation Token

1. Login to dashboard
2. Navigate to Config → API Tokens
3. Click "Create Token"
4. Copy token immediately (shown once)
5. Use in scripts: `curl -H "X-API-Token: <token>" ...`

### Investigating Failover

1. Check events: `/api/events/switches`
2. Review metrics before/after: `/api/metrics?interface=<name>`
3. Examine controller logs: `journalctl -u wancontrol`
4. Verify scoring thresholds in config

### Backup & Restore

```bash
# Backup
sudo cp /var/lib/wancontrol/wan.db ~/backup.$(date +%F).db

# Restore (stop service first)
sudo systemctl stop wancontrol
sudo cp ~/backup.db /var/lib/wancontrol/wan.db
sudo systemctl start wancontrol
```

---

## Performance Tuning

### High-Latency Networks

```yaml
scoring:
  latency_penalty_per_ms: 0.1  # Reduce from 0.3
  hard_fail_threshold: 10      # More tolerant
```

### Unstable Connections

```yaml
scoring:
  hysteresis_switch_to_backup: 30   # Increase from 25
  hysteresis_return_to_primary: 15  # Increase from 10
```

### Resource-Constrained Systems

```yaml
probes:
  icmp_count: 3         # Reduce from 5
  interval_sec: 2       # Reduce from 1
  
retention:
  metrics_hours: 24     # Reduce from 72
```

---

## Monitoring & Alerting

### Built-in Alerts

- Link down/up
- Gateway switch
- Interface added/removed from pool
- Controller errors

### Webhook Integration

Configure in `config.yaml`:

```yaml
alerting:
  enabled: true
  webhooks:
    - url: "http://ntfy.sh/wancontrol"
      method: POST
      headers:
        Title: "WANControl Alert"
      on_events:
        - "link_down"
        - "gateway_switch"
```

### External Monitoring

Poll these endpoints:
- `/api/health` - Service alive
- `/api/status` - Overall health
- `/api/metrics/latest` - Current scores

---

## Version Information

- **Current Version**: 2.0
- **Schema Version**: 1
- **Python**: 3.10+
- **Node**: 18+ (frontend dev)

---

## Support Resources

- **Wiki**: `WIKI.md` - Comprehensive documentation
- **Technical Docs**: `DOCUMENTATION.md` - Full API reference
- **Beginner Guide**: `NOVICE_GUIDE.md` - Step-by-step tutorial
- **Design System**: `DESIGN.md` - UI/UX specifications
- **README**: `README.md` - Quick start guide

---

## Contributing Guidelines

When working with this codebase:

1. **Type Safety**: Always use type hints
2. **Error Handling**: Log with component context
3. **Testing**: Add tests for new functionality
4. **Documentation**: Update relevant docs
5. **Security**: Never commit secrets or keys
6. **Performance**: Consider impact on probe loop timing

---

## License

See LICENSE file in repository root.
