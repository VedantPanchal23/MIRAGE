import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  vus: 1,
  iterations: 100,
  thresholds: {
    http_req_duration: ['p(95)<3000', 'p(99)<4000'],
    http_req_failed: ['rate<0.01'],
  },
};

const BASE_URL = __ENV.MIRAGE_BASE_URL || 'http://localhost:8000';

export default function () {
  const payload = JSON.stringify({
    prompt: 'Tell me about the discovery of penicillin.',
    response: 'Penicillin was discovered by Alexander Fleming in London in 1928.',
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
    'has hrs score': (r) => JSON.parse(r.body).hrs_result.hrs !== undefined,
  });

  sleep(0.05);
}
