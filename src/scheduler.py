from __future__ import annotations

import os
import random
import threading
from datetime import date, datetime, time, timedelta
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.date import DateTrigger

from .config import AppConfig, _parse_time, load_config
from .runner import run_all_accounts_once

import logging

logger = logging.getLogger("auto_login")
_job_lock = threading.Lock()


class FileLock:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle = None

    def acquire(self) -> bool:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = self._path.open("a+", encoding="utf-8")
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False

        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        self._handle = handle
        return True

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            self._handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            self._handle.close()
            self._handle = None


def run_scheduler(
    config: AppConfig,
    base_dir: Path,
    config_path: Path,
    env_path: Path,
    validate_paths: bool,
    required_anchors: list[str] | None,
) -> None:
    scheduler = BlockingScheduler()
    stop_flag = base_dir / "stop.flag"
    lock_path = base_dir / "logs" / "run.lock"
    scheduled_job_ids: list[str] = []

    def job_runner() -> None:
        if not _job_lock.acquire(blocking=False):
            logger.warning("任务仍在运行，跳过本次调度")
            return
        if stop_flag.exists():
            logger.info("检测到 stop.flag，本次任务不启动")
            _job_lock.release()
            return
        lock = FileLock(lock_path)
        if not lock.acquire():
            logger.warning("已有任务在运行，跳过本次调度")
            _job_lock.release()
            return
        logger.info("调度任务开始")
        try:
            run_config = load_config(
                config_path=config_path,
                env_path=env_path,
                base_dir=base_dir,
                validate_paths=validate_paths,
                required_anchors=required_anchors,
            )
            run_all_accounts_once(
                run_config,
                base_dir,
                stop_flag_path=stop_flag,
            )
        except Exception as exc:
            logger.exception("调度任务异常: %s", exc)
        finally:
            lock.release()
            _job_lock.release()
            logger.info("调度任务结束")

    def schedule_for_today() -> None:
        for job_id in list(scheduled_job_ids):
            if scheduler.get_job(job_id):
                scheduler.remove_job(job_id)
        scheduled_job_ids.clear()

        run_times = _build_daily_times(config, date.today())
        now = datetime.now()
        for index, run_time in enumerate(run_times, 1):
            if run_time <= now:
                logger.warning("调度时间已过，立即补跑一次: %s", run_time)
                job_runner()
                continue
            job_id = f"daily_{run_time:%Y%m%d}_{index}"
            scheduler.add_job(
                job_runner,
                trigger=DateTrigger(run_time),
                id=job_id,
                replace_existing=True,
            )
            scheduled_job_ids.append(job_id)
        logger.info(
            "当天调度时间: %s",
            ", ".join(dt.strftime("%H:%M") for dt in run_times),
        )

    def schedule_next_day() -> None:
        schedule_for_today()
        next_refresh = datetime.combine(
            date.today() + timedelta(days=1),
            time(hour=0, minute=1),
        )
        scheduler.add_job(
            schedule_next_day,
            trigger=DateTrigger(next_refresh),
            id="daily_refresh",
            replace_existing=True,
        )

    schedule_next_day()
    logger.info("调度器已启动")
    scheduler.start()


def _build_daily_times(config: AppConfig, day: date) -> list[datetime]:
    schedule = config.schedule
    if schedule.mode == "fixed_times":
        run_times = [
            _combine_date(day, _parse_time(value).time())
            for value in schedule.fixed_times
        ]
        return sorted(run_times)

    seed = int(day.strftime("%Y%m%d"))
    rng = random.Random(seed)
    logger.info("随机窗口调度种子: %s", seed)
    attempts = 30
    run_times: list[datetime] = []
    for _ in range(attempts):
        run_times = []
        for window in schedule.random_windows:
            base_time = _combine_date(
                day,
                _parse_time(window.center).time(),
            )
            jitter = rng.randint(
                -window.jitter_minutes,
                window.jitter_minutes,
            )
            run_times.append(
                _clamp_to_day(base_time + timedelta(minutes=jitter), day),
            )
        if _minutes_gap(run_times[0], run_times[1]) >= schedule.min_gap_minutes:
            return sorted(run_times)
    logger.warning("随机窗口无法满足最小间隔，使用中心时间")
    for window in schedule.random_windows:
        run_times.append(
            _combine_date(day, _parse_time(window.center).time()),
        )
    return sorted(run_times)


def _combine_date(day: date, clock: time) -> datetime:
    return datetime.combine(day, clock)


def _minutes_gap(a: datetime, b: datetime) -> int:
    gap = abs((a - b).total_seconds()) / 60
    return int(gap)


def _clamp_to_day(value: datetime, day: date) -> datetime:
    day_start = datetime.combine(day, time.min)
    day_end = datetime.combine(day, time.max)
    if value < day_start:
        return day_start
    if value > day_end:
        return day_end
    return value
