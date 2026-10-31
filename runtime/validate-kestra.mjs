import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';

// The default operation only validates YAML; it never imports or updates a flow.
// API paths verified against Kestra's official FlowController/ExecutionController.
export function settings(env = process.env) {
  if (!env.KESTRA_URL) throw new Error('Set KESTRA_URL to your Kestra instance URL.');
  const url = new URL(env.KESTRA_URL);
  if (url.username || url.password || url.search || url.hash) throw new Error('Use a base URL without credentials, query or fragment.');
  if (url.protocol !== 'https:' && !(url.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname))) {
    throw new Error('Use HTTPS for a remote Kestra instance.');
  }
  const tenant = env.KESTRA_TENANT || 'main';
  if (!/^[A-Za-z0-9_.-]+$/.test(tenant)) throw new Error('Invalid KESTRA_TENANT.');
  const headers = { Accept: 'application/json' };
  if (env.KESTRA_API_TOKEN) headers.Authorization = `Bearer ${env.KESTRA_API_TOKEN}`;
  else if (env.KESTRA_USERNAME || env.KESTRA_PASSWORD) {
    if (!env.KESTRA_USERNAME || !env.KESTRA_PASSWORD) throw new Error('Set both KESTRA_USERNAME and KESTRA_PASSWORD.');
    headers.Authorization = `Basic ${Buffer.from(`${env.KESTRA_USERNAME}:${env.KESTRA_PASSWORD}`).toString('base64')}`;
  }
  return { base: `${url.href.replace(/\/$/, '')}/api/v1/${encodeURIComponent(tenant)}`, headers };
}

export async function request(config, path, options = {}, fetchImpl = fetch) {
  let response;
  try {
    response = await fetchImpl(config.base + path, {
      ...options,
      headers: { ...config.headers, ...options.headers },
      redirect: 'error',
      signal: AbortSignal.timeout(30_000),
    });
  } catch {
    throw new Error('Kestra request failed: check reachability, TLS and authentication.');
  }
  if (!response.ok) throw new Error(`Kestra returned HTTP ${response.status}; inspect the instance UI for details.`);
  try { return await response.json(); }
  catch { throw new Error('Kestra returned an unexpected non-JSON response.'); }
}

export function validationSummary(result) {
  if (!Array.isArray(result) || !result.length) throw new Error('Kestra returned no per-flow validation result.');
  const flows = result.map(row => {
    if (!row || typeof row !== 'object' || !(Object.hasOwn(row, 'constraints') || Object.hasOwn(row, 'errors') || (typeof row.flow === 'string' && typeof row.namespace === 'string'))) throw new Error('Unexpected Kestra validation response shape.');
    const errors = row.errors == null ? [] : row.errors;
    if (!Array.isArray(errors)) throw new Error('Unexpected Kestra validation errors shape.');
    const constraints = row.constraints;
    if (constraints != null && typeof constraints !== 'string' && !Array.isArray(constraints)) throw new Error('Unexpected Kestra constraints shape.');
    const constraintCount = Array.isArray(constraints) ? constraints.length : constraints ? 1 : 0;
    return { errorCount: errors.length + constraintCount, warningCount: Array.isArray(row.warnings) ? row.warnings.length : 0 };
  });
  return { valid: flows.every(row => row.errorCount === 0), flows };
}

export async function main(args = process.argv.slice(2), env = process.env, fetchImpl = fetch) {
  if (args.includes('--help') || !args.length) {
    console.log('Validate only: node runtime/validate-kestra.mjs <flow.yaml> [--report <report.json>]');
    console.log('Run already imported flow: add --run-existing <namespace>/<id> [--inputs <inputs.json>]');
    console.log('Environment: KESTRA_URL, optional KESTRA_TENANT (main), KESTRA_API_TOKEN or KESTRA_USERNAME/KESTRA_PASSWORD.');
    return;
  }
  const yamlPath = args[0];
  if (yamlPath.startsWith('--')) throw new Error('The first argument must be a YAML file.');
  const options = {};
  for (let i = 1; i < args.length; i += 2) {
    if (!['--report', '--run-existing', '--inputs'].includes(args[i]) || !args[i + 1] || args[i + 1].startsWith('--')) throw new Error('Invalid command arguments; use --help.');
    options[args[i]] = args[i + 1];
  }
  if (options['--inputs'] && !options['--run-existing']) throw new Error('--inputs requires --run-existing.');
  const config = settings(env);
  const yaml = await readFile(resolve(yamlPath), 'utf8');
  const validated = validationSummary(await request(config, '/flows/validate', {
    method: 'POST', headers: { 'Content-Type': 'application/x-yaml' }, body: yaml,
  }, fetchImpl));
  const report = { checkedAt: new Date().toISOString(), sourceSha256: createHash('sha256').update(yaml).digest('hex'), engineValidated: true, ...validated, execution: null };
  if (validated.valid && options['--run-existing']) {
    const [namespace, id, extra] = options['--run-existing'].split('/');
    if (extra || !namespace || !id || !/^[A-Za-z0-9_.-]+$/.test(namespace) || !/^[A-Za-z0-9_-]+$/.test(id)) throw new Error('Use --run-existing namespace/flow-id.');
    const form = new FormData();
    const inputs = options['--inputs'] ? JSON.parse(await readFile(resolve(options['--inputs']), 'utf8')) : {};
    if (!inputs || Array.isArray(inputs) || typeof inputs !== 'object') throw new Error('Inputs must be a JSON object keyed by input ID.');
    for (const [key, value] of Object.entries(inputs)) form.set(key, typeof value === 'string' ? value : JSON.stringify(value));
    const created = await request(config, `/executions/${encodeURIComponent(namespace)}/${encodeURIComponent(id)}`, { method: 'POST', body: form }, fetchImpl);
    // Kestra 2 returns an execution wrapper; 1.x returned the execution directly.
    let execution = created.execution ?? created;
    const executionId = execution.id;
    if (typeof executionId !== 'string' || !/^[A-Za-z0-9_-]+$/.test(executionId)) throw new Error('Execution response did not include a valid execution ID.');
    const deadline = Date.now() + 300_000;
    const terminal = new Set(['SUCCESS', 'WARNING', 'FAILED', 'KILLED', 'CANCELLED']);
    while (!terminal.has(execution.state?.current) && Date.now() < deadline) {
      await new Promise(done => setTimeout(done, 2000));
      execution = await request(config, `/executions/${encodeURIComponent(executionId)}`, {}, fetchImpl);
    }
    report.execution = { id: executionId, namespace, flowId: id, state: execution.state?.current ?? 'UNKNOWN' };
    // Successful orchestration is not evidence that the audit found no anomalies.
    // Review its JSON/CSV artifacts and completeness before making that claim.
  }
  if (options['--report']) {
    const reportPath = resolve(options['--report']);
    await mkdir(resolve(reportPath, '..'), { recursive: true });
    await writeFile(reportPath, JSON.stringify(report, null, 2) + '\n');
  }
  console.log(JSON.stringify(report, null, 2));
  if (!validated.valid || (report.execution && report.execution.state !== 'SUCCESS')) process.exitCode = 1;
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().catch(error => { console.error(error.message); process.exitCode = 1; });
}
