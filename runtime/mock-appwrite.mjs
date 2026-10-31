// Fictional transport harness for local engine tests. This is NOT Appwrite.
import http from 'node:http';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const privateRoot = resolve(import.meta.dirname, 'private');
await mkdir(privateRoot, { recursive: true });
const state = { scope: 'Fictional local HTTP harness, not Appwrite', logins: 0, jwts: 0, exports: 0, logouts: 0, activeSessions: 0 };
const sessions = new Set();
const persist = () => writeFile(resolve(privateRoot, 'mock-observations.json'), JSON.stringify(state, null, 2));
const server = http.createServer(async (req, res) => {
  const reply = (code, body, headers = {}) => {
    res.writeHead(code, { 'Content-Type': 'application/json', ...headers });
    res.end(JSON.stringify(body));
  };
  try {
    const parts = [];
    for await (const chunk of req) { parts.push(chunk); if (parts.reduce((n, part) => n + part.length, 0) > 65536) throw new Error('body limit'); }
    const body = parts.length ? JSON.parse(Buffer.concat(parts).toString()) : {};
    const cookie = (req.headers.cookie || '').match(/a_session_mock_project=([^;]+)/)?.[1];
    if (req.headers['x-appwrite-project'] !== 'mock_project') return reply(401, { error: 'mock project required' });
    if (req.method === 'POST' && req.url === '/v1/account/sessions/email') {
      if (body.email !== 'audit@example.invalid' || body.password !== 'MockOnly-aA1!') return reply(401, { error: 'mock identity required' });
      const token = 'fixture-session-' + (++state.logins);
      sessions.add(token); state.activeSessions = sessions.size;
      await persist();
      return reply(201, { $id: token }, { 'Set-Cookie': `a_session_mock_project=${token}; Path=/; HttpOnly` });
    }
    if (req.method === 'POST' && req.url === '/v1/account/jwts' && sessions.has(cookie)) {
      state.jwts++; await persist();
      return reply(201, { jwt: 'fixture-only-jwt' });
    }
    if (req.method === 'POST' && req.url === '/v1/functions/audit_export/executions' &&
        req.headers['x-appwrite-jwt'] === 'fixture-only-jwt' && !cookie && sessions.size > 0) {
      if (body.async !== false || body.path !== '/export' || body.method !== 'GET') return reply(400, { error: 'incorrect execution contract' });
      let scenario = { fixture: 'clean-ready', mode: 'clean' };
      try { scenario = JSON.parse(await readFile(resolve(privateRoot, 'mock-scenario.json'), 'utf8')); }
      catch (error) { if (error.code !== 'ENOENT') throw error; }
      if (!['clean-ready', 'missing-then-received'].includes(scenario.fixture)) throw new Error('unknown fictional fixture');
      const data = JSON.parse(await readFile(resolve(root, 'fixtures', scenario.fixture + '.json'), 'utf8'));
      if (scenario.mode === 'inconsistent') data.samples[0].custodianId = 'fictional-wrong-custodian';
      if (scenario.mode === 'incomplete') { data.complete = false; data.issues = [{ code: 'CONCURRENT_CHANGE', message: 'Fictional overlapping update.' }]; }
      state.exports++; await persist();
      return reply(201, { $id: 'fixture-execution', status: 'completed', responseStatusCode: 200, responseBody: JSON.stringify(data) });
    }
    if (req.method === 'DELETE' && req.url === '/v1/account/sessions/current' && sessions.has(cookie)) {
      sessions.delete(cookie); state.logouts++; state.activeSessions = sessions.size;
      await persist();
      res.writeHead(204); return res.end();
    }
    return reply(401, { error: 'unauthenticated fictional route' });
  } catch { return reply(500, { error: 'fictional harness failed' }); }
});
server.listen(18081, '127.0.0.1', () => console.log('Fictional Appwrite transport harness on loopback:18081; no cloud service contacted.'));
