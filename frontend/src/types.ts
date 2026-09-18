export interface Alarm {
  alarm_id: number;
  event_id: string;
  sensor_id: string;
  site_id: string;
  type: string;
  severity: string;
  status: "ACTIVE" | "ACKNOWLEDGED" | "RESOLVED";
  created_at: string;
  source_ts?: string | null;
  confidence?: number | null;
  acknowledged_at?: string | null;
  resolved_at?: string | null;
}

export interface Site {
  site_id: string;
  status: string;
  active_alarm_count: number;
  highest_active_severity: string | null;
  latest_event_ts?: string | null;
  updated_at: string;
}

export interface Sensor {
  sensor_id: string;
  site_id: string;
  status: string;
  online: boolean;
  last_event_ts?: string | null;
  last_heartbeat_ts?: string | null;
  latest_event_type?: string | null;
  updated_at: string;
}

export interface Snapshot {
  alarms: Alarm[];
  sites: Site[];
  sensors: Sensor[];
}

export interface LatencyReport {
  queue?: number;
  process?: number;
  total?: number;
}

export interface TimelineEvent {
  event_id: string;
  sensor_id: string;
  site_id: string;
  type: string;
  severity: string;
  confidence?: number | null;
  source_ts: string;
  processed_at?: string | null;
  alarm_id?: number | null;
  alarm_status?: string | null;
  escalated?: boolean | null;
}

export interface Correlation {
  correlation_id: number;
  rule: string;
  site_id: string;
  sensor_id?: string | null;
  window_start: string;
  window_end: string;
  severity_before: string;
  severity_after: string;
  event_ids: string[];
  alarm_ids: number[];
  description: string;
  detected_at: string;
}

export interface SiteTimeline {
  site: Site;
  events: TimelineEvent[];
  correlations: Correlation[];
}

export interface SensorTimeline {
  sensor: Sensor;
  events: TimelineEvent[];
}

export interface AlarmUpdate {
  alarm: Alarm;
  sensor?: Sensor | null;
  latency_ms?: LatencyReport;
}

export interface DashboardMessage {
  kind: "snapshot" | "alarm" | "alarms" | "sensor" | "sites" | "correlations" | "ping";
  alarms?: Alarm[];
  sites?: Site[];
  sensors?: Sensor[];
  correlations?: Correlation[];
  alarm?: Alarm;
  site?: Site;
  sensor?: Sensor;
  updates?: AlarmUpdate[];
  latency_ms?: LatencyReport;
}

export const SEVERITY_RANK: Record<string, number> = {
  critical: 4,
  high: 3,
  medium: 2,
  low: 1,
  informational: 0,
};