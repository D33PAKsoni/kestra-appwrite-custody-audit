import { test } from 'node:test';
import assert from 'node:assert/strict';
import { settings, request, validationSummary } from './validate-kestra.mjs';

test('runtime helper rejects remote cleartext URLs and credentials in URLs', () => {
  assert.throws(() => settings({ KESTRA_URL: 'http://example.com' }), /HTTPS/);
  assert.throws(() => settings({ KESTRA_URL: 'https://user:pass@example.com' }), /without credentials/);
  assert.equal(settings({ KESTRA_URL: 'http://localhost:8080' }).base, 'http://localhost:8080/api/v1/main');
});

test('validation handles current constraints and structured errors without declaring failures valid', () => {
  assert.equal(validationSummary([{ flow: 'audit', namespace: 'test', constraints: null }]).valid, true);
  assert.equal(validationSummary([{ constraints: 'Unrecognized task type' }]).valid, false);
  assert.equal(validationSummary([{ errors: [{ message: 'Invalid field' }] }]).valid, false);
  assert.throws(() => validationSummary([]), /no per-flow/);
  assert.throws(() => validationSummary([{}]), /shape/);
});

test('runtime HTTP wrapper refuses redirects and does not expose server error bodies', async () => {
  const config = settings({ KESTRA_URL: 'https://example.com', KESTRA_API_TOKEN: 'private-token' });
  let observed;
  await assert.rejects(request(config, '/flows/validate', {}, async (url, options) => {
    observed = { url, options };
    return { ok: false, status: 401, text() { return 'private-token'; } };
  }), error => error.message.includes('HTTP 401') && !error.message.includes('private-token'));
  assert.equal(observed.options.redirect, 'error');
  assert.equal(observed.options.headers.Authorization, 'Bearer private-token');
});
