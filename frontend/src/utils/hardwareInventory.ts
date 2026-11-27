import type { DeepScanFinding } from '../api/deepScan'
import type { VsphereDeviceObservation } from '../api/devices'

const positiveNumber = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value > 0
const record = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value)

/** Only a current, unambiguous VM can supply preferred hardware values. */
export function preferredVmwareHardware(observations: VsphereDeviceObservation[]): VsphereDeviceObservation[] {
  const current = observations.filter(row => ['existing', 'created'].includes(row.match_status))
  if (current.length !== 1 || current[0].kind !== 'vm') return []
  const row = current[0]
  const fields: Record<string, unknown> = {}
  for (const key of ['cpu_count', 'memory_size_mib']) {
    if (positiveNumber(row.fields[key])) fields[key] = row.fields[key]
  }
  const disks = row.fields.disks
  if (Array.isArray(disks) && disks.length > 0
    && disks.every(disk => record(disk) && typeof disk.disk_id === 'string' && /^[A-Za-z0-9_.:-]{1,128}$/.test(disk.disk_id) && positiveNumber(disk.capacity_bytes))
    && new Set(disks.map(disk => disk.disk_id)).size === disks.length) {
    fields.disks = disks
  }
  return Object.keys(fields).length ? [{ ...row, fields, custom_fields: [] }] : []
}

function decode(raw: unknown): unknown {
  if (typeof raw !== 'string') return raw
  try { return JSON.parse(raw) } catch { return raw }
}

function omitFields(value: unknown, fields: string[]): unknown {
  if (Array.isArray(value)) return value.map(item => omitFields(item, fields)).filter(hasValue)
  if (!record(value)) return value
  return Object.fromEntries(Object.entries(value).filter(([key]) => !fields.includes(key)))
}

function hasValue(value: unknown): boolean {
  if (Array.isArray(value)) return value.length > 0
  if (record(value)) return Object.keys(value).length > 0
  return value !== null && value !== undefined && String(value).trim() !== ''
}

/**
 * Project only supplemental guest fields for the combined Hardware view.
 * Original findings stay untouched for source filters and change history.
 */
export function hardwareFallbackFindings(findings: DeepScanFinding[], preferred: VsphereDeviceObservation[]): DeepScanFinding[] {
  const fields = preferred[0]?.fields
  if (!fields) return findings
  const cpu = positiveNumber(fields.cpu_count)
  const memory = positiveNumber(fields.memory_size_mib)
  const disks = Array.isArray(fields.disks) && fields.disks.length > 0
    && fields.disks.every(disk => record(disk) && positiveNumber(disk.capacity_bytes))

  return findings.flatMap(finding => {
    if (finding.finding_type !== 'hardware') return [finding]
    let value = decode(finding.value)
    switch (finding.key) {
      case 'computer_system':
        value = omitFields(value, [
          ...(cpu ? ['NumberOfLogicalProcessors'] : []),
          ...(memory ? ['TotalPhysicalMemory'] : []),
        ])
        break
      case 'processor':
        if (cpu) value = omitFields(value, ['NumberOfCores', 'NumberOfLogicalProcessors'])
        break
      case 'cpu':
        if (cpu && typeof value === 'string') {
          value = value.split('\n').filter(line => !/^\s*(CPU\(s\)|On-line CPU\(s\) list|Off-line CPU\(s\) list)\s*:/i.test(line)).join('\n')
        }
        break
      case 'memory':
        // free(1) reports guest totals and usage, not additional hardware.
        if (memory) return []
        break
      case 'physical_memory':
        if (memory) {
          value = typeof value === 'string'
            ? value.split('\n').filter(line => !/^\s*(Size|Maximum Capacity)\s*:/i.test(line)).join('\n')
            : omitFields(value, ['Capacity'])
        }
        break
      case 'disk_drives':
        if (disks) value = omitFields(value, ['Size'])
        break
      case 'disks':
        if (disks && typeof value === 'string') {
          const lines = value.trim().split('\n')
          const headers = lines[0].trim().split(/\s+/)
          const sizeColumn = headers.indexOf('SIZE')
          if (sizeColumn >= 0) value = lines.map(line => {
            const tokens = line.trim().split(/\s+/)
            // MODEL is the final lsblk column and may itself contain spaces.
            const cells = [...tokens.slice(0, headers.length - 1), tokens.slice(headers.length - 1).join(' ')]
            return cells.filter((_, index) => index !== sizeColumn).join('  ')
          }).join('\n')
        }
        break
    }
    return hasValue(value) ? [{ ...finding, value }] : []
  })
}
