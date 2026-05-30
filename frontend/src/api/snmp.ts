import apiClient from './client'

export interface SnmpProfile {
  id: number
  name: string
  version: '1' | '2c' | '3'
  community: string
  username?: string
  security_level?: 'noAuthNoPriv' | 'authNoPriv' | 'authPriv'
  auth_protocol?: 'MD5' | 'SHA' | ''
  auth_password?: string
  privacy_protocol?: 'DES' | 'AES' | ''
  privacy_password?: string
  port: number
  enabled: boolean
}

export type SnmpProfileCreate = {
  name: string
  version: '1' | '2c' | '3'
  community: string
  username: string
  security_level: 'noAuthNoPriv' | 'authNoPriv' | 'authPriv'
  auth_protocol: 'MD5' | 'SHA'
  auth_password: string
  privacy_protocol: 'DES' | 'AES'
  privacy_password: string
  port: number
  enabled: boolean
}

export interface SnmpSwitch {
  id: number
  name: string
  host: string
  device_id?: number | null
  profile_id?: number | null
  enabled: boolean
  sys_name?: string | null
  sys_descr?: string | null
  sys_object_id?: string | null
  vendor?: string | null
  vendor_key?: string | null
  vendor_notes?: string | null
  last_poll_at?: string | null
  last_error?: string | null
  interface_count: number
  mac_count: number
}

export interface SnmpEndpoint {
  mac_address: string
  device_id?: number | null
  device_label?: string
  switch_name: string
  switch_host: string
  if_index?: number | null
  interface_name?: string
  interface_alias?: string
  vlan?: string
  last_seen_at: string
}

export interface SnmpPortEndpoint {
  mac_address: string
  vlan: string
  device_id?: number | null
  device_label?: string
  last_seen_at: string
}

export interface SnmpSwitchPort {
  if_index: number
  name: string
  description: string
  alias: string
  admin_status: string
  oper_status: string
  speed_bps?: number | null
  is_active: boolean
  endpoints: SnmpPortEndpoint[]
  last_seen_at: string
}

export interface SnmpSwitchPortsResponse {
  switch: SnmpSwitch | null
  has_visualization: boolean
  ports: SnmpSwitchPort[]
}

export const snmpApi = {
  listProfiles: () => apiClient.get<SnmpProfile[]>('/snmp/profiles').then((r) => r.data),
  createProfile: (data: SnmpProfileCreate) =>
    apiClient.post<SnmpProfile>('/snmp/profiles', data).then((r) => r.data),
  deleteProfile: (profileId: number) => apiClient.delete(`/snmp/profiles/${profileId}`).then((r) => r.data),
  listSwitches: () => apiClient.get<SnmpSwitch[]>('/snmp/switches').then((r) => r.data),
  createSwitch: (data: { name: string; host: string; profile_id: number; device_id?: number | null; enabled: boolean }) =>
    apiClient.post<SnmpSwitch>('/snmp/switches', data).then((r) => r.data),
  deleteSwitch: (switchId: number) => apiClient.delete(`/snmp/switches/${switchId}`).then((r) => r.data),
  pollSwitch: (switchId: number) => apiClient.post(`/snmp/switches/${switchId}/poll`).then((r) => r.data),
  getDevicePorts: (deviceId: number) =>
    apiClient.get<SnmpSwitchPortsResponse>(`/snmp/devices/${deviceId}/ports`).then((r) => r.data),
  listEndpoints: () => apiClient.get<SnmpEndpoint[]>('/snmp/topology/endpoints').then((r) => r.data),
}
