import { useNavigate } from 'react-router-dom'
import { Device } from '../../api/devices'
import { formatMac, formatRelativeTime, formatDeviceLabel } from '../../utils/formatters'
import Badge from '../ui/Badge'
import ConnectButtons from './ConnectButtons'
import DeviceClassIcon from './DeviceClassIcon'

interface Props {
  devices: Device[]
  onRegister: (device: Device) => void
  onRefresh: () => void
}

export default function DeviceTable({ devices, onRegister, onRefresh }: Props) {
  const navigate = useNavigate()

  if (devices.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-text-subtle">
        <svg className="w-12 h-12 mb-3 opacity-40" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.2}
            d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
        </svg>
        <p className="text-sm">No devices found</p>
      </div>
    )
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-border">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-text-subtle text-xs uppercase tracking-wider">
            <th className="px-4 py-3 text-left font-medium">Device</th>
            <th className="px-4 py-3 text-left font-medium">IP Address</th>
            <th className="px-4 py-3 text-left font-medium">Vendor</th>
            <th className="px-4 py-3 text-left font-medium">Status</th>
            <th className="px-4 py-3 text-left font-medium">Last Seen</th>
            <th className="px-4 py-3 text-left font-medium">Connect</th>
          </tr>
        </thead>
        <tbody>
          {devices.map((device, i) => (
            <tr
              key={device.id}
              onClick={() => navigate(`/devices/${device.id}`)}
              className={`border-b border-border last:border-0 cursor-pointer
                transition-colors hover:bg-surface2
                ${i % 2 === 0 ? 'bg-surface' : 'bg-background/50'}`}
            >
              <td className="px-4 py-3">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-lg bg-surface2 border border-border flex items-center justify-center flex-shrink-0">
                    <DeviceClassIcon deviceClass={device.device_class} className="w-4 h-4" />
                  </div>
                  <div>
                    <p className="font-medium text-text-base leading-tight">
                      {formatDeviceLabel(device)}
                    </p>
                    <p className="text-xs text-text-subtle font-mono">
                      {formatMac(device.mac_address)}
                    </p>
                  </div>
                  {!device.is_registered && (
                    <button
                      onClick={(e) => { e.stopPropagation(); onRegister(device) }}
                      className="ml-2 text-xs bg-warning-dim text-warning border border-warning/20 px-2 py-0.5 rounded-full hover:bg-warning hover:text-background transition-colors font-medium"
                    >
                      NEW
                    </button>
                  )}
                </div>
              </td>
              <td className="px-4 py-3 font-mono text-text-muted text-xs">
                {device.ip_address ?? '—'}
              </td>
              <td className="px-4 py-3 text-text-muted text-xs max-w-32 truncate">
                {device.vendor ?? '—'}
              </td>
              <td className="px-4 py-3">
                <Badge variant={device.is_online ? 'success' : 'danger'} dot>
                  {device.is_online ? 'Online' : 'Offline'}
                </Badge>
              </td>
              <td className="px-4 py-3 text-text-subtle text-xs">
                {formatRelativeTime(device.last_seen)}
              </td>
              <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                <ConnectButtons device={device} onScanRequested={onRefresh} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
