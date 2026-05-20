import apiClient from './client'

export interface SnmpProfile {
  id: number
  name: string
  version: string
  community: string
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

export const snmpApi = {
  listProfiles: () => apiClient.get<SnmpProfile[]>('/snmp/profiles').then((r) => r.data),
  createProfile: (data: { name: string; community: string; port: number; enabled: boolean }) =>
    apiClient.post<SnmpProfile>('/snmp/profiles', { ...data, version: '2c' }).then((r) => r.data),
  listSwitches: () => apiClient.get<SnmpSwitch[]>('/snmp/switches').then((r) => r.data),
  createSwitch: (data: { name: string; host: string; profile_id: number; device_id?: number | null; enabled: boolean }) =>
    apiClient.post<SnmpSwitch>('/snmp/switches', data).then((r) => r.data),
  pollSwitch: (switchId: number) => apiClient.post(`/snmp/switches/${switchId}/poll`).then((r) => r.data),
  listEndpoints: () => apiClient.get<SnmpEndpoint[]>('/snmp/topology/endpoints').then((r) => r.data),
}
