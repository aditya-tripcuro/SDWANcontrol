export interface TokenPair {
  access_token: string
  token_type: string
  expires_in: number
}

export interface InterfaceStatus {
  name: string
  label: string
  expected_speed_mbps: number
  gateway: string
  routing_table_id: number
  wan_state: 'STABLE' | 'DEGRADED' | 'FAILED' | 'SWITCHING'
  score: number
  in_pool: boolean
}

export interface ControllerStatus {
  mode: 'STARTING' | 'RUNNING' | 'MAINTENANCE' | 'KILLED'
  wan_mode: 'failover' | 'load_balance'
  active_interface: string | null
  nexthop_pool: string[]
  interfaces: Record<string, {
    wan_state: 'STABLE' | 'DEGRADED' | 'FAILED' | 'SWITCHING'
    score: number
    in_pool: boolean
  }>
  timestamp: number
}

export interface MetricRow {
  id: number
  interface: string
  timestamp: number
  latency_ms: number
  jitter_ms: number
  loss_pct: number
  dns_ok: boolean
  http_ok: boolean
  score: number
}

export interface SwitchEventRow {
  id: number
  timestamp: number
  from_interface: string
  to_interface: string
  reason: string
  triggered_by: string
  score_before: number
  score_after: number
}

export interface ControllerEventRow {
  id: number
  timestamp: number
  level: string
  component: string
  message: string
  user_id: number | null
}

export interface AlertRow {
  id: number
  timestamp: number
  level: string
  title: string
  body: string
  resolved_at: number | null
  notified: boolean
}

export interface UserRow {
  id: number
  username: string
  role: 'admin' | 'operator' | 'viewer'
  created_at: number
  last_login: number | null
  is_active: boolean
}

export interface ApiTokenRow {
  id: number
  user_id: number
  label: string
  created_at: number
  last_used: number | null
  expires_at: number | null
  is_revoked: boolean
}

export interface DbStats {
  file_size_bytes: number
  metrics_count: number
  switch_events_count: number
  controller_events_count: number
  alerts_count: number
  users_count: number
  schema_version: number
}
