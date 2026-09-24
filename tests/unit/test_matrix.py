from testbed.matrix import (
    CLIENT_PROFILES, ApConfig, ap_configs, build_matrix, compliance_violations, expected,
    markdown_table,
)

WPA2_ONLY = CLIENT_PROFILES["wpa2-only"]
WPA3 = CLIENT_PROFILES["wpa3-capable"]


def test_matrix_size():
    # open x1 PMF + 3 secured modes x3 PMF = 10 combos, x5 channels, x2 clients
    assert len(ap_configs()) == 50
    assert len(build_matrix()) == 100


def test_band_follows_channel():
    assert ApConfig("wpa2", 1, 6).hw_mode == "g"
    assert ApConfig("wpa2", 1, 36).hw_mode == "a"


def test_wpa2_client_against_wpa3_ap_must_fail():
    exp = expected(ApConfig("wpa3", 2, 6), WPA2_ONLY)
    assert (exp.outcome, exp.stage) == ("fail", "association")


def test_sae_without_required_pmf_is_flagged():
    for pmf in (0, 1):
        assert compliance_violations(ApConfig("wpa3", pmf, 6))
        assert expected(ApConfig("wpa3", pmf, 6), WPA3).outcome == "noncompliant"
    assert not compliance_violations(ApConfig("wpa3", 2, 6))


def test_transition_mode_needs_pmf_optional():
    assert compliance_violations(ApConfig("transition", 0, 6))
    assert compliance_violations(ApConfig("transition", 2, 6))
    assert not compliance_violations(ApConfig("transition", 1, 6))
    assert expected(ApConfig("transition", 1, 6), WPA2_ONLY).outcome == "pass"


def test_pmf_required_rejects_legacy_client():
    assert expected(ApConfig("wpa2", 2, 6), WPA2_ONLY).outcome == "fail"
    assert expected(ApConfig("wpa2", 2, 6), WPA3).outcome == "pass"


def test_open_passes_for_everyone():
    for client in CLIENT_PROFILES.values():
        assert expected(ApConfig("open", 0, 1), client).outcome == "pass"
        assert client.network_for(ApConfig("open", 0, 1))["key_mgmt"] == "NONE"


def test_markdown_table_has_one_row_per_combo():
    rows = [line for line in markdown_table().splitlines()[2:] if line.startswith("|")]
    assert len(rows) == 10
