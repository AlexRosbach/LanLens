import { Device, devicesApi } from '../../api/devices'
import { buildSshUri, buildWebLinks, hasVnc } from '../../utils/connectionUtils'
import { useI18n } from '../../i18n'

interface Props {
  device: Device
  compact?: boolean
}

export default function ConnectButtons({ device, compact = false }: Props) {
  const { t } = useI18n()
  const scan = device.latest_scan
  const ip = device.ip_address

  if (!ip) return <span className="text-xs text-text-subtle">{t('no_ip')}</span>

  if (!scan) {
    if (compact) return null
    return <span className="text-xs text-text-subtle">{t('port_scan_not_scanned_yet')}</span>
  }

  const webLinks = buildWebLinks(ip, scan.open_ports)

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {scan.ssh_available && (
        <a
          href={buildSshUri(ip)}
          onClick={(e) => e.stopPropagation()}
          className="connect-btn text-primary border-primary/30 hover:bg-primary-dim"
        >
          SSH
        </a>
      )}
      {scan.rdp_available && (
        <a
          href={devicesApi.getRdpUrl(device.id)}
          onClick={(e) => e.stopPropagation()}
          download
          className="connect-btn text-warning border-warning/30 hover:bg-warning-dim"
        >
          RDP
        </a>
      )}
      {webLinks.map((link) => (
        <a
          key={link.url}
          href={link.url}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(e) => e.stopPropagation()}
          className="connect-btn text-success border-success/30 hover:bg-success-dim"
        >
          {link.label}
        </a>
      ))}
      {hasVnc(scan.open_ports) && (
        <span className="connect-btn text-text-subtle border-border cursor-default">VNC</span>
      )}
    </div>
  )
}
