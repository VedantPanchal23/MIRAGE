"""Example 1: Basic Verification with MIRAGE Python SDK (Gate 4 Output Assurance).

Demonstrates:
- Client configuration using environment credentials without logging them.
- Submitting text for verification to POST /v1/verify.
- Interpreting typed results: HRS, risk tier, conformal interval, claims decomposition.
"""

import os
import sys

from mirage_sdk import MirageAuthenticationError, MirageClient, MirageValidationError


def main() -> None:
    api_key = os.environ.get("MIRAGE_API_KEY", "mirage_test_key_sample")
    base_url = os.environ.get("MIRAGE_BASE_URL", "http://localhost:8000")

    print(f"Connecting to MIRAGE gateway at {base_url} (API Key: [CONFIGURED])...")

    try:
        with MirageClient(api_key=api_key, base_url=base_url) as client:
            prompt = "What is the primary function of ribosomes in a biological cell?"
            response = "Ribosomes are responsible for protein synthesis by translating messenger RNA."

            print(f"\nSubmitting prompt: {prompt}")
            print(f"Candidate response: {response}")

            result = client.verify(prompt=prompt, response=response)

            print("\n--- Gate 4 Verification Results ---")
            print(f"Request ID:           {result.request_id}")
            print(f"Verified Response:    {result.verified_response}")
            print(f"Hallucination Risk:   {result.hrs_result.hrs:.4f}")
            print(f"Operational Tier:     {result.hrs_result.tier}")
            ci = result.hrs_result.conformal_interval
            print(f"95% Conformal Bounds: [{ci.lower:.4f}, {ci.upper:.4f}] (width: {ci.width:.4f})")
            print(f"Claims Evaluated:     {result.hrs_result.claims_count}")
            print(f"Latency:              {result.hrs_result.computation_latency_ms:.2f} ms")

            for idx, c in enumerate(result.claims, 1):
                print(f"  Claim {idx}: '{c.claim.text}' -> Verdict: {c.status} (risk: {c.risk_score:.3f})")

    except MirageAuthenticationError:
        print("\n[ERROR] Authentication failed: verify your MIRAGE_API_KEY is valid.")
        sys.exit(1)
    except MirageValidationError as exc:
        print(f"\n[ERROR] Request validation failed: {exc.message}")
        sys.exit(1)


if __name__ == "__main__":
    main()
