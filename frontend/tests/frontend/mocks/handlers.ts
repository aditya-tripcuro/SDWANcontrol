import { http, HttpResponse } from 'msw'

const ADMIN_PAYLOAD = { sub: 1, username: 'admin', role: 'admin', iat: 1700000000, exp: 1700000000 + 3600 }
export const FAKE_ADMIN_JWT = `eyJhbGciOiJIUzI1NiJ9.${btoa(JSON.stringify(ADMIN_PAYLOAD))}.fakesig`

export const FAKE_STATUS = {
  mode: 'RUNNING', wan_mode: 'load_balance',
  active_interface: null, nexthop_pool: ['wan0', 'wan1'],
  interfaces: {
    wan0: { wan_state: 'STABLE', score: 97.4, in_pool: true },
    wan1: { wan_state: 'DEGRADED', score: 42.0, in_pool: true },
  },
  timestamp: 1700000000.0,
}

export const FAKE_INTERFACES = [
  { name: 'wan0', label: 'Fiber Primary', expected_speed_mbps: 100, gateway: '192.168.1.1', routing_table_id: 100, wan_state: 'STABLE', score: 97.4, in_pool: true },
  { name: 'wan1', label: 'LTE Backup', expected_speed_mbps: 30, gateway: '10.0.0.1', routing_table_id: 101, wan_state: 'DEGRADED', score: 42.0, in_pool: true },
]

export const FAKE_METRICS = [
  { id: 1, interface: 'wan0', timestamp: 1700000000, latency_ms: 12.3, jitter_ms: 1.1, loss_pct: 0.0, dns_ok: true, http_ok: true, score: 97.4 },
]

export const FAKE_METRICS_LATEST = {
  wan0: FAKE_METRICS[0],
  wan1: null,
}

export const FAKE_ALERTS = [
  { id: 1, timestamp: 1700000000, level: 'CRITICAL', title: 'WANControl Alert: link_down', body: 'Link down: wan1', resolved_at: null, notified: false },
  { id: 2, timestamp: 1699990000, level: 'INFO', title: 'WANControl Alert: link_up', body: 'Link up: wan1', resolved_at: 1699995000.0, notified: true },
]

export const FAKE_USERS = [
  { id: 1, username: 'admin', role: 'admin', created_at: 1700000000, last_login: 1700000100, is_active: true },
]

export const handlers = [
  http.post('/api/auth/login', () => {
    return HttpResponse.json({ access_token: FAKE_ADMIN_JWT, token_type: 'bearer', expires_in: 3600 })
  }),

  http.get('/api/status', () => HttpResponse.json(FAKE_STATUS)),
  http.get('/api/status/interfaces', () => HttpResponse.json(FAKE_INTERFACES)),
  http.get('/api/metrics', () => HttpResponse.json(FAKE_METRICS)),
  http.get('/api/metrics/latest', () => HttpResponse.json(FAKE_METRICS_LATEST)),
  http.get('/api/events/switches', () => HttpResponse.json([])),
  http.get('/api/events/controller', () => HttpResponse.json([])),
  http.get('/api/alerts', () => HttpResponse.json(FAKE_ALERTS)),
  http.post('/api/alerts/:id/resolve', () => HttpResponse.json({ resolved: true })),
  http.get('/api/users', () => HttpResponse.json(FAKE_USERS)),
  http.post('/api/users', () => HttpResponse.json({ id: 2, username: 'new', role: 'viewer' }, { status: 201 })),
  http.get('/api/tokens', () => HttpResponse.json([])),
  http.post('/api/tokens', () => HttpResponse.json({ token: 'rawtoken123', label: 'lbl' }, { status: 201 })),
  http.delete('/api/tokens/:id', () => HttpResponse.json({ revoked: true })),
  http.get('/api/config/raw', () => new HttpResponse('interfaces: []\n')),
  http.put('/api/config/interfaces', () => HttpResponse.json({ updated: true, interfaces: 2 })),
  http.post('/api/config/reload', () => HttpResponse.json({ reloaded: true })),
]
