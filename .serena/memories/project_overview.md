# 项目概览
- 目标：Windows11 游戏自动登录与签到自动化（MVP），每日两次登录周期（间隔>=90分钟），账号池轮换，网页登录+客户端操作（频道/角色选择/进入游戏/退出）。
- 运行环境：仅支持 Windows11 实际运行；Linux 仅保证单元测试可跑。
- 调度：APScheduler 常驻，默认随机窗口（07:00±3min、13:00±3min），可切换固定时间。
- 自动化：Playwright（网页登录）+ OpenCV 模板匹配 + PyAutoGUI 操作；psutil/pywin32 进程/窗口；PyQt6 简单前端。
- 结构：根目录扁平化，配置驱动（config.yaml + .env），功能模块按 ops/runner 拆分。
