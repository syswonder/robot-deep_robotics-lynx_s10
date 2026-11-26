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
    assert b["lynx_chassis"]["config"]["allow_motion"] is True
    assert b["lynx_chassis"]["config"]["allow_gait"] is True
    assert b["scene"]["config"]["outdoor_navigation"]["execution_enabled"] is True
    for motion, cfg in ((False, a["outdoor_execution"]["config"]),
                        (True, b["outdoor_execution"]["config"])):
        assert cfg["policy"]["motion_enabled"] is motion
        assert cfg["gait_switching_enabled"] is True
        assert cfg["policy"]["gait_boundary_tolerance_m"] == .25
        assert cfg["policy"]["gait_switch_timeout_s"] == 10.
        assert cfg["policy"]["sensor_timeout_s"] == 2.
        assert cfg["policy"]["fixed_arrival_m"] == cfg["policy"]["float_arrival_m"] == 3.
        assert cfg["topic_remap"]["odom"] == "/localization/odom"
        assert cfg["topic_remap"]["localization"] == "/localization/status"
        assert cfg["provider_ids"] == {"cloud": "lynx_lidar",
                                       "localization": "localization_outdoor",
                                       "chassis": "lynx_chassis"}
        assert cfg["global_grid"]["rolling"] is True
        for absent in ("terrain", "decision_cycle", "semantic_segmentation", "ground_height_file"):
            assert absent not in cfg
        for absent in ("lidar_enabled", "camera_enabled", "camera_frame"):
            assert absent not in cfg["policy"]
        assert cfg["velocity_output_topic"] == ("/cmd_vel" if motion else "/robonix/nomotion/outdoor_cmd_vel")
    assert "gait_output_topic" not in b["outdoor_execution"]["config"]
    assert a["outdoor_execution"]["config"]["gait_output_topic"] == "/robonix/nomotion/outdoor_gait"
    for manifest in (check, field):
        items = entries(manifest)
        assert items["localization_outdoor"]["config"]["estimator_mode"] == "eskf"
        assert items["wit_imu"]["config"]["device_profile"] == "inertial"
        assert "/ODOM" not in json.dumps(manifest)


def test_profiles_pass_the_actual_service_configuration_validators(tmp_path):
    from localization_outdoor.configuration import validate as localization_config
    from outdoor_nav.configuration import validate as navigation_config
    from wit_imu.driver import parse_config as imu_config

    for filename in ("robonix_manifest.yaml", "robonix_manifest.field.yaml"):
        items = entries(load(filename))
        assert localization_config(items["localization_outdoor"]["config"])["estimator_mode"] == "eskf"
        assert imu_config(items["wit_imu"]["config"])["serial"]["baud"] == 115200
        nav = copy.deepcopy(items["outdoor_execution"]["config"])
        nav["params_file"] = str(ROOT / "config/outdoor_nav2.yaml")
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
                    "branch": "main",
                },
                {
                    "path": "packages/edited",
                    "url": "invalid://must-not-be-used",
                    "branch": "main",
                },
            ]
        )
    )
    with pytest.raises(ValueError, match="local package changes"):
        prepare.prepare(tmp_path)
    assert not (tmp_path / "packages/missing").exists()
    assert (package / "local.txt").read_text() == "keep this edit"


def test_enabled_external_packages_track_branches():
    import re
    sources = json.loads((ROOT / 'sources.json').read_text())
    tracks = {item['path']: item for item in sources}
    assert len(tracks) == len(sources)
    assert all(set(item) == {'path', 'url', 'branch'} for item in sources)
    assert all(re.fullmatch(r'[\w./-]+', item['branch']) for item in sources)
    assert 'packages/primitive-orbbec-camera' in tracks
    prefix = '${OUTDOOR_DEPLOY_ROOT}/'
    for filename in ('robonix_manifest.yaml', 'robonix_manifest.field.yaml'):
        for item in entries(load(filename)).values():
            if item['path'].startswith(prefix + 'packages/'):
                assert item['path'][len(prefix):] in tracks


def test_prepare_rejects_option_like_branch_names(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "prepare_outdoor", ROOT / "scripts/prepare.py"
    )
    prepare = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prepare)
    package = tmp_path / "packages/clean"
    package.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(package)], check=True)
    (tmp_path / "sources.json").write_text(
        json.dumps(
            [
                {
                    "path": "packages/clean",
                    "url": "invalid://must-not-be-used",
                    "branch": "--upload-pack=evil",
                }
            ]
        )
    )
    with pytest.raises(ValueError, match="Invalid branch"):
        prepare.prepare(tmp_path)
