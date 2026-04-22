import { rest } from 'msw'

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
  rest.post('/api/auth/login', (req, res, ctx) => {
    return res(ctx.status(200), ctx.json({ access_token: FAKE_ADMIN_JWT, token_type: 'bearer', expires_in: 3600 }))
  }),

  rest.get('/api/status', (req, res, ctx) => res(ctx.json(FAKE_STATUS))),
  rest.get('/api/status/interfaces', (req, res, ctx) => res(ctx.json(FAKE_INTERFACES))),
  rest.get('/api/metrics', (req, res, ctx) => res(ctx.json(FAKE_METRICS))),
  rest.get('/api/metrics/latest', (req, res, ctx) => res(ctx.json(FAKE_METRICS_LATEST))),
  rest.get('/api/events/switches', (req, res, ctx) => res(ctx.json([]))),
  rest.get('/api/events/controller', (req, res, ctx) => res(ctx.json([]))),
  rest.get('/api/alerts', (req, res, ctx) => res(ctx.json(FAKE_ALERTS))),
  rest.post('/api/alerts/:id/resolve', (req, res, ctx) => res(ctx.status(200), ctx.json({ resolved: true }))),
  rest.get('/api/users', (req, res, ctx) => res(ctx.json(FAKE_USERS))),
  rest.post('/api/users', (req, res, ctx) => res(ctx.status(201), ctx.json({ id: 2, username: 'new', role: 'viewer' }))),
  rest.get('/api/tokens', (req, res, ctx) => res(ctx.json([]))),
  rest.post('/api/tokens', (req, res, ctx) => res(ctx.status(201), ctx.json({ token: 'rawtoken123', label: 'lbl' }))),
  rest.delete('/api/tokens/:id', (req, res, ctx) => res(ctx.status(200), ctx.json({ revoked: true }))),
  rest.get('/api/config/raw', (req, res, ctx) => res(ctx.text('interfaces: []\n'))),
  rest.put('/api/config/interfaces', (req, res, ctx) => res(ctx.json({ updated: true, interfaces: 2 }))),
  rest.post('/api/config/reload', (req, res, ctx) => res(ctx.json({ reloaded: true }))),
]
