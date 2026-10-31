import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { pythonExecutable } from './python.mjs';

const root = resolve(import.meta.dirname, '..');
const python = pythonExecutable();
const checks = [
  [process.execPath, ['--test', 'tests/exporter.test.mjs', 'runtime/validate-kestra.test.mjs']],
  [python, ['-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py', '-v']],
  [python, ['scripts/check_blueprint.py']],
];
if (existsSync(resolve(root, 'reports/appwrite-baseline.json'))) {
  checks.push([process.execPath, ['scripts/verify-original.mjs']]);
}
for (const [command, args] of checks) {
  const result = spawnSync(command, args, { cwd: root, stdio: 'inherit', windowsHide: true });
  if (result.status !== 0) { process.exitCode = result.status ?? 1; break; }
}
