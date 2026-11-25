// Offline test of license.js: node --test, no network. The CloudFront import
// line is stripped and the code runs in a vm with a stub KeyValueStore and a
// fixed clock.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, 'license.js'), 'utf8')
  .split('\n')
  .filter((line) => !line.startsWith("import cf from 'cloudfront'"))
  .join('\n');

const NOW = 1_800_000_000;

// get is (key) => value, or a function that throws.
function load(get) {
  const sandbox = {
    cf: { kvs: () => ({ get: async (key) => get(key) }) },
    Date: { now: () => NOW * 1000 },
  };
  vm.createContext(sandbox);
  return vm.runInContext(`${source}\n;handler;`, sandbox);
}

const call = async (get) => load(get)({ request: { uri: '/license' } });
const body = (res) => JSON.parse(res.body.data);

test('before release: 403', async () => {
  const res = await call(() => String(NOW + 1));
  assert.equal(res.statusCode, 403);
  assert.equal(body(res).released, false);
});

test('at exactly release_at: 200', async () => {
  const res = await call(() => String(NOW));
  assert.equal(res.statusCode, 200);
});

test('after release: 200 JSON, no-store', async () => {
  const res = await call(() => String(NOW - 3600));
  assert.equal(res.statusCode, 200);
  assert.equal(res.headers['content-type'].value, 'application/json');
  assert.equal(res.headers['cache-control'].value, 'no-store');
  assert.equal(body(res).released, true);
});

test('key missing: 403', async () => {
  const res = await call(() => undefined);
  assert.equal(res.statusCode, 403);
});

test('empty value: 403', async () => {
  const res = await call(() => '');
  assert.equal(res.statusCode, 403);
});

test('non-numeric value: 403', async () => {
  for (const v of ['abc', '12x', '-5', '1.5', ' ']) {
    const res = await call(() => v);
    assert.equal(res.statusCode, 403, `value ${JSON.stringify(v)}`);
  }
});

test('kvs.get throws: 403', async () => {
  const res = await call(() => {
    throw new Error('KeyNotFound');
  });
  assert.equal(res.statusCode, 403);
});
