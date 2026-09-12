import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  scenarios: {
    sustained: {
      executor: 'constant-vus',
      vus: 100,
      duration: '10m',
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<3000'],
    http_req_failed: ['rate<0.01'],
    http_reqs: ['rate>33'], // Throughput > 33 req/s
  },
};

const BASE_URL = __ENV.MIRAGE_BASE_URL || 'http://localhost:8000';

export default function () {
  const payload = JSON.stringify({
    prompt: 'Explain the theory of general relativity in one sentence.',
    response: 'General relativity posits that gravity is the curvature of spacetime caused by mass and energy.',
    tenant_id: 'perf_tenant',
  });

  const params = {
    headers: {
      'Content-Type': 'application/json',
      'X-Tenant-ID': 'perf_tenant',
      'X-API-Key': 'dev_key_default',
    },
  };

  const res = http.post(`${BASE_URL}/v1/verify`, payload, params);

  check(res, {
    'status is 200': (r) => r.status === 200,
    'verification completed': (r) => JSON.parse(r.body).claims.length > 0,
  });

  sleep(0.05);
}
