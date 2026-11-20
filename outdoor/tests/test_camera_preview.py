"""Synthetic ROS images only: concurrent previews must not share an executor."""
import importlib.util
from pathlib import Path
import time

import pytest


def test_rgb_and_depth_preview_concurrently(monkeypatch):
    rclpy = pytest.importorskip('rclpy')
    np = pytest.importorskip('numpy')
    cv2 = pytest.importorskip('cv2')
    from sensor_msgs.msg import Image
    root = Path(__file__).resolve().parents[2] / 'tools/camera_view'
    monkeypatch.syspath_prepend(str(root))
    monkeypatch.setenv('ROS_DOMAIN_ID', '181')
    spec = importlib.util.spec_from_file_location('camera_view_under_test', root/'server.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    owned = not rclpy.ok()
    if owned:
        rclpy.init()
    publisher = rclpy.create_node('synthetic_preview_test')
    rgb_pub = publisher.create_publisher(Image, '/synthetic/preview/rgb', 5)
    depth_pub = publisher.create_publisher(Image, '/synthetic/preview/depth', 5)
    settings = dict(idle_stop_s=15, fps=5., width=32, jpeg_quality=80)
    cameras = [module.Camera('深度彩色', {'topic': '/synthetic/preview/rgb'}, settings),
               module.Camera('深度图', {'topic': '/synthetic/preview/depth', 'mode': 'depth'}, settings)]
    try:
        for camera in cameras:
            camera.touch()
            camera.start()
        rgb, depth = Image(), Image()
        for msg in (rgb, depth):
            msg.width, msg.height = 16, 12
        rgb.encoding, rgb.step = 'rgb8', 48
        rgb.data = bytes([255, 0, 0]) * (16*12)
        depth.encoding, depth.step = '16UC1', 32
        depth.data = np.full((12, 16), 1000, np.uint16).tobytes()
        deadline = time.monotonic()+8
        while time.monotonic() < deadline and not all(c.snapshot()[0] for c in cameras):
            rgb_pub.publish(rgb)
            depth_pub.publish(depth)
            rclpy.spin_once(publisher, timeout_sec=.05)
        for camera in cameras:
            frame, stamp, _ = camera.snapshot()
            assert frame, camera.error
            assert time.monotonic()-stamp < 2
            image = cv2.imdecode(np.frombuffer(frame, np.uint8), cv2.IMREAD_COLOR)
            assert image.shape == (12, 16, 3)
        image = cv2.imdecode(np.frombuffer(cameras[0].snapshot()[0], np.uint8), cv2.IMREAD_COLOR)
        assert image[0, 0, 2] > 200 and image[0, 0, 0] < 30
    finally:
        for camera in cameras:
            camera.restart = True
        for camera in cameras:
            if camera.thread:
                camera.thread.join(timeout=3)
        publisher.destroy_node()
        if owned:
            rclpy.shutdown()
