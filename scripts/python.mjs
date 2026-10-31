import { existsSync } from 'node:fs';
import { homedir } from 'node:os';
import { resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

export function pythonExecutable() {
  const candidates = [process.env.PYTHON_EXECUTABLE, 'python', 'python3',
    resolve(homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe')].filter(Boolean);
  for (const candidate of candidates) {
    const check = spawnSync(candidate, ['-c', 'import sys; assert sys.version_info >= (3, 10)'], { windowsHide: true });
    if (check.status === 0) return candidate;
  }
  throw new Error('Python 3.10+ is required. Set PYTHON_EXECUTABLE to its absolute executable path.');
}

if (process.argv[1] && resolve(process.argv[1]) === resolve(import.meta.filename)) {
  const result = spawnSync(pythonExecutable(), process.argv.slice(2), { stdio: 'inherit', windowsHide: true });
  process.exitCode = result.status ?? 1;
}
