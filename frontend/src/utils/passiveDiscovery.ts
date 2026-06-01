type PassiveObservationLike = {
  id: number
  protocol: string
  source_ip?: string | null
  source_mac?: string | null
  destination_ip?: string | null
  service_name?: string | null
  service_type?: string | null
  summary?: string | null
  metadata?: Record<string, unknown>
  observed_at: string
}

function metadataValue(row: PassiveObservationLike, key: string) {
  const value = row.metadata?.[key]
  return value == null ? '' : String(value)
}

function passiveObservationKey(row: PassiveObservationLike) {
  const source = row.source_ip || row.source_mac?.toLowerCase() || ''
  if (row.protocol === 'multicast') {
    return [
      row.protocol,
      source,
      row.destination_ip || '',
      metadataValue(row, 'transport'),
      metadataValue(row, 'destination_port'),
      row.summary || '',
    ].join('|')
  }
  return [
    row.protocol,
    source,
    row.destination_ip || '',
    row.service_name || '',
    row.service_type || '',
    row.summary || '',
    metadataValue(row, 'location'),
  ].join('|')
}

export function dedupePassiveObservations<T extends PassiveObservationLike>(rows: T[]) {
  const unique = new Map<string, T>()
  for (const row of rows) {
    const key = passiveObservationKey(row)
    const existing = unique.get(key)
    if (!existing || new Date(row.observed_at).getTime() > new Date(existing.observed_at).getTime()) {
      unique.set(key, row)
    }
  }
  return [...unique.values()].sort((a, b) => new Date(b.observed_at).getTime() - new Date(a.observed_at).getTime())
}
