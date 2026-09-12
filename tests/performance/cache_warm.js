import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  vus: 5,
  iterations: 50,
};

const BASE_URL = __ENV.MIRAGE_BASE_URL || 'http://localhost:8000';

const PROMPTS = [
  'What is the capital of France?',
  'Who discovered penicillin?',
  'When did Apollo 11 land on the Moon?',
  'What is the chemical symbol for gold?',
  'Who wrote Hamlet?',
];

export default function () {
  const prompt = PROMPTS[__ITER % PROMPTS.length];
  const payload = JSON.stringify({
    prompt: prompt,
    response: `${prompt} is a well-known factual question with a verified answer.`,
    tenant_id: 'cache_test_tenant',
  });

  const params = {
    headers: {
      'Content-Type': 'application/json',
      'X-Tenant-ID': 'cache_test_tenant',
      'X-API-Key': 'dev_key_default',
    },
  };

  const res = http.post(`${BASE_URL}/v1/verify`, payload, params);

  check(res, {
    'status is 200': (r) => r.status === 200,
  });

  sleep(0.02);
}
