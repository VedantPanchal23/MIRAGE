import test from 'node:test';
import assert from 'node:assert/strict';
import { MirageClient, MirageAuthenticationError } from '../index.js';

test('MirageClient instantiation requires non-empty apiKey', () => {
  assert.throws(
    () => new MirageClient({ apiKey: '' }),
    (err) => err instanceof MirageAuthenticationError
  );
  assert.throws(
    () => new MirageClient({ apiKey: '   ' }),
    (err) => err instanceof MirageAuthenticationError
  );
});

test('MirageClient sets default baseUrl and properties', () => {
  const client = new MirageClient({
    apiKey: 'mirage_test_key_123',
    baseUrl: 'http://localhost:8000/',
    tenantId: 'tenant_test',
  });

  assert.equal(client.baseUrl, 'http://localhost:8000');
  assert.equal(client.apiKey, 'mirage_test_key_123');
  assert.equal(client.tenantId, 'tenant_test');
  assert.equal(client.timeout, 30000);
});

test('MirageClient verify sends proper request structure', async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => {
    globalThis.fetch = originalFetch;
  });

  let interceptedUrl = '';
  let interceptedHeaders = {};
  let interceptedBody = null;

  globalThis.fetch = async (url, options) => {
    interceptedUrl = url;
    interceptedHeaders = options.headers;
    interceptedBody = JSON.parse(options.body);

    return {
      ok: true,
      status: 200,
      json: async () => ({
        request_id: 'req_12345',
        hrs_result: { hrs: 0.12, tier: 'LOW', conformal_interval: { lower: 0.08, upper: 0.16 } },
        verified_response: 'All verified.',
      }),
    };
  };

  const client = new MirageClient({
    apiKey: 'test_key',
    baseUrl: 'http://localhost:8000',
    tenantId: 'tenant_demo',
  });

  const res = await client.verify({
    prompt: 'Check compliance',
    response: 'Compliant.',
  });

  assert.equal(interceptedUrl, 'http://localhost:8000/v1/verify');
  assert.equal(interceptedHeaders['X-API-Key'], 'test_key');
  assert.equal(interceptedBody.prompt, 'Check compliance');
  assert.equal(interceptedBody.response, 'Compliant.');
  assert.equal(res.request_id, 'req_12345');
  assert.equal(res.hrs_result.hrs, 0.12);
});

test('MirageClient verifyStream parses SSE events correctly', async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => {
    globalThis.fetch = originalFetch;
  });

  const sseChunks = [
    'event: connected\ndata: {"trace_id": "tr_1"}\n\n',
    'event: claims_extracted\ndata: {"claims_count": 1}\n\n',
    'event: claim_verified\ndata: {"claim_id": "c1", "status": "SUPPORTED", "attribution": {"rav": 0.9}}\n\n',
    'event: verification_complete\ndata: {"hrs_score": 0.05, "risk_tier": "LOW"}\n\n',
  ];

  globalThis.fetch = async () => {
    let index = 0;
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      pull(controller) {
        if (index < sseChunks.length) {
          controller.enqueue(encoder.encode(sseChunks[index++]));
        } else {
          controller.close();
        }
      },
    });

    return {
      ok: true,
      status: 200,
      body: stream,
    };
  };

  const client = new MirageClient({ apiKey: 'test_key' });
  const events = [];

  for await (const event of client.verifyStream({ prompt: 'test', response: 'test' })) {
    events.push(event);
  }

  assert.equal(events.length, 4);
  assert.equal(events[0].event, 'connected');
  assert.equal(events[0].data.trace_id, 'tr_1');
  assert.equal(events[1].event, 'claims_extracted');
  assert.equal(events[1].data.claims_count, 1);
  assert.equal(events[2].event, 'claim_verified');
  assert.equal(events[2].data.status, 'SUPPORTED');
  assert.equal(events[3].event, 'verification_complete');
  assert.equal(events[3].data.hrs_score, 0.05);
});
