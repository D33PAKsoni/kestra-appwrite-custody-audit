import { mkdir, readdir, writeFile, readFile, copyFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { existsSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';

const root = resolve(import.meta.dirname, '..');
const dist = resolve(root, 'dist');
await mkdir(dist, { recursive: true });
const sourceFiles = ['README.md', 'LICENSE', 'ATTRIBUTION.md', '.gitignore', 'package.json', 'package-lock.json', 'requirements-dev.txt',
  '.github', 'ci', 'companion', 'docs', 'fixtures', 'flows', 'scripts', 'tests',
  'runtime/README.md', ...(await readdir(resolve(root, 'runtime'))).filter(name => /\.(mjs|py|ps1)$/.test(name)).map(name => 'runtime/' + name)];
for (const file of ['reports/VERIFICATION.md', 'reports/blueprint-local-check.json', 'reports/local-scenarios',
  'reports/unit-checks.txt', 'reports/kestra-runtime-validation.json', 'reports/kestra-local-engine.json', 'reports/kestra-artifacts',
  'reports/LIVE_VERIFICATION.md', 'reports/PUBLICATION_PREPARATION.md', 'reports/live-provision.json', 'reports/live-deployment.json', 'reports/live-transport.json',
  'reports/live-security.json', 'reports/live-kestra.json', 'reports/live-kestra-inconsistent.json', 'reports/live-kestra-incomplete.json',
  'reports/live-restoration.json', 'reports/live-final-state.json', 'reports/live-engine-artifacts']) {
  if (existsSync(resolve(root, file))) sourceFiles.push(file);
}
// No .env, local runtime, dependencies, session files or original application source enters either archive.
const outputs = [
  ['kestra-labrelay-source.tar.gz', ['--exclude=__pycache__', '--exclude=*.pyc', ...sourceFiles]],
  ['appwrite-audit-companion.tar.gz', ['companion', 'package.json', 'package-lock.json', 'LICENSE', 'ATTRIBUTION.md']],
];
const manifest = [];
for (const [source, name] of [
  ['flows/appwrite-custody-audit.yaml', 'appwrite-custody-audit.catalog.yaml'],
  ['.local/appwrite-custody-audit.runtime.yaml', 'appwrite-custody-audit.runtime.yaml'],
]) {
  await copyFile(resolve(root, source), resolve(dist, name));
  const bytes = await readFile(resolve(dist, name));
  manifest.push({ file: name, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex') });
}
for (const [name, files] of outputs) {
  const destination = resolve(dist, name);
  const result = spawnSync('tar', ['-czf', destination, '-C', root, ...files], { cwd: root, stdio: 'inherit', windowsHide: true });
  if (result.status !== 0) throw new Error(`Could not package ${name}.`);
  const bytes = await readFile(destination);
  manifest.push({ file: name, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex') });
}
await writeFile(resolve(dist, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n');
console.log(JSON.stringify(manifest, null, 2));
