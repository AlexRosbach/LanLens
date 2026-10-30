type JsonObject = Record<string, unknown>;

function object(value: unknown): JsonObject {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as JsonObject
    : {};
}

function pick(source: JsonObject, keys: readonly string[]): JsonObject {
  const result: JsonObject = {};
  for (const key of keys) {
    if (source[key] !== undefined) result[key] = source[key];
  }
  return result;
}

const DEVICE_FIELDS = [
  'id', 'mac_address', 'ip_address', 'hostname', 'preferred_name', 'display_name',
  'label', 'device_class', 'vendor', 'vendor_detected', 'vendor_override',
  'segment_id', 'segment_name', 'is_dhcp', 'purpose', 'description', 'location',
  'responsible', 'os_info', 'kernel_version', 'inferred_os_family',
  'os_inference_confidence', 'os_inference_reasons', 'asset_tag', 'is_registered',
  'is_new', 'is_online', 'first_seen', 'last_seen', 'hardware_summary', 'host_label',
  'cmdb_id', 'ignored', 'notifications_muted', 'maintenance_until',
  'maintenance_note', 'is_archived', 'archived_at', 'snmp_switch',
  'snmp_interface', 'snmp_interface_alias', 'snmp_vlan', 'snmp_last_seen_at',
] as const;

const SERVICE_FIELDS = [
  'id', 'device_id', 'name', 'service_type', 'service_group_name', 'url', 'port',
  'protocol', 'description', 'version', 'device_label', 'device_ip', 'device_class',
] as const;

export function sanitizeDevice(value: unknown): JsonObject {
  const source = object(value);
  const result = pick(source, DEVICE_FIELDS);
  if (source.latest_scan) result.latest_scan = sanitizePortScan(source.latest_scan);
  if (Array.isArray(source.services)) result.services = source.services.map(sanitizeService);
  return result;
}

export function sanitizeService(value: unknown): JsonObject {
  return pick(object(value), SERVICE_FIELDS);
}

export function sanitizePortScan(value: unknown): JsonObject {
  const source = object(value);
  const result = pick(source, [
    'id', 'scanned_at', 'ssh_available', 'rdp_available', 'http_available', 'https_available',
  ]);
  if (Array.isArray(source.open_ports)) {
    result.open_ports = source.open_ports.map((entry) => pick(object(entry), ['port', 'protocol', 'service', 'state']));
  }
  return result;
}

export function sanitizeTopology(value: unknown): JsonObject {
  const source = object(value);
  return {
    nodes: Array.isArray(source.nodes)
      ? source.nodes.map((entry) => pick(object(entry), [
        'id', 'label', 'ip_address', 'device_class', 'is_online', 'segment_id',
        'segment_name', 'service_count', 'snmp_switch', 'snmp_interface', 'snmp_vlan',
      ]))
      : [],
    edges: Array.isArray(source.edges)
      ? source.edges.map((entry) => pick(object(entry), ['source', 'target', 'relationship_type', 'label']))
      : [],
  };
}

export function sanitizeDeviceList(value: unknown, offset: number, limit: number): JsonObject {
  const source = object(value);
  const items = Array.isArray(source.items) ? source.items.map(sanitizeDevice) : [];
  return {
    items: items.slice(offset, offset + limit),
    returned: Math.min(limit, Math.max(0, items.length - offset)),
    offset,
    available_after_filter: items.length,
    totals: pick(source, ['total', 'online', 'offline', 'unregistered', 'archived']),
  };
}

export function sanitizeNotification(value: unknown): JsonObject {
  return pick(object(value), [
    'id', 'device_id', 'device_path', 'device_url', 'event_type', 'event_subtype',
    'message', 'is_read', 'created_at',
  ]);
}

export function sanitizeNetworkChange(value: unknown): JsonObject {
  return pick(object(value), [
    'id', 'event_id', 'device_id', 'device_label', 'device', 'ip_address',
    'mac_address', 'device_class', 'event_type', 'field', 'old_value', 'new_value',
    'source', 'message', 'created_at', 'timestamp',
  ]);
}

export function sanitizeSegment(value: unknown): JsonObject {
  return pick(object(value), ['id', 'name', 'color', 'ip_start', 'ip_end', 'description', 'created_at']);
}
