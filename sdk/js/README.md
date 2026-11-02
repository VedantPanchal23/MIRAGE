# @mirage-ai/sdk

Official, zero-dependency JavaScript & Node.js SDK for the **MIRAGE 3.0 Execution Assurance Platform**.

Governs AI agents before they act (Gate 1–3) and verifies AI outputs and real-world outcomes after they act (Gate 4–5).

---

## Installation

```bash
npm install @mirage-ai/sdk
```

*(Requires Node.js 18+ or any modern runtime with native `fetch`)*

---

## Quickstart

```javascript
import { MirageClient } from '@mirage-ai/sdk';

const client = new MirageClient({
  apiKey: process.env.MIRAGE_API_KEY,
  baseUrl: process.env.MIRAGE_BASE_URL || 'http://localhost:8000',
});

// 1. Gate 4: Factual Consistency & Hallucination Risk
const result = await client.verify({
  prompt: 'What is the corporate travel expense ceiling?',
  response: 'The travel expense ceiling is $500 per day without manager sign-off.',
});

console.log('Hallucination Risk Score:', result.hrs_result.hrs);
console.log('Risk Tier:', result.hrs_result.tier);
console.log('Conformal Interval:', result.hrs_result.conformal_interval);
```

---

## Real-Time SSE Streaming

Stream progressive claim-by-claim verification events in real time:

```javascript
for await (const { event, data } of client.verifyStream({
  prompt: 'Provide quarterly financial metrics',
  response: 'Revenue grew 14% to $2.1M. EBITDA margin expanded to 28%.',
})) {
  if (event === 'claims_extracted') {
    console.log(`Decomposed into ${data.claims_count} atomic propositions`);
  } else if (event === 'claim_verified') {
    console.log(`Claim: "${data.text}" -> Status: ${data.status} (RAV: ${data.attribution.rav})`);
  } else if (event === 'verification_complete') {
    console.log(`Completed with HRS: ${data.hrs_score} (${data.risk_tier})`);
  }
}
```

---

## Governed Actions & Reality Verification (Gate 3 & Gate 5)

```javascript
// Step 1: Propose Action (Gate 3 Policy & Concurrency Lease Check)
const proposal = await client.proposeAction({
  transaction_id: `tx_${Date.now()}`,
  tool_name: 'database.update_order_status',
  action_type: 'WRITE',
  target_resource: 'orders:ord_9981',
  parameters: { order_id: 'ord_9981', status: 'COMPLETED' },
});

if (proposal.decision === 'ALLOW') {
  // Step 2: Execute Action
  const execution = await client.executeAction(proposal.action_id);

  // Step 3: Independent Reality Verification (Gate 5)
  const outcome = await client.verifyOutcome({
    action_id: proposal.action_id,
    execution_result: execution.result,
    predicted_postconditions: { order_status: 'COMPLETED' },
  });

  console.log('Outcome status:', outcome.status); // VERIFIED_SUCCESS
}
```

---

## License

Apache-2.0
