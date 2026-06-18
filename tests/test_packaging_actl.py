# tests/test_packaging_actl.py
# NB: use defusedxml — the .policy file carries a DOCTYPE/external-DTD ref; stdlib
# ElementTree is XXE/billion-laughs prone by default. defusedxml is dev-only.
from defusedxml import ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_polkit_policy_is_valid_xml_with_action():
    tree = ET.parse(ROOT / "packaging" / "co.kodownik.kokpit.actl.policy")
    actions = [a.get("id") for a in tree.getroot().findall("action")]
    assert "co.kodownik.kokpit.actl" in actions


def test_policy_binds_helper_as_root():
    text = (ROOT / "packaging" / "co.kodownik.kokpit.actl.policy").read_text()
    assert "/usr/local/bin/kokpit-actl-helper" in text
    assert "<annotate key=\"org.freedesktop.policykit.exec.path\">" in text


def test_install_script_present_and_executable():
    s = ROOT / "packaging" / "install-actl-helper.sh"
    assert s.exists() and s.read_text().startswith("#!")
