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

// --- 17.4: the instance runs itself, with a pinned k6 and a byte budget ------

test('k6 is pinned by version and a 64-hex sha256 in the module and the root', () => {
  const sha = /default\s+=\s+"([0-9a-f]{64})"/;
  const mod = read('variables.tf');
  const root = readFileSync(join(terraformDir, 'envs', 'dev-launch', 'variables.tf'), 'utf8');
  const modSha = mod.match(/variable "k6_sha256"[\s\S]*?default\s+=\s+"([0-9a-f]{64})"/);
  const rootSha = root.match(/variable "k6_sha256"[\s\S]*?default\s+=\s+"([0-9a-f]{64})"/);
  assert.ok(modSha && rootSha, 'k6_sha256 default must be 64 hex');
  assert.equal(modSha[1], rootSha[1]);
  assert.ok(sha.test(mod));
  const ver = (t) => t.match(/variable "k6_version"[\s\S]*?default\s+=\s+"(\d+\.\d+\.\d+)"/)?.[1];
  assert.ok(ver(mod));
  assert.equal(ver(mod), ver(root));
});

test('user data checks the k6 sha256, sets the nftables quota and fails closed', () => {
  const ud = read('user_data.sh.tftpl');
  assert.match(ud, /sha256sum -c -/);
  assert.match(ud, /quota over "\$BUDGET_BYTES" bytes drop/);
  assert.match(ud, /\[ "\$BUDGET_BYTES" -gt 0 \]/);
  assert.match(ud, /\[ -n "\$K6_VERSION" \] && \[ -n "\$K6_SHA256" \]/);
  assert.match(ud, /trap .*shutdown -h now/);
  assert.ok(!/^\s*set -x/m.test(ud), 'no trace output: the cookies pass through');
  assert.ok(ud.indexOf('quota over') < ud.indexOf('k6 run'), 'the quota is set before k6 runs');
});

test('the instance needs a byte budget and the role has one isolated results/* write', () => {
  const gen = read('load_gen.tf');
  assert.match(gen, /precondition\s*\{[\s\S]*?var\.budget_bytes > 0/);
  const stmts = [...gen.matchAll(/Sid\s+=\s+"([^"]+)"[\s\S]*?Resource\s+=\s+(\[[^\]]*\]|"[^"]*")/g)];
  const withResults = stmts.filter((m) => m[2].includes('/results/'));
  assert.equal(withResults.length, 1, 'exactly one statement names results/*');
  assert.equal(withResults[0][1], 'ResultsWrite');
  assert.ok(!withResults[0][2].includes('build/') && !withResults[0][2].includes('patch/'));
  assert.match(gen, /Sid\s+=\s+"ResultsWrite"\s+Effect\s+=\s+"Allow"\s+Action\s+=\s+"s3:PutObject"/);
  // nothing else gained a write: the other PutObject statement is build/ and patch/ only
  assert.equal((gen.match(/"s3:PutObject"/g) || []).length, 2);
});

test('the public key ID is an output of the module and the root', () => {
  assert.match(read('outputs.tf'), /output "public_key_id"[\s\S]*aws_cloudfront_public_key\.this\.id/);
  const root = readFileSync(join(terraformDir, 'envs', 'dev-launch', 'outputs.tf'), 'utf8');
  assert.match(root, /output "public_key_id"/);
  assert.match(read('variables.tf'), /variable "budget_bytes"/);
  assert.match(read('variables.tf'), /variable "shutdown_margin_minutes"[\s\S]*?default\s+=\s+30/);
});

test('user data seeds content-addressed sets with seed.py and runs each run with its manifest', () => {
  const ud = read('user_data.sh.tftpl');
  assert.match(ud, /seed\.py" "\$SCN\/sets\.json" "\$set_name" "\$MANIFEST_DIR" --bucket "\$BUILD_BUCKET"/);
  assert.ok(!ud.includes('/dev/urandom'), 'chunks come from seed.py, not a repeated seed file');
  assert.match(ud, /-e "RUN_INDEX=\$idx"/);
  assert.match(ud, /-e "MANIFEST_DIR=\$MANIFEST_DIR"/);
  assert.match(ud, /results\/\$name-\$idx\.json/);
  assert.ok(ud.indexOf('seed.py') < ud.indexOf('k6 run'), 'seed before k6 runs');
  assert.ok(ud.indexOf('results/seeded') < ud.indexOf('k6 run'));
});

test('the public key is normalised to one trailing newline, so the session PEM never forces a replacement', () => {
  const main = read('main.tf');
  assert.match(main, /public_key_pem\s+=\s+"\$\{trimspace\(coalesce\(var\.public_key_pem, file\("\$\{path\.module\}\/default_public_key\.pem"\)\)\)\}\\n"/);
  assert.match(main, /encoded_key = local\.public_key_pem/);
});

test('user data writes the nftables table to results/nft.txt before the done marker', () => {
  const ud = read('user_data.sh.tftpl');
  const nft = ud.indexOf('nft list table inet cerberus_launch | aws s3 cp - "s3://$BUILD_BUCKET/results/nft.txt"');
  assert.ok(nft > 0, 'nft.txt is written');
  assert.ok(nft > ud.indexOf('k6 run'), 'after the run, so the counter is read');
  assert.ok(nft < ud.indexOf('results/done'), 'before the done marker');
  assert.match(ud, /results\/nft\.txt" --only-show-errors \\\n  \|\| echo/, 'a failure does not block done');
});

test('user data writes a window file per sub-run before its k6 summary, and a failure does not block the run', () => {
  const ud = read('user_data.sh.tftpl');
  const start = ud.indexOf('start_ms=$(date +%s%3N)');
  const win = ud.indexOf('results/$name-$idx.window.json');
  const summary = ud.indexOf('"/tmp/$name-$idx.json" "s3://$BUILD_BUCKET/results/$name-$idx.json"');
  assert.ok(start > 0 && start < ud.indexOf('k6 run'), 'start is read before k6 runs');
  assert.ok(ud.indexOf('end_ms=$(date +%s%3N)') > ud.indexOf('download.js'), 'end is read after k6');
  assert.ok(win > 0 && win < summary, 'the window is uploaded before the k6 summary');
  assert.match(ud, /\{"run":"%s-%s","start_ms":%s,"end_ms":%s\}/);
  assert.match(ud, /\.window\.json" --only-show-errors \\\n\s+\|\| echo "window evidence not written" >&2/, 'a failure does not block the run');
});
