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

两份清单在 check 模式都启动山猫前摄像头（video4），Scene 的 `/cam` 直接显示原语画面，
不依赖 `tools/camera_view` 网页。需安装 `ffmpeg`，Python 环境需有 NumPy 和 Pillow。
相机断流时后台继续重连，不阻止定位、地图和 Scene 启动。
独立工具网页仍可用于切换前后左右相机。
Scene 电量显示复用独立工具的电量服务（`camera_battery_port: 8080`），
需启动 `lynx-camera.service`；每 5 秒刷新，断开或过期时会提示。

本体通信在 domain 0，室外程序在 domain 80。不使用本体 `/ODOM`。
启动不自动站起或发目标；航向质量尚未确认，动态精度与真实楼梯待现场验收。

统一文档位于 outdoorNav 工作区的 `docs/ARCHITECTURE.md`、`docs/DEPLOYMENT.md` 和
`docs/VALIDATION.md`。地图及采集记录保留在 `data/outdoor_mapping`，日志在 `run`。

## 仅雷达与地面基准

室外默认只用雷达避障（`camera_enabled` 保持默认关闭），RGB 预览不受影响。本版导航只消费雷达点云，不再读取 `config/ground.local.json`，清单里也没有 `ground_height_file`；该文件可以保留，但导航不使用。

当前导航基于 main `fe738b6` 加非视觉回迁：继续使用录制路线的步态区段切换楼梯步态，不启用视觉分割、地形状态机或周期方向引导。检查配置不输出真实运动。

## 两个 profile

`robonix_manifest.yaml`（检查）不输出真实运动：`motion_enabled: false`，底盘原语 `allow_motion`/`allow_gait` 为 false，速度发到 `/robonix/nomotion/outdoor_cmd_vel`、步态发到 `/robonix/nomotion/outdoor_gait`，Scene 的执行关闭。
`robonix_manifest.field.yaml`（运动）许可底盘运动与步态，速度发到 `/cmd_vel`。
加载环境前设置 `OUTDOOR_MODE=check`（默认）或 `OUTDOOR_MODE=preview`；`preview` 关闭硬件并改为启动 Pilot，从环境读取 `ROBONIX_VLM_UPSTREAM`、`ROBONIX_VLM_MODEL` 和 `ROBONIX_VLM_API_KEY`。

Nav2 的地图尺寸、分辨率、控制器、速度和足迹只在 `config/outdoor_nav2.yaml` 配置；清单只给感知图一个 20 m × 20 m、0.1 m 分辨率、随车滚动的初始窗口，不覆盖 Nav2 参数。普通导航使用有序短窗口；终点远于窗口并不要求扩大感知图。

`policy.gait_boundary_tolerance_m`（默认 0.25 m）要求到达录制路线中步态切换所在站点后才继续；普通中间点仍按原有宽松条件通过，最终到点容差仍为 3 m。规划器不得跳过或挪开步态切换站点，找不到可行路径时停车报原因，不用捷径进入楼梯。站立但已在导航模式时可以先请求并确认步态，速度仍必须等真实步态反馈。

平地避障保留 DWB 车心判据，不启用车体多边形判据；到点容差保持 3 m。临时改动的保留/撤销依据与未证实的现场诊断记录在 OutdoorNav 工作区 `docs/FIELD_CHANGES_20261120.md`。开发验证使用独立 `outdoorNav-indoor-20261120` 目录，不自动恢复真实底盘运动。

## 2026-11-26 recorded-gait backport

非视觉回迁清单在 `service-navigation-outdoor-rbnx` 的 `docs/MAIN_BACKPORT_20261126.md`：稀疏直线规划、统一转弯判定、定位修正后的恢复、雷达采集时间与乱序丢弃、底盘准备与运动许可拆分，以及强制步态边界站点。楼梯步态仍来自录制路线区间；视觉分割、地形状态机和周期方向引导不参与本部署。

`requirements-stairs.txt` 和 `models/` 本 profile 不使用。GNSS 账号、密码和地面标定保持机器本地。不要在本地改过的包树上跑 `scripts/prepare.py`；确切依赖提交见 `sources.json`。
