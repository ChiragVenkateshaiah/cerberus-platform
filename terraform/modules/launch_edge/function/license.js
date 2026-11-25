// /license* viewer-request Function (cloudfront-js-2.0). It answers every
// request, so the S3 origin behind the behaviour is never read. The release
// time is the KeyValueStore key release_at, in epoch seconds, written by
// Terraform. It fails closed: a missing key, a value that is not whole
// digits, or any error gives 403.
import cf from 'cloudfront';

const kvs = cf.kvs();

function reply(statusCode, statusDescription, payload) {
  return {
    statusCode: statusCode,
    statusDescription: statusDescription,
    headers: {
      'content-type': { value: 'application/json' },
      'cache-control': { value: 'no-store' },
    },
    body: { encoding: 'text', data: JSON.stringify(payload) },
  };
}

async function handler(event) {
  try {
    const raw = await kvs.get('release_at');
    if (typeof raw !== 'string' || !/^[0-9]+$/.test(raw.trim())) {
      return reply(403, 'Forbidden', { released: false });
    }
    const releaseAt = Number(raw.trim());
    const now = Math.floor(Date.now() / 1000);
    if (now < releaseAt) {
      return reply(403, 'Forbidden', { released: false });
    }
    return reply(200, 'OK', { released: true });
  } catch (err) {
    return reply(403, 'Forbidden', { released: false });
  }
}
