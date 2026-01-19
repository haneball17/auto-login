from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml
from PyQt6.QtCore import QTimer, QTime, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from .config import load_config


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("auto-login 控制台")
        self.resize(1100, 760)

        self.base_dir = Path(__file__).resolve().parents[1]
        self.config_path = self.base_dir / "config.yaml"
        self.stop_flag_path = self.base_dir / "stop.flag"
        self.logs_dir = self.base_dir / "logs"
        self.evidence_dir = self.base_dir / "evidence"

        self._runner_process = None
        self._once_processes: list = []
        self._log_path: Path | None = None
        self._log_offset = 0
        self._current_account = "-"
        self._current_step = "-"

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.config_tab = self._build_config_tab()
        self.run_tab = self._build_run_tab()
        self.log_tab = self._build_log_tab()

        self.tabs.addTab(self.config_tab, "配置")
        self.tabs.addTab(self.run_tab, "执行")
        self.tabs.addTab(self.log_tab, "日志")

        self._load_config_text()
        self._refresh_log_files()

        self.log_timer = QTimer(self)
        self.log_timer.setInterval(1000)
        self.log_timer.timeout.connect(self._poll_log_updates)
        self.log_timer.start()

    def _build_config_tab(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)

        schedule_group = QGroupBox("调度设置")
        schedule_layout = QGridLayout(schedule_group)

        self.schedule_mode = QComboBox()
        self.schedule_mode.addItem("固定时间", "fixed_times")
        self.schedule_mode.addItem("随机窗口", "random_window")
        self.schedule_mode.currentIndexChanged.connect(
            self._on_schedule_mode_changed,
        )

        self.time_first = QTimeEdit()
        self.time_first.setDisplayFormat("HH:mm")
        self.time_second = QTimeEdit()
        self.time_second.setDisplayFormat("HH:mm")

        self.jitter_minutes = QSpinBox()
        self.jitter_minutes.setRange(0, 120)
        self.jitter_minutes.setSuffix(" 分钟")

        self.min_gap_minutes = QSpinBox()
        self.min_gap_minutes.setRange(1, 1440)
        self.min_gap_minutes.setSuffix(" 分钟")

        apply_button = QPushButton("应用到 YAML")
        apply_button.clicked.connect(self._apply_schedule_to_yaml)

        schedule_layout.addWidget(QLabel("调度模式"), 0, 0)
        schedule_layout.addWidget(self.schedule_mode, 0, 1)
        schedule_layout.addWidget(QLabel("第一次时间"), 1, 0)
        schedule_layout.addWidget(self.time_first, 1, 1)
        schedule_layout.addWidget(QLabel("第二次时间"), 2, 0)
        schedule_layout.addWidget(self.time_second, 2, 1)
        schedule_layout.addWidget(QLabel("随机范围"), 3, 0)
        schedule_layout.addWidget(self.jitter_minutes, 3, 1)
        schedule_layout.addWidget(QLabel("最小间隔"), 4, 0)
        schedule_layout.addWidget(self.min_gap_minutes, 4, 1)
        schedule_layout.addWidget(apply_button, 5, 0, 1, 2)

        self.config_editor = QPlainTextEdit()
        self.config_editor.setTabStopDistance(4 * 8)

        button_row = QHBoxLayout()
        load_button = QPushButton("加载")
        save_button = QPushButton("保存")
        validate_button = QPushButton("语法校验")

        load_button.clicked.connect(self._load_config_text)
        save_button.clicked.connect(self._save_config_text)
        validate_button.clicked.connect(self._validate_config_text)

        button_row.addWidget(load_button)
        button_row.addWidget(save_button)
        button_row.addWidget(validate_button)
        button_row.addStretch()

        layout.addWidget(schedule_group)
        layout.addWidget(QLabel("config.yaml（原始编辑）"))
        layout.addWidget(self.config_editor, 1)
        layout.addLayout(button_row)

        return container

    def _build_run_tab(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)

        status_group = QGroupBox("运行状态")
        status_layout = QGridLayout(status_group)
        self.status_process = QLabel("调度进程：未运行")
        self.status_account = QLabel("当前账号：-")
        self.status_step = QLabel("当前步骤：-")
        status_layout.addWidget(self.status_process, 0, 0)
        status_layout.addWidget(self.status_account, 1, 0)
        status_layout.addWidget(self.status_step, 2, 0)

        control_group = QGroupBox("执行控制")
        control_layout = QHBoxLayout(control_group)
        self.start_button = QPushButton("开始")
        self.stop_button = QPushButton("停止")
        self.force_stop_button = QPushButton("强制停止")
        self.once_button = QPushButton("立即执行一次")
        self.reset_state_button = QPushButton("重置登录进度")

        self.start_button.clicked.connect(self._start_scheduler)
        self.stop_button.clicked.connect(self._stop_scheduler)
        self.force_stop_button.clicked.connect(self._force_stop)
        self.once_button.clicked.connect(self._run_once)
        self.reset_state_button.clicked.connect(self._reset_state)

        control_layout.addWidget(self.start_button)
        control_layout.addWidget(self.stop_button)
        control_layout.addWidget(self.force_stop_button)
        control_layout.addWidget(self.once_button)
        control_layout.addWidget(self.reset_state_button)

        layout.addWidget(status_group)
        layout.addWidget(control_group)
        layout.addStretch()
        return container

    def _build_log_tab(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)

        top_row = QHBoxLayout()
        self.log_file_combo = QComboBox()
        refresh_button = QPushButton("刷新文件列表")
        refresh_button.clicked.connect(self._refresh_log_files)
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("关键字过滤")
        self.filter_input.textChanged.connect(self._on_filter_changed)
        self.auto_scroll = QCheckBox("实时滚动")
        self.auto_scroll.setChecked(True)

        folder_group = QHBoxLayout()
        self.folder_combo = QComboBox()
        self.folder_combo.addItem("logs", "logs")
        self.folder_combo.addItem("evidence", "evidence")
        open_folder_button = QPushButton("打开文件夹")
        open_folder_button.clicked.connect(self._open_selected_folder)
        folder_group.addWidget(self.folder_combo)
        folder_group.addWidget(open_folder_button)

        self.log_file_combo.currentIndexChanged.connect(
            self._load_selected_log_file,
        )

        top_row.addWidget(QLabel("日志文件"))
        top_row.addWidget(self.log_file_combo, 2)
        top_row.addWidget(refresh_button)
        top_row.addWidget(self.filter_input, 2)
        top_row.addWidget(self.auto_scroll)
        top_row.addLayout(folder_group)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)

        layout.addLayout(top_row)
        layout.addWidget(self.log_view, 1)
        return container

    def _load_config_text(self) -> None:
        if not self.config_path.is_file():
            QMessageBox.warning(self, "配置错误", "未找到 config.yaml")
            return
        text = self.config_path.read_text(encoding="utf-8")
        self.config_editor.setPlainText(text)
        self._sync_schedule_fields(text)
        self._update_evidence_dir(text)

    def _save_config_text(self) -> None:
        text = self.config_editor.toPlainText()
        self.config_path.write_text(text, encoding="utf-8")
        self._update_evidence_dir(text)
        QMessageBox.information(self, "保存成功", "config.yaml 已保存")

    def _validate_config_text(self) -> None:
        text = self.config_editor.toPlainText()
        data = self._parse_yaml(text)
        if data is None:
            return
        try:
            temp_path = self.base_dir / ".ui_config_check.yaml"
            temp_path.write_text(text, encoding="utf-8")
            load_config(
                config_path=temp_path,
                base_dir=self.base_dir,
                env_path=self.base_dir / ".env",
                validate_paths=False,
            )
        except Exception as exc:
            QMessageBox.warning(self, "校验失败", str(exc))
            return
        finally:
            if "temp_path" in locals() and temp_path.exists():
                temp_path.unlink()
        QMessageBox.information(self, "校验成功", "配置可用")

    def _apply_schedule_to_yaml(self) -> None:
        text = self.config_editor.toPlainText()
        data = self._parse_yaml(text)
        if data is None:
            return
        schedule = data.get("schedule", {})
        mode = self.schedule_mode.currentData()
        schedule["mode"] = mode
        schedule["min_gap_minutes"] = self.min_gap_minutes.value()
        time1 = self.time_first.time().toString("HH:mm")
        time2 = self.time_second.time().toString("HH:mm")
        if mode == "random_window":
            jitter = self.jitter_minutes.value()
            schedule["random_windows"] = [
                {"center": time1, "jitter_minutes": jitter},
                {"center": time2, "jitter_minutes": jitter},
            ]
            schedule.setdefault("fixed_times", [time1, time2])
        else:
            schedule["fixed_times"] = [time1, time2]
            schedule.setdefault(
                "random_windows",
                [
                    {"center": time1, "jitter_minutes": 0},
                    {"center": time2, "jitter_minutes": 0},
                ],
            )
        data["schedule"] = schedule
        self.config_editor.setPlainText(
            yaml.safe_dump(
                data,
                allow_unicode=True,
                sort_keys=False,
            )
        )

    def _sync_schedule_fields(self, text: str) -> None:
        data = self._parse_yaml(text)
        if data is None:
            return
        schedule = data.get("schedule", {})
        mode = schedule.get("mode", "random_window")
        index = 1 if mode == "random_window" else 0
        self.schedule_mode.setCurrentIndex(index)

        time1, time2 = "07:00", "13:00"
        jitter = 0
        if mode == "random_window":
            windows = schedule.get("random_windows", [])
            if len(windows) >= 2:
                time1 = windows[0].get("center", time1)
                time2 = windows[1].get("center", time2)
                jitter = int(windows[0].get("jitter_minutes", 0))
        else:
            fixed_times = schedule.get("fixed_times", [])
            if len(fixed_times) >= 2:
                time1 = fixed_times[0]
                time2 = fixed_times[1]
            jitter = int(schedule.get("jitter_minutes", 0) or 0)

        self.time_first.setTime(self._safe_time(time1))
        self.time_second.setTime(self._safe_time(time2))
        self.jitter_minutes.setValue(jitter)
        self.min_gap_minutes.setValue(
            int(schedule.get("min_gap_minutes", 90)),
        )
        self._on_schedule_mode_changed()

    def _on_schedule_mode_changed(self) -> None:
        is_random = self.schedule_mode.currentData() == "random_window"
        self.jitter_minutes.setEnabled(is_random)

    def _safe_time(self, value: str) -> QTime:
        parsed = QTime.fromString(value, "HH:mm")
        if parsed.isValid():
            return parsed
        return QTime(7, 0)

    def _parse_yaml(self, text: str) -> dict | None:
        try:
            data = yaml.safe_load(text) or {}
        except yaml.YAMLError as exc:
            QMessageBox.warning(self, "YAML 解析失败", str(exc))
            return None
        if not isinstance(data, dict):
            QMessageBox.warning(self, "YAML 解析失败", "配置内容格式不正确")
            return None
        return data

    def _update_evidence_dir(self, text: str) -> None:
        data = self._parse_yaml(text)
        if data is None:
            return
        evidence = data.get("evidence", {})
        dir_value = evidence.get("dir", "evidence")
        self.evidence_dir = self.base_dir / Path(str(dir_value))

    def _start_scheduler(self) -> None:
        if self._runner_process and self._runner_process.state() != 0:
            QMessageBox.information(self, "提示", "调度已在运行")
            return
        self._clear_stop_flag()
        self._runner_process = self._start_process(["-m", "src.main"])
        self.status_process.setText("调度进程：运行中")

    def _stop_scheduler(self) -> None:
        self.stop_flag_path.write_text("stop", encoding="utf-8")
        QMessageBox.information(self, "提示", "已写入 stop.flag，等待当前账号完成")

    def _force_stop(self) -> None:
        self._write_status("执行中止", "强制停止已触发")
        if self._runner_process and self._runner_process.state() != 0:
            self._runner_process.kill()
        for process in list(self._once_processes):
            if process.state() != 0:
                process.kill()
        self._once_processes.clear()
        self.status_process.setText("调度进程：未运行")

    def _run_once(self) -> None:
        self._clear_stop_flag()
        process = self._start_process(["-m", "src.main", "--once"])
        self._once_processes.append(process)

    def _reset_state(self) -> None:
        if self._runner_process and self._runner_process.state() != 0:
            QMessageBox.information(self, "提示", "调度正在运行，请先停止再重置登录进度")
            return
        if any(process.state() != 0 for process in self._once_processes):
            QMessageBox.information(self, "提示", "单次执行仍在运行，请先停止再重置登录进度")
            return
        confirm = QMessageBox.question(
            self,
            "确认重置",
            "将覆盖 logs/state.json 为 {}，账号进度将从头开始。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        state_path = self.logs_dir / "state.json"
        state_path.write_text("{}", encoding="utf-8")
        self._current_account = "-"
        self._current_step = "-"
        self.status_account.setText("当前账号：-")
        self.status_step.setText("当前步骤：-")
        QMessageBox.information(self, "重置完成", "账号登录进度已重置")

    def _start_process(self, args: list[str]):
        from PyQt6.QtCore import QProcess

        process = QProcess(self)
        process.setWorkingDirectory(str(self.base_dir))
        process.start(sys.executable, args)
        process.finished.connect(lambda: self._cleanup_process(process))
        return process

    def _cleanup_process(self, process) -> None:
        if process is self._runner_process:
            self.status_process.setText("调度进程：未运行")
            self._runner_process = None
        if process in self._once_processes:
            self._once_processes.remove(process)

    def _clear_stop_flag(self) -> None:
        if self.stop_flag_path.exists():
            self.stop_flag_path.unlink()

    def _refresh_log_files(self) -> None:
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        files = sorted(self.logs_dir.glob("*.log"), reverse=True)
        self.log_file_combo.clear()
        for path in files:
            self.log_file_combo.addItem(path.name, path)
        if files:
            self.log_file_combo.setCurrentIndex(0)
            self._load_selected_log_file()

    def _load_selected_log_file(self) -> None:
        path = self.log_file_combo.currentData()
        if not isinstance(path, Path):
            return
        self._log_path = path
        self._log_offset = 0
        self._render_log(full_reload=True)

    def _on_filter_changed(self) -> None:
        self._render_log(full_reload=True)

    def _poll_log_updates(self) -> None:
        if self._log_path is None:
            return
        self._render_log(full_reload=False)

    def _render_log(self, full_reload: bool) -> None:
        if self._log_path is None or not self._log_path.is_file():
            return
        filter_text = self.filter_input.text().strip()
        try:
            with self._log_path.open("r", encoding="utf-8") as handle:
                if full_reload:
                    content = handle.read()
                    self._log_offset = handle.tell()
                    lines = content.splitlines()
                    self.log_view.setPlainText(
                        self._filter_lines(lines, filter_text),
                    )
                    self._update_status_from_log_lines(lines)
                else:
                    handle.seek(self._log_offset)
                    new_content = handle.read()
                    if not new_content:
                        return
                    self._log_offset = handle.tell()
                    new_lines = new_content.splitlines()
                    self._append_log_lines(new_lines, filter_text)
        except OSError:
            return

    def _filter_lines(self, lines: list[str], keyword: str) -> str:
        if not keyword:
            return "\n".join(lines)
        return "\n".join(
            line for line in lines if keyword in line
        )

    def _append_log_lines(self, lines: list[str], keyword: str) -> None:
        filtered = self._filter_lines(lines, keyword)
        if filtered:
            self.log_view.appendPlainText(filtered)
        self._update_status_from_log_lines(lines)
        if self.auto_scroll.isChecked():
            self.log_view.verticalScrollBar().setValue(
                self.log_view.verticalScrollBar().maximum(),
            )

    def _update_status_from_log_lines(self, lines: list[str]) -> None:
        for line in lines:
            account = self._extract_account(line)
            if account:
                self._current_account = account
                self.status_account.setText(f"当前账号：{account}")
            step = self._extract_step(line)
            if step:
                self._current_step = step
                self.status_step.setText(f"当前步骤：{step}")

    def _extract_account(self, line: str) -> str | None:
        match = re.search(r"开始处理账号: (.+?) /", line)
        if match:
            return match.group(1).strip()
        match = re.search(r"账号 \\d+/\\d+ 第 \\d+/\\d+ 次尝试: (\\S+)", line)
        if match:
            return match.group(1).strip()
        return None

    def _extract_step(self, line: str) -> str | None:
        step_map = [
            ("启动登录器", "启动器"),
            ("等待登录URL", "等待登录URL"),
            ("开始网页登录", "网页登录"),
            ("网页登录成功", "网页登录完成"),
            ("游戏窗口就绪", "游戏窗口"),
            ("频道选择界面", "频道选择"),
            ("角色选择界面", "角色选择"),
            ("进入游戏界面匹配成功", "进入游戏"),
            ("进入游戏界面，等待", "游戏内等待"),
            ("强制结束游戏进程", "退出游戏"),
            ("账号流程完成", "账号完成"),
            ("单次全账号流程结束", "流程结束"),
            ("调度任务开始", "调度任务"),
            ("调度任务结束", "调度任务结束"),
        ]
        for keyword, label in step_map:
            if keyword in line:
                return label
        return None

    def _open_selected_folder(self) -> None:
        choice = self.folder_combo.currentData()
        if choice == "logs":
            folder = self.logs_dir
        else:
            folder = self.evidence_dir
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _write_status(self, title: str, message: str) -> None:
        QMessageBox.information(self, title, message)


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
