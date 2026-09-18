# MIRAGE: Faculty Review Q&A Defense Cheatsheet

**Institution:** Chandubhai S. Patel Institute of Technology (CSPIT)  
**Department:** Artificial Intelligence and Machine Learning  
**Investigators:** Vedant Panchal (`23AIML042`) & Dax Virani (`23AIML076`)  

Use this quick-reference guide during your viva/presentation to answer challenging technical questions from faculty members.

---

### Q1: "How is MIRAGE different from Retrieval-Augmented Generation (RAG)?"
* **Answer**:  
  *"Sir/Ma'am, RAG is an **input-side prompt enrichment** technique. It searches documents and pastes them into the LLM's prompt. However, extensive research (such as NeMo Guardrails and HaluEval) shows that even with relevant context, LLMs frequently ignore instructions, misinterpret numbers, or hallucinate extrinsic facts.*  
  *MIRAGE is an **output-side verification and certification middleware**. We intercept what the LLM actually generates, decompose it into singular atomic claims, cross-examine it across 5 independent signals (retrieval, self-consistency entropy, NLI cross-encoder, vision, and internal logic), and calculate a statistically calibrated risk score before allowing it to reach the user."*

---

### Q2: "Why can't we simply ask GPT-4 or another LLM: 'Are you sure this is correct?' (Self-Reflection)?"
* **Answer**:  
  *"Prompting the same LLM for self-reflection suffers from **shared inductive bias** and **sycophancy**. If a model hallucinates a fact due to missing parametric knowledge, asking it again with prompt engineering causes it to defend its original hallucination.*  
  *MIRAGE uses deterministic cross-model verification: a fine-tuned DeBERTa-v3 cross-encoder that outputs strict mathematical entailment probabilities, combined with discrete Semantic Entropy (clustering $n=5$ completions by bidirectional entailment). This objective mathematical formulation cannot be swayed by conversational prompting."*

---

### Q3: "What is the computational overhead and latency? Won't this make LLM apps too slow?"
* **Answer**:  
  *"We designed MIRAGE for a strict sub-second SLA ($P95 < 1.5$s for cached queries, $< 3.0$s for cold full verification). We achieve this through four optimizations:*  
  1. *FLAN-T5 runs locally on CPU in $<50$ms.*  
  2. *All five signal workers (RAV, SCS, NLI, ICS, VGS) execute **concurrently in parallel** using asynchronous I/O and Celery distributed tasks.*  
  3. *In multimodal queries, CLIP pre-filtering bypasses expensive deep visual inference if similarity exceeds $0.85$ ($0$ms vision overhead).*  
  4. *Deterministic Redis ACL caching ensures identical prompt-response pairs achieve instant $0$ms cache hits."*

---

### Q4: "Why use LightGBM for the Hallucination Risk Score (HRS) instead of a simple weighted average?"
* **Answer**:  
  *"A linear weighted sum assumes signals are independent and linear, which is false in natural language.*  
  *For instance, if DeBERTa NLI outputs a 99% probability of direct factual contradiction, the response is definitively hallucinated regardless of high vector retrieval similarity. A linear average would dilute that contradiction.*  
  *LightGBM models non-linear feature interactions and decision splits across all 12 signal features. Furthermore, we run **Isotonic Regression** on top of LightGBM to guarantee an Expected Calibration Error ($ECE$) $< 0.05$, meaning an 80% risk score mathematically corresponds to an 80% empirical probability of error."*

---

### Q5: "What is Mondrian Conformal Prediction and why is it needed?"
* **Answer**:  
  *"Standard ML classifiers produce raw probabilities that are often overconfident. In high-stakes domains like healthcare or legal tech, enterprise compliance officers need guaranteed error bounds.*  
  *Mondrian Conformal Prediction partitions claims into groups based on criticality (High, Medium, Low) and outputs mathematically certified 95% prediction intervals $[HRS_{\text{lower}}, HRS_{\text{upper}}]$. It guarantees that the true factual risk falls inside this interval with $\ge 95\%$ coverage, regardless of model architecture."*

---

### Q6: "What happens if one of your backend services (like Qdrant or Redis) crashes during a request?"
* **Answer**:  
  *"We have implemented the **Circuit Breaker pattern** (`pybreaker`) across all dependencies:*  
  * *If Qdrant fails $3$ consecutive times, the circuit opens for $30$ seconds, and MIRAGE automatically engages **RAV-less degradation mode** (evaluating SCS + NLI + ICS without crashing).*  
  * *If Redis rate limiting fails, it **fails closed** for security, returning HTTP 503 with a `Retry-After` header to protect downstream backends.*  
  * *We have verified this behavior with dedicated chaos tests (`tests/chaos/test_chaos_resilience.py`), proving zero unhandled 500 errors."*

---

### Q7: "What have you actually implemented so far vs. what is just planned?"
* **Answer**:  
  *"We have completed all of **Phase P0 (P0.1 through P0.6)**, which represents the entire hardened foundational engine:*  
  1. *FastAPI Gateway with JWT authentication, RBAC, and PII scrubbing.*  
  2. *PostgreSQL 16 persistence with Row-Level Security (`mirage_app`) and MongoDB 7 trace persistence.*  
  3. *Distributed Redis 7.2 ACL caching and token-bucket rate limiting.*  
  4. *RabbitMQ 3.13 Quorum queues with Celery persistent daemon workers.*  
  5. *13-container Docker Compose production topology with OpenTelemetry distributed tracing.*  
  6. *Our automated regression test suite passes **307 / 307 tests**.*  
  *We are currently in **Phase P1** completing REST API contract conformance."*

---

### Q8: "How does the autonomous remediation loop know how to fix a hallucination without making new mistakes?"
* **Answer**:  
  *"We use a **LangGraph state machine**. Instead of giving the LLM a free-form prompt, our agent:*  
  1. *Extracts only the specific contradicted atomic claim.*  
  2. *Retrieves the exact ground-truth evidence chunk from Qdrant.*  
  3. *Prompts the model with strict evidence-grounded constraints: 'Rewrite only this statement using exclusively the provided evidence.'*  
  4. *Crucially, MIRAGE enforces a **mandatory re-verification pass**. If the rewritten text still scores $HRS > 0.30$, it is rejected, preventing the introduction of new hallucinations."*

---

### Q9: "What is your hardware and GPU budget? Can this run in a university lab or single server?"
* **Answer**:  
  *"Yes. We specifically sized and budgeted MIRAGE for a single **NVIDIA A10G (24GB VRAM)** instance (AWS `g5.2xlarge` or institutional GPU server):*  
  * *DeBERTa-v3-large (FP16): $\sim 2.1$ GB VRAM.*  
  * *LLaVA-1.6-Mistral-7B (4-bit AWQ): $\sim 14.2$ GB VRAM.*  
  * *Total GPU Memory: $\sim 16.3$ GB / 24 GB ($68\%$ utilization).*  
  * *Headroom: $\sim 7.7$ GB remaining for KV-cache and batching.*  
  * *FLAN-T5-base and the Gateway run efficiently on standard CPU cores ($4$ vCPUs, $16$ GB RAM)."*

---

### Q10: "How do you ensure multi-tenant security and data privacy between different organizations?"
* **Answer**:  
  *"We implement defense-in-depth across the entire stack:*  
  1. *At the ASGI boundary, untrusted headers like `X-Role` or `X-Tenant-ID` are forcefully stripped to prevent identity spoofing.*  
  2. *In PostgreSQL, **Row-Level Security (RLS)** restricts queries to `app.current_tenant_id` at the database engine level.*  
  3. *In Redis, ACL users isolate cache keys (`scs:*`) from rate limiters (`ratelimit:*`).*  
  4. *In MongoDB, queries are filtered by authenticated tenant IDs.*  
  5. *Every verification run is sealed into a tamper-evident **SHA-256 cryptographic audit ledger**."*
