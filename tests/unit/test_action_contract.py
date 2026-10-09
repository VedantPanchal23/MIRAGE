"""Unit tests for Action Contract normalization, parameter hashing, and precondition rules."""

import pytest

from shared.schemas.action import (
    ActionProposal,
    ActionType,
    compute_parameters_hash,
    normalize_action_parameters,
)


def test_parameter_normalization_strips_whitespace_and_preserves_clean_values() -> None:
    raw = {
        "  name ": "  database_backup  ",
        "nested": {
            "path": "  /var/log/app.log  ",
            "items": [" item1 ", " item2 "],
        },
    }
    normalized = normalize_action_parameters(raw)
    assert normalized["name"] == "database_backup"
    assert normalized["nested"]["path"] == "/var/log/app.log"
    assert normalized["nested"]["items"] == ["item1", "item2"]


def test_parameter_normalization_blocks_path_traversal() -> None:
    with pytest.raises(ValueError, match="Path traversal detected"):
        normalize_action_parameters({"filepath": "../../etc/shadow"})

    with pytest.raises(ValueError, match="Path traversal detected"):
        normalize_action_parameters({"filepath": "sub/../../../windows/win.ini"})

    with pytest.raises(ValueError, match="Path traversal detected"):
        normalize_action_parameters({"filepath": "..\\..\\sensitive_file.txt"})


def test_parameter_normalization_blocks_ssrf_to_loopback_and_metadata() -> None:
    with pytest.raises(ValueError, match="SSRF attempt blocked"):
        normalize_action_parameters({"url": "http://localhost:8080/admin"})

    with pytest.raises(ValueError, match="SSRF attempt blocked"):
        normalize_action_parameters({"url": "http://127.0.0.1/secrets"})

    with pytest.raises(ValueError, match="SSRF attempt blocked"):
        normalize_action_parameters({"url": "http://169.254.169.254/latest/meta-data"})

    with pytest.raises(ValueError, match="SSRF attempt blocked"):
        normalize_action_parameters({"url": "https://0.0.0.0:443/private"})


def test_parameter_normalization_canonicalizes_urls() -> None:
    raw = {"target_url": "HTTP://Example.COM:80/api/v1?beta=2&alpha=1"}
    normalized = normalize_action_parameters(raw)
    # Lowercase scheme and host, stripped default port, sorted query parameters
    assert normalized["target_url"] == "http://example.com/api/v1?alpha=1&beta=2"


def test_compute_parameters_hash_is_invariant_to_key_insertion_order() -> None:
    dict_a = {"z": 100, "a": "first", "m": [1, 2, 3]}
    dict_b = {"a": "first", "m": [1, 2, 3], "z": 100}

    hash_a = compute_parameters_hash(dict_a)
    hash_b = compute_parameters_hash(dict_b)

    assert len(hash_a) == 64
    assert hash_a == hash_b

    # Any parameter change alters the hash
    dict_c = {"z": 101, "a": "first", "m": [1, 2, 3]}
    assert compute_parameters_hash(dict_c) != hash_a


def test_action_proposal_schema_defaults() -> None:
    proposal = ActionProposal(
        transaction_id="txn_123",
        tool_name="db_query",
        action_type=ActionType.READ,
        target_resource="db://users",
        parameters={"query": "SELECT * FROM users"},
        idempotency_key="idem_test_proposal_01",
    )
    assert proposal.action_type == ActionType.READ
    assert proposal.blast_radius.target_environment == "DEV"
    assert proposal.blast_radius.estimated_dollar_cost == 0.0
    assert len(proposal.preconditions) == 0
    assert len(proposal.postconditions) == 0
