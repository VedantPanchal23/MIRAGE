# MIRAGE: First Project Review Documentation Package

**Institution:** Chandubhai S. Patel Institute of Technology (CSPIT)  
**Department:** Department of Artificial Intelligence and Machine Learning (AIML)  
**Project Title:** MIRAGE — Autonomous Multimodal Hallucination Detection & Factual Consistency Verification Middleware for Production LLMs  
**Academic Year:** 2026–2027  

---

## Student Investigators
* **Vedant Panchal** (Roll No: `23AIML042`)
* **Dax Virani** (Roll No: `23AIML076`)

---

## Review Package Directory

This directory contains the complete technical deliverables, system designs, diagrams, and live execution instructions prepared for the **First Project Review**:

| File | Description | Core Artifacts |
| :--- | :--- | :--- |
| [`high_level_design.md`](./high_level_design.md) | High-Level Design (HLD) specification. | 5 Product Interfaces, Architectural Pipeline, 5-Plane Topology |
| [`low_level_design.md`](./low_level_design.md) | Low-Level Design (LLD) specification. | Claim Decomposer, 5-Signal Engine, HRS Formulation, LangGraph State Machine, Multi-Store DB Schemas |
| [`system_diagrams.md`](./system_diagrams.md) | Complete Visual Diagram Collection. | 6 Full Mermaid Diagrams (Architecture, Topology, 3 Sequence Flows, ER Diagram) |
| [`live_testing_guide.md`](./live_testing_guide.md) | Live Testing & Demonstration Guide. | CLI interactive tester, Swagger UI, Pytest commands, sample test cases |
| [`implementation_status_and_future_roadmap.md`](./implementation_status_and_future_roadmap.md) | Current Progress vs. Future Scope. | Phases P0.1–P0.6 Completed (307/307 tests), P1 In Progress, P2–P5 Roadmap |
| [`faculty_qa_cheatsheet.md`](./faculty_qa_cheatsheet.md) | Review Defense & Oral Exam Guide. | 10 Anticipated faculty questions & authoritative technical responses |

---

## Quick Start Commands for Reviewers

```powershell
# 1. Run the official 3-scenario terminal demonstration
.venv\Scripts\python scripts/demo_faculty_presentation.py

# 2. Run custom live interactive verification on ANY prompt/response
.venv\Scripts\python scripts/verify_interactive.py

# 3. Run automated integration verification (4 core pipeline tests)
.venv\Scripts\python -m pytest tests/integration/test_pipeline_integration.py -v

# 4. Run full regression test suite (272 fast unit & security tests)
.venv\Scripts\python -m pytest -q -m "not integration and not chaos"

# 5. Start the live FastAPI Gateway for interactive browser testing
.venv\Scripts\python -m uvicorn gateway.main:app --port 8000
# Navigate to: http://localhost:8000/docs
```
