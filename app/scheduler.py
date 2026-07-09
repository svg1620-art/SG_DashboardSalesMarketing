"""Ежедневный автосинк через APScheduler (ТЗ §6, §9).

Крутится в фоне веб-процесса. При нескольких воркерах защиту от двойного
запуска обеспечивает advisory-lock внутри run_sync.
"""
from apscheduler.schedulers.background import BackgroundScheduler

from .sync import run_sync

_scheduler: BackgroundScheduler | None = None


def init_scheduler(config):
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    if not config.ENABLE_SCHEDULER or not config.DATABASE_URL:
        return None

    sched = BackgroundScheduler(timezone="UTC")
    sched.add_job(
        run_sync,
        trigger="cron",
        hour=config.SYNC_HOUR_UTC,
        minute=0,
        args=[config],
        kwargs={"full": False},
        id="daily_sync",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    sched.start()
    _scheduler = sched
    return sched
