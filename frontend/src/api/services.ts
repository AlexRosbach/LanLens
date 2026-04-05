import apiClient from './client'

export type ServiceType = 'web' | 'api' | 'ssh' | 'rdp' | 'database' | 'monitoring' | 'storage' | 'automation' | 'other'

export interface Service {
  id: number
  device_id: number
  name: string
  service_type: ServiceType
  icon_key: string | null
  url: string | null
  port: number | null
  protocol: string
  description: string | null
  version: string | null
  username_hint: string | null
  password_location: string | null
  notes: string | null
  sort_order: number
  created_at: string
  updated_at: string
}

export interface ServiceCreate {
  name: string
  service_type?: ServiceType
  icon_key?: string
  url?: string
  port?: number
  protocol?: string
  description?: string
  version?: string
  username_hint?: string
  password_location?: string
  notes?: string
  sort_order?: number
}

export type ServiceUpdate = Partial<ServiceCreate>

export const servicesApi = {
  list: (deviceId: number) =>
    apiClient.get<Service[]>(`/devices/${deviceId}/services`).then((r) => r.data),

  create: (deviceId: number, data: ServiceCreate) =>
    apiClient.post<Service>(`/devices/${deviceId}/services`, data).then((r) => r.data),

  update: (deviceId: number, serviceId: number, data: ServiceUpdate) =>
    apiClient.put<Service>(`/devices/${deviceId}/services/${serviceId}`, data).then((r) => r.data),

  delete: (deviceId: number, serviceId: number) =>
    apiClient.delete(`/devices/${deviceId}/services/${serviceId}`),
}

// ── Well-known service presets ───────────────────────────────────────────────
export interface ServicePreset {
  name: string
  icon_key: string
  service_type: ServiceType
  protocol: string
  port?: number
  description?: string
}

export const SERVICE_PRESETS: ServicePreset[] = [
  { name: 'Apache Guacamole', icon_key: 'guacamole', service_type: 'web', protocol: 'https', port: 8080, description: 'Remote desktop gateway' },
  { name: 'N8N', icon_key: 'n8n', service_type: 'automation', protocol: 'https', port: 5678, description: 'Workflow automation' },
  { name: 'Grafana', icon_key: 'grafana', service_type: 'monitoring', protocol: 'https', port: 3000, description: 'Metrics & dashboards' },
  { name: 'Portainer', icon_key: 'portainer', service_type: 'web', protocol: 'https', port: 9443, description: 'Docker management' },
  { name: 'Proxmox VE', icon_key: 'proxmox', service_type: 'web', protocol: 'https', port: 8006, description: 'Virtualisation platform' },
  { name: 'Nextcloud', icon_key: 'nextcloud', service_type: 'storage', protocol: 'https', port: 443, description: 'Self-hosted cloud storage' },
  { name: 'Home Assistant', icon_key: 'homeassistant', service_type: 'automation', protocol: 'http', port: 8123, description: 'Smart home platform' },
  { name: 'Uptime Kuma', icon_key: 'uptimekuma', service_type: 'monitoring', protocol: 'https', port: 3001, description: 'Uptime monitoring' },
  { name: 'Beszel', icon_key: 'beszel', service_type: 'monitoring', protocol: 'https', port: 8090, description: 'Server monitoring' },
  { name: 'Gitea', icon_key: 'gitea', service_type: 'web', protocol: 'https', port: 3000, description: 'Self-hosted Git' },
  { name: 'Vaultwarden', icon_key: 'vaultwarden', service_type: 'web', protocol: 'https', port: 80, description: 'Password manager' },
  { name: 'Synology DSM', icon_key: 'synology', service_type: 'web', protocol: 'https', port: 5001, description: 'Synology NAS' },
  { name: 'TrueNAS', icon_key: 'truenas', service_type: 'web', protocol: 'https', port: 443, description: 'TrueNAS management' },
  { name: 'Plex', icon_key: 'plex', service_type: 'web', protocol: 'https', port: 32400, description: 'Media server' },
  { name: 'Jellyfin', icon_key: 'jellyfin', service_type: 'web', protocol: 'https', port: 8096, description: 'Media server' },
  { name: 'Pi-hole', icon_key: 'pihole', service_type: 'web', protocol: 'http', port: 80, description: 'DNS ad-blocker' },
  { name: 'phpMyAdmin', icon_key: 'phpmyadmin', service_type: 'database', protocol: 'https', description: 'MySQL web UI' },
  { name: 'SSH', icon_key: 'ssh', service_type: 'ssh', protocol: 'ssh', port: 22, description: 'Secure shell access' },
  { name: 'Webmin', icon_key: 'webmin', service_type: 'web', protocol: 'https', port: 10000, description: 'Server admin panel' },
  { name: 'Custom', icon_key: 'custom', service_type: 'web', protocol: 'https', description: 'Custom service' },
]

export const SERVICE_TYPE_LABELS: Record<ServiceType, string> = {
  web: 'Web UI',
  api: 'API',
  ssh: 'SSH',
  rdp: 'RDP',
  database: 'Database',
  monitoring: 'Monitoring',
  storage: 'Storage',
  automation: 'Automation',
  other: 'Other',
}
