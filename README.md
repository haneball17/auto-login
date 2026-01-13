# auto-login

Windows11 游戏自动登录与签到自动化项目（MVP）。

## 运行方式

- 启动主程序：`poetry run python -m src.main`
- 启动器 + 网页登录：`poetry run python -m src.main --launcher-web-login`
- 启动前端：`poetry run python -m src.ui`（M5 完成后）
- 本地启动器路径请在 `.env` 中设置 `LAUNCHER__EXE_PATH`

## 规范

- 代码风格遵循 PEP 8
