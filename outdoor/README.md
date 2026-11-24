# 山猫室外部署

本目录只保留 Robonix 部署清单、现场参数与依赖准备。硬件代码在 `../primitives`，
定位、建图和导航由独立服务提供。没有额外的 Python 启停 CLI。

```bash
python3 scripts/prepare.py
uv venv --system-site-packages --python /usr/bin/python3 .venv
uv pip install --python .venv/bin/python -e framework/robonix/pylib/robonix-api -r requirements.txt
# 填写 config/gnss.base.yaml 和 mode 600 的 config/secrets.json。
source scripts/environment.sh
rbnx build -f robonix_manifest.yaml
flock -n run/boot.lock rbnx boot -f robonix_manifest.yaml --no-update-check -v
```

另一个已加载环境的终端执行 `rbnx caps -v` 或 `rbnx shutdown -f robonix_manifest.yaml`。
运动模式使用 `robonix_manifest.field.yaml`，先停止检查模式，两者共用同一个启动锁。
重起前须等 `rbnx shutdown -f robonix_manifest.field.yaml` 成功结束；不删除
`rbnx-boot/state.json` 绕过停栈。修复后的 CLI 会在旧栈或清理尚未结束时立即拒绝启动，
不会先覆盖旧日志再等原语超时；Linux 停栈也会按本轮身份收尾独立进程组中的子进程。
若停栈失败，保留状态与日志并查明占用者，不按进程名称批量杀进程。

网页在机器人回环地址 `http://127.0.0.1:50108/outdoor`。

两份清单均启动山猫前摄像头（video4），Scene 的 `/cam` 直接显示原语画面，
不依赖 `tools/camera_view` 网页。需安装 `ffmpeg`，Python 环境需有 NumPy 和 Pillow。
相机断流时后台继续重连，不阻止定位、地图和 Scene 启动。
独立工具网页仍可用于切换前后左右相机。
Scene 电量显示复用独立工具的电量服务（`camera_battery_port: 8080`），
需启动 `lynx-camera.service`；每 5 秒刷新，断开或过期时会提示。

本体通信在 domain 0，室外程序在 domain 80。不使用本体 `/ODOM`。
启动不自动站起或发目标；航向质量尚未确认，动态精度与真实楼梯待现场验收。

统一文档位于 outdoorNav 工作区的 `docs/ARCHITECTURE.md`、`docs/DEPLOYMENT.md` 和
`docs/VALIDATION.md`。地图及采集记录保留在 `data/outdoor_mapping`，日志在 `run`。

## 本机地面基准与仅雷达准备

导航新分支必须在 `config/ground.local.json` 填入本机地面 z；该文件被 Git 和工作区同步脚本排除，无有效值会拒绝初始化。模板 `ground.local.example.json` 不带数值默认。雷达/地形与相机地面检测统一使用该值，不在清单分别存两份。

当前使用 `feat/vision-multisensor-navigation`，正式测试保持普通路线导航，`decision_cycle.enabled=false`。2026-11-24 的 field 配置已打开实验性 RGB-D 楼梯语义识别和上楼状态机，关闭旧相机几何链；识别式上楼尚未通过验收。检查配置仍不输出真实运动。


## 现场绕法清理后的配置

Nav2 的地图尺寸、分辨率、控制器、速度和足迹只在 `config/outdoor_nav2.yaml` 配置，不再叠加 manifest 的 `global_grid` 覆盖。普通导航使用有序短窗口，周期模式使用局部 odom 快照；终点远于窗口并不要求扩大感知图。

两份 profile 已分开：检查配置保留雷达与禁运动设置，field 配置包含当日楼梯识别实验参数。底盘准备检查已恢复：常规步态可以请求导航步态，速度仍要等待实际步态确认；不再需要 `require_chassis_ready=false`。terrain/decision_cycle 可以独立或同时开启，不把关闭它们当作修复。field 的 `can_climb_stairs=true` 是试验开关，不是已通过实机爬楼验收的结论。

平地避障保留 DWB 车心判据，不启用车体多边形判据；到点容差保持 3 m。临时改动的保留/撤销依据与未证实的现场诊断记录在 OutdoorNav 工作区 `docs/FIELD_CHANGES_20261120.md`。开发验证使用独立 `outdoorNav-indoor-20261120` 目录，不自动恢复真实底盘运动。

## 2026-11-24 handoff

Start with [the workspace handoff](https://github.com/Stone749990226/outdoorNav/blob/integrate-existing-lynx-navigation/docs/HANDOFF_20261124.md).
It lists the field changes, failed ascent checks, model revision and tomorrow's
perception-only verification steps. Exact dependency commits are in `sources.json`.
Do not run `scripts/prepare.py` over locally modified package trees.

The stair experiment needs the JetPack-provided CUDA PyTorch and matching
`requirements-stairs.txt`. Model files stay under the ignored `models/` directory;
GNSS accounts, password and ground calibration stay machine-local.
