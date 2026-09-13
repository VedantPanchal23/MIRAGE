"""Integration Tests: Multi-component end-to-end verification pipeline tests.

Implements Testing Strategy §5:
- Gateway -> Claim Decomposer -> Multi-Signal Workers -> HRS Engine -> Correction Loop
- Knowledge Base Ingestion & Document Verification
- Audit Cryptographic Hash Chaining & Compliance Reporting
- WebSocket Progressive Verification Streaming
"""

from starlette.testclient import TestClient

from gateway.main import create_app

app = create_app()
client = TestClient(app)


class TestPipelineIntegration:
    """End-to-end integration test suite."""

    def test_full_pipeline_verification_end_to_end(self) -> None:
        """Verify that a full verification request passes through all pipeline stages."""
        payload = {
            "prompt": "What is the capital of France and what river runs through it?",
            "response": "Paris is the capital of France and it is situated along the Seine River.",
            "tenant_id": "tenant_integration_01",
            "knowledge_base_id": "default_kb",
        }

        response = client.post("/v1/verify", json=payload)
        assert response.status_code == 200

        data = response.json()
        assert "verified_response" in data
        assert "hrs_result" in data
        assert "claims" in data

        hrs_res = data["hrs_result"]
        assert 0.0 <= hrs_res["hrs"] <= 1.0
        assert hrs_res["tier"] in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
        assert "signal_attribution" in hrs_res
        assert hrs_res["conformal_interval"]["lower"] <= hrs_res["conformal_interval"]["upper"]

        # Security headers attached
        assert "x-trace-id" in response.headers
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-pii-detected"] == "false"

    def test_knowledge_base_upload_and_retrieval_integration(self) -> None:
        """Test document ingestion via REST and subsequent verification grounding."""
        doc_payload = {
            "filename": "apollo_11_mission.txt",
            "content": (
                "Apollo 11 launched on July 16, 1969. Astronaut Neil Armstrong became the first "
                "human to walk on the lunar surface on July 20, 1969, accompanied by Buzz Aldrin. "
                "Michael Collins orbited the Moon in the command module Columbia."
            ),
            "collection_name": "space_history_kb",
        }

        # 1. Upload document
        upload_res = client.post(
            "/v1/knowledge-base/upload",
            json=doc_payload,
            headers={"X-Tenant-ID": "tenant_integration_kb"},
        )
        assert upload_res.status_code == 201
        upload_data = upload_res.json()
        assert "document_id" in upload_data
        assert upload_data["chunks_count"] >= 1

        # 2. List documents
        list_res = client.get(
            "/v1/knowledge-base/documents",
            headers={"X-Tenant-ID": "tenant_integration_kb"},
        )
        assert list_res.status_code == 200
        docs = list_res.json()["documents"]
        assert any(d["filename"] == "apollo_11_mission.txt" for d in docs)

        # 3. Delete document
        doc_id = upload_data["document_id"]
        del_res = client.delete(
            f"/v1/knowledge-base/documents/{doc_id}",
            headers={"X-Tenant-ID": "tenant_integration_kb"},
        )
        assert del_res.status_code == 200

    def test_audit_chain_and_compliance_report_integration(self) -> None:
        """Verify cryptographic audit chain inspection and compliance certificate generation."""
        # 1. Verify chain
        chain_res = client.post(
            "/v1/audit/verify-chain",
            headers={"X-Tenant-ID": "tenant_integration_audit", "X-Role": "auditor"},
        )
        assert chain_res.status_code == 200
        assert chain_res.json()["valid"] is True

        # 2. Generate report
        report_res = client.get(
            "/v1/audit/report/sess_integration_test_99",
            headers={"X-Tenant-ID": "tenant_integration_audit", "X-Role": "auditor"},
        )
        assert report_res.status_code == 200
        report_data = report_res.json()
        assert "report_id" in report_data
        assert "tamper_verification_signature" in report_data
        assert "compliance_standard" in report_data

        # 3. Natural language query
        query_res = client.post(
            "/v1/audit/query",
            json={"query": "show all critical risk sessions with contradiction"},
            headers={"X-Tenant-ID": "tenant_integration_audit", "X-Role": "auditor"},
        )
        assert query_res.status_code == 200
        assert "results" in query_res.json()

    def test_websocket_stream_progressive_events_integration(self) -> None:
        """Test real-time WebSocket connection and event lifecycle."""
        with client.websocket_connect("/v1/verify/stream") as ws:
            # 1. Receive connection established event
            init_event = ws.receive_json()
            assert init_event["event_type"] == "connection_established"
            assert "trace_id" in init_event

            # 2. Send verification request
            ws.send_json(
                {
                    "prompt": "Explain photosynthesis",
                    "response": "Photosynthesis is the process by which plants convert sunlight into chemical energy.",
                    "tenant_id": "tenant_ws_test",
                }
            )

            # 3. Expect claims extracted event
            claims_event = ws.receive_json()
            assert claims_event["event_type"] == "claims_extracted"
            assert claims_event["claims_count"] >= 1

            # 4. Expect signals computed event
            signals_event = ws.receive_json()
            assert signals_event["event_type"] == "signals_computed"
            assert "signal_attribution" in signals_event

            # 5. Expect verification complete event
            complete_event = ws.receive_json()
            assert complete_event["event_type"] == "verification_complete"
            assert 0.0 <= complete_event["hrs_score"] <= 1.0
            assert complete_event["risk_tier"] in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
