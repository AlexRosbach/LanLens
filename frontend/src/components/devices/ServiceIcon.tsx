import { ServiceType } from '../../api/services'

interface Props {
  iconKey?: string | null
  serviceType?: ServiceType
  className?: string
}

// Emoji-based icon fallback map for well-known services
const ICON_EMOJIS: Record<string, string> = {
  guacamole: '🖥',
  n8n: '⚡',
  grafana: '📊',
  portainer: '🐳',
  proxmox: '🖧',
  nextcloud: '☁',
  homeassistant: '🏠',
  uptimekuma: '🔔',
  beszel: '📈',
  gitea: '🐙',
  vaultwarden: '🔐',
  synology: '💾',
  truenas: '💿',
  plex: '🎬',
  jellyfin: '🎥',
  pihole: '🛡',
  phpmyadmin: '🗄',
  ssh: '💻',
  webmin: '⚙',
  custom: '🔧',
}

const TYPE_COLORS: Record<ServiceType, string> = {
  web: 'text-primary bg-primary-dim',
  api: 'text-purple-400 bg-purple-400/10',
  ssh: 'text-warning bg-warning-dim',
  rdp: 'text-orange-400 bg-orange-400/10',
  database: 'text-cyan-400 bg-cyan-400/10',
  monitoring: 'text-success bg-success-dim',
  storage: 'text-blue-400 bg-blue-400/10',
  automation: 'text-pink-400 bg-pink-400/10',
  other: 'text-text-muted bg-surface2',
}

export function ServiceTypeTag({ type }: { type: ServiceType }) {
  const colors = TYPE_COLORS[type] ?? TYPE_COLORS.other
  return (
    <span className={`text-xs font-medium px-1.5 py-0.5 rounded-md ${colors}`}>
      {type}
    </span>
  )
}

export default function ServiceIcon({ iconKey, serviceType = 'web', className = 'w-8 h-8' }: Props) {
  const emoji = iconKey ? ICON_EMOJIS[iconKey] : null
  const colors = TYPE_COLORS[serviceType] ?? TYPE_COLORS.other

  if (emoji) {
    return (
      <div className={`${className} rounded-lg ${colors} flex items-center justify-center text-lg`}>
        {emoji}
      </div>
    )
  }

  // Generic icon based on service type
  return (
    <div className={`${className} rounded-lg ${colors} flex items-center justify-center`}>
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
          d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9m-9 9a9 9 0 019-9" />
      </svg>
    </div>
  )
}
