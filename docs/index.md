# WANControl v2 Documentation

Welcome to the official WANControl v2 documentation. This directory contains comprehensive guides for installing, configuring, and operating WANControl.

## 📚 Documentation Files

| Document | Description | Audience |
|----------|-------------|----------|
| **[README.md](README.md)** | Complete reference manual - all features explained | Everyone |
| **[quickstart.md](quickstart.md)** | Get started in 10 minutes - installation to first login | New users |
| **[api-reference.md](api-reference.md)** | REST API documentation - all endpoints with examples | Developers |
| **[wiki.md](wiki.md)** | Wiki index - navigation and quick links | Everyone |

## 🚀 Quick Start

New to WANControl? Start here:

1. Read the **[Quick Start Guide](quickstart.md)** for installation
2. Review the **[Configuration Reference](README.md#configuration-reference)** 
3. Access the dashboard at `http://your-server:5000`
4. Check the **[API Reference](api-reference.md)** for automation

## 📖 Key Topics

### Installation & Setup
- [Quick Install (10 min)](quickstart.md#step-1-installation)
- [Manual Installation](README.md#installation-guide)
- [Interface Discovery](quickstart.md#step-3-discover-interfaces)

### Configuration
- [Full Config Example](README.md#full-configuration-example)
- [Environment Variables](README.md#environment-variable-overrides)
- [Hot Reloading](README.md#hot-reloading)

### API & Automation
- [Complete API Reference](api-reference.md)
- [Authentication](api-reference.md#authentication)
- [Server-Sent Events](api-reference.md#server-sent-events)

### Operations
- [Deployment Checklist](README.md#production-checklist)
- [Troubleshooting](README.md#troubleshooting)
- [Backup Strategy](README.md#backup-strategy)

### Development
- [Dev Environment Setup](README.md#setting-up-development-environment)
- [Running Tests](README.md#running-tests)
- [Contributing](README.md#contributing)

## 🔧 Support

- **GitHub Issues**: https://github.com/aditya-tripcuro/SDWANcontrol/issues
- **Logs**: `journalctl -u wancontrol -f`
- **Health Check**: `curl http://localhost:5000/api/health`

## 📋 Version

**Current:** v2.0.0

---

For the complete wiki with navigation and quick links, see **[wiki.md](wiki.md)**.
