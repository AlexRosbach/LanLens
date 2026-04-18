import { useState } from 'react'
import toast from 'react-hot-toast'
import {
  Service,
  ServiceCreate,
  ServicePreset,
  ServiceType,
  SERVICE_PRESETS,
  SERVICE_TYPE_LABELS,
  servicesApi,
} from '../../api/services'
import Button from '../ui/Button'
import Input from '../ui/Input'
import Modal from '../ui/Modal'
import ServiceIcon from './ServiceIcon'
import { useI18n } from '../../i18n'

interface Props {
  deviceId: number
  editService?: Service | null
  onClose: () => void
  onSaved: (service: Service) => void
}

const PROTOCOLS = ['https', 'http', 'ssh', 'rdp', 'tcp', 'udp']
const SERVICE_TYPES: ServiceType[] = ['web', 'api', 'ssh', 'rdp', 'database', 'monitoring', 'storage', 'automation', 'other']

export default function AddServiceModal({ deviceId, editService, onClose, onSaved }: Props) {
  const isEdit = !!editService
  const { t } = useI18n()

  const [selectedPreset, setSelectedPreset] = useState<ServicePreset | null>(null)
  const [showPresets, setShowPresets] = useState(!isEdit)

  const [name, setName] = useState(editService?.name ?? '')
  const [serviceType, setServiceType] = useState<ServiceType>(editService?.service_type ?? 'web')
  const [iconKey, setIconKey] = useState(editService?.icon_key ?? '')
  const [url, setUrl] = useState(editService?.url ?? '')
  const [port, setPort] = useState<string>(editService?.port?.toString() ?? '')
  const [protocol, setProtocol] = useState(editService?.protocol ?? 'https')
  const [description, setDescription] = useState(editService?.description ?? '')
  const [version, setVersion] = useState(editService?.version ?? '')
  const [usernameHint, setUsernameHint] = useState(editService?.username_hint ?? '')
  const [passwordLocation, setPasswordLocation] = useState(editService?.password_location ?? '')
  const [notes, setNotes] = useState(editService?.notes ?? '')
  const [saving, setSaving] = useState(false)

  function applyPreset(preset: ServicePreset) {
    setSelectedPreset(preset)
    setName(preset.name)
    setServiceType(preset.service_type)
    setIconKey(preset.icon_key)
    setProtocol(preset.protocol)
    if (preset.port) setPort(preset.port.toString())
    if (preset.description) setDescription(preset.description)
    setShowPresets(false)
  }

  async function handleSave() {
    if (!name.trim()) { toast.error(t('please_enter_service_name')); return }

    const data: ServiceCreate = {
      name: name.trim(),
      service_type: serviceType,
      icon_key: iconKey || undefined,
      url: url.trim() || undefined,
      port: port ? parseInt(port) : undefined,
      protocol,
      description: description.trim() || undefined,
      version: version.trim() || undefined,
      username_hint: usernameHint.trim() || undefined,
      password_location: passwordLocation.trim() || undefined,
      notes: notes.trim() || undefined,
    }

    setSaving(true)
    try {
      let result: Service
      if (isEdit && editService) {
        result = await servicesApi.update(deviceId, editService.id, data)
        toast.success(t('service_updated'))
      } else {
        result = await servicesApi.create(deviceId, data)
        toast.success(t('service_added'))
      }
      onSaved(result)
      onClose()
    } catch {
      toast.error(t('failed_to_save_service'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={isEdit ? t('edit_service_title', { name: editService!.name }) : t('add_service')}
      maxWidth="max-w-2xl"
    >
      {/* Preset picker (only on create) */}
      {!isEdit && showPresets && (
        <div className="mb-5">
          <p className="text-sm text-text-muted mb-3">{t('choose_preset_or_custom')}</p>
          <div className="grid grid-cols-3 sm:grid-cols-4 gap-2 max-h-52 overflow-y-auto pr-1">
            {SERVICE_PRESETS.map((preset) => (
              <button
                key={preset.name}
                onClick={() => applyPreset(preset)}
                className="flex flex-col items-center gap-1.5 p-2 rounded-lg border border-border
                  hover:border-primary/50 hover:bg-surface2 transition-colors text-center"
              >
                <ServiceIcon iconKey={preset.icon_key} serviceType={preset.service_type} className="w-8 h-8" />
                <span className="text-xs text-text-muted leading-tight">{preset.name}</span>
              </button>
            ))}
          </div>
          <button
            onClick={() => setShowPresets(false)}
            className="mt-3 text-xs text-text-subtle hover:text-primary transition-colors"
          >
            {t('skip_preset_manual')}
          </button>
        </div>
      )}

      {/* Form */}
      <div className="flex flex-col gap-4">
        {/* Name + type row */}
        <div className="grid grid-cols-2 gap-3">
          <Input
            label={t('service_name_required')}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Grafana, N8N"
            autoFocus={!showPresets}
          />
          <div className="flex flex-col gap-1">
            <label className="text-sm font-medium text-text-muted">{t('type')}</label>
            <select
              value={serviceType}
              onChange={(e) => setServiceType(e.target.value as ServiceType)}
              className="input-field"
            >
              {SERVICE_TYPES.map((t) => (
                <option key={t} value={t}>{SERVICE_TYPE_LABELS[t]}</option>
              ))}
            </select>
          </div>
        </div>

        {/* URL + port + protocol */}
        <div className="grid grid-cols-3 gap-3">
          <div className="col-span-2">
            <Input
              label="URL"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://192.168.1.10:3000"
            />
          </div>
          <Input
            label="Port"
            type="number"
            value={port}
            onChange={(e) => setPort(e.target.value)}
            placeholder="443"
          />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="flex flex-col gap-1">
            <label className="text-sm font-medium text-text-muted">{t('protocol')}</label>
            <select value={protocol} onChange={(e) => setProtocol(e.target.value)} className="input-field">
              {PROTOCOLS.map((p) => <option key={p}>{p}</option>)}
            </select>
          </div>
          <Input
            label={t('version')}
            value={version}
            onChange={(e) => setVersion(e.target.value)}
            placeholder="e.g. 10.5.1"
          />
        </div>

        <Input
          label={t('description')}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder={t('service_description_placeholder')}
        />

        {/* Credentials section */}
        <div className="border border-border rounded-xl p-3 flex flex-col gap-3 bg-surface2/50">
          <p className="text-xs font-medium text-text-subtle uppercase tracking-wider">{t('access_info')}</p>
          <div className="grid grid-cols-2 gap-3">
            <Input
              label={t('username_login_hint')}
              value={usernameHint}
              onChange={(e) => setUsernameHint(e.target.value)}
              placeholder="e.g. admin"
            />
            <Input
              label={t('password_location')}
              value={passwordLocation}
              onChange={(e) => setPasswordLocation(e.target.value)}
              placeholder="e.g. Vaultwarden → Servers"
            />
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-sm font-medium text-text-muted">Notes</label>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={2}
            className="input-field resize-none"
            placeholder={t('notes_placeholder')}
          />
        </div>

        <div className="flex gap-3 justify-end pt-1">
          <Button variant="ghost" onClick={onClose}>{t('cancel')}</Button>
          <Button onClick={handleSave} loading={saving}>
            {isEdit ? t('save_changes_label') : t('add_service')}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
