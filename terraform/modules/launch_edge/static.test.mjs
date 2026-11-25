// Offline static checks of the launch edge Terraform: node --test, no network.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const terraformDir = join(here, '..', '..');
const read = (p) => readFileSync(join(here, p), 'utf8');

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    if (name === '.terraform') return [];
    const p = join(dir, name);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}

test('no private key text anywhere under terraform/', () => {
  const marker = ['PRIVATE', 'KEY'].join(' ');
  for (const file of walk(terraformDir)) {
    if (file.endsWith('static.test.mjs')) continue;
    assert.ok(!readFileSync(file, 'utf8').includes(marker), `${file} has a private key`);
  }
});

test('the default PEM is one public key block', () => {
  const pem = read('default_public_key.pem');
  assert.match(pem, /^-----BEGIN PUBLIC KEY-----\n/);
  assert.match(pem, /-----END PUBLIC KEY-----\n$/);
});

test('log record_fields hold no excluded name', () => {
  const main = read('main.tf');
  const block = main.match(/log_fields = \[([\s\S]*?)\n  \]/);
  assert.ok(block, 'log_fields list not found');
  const fields = [...block[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]);
  assert.ok(fields.length > 0);
  for (const bad of ['c-ip', 'x-forwarded-for', 'c-port', 'cs(Cookie)', 'cs(Referer)', 'cs(User-Agent)']) {
    assert.ok(!fields.includes(bad), `${bad} must not be logged`);
  }
  assert.ok(fields.includes('x-edge-request-id'));
});

test('every log field is in the verified CloudFront v2 list', () => {
  const verified = ['timestamp(ms)', 'x-edge-request-id', 'x-edge-location', 'x-edge-result-type',
    'x-edge-response-result-type', 'x-edge-detailed-result-type', 'sc-status', 'sc-bytes',
    'cs-method', 'cs-uri-stem', 'time-taken', 'time-to-first-byte', 'cs-protocol'];
  const main = read('main.tf');
  const block = main.match(/log_fields = \[([\s\S]*?)\n  \]/);
  const fields = [...block[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]);
  for (const f of fields) assert.ok(verified.includes(f), `${f} is not a verified field`);
  assert.ok(fields.includes('timestamp(ms)'));
  assert.ok(!fields.includes('timestamp'));
});

test('log delivery sets suffix_path with no account ID', () => {
  const main = read('main.tf');
  const m = main.match(/s3_delivery_configuration \{\s*suffix_path\s+=\s+"([^"]*)"/);
  assert.ok(m, 'suffix_path not found');
  assert.equal(m[1], '{DistributionId}/{yyyy}/{MM}/{dd}/{HH}');
  assert.ok(!/account/i.test(m[1]));
  assert.ok(!/enable_hive_compatible_path\s+=\s+true/.test(main));
});

test('every behaviour is signed and there is no Origin Shield', () => {
  const main = read('main.tf');
  const behaviours = (main.match(/(default_cache_behavior|ordered_cache_behavior) \{/g) || []).length;
  const signed = (main.match(/trusted_key_groups\s+=/g) || []).length;
  assert.ok(behaviours > 0);
  assert.ok(signed > 0);
  assert.equal(signed, behaviours);
  assert.ok(!main.includes('origin_shield {'));
});

test('the load generator is gated, one-time Spot, with no broad SSM policy', () => {
  const gen = read('load_gen.tf');
  assert.match(gen, /create_load_gen \? 1 : 0/);
  assert.match(gen, /spot_instance_type\s+=\s+"one-time"/);
  assert.ok(!gen.includes('policy_arn'), 'no managed policy on the load generator role');
  assert.match(gen, /volume_tags/);
});

test('names match the cerberus-admin launch policy', () => {
  const all = ['main.tf', 'load_gen.tf'].map(read).join('\n');
  // The bucket names come from locals, not name = "...".
  const buckets = [...all.matchAll(/(?:build|logs)_bucket_name\s+=\s+"([^"$]+)/g)].map((m) => m[1]);
  assert.equal(buckets.length, 2);
  for (const b of buckets) assert.ok(b.startsWith('cerberus-platform-launch-'), `bucket ${b}`);
  for (const m of all.matchAll(/\bname(?:_prefix)?\s+=\s+"([^"$]+)"/g)) {
    if (m[1].startsWith('Managed-') || m[1].startsWith('/aws/')) continue;
    assert.ok(m[1].startsWith('cerberus-launch-'), `name ${m[1]}`);
  }
});

test('the environment root sets Stack=dev-launch and Project as default tags', () => {
  const provider = readFileSync(join(terraformDir, 'envs', 'dev-launch', 'provider.tf'), 'utf8');
  assert.match(provider, /Stack\s+=\s+"dev-launch"/);
  assert.match(provider, /Project\s+=\s+"cerberus-platform"/);
});
