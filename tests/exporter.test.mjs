import { test } from 'node:test';
import assert from 'node:assert/strict';
import { exportOrganization } from '../companion/exporter.mjs';
import { createHandler } from '../companion/function.mjs';

const row = (id, data) => ({ $id: id, $permissions: ['secret-permission'], $databaseId: 'private-db', ...data });
const sample = id => row(id, { orgId: 'org-a', batchId: 'batch-a', version: 0, custodianId: 'collector' });
const receipt = id => row(id, { orgId: 'org-a', batchId: 'batch-a', detailsJson: JSON.stringify({ items: [], missing: [] }) });

function database({ samples = [sample('s-001')], receipts = [], events = [], handoffs = [],
  batches = [row('batch-row', { orgId: 'org-a', batchId: 'batch-a', version: 1 })],
  member = row('actor', { orgId: 'org-a', role: 'receiver', active: true }), beforeList, onMember } = {}) {
  const tables = { samples, batch_receipts: receipts, events, handoffs, batches };
  const calls = [];
  let memberReads = 0;
  return { tables, calls,
    async getRow(args) {
      assert.equal(args.tableId, 'memberships');
      assert.equal(args.rowId, 'actor');
      const result = onMember?.(++memberReads, member) ?? member;
      if (!result) throw Object.assign(new Error('not found'), { code: 404 });
      return structuredClone(result);
    },
    async listRows(args) {
      calls.push(args);
      beforeList?.(args, tables, calls);
      const queries = args.queries.map(query => JSON.parse(query));
      const eq = queries.filter(query => query.method === 'equal');
      assert.equal(queries.find(query => query.method === 'orderAsc').attribute, '$id');
      let results = tables[args.tableId].filter(item => eq.every(query => query.values.includes(item[query.attribute])))
        .sort((a, b) => a.$id.localeCompare(b.$id));
      const total = results.length;
      const cursor = queries.find(query => query.method === 'cursorAfter')?.values[0];
      if (cursor) results = results.slice(results.findIndex(item => item.$id === cursor) + 1);
      const limit = queries.find(query => query.method === 'limit').values[0];
      return structuredClone({ total, rows: results.slice(0, limit) });
    },
    createRow() { assert.fail('Exporter must never write.'); },
    updateRow() { assert.fail('Exporter must never write.'); },
    createTransaction() { assert.fail('Exporter must never create a transaction.'); },
  };
}

test('cursor pagination includes more than 100 samples and more than 20 receipts', async () => {
  const samples = Array.from({ length: 105 }, (_, n) => sample(`s-${String(n).padStart(3, '0')}`));
  const receipts = Array.from({ length: 23 }, (_, n) => receipt(`r-${String(n).padStart(3, '0')}`));
  const db = database({ samples, receipts });
  const result = await exportOrganization({ db, databaseId: 'db', actorId: 'actor', now: () => new Date('2026-10-30T00:00:00Z') });
  assert.equal(result.complete, true);
  assert.equal(result.samples.length, 105);
  assert.equal(result.receipts.length, 23);
  assert.equal(result.collectedAt, '2026-10-30T00:00:00.000Z');
  assert.deepEqual(result.receipts[0].details, { items: [], missing: [] });
  assert.equal(result.samples[0].id, 's-000');
  assert.equal(JSON.stringify(result).includes('$permissions'), false);
  assert.equal(JSON.stringify(result).includes('private-db'), false);
  assert.equal(JSON.stringify(result).includes('detailsJson'), false);
});

test('uses existing sample indexes for histories and handoffs and never exports other organizations', async () => {
  const db = database({ samples: [sample('s-001'), row('s-other', { orgId: 'org-b' })],
    events: [row('e-a', { orgId: 'org-a', sampleId: 's-001', version: 0 }),
      row('e-b', { orgId: 'org-b', sampleId: 's-001', note: 'private-secret' })],
    handoffs: [row('h-b', { orgId: 'org-b', sampleId: 's-other' })],
    receipts: [receipt('r-a'), row('r-b', { orgId: 'org-b', detailsJson: '{}' })] });
  const result = await exportOrganization({ db, databaseId: 'db', actorId: 'actor' });
  assert.deepEqual(result.samples.map(item => item.id), ['s-001']);
  assert.deepEqual(result.events.map(item => item.id), ['e-a']);
  assert.deepEqual(result.receipts.map(item => item.id), ['r-a']);
  assert.equal(JSON.stringify(result).includes('private-secret'), false);
  assert.equal(result.complete, false);
  assert.ok(result.issues.some(item => item.code === 'SCOPE_MISMATCH'));
  const childQueries = db.calls.filter(call => ['events', 'handoffs'].includes(call.tableId));
  assert.ok(childQueries.every(call => call.queries.map(JSON.parse).some(query => query.method === 'equal' && query.attribute === 'sampleId')));
});

test('all pages of a sample history are exported', async () => {
  const db = database({ events: Array.from({ length: 105 }, (_, version) =>
    row(`e-${String(version).padStart(3, '0')}`, { orgId: 'org-a', sampleId: 's-001', version })) });
  const result = await exportOrganization({ db, databaseId: 'db', actorId: 'actor' });
  assert.equal(result.complete, true);
  assert.equal(result.events.length, 105);
});

test('retries when a custody mutation changes sample and batch revisions during collection', async () => {
  let changed = false;
  const db = database({ beforeList(args, tables) {
    if (!changed && args.tableId === 'events') {
      changed = true;
      tables.samples[0].version++;
      tables.batches[0].version++;
    }
  } });
  const result = await exportOrganization({ db, databaseId: 'db', actorId: 'actor' });
  assert.equal(result.complete, true);
  assert.equal(result.attempts, 2);
  assert.equal(result.samples[0].version, 1);
});

test('continual concurrent activity yields an inconclusive export after bounded retries', async () => {
  const db = database({ beforeList(args, tables) {
    if (args.tableId === 'events') { tables.samples[0].version++; tables.batches[0].version++; }
  } });
  const result = await exportOrganization({ db, databaseId: 'db', actorId: 'actor' });
  assert.equal(result.complete, false);
  assert.equal(result.attempts, 2);
  assert.ok(result.issues.some(item => item.code === 'CONCURRENT_CHANGE'));
});

test('new registration during export is detected by set/revision guards', async () => {
  let added = false;
  const db = database({ beforeList(args, tables) {
    if (!added && args.tableId === 'handoffs') {
      added = true;
      tables.samples.push(sample('s-002'));
      tables.batches[0].version++;
    }
  } });
  const result = await exportOrganization({ db, databaseId: 'db', actorId: 'actor' });
  assert.equal(result.complete, true);
  assert.equal(result.attempts, 2);
  assert.equal(result.samples.length, 2);
});

test('page and sample limits cannot silently become a healthy export', async () => {
  const db = database({ samples: Array.from({ length: 5 }, (_, n) => sample(`s-${n}`)) });
  const paged = await exportOrganization({ db, databaseId: 'db', actorId: 'actor', pageSize: 2, maxPages: 1 });
  assert.equal(paged.complete, false);
  assert.ok(paged.issues.some(item => item.code === 'EXPORT_LIMIT_REACHED'));
  const limited = await exportOrganization({ db, databaseId: 'db', actorId: 'actor', maxSamples: 2 });
  assert.equal(limited.complete, false);
  assert.equal(limited.samples.length, 2);
  assert.equal(limited.attempts, 1);
  assert.equal(limited.issues.some(item => item.code === 'CONCURRENT_CHANGE'), false);
});

test('related-record limits bound output and mark it incomplete', async () => {
  const db = database({ events: [0, 1, 2].map(version =>
    row(`e-${version}`, { orgId: 'org-a', sampleId: 's-001', version })) });
  const result = await exportOrganization({ db, databaseId: 'db', actorId: 'actor', maxChildRows: 2 });
  assert.equal(result.complete, false);
  assert.equal(result.events.length, 2);
  assert.ok(result.issues.some(item => item.code === 'EXPORT_LIMIT_REACHED'));
});

test('oversized response omits data and explicitly marks the export incomplete', async () => {
  const db = database({ events: [row('e-big', { orgId: 'org-a', sampleId: 's-001', note: 'a'.repeat(5000) })] });
  const result = await exportOrganization({ db, databaseId: 'db', actorId: 'actor', maxResponseBytes: 2000 });
  assert.equal(result.complete, false);
  for (const key of ['samples', 'events', 'handoffs', 'receipts', 'batches']) assert.deepEqual(result[key], []);
  assert.ok(result.issues.some(item => item.code === 'EXPORT_TOO_LARGE'));
});

test('duplicate cursor results cannot silently hide rows', async () => {
  const db = database({ samples: [sample('s-001'), sample('s-002')] });
  const original = db.listRows;
  db.listRows = async args => {
    const result = await original(args);
    if (args.tableId === 'samples' && args.queries.map(JSON.parse).some(query => query.method === 'cursorAfter'))
      result.rows = [sample('s-001')];
    return result;
  };
  const result = await exportOrganization({ db, databaseId: 'db', actorId: 'actor', pageSize: 1 });
  assert.equal(result.complete, false);
  assert.ok(result.issues.some(item => item.code === 'DUPLICATE_PAGE_ROW'));
});

test('invalid receipt JSON marks incomplete without exposing the stored JSON string', async () => {
  const db = database({ receipts: [row('r-bad', { orgId: 'org-a', detailsJson: 'invalid-private-text' })] });
  const result = await exportOrganization({ db, databaseId: 'db', actorId: 'actor' });
  assert.equal(result.complete, false);
  assert.equal(result.receipts[0].details, null);
  assert.ok(result.issues.some(item => item.code === 'INVALID_RECEIPT_DETAILS'));
  assert.equal(JSON.stringify(result).includes('invalid-private-text'), false);
});

test('inactive membership is denied before any record query', async () => {
  const db = database({ member: row('actor', { orgId: 'org-a', active: false }) });
  await assert.rejects(exportOrganization({ db, databaseId: 'db', actorId: 'actor' }), { code: 'FORBIDDEN', status: 403 });
  assert.equal(db.calls.length, 0);
});

test('membership revocation or organization switch during export returns no records', async () => {
  for (const change of [{ active: false }, { orgId: 'org-b' }]) {
    const db = database({ onMember(n, member) { return n > 1 ? { ...member, ...change } : member; } });
    await assert.rejects(exportOrganization({ db, databaseId: 'db', actorId: 'actor' }), { code: 'FORBIDDEN', status: 403 });
  }
});

const env = { APPWRITE_FUNCTION_API_ENDPOINT: 'https://example.invalid/v1', APPWRITE_FUNCTION_PROJECT_ID: 'project', APPWRITE_DATABASE_ID: 'database' };
const request = { method: 'GET', path: '/export', headers: { 'x-appwrite-user-jwt': 'jwt', 'x-appwrite-key': 'ephemeral-key' } };
async function invoke(handler, req = request) {
  const logged = [];
  const response = await handler({ req, res: { json: (body, status = 200) => ({ body, status }) }, error: value => logged.push(value) });
  return { ...response, logged };
}

test('handler denies unsupported routes/methods, organization query input, and missing JWT before creating a database client', async () => {
  const handler = createHandler({ env, verifyActor: () => assert.fail('Verification should not run.'), createDatabase: () => assert.fail('Database must not be constructed.') });
  assert.equal((await invoke(handler, { ...request, method: 'POST' })).status, 405);
  assert.equal((await invoke(handler, { ...request, path: '/commands' })).status, 404);
  assert.equal((await invoke(handler, { ...request, path: '/export?orgId=org-b' })).status, 404);
  assert.equal((await invoke(handler, { ...request, headers: { 'x-appwrite-user-id': 'actor', 'x-appwrite-key': 'key' } })).status, 401);
});

test('handler verifies JWT with Account and uses only the per-execution key', async () => {
  const handler = createHandler({ env: { ...env, APPWRITE_API_KEY: 'admin-do-not-use' },
    async verifyActor(args) { assert.equal(args.jwt, 'jwt'); return 'actor'; },
    createDatabase(args) { assert.equal(args.apiKey, 'ephemeral-key'); return database(); } });
  const response = await invoke(handler);
  assert.equal(response.status, 200);
  assert.equal(response.body.complete, true);
  assert.equal(JSON.stringify(response).includes('ephemeral-key'), false);
});

test('invalid JWT is rejected and backend failures do not disclose credentials or SDK bodies', async () => {
  const badJwt = createHandler({ env, verifyActor: async () => { throw new Error('secret-jwt'); }, createDatabase: () => assert.fail('Must not run.') });
  assert.equal((await invoke(badJwt)).status, 401);
  const failing = createHandler({ env, verifyActor: async () => 'actor', createDatabase: () => ({ getRow() { throw new Error('secret-key SDK body'); } }) });
  const response = await invoke(failing);
  assert.equal(response.status, 503);
  assert.equal(JSON.stringify(response).includes('secret-key'), false);
});

test('missing platform dynamic key cannot fall back to an administrator key', async () => {
  const handler = createHandler({ env: { ...env, APPWRITE_API_KEY: 'administrator' } });
  const response = await invoke(handler, { ...request, headers: { 'x-appwrite-user-jwt': 'jwt' } });
  assert.equal(response.status, 503);
});
