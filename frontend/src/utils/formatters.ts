import { formatDistanceToNow, format } from 'date-fns'

export function formatMac(mac: string): string {
  return mac.toUpperCase()
}

export function formatIp(ip: string | null): string {
  return ip ?? '—'
}

export function formatRelativeTime(dateStr: string): string {
  try {
    return formatDistanceToNow(new Date(dateStr), { addSuffix: true })
  } catch {
    return dateStr
  }
}

export function formatDateTime(dateStr: string): string {
  try {
    return format(new Date(dateStr), 'dd.MM.yyyy HH:mm')
  } catch {
    return dateStr
  }
}

export function formatDeviceLabel(device: { label: string | null; mac_address: string }): string {
  return device.label || device.mac_address
}
