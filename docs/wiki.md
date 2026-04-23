# WANControl v2 Documentation Wiki

Welcome to the WANControl v2 documentation wiki. This comprehensive guide covers everything from installation to advanced configuration.

## 📚 Documentation Index

### Getting Started

- **[Quick Start Guide](quickstart.md)** - Get up and running in 10 minutes
- **[Full Documentation](README.md)** - Complete reference manual

### Core Documentation

- **[Installation Guide](README.md#installation-guide)** - Step-by-step installation instructions
- **[Configuration Reference](README.md#configuration-reference)** - All configuration options explained
- **[API Reference](api-reference.md)** - Complete REST API documentation

### Technical Guides

- **[Architecture Overview](README.md#architecture-overview)** - System design and components
- **[Database Schema](README.md#database-schema)** - SQLite database structure
- **[Network Operations](README.md#network-operations)** - How network management works
- **[Monitoring & Health Checks](README.md#monitoring--health-checks)** - Probe system and scoring
- **[Controller State Machine](README.md#controller-state-machine)** - Control logic and decision making

### Operations

- **[Deployment Guide](README.md#deployment-guide)** - Production deployment checklist
- **[Troubleshooting](README.md#troubleshooting)** - Common issues and solutions
- **[Development Guide](README.md#development-guide)** - Setting up development environment

### Frontend

- **[Dashboard Guide](README.md#frontend-dashboard)** - Using the web interface
- **[Frontend Development](README.md#development-guide)** - Building the React UI

---

## 🚀 Quick Links

### Most Used Pages

| Topic | Link |
|-------|------|
| Install | [Quick Start](quickstart.md#step-1-installation) |
| Configure | [Config Reference](README.md#configuration-reference) |
| API Docs | [API Reference](api-reference.md) |
| Troubleshoot | [Common Issues](README.md#troubleshooting) |

### Common Tasks

| Task | Documentation |
|------|---------------|
| Generate secret key | [Quick Start](quickstart.md#step-2-generate-secret-key) |
| Discover interfaces | [Quick Start](quickstart.md#step-3-discover-interfaces) |
| Configure webhooks | [Config Reference](README.md#alerting) |
| Create users | [API Reference](api-reference.md#post-apiusers) |
| Create API tokens | [API Reference](api-reference.md#post-apitokens) |
| Reload config | [Quick Start](quickstart.md#reload-configuration) |

---

## 📖 Table of Contents

### Introduction

- [What is WANControl?](README.md#introduction)
- [Key Features](README.md#introduction)
- [System Requirements](README.md#introduction)

### Installation & Setup

- [Quick Installation](quickstart.md#step-1-installation)
- [Manual Installation](README.md#installation-guide)
- [Building Frontend](README.md#building-frontend-optional)
- [Verification](quickstart.md#step-8-verify-operation)

### Configuration

- [Configuration File Location](README.md#configuration-file-location)
- [Full Example](README.md#full-configuration-example)
- [Interfaces](README.md#interfaces-required)
- [WAN Mode](README.md#wan_mode-required)
- [Probes](README.md#probes)
- [Scoring](README.md#scoring)
- [Alerting & Webhooks](README.md#alerting)
- [Environment Variables](README.md#environment-variable-overrides)
- [Hot Reloading](README.md#hot-reloading)

### API Reference

- [Base URL & Authentication](api-reference.md#authentication)
- [Auth Endpoints](api-reference.md#authentication-endpoints)
- [Status Endpoints](api-reference.md#status-endpoints)
- [Metrics Endpoints](api-reference.md#metrics-endpoints)
- [Events Endpoints](api-reference.md#events-endpoints)
- [Alerts Endpoints](api-reference.md#alerts-endpoints)
- [User Management](api-reference.md#user-management-endpoints)
- [Token Management](api-reference.md#api-token-management)
- [Configuration Endpoints](api-reference.md#configuration-endpoints)
- [Database Management](api-reference.md#database-management-endpoints)
- [Server-Sent Events](api-reference.md#server-sent-events)

### Architecture

- [Component Diagram](README.md#architecture-overview)
- [Module Responsibilities](README.md#module-responsibilities)
- [Execution Flow](README.md#execution-flow)

### Database

- [Schema Overview](README.md#database-schema)
- [Tables](README.md#tables)
- [Migrations](README.md#migrations)
- [Retention Policies](README.md#retention-policies)
- [Backup & Restore](README.md#backup-and-restore)

### Network Operations

- [Dry Run Mode](README.md#dry-run-mode)
- [Interface Information](README.md#interface-information)
- [Health Probes](README.md#health-probes)
- [Route Management](README.md#route-management)
- [Policy Routing](README.md#policy-routing)
- [Sudo Configuration](README.md#sudo-configuration)

### Monitoring

- [Probe Types](README.md#probe-types)
- [Scoring Algorithm](README.md#scoring-algorithm)
- [State Transitions](README.md#state-transitions)
- [Parallel Execution](README.md#parallel-probe-execution)

### Controller

- [Controller Modes](README.md#controller-modes)
- [WAN States](README.md#wan-states)
- [Failover Logic](README.md#failover-mode-logic)
- [Load Balance Logic](README.md#load-balance-mode-logic)
- [Master/Standby Election](README.md#masterstandby-election)
- [Alert Conditions](README.md#alert-conditions)

### Deployment

- [Production Checklist](README.md#production-checklist)
- [Firewall Configuration](README.md#firewall-configuration)
- [High Availability](README.md#high-availability-setup)
- [Monitoring Integration](README.md#monitoring-integration)
- [Backup Strategy](README.md#backup-strategy)
- [Disaster Recovery](README.md#disaster-recovery)

### Troubleshooting

- [Service Won't Start](README.md#service-wont-start)
- [Routes Not Applying](README.md#routes-not-applying)
- [High CPU Usage](README.md#high-cpu-usage)
- [Database Corruption](README.md#database-corruption)
- [Webhook Issues](README.md#webhook-not-delivering)
- [Authentication Problems](README.md#jwt-authentication-failing)
- [Log Analysis](README.md#log-analysis)

### Development

- [Dev Environment Setup](README.md#setting-up-development-environment)
- [Running Tests](README.md#running-tests)
- [Code Style](README.md#code-style)
- [Adding Features](README.md#adding-new-features)
- [Debugging](README.md#debugging)
- [Contributing](README.md#contributing)

---

## 🔧 Support & Resources

### Getting Help

- **GitHub Issues**: https://github.com/aditya-tripcuro/SDWANcontrol/issues
- **Documentation**: You're reading it!
- **Logs**: `journalctl -u wancontrol -f`

### Useful Commands

```bash
# Check service status
sudo systemctl status wancontrol

# View logs
journalctl -u wancontrol -f

# Test API
curl http://localhost:5000/api/health

# Reload configuration
sudo kill -HUP $(pgrep -f "python -m wancontrol")

# Discover interfaces
python3 /opt/wancontrol/discover_interfaces.py
```

### External Resources

- **Flask Documentation**: https://flask.palletsprojects.com/
- **React Documentation**: https://react.dev/
- **SQLite Documentation**: https://www.sqlite.org/docs.html
- **iproute2 Documentation**: https://man7.org/linux/man-pages/man8/ip.8.html

---

## 📝 Version Information

**Current Version:** 2.0.0

**Release Date:** 2024

**Key Changes in v2:**
- Complete rewrite with modern architecture
- React frontend dashboard
- SQLite persistence layer
- JWT authentication
- Role-based access control
- Hot-reloadable configuration
- Comprehensive API

---

## 🎯 Next Steps

### New Users

1. Start with the **[Quick Start Guide](quickstart.md)**
2. Read about **[Configuration](README.md#configuration-reference)**
3. Explore the **[Dashboard](README.md#frontend-dashboard)**
4. Review **[Troubleshooting](README.md#troubleshooting)** if needed

### Developers

1. Set up **[Development Environment](README.md#setting-up-development-environment)**
2. Read the **[Architecture Overview](README.md#architecture-overview)**
3. Review the **[API Reference](api-reference.md)**
4. Check out **[Contributing Guidelines](README.md#contributing)**

### Administrators

1. Follow the **[Deployment Guide](README.md#deployment-guide)**
2. Configure **[Backups](README.md#backup-strategy)**
3. Set up **[Monitoring](README.md#monitoring-integration)**
4. Review **[Security Best Practices](README.md#firewall-configuration)**

---

*Documentation for WANControl v2.0.0*

Last updated: 2024
