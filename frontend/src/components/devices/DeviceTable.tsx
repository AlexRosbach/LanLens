import { useNavigate } from 'react-router-dom'
import { Device } from '../../api/devices'
import { formatMac, formatRelativeTime, formatDeviceLabel } from '../../utils/formatters'
import { useI18n } from '../../i18n'
import Badge from '../ui/Badge'
import ConnectButtons from './ConnectButtons'
import DeviceClassIcon from './DeviceClassIcon'

interface Props {
  devices: Device[]
  onRegister: (device: Device) => void
  onRefresh: () => void
}

function getViewedIds(): Set<number> {
  try {
    const raw = localStorage.getItem('lanlens_viewed_devices')
    return new Set(raw ? JSON.parse(raw) : [])
  } catch {
    return new Set()
  }
}

export default function DeviceTable({ devices, onRegister, onRefresh }: Props) {
  const navigate = useNavigate()
  const { t, lang } = useI18n()
  const viewedIds = getViewedIds()

  function handleRowClick(id: number) {
    // Mark as viewed in localStorage
    const viewed = getViewedIds()
    viewed.add(id)
    localStorage.setItem('lanlens_viewed_devices', JSON.stringify([...viewed]))
    navigate(`/devices/${id}`)
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

  return (
    <div className="overflow-x-auto rounded-xl border border-border">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-text-subtle text-xs uppercase tracking-wider">
            <th className="px-4 py-3 text-left font-medium">{t('col_device')}</th>
            <th className="px-4 py-3 text-left font-medium">{t('col_ip')}</th>
            <th className="px-4 py-3 text-left font-medium hidden md:table-cell">{t('col_vendor')}</th>
            <th className="px-4 py-3 text-left font-medium">{t('col_status')}</th>
            <th className="px-4 py-3 text-left font-medium hidden sm:table-cell">{t('col_last_seen')}</th>
            <th className="px-4 py-3 text-left font-medium">{t('col_connect')}</th>
          </tr>
        </thead>
        <tbody>
          {devices.map((device, i) => {
            const isNew = !device.is_registered && !viewedIds.has(device.id)
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
                      <div className="flex items-center gap-1.5 mt-0.5">
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
                  <ConnectButtons device={device} onScanRequested={onRefresh} />
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
