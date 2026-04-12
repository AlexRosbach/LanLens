import { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { autoScanRulesApi, type AutoScanRule, type AutoScanRuleCreate } from '../api/autoScanRules'
import { credentialsApi, type Credential } from '../api/credentials'
import CredentialManager from '../components/settings/CredentialManager'
import Button from '../components/ui/Button'
import Card from '../components/ui/Card'
import Input from '../components/ui/Input'
import { useI18n } from '../i18n'

// ── Scan profile descriptions ──────────────────────────────────────────────────

const PROFILE_INFO = [
  {
    key: 'hardware_only',
    credType: 'both',
    collects: ['System vendor & model', 'Serial number', 'CPU info', 'Memory', 'Disks', 'OS release & kernel'],
  },
  {
    key: 'os_services',
    credType: 'both',
    collects: ['Everything in Hardware Only', 'Full OS details', 'Uptime', 'All running systemd services'],
  },
  {
    key: 'linux_container_host',
    credType: 'linux',
    collects: ['Everything in OS + Services', 'Docker containers & info', 'Podman containers', 'k3s pods'],
  },
  {
    key: 'windows_audit',
    credType: 'windows',
    collects: ['Hardware & OS details', 'Running Windows services', 'Installed Windows Features', 'Licensing', 'IIS sites', 'Hyper-V VMs', 'SQL instances', 'AD domain', 'DHCP scopes'],
  },
  {
    key: 'hypervisor_inventory',
    credType: 'linux',
    collects: ['Hardware & OS & Services', 'KVM VMs (virsh)', 'Proxmox QEMU VMs + MAC addresses', 'Proxmox LXC containers + MAC addresses', 'libvirt networks', 'VM-to-device matching'],
  },
  {
    key: 'full',
    credType: 'both',
    collects: ['All of the above (Linux: hardware + OS + services + containers + hypervisor)', 'All of the above (Windows: hardware + OS + services + audit)'],
  },
]

const DEVICE_CLASSES = [
  'Server', 'VM', 'Workstation', 'NAS',
  'Router', 'Switch', 'AP', 'Firewall',
  'Mobile', 'TV', 'VoIP', 'IoT', 'Printer', 'Camera', 'Unknown',
]

// ── Auto-scan rule modal ───────────────────────────────────────────────────────

interface RuleModalProps {
  credentials: Credential[]
  initial?: AutoScanRule | null
  onSave: (rule: AutoScanRuleCreate & { id?: number }) => Promise<void>
  onClose: () => void
}

function RuleModal({ credentials, initial, onSave, onClose }: RuleModalProps) {
  const { t, lang } = useI18n()
  const [name, setName] = useState(initial?.name ?? '')
  const [deviceClass, setDeviceClass] = useState<string>(initial?.device_class ?? '')
  const [credentialId, setCredentialId] = useState<number | ''>(initial?.credential_id ?? '')
  const [profile, setProfile] = useState(initial?.scan_profile ?? 'os_services')
  const [interval, setInterval] = useState(initial?.interval_minutes ?? 720)
  const [saving, setSaving] = useState(false)

  async function handleSave() {
    if (!name.trim()) { toast.error(lang === 'de' ? 'Name erforderlich' : 'Name required'); return }
    if (!credentialId) { toast.error(lang === 'de' ? 'Zugangsdaten erforderlich' : 'Credential required'); return }
    setSaving(true)
    try {
      await onSave({
        id: initial?.id,
        name: name.trim(),
        device_class: deviceClass || null,
        credential_id: Number(credentialId),
        scan_profile: profile,
        interval_minutes: interval,
        enabled: true,
      })
      onClose()
    } catch {
      toast.error(lang === 'de' ? 'Speichern fehlgeschlagen' : 'Failed to save rule')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
      <div className="bg-surface border border-border rounded-xl shadow-xl w-full max-w-md space-y-4 p-6">
        <h3 className="text-base font-semibold text-text-base">
          {initial ? t('auto_scan_rule_edit') : t('auto_scan_rule_add')}
        </h3>

        <Input
          label={lang === 'de' ? 'Regelname' : 'Rule name'}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={lang === 'de' ? 'z.B. Alle Server täglich' : 'e.g. All Servers daily'}
        />

        <div className="flex flex-col gap-1">
          <label className="text-sm font-medium text-text-muted">
            {lang === 'de' ? 'Geräteklasse (leer = alle)' : 'Device class (empty = all)'}
          </label>
          <select
            className="input-field"
            value={deviceClass}
            onChange={(e) => setDeviceClass(e.target.value)}
          >
            <option value="">{lang === 'de' ? 'Alle Geräteklassen' : 'All device classes'}</option>
            {DEVICE_CLASSES.map((cls) => (
              <option key={cls} value={cls}>{cls}</option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-sm font-medium text-text-muted">{t('deep_scan_credential')}</label>
          <select
            className="input-field"
            value={credentialId}
            onChange={(e) => setCredentialId(e.target.value ? Number(e.target.value) : '')}
          >
            <option value="">{t('deep_scan_no_credential')}</option>
            {credentials.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} ({c.username} — {c.credential_type === 'linux_ssh' ? t('credential_type_linux_ssh') : t('credential_type_windows_winrm')})
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-sm font-medium text-text-muted">{t('deep_scan_profile')}</label>
          <select className="input-field" value={profile} onChange={(e) => setProfile(e.target.value)}>
            {PROFILE_INFO.map((p) => (
              <option key={p.key} value={p.key}>
                {t(('deep_scan_profile_' + p.key) as Parameters<typeof t>[0])}
              </option>
            ))}
          </select>
        </div>

        <Input
          label={t('deep_scan_interval')}
          type="number"
          min={5}
          value={interval}
          onChange={(e) => setInterval(Number(e.target.value) || 60)}
        />

        <div className="flex justify-end gap-2 pt-2">
          <Button variant="ghost" onClick={onClose}>{t('cancel')}</Button>
          <Button onClick={handleSave} loading={saving}>{t('save')}</Button>
        </div>
      </div>
    </div>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function DeepScanSettings() {
  const { t, lang } = useI18n()
  const [credentials, setCredentials] = useState<Credential[]>([])
  const [rules, setRules] = useState<AutoScanRule[]>([])
  const [showRuleModal, setShowRuleModal] = useState(false)
  const [editingRule, setEditingRule] = useState<AutoScanRule | null>(null)

  useEffect(() => {
    credentialsApi.list().then((r) => setCredentials(r.data)).catch(() => {})
    autoScanRulesApi.list().then(setRules).catch(() => {})
  }, [])

  async function handleSaveRule(data: AutoScanRuleCreate & { id?: number }) {
    if (data.id) {
      const updated = await autoScanRulesApi.update(data.id, data)
      setRules((prev) => prev.map((r) => (r.id === data.id ? updated : r)))
      toast.success(lang === 'de' ? 'Regel gespeichert' : 'Rule saved')
    } else {
      const created = await autoScanRulesApi.create(data)
      setRules((prev) => [...prev, created])
      toast.success(lang === 'de' ? 'Regel erstellt' : 'Rule created')
    }
  }

  async function handleToggleRule(rule: AutoScanRule) {
    try {
      const updated = await autoScanRulesApi.update(rule.id, { enabled: !rule.enabled })
      setRules((prev) => prev.map((r) => (r.id === rule.id ? updated : r)))
    } catch {
      toast.error(lang === 'de' ? 'Fehler beim Aktualisieren' : 'Failed to update rule')
    }
  }

  async function handleDeleteRule(id: number) {
    if (!confirm(t('delete_confirm'))) return
    try {
      await autoScanRulesApi.delete(id)
      setRules((prev) => prev.filter((r) => r.id !== id))
      toast.success(lang === 'de' ? 'Regel gelöscht' : 'Rule deleted')
    } catch {
      toast.error(lang === 'de' ? 'Löschen fehlgeschlagen' : 'Failed to delete rule')
    }
  }

  const credName = (id: number) => credentials.find((c) => c.id === id)?.name ?? `#${id}`

  return (
    <div className="space-y-6">
      {/* ── Credentials ─────────────────────────────────────────────────────── */}
      <Card>
        <h2 className="text-lg font-semibold text-text-base mb-1">{t('deep_scan_credentials')}</h2>
        <p className="text-sm text-text-subtle mb-4">
          {lang === 'de'
            ? 'SSH- und WinRM-Zugangsdaten für den Tiefenscan. Passwörter werden Fernet-verschlüsselt gespeichert.'
            : 'SSH and WinRM credentials for deep scan. Passwords are stored Fernet-encrypted.'}
        </p>
        <CredentialManager onCredentialsChange={setCredentials} />
      </Card>

      {/* ── Scan profiles ────────────────────────────────────────────────────── */}
      <Card>
        <h2 className="text-lg font-semibold text-text-base mb-1">{t('deep_scan_profiles_title')}</h2>
        <p className="text-sm text-text-subtle mb-4">
          {lang === 'de'
            ? 'Übersicht aller verfügbaren Scan-Profile und was sie erfassen.'
            : 'Overview of all available scan profiles and what they collect.'}
        </p>

        <div className="space-y-3">
          {PROFILE_INFO.map((p) => {
            const labelKey = ('deep_scan_profile_' + p.key) as Parameters<typeof t>[0]
            const typeLabel =
              p.credType === 'linux' ? 'Linux SSH' :
              p.credType === 'windows' ? 'Windows WinRM' :
              'Linux SSH / Windows WinRM'
            return (
              <div key={p.key} className="rounded-xl border border-border bg-surface2 p-4">
                <div className="flex items-start justify-between gap-3 mb-2">
                  <p className="text-sm font-semibold text-text-base">{t(labelKey)}</p>
                  <span className="text-xs px-2 py-0.5 rounded-full bg-primary-dim text-primary border border-primary/20 whitespace-nowrap flex-shrink-0">
                    {typeLabel}
                  </span>
                </div>
                <ul className="space-y-0.5">
                  {p.collects.map((item, i) => (
                    <li key={i} className="flex items-start gap-2 text-xs text-text-muted">
                      <span className="text-success mt-0.5 flex-shrink-0">✓</span>
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            )
          })}
        </div>
      </Card>

      {/* ── Auto-scan rules ──────────────────────────────────────────────────── */}
      <Card>
        <div className="flex items-center justify-between gap-4 mb-1">
          <div>
            <h2 className="text-lg font-semibold text-text-base">{t('auto_scan_rules_title')}</h2>
            <p className="text-sm text-text-subtle mt-0.5">
              {lang === 'de'
                ? 'Globale Regeln: Alle passenden Geräte werden automatisch nach Ablauf des Intervalls gescannt — unabhängig von gerätespezifischen Einstellungen.'
                : 'Global rules: All matching devices are scanned automatically after the interval elapses — independent of per-device settings.'}
            </p>
          </div>
          <Button size="sm" onClick={() => { setEditingRule(null); setShowRuleModal(true) }}>
            {t('auto_scan_rule_add')}
          </Button>
        </div>

        <div className="mt-4 space-y-2">
          {rules.length === 0 && (
            <p className="text-sm text-text-subtle text-center py-4">{t('auto_scan_no_rules')}</p>
          )}
          {rules.map((rule) => (
            <div
              key={rule.id}
              className={`rounded-xl border p-4 flex items-start justify-between gap-3 ${
                rule.enabled ? 'border-border bg-surface2' : 'border-border/50 bg-surface opacity-60'
              }`}
            >
              <div className="min-w-0 space-y-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <p className="text-sm font-semibold text-text-base">{rule.name}</p>
                  {rule.device_class ? (
                    <span className="text-xs px-1.5 py-0.5 rounded-full bg-surface border border-border text-text-muted">
                      {rule.device_class}
                    </span>
                  ) : (
                    <span className="text-xs px-1.5 py-0.5 rounded-full bg-surface border border-border text-text-subtle">
                      {lang === 'de' ? 'Alle Klassen' : 'All classes'}
                    </span>
                  )}
                  {!rule.enabled && (
                    <span className="text-xs text-warning">{lang === 'de' ? 'Deaktiviert' : 'Disabled'}</span>
                  )}
                </div>
                <p className="text-xs text-text-subtle">
                  {lang === 'de' ? 'Profil' : 'Profile'}: <span className="text-text-muted">{t(('deep_scan_profile_' + rule.scan_profile) as Parameters<typeof t>[0])}</span>
                  {' · '}
                  {lang === 'de' ? 'Zugangsdaten' : 'Credential'}: <span className="text-text-muted">{credName(rule.credential_id)}</span>
                  {' · '}
                  {lang === 'de' ? 'Intervall' : 'Interval'}: <span className="text-text-muted">{rule.interval_minutes} min</span>
                </p>
              </div>
              <div className="flex items-center gap-1 flex-shrink-0">
                <button
                  onClick={() => handleToggleRule(rule)}
                  className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                    rule.enabled ? 'bg-primary' : 'bg-surface2 border border-border'
                  }`}
                  title={rule.enabled ? (lang === 'de' ? 'Deaktivieren' : 'Disable') : (lang === 'de' ? 'Aktivieren' : 'Enable')}
                >
                  <span className={`inline-block h-3 w-3 transform rounded-full bg-white shadow transition-transform ${rule.enabled ? 'translate-x-5' : 'translate-x-1'}`} />
                </button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => { setEditingRule(rule); setShowRuleModal(true) }}
                >
                  {t('edit')}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleDeleteRule(rule.id)}
                >
                  <span className="text-danger">{t('delete_segment')}</span>
                </Button>
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* ── Rule modal ───────────────────────────────────────────────────────── */}
      {showRuleModal && (
        <RuleModal
          credentials={credentials}
          initial={editingRule}
          onSave={handleSaveRule}
          onClose={() => { setShowRuleModal(false); setEditingRule(null) }}
        />
      )}
    </div>
  )
}
