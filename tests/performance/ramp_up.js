import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '1m', target: 20 },
    { duration: '2m', target: 50 },
    { duration: '2m', target: 100 },
  ],
  thresholds: {
    http_req_duration: ['p(95)<3000'],
    http_req_failed: ['rate<0.01'],
  },
};

const BASE_URL = __ENV.MIRAGE_BASE_URL || 'http://localhost:8000';

export default function () {
  const payload = JSON.stringify({
    prompt: 'What is the boiling point of water?',
    response: 'Water boils at 100 degrees Celsius at standard atmospheric pressure.',
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
  });

  sleep(0.1);
}
