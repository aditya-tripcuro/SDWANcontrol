# WANControl v2 - API Reference

Complete reference for the WANControl REST API.

## Base URL

```
http://<host>:5000/api
```

## Authentication

### JWT Bearer Token (Interactive Sessions)

```bash
Authorization: Bearer <jwt_token>
```

### API Token (Automation)

```bash
X-API-Token: <raw_token>
```

---

## Authentication Endpoints

### POST /api/auth/login

Authenticate and receive JWT access token.

**Request:**
```json
{
  "username": "string",
  "password": "string"
}
```

**Response (200 OK):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 86400
}
```

**Error Responses:**

| Code | Message | Description |
|------|---------|-------------|
| 401 | `invalid_credentials` | Wrong username or password |
| 403 | `user_inactive` | Account has been deactivated |

---

### POST /api/auth/logout

Invalidate current session. Client should remove stored token.

**Response (200 OK):**
```json
{
  "message": "Logged out successfully"
}
```

---

### POST /api/auth/change-password

Change authenticated user's password.

**Requires:** Authentication

**Request:**
```json
{
  "current_password": "string",
  "new_password": "string"
}
```

**Requirements:**
- New password must be at least 12 characters

**Response (200 OK):**
```json
{
  "message": "Password changed successfully"
}
```

**Error Responses:**

| Code | Message | Description |
|------|---------|-------------|
| 401 | `invalid_credentials` | Current password is incorrect |
| 400 | `weak_password` | New password too short |

---

## Status Endpoints

### GET /api/health

Liveness check and version information.

**No authentication required.**

**Response (200 OK):**
```json
{
  "status": "healthy",
  "version": "2.0.0"
}
```

---

### GET /api/status

Overall controller status.

**Requires:** Authentication

**Response (200 OK):**
```json
{
  "mode": "RUNNING",
  "wan_mode": "load_balance",
  "active_interface": "wan0",
  "nexthop_pool": ["wan0", "wan1"],
  "last_update": 1698765432.123,
  "uptime_seconds": 3600.5
}
```

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `mode` | string | Controller mode (STARTING, RUNNING, MAINTENANCE, KILLED) |
| `wan_mode` | string | Routing mode (failover, load_balance) |
| `active_interface` | string|null | Currently active interface (failover mode) |
| `nexthop_pool` | array | List of interfaces in load balance pool |
| `last_update` | float | Unix timestamp of last state update |
| `uptime_seconds` | float | Seconds since controller started |

---

### GET /api/status/interfaces

Per-interface status summary.

**Requires:** Authentication

**Response (200 OK):**
```json
{
  "interfaces": [
    {
      "name": "wan0",
      "label": "Fiber Primary",
      "state": "STABLE",
      "score": 95.5,
      "in_pool": true,
      "gateway": "192.168.1.1",
      "ip_address": "192.168.1.100"
    }
  ]
}
```

**Interface Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | System interface name |
| `label` | string | Human-readable label |
| `state` | string | STABLE, DEGRADED, FAILED, SWITCHING |
| `score` | float | Current health score (0-100) |
| `in_pool` | boolean | Included in load balance pool |
| `gateway` | string | Configured gateway IP |
| `ip_address` | string|null | Current interface IP address |

---

## Metrics Endpoints

### GET /api/metrics

Historical metrics with optional filtering.

**Requires:** Authentication

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `interface` | string | - | Filter by interface name |
| `start` | float | - | Start timestamp (Unix epoch) |
| `end` | float | - | End timestamp (Unix epoch) |
| `limit` | integer | 1000 | Maximum records to return |

**Response (200 OK):**
```json
{
  "metrics": [
    {
      "id": 1,
      "interface": "wan0",
      "timestamp": 1698765432.123,
      "latency_ms": 12.5,
      "jitter_ms": 1.2,
      "loss_pct": 0.0,
      "dns_ok": true,
      "http_ok": true,
      "score": 95.5
    }
  ]
}
```

**Metric Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | Database record ID |
| `interface` | string | Interface name |
| `timestamp` | float | Unix timestamp |
| `latency_ms` | float | Average ICMP latency |
| `jitter_ms` | float | Latency variance |
| `loss_pct` | float | Packet loss percentage |
| `dns_ok` | boolean | DNS resolution successful |
| `http_ok` | boolean | HTTP probe successful |
| `score` | float | Calculated health score |

---

### GET /api/metrics/latest

Latest metric for each interface.

**Requires:** Authentication

**Response (200 OK):**
```json
{
  "latest": [
    {
      "interface": "wan0",
      "timestamp": 1698765432.123,
      "latency_ms": 12.5,
      "jitter_ms": 1.2,
      "loss_pct": 0.0,
      "dns_ok": true,
      "http_ok": true,
      "score": 95.5
    }
  ]
}
```

---

## Events Endpoints

### GET /api/events/switches

Recent failover and pool membership events.

**Requires:** Authentication

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | integer | 100 | Maximum records to return |

**Response (200 OK):**
```json
{
  "events": [
    {
      "id": 1,
      "timestamp": 1698765432.123,
      "from_interface": "wan0",
      "to_interface": "wan1",
      "reason": "score_below_threshold",
      "triggered_by": "controller",
      "score_before": 18.5,
      "score_after": 88.2
    }
  ]
}
```

**Event Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | Database record ID |
| `timestamp` | float | Unix timestamp |
| `from_interface` | string|null | Previous active interface |
| `to_interface` | string | New active interface |
| `reason` | string | Reason for switch |
| `triggered_by` | string | What triggered the switch |
| `score_before` | float | Score before switch |
| `score_after` | float | Score after switch |

---

### GET /api/events/controller

Controller activity log.

**Requires:** Authentication

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `level` | string | - | Filter by level (INFO, WARNING, ERROR) |
| `limit` | integer | 100 | Maximum records to return |

**Response (200 OK):**
```json
{
  "events": [
    {
      "id": 1,
      "timestamp": 1698765432.123,
      "level": "INFO",
      "component": "controller",
      "message": "Controller started in load_balance mode",
      "user_id": null
    }
  ]
}
```

---

## Alerts Endpoints

### GET /api/alerts

Recent alerts.

**Requires:** Authentication

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `unresolved_only` | boolean | false | Only unresolved alerts |
| `limit` | integer | 100 | Maximum records to return |

**Response (200 OK):**
```json
{
  "alerts": [
    {
      "id": 1,
      "timestamp": 1698765432.123,
      "level": "WARNING",
      "title": "Interface Degraded",
      "body": "wan0 score dropped below threshold",
      "resolved_at": null,
      "notified": true
    }
  ]
}
```

**Alert Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | Database record ID |
| `timestamp` | float | Unix timestamp |
| `level` | string | INFO, WARNING, ERROR, CRITICAL |
| `title` | string | Alert title |
| `body` | string | Alert description |
| `resolved_at` | float|null | Resolution timestamp |
| `notified` | boolean | Webhook notification sent |

---

### POST /api/alerts/:alert_id/resolve

Mark an alert as resolved.

**Requires:** Authentication (operator or admin role)

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `alert_id` | integer | Alert ID to resolve |

**Response (200 OK):**
```json
{
  "message": "Alert resolved successfully"
}
```

---

## User Management Endpoints

**All user management endpoints require admin role.**

### GET /api/users

List all users.

**Requires:** Admin role

**Response (200 OK):**
```json
{
  "users": [
    {
      "id": 1,
      "username": "admin",
      "role": "admin",
      "created_at": 1698765432.123,
      "last_login": 1698769032.456,
      "is_active": true
    }
  ]
}
```

---

### POST /api/users

Create a new user.

**Requires:** Admin role

**Request:**
```json
{
  "username": "string",
  "password": "string",
  "role": "viewer|operator|admin"
}
```

**Requirements:**
- Username must be unique
- Password minimum 12 characters
- Role must be viewer, operator, or admin

**Response (201 Created):**
```json
{
  "user_id": 2,
  "message": "User created successfully"
}
```

**Error Responses:**

| Code | Message | Description |
|------|---------|-------------|
| 400 | `username_taken` | Username already exists |
| 400 | `weak_password` | Password too short |
| 400 | `invalid_role` | Invalid role specified |

---

### GET /api/users/:user_id

Get user details.

**Requires:** Admin role

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `user_id` | integer | User ID |

**Response (200 OK):**
```json
{
  "id": 1,
  "username": "admin",
  "role": "admin",
  "created_at": 1698765432.123,
  "last_login": 1698769032.456,
  "is_active": true
}
```

**Error Responses:**

| Code | Message | Description |
|------|---------|-------------|
| 404 | `user_not_found` | User ID does not exist |

---

### POST /api/users/:user_id/deactivate

Deactivate a user account.

**Requires:** Admin role

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `user_id` | integer | User ID |

**Response (200 OK):**
```json
{
  "message": "User deactivated successfully"
}
```

**Notes:**
- Cannot deactivate your own account
- Deactivated users cannot log in

---

### POST /api/users/:user_id/role

Update user role.

**Requires:** Admin role

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `user_id` | integer | User ID |

**Request:**
```json
{
  "role": "viewer|operator|admin"
}
```

**Response (200 OK):**
```json
{
  "message": "User role updated successfully"
}
```

---

## API Token Management

### GET /api/tokens

List API tokens for authenticated user.

**Requires:** Authentication

**Response (200 OK):**
```json
{
  "tokens": [
    {
      "id": 1,
      "user_id": 1,
      "label": "Monitoring Script",
      "created_at": 1698765432.123,
      "last_used": 1698769032.456,
      "expires_at": null,
      "is_revoked": false
    }
  ]
}
```

**Token Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | Token ID |
| `user_id` | integer | Owner user ID |
| `label` | string | Token description |
| `created_at` | float | Creation timestamp |
| `last_used` | float|null | Last usage timestamp |
| `expires_at` | float|null | Expiry timestamp |
| `is_revoked` | boolean | Token revoked status |

---

### POST /api/tokens

Create a new API token.

**Requires:** Authentication

**Request:**
```json
{
  "label": "string",
  "expires_in_days": 365
}
```

**Request Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `label` | string | Yes | Token description |
| `expires_in_days` | integer | No | Days until expiry (null = never) |

**Response (201 Created):**
```json
{
  "token_id": 2,
  "token": "raw_token_value_here_abc123",
  "message": "Token created successfully. Store this token securely; it cannot be retrieved again."
}
```

**Important:** The raw token is shown only once. Store it securely.

---

### DELETE /api/tokens/:token_id

Revoke an API token.

**Requires:** Authentication (admin can revoke any token)

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `token_id` | integer | Token ID |

**Response (200 OK):**
```json
{
  "message": "Token revoked successfully"
}
```

**Notes:**
- Users can revoke their own tokens
- Admins can revoke any token
- Revoked tokens cannot be restored

---

## Configuration Endpoints

### GET /api/config/raw

Get raw configuration (sanitized).

**Requires:** Authentication

**Response (200 OK):**
```json
{
  "config": {
    "interfaces": [...],
    "wan_mode": "load_balance",
    "probes": {...},
    "scoring": {...},
    ...
  }
}
```

**Note:** Sensitive values (like secret_key) are omitted.

---

### POST /api/config/reload

Reload configuration from disk.

**Requires:** Operator or admin role

**Response (200 OK):**
```json
{
  "message": "Configuration reloaded successfully"
}
```

**Notes:**
- Reads `/etc/wancontrol/config.yaml`
- Most settings apply immediately
- `db_path` requires restart to change

---

### PUT /api/config/interfaces

Update interface configuration dynamically.

**Requires:** Operator or admin role

**Request:**
```json
{
  "interfaces": [
    {
      "name": "wan0",
      "label": "Fiber Primary",
      "expected_speed_mbps": 100,
      "gateway": "192.168.1.1",
      "routing_table_id": 100
    }
  ]
}
```

**Response (200 OK):**
```json
{
  "message": "Interface configuration updated successfully"
}
```

---

## Database Management Endpoints

**All database management endpoints require admin role.**

### GET /api/db/stats

Get database statistics.

**Requires:** Admin role

**Response (200 OK):**
```json
{
  "file_size_bytes": 1048576,
  "metrics_count": 50000,
  "switch_events_count": 15,
  "controller_events_count": 200,
  "alerts_count": 10,
  "users_count": 3,
  "schema_version": 1
}
```

---

### POST /api/db/prune

Trigger manual data pruning.

**Requires:** Admin role

**Response (200 OK):**
```json
{
  "message": "Pruning completed",
  "deleted_metrics": 5000,
  "deleted_events": 50
}
```

**Notes:**
- Removes metrics older than retention policy
- Removes events older than retention policy
- Safe to run during normal operation

---

### POST /api/db/flush

Flush all historical data.

**Requires:** Admin role

**Request:**
```json
{
  "confirm": true
}
```

**Response (200 OK):**
```json
{
  "message": "Database flushed successfully"
}
```

**Warning:** This deletes:
- All metrics
- All events
- All alerts

Preserved:
- Users
- API tokens
- Configuration

**Confirmation required to prevent accidental data loss.**

---

## Server-Sent Events

### GET /api/stream

Real-time event stream via Server-Sent Events (SSE).

**Requires:** Authentication

**Response Content-Type:** `text/event-stream`

**Connection:** Keep-alive, streaming

### Event Types

#### Metric Update

```
data: {"type":"metric","interface":"wan0","timestamp":1698765432.123,"score":95.5,"latency_ms":12.5}
```

#### State Change

```
data: {"type":"state_change","interface":"wan0","from":"STABLE","to":"DEGRADED","score":65.0}
```

#### New Alert

```
data: {"type":"alert","level":"WARNING","title":"Interface Degraded","body":"wan0 score dropped"}
```

#### Switch Event

```
data: {"type":"switch","from_interface":"wan0","to_interface":"wan1","reason":"score_below_threshold"}
```

### JavaScript Example

```javascript
const eventSource = new EventSource('/api/stream', {
  headers: { 'Authorization': 'Bearer ' + token }
});

eventSource.onmessage = (event) => {
  const data = JSON.parse(event.data);
  
  switch(data.type) {
    case 'metric':
      updateMetricsChart(data);
      break;
    case 'state_change':
      showStateChange(data);
      break;
    case 'alert':
      displayAlert(data);
      break;
    case 'switch':
      logSwitchEvent(data);
      break;
  }
};

eventSource.onerror = (error) => {
  console.error('SSE connection error:', error);
  // Reconnect after delay
  setTimeout(() => eventSource.close(), 5000);
};
```

### Python Example

```python
import requests
import json

url = 'http://localhost:5000/api/stream'
headers = {'Authorization': f'Bearer {token}'}

with requests.get(url, headers=headers, stream=True) as response:
    for line in response.iter_lines():
        if line and line.startswith(b'data:'):
            data = json.loads(line[6:])
            print(f"Received: {data}")
```

---

## Error Handling

### Standard Error Response Format

```json
{
  "error": {
    "code": "error_code",
    "message": "Human-readable error message"
  }
}
```

### HTTP Status Codes

| Code | Meaning | Common Scenarios |
|------|---------|------------------|
| 200 | OK | Successful request |
| 201 | Created | Resource created (user, token) |
| 400 | Bad Request | Invalid input, validation failed |
| 401 | Unauthorized | Missing or invalid authentication |
| 403 | Forbidden | Insufficient permissions |
| 404 | Not Found | Resource doesn't exist |
| 409 | Conflict | Duplicate resource |
| 500 | Internal Server Error | Server error |

### Common Error Codes

| Code | Description |
|------|-------------|
| `invalid_credentials` | Wrong username/password |
| `token_expired` | JWT or API token expired |
| `token_invalid` | Malformed token |
| `token_revoked` | API token was revoked |
| `insufficient_role` | User role too low for action |
| `user_inactive` | Account deactivated |
| `user_not_found` | User ID doesn't exist |
| `username_taken` | Username already registered |
| `weak_password` | Password doesn't meet requirements |
| `invalid_role` | Invalid role specified |
| `config_error` | Configuration file error |
| `database_error` | Database operation failed |

---

## Rate Limiting

Currently, WANControl does not implement rate limiting. For production deployments with high traffic, consider:

1. Using a reverse proxy (nginx, Apache) with rate limiting
2. Implementing application-level rate limiting
3. Using API gateway solutions

---

## CORS

The API supports Cross-Origin Resource Sharing (CORS) for frontend applications.

**Allowed Origins:** Configured in Flask app

**Allowed Methods:** GET, POST, PUT, DELETE, OPTIONS

**Allowed Headers:** Authorization, X-API-Token, Content-Type

**Credentials:** Supported (for cookie-based sessions)

---

## Versioning

API version is included in health check response:

```json
{
  "status": "healthy",
  "version": "2.0.0"
}
```

Breaking changes will result in major version increments.

---

## Best Practices

### Authentication

1. **Store tokens securely** - Use environment variables or secret managers
2. **Use API tokens for automation** - More secure than storing passwords
3. **Set appropriate expiry** - Short-lived tokens for interactive use
4. **Revoke unused tokens** - Regularly audit and clean up

### Error Handling

1. **Check status codes** - Don't assume success
2. **Parse error responses** - Extract code and message
3. **Implement retries** - With exponential backoff for transient errors
4. **Log failures** - For debugging and monitoring

### Performance

1. **Use appropriate limits** - Don't fetch more data than needed
2. **Filter early** - Use query parameters to reduce payload
3. **Cache when possible** - Static data doesn't need frequent polling
4. **Use SSE for real-time** - More efficient than polling

### Security

1. **Use HTTPS in production** - Encrypt all traffic
2. **Rotate secret keys** - Periodically regenerate server.secret_key
3. **Audit user access** - Review user list and tokens regularly
4. **Monitor failed logins** - Detect brute force attempts

---

*API Reference for WANControl v2.0.0*
