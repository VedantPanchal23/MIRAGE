# MIRAGE 3.0 — Deployment and Operations

> **Status:** Authoritative | **Version:** 3.0.0-draft | **Date:** 2026-10-05

## 1. Introduction

MIRAGE 3.0 represents a significant architectural shift from a centralized verification service to a distributed AI Execution Assurance Platform. It bridges the Control Plane, Execution Plane, Data Plane, and Observability Plane. This document details the deployment topologies, operational strategies, high availability patterns, and maintenance requirements for running MIRAGE securely and reliably in production environments.

---

## 2. Deployment Topologies

### 2.1 Local Development
Optimized for developer experience, rapid iteration, and hot-reloading.
* **Mechanism:** Managed entirely via `docker-compose.yml` and unified `Makefile` targets (e.g., `make up`, `make test`, `make logs`).
* **Configuration:** Environment variables managed via local `.env` files (strictly ignored by Git).
* **Components:** Runs a consolidated, lightweight version of the distributed architecture. Services are mapped to local ports for easy debugging. Mock MCP servers are spun up automatically for integration testing.

### 2.2 Expanded Container Topology
MIRAGE 3.0 expands significantly beyond the 2.x 13-container topology to accommodate the distributed Control and Execution planes.
* **Control Plane Services:** Identity Service, Policy Service, Capability Manager, Budget Manager.
* **Execution Plane Services:** Gateway, Intent Classifier, Risk Engine, Action Governor, Verification Engine (Gate 4), Reality Verifier (Gate 5), Tool Proxy, Model Router.
* **Data & Observability:** PostgreSQL, MongoDB, Redis, Qdrant, Event Stream (Kafka/RabbitMQ), OTel Collector, React/JSX Frontend.

### 2.3 Kubernetes (Recommended Production)
Kubernetes is the standard target for scalable production deployments.
* **Mechanism:** Deployed via official Helm charts. Configurations map strictly to ConfigMaps, while credentials map to Secrets.
* **Pod Design:** Anti-affinity rules ensure that Execution Plane workers and Data Plane stateful sets are spread across different physical nodes and Availability Zones.
* **Resource Limits:** Strict CPU and memory requests/limits are enforced to prevent noisy neighbor problems within the cluster.
* **Scaling Policies:** Horizontal Pod Autoscaler (HPA) configured dynamically. For instance, the Gateway scales on Requests Per Second (RPS), while the Verification Engine scales on CPU utilization and queue depth.

### 2.4 Cloud, On-Prem, and Hybrid Patterns
* **Cloud (AWS, GCP, Azure):** Leverage managed data services to reduce operational burden. Recommend AWS RDS (PostgreSQL), DocumentDB/Atlas (MongoDB), ElastiCache (Redis), and managed Kubernetes (EKS/GKE/AKS).
* **On-Premise:** Full deployment utilizing internal load balancers, enterprise block storage (SAN/NAS) for stateful data, and strict ingress/egress firewall rules.
* **Hybrid Deployment:** The Control Plane (policies, identities) is hosted centrally in the cloud, while Execution Plane Gateways are deployed locally at the edge or on-prem to satisfy data residency, latency, and compliance requirements.
* **Air-Gapped Deployment Constraints:** Requires specialized offline installation bundles. All external model routing is disabled. Requires downloading, packaging, and hosting all local model weights (e.g., DeBERTa, LLaMA) on internal GPU clusters. Outbound API calls are strictly blocked.

---

## 3. High Availability (HA) and Disaster Recovery (DR)

### 3.1 Horizontal Scaling per Component
* **Stateless Services (Gateway, Policy Engine, Risk Engine):** Scale horizontally out-of-the-box. Configured as Active/Active behind Layer 7 load balancers.
* **Heavy Compute (Verification Engine):** Scales based on verification budgets and queue depths. Utilizes GPU nodes where available for visual grounding and NLI.
* **Stateful Services:**
  * **PostgreSQL:** Primary/Replica setup using Patroni or AWS RDS Multi-AZ.
  * **MongoDB:** Replica sets with minimum 3 nodes across AZs.
  * **Redis:** Redis Cluster mode for partitioning and high availability.
  * **Qdrant:** Distributed deployment with replication factor >= 2.

### 3.2 Disaster Recovery Targets and Mechanisms
* **RPO (Recovery Point Objective):** < 5 minutes.
* **RTO (Recovery Time Objective):** < 15 minutes.
* **PostgreSQL:** Continuous WAL (Write-Ahead Logging) archiving to object storage (S3) and daily automated snapshots.
* **MongoDB:** Continuous oplog replication and daily snapshots.
* **Qdrant:** Periodic volume snapshots and snapshot exports to object storage.
* **Audit Logs:** Immutable, continuous replication of the SHA-256 audit chain to WORM (Write Once, Read Many) cold storage.

---

## 4. Operational Guidelines

### 4.1 Secrets Management Architecture
* **Rule:** `.env` files are strictly prohibited in production and staging environments.
* **Integration:** Integration with enterprise secret stores (e.g., HashiCorp Vault, AWS Secrets Manager, Azure Key Vault) is mandatory.
* **Delivery:** Secrets are injected into Kubernetes pods via CSI secret store providers or sidecar injection at runtime. Applications must never log secrets.

### 4.2 Observability Integration
* **Tracing:** OpenTelemetry (OTel) Collector daemonsets deployed on every node to capture distributed traces across all AI Transaction stages.
* **Metrics:** Prometheus endpoints exposed on all services (`/metrics`).
* **Dashboards:** Standardized Grafana templates provided for operational insights, tracking Gate latencies, throughput, error rates, budget consumption, and infrastructure health.

### 4.3 Upgrades and Migration Procedures
* **Upgrades:** Rolling updates strategy ensuring zero-downtime. All APIs must maintain strict backward compatibility (N-1 version support).
* **Database Migrations:** 
  * Schema migrations are executed via Alembic (PostgreSQL) in a dedicated pre-flight job before application pods are updated.
  * MongoDB migrations use custom scripts to ensure schema evolution without locking collections.
* **Blue/Green Deployment:** Supported for major version upgrades (e.g., MIRAGE 2.x to 3.0), allowing traffic shifting after full verification.

### 4.4 Capacity Planning Guidelines
To ensure predictable performance, deployments are categorized into scale tiers.
* **Small (Dev/Test):** ~100 TPS. Minimum 16 vCPUs, 64GB RAM total across cluster.
* **Medium (Standard Enterprise):** ~500 TPS. Minimum 64 vCPUs, 256GB RAM. Dedicated DB instances.
* **Large (High Volume/Agentic):** >2000 TPS. >200 vCPUs, distributed GPU nodes for inline verification, sharded Qdrant.
* **Resource Estimates:** Output Assurance (Gate 4) remains the most resource-intensive step. Plan for 1 GPU (A10G or better) per 50 concurrent heavy verifications. Gate 1 (Input Assurance) runs entirely on CPU with sub-millisecond latency.
