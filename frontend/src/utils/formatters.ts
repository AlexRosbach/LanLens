import { formatDistanceToNow, format } from 'date-fns'
import { de, enUS } from 'date-fns/locale'

export function formatMac(mac: string | null, ipOnlyLabel?: string): string {
  if (!mac) return '—'
  if (mac.startsWith('ip:')) return ipOnlyLabel ?? mac
  return mac.toUpperCase()
}

export function formatIp(ip: string | null): string {
  return ip ?? '—'
}

/**
 * Parse a date string from the backend. The backend stores UTC times without
 * timezone info, so we append 'Z' to ensure correct interpretation.
 */
export function parseDateStr(dateStr: string): Date {
  const normalized =
    dateStr.endsWith('Z') || /[+-]\d{2}:\d{2}$/.test(dateStr)
      ? dateStr
      : dateStr + 'Z'
  return new Date(normalized)
}


function padDatePart(value: number): string {
  return String(value).padStart(2, '0')
}

export function backendUtcToLocalDateTimeInput(dateStr?: string | null): string {
  if (!dateStr) return ''
  try {
    const date = parseDateStr(dateStr)
    if (Number.isNaN(date.getTime())) return ''
    return `${date.getFullYear()}-${padDatePart(date.getMonth() + 1)}-${padDatePart(date.getDate())}T${padDatePart(date.getHours())}:${padDatePart(date.getMinutes())}`
  } catch {
    return ''
  }
}

export function localDateTimeInputToUtcIso(value: string): string | null {
  if (!value) return null
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return null
  return date.toISOString()
}

export function formatRelativeTime(dateStr: string, lang = 'en'): string {
  try {
    return formatDistanceToNow(parseDateStr(dateStr), {
      addSuffix: true,
      locale: lang === 'de' ? de : enUS,
    })
  } catch {
    return dateStr
  }
}

export function formatDateTime(dateStr: string): string {
  try {
    return format(parseDateStr(dateStr), 'dd.MM.yyyy HH:mm')
  } catch {
    return dateStr
  }
}

export function formatBitsPerSecond(value?: number | null): string {
  if (!value || value <= 0) return '—'
  const units = ['bps', 'Kbps', 'Mbps', 'Gbps', 'Tbps']
  let current = value
  let unit = 0
  while (current >= 1000 && unit < units.length - 1) {
    current /= 1000
    unit += 1
  }
  const digits = current >= 100 ? 0 : current >= 10 ? 1 : 2
  return `${current.toFixed(digits).replace(/\.0+$/, '')} ${units[unit]}`
}

export function formatCounter(value?: number | null): string {
  if (value === null || value === undefined) return '—'
  return new Intl.NumberFormat().format(value)
}

export function formatDeviceLabel(
  device: { label: string | null; hostname: string | null; mac_address: string },
  ipOnlyLabel?: string,
): string {
  if (device.label) return device.label
  if (device.hostname) return device.hostname
  if (device.mac_address.startsWith('ip:') && ipOnlyLabel) return ipOnlyLabel
  return device.mac_address
}
