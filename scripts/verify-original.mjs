import { readFile, readdir, mkdir, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { resolve, relative } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const baseline = JSON.parse((await readFile(resolve(root, 'reports/appwrite-baseline.json'), 'utf8')).replace(/^\uFEFF/, ''));
const excludedDirs = new Set(['node_modules', 'dist', '.local', 'test-results', 'playwright-report']);
const changed = [], missing = [], added = [];
for (const file of baseline.files) {
  try {
    const actual = createHash('sha256').update(await readFile(resolve(baseline.root, file.path))).digest('hex');
    if (actual !== file.sha256) changed.push(file.path);
  } catch (error) { if (error.code === 'ENOENT') missing.push(file.path); else throw error; }
}
async function visit(folder) {
  for (const entry of await readdir(folder, { withFileTypes: true })) {
    const path = resolve(folder, entry.name);
    if (entry.isDirectory()) { if (!excludedDirs.has(entry.name)) await visit(path); }
    else if (!/^\.env($|\.)/.test(entry.name)) {
      const name = relative(baseline.root, path).replaceAll('\\', '/');
      if (!baseline.files.some(file => file.path === name)) added.push(name);
    }
  }
}
await visit(baseline.root);
const result = { checkedAt: new Date().toISOString(), originalRoot: baseline.root,
  comparedFiles: baseline.files.length, changed, missing, added,
  unchanged: !changed.length && !missing.length && !added.length,
  scope: 'All original files except dependency/build/cache/test-output directories and .env files. Cloud state was not modified or compared.' };
await mkdir(resolve(root, 'reports'), { recursive: true });
await writeFile(resolve(root, 'reports/appwrite-preservation.json'), JSON.stringify(result, null, 2) + '\n');
console.log(JSON.stringify({ unchanged: result.unchanged, comparedFiles: result.comparedFiles, changed, missing, added }));
if (!result.unchanged) process.exitCode = 1;
