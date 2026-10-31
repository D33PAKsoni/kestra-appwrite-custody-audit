import { Query } from 'node-appwrite';

export class ExportError extends Error {
  constructor(code, status, message) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

// Only application fields leave the server. Never export platform permissions,
// database identifiers, membership records, secrets or user account properties.
export function unpack(row) {
  return { ...Object.fromEntries(Object.entries(row).filter(([key]) => !key.startsWith('$'))), id: row.$id };
}

const issue = (code, message) => ({ code, message });
const signature = rows => JSON.stringify(rows.map(row => JSON.stringify(row)).sort());

async function membership(db, databaseId, actorId) {
  let row;
  try { row = await db.getRow({ databaseId, tableId: 'memberships', rowId: actorId }); }
  catch (error) {
    if (error.code !== 404) throw error;
  }
  if (!row || row.active !== true || typeof row.orgId !== 'string' || !row.orgId)
    throw new ExportError('FORBIDDEN', 403, 'An active organization membership is required.');
  return unpack(row);
}

/**
 * Fully cursor-page an indexed query, or mark the export incomplete. Counts and
 * duplicate IDs are checked so a broken/stale page can never silently pass.
 */
async function readPages(db, databaseId, tableId, filters, limits, issues) {
  const rows = [];
  const seen = new Set();
  let cursor;
  let expected;
  for (let page = 0; page < limits.maxPages; page++) {
    const result = await db.listRows({ databaseId, tableId,
      queries: [...filters, Query.orderAsc('$id'), Query.limit(limits.pageSize), ...(cursor ? [Query.cursorAfter(cursor)] : [])] });
    if (!Array.isArray(result.rows) || !Number.isSafeInteger(result.total) || result.total < 0)
      throw new ExportError('INVALID_BACKEND_RESPONSE', 502, 'The database returned an invalid page.');
    if (expected !== undefined && expected !== result.total)
      issues.push(issue('PAGE_SET_CHANGED', `The ${tableId} row count changed while reading pages.`));
    expected = result.total;
    if (!result.rows.length) {
      if (rows.length !== expected)
        issues.push(issue('INCOMPLETE_PAGE_SET', `Not all ${tableId} rows were returned.`));
      return rows;
    }
    for (const row of result.rows) {
      if (typeof row.$id !== 'string' || !row.$id)
        throw new ExportError('INVALID_BACKEND_RESPONSE', 502, 'The database returned a row without an ID.');
      if (seen.has(row.$id)) {
        issues.push(issue('DUPLICATE_PAGE_ROW', `A ${tableId} row appeared on more than one page.`));
        return rows;
      }
      seen.add(row.$id);
      rows.push(unpack(row));
    }
    if (rows.length >= expected) {
      if (rows.length !== expected)
        issues.push(issue('INCOMPLETE_PAGE_SET', `The ${tableId} row count does not match its pages.`));
      return rows;
    }
    cursor = result.rows.at(-1).$id;
  }
  issues.push(issue('EXPORT_LIMIT_REACHED', `The ${tableId} query exceeded the configured page limit.`));
  return rows;
}

function scoped(rows, orgId, tableId, issues) {
  const accepted = rows.filter(row => row.orgId === orgId);
  if (accepted.length !== rows.length)
    issues.push(issue('SCOPE_MISMATCH', `Excluded records outside the authorized organization from ${tableId}.`));
  return accepted;
}

function openReceipt(row, issues) {
  const { detailsJson, ...record } = row;
  try {
    const details = JSON.parse(detailsJson);
    if (!details || typeof details !== 'object' || Array.isArray(details)) throw new Error('invalid');
    return { ...record, details };
  } catch {
    issues.push(issue('INVALID_RECEIPT_DETAILS', 'A receipt contains invalid JSON details.'));
    return { ...record, details: null };
  }
}

/**
 * No writes or transactions. Guards cover app-mediated writes, which advance
 * the batch revision. This is a bounded consistency check, not a database-wide
 * transactional snapshot or protection against administrator edits.
 * Events/handoffs are reachable from current samples; orphan rows are outside
 * this export's coverage because the existing schema has no org-only index.
 */
export async function exportOrganization({ db, databaseId, actorId,
  now = () => new Date(), pageSize = 100, maxPages = 50, maxSamples = 500,
  maxAttempts = 2, maxChildRows = 20000, maxResponseBytes = 4 * 1024 * 1024 }) {
  for (const [name, value, max] of [['pageSize', pageSize, 100], ['maxPages', maxPages, 100],
    ['maxSamples', maxSamples, 10000], ['maxAttempts', maxAttempts, 3], ['maxChildRows', maxChildRows, 100000],
    ['maxResponseBytes', maxResponseBytes, 16 * 1024 * 1024]]) {
    if (!Number.isSafeInteger(value) || value < 1 || value > max)
      throw new Error(`Invalid exporter ${name}.`);
  }
  const member = await membership(db, databaseId, actorId);
  const orgId = member.orgId;
  const limits = { pageSize, maxPages };
  let snapshot;
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    const issues = [];
    const orgFilter = [Query.equal('orgId', orgId)];
    const read = (table, filters = orgFilter) => readPages(db, databaseId, table, filters, limits, issues);
    const batches = scoped(await read('batches'), orgId, 'batches', issues);
    const samplesBefore = scoped(await read('samples'), orgId, 'samples', issues);
    let samples = samplesBefore;
    if (samples.length > maxSamples) {
      samples = samples.slice(0, maxSamples);
      issues.push(issue('EXPORT_LIMIT_REACHED', 'The organization exceeds the configured sample limit.'));
    }
    const receipts = scoped(await read('batch_receipts'), orgId, 'batch_receipts', issues).map(row => openReceipt(row, issues));
    const handoffs = [];
    const events = [];
    for (const sample of samples) {
      if (handoffs.length + events.length >= maxChildRows) {
        issues.push(issue('EXPORT_LIMIT_REACHED', 'The export exceeds the configured related-record limit.'));
        break;
      }
      const filter = [Query.equal('sampleId', sample.id)];
      const children = [
        ['handoffs', handoffs, scoped(await read('handoffs', filter), orgId, 'handoffs', issues)],
        ['events', events, scoped(await read('events', filter), orgId, 'events', issues)],
      ];
      for (const [table, target, records] of children) {
        if (records.some(record => record.sampleId !== sample.id))
          issues.push(issue('REFERENCE_MISMATCH', `Excluded ${table} records referencing a different sample.`));
        const matching = records.filter(record => record.sampleId === sample.id);
        const remaining = maxChildRows - handoffs.length - events.length;
        target.push(...matching.slice(0, remaining));
        if (matching.length > remaining)
          issues.push(issue('EXPORT_LIMIT_REACHED', 'The export exceeds the configured related-record limit.'));
      }
    }
    const samplesAfter = scoped(await read('samples'), orgId, 'samples', issues);
    const batchesAfter = scoped(await read('batches'), orgId, 'batches', issues);
    const memberAfter = await membership(db, databaseId, actorId);
    if (memberAfter.orgId !== orgId)
      throw new ExportError('FORBIDDEN', 403, 'Organization membership changed during the export.');
    const stable = signature(samplesBefore) === signature(samplesAfter) && signature(batches) === signature(batchesAfter);
    if (!stable) issues.push(issue('CONCURRENT_CHANGE', 'Records changed during export; no consistency verdict is available.'));
    const deduplicatedIssues = [...new Map(issues.map(item => [item.code + item.message, item])).values()];
    snapshot = { schemaVersion: 1, orgId, collectedAt: now().toISOString(), complete: deduplicatedIssues.length === 0,
      consistency: 'batch-revision-guarded', attempts: attempt, issues: deduplicatedIssues,
      coverage: { eventsAndHandoffs: 'reachable-from-current-samples', orphanRowsChecked: false,
        administratorEditsGuarded: false },
      samples, handoffs, events, receipts, batches };
    if (Buffer.byteLength(JSON.stringify(snapshot), 'utf8') > maxResponseBytes) {
      snapshot.complete = false;
      snapshot.issues.push(issue('EXPORT_TOO_LARGE', 'The export exceeds the configured response-size limit; audit data was omitted.'));
      for (const field of ['samples', 'handoffs', 'events', 'receipts', 'batches']) snapshot[field] = [];
      return snapshot;
    }
    // Retry normal concurrent changes; structural/limit problems require action.
    if (stable && !issues.some(item => item.code === 'PAGE_SET_CHANGED')) return snapshot;
  }
  return snapshot;
}
