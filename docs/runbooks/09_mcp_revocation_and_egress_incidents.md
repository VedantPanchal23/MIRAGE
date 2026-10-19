# Runbook 09: MCP Revocation and Egress Incidents

## 1. Overview and Threat Boundary
MIRAGE governs remote Model Context Protocol (MCP) servers and third-party tools via `GovernedToolProxy`.
- Remote tools are **untrusted** by default.
- Every tool invocation traverses Gate 3 (Action Assurance) for capability checks, lease fencing, and parameter validation.
- Tool outputs traverse Gate 4 and Gate 5 to prevent indirect prompt injection, data exfiltration, or hallucinated claims.
- SSRF and private IP egress (e.g. AWS metadata endpoint `169.254.169.254`, `localhost`, `10.0.0.0/8`, `192.168.0.0/16`) are blocked by `SSRFProtector`.

## 2. Emergency MCP Server Revocation Procedure

If an external MCP server is compromised, emits malicious payloads, or attempts unauthorized egress:

### Revoke MCP Server Registration via API:
```bash
curl -X POST http://localhost:8000/v1/mcp/servers/<server_id>/revoke \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{"reason": "Anomalous tool output / prompt injection payload detected"}'
```
This action:
1. Sets `is_revoked = true` on the `mcp_servers` table.
2. Removes all associated tools from active agent tool registries.
3. Automatically rejects any subsequent proxy requests to that server with HTTP 403 `MCP_SERVER_REVOKED`.

### Emergency Database Revocation:
```sql
UPDATE mcp_servers 
SET is_revoked = true, updated_at = now() 
WHERE id = '<server_id>';
```

## 3. Investigating SSRF and Egress Incidents
When an SSRF alert or egress block occurs:
1. Inspect the gateway logs for egress security violations:
```bash
docker compose logs gateway | grep -i "egress_blocked"
```
2. Verify the blocked destination:
   - Metadata services (`http://169.254.169.254/...`)
   - Internal infrastructure services (`http://postgres:5432`, `http://redis:6379`)
3. Determine the invoking agent, session ID, and transaction ID from the structured log.
4. Suspend the agent's delegation grants if lateral movement was attempted:
```sql
UPDATE delegations 
SET status = 'REVOKED', revoked_at = now() 
WHERE delegate_agent_id = '<agent_id>';
```
