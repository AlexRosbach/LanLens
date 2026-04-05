import { formatDistanceToNow, format } from 'date-fns'
import { de, enUS } from 'date-fns/locale'

export function formatMac(mac: string): string {
  return mac.toUpperCase()
}

export function formatIp(ip: string | null): string {
  return ip ?? '—'
}

/**
 * Parse a date string from the backend. The backend stores UTC times without
 * timezone info, so we append 'Z' to ensure correct interpretation.
 */
function parseDateStr(dateStr: string): Date {
  const normalized =
    dateStr.endsWith('Z') || /[+-]\d{2}:\d{2}$/.test(dateStr)
      ? dateStr
      : dateStr + 'Z'
  return new Date(normalized)
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

export function formatDeviceLabel(device: { label: string | null; hostname: string | null; mac_address: string }): string {
  return device.label || device.hostname || device.mac_address
}
