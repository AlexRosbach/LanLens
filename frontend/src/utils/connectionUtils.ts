import { PortInfo } from '../api/devices'

export interface WebLink { label: string; url: string }

export function buildSshUri(ip: string): string {
  return `ssh://${ip}`
}

export function buildWebLinks(ip: string, ports: PortInfo[]): WebLink[] {
  const portNums = ports.filter((p) => p.state === 'open').map((p) => p.port)
  const links: WebLink[] = []

  if (portNums.includes(443)) links.push({ label: 'HTTPS', url: `https://${ip}` })
  if (portNums.includes(80)) links.push({ label: 'HTTP', url: `http://${ip}` })
  if (portNums.includes(8443)) links.push({ label: ':8443', url: `https://${ip}:8443` })
  if (portNums.includes(8080)) links.push({ label: ':8080', url: `http://${ip}:8080` })

  return links
}

export function hasVnc(ports: PortInfo[]): boolean {
  return ports.some((p) => p.port === 5900 && p.state === 'open')
}
