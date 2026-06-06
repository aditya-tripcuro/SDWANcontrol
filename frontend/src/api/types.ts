export interface InterfaceStatus {
  name: string
  label: string
  expected_speed_mbps: number
  gateway: string
  routing_table_id: number
  wan_state: 'STABLE' | 'DEGRADED' | 'FAILED'
  score: number
  in_pool: boolean
}

export interface ControllerStatus {
  mode: 'STOPPED' | 'STARTING' | 'RUNNING' | 'PAUSED' | 'KILLED'
  wan_mode: 'failover' | 'load_balance'
  active_interface: string | null
  nexthop_pool: string[]
  interfaces: Record<string, {
    wan_state: 'STABLE' | 'DEGRADED' | 'FAILED'
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
  requires_password_change: boolean
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
  speedtest_count: number
  usage_count: number
  schema_version: number
}

export interface SpeedtestResult {
  id: number
  interface: string
  timestamp: number
  download_mbps: number | null
  upload_mbps: number | null
  ping_ms: number | null
  jitter_ms: number | null
  packet_loss_pct: number | null
  server_name: string | null
  isp: string | null
  error: string | null
}

export interface UsageSample {
  id: number
  interface: string
  timestamp: number
  rx_mbps: number
  tx_mbps: number
  rx_bytes_total: number
  tx_bytes_total: number
}
