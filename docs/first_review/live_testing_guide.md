# MIRAGE: Faculty Live Testing & Execution Guide

**Institution:** Chandubhai S. Patel Institute of Technology (CSPIT)  
**Department:** Artificial Intelligence and Machine Learning  
**Investigators:** Vedant Panchal (`23AIML042`) & Dax Virani (`23AIML076`)  

---

## 1. Quick Setup in Terminal

Open PowerShell in the project directory:
```powershell
cd C:\Users\vedan\Desktop\MIRAGE
```

All commands below utilize the pre-configured local virtual environment:
```powershell
# Verify Python version and environment
.venv\Scripts\python --version
# Should output: Python 3.12.10
```

---

## 2. Testing Option A: Automated 3-Scenario Terminal Demonstration

Use this option to give the faculty a polished, structured demonstration in 4 seconds:

```powershell
.venv\Scripts\python scripts/demo_faculty_presentation.py
```

### What Happens On-Screen:
1. **Scenario 1 (Factually Accurate Query)**:
   * **Prompt**: *"What is the capital of France and what river flows through it?"*
   * **Response**: *"Paris is the capital of France and the Seine River flows through it."*
   * **Output**: Decomposes 1 claim $\to$ Evaluates RAV, SCS, NLI $\to$ HRS score $0.0398$ (LOW Risk, $[0.0000, 0.0948]$) $\to$ **`[SAFE / PASS]`**.
2. **Scenario 2 (Medical Hallucination)**:
   * **Prompt**: *"What is the FDA-approved initial dosing for Metformin in adults?"*
   * **Response**: *"The standard starting dose for Metformin is 5000mg taken four times daily before bed."*
   * **Output**: Mismatch against FDA knowledge base $\to$ HRS score $0.3550$ (MEDIUM Risk) $\to$ **`[MODERATE / FLAGGED]`**.
3. **Scenario 3 (Internal Self-Contradiction & Autonomous Remediation)**:
   * **Prompt**: *"Provide a summary of the Apollo 11 lunar landing."*
   * **Response**: *"Apollo 11 successfully landed astronauts on the Moon in July 1969. However, human beings have never landed on the Moon."*
   * **Output**: Decomposes 2 conflicting claims $\to$ **ICS (Internal Consistency Scorer)** triggers $\to$ HRS spikes to **$0.8500$ (CRITICAL Risk)** $\to$ **LangGraph Correction Loop triggers live**, isolates the contradiction, injects factual evidence, and generates an evidence-grounded rewrite!

---

## 3. Testing Option B: Interactive Live Test (Faculty Types Any Custom Query)

If a professor says:
> *"Don't show me your pre-set examples. Type this prompt and this response right now and prove your system works!"*

Run the interactive console:
```powershell
.venv\Scripts\python scripts/verify_interactive.py
```

The script will prompt you:
```text
Enter Prompt [Press Enter for default]: 
Enter Model Response [Press Enter for default]: 
Enter Custom Ground Truth Evidence [Press Enter to use built-in KB]: 
```

You can either type/paste what the faculty dictates, or press Enter to run the default test.

---

## 4. Testing Option C: Command-Line One-Liner (Instant Evaluation)

You can pass ANY prompt and response directly as arguments:

### Test Case 1: True Claim (Will PASS with Low Risk)
```powershell
.venv\Scripts\python scripts/verify_interactive.py --prompt "When was Python created?" --response "Python was created by Guido van Rossum in the late 1980s."
```
* **Expected Result**: HRS $\approx 0.05$ (LOW Risk), 95% Conformal CI $[0.00, 0.11]$, Verdict: `[SAFE / PASS]`.

### Test Case 2: Hallucination / Contradiction (Will TRIGGER Intercept & Remediation)
```powershell
.venv\Scripts\python scripts/verify_interactive.py --prompt "When was the Eiffel Tower built?" --response "The Eiffel tower was built in 1989 for the Olympic Games in London."
```
* **Expected Result**: Claims classified as `CONTRADICTED`, HRS = **$0.8500$ (CRITICAL Risk)**, TreeSHAP attributes risk to NLI & RAV, **LangGraph agent rewrites the response with ground truth!**

### Test Case 3: Custom Domain with Injected Faculty Evidence
If the faculty asks: *"How does it work if we have a proprietary institutional document?"*
```powershell
.venv\Scripts\python scripts/verify_interactive.py --prompt "Who is the Head of AIML at CSPIT?" --response "Dr. John Doe from Stanford University is the Head of AIML at CSPIT." --evidence "Chandubhai S. Patel Institute of Technology established the Department of Artificial Intelligence and Machine Learning in 2021."
```
* **Expected Result**: System uses the custom evidence provided on the fly to detect unsupported named entities!

---

## 5. Testing Option D: Interactive Browser Swagger UI

Show the professors the interactive REST API documentation:

1. In a terminal window, start the gateway:
   ```powershell
   .venv\Scripts\python -m uvicorn gateway.main:app --port 8000
   ```
2. Open your browser and go to:
   ```
   http://localhost:8000/docs
   ```
3. Live endpoints to demonstrate:
   * `GET /v1/health` $\to$ Click **Try it out** $\to$ **Execute**:
     * Shows system status `healthy`, uptime, and all 7 circuit breakers (`llm_api`, `qdrant`, `nli_verifier`, `flan_t5_decomposer`, `redis_cache`, `rabbitmq_broker`, `llava_model`) in operational `closed` state.
   * `POST /v1/verify` $\to$ Core verification contract.
   * `POST /v1/chat/completions` $\to$ Drop-in OpenAI proxy.
   * `GET /v1/audit/verify-chain` $\to$ Tamper-evident SHA-256 cryptographic audit ledger.

---

## 6. Testing Option E: Automated Pytest Suite (Scientific Validation)

To demonstrate rigorous engineering practices, execute the automated tests:

### Core Pipeline Integration Tests (4 Tests in ~22 seconds):
```powershell
.venv\Scripts\python -m pytest tests/integration/test_pipeline_integration.py -v
```

### Fast Unit & Security Suite (272 Tests in ~100 seconds):
```powershell
.venv\Scripts\python -m pytest -q -m "not integration and not chaos"
```

### Full Regression Suite:
```powershell
# 307 / 307 Tests passing across unit, contract, integration, chaos, and security gates.
```
