from pathlib import Path

from opensign.hardware_probe.analysis import diff_ble_sessions, rank_chipset_candidates
from opensign.hardware_probe.evidence import EvidenceStore


def test_diff_ble_sessions_reports_variable_positions() -> None:
    baseline = [{"direction": "write", "characteristic": "w", "payload_hex": "AA0102"}]
    experiments = [[{"direction": "write", "characteristic": "w", "payload_hex": "AA0902"}]]
    report = diff_ble_sessions(baseline, experiments)
    packet = report["experiments"][0]["alignment"][0]
    assert packet["common_prefix_length"] == 1
    assert packet["variable_positions"] == [1]


def test_chipset_ranking_requires_supplied_evidence() -> None:
    empty = rank_chipset_candidates(["ABC123"], {})
    assert empty["confirmed"] == []
    report = rank_chipset_candidates(
        ["ABC123"],
        {"ble": True},
        [{"name": "candidate", "marking_patterns": ["ABC"], "radio_capabilities": {"ble": True}}],
    )
    assert report["confirmed"][0]["name"] == "candidate"


def test_evidence_store_breadcrumbs(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / "evidence")
    hardware = store.record_hardware("desk-sign", pcb_markings=["ABC123"])
    assert hardware.exists()
    store.add_breadcrumb("capture-1", kind="capture", data={"scenario": "clear"})
    store.add_breadcrumb(
        "hypothesis-1",
        kind="hypothesis",
        data={"claim": "byte 1 is command"},
        parents=["capture-1"],
    )
    path = store.breadcrumb_path("hypothesis-1")
    assert [node["node_id"] for node in path] == ["hypothesis-1", "capture-1"]
