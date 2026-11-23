import assert from 'node:assert/strict';
import test from 'node:test';

import {sanitizeDevice, sanitizeNetworkChange, sanitizeService, sanitizeTopology} from '../src/sanitize.js';
import {deviceFixture} from './helpers.js';

test('device output omits secret and operator-private fields', () => {
  const sanitized = sanitizeDevice(deviceFixture);
  assert.equal(sanitized.id, 1);
  assert.equal('password_location' in sanitized, false);
  assert.equal('notes' in sanitized, false);
  assert.equal('maintenance_note' in sanitized, false);
  assert.equal('manual_connect_entries' in sanitized, false);
  assert.deepEqual((sanitized.latest_scan as {open_ports: unknown[]}).open_ports, [
    {port: 22, protocol: 'tcp', service: 'ssh'},
  ]);
});

test('device output omits private maintenance notes', () => {
  const sanitized = sanitizeDevice({...deviceFixture, maintenance_note: 'replace switch PSU next Tuesday'});
  assert.equal('maintenance_note' in sanitized, false);
  assert.equal(JSON.stringify(sanitized).includes('replace switch PSU'), false);
});

test('topology output omits raw discovery metadata', () => {
  const sanitized = sanitizeTopology({
    nodes: [{id: 1, label: 'server', metadata: {secret: true}}],
    edges: [{source: 1, target: 2, relationship_type: 'snmp', metadata: {community: 'private'}}],
  });
  assert.equal('metadata' in (sanitized.nodes as Record<string, unknown>[])[0]!, false);
  assert.equal('metadata' in (sanitized.edges as Record<string, unknown>[])[0]!, false);
});

test('service output removes URL credentials and credential-bearing components', () => {
  const sanitized = sanitizeService({
    id: 7,
    name: 'Admin portal',
    url: 'https://operator:secret@example.test/admin?access_token=private#invite=private',
  });

  assert.equal(sanitized.url, 'https://example.test/admin');
  assert.equal(JSON.stringify(sanitized).includes('secret'), false);
  assert.equal(JSON.stringify(sanitized).includes('private'), false);
});

test('network change output redacts private note values using the API field_name contract', () => {
  const sanitized = sanitizeNetworkChange({
    id: 9,
    device_id: 1,
    event_type: 'device_updated',
    field_name: 'notes',
    old_value: 'private old note',
    new_value: 'private new note',
  });

  assert.equal(sanitized.field, 'notes');
  assert.equal('old_value' in sanitized, false);
  assert.equal('new_value' in sanitized, false);
});
