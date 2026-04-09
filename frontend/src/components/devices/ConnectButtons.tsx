import { Device } from '../../api/devices'
import { buildSshUri, buildWebLinks, hasVnc } from '../../utils/connectionUtils'
import { devicesApi } from '../../api/devices'
import toast from 'react-hot-toast'
import { useState } from 'react'

interface Props {
  device: Device
  onScanRequested?: () => void
}

export default function ConnectButtons({ device, onScanRequested }: Props) {
  const [scanning, setScanning] = useState(false)
  const scan = device.latest_scan
  const ip = device.ip_address

  if (!ip) return <span className="text-xs text-text-subtle">No IP</span>

  if (!scan) {
    return (
      <button
        disabled={scanning}
        onClick={async (e) => {
          e.stopPropagation()
          setScanning(true)
          try {
            await devicesApi.scanPorts(device.id)
            toast.success('Port scan started')
            onScanRequested?.()
          } catch {
            toast.error('Port scan failed')
          } finally {
            setScanning(false)
          }
        }}
        className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-lg
          bg-surface2 text-text-muted hover:text-primary hover:bg-primary-dim border border-border
          transition-colors disabled:opacity-50"
      >
        <svg className={`w-3.5 h-3.5 ${scanning ? 'animate-spin' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
        {scanning ? 'Scanning…' : 'Scan Ports'}
      </button>
    )
  }

  const webLinks = buildWebLinks(ip, scan.open_ports)

  async function handleRescan(e: React.MouseEvent) {
    e.stopPropagation()
    setScanning(true)
    try {
      await devicesApi.scanPorts(device.id)
      toast.success('Port scan started')
      onScanRequested?.()
    } catch {
      toast.error('Port scan failed')
    } finally {
      setScanning(false)
    }
  }

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
      <button
        disabled={scanning}
        onClick={handleRescan}
        className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-lg
          bg-surface2 text-text-muted hover:text-primary hover:bg-primary-dim border border-border
          transition-colors disabled:opacity-50"
      >
        <svg className={`w-3.5 h-3.5 ${scanning ? 'animate-spin' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
        </svg>
        {scanning ? 'Scanning…' : 'Rescan Ports'}
      </button>
    </div>
  )
}
