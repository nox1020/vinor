import asyncio
import json
import os
from datetime import timedelta

from . import bot

WORKER_LOCK_FILE = os.path.join(bot._PROJECT_ROOT, ".worker.lock")


def _pid_alive(pid: int) -> bool:
    """بررسی زنده بودن یک PID به صورت سبک و بدون وابستگی خارجی"""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _acquire_worker_lock() -> bool:
    """جلوگیری از اجرای هم‌زمان چند worker"""
    if os.path.exists(WORKER_LOCK_FILE):
        try:
            with open(WORKER_LOCK_FILE, "r", encoding="utf-8") as f:
                old_pid = int((f.read() or "0").strip())
            if _pid_alive(old_pid):
                print(f"⚠️ Worker already running with pid={old_pid}. Exiting duplicate instance.")
                return False
        except Exception:
            pass
    try:
        with open(WORKER_LOCK_FILE, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
        return True
    except Exception as e:
        print(f"❌ Cannot create worker lock file: {e}")
        return False


def _release_worker_lock():
    try:
        if os.path.exists(WORKER_LOCK_FILE):
            with open(WORKER_LOCK_FILE, "r", encoding="utf-8") as f:
                pid_in_file = int((f.read() or "0").strip())
            if pid_in_file == os.getpid():
                os.remove(WORKER_LOCK_FILE)
    except Exception:
        pass


def parse_time_text(value: str):
    raw = (value or "").strip()
    if ":" in raw:
        parts = raw.split(":")
        if len(parts) != 2:
            raise ValueError("فرمت زمان نامعتبر است")
        hour = int(parts[0].strip())
        minute = int(parts[1].strip())
    else:
        hour = int(raw)
        minute = 0
    if hour < 0 or hour > 23:
        raise ValueError("ساعت باید بین 0 تا 23 باشد")
    if minute < 0 or minute > 59:
        raise ValueError("دقیقه باید بین 0 تا 59 باشد")
    return hour, minute


def parse_weekdays_text(value: str):
    raw = (value or "").strip()
    if not raw:
        raise ValueError("روزهای هفته خالی است")
    days = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        day = int(part)
        if day < 0 or day > 6:
            raise ValueError("روز باید بین 0 تا 6 باشد")
        days.append(day)
    if not days:
        raise ValueError("حداقل یک روز باید انتخاب شود")
    return sorted(list(set(days)))


async def apply_settings_reschedule_if_needed():
    # [audit] job شروع خودکار فقط در bot.py ساخته می‌شود (resync هر ۲ دقیقه از configs.json).
    # ساختن همان job در worker باعث دو شروع هم‌زمان در ساعت شروع (نردبان/پرداخت دوبل) می‌شد.
    return
    start_time = bot.get_start_time_from_config()
    if start_time is None:
        return
    start_hour, start_minute = start_time
    admins = bot.curd.getAdmins()
    for admin_id in admins:
        try:
            await bot.setup_auto_start_job(int(admin_id), start_hour, start_minute)
        except Exception as e:
            print(f"⚠️ خطا در بروزرسانی auto start برای ادمین {admin_id}: {e}")
    if bot.Datas.admin:
        try:
            await bot.setup_auto_start_job(int(bot.Datas.admin), start_hour, start_minute)
        except Exception as e:
            print(f"⚠️ خطا در بروزرسانی auto start برای ادمین پیش‌فرض: {e}")


async def start_job(chatid: int):
    job_id = bot.curd.getJob(chatid=chatid)
    if job_id:
        raise ValueError("نردبان فعال از قبل وجود دارد")

    if not bot.is_repeat_period_active():
        raise ValueError("دوره تکرار به پایان رسیده است")

    if not bot.is_today_active_weekday():
        raise ValueError("امروز در روزهای فعال نیست")

    manage_details = bot.curd.getManage(chatid=chatid)
    if manage_details[0] != 1:
        raise ValueError("ابتدا ربات را فعال کنید")

    logins = bot.curd.getCookies(chatid=chatid)
    if not logins:
        raise ValueError("هیچ لاگین فعالی وجود ندارد")

    if bot.is_stop_time_in_past():
        raise ValueError("ساعت توقف خودکار در گذشته است")

    stop_time = bot.get_stop_time_from_config()
    if stop_time is not None:
        end_hour, _ = stop_time
    else:
        current_hour = bot.now_tehran().hour
        end_hour = (current_hour + 12) % 24

    await bot.startNardebanDasti(chatid=chatid, end=end_hour)


async def remove_job(chatid: int):
    job_id = bot.curd.getJob(chatid=chatid)
    if job_id:
        try:
            bot.scheduler.remove_job(job_id=job_id)
        except Exception:
            pass

        try:
            stop_job_id = f"auto_stop_{chatid}_{job_id}"
            bot.scheduler.remove_job(stop_job_id)
        except Exception:
            pass

    # حذف همه auto_stopهای مرتبط با چت (پوشش نوع 4 و حالت‌های مانده)
    try:
        for j in bot.scheduler.get_jobs():
            try:
                jid = str(getattr(j, "id", "") or "")
                if jid.startswith(f"auto_stop_{chatid}"):
                    bot.scheduler.remove_job(jid)
            except Exception:
                continue
    except Exception:
        pass

    # پاکسازی jobهای باقیمانده sendNardeban برای این چت (خصوصاً type 4/date jobs)
    try:
        for j in bot.scheduler.get_jobs():
            try:
                j_args = list(getattr(j, "args", []) or [])
                if not j_args:
                    continue
                if int(j_args[0]) != int(chatid):
                    continue
                func_ref = str(getattr(j, "func_ref", "") or "")
                if "sendNardeban" in func_ref:
                    bot.scheduler.remove_job(j.id)
            except Exception:
                continue
    except Exception:
        pass

    bot.curd.removeJob(chatid=chatid)
    bot.refreshUsed(chatid=chatid)


async def execute_command(command_row):
    command_id, chatid, command_type, payload_text, status, created_at = command_row
    chatid = int(chatid)
    payload = {}
    if payload_text:
        try:
            payload = json.loads(payload_text)
        except Exception:
            payload = {}

    primary = int(bot.Datas.admin) if bot.Datas.admin is not None else None

    def _require_primary():
        if primary is not None and chatid != primary:
            raise ValueError("این عمل فقط با حساب ادمین اصلی در پنل وب مجاز است.")

    if command_type == "setactive":
        active = 1 if str(payload.get("active", "0")) == "1" else 0
        bot.curd.setStatusManage(q="active", v=active, chatid=chatid)
        return True, f"active={active}"

    if command_type == "setInterval":
        interval = int(payload.get("interval_minutes", "5"))
        if interval < 1:
            raise ValueError("interval_minutes باید حداقل 1 باشد")
        bot.curd.setStatusManage(q="interval_minutes", v=interval, chatid=chatid)
        return True, f"interval={interval}"

    if command_type == "setNaturalFlowRange":
        lo = int(payload.get("natural_flow_min_minutes", "3"))
        hi = int(payload.get("natural_flow_max_minutes", "15"))
        lo = max(1, min(lo, 1440))
        hi = max(1, min(hi, 1440))
        if lo > hi:
            lo, hi = hi, lo
        bot.curd.setStatusManage(q="natural_flow_min_minutes", v=lo, chatid=chatid)
        bot.curd.setStatusManage(q="natural_flow_max_minutes", v=hi, chatid=chatid)
        return True, f"natural_flow_min_max={lo}-{hi}"

    if command_type == "setNardebanType":
        ntype = int(payload.get("nardeban_type", "1"))
        if ntype not in (1, 2, 3, 4):
            raise ValueError("نوع نردبان باید بین 1 تا 4 باشد")
        bot.curd.setStatusManage(q="nardeban_type", v=ntype, chatid=chatid)
        return True, f"nardeban_type={ntype}"

    if command_type == "setStartTime":
        _require_primary()
        hour, minute = parse_time_text(payload.get("time_text", ""))
        ok = bot.set_start_time_in_config(hour, minute)
        if not ok:
            raise ValueError("ذخیره زمان شروع ناموفق بود")
        await apply_settings_reschedule_if_needed()
        return True, f"start={hour:02d}:{minute:02d}"

    if command_type == "setStopTime":
        _require_primary()
        hour, minute = parse_time_text(payload.get("time_text", ""))
        ok = bot.set_stop_time_in_config(hour, minute)
        if not ok:
            raise ValueError("ذخیره زمان توقف ناموفق بود")
        return True, f"stop={hour:02d}:{minute:02d}"

    if command_type == "setRepeatDays":
        _require_primary()
        days = int(payload.get("repeat_days", "365"))
        if days < 1 or days > 3650:
            raise ValueError("repeat_days باید بین 1 تا 3650 باشد")
        ok = bot.set_repeat_days_in_config(days, reset_start_date=True)
        if not ok:
            raise ValueError("ذخیره روزهای تکرار ناموفق بود")
        await apply_settings_reschedule_if_needed()
        return True, f"repeat_days={days}"

    if command_type == "setWeekdays":
        _require_primary()
        weekdays = parse_weekdays_text(payload.get("weekdays", ""))
        ok = bot.set_active_weekdays_in_config(weekdays)
        if not ok:
            raise ValueError("ذخیره روزهای هفته ناموفق بود")
        await apply_settings_reschedule_if_needed()
        return True, f"weekdays={weekdays}"

    if command_type == "setLoginActive":
        phone = str(payload.get("phone", "")).strip()
        active = 1 if str(payload.get("active", "0")) == "1" else 0
        success, message = bot.curd.activeLogin(phone=phone, status=active, chatid=chatid)
        if not success:
            raise ValueError(message)
        return True, message

    if command_type == "deleteLogin":
        phone = str(payload.get("phone", "")).strip()
        ok = bot.curd.delLoginByChatid(phone=phone, chatid=chatid)
        if not ok:
            raise ValueError("شماره برای این ادمین یافت نشد یا حذف نشد")
        return True, f"deleted phone={phone}"

    if command_type == "startJob":
        await start_job(chatid)
        return True, "started"

    if command_type == "remJob":
        await remove_job(chatid)
        return True, "stopped"

    if command_type == "reExtract":
        await bot.reExtractTokens(chatid=chatid)
        return True, "reExtract done"

    if command_type == "resetTokens":
        await bot.resetAllExtractions(chatid=chatid)
        return True, "resetTokens done"

    if command_type == "addAdmin":
        _require_primary()
        raw = str(payload.get("admin_chat_id", "")).strip()
        if not raw.isdigit():
            raise ValueError("شناسه چت باید فقط عدد باشد")
        new_id = int(raw)
        if new_id <= 0:
            raise ValueError("شناسه چت نامعتبر است")
        primary = int(bot.Datas.admin) if bot.Datas.admin is not None else None
        if primary is not None and new_id == primary:
            return True, "این همان ادمین پیش‌فرض است (از قبل در سیستم)"
        if bot.curd.setAdmin(chatid=new_id) != 1:
            raise ValueError("افزودن ادمین ناموفق بود")
        try:
            await bot.bot_send_message(
                chat_id=new_id,
                text="شما به لیست ادمین‌های ربات اضافه شدید؛ برای فعال‌سازی /start را بزنید.",
            )
        except Exception:
            pass
        return True, f"ادمین {new_id} اضافه شد"

    if command_type == "removeAdmin":
        _require_primary()
        raw = str(payload.get("admin_chat_id", "")).strip()
        if not raw.isdigit():
            raise ValueError("شناسه چت باید فقط عدد باشد")
        rid = int(raw)
        primary = int(bot.Datas.admin) if bot.Datas.admin is not None else None
        if primary is not None and rid == primary:
            raise ValueError("ادمین پیش‌فرض قابل حذف نیست")
        if bot.curd.remAdmin(chatid=rid) != 1:
            raise ValueError("حذف ادمین ناموفق بود")
        try:
            await bot.bot_send_message(
                chat_id=rid,
                text="شما از لیست ادمین‌های ربات حذف شدید.",
            )
        except Exception:
            pass
        return True, f"ادمین {rid} حذف شد"

    raise ValueError(f"command_type ناشناخته: {command_type}")


async def process_pending_commands():
    pending = bot.curd.getPendingWebCommands(limit=30)
    if not pending:
        return
    for row in pending:
        command_id = row[0]
        if not bot.curd.lockWebCommand(command_id):
            continue
        try:
            ok, result = await execute_command(row)
            bot.curd.completeWebCommand(command_id, success=ok, result_text=str(result))
        except Exception as e:
            bot.curd.completeWebCommand(command_id, success=False, result_text=str(e))


async def bootstrap_scheduler():
    loop = asyncio.get_running_loop()
    bot.scheduler.configure(event_loop=loop)
    if not bot.scheduler.running:
        bot.scheduler.start()

    # [audit] شروع خودکار فقط در bot.py؛ اینجا غیرفعال شد تا ساعت ۸ دو نردبان هم‌زمان شروع نشود.
    try:
        start_time = None
        if start_time is not None:
            start_hour, start_minute = start_time
            admins = bot.curd.getAdmins()
            for admin_id in admins:
                try:
                    await bot.setup_auto_start_job(int(admin_id), start_hour, start_minute)
                except Exception as e:
                    print(f"⚠️ خطا در auto_start ادمین {admin_id}: {e}")
            if bot.Datas.admin:
                try:
                    await bot.setup_auto_start_job(int(bot.Datas.admin), start_hour, start_minute)
                except Exception as e:
                    print(f"⚠️ خطا در auto_start ادمین پیش‌فرض: {e}")
    except Exception as e:
        print(f"⚠️ خطا در bootstrap scheduler: {e}")


async def main():
    print("==================================================")
    print("🚀 Web Worker started (independent from Telegram)")
    print("==================================================")

    # تضمین ایجاد جدول صف فرمان‌ها
    bot.curd.cTable_web_commands()
    # ردیف‌های processing مانده از کرش/توقف قبلی باعث می‌شد پنل همیشه «در حال شروع» بماند
    bot.curd.reset_abandoned_processing_web_commands()

    await bootstrap_scheduler()

    parent_raw = (os.environ.get("PROBOT_PARENT_PID") or "").strip()
    parent_pid = int(parent_raw) if parent_raw.isdigit() else 0
    while True:
        # [vinor] اگر پروسهٔ ربات (والد) مرده، worker هم خارج شود تا یتیم نماند.
        if parent_pid and not _pid_alive(parent_pid):
            print("ℹ️ پروسهٔ ربات متوقف شده؛ worker خارج می‌شود.")
            return
        try:
            await process_pending_commands()
        except Exception as e:
            print(f"❌ خطا در حلقه worker: {e}")
        await asyncio.sleep(3)


def serve():
    import signal

    def _on_term(signum, frame):
        raise SystemExit(0)

    try:
        signal.signal(signal.SIGTERM, _on_term)
    except Exception:
        pass
    if not _acquire_worker_lock():
        raise SystemExit(0)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("⚠️ Worker stopped by user.")
    finally:
        _release_worker_lock()


if __name__ == "__main__":
    serve()
