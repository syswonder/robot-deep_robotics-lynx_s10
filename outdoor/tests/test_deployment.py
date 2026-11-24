"""Deployment wiring and motion isolation, without ROS or hardware."""

import copy
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    return yaml.safe_load((ROOT / name).read_text())


def entries(manifest):
    return {
        item["name"]: item
        for section in ("primitive", "service")
        for item in manifest[section]
    }


def test_profiles_isolate_motion_and_share_the_same_dependencies():
    check = load("robonix_manifest.yaml")
    field = load("robonix_manifest.field.yaml")
    a, b = entries(check), entries(field)
    assert a["lynx_chassis"]["config"]["allow_motion"] is False
    assert a["lynx_chassis"]["config"]["allow_gait"] is False
    assert a["scene"]["config"]["outdoor_navigation"]["execution_enabled"] is False
    assert a["outdoor_execution"]["config"]["policy"]["motion_enabled"] is False
    assert a["outdoor_execution"]["config"]["velocity_output_topic"] != "/cmd_vel"
    assert (
        a["outdoor_execution"]["config"]["gait_output_topic"] != "/outdoor/gait_request"
    )
    assert b["lynx_chassis"]["config"]["allow_motion"] is True
    assert b["lynx_chassis"]["config"]["allow_gait"] is True
    assert b["scene"]["config"]["outdoor_navigation"]["execution_enabled"] is True
    assert b["outdoor_execution"]["config"]["policy"]["motion_enabled"] is True
    assert b["outdoor_execution"]["config"]["velocity_output_topic"] == "/cmd_vel"
    assert (
        "gait_output_topic" not in b["outdoor_execution"]["config"]
    )  # resolved from guarded capability
    # Field stair perception is experimental; check mode remains lidar-only.
    # Normalize only the declared experiment differences, not arbitrary wiring.
    normalized = copy.deepcopy(field)
    normalized["name"] = check["name"]
    n = entries(normalized)
    for key in ("allow_motion", "allow_gait"):
        n["lynx_chassis"]["config"][key] = False
    n["scene"]["config"]["outdoor_navigation"]["execution_enabled"] = False
    n["scene"]["config"]["observations"] = []
    n["outdoor_execution"]["config"]["policy"]["motion_enabled"] = False
    for key in ("velocity_output_topic", "gait_output_topic"):
        n["outdoor_execution"]["config"][key] = a["outdoor_execution"]["config"][key]
    field_nav = b["outdoor_execution"]["config"]
    assert field_nav["terrain"]["enabled"] and field_nav["terrain"]["can_climb_stairs"]
    assert field_nav["terrain"]["stairs_classes"] == ["stairs"]
    assert field_nav["semantic_segmentation"]["enabled"]
    assert field_nav["semantic_segmentation"]["classes"]["53"] == "stairs"
    assert not field_nav["decision_cycle"]["enabled"]
    nav = n["outdoor_execution"]["config"]
    baseline = a["outdoor_execution"]["config"]
    nav["terrain"] = copy.deepcopy(baseline["terrain"])
    nav.pop("semantic_segmentation")
    for key in ("camera_enabled", "camera_geometry_enabled", "camera_max_range_m",
                "sensor_timeout_s", "navigation_recovery_timeout_s"):
        if key in baseline["policy"]:
            nav["policy"][key] = baseline["policy"][key]
        else:
            nav["policy"].pop(key, None)
    for key in ("color_profile", "depth_profile"):
        assert b["orbbec_camera"]["config"][key] == "640x480x30"
        n["orbbec_camera"]["config"][key] = a["orbbec_camera"]["config"][key]
    assert normalized == check
    for manifest in (check, field):
        items = entries(manifest)
        assert items["outdoor_execution"]["config"]["provider_ids"] == {
            "cloud": "lynx_lidar",
            "localization": "localization_outdoor",
            "chassis": "lynx_chassis",
            "imu": "wit_imu",
            "camera": "orbbec_camera",
        }
        assert items["localization_outdoor"]["config"]["estimator_mode"] == "eskf"
        assert items["wit_imu"]["config"]["device_profile"] == "inertial"
        camera = items["lynx_camera"]["config"]
        assert any(c.get("primary") and c["url"].endswith("/video4")
                   for c in camera["channels"])
        scene = items["scene"]["config"]
        assert scene["camera_provider_id"] == "lynx_camera"
        assert scene.get("camera_viewer_port") == 8080
        if scene.get("observations"):
            assert any(o["kind"] == "rgb" and o["provider_id"] == "lynx_camera"
                       and o["contract"] == "robonix/primitive/camera/rgb"
                       for o in scene["observations"])
        assert items["localization_outdoor"]["config"]["require_map_reference"] is True
        assert "/ODOM" not in json.dumps(manifest)


def test_profiles_pass_the_actual_service_configuration_validators(tmp_path):
    from localization_outdoor.configuration import validate as localization_config
    from outdoor_nav.configuration import validate as navigation_config
    from wit_imu.driver import parse_config as imu_config

    ground = tmp_path / "ground.local.json"
    ground.write_text('{"ground_z_m": -0.25}')  # Synthetic test calibration, not a machine value.
    for filename in ("robonix_manifest.yaml", "robonix_manifest.field.yaml"):
        items = entries(load(filename))
        assert (
            localization_config(items["localization_outdoor"]["config"])[
                "estimator_mode"
            ]
            == "eskf"
        )
        assert imu_config(items["wit_imu"]["config"])["serial"]["baud"] == 115200
        nav = copy.deepcopy(items["outdoor_execution"]["config"])
        nav["params_file"] = str(ROOT / "config/outdoor_nav2.yaml")
        nav["ground_height_file"] = str(ground)
        if nav.get("semantic_segmentation", {}).get("enabled"):
            # Test configuration validation without downloading model weights.
            model = tmp_path / "synthetic-model"
            model.mkdir(exist_ok=True)
            nav["semantic_segmentation"]["weights"] = str(model)
        navigation_config(nav)


def test_prepare_refuses_dirty_dependencies_before_updating_anything(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "prepare_outdoor", ROOT / "scripts/prepare.py"
    )
    prepare = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prepare)
    package = tmp_path / "packages/edited"
    package.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(package)], check=True)
    (package / "local.txt").write_text("keep this edit")
    # The missing first dependency must not be cloned before detecting the dirty second one.
    (tmp_path / "sources.json").write_text(
        json.dumps(
            [
                {
                    "path": "packages/missing",
                    "url": "invalid://must-not-be-used",
                    "revision": "a" * 40,
                },
                {
                    "path": "packages/edited",
                    "url": "invalid://must-not-be-used",
                    "revision": "b" * 40,
                },
            ]
        )
    )
    with pytest.raises(ValueError, match="local package changes"):
        prepare.prepare(tmp_path)
    assert not (tmp_path / "packages/missing").exists()
    assert (package / "local.txt").read_text() == "keep this edit"


def test_enabled_external_packages_are_locked_to_exact_revisions():
    import re
    sources = json.loads((ROOT / 'sources.json').read_text())
    pins = {item['path']: item for item in sources}
    assert len(pins) == len(sources)
    assert all(re.fullmatch('[a-f0-9]{40}', item['revision']) for item in sources)
    assert 'packages/primitive-orbbec-camera' in pins
    prefix = '${OUTDOOR_DEPLOY_ROOT}/'
    for filename in ('robonix_manifest.yaml', 'robonix_manifest.field.yaml'):
        for item in entries(load(filename)).values():
            if item['path'].startswith(prefix + 'packages/'):
                assert item['path'][len(prefix):] in pins
