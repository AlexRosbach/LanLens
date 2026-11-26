import { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { agentsApi, type CreatedEnrollmentToken, type EnrollmentToken } from '../../api/agents'
import Button from '../ui/Button'
import Input from '../ui/Input'
import { useI18n } from '../../i18n'

const durations = [
  { label: '1 hour', value: 60 }, { label: '24 hours', value: 1440 },
  { label: '7 days', value: 10080 }, { label: '30 days', value: 43200 },
  { label: 'Never expires', value: null },
]

interface Props { platform?: 'windows' | 'linux' }

export default function WindowsAgentPanel({ platform = 'windows' }: Props) {
  const {lang} = useI18n()
  const german = lang === 'de'
  const [trustCertificate, setTrustCertificate] = useState(false)
  const [tokens, setTokens] = useState<EnrollmentToken[]>([])
  const [name, setName] = useState(platform === 'windows' ? 'Windows inventory agent' : 'Linux inventory agent')
  const [duration, setDuration] = useState<number | null>(10080)
  const [interval, setInterval] = useState(60)
  const [serverUrl, setServerUrl] = useState(() => window.location.origin)
  const [created, setCreated] = useState<CreatedEnrollmentToken | null>(null)
  const [loading, setLoading] = useState(false)

  const validServerUrl = /^https:\/\/[a-zA-Z0-9.\-\[\]:]+(?:\/[a-zA-Z0-9._~\/-]*)?$/.test(serverUrl)
  const buildCommand = (updateExisting = false) => {
    if (!validServerUrl || (!created && !updateExisting)) return ''
    const url = serverUrl.replace(/\/$/, '')
    if (platform === 'linux') return `curl --proto '=https' --proto-redir '=https' -fsS '${url}/api/agents/linux/install.sh' | sudo bash -s -- --server-url '${url}' --enrollment-token '${created?.token ?? ''}' --interval-minutes ${interval}`
    const args = updateExisting ? '-UpdateExisting' : `-EnrollmentToken '${created?.token ?? ''}' -IntervalMinutes ${interval}`
    const install = `& ([ScriptBlock]::Create((iwr -UseBasicParsing -MaximumRedirection 0 '${url}/api/agents/windows/install.ps1').Content)) -ServerUrl '${url}' ${args}`
    if (!trustCertificate) return `powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "${install}"`
    const bootstrap = `$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.Net.Security;
using System.Security.Cryptography.X509Certificates;
public static class LanLensBootstrapTls {
    public static RemoteCertificateValidationCallback ForUntrustedCertificate() {
        return delegate(object sender, X509Certificate cert, X509Chain chain, SslPolicyErrors errors) {
            return cert != null;
        };
    }
}
'@
$request = [Net.HttpWebRequest][Net.WebRequest]::Create('${url}/api/agents/windows/install.ps1')
$request.AllowAutoRedirect = $false
$request.Timeout = 30000
$request.ServerCertificateValidationCallback = [LanLensBootstrapTls]::ForUntrustedCertificate()
$response = $request.GetResponse()
try {
    if ([int]$response.StatusCode -lt 200 -or [int]$response.StatusCode -ge 300) { throw 'Unexpected HTTP status.' }
    $reader = New-Object IO.StreamReader($response.GetResponseStream())
    try { $script = $reader.ReadToEnd() } finally { $reader.Dispose() }
} finally { $response.Dispose() }
& ([ScriptBlock]::Create($script)) -ServerUrl '${url}' ${args} -TrustUntrustedCertificate`
    // Windows PowerShell expects UTF-16LE for EncodedCommand; avoids shell quoting issues.
    const bytes = Array.from(bootstrap, char => String.fromCharCode(char.charCodeAt(0)&255, char.charCodeAt(0)>>8)).join('')
    return 'powershell.exe -NoProfile -ExecutionPolicy Bypass -EncodedCommand ' + btoa(bytes)
  }
  const command = buildCommand()
  const updateCommand = platform === 'windows' ? buildCommand(true) : ''

  async function refresh() {
    try { setTokens((await agentsApi.listTokens()).data) } catch { toast.error('Could not load installation tokens') }
  }
  useEffect(() => { void refresh() }, [])

  async function create() {
    if (!name.trim()) { toast.error('Enter a token name'); return }
    if (!validServerUrl) { toast.error('Use a public HTTPS URL for off-LAN agents'); return }
    setLoading(true)
    try {
      const result = (await agentsApi.createToken({ name: name.trim(), expires_in_minutes: duration })).data
      setCreated(result)
      await refresh()
      toast.success('Installation token created')
    } catch (error: any) { toast.error(error.response?.data?.detail || 'Could not create token') } finally { setLoading(false) }
  }

  async function revoke(id: number) {
    try { await agentsApi.revokeToken(id); await refresh(); toast.success('Installation token revoked') }
    catch { toast.error('Could not revoke token') }
  }
  async function copy() { await navigator.clipboard.writeText(command); toast.success('Installation command copied') }

  return <div className="space-y-5">
    <div className="rounded-xl border border-primary/25 bg-primary-dim/30 p-4">
      <h3 className="font-semibold text-text-base">Outbound {platform === 'windows' ? 'Windows' : 'Linux'} Agent</h3>
      <p className="mt-1 text-sm text-text-muted">Installs a {platform === 'windows' ? 'Windows service' : 'systemd service'} that sends inventory over HTTPS to LanLens. No inbound {platform === 'windows' ? 'WinRM' : 'SSH'} connection is required.</p>
    </div>
    <div className="grid gap-4 md:grid-cols-2">
      <Input label="Installation token name" value={name} onChange={(e) => setName(e.target.value)} />
      <div className="flex flex-col gap-1"><label className="text-sm font-medium text-text-muted">Token validity</label><select className="input-field" value={duration ?? 'never'} onChange={(e) => setDuration(e.target.value === 'never' ? null : Number(e.target.value))}>{durations.map((item) => <option key={String(item.value)} value={item.value ?? 'never'}>{item.label}</option>)}</select></div>
      <Input label="Public LanLens HTTPS URL" value={serverUrl} onChange={(e) => setServerUrl(e.target.value)} hint="This URL must be reachable from the target endpoint." />
      <Input label="Reporting interval (minutes)" type="number" min={5} max={1440} value={interval} onChange={(e) => setInterval(Math.min(1440, Math.max(5, Number(e.target.value) || 60)))} />
    </div>
    {platform === 'windows' && <div className="space-y-2">
      <label className="flex items-center gap-2 text-sm text-text-base"><input type="checkbox" checked={trustCertificate} onChange={e=>setTrustCertificate(e.target.checked)} />{german ? 'Nicht vertrauenswürdigem Zertifikat explizit vertrauen' : 'Explicitly trust an untrusted certificate'}</label>
      {trustCertificate && <p className="text-xs text-warning">{german ? 'Die Zertifikatskette wird nicht mehr als Vertrauensnachweis geprüft. Angreifer könnten den Server imitieren, den Installer manipulieren oder Agent-Zugangsdaten abfangen. Nur in einer vertrauenswürdigen Umgebung verwenden. Auch Hostname und Gültigkeitszeitraum werden bei dieser Ausnahme nicht geprüft.' : 'The certificate chain is no longer required to be trusted. Attackers could impersonate the server, tamper with the installer, or intercept agent credentials. Only use in a trusted environment. This exception also disables hostname and validity-date checks.'}</p>}
    </div>}
    <Button onClick={create} loading={loading}>Create installation command</Button>
    {created && <div className="rounded-xl border border-success/40 bg-surface2 p-4 space-y-3">
      <p className="text-sm text-text-base">Run this once with {platform === 'windows' ? 'elevated PowerShell' : 'root or sudo'}. The token is single-use and shown only now. Revoking it also disables the enrolled agent.</p>
      <textarea readOnly value={command} className="input-field min-h-32 font-mono text-xs" />
      <Button variant="outline" size="sm" onClick={copy} disabled={!command}>Copy installation command</Button>
    </div>}
    {platform === 'windows' && <div className="rounded-xl border border-border p-3 space-y-2">
      <h3 className="font-semibold text-text-base">{german ? 'Installierten Agent aktualisieren' : 'Update installed agent'}</h3>
      <p className="text-xs text-text-muted">{german ? 'Als Administrator ausführen. Registrierung, Zieladresse, Intervall und Sequenz bleiben erhalten. Danach ist die Deinstallation über Windows-Einstellungen → Apps möglich. Zertifikatsoption wie bei der ursprünglichen Installation wählen.' : 'Run elevated. Enrollment, destination, interval and sequence are preserved. Afterwards uninstall via Windows Settings → Apps. Select the certificate option used for the original installation.'}</p>
      <Button variant="outline" size="sm" disabled={!updateCommand} onClick={async()=>{await navigator.clipboard.writeText(updateCommand); toast.success(german ? 'Update-Befehl kopiert' : 'Update command copied')}}>{german ? 'Update-Befehl kopieren' : 'Copy update command'}</Button>
      <p className="text-xs text-text-muted">Log: C:\ProgramData\LanLensAgent\agent.log</p>
    </div>}
    <div className="space-y-2"><h3 className="font-semibold text-text-base">Installation tokens</h3>
      {tokens.length === 0 ? <p className="text-sm text-text-subtle">No installation tokens yet.</p> : tokens.map((token) => <div key={token.id} className="rounded-lg border border-border bg-surface2 p-3 flex items-center justify-between gap-3"><div><p className="text-sm font-medium text-text-base">{token.name}</p><p className="text-xs text-text-subtle">{token.revoked_at ? 'Revoked' : token.last_used_at ? 'Used (agent enrolled)' : token.expires_at ? `Expires ${new Date(token.expires_at).toLocaleString()}` : 'Never expires'}</p></div>{!token.revoked_at && <Button size="sm" variant="ghost" onClick={() => revoke(token.id)}><span className="text-danger">Revoke</span></Button>}</div>)}</div>
  </div>
}
