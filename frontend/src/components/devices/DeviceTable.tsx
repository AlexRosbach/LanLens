import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Device } from '../../api/devices'
import { formatMac, formatRelativeTime, formatDeviceLabel } from '../../utils/formatters'
import { useI18n } from '../../i18n'
import Badge from '../ui/Badge'
import ConnectButtons from './ConnectButtons'
import DeviceClassIcon, { isVmClass } from './DeviceClassIcon'

interface Props {
  devices: Device[]
  onRegister: (device: Device) => void
  onRefresh: () => void
}

type SortKey = 'device' | 'ip' | 'vendor' | 'status' | 'last_seen'
type SortDir = 'asc' | 'desc'

function ipToInt(ip: string | null): number {
  if (!ip) return -1
  const parts = ip.split('.').map(Number)
  return parts.length === 4 ? ((parts[0] << 24) | (parts[1] << 16) | (parts[2] << 8) | parts[3]) >>> 0 : -1
}


function SortIcon({ active, dir }: { active: boolean; dir: SortDir }) {
  return (
    <span className={`inline-flex flex-col ml-1 transition-opacity ${active ? 'opacity-100' : 'opacity-30 group-hover:opacity-60'}`}>
      <svg className={`w-2.5 h-2.5 -mb-0.5 ${active && dir === 'asc' ? 'text-primary' : 'text-text-subtle'}`} viewBox="0 0 10 6" fill="currentColor">
        <path d="M5 0L10 6H0z" />
      </svg>
      <svg className={`w-2.5 h-2.5 ${active && dir === 'desc' ? 'text-primary' : 'text-text-subtle'}`} viewBox="0 0 10 6" fill="currentColor">
        <path d="M5 6L0 0H10z" />
      </svg>
    </span>
  )
}

export default function DeviceTable({ devices, onRegister, onRefresh }: Props) {
  const navigate = useNavigate()
  const { t, lang } = useI18n()
  const [sortKey, setSortKey] = useState<SortKey>('last_seen')
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  function handleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir(key === 'ip' ? 'asc' : 'asc')
    }
  }

  function sortDevices(list: Device[]): Device[] {
    const sign = sortDir === 'asc' ? 1 : -1
    return [...list].sort((a, b) => {
      switch (sortKey) {
        case 'device':
          return sign * formatDeviceLabel(a).localeCompare(formatDeviceLabel(b))
        case 'ip':
          return sign * (ipToInt(a.ip_address) - ipToInt(b.ip_address))
        case 'vendor':
          return sign * (a.vendor ?? '').localeCompare(b.vendor ?? '')
        case 'status':
          return sign * (Number(b.is_online) - Number(a.is_online))
        case 'last_seen':
          return sign * (new Date(a.last_seen).getTime() - new Date(b.last_seen).getTime())
        default:
          return 0
      }
    })
  }

  function handleRowClick(id: number) {
    navigate(`/devices/${id}`)
  }

  function SortTh({ colKey, label, className = '' }: { colKey: SortKey; label: string; className?: string }) {
    return (
      <th
        className={`px-4 py-3 text-left font-medium cursor-pointer select-none group whitespace-nowrap ${className}`}
        onClick={() => handleSort(colKey)}
      >
        {label}
        <SortIcon active={sortKey === colKey} dir={sortDir} />
      </th>
    )
  }

  if (devices.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-text-subtle">
        <svg className="w-12 h-12 mb-3 opacity-40" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.2}
            d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
        </svg>
        <p className="text-sm">{t('no_devices_found')}</p>
      </div>
    )
  }

  const sorted = sortDevices(devices)

  return (
    <div className="overflow-x-auto rounded-xl border border-border">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-text-subtle text-xs uppercase tracking-wider">
            <SortTh colKey="device" label={t('col_device')} />
            <SortTh colKey="ip" label={t('col_ip')} />
            <SortTh colKey="vendor" label={t('col_vendor')} className="hidden md:table-cell" />
            <SortTh colKey="status" label={t('col_status')} />
            <SortTh colKey="last_seen" label={t('col_last_seen')} className="hidden sm:table-cell" />
            <th className="px-4 py-3 text-left font-medium">{t('col_connect')}</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((device, i) => {
            const isNew = device.is_new
            return (
              <tr
                key={device.id}
                onClick={() => handleRowClick(device.id)}
                className={`border-b border-border last:border-0 cursor-pointer
                  transition-colors hover:bg-surface2
                  ${i % 2 === 0 ? 'bg-surface' : 'bg-background/50'}`}
              >
                <td className="px-4 py-3">
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg bg-surface2 border border-border flex items-center justify-center flex-shrink-0">
                      <DeviceClassIcon deviceClass={device.device_class} className="w-4 h-4" />
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <p className="font-medium text-text-base leading-tight truncate">
                          {formatDeviceLabel(device)}
                        </p>
                        {isNew && (
                          <button
                            onClick={(e) => { e.stopPropagation(); onRegister(device) }}
                            className="text-xs bg-warning-dim text-warning border border-warning/20 px-1.5 py-0.5 rounded-full hover:bg-warning hover:text-background transition-colors font-medium flex-shrink-0"
                          >
                            {t('badge_new')}
                          </button>
                        )}
                        {device.is_dhcp && (
                          <span className="text-xs bg-primary-dim text-primary border border-primary/20 px-1.5 py-0.5 rounded-full flex-shrink-0">
                            {t('badge_dhcp')}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-1.5 mt-0.5 flex-wrap">
                        <p className="text-xs text-text-subtle font-mono truncate">
                          {formatMac(device.mac_address)}
                        </p>
                        {device.segment_name && (
                          <span
                            className="text-xs px-1.5 py-0.5 rounded-full font-medium flex-shrink-0"
                            style={{
                              backgroundColor: (device.segment_color ?? '#6366f1') + '22',
                              color: device.segment_color ?? '#6366f1',
                              border: `1px solid ${(device.segment_color ?? '#6366f1')}44`,
                            }}
                          >
                            {device.segment_name}
                          </span>
                        )}
                      </div>
                      {device.host_label && isVmClass(device.device_class) && (
                        <div className="flex items-center gap-1 mt-0.5">
                          <svg className="w-3 h-3 text-text-subtle flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2m-2-4h.01M17 16h.01" />
                          </svg>
                          <p className="text-xs text-text-subtle truncate max-w-[160px]">
                            {device.host_label}
                          </p>
                        </div>
                      )}
                      {device.hardware_summary && (
                        <p className="text-xs text-text-subtle truncate mt-0.5 max-w-[200px]">
                          {device.hardware_summary}
                        </p>
                      )}
                    </div>
                  </div>
                </td>
                <td className="px-4 py-3 font-mono text-text-muted text-xs">
                  {device.ip_address ?? '—'}
                </td>
                <td className="px-4 py-3 text-text-muted text-xs max-w-32 truncate hidden md:table-cell">
                  {device.vendor ?? '—'}
                </td>
                <td className="px-4 py-3">
                  <Badge variant={device.is_online ? 'success' : 'danger'} dot>
                    {device.is_online ? t('badge_online') : t('badge_offline')}
                  </Badge>
                </td>
                <td className="px-4 py-3 text-text-subtle text-xs hidden sm:table-cell">
                  {formatRelativeTime(device.last_seen, lang)}
                </td>
                <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                  <ConnectButtons device={device} onScanRequested={onRefresh} compact />
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}


interface Props {
  devices: Device[]
  onRegister: (device: Device) => void
  onRefresh: () => void
}
