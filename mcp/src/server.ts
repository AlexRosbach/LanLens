import { McpServer, ResourceTemplate } from '@modelcontextprotocol/server';
import * as z from 'zod/v4';

import type { LanLensMcpConfig } from './config.js';
import { LanLensApiError, LanLensClient } from './client.js';
import {
  sanitizeDevice,
  sanitizeDeviceList,
  sanitizeNetworkChange,
  sanitizeNotification,
  sanitizePortScan,
  sanitizeSegment,
  sanitizeService,
  sanitizeTopology,
} from './sanitize.js';

const DEVICE_CLASSES = [
  'Server', 'Linux Server', 'Windows Server', 'VM', 'Linux VM', 'Windows VM',
  'Workstation', 'Linux Workstation', 'Windows Workstation', 'Apple Workstation',
  'NAS', 'Router', 'Switch', 'AP', 'Firewall', 'Mobile', 'TV', 'VoIP', 'IoT',
  'Printer', 'Camera', 'Unknown',
] as const;

function jsonResult(data: unknown) {
  return {
    content: [{type: 'text' as const, text: JSON.stringify(data, null, 2)}],
    structuredContent: {result: data},
  };
}

function errorResult(error: unknown) {
  const known = error instanceof LanLensApiError;
  const message = known ? error.message : 'The LanLens MCP operation failed';
  const code = known ? error.code : 'INTERNAL_ERROR';
  return {
    isError: true,
    content: [{type: 'text' as const, text: `${code}: ${message}`}],
    structuredContent: {error: {code, message}},
  };
}

function errorMessage(error: unknown): string {
  const result = errorResult(error);
  return result.content[0]?.text ?? 'INTERNAL_ERROR: The LanLens MCP operation failed';
}

function array(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

export function createLanLensMcpServer(config: LanLensMcpConfig): McpServer {
  const client = new LanLensClient(config);
  const server = new McpServer({name: 'lanlens', version: '1.6.1'});

  server.registerResource(
    'lanlens-health',
    'lanlens://health',
    {title: 'LanLens health and build metadata', mimeType: 'application/json'},
    async (uri) => {
      try {
        const health = await client.health();
        return {contents: [{uri: uri.href, mimeType: 'application/json', text: JSON.stringify(health)}]};
      } catch (error) {
        throw new Error(errorMessage(error));
      }
    },
  );

  server.registerResource(
    'lanlens-device',
    new ResourceTemplate('lanlens://devices/{deviceId}', {list: undefined}),
    {title: 'Safe LanLens device inventory record', mimeType: 'application/json'},
    async (uri, variables) => {
      const rawId = Array.isArray(variables.deviceId) ? variables.deviceId[0] : variables.deviceId;
      const deviceId = Number.parseInt(String(rawId), 10);
      if (!Number.isSafeInteger(deviceId) || deviceId < 1) throw new Error('Invalid device ID');
      try {
        const device = sanitizeDevice(await client.getDevice(deviceId));
        return {contents: [{uri: uri.href, mimeType: 'application/json', text: JSON.stringify(device)}]};
      } catch (error) {
        throw new Error(errorMessage(error));
      }
    },
  );

  server.registerTool('get_health', {
    title: 'Get LanLens health',
    description: 'Return LanLens health, version, build, commit, and branch metadata.',
    inputSchema: z.object({}),
    annotations: {readOnlyHint: true, destructiveHint: false, idempotentHint: true},
  }, async () => {
    try { return jsonResult(await client.health()); } catch (error) { return errorResult(error); }
  });

  server.registerTool('list_devices', {
    title: 'List LanLens devices',
    description: 'Search and filter the safe LanLens inventory. Secret fields and password locations are never returned.',
    inputSchema: z.object({
      search: z.string().trim().max(120).optional(),
      online_only: z.boolean().optional(),
      unregistered_only: z.boolean().optional(),
      archived_only: z.boolean().optional(),
      device_class: z.enum(DEVICE_CLASSES).optional(),
      offset: z.number().int().min(0).max(100_000).default(0),
      limit: z.number().int().min(1).max(200).default(50),
    }),
    annotations: {readOnlyHint: true, destructiveHint: false, idempotentHint: true},
  }, async ({search, online_only, unregistered_only, archived_only, device_class, offset, limit}) => {
    try {
      const devices = await client.listDevices({
        search,
        onlineOnly: online_only,
        unregisteredOnly: unregistered_only,
        archivedOnly: archived_only,
        deviceClass: device_class,
      });
      return jsonResult(sanitizeDeviceList(devices, offset, limit));
    } catch (error) { return errorResult(error); }
  });

  server.registerTool('get_device', {
    title: 'Get LanLens device',
    description: 'Return one safe device inventory record without credentials, secrets, password locations, or private notes.',
    inputSchema: z.object({device_id: z.number().int().positive()}),
    annotations: {readOnlyHint: true, destructiveHint: false, idempotentHint: true},
  }, async ({device_id}) => {
    try { return jsonResult(sanitizeDevice(await client.getDevice(device_id))); } catch (error) { return errorResult(error); }
  });

  server.registerTool('list_services', {
    title: 'List LanLens services',
    description: 'List discovered or documented services, optionally for one device.',
    inputSchema: z.object({device_id: z.number().int().positive().optional()}),
    annotations: {readOnlyHint: true, destructiveHint: false, idempotentHint: true},
  }, async ({device_id}) => {
    try { return jsonResult(array(await client.listServices(device_id)).map(sanitizeService)); } catch (error) { return errorResult(error); }
  });

  server.registerTool('list_open_ports', {
    title: 'List device port scans',
    description: 'Return recent port scan records and open ports for one device.',
    inputSchema: z.object({device_id: z.number().int().positive(), limit: z.number().int().min(1).max(20).default(5)}),
    annotations: {readOnlyHint: true, destructiveHint: false, idempotentHint: true},
  }, async ({device_id, limit}) => {
    try { return jsonResult(array(await client.listPortScans(device_id)).slice(0, limit).map(sanitizePortScan)); } catch (error) { return errorResult(error); }
  });

  server.registerTool('get_topology', {
    title: 'Get network topology',
    description: 'Return safe LanLens topology nodes and relationships without raw discovery metadata.',
    inputSchema: z.object({}),
    annotations: {readOnlyHint: true, destructiveHint: false, idempotentHint: true},
  }, async () => {
    try { return jsonResult(sanitizeTopology(await client.topology())); } catch (error) { return errorResult(error); }
  });

  server.registerTool('list_segments', {
    title: 'List network segments',
    description: 'Return configured LanLens network segments.',
    inputSchema: z.object({}),
    annotations: {readOnlyHint: true, destructiveHint: false, idempotentHint: true},
  }, async () => {
    try { return jsonResult(array(await client.segments()).map(sanitizeSegment)); } catch (error) { return errorResult(error); }
  });

  server.registerTool('list_notifications', {
    title: 'List notifications',
    description: 'Return up to the 100 most recent LanLens notifications.',
    inputSchema: z.object({unread_only: z.boolean().default(false), limit: z.number().int().min(1).max(100).default(50)}),
    annotations: {readOnlyHint: true, destructiveHint: false, idempotentHint: true},
  }, async ({unread_only, limit}) => {
    try { return jsonResult(array(await client.notifications(unread_only)).slice(0, limit).map(sanitizeNotification)); } catch (error) { return errorResult(error); }
  });

  server.registerTool('list_network_changes', {
    title: 'List recent network changes',
    description: 'Return recent audited LanLens network and device changes.',
    inputSchema: z.object({
      device_id: z.number().int().positive().optional(),
      since_hours: z.number().int().min(1).max(2160).optional(),
      search: z.string().trim().max(120).optional(),
      limit: z.number().int().min(1).max(200).default(50),
    }),
    annotations: {readOnlyHint: true, destructiveHint: false, idempotentHint: true},
  }, async ({device_id, since_hours, search, limit}) => {
    try {
      const changes = await client.networkChanges({deviceId: device_id, sinceHours: since_hours, search, limit});
      return jsonResult(array(changes).map(sanitizeNetworkChange));
    } catch (error) { return errorResult(error); }
  });

  if (config.enableWrites) {
    server.registerTool('update_device_metadata', {
      title: 'Update safe device metadata',
      description: 'Update allow-listed LanLens device metadata. This tool is present only when LANLENS_MCP_ENABLE_WRITES=true; the LanLens token must also permit writes.',
      inputSchema: z.object({
        device_id: z.number().int().positive(),
        device_class: z.enum(DEVICE_CLASSES).optional(),
        responsible: z.string().max(255).nullable().optional(),
        location: z.string().max(255).nullable().optional(),
        description: z.string().max(10_000).nullable().optional(),
      }).refine((value) => Object.keys(value).some((key) => key !== 'device_id'), {message: 'At least one metadata field is required'}),
      annotations: {readOnlyHint: false, destructiveHint: false, idempotentHint: true},
    }, async ({device_id, ...metadata}) => {
      try { return jsonResult(sanitizeDevice(await client.updateDeviceMetadata(device_id, metadata))); } catch (error) { return errorResult(error); }
    });
  }

  return server;
}
