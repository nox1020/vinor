# -*- coding: utf-8 -*-
"""مهاجرت تصاویر آپلودشده قبلی — فشرده‌سازی + واریانت نمایش."""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from flask import Flask, current_app

from .images import (
    ALLOWED_IMAGE_EXTS,
    process_image_file_on_disk,
)
from .storage import (
    _load,
    _save,
    data_dir,
    ensure_file,
    legacy_dir,
    load_ads,
    load_express_partners,
    load_users,
    save_ads,
    save_express_partners,
    save_users,
)

_IMAGE_EXT_WITH_DOT = tuple(f".{e}" for e in ALLOWED_IMAGE_EXTS) + (".bmp",)
_SKIP_DIR_NAMES = frozenset({"__variants__", ".processed", "apk"})


def _state_path(app=None) -> str:
    return ensure_file(
        "UPLOAD_IMAGE_MIGRATION_STATE_FILE",
        "upload_image_migration.json",
        {},
        app,
    )


def _load_state(app=None) -> Dict[str, Any]:
    data = _load(_state_path(app))
    return data if isinstance(data, dict) else {}


def _save_state(state: Dict[str, Any], app=None) -> None:
    _save(_state_path(app), state)


def _file_state_key(upload_root: str, rel_path: str) -> str:
    return f"{upload_root}|{rel_path}"


def _stored_path(rel_path: str) -> str:
    rel = rel_path.replace("\\", "/").lstrip("/")
    if rel.startswith("uploads/"):
        return rel
    return f"uploads/{rel}"


def collect_upload_roots(app=None) -> List[str]:
    from flask import current_app as ca

    app = app or ca
    roots: List[str] = []
    seen: Set[str] = set()

    def _add(path: Optional[str]) -> None:
        if not path:
            return
        ab = os.path.abspath(path)
        if os.path.isdir(ab) and ab not in seen:
            seen.add(ab)
            roots.append(ab)

    _add(app.config.get("UPLOAD_FOLDER"))
    _add(os.path.join(data_dir(app), "uploads"))
    _add(os.path.join(legacy_dir(app), "uploads"))
    try:
        _add(os.path.join(app.static_folder, "uploads"))
    except Exception:
        pass

    return roots


def iter_upload_image_files(upload_root: str):
    for dirpath, dirnames, filenames in os.walk(upload_root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIR_NAMES]
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext not in _IMAGE_EXT_WITH_DOT:
                continue
            abs_path = os.path.join(dirpath, fn)
            rel = os.path.relpath(abs_path, upload_root).replace("\\", "/")
            yield upload_root, rel


def _is_processed(state: Dict[str, Any], upload_root: str, rel_path: str) -> bool:
    abs_path = os.path.join(upload_root, rel_path)
    if not os.path.isfile(abs_path):
        return True
    try:
        mtime = int(os.path.getmtime(abs_path))
    except Exception:
        mtime = 0
    key = _file_state_key(upload_root, rel_path)
    files = state.get("files") if isinstance(state.get("files"), dict) else {}
    entry = files.get(key)
    if not isinstance(entry, dict):
        return False
    return entry.get("mtime") == mtime and entry.get("variants") is True


def _mark_processed(state: Dict[str, Any], upload_root: str, rel_path: str) -> None:
    abs_path = os.path.join(upload_root, rel_path)
    if not os.path.isfile(abs_path):
        return
    try:
        mtime = int(os.path.getmtime(abs_path))
    except Exception:
        mtime = 0
    files = state.setdefault("files", {})
    if not isinstance(files, dict):
        files = {}
        state["files"] = files
    files[_file_state_key(upload_root, rel_path)] = {
        "mtime": mtime,
        "variants": True,
        "processed_at": datetime.utcnow().isoformat() + "Z",
    }


def _try_rename_value(value: str, renames: Dict[str, str]) -> str:
    if not value or not renames:
        return value
    s = str(value).strip()
    if s in renames:
        return renames[s]
    if s.startswith("/uploads/"):
        alt = s[1:]
        if alt in renames:
            new = renames[alt]
            return new if new.startswith("/") else f"/{new.lstrip('/')}"
    for old, new in renames.items():
        old_tail = old.split("uploads/", 1)[-1] if "uploads/" in old else old
        new_tail = new.split("uploads/", 1)[-1] if "uploads/" in new else new
        if s == f"/uploads/{old_tail}":
            return f"/uploads/{new_tail}"
        if s == old_tail:
            return new_tail
    return value


def _patch_strings_in_obj(obj: Any, renames: Dict[str, str]) -> int:
    changed = 0
    if isinstance(obj, list):
        for i, item in enumerate(obj):
            if isinstance(item, str):
                new_v = _try_rename_value(item, renames)
                if new_v != item:
                    obj[i] = new_v
                    changed += 1
            elif isinstance(item, (list, dict)):
                changed += _patch_strings_in_obj(item, renames)
    elif isinstance(obj, dict):
        for key, val in obj.items():
            if isinstance(val, str):
                new_v = _try_rename_value(val, renames)
                if new_v != val:
                    obj[key] = new_v
                    changed += 1
            elif isinstance(val, (list, dict)):
                changed += _patch_strings_in_obj(val, renames)
    return changed


def apply_upload_path_renames(renames: Dict[str, str], app=None) -> int:
    if not renames:
        return 0
    total = 0

    ads = load_ads(app) or []
    if isinstance(ads, list):
        total += _patch_strings_in_obj(ads, renames)
        save_ads(ads, app)

    partners = load_express_partners(app) or []
    if isinstance(partners, list):
        total += _patch_strings_in_obj(partners, renames)
        save_express_partners(partners, app)

    users = load_users(app) or []
    if isinstance(users, list):
        total += _patch_strings_in_obj(users, renames)
        save_users(users, app)

    return total


def migrate_all_upload_images(
    *,
    dry_run: bool = False,
    force: bool = False,
    limit: Optional[int] = None,
    app=None,
) -> Dict[str, Any]:
    """پردازش همه تصاویر موجود در پوشه‌های uploads."""
    from flask import current_app as ca

    app = app or ca
    state = _load_state(app)
    stats = {
        "roots": 0,
        "scanned": 0,
        "processed": 0,
        "skipped": 0,
        "failed": 0,
        "refs_updated": 0,
        "renames": 0,
        "dry_run": dry_run,
    }
    renames: Dict[str, str] = {}
    roots = collect_upload_roots(app)
    stats["roots"] = len(roots)

    for upload_root in roots:
        for upload_root, rel_path in iter_upload_image_files(upload_root):
            stats["scanned"] += 1
            if limit is not None and stats["processed"] >= limit:
                break

            if not force and _is_processed(state, upload_root, rel_path):
                stats["skipped"] += 1
                continue

            old_stored = _stored_path(rel_path)

            if dry_run:
                stats["processed"] += 1
                current_app.logger.info(
                    "Upload image migration dry-run: %s/%s",
                    upload_root,
                    rel_path,
                )
                continue

            try:
                new_stored = process_image_file_on_disk(upload_root, rel_path)
            except Exception:
                current_app.logger.exception(
                    "Upload image migration failed: %s/%s", upload_root, rel_path
                )
                stats["failed"] += 1
                continue

            if not new_stored:
                stats["failed"] += 1
                continue

            new_rel = new_stored.replace("uploads/", "", 1)
            if new_stored != old_stored:
                renames[old_stored] = new_stored
                renames[f"/{old_stored}"] = f"/{new_stored}"
                stats["renames"] += 1
                rel_path = new_rel

            _mark_processed(state, upload_root, rel_path)
            stats["processed"] += 1

            if not dry_run and stats["processed"] % 3 == 0:
                if renames:
                    stats["refs_updated"] += apply_upload_path_renames(renames, app)
                    renames.clear()
                _save_state(state, app)

        if limit is not None and stats["processed"] >= limit:
            break

    if renames and not dry_run:
        stats["refs_updated"] += apply_upload_path_renames(renames, app)

    if not dry_run:
        state["last_run_at"] = datetime.utcnow().isoformat() + "Z"
        state["last_stats"] = {k: v for k, v in stats.items() if k != "dry_run"}
        _save_state(state, app)

    try:
        current_app.logger.info("Upload image migration finished: %s", stats)
    except Exception:
        pass

    return stats


def _try_acquire_migration_lock(app) -> Optional[int]:
    if os.name != "posix":
        return -1
    try:
        import fcntl

        lock_path = os.path.join(data_dir(app), "upload_image_migration.lock")
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except Exception:
        return None


def _release_migration_lock(fd: Optional[int]) -> None:
    if fd is None or fd < 0:
        return
    try:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    except Exception:
        pass


def maybe_migrate_upload_images(
    *,
    force: bool = False,
    dry_run: bool = False,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    lock_fd = _try_acquire_migration_lock(current_app)
    if lock_fd is None:
        return {"skipped": True, "reason": "another_worker_running"}
    try:
        return migrate_all_upload_images(force=force, dry_run=dry_run, limit=limit)
    finally:
        _release_migration_lock(lock_fd)


def has_pending_upload_image_migration(app=None) -> bool:
    """آیا تصویری هست که هنوز migrate نشده؟"""
    from flask import current_app as ca

    app = app or ca
    state = _load_state(app)
    for upload_root in collect_upload_roots(app):
        for _, rel in iter_upload_image_files(upload_root):
            if not _is_processed(state, upload_root, rel):
                return True
    return False


_STARTUP_DELAY_SEC = 30
_AUTO_BATCH_SIZE = 15
_AUTO_MAX_ROUNDS = 300


def _migration_loop(app: Flask) -> None:
    time.sleep(_STARTUP_DELAY_SEC)
    with app.app_context():
        if not has_pending_upload_image_migration(app):
            app.logger.info("Upload image migration auto-run skipped (nothing pending)")
            return
    app.logger.info("Upload image migration auto-run started")
    rounds = 0
    idle_rounds = 0

    while rounds < _AUTO_MAX_ROUNDS and idle_rounds < 2:
        rounds += 1
        try:
            with app.app_context():
                result = maybe_migrate_upload_images(limit=_AUTO_BATCH_SIZE)
        except Exception:
            app.logger.exception("Upload image migration auto-run batch failed")
            break

        if result.get("skipped") and result.get("reason") == "another_worker_running":
            time.sleep(15)
            continue

        if result.get("skipped"):
            break

        processed = int(result.get("processed") or 0)
        if processed == 0:
            idle_rounds += 1
        else:
            idle_rounds = 0
            app.logger.info("Upload image migration auto-run batch: %s", result)

        time.sleep(2 if processed >= _AUTO_BATCH_SIZE else 1)

    app.logger.info("Upload image migration auto-run finished (rounds=%s)", rounds)


def schedule_upload_image_migration(app: Flask) -> None:
    if os.environ.get("VINOR_DISABLE_UPLOAD_IMAGE_MIGRATION", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        app.logger.info(
            "Upload image migration auto-run disabled (VINOR_DISABLE_UPLOAD_IMAGE_MIGRATION)"
        )
        return
    try:
        with app.app_context():
            if not has_pending_upload_image_migration(app):
                app.logger.info("Upload image migration skipped at boot (nothing pending)")
                return
    except Exception:
        pass
    threading.Thread(
        target=_migration_loop,
        args=(app,),
        daemon=True,
        name="vinor-upload-image-migration",
    ).start()
    app.logger.info(
        "Upload image migration auto-run enabled (~%ss after boot if pending, batch=%s)",
        _STARTUP_DELAY_SEC,
        _AUTO_BATCH_SIZE,
    )
