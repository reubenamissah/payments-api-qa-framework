// k6 load test: authenticated users each create two accounts, then send transfers in a loop.
// Run:  k6 run -e BASE_URL=http://localhost:8000 perf/transfers.js
// Start the API with a high RATE_LIMIT_PER_MINUTE, otherwise the limiter (correctly) returns 429.
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Rate } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const transferDuration = new Trend('transfer_duration', true);
const transferSuccess = new Rate('transfer_success');

export const options = {
  stages: [
    { duration: __ENV.RAMP_UP || '10s', target: Number(__ENV.VUS || 20) },
    { duration: __ENV.HOLD || '20s', target: Number(__ENV.VUS || 20) },
    { duration: __ENV.RAMP_DOWN || '5s', target: 0 },
  ],
  thresholds: {
    http_req_failed: ['rate<0.01'],             // under 1% errors
    http_req_duration: ['p(95)<500'],           // 95% of requests under 500 ms
    'transfer_duration': ['p(95)<500', 'p(99)<1000'],
    transfer_success: ['rate>0.99'],
    checks: ['rate>0.99'],
  },
};

const json = { 'Content-Type': 'application/json' };
let session; // per virtual user, created on its first iteration

function setupSession() {
  const auth = http.post(`${BASE_URL}/auth/token`,
    JSON.stringify({ client_id: 'qa-client', client_secret: 'qa-secret' }), { headers: json });
  const headers = { ...json, Authorization: `Bearer ${auth.json('access_token')}` };
  const create = (balance) => http.post(`${BASE_URL}/accounts`,
    JSON.stringify({ owner_name: `VU ${__VU}`, currency: 'NGN', initial_balance: balance }),
    { headers }).json('id');
  return { headers, source: create(1_000_000_000), destination: create(0) };
}

export default function () {
  session = session || setupSession();

  const res = http.post(`${BASE_URL}/transfers`, JSON.stringify({
    source_account_id: session.source,
    destination_account_id: session.destination,
    amount: 10,
    currency: 'NGN',
    narration: 'k6 load test',
  }), {
    headers: { ...session.headers, 'Idempotency-Key': `k6-${__VU}-${__ITER}-${Date.now()}` },
    tags: { name: 'POST /transfers' },
  });

  const ok = check(res, {
    'transfer created (201)': (r) => r.status === 201,
    'status is COMPLETED': (r) => r.json('status') === 'COMPLETED',
  });
  transferDuration.add(res.timings.duration);
  transferSuccess.add(ok);

  const read = http.get(`${BASE_URL}/accounts/${session.destination}`, {
    headers: session.headers, tags: { name: 'GET /accounts/{id}' } });
  check(read, { 'account readable (200)': (r) => r.status === 200 });

  sleep(0.1);
}
