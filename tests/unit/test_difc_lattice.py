"""Unit tests for the Dynamic Information Flow Control (DIFC) security lattice."""


from shared.schemas.control_plane import (
    Taint,
    TaintLatticeLevel,
    compute_lattice_high_water_mark,
    is_dangerous_triad_active,
    normalize_taints,
    taint_to_lattice_level,
)


def test_lattice_levels_ordering() -> None:
    """Ensure formal lattice levels satisfy the strict partial order:

    PUBLIC < INTERNAL < CONFIDENTIAL < RESTRICTED_PII < SECRET_CREDENTIAL
    """
    assert TaintLatticeLevel.PUBLIC < TaintLatticeLevel.INTERNAL
    assert TaintLatticeLevel.INTERNAL < TaintLatticeLevel.CONFIDENTIAL
    assert TaintLatticeLevel.CONFIDENTIAL < TaintLatticeLevel.RESTRICTED_PII
    assert TaintLatticeLevel.RESTRICTED_PII < TaintLatticeLevel.SECRET_CREDENTIAL


def test_taint_to_lattice_level_mapping() -> None:
    """Verify mapping from taints to lattice levels."""
    assert taint_to_lattice_level(Taint.PUBLIC) == TaintLatticeLevel.PUBLIC
    assert taint_to_lattice_level(Taint.INTERNAL) == TaintLatticeLevel.INTERNAL
    assert taint_to_lattice_level(Taint.CONFIDENTIAL) == TaintLatticeLevel.CONFIDENTIAL
    assert taint_to_lattice_level(Taint.RESTRICTED_PII) == TaintLatticeLevel.RESTRICTED_PII
    assert taint_to_lattice_level(Taint.SECRET_CREDENTIAL) == TaintLatticeLevel.SECRET_CREDENTIAL
    # Unknown string falls back to PUBLIC
    assert taint_to_lattice_level("UNKNOWN_TAINT") == TaintLatticeLevel.PUBLIC


def test_compute_lattice_high_water_mark() -> None:
    """Ensure the join (supremum) operation selects the maximum lattice level."""
    taints_low = [Taint.PUBLIC, Taint.INTERNAL]
    assert compute_lattice_high_water_mark(taints_low) == TaintLatticeLevel.INTERNAL

    taints_mixed = [Taint.PUBLIC, Taint.CONFIDENTIAL, Taint.INTERNAL]
    assert compute_lattice_high_water_mark(taints_mixed) == TaintLatticeLevel.CONFIDENTIAL

    taints_high = [Taint.UNTRUSTED, Taint.INTERNAL, Taint.SECRET_CREDENTIAL]
    assert compute_lattice_high_water_mark(taints_high) == TaintLatticeLevel.SECRET_CREDENTIAL


def test_is_dangerous_triad_active() -> None:
    """Verify Dangerous Triad detection (Private Data + Untrusted Content)."""
    # Untrusted alone is not the triad
    assert not is_dangerous_triad_active([Taint.UNTRUSTED])

    # Confidential alone is not the triad
    assert not is_dangerous_triad_active([Taint.CONFIDENTIAL])

    # Internal + Untrusted does not trigger confidential triad
    assert not is_dangerous_triad_active([Taint.UNTRUSTED, Taint.INTERNAL])

    # Untrusted + Confidential triggers triad
    assert is_dangerous_triad_active([Taint.UNTRUSTED, Taint.CONFIDENTIAL])

    # Untrusted + Restricted PII triggers triad
    assert is_dangerous_triad_active([Taint.UNTRUSTED, Taint.RESTRICTED_PII])

    # Untrusted + Secret Credential triggers triad
    assert is_dangerous_triad_active([Taint.UNTRUSTED, Taint.SECRET_CREDENTIAL])


def test_normalize_taints_auto_interlocks_concurrent_restriction() -> None:
    """Verify normalize_taints automatically appends TAINT_CONCURRENT_RESTRICTION."""
    normalized = normalize_taints([Taint.UNTRUSTED, Taint.CONFIDENTIAL])
    assert Taint.CONCURRENT_RESTRICTION in normalized
    assert Taint.UNTRUSTED in normalized
    assert Taint.CONFIDENTIAL in normalized

    # When no confidential taint, concurrent restriction is not added
    normalized_safe = normalize_taints([Taint.UNTRUSTED, Taint.PUBLIC])
    assert Taint.CONCURRENT_RESTRICTION not in normalized_safe
