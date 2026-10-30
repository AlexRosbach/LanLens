import { useState } from 'react'
import toast from 'react-hot-toast'
import { Device, ManualConnectEntry, ManualConnectEntryInput, devicesApi } from '../../api/devices'
import { useI18n } from '../../i18n'
import Button from '../ui/Button'
import Input from '../ui/Input'

interface Props {
  device: Device
  onChange: (entries: ManualConnectEntry[]) => void
}

const emptyForm: ManualConnectEntryInput = { label: '', url: 'https://', protocol: 'https', sort_order: 0 }

export default function ManualConnectEntries({ device, onChange }: Props) {
  const { t } = useI18n()
  const entries = device.manual_connect_entries ?? []
  const [form, setForm] = useState<ManualConnectEntryInput>(emptyForm)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [saving, setSaving] = useState(false)

  const reset = () => {
    setEditingId(null)
    setForm(emptyForm)
  }

  const save = async () => {
    if (!form.label.trim() || !form.url.trim()) return
    setSaving(true)
    try {
      const saved = editingId
        ? await devicesApi.updateManualConnectEntry(device.id, editingId, form)
        : await devicesApi.createManualConnectEntry(device.id, form)
      const next = editingId
        ? entries.map((entry) => entry.id === editingId ? saved : entry)
        : [...entries, saved]
      onChange(next.sort((a, b) => a.sort_order - b.sort_order || a.id - b.id))
      toast.success(t(editingId ? 'manual_connect_updated' : 'manual_connect_added'))
      reset()
    } catch {
      toast.error(t('manual_connect_save_failed'))
    } finally {
      setSaving(false)
    }
  }

  const remove = async (entry: ManualConnectEntry) => {
    if (!window.confirm(t('manual_connect_delete_confirm', { label: entry.label }))) return
    try {
      await devicesApi.deleteManualConnectEntry(device.id, entry.id)
      onChange(entries.filter((candidate) => candidate.id !== entry.id))
      toast.success(t('manual_connect_deleted'))
      if (editingId === entry.id) reset()
    } catch {
      toast.error(t('manual_connect_delete_failed'))
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-text-subtle">{t('manual_connect_hint')}</p>
      {entries.length > 0 && (
        <div className="space-y-2">
          {entries.map((entry) => (
            <div key={entry.id} className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-surface2/40 px-3 py-2">
              <a href={entry.url} target={entry.protocol === 'http' || entry.protocol === 'https' ? '_blank' : undefined} rel="noreferrer" className="min-w-0 flex-1 text-sm font-medium text-primary hover:underline">
                {entry.label}
                <span className="ml-2 break-all text-xs font-normal text-text-subtle">{entry.url}</span>
              </a>
              <Button size="sm" variant="ghost" onClick={() => {
                setEditingId(entry.id)
                setForm({ label: entry.label, url: entry.url, protocol: entry.protocol, sort_order: entry.sort_order })
              }}>{t('edit')}</Button>
              <Button size="sm" variant="ghost" onClick={() => remove(entry)}>{t('delete')}</Button>
            </div>
          ))}
        </div>
      )}
      <div className="grid gap-2 rounded-lg border border-border p-3 md:grid-cols-[1fr_2fr_8rem_auto]">
        <Input aria-label={t('manual_connect_label')} value={form.label} onChange={(event) => setForm((current) => ({ ...current, label: event.target.value }))} placeholder={t('manual_connect_label')} />
        <Input aria-label={t('manual_connect_url')} value={form.url} onChange={(event) => {
          const url = event.target.value
          const scheme = url.split(':', 1)[0].toLowerCase()
          setForm((current) => ({
            ...current,
            url,
            protocol: ['http', 'https', 'ssh', 'rdp', 'vnc', 'tcp'].includes(scheme)
              ? scheme as ManualConnectEntryInput['protocol']
              : current.protocol,
          }))
        }} placeholder="https://nas.example.com" />
        <select aria-label={t('manual_connect_protocol')} className="input-field" value={form.protocol} onChange={(event) => setForm((current) => ({ ...current, protocol: event.target.value as ManualConnectEntryInput['protocol'] }))}>
          {['https', 'http', 'ssh', 'rdp', 'vnc', 'tcp'].map((protocol) => <option key={protocol} value={protocol}>{protocol.toUpperCase()}</option>)}
        </select>
        <div className="flex gap-2">
          <Button size="sm" loading={saving} disabled={!form.label.trim() || !form.url.trim()} onClick={save}>{editingId ? t('save') : t('add')}</Button>
          {editingId && <Button size="sm" variant="ghost" onClick={reset}>{t('cancel')}</Button>}
        </div>
      </div>
    </div>
  )
}
