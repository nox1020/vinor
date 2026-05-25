# run.py
import os, logging
import sys
from logging.handlers import RotatingFileHandler
from flask import send_from_directory, request, jsonify
from app import create_app

app = create_app()

class SafeRotatingFileHandler(RotatingFileHandler):
    """
    RotatingFileHandler با exception handling برای Windows
    برای جلوگیری از PermissionError هنگام rotate فایل
    """
    def rotate(self, source, dest):
        """
        Override rotate برای استفاده از shutil.move به جای os.rename
        این متد در Windows بهتر کار می‌کند
        """
        import shutil
        try:
            if os.path.exists(source):
                if os.path.exists(dest):
                    try:
                        os.remove(dest)
                    except (OSError, PermissionError):
                        pass
                try:
                    shutil.move(source, dest)
                except (OSError, PermissionError):
                    # اگر فایل lock شده، skip می‌کنیم
                    pass
        except Exception:
            # اگر هر خطایی رخ داد، فقط ادامه می‌دهیم
            pass
    
    def doRollover(self):
        """
        Override doRollover برای handle کردن PermissionError در Windows
        """
        if self.stream:
            self.stream.close()
            self.stream = None
        
        try:
            # استفاده از shutil.move به جای os.rename برای Windows
            import shutil
            if self.backupCount > 0:
                for i in range(self.backupCount - 1, 0, -1):
                    sfn = "%s.%d" % (self.baseFilename, i)
                    dfn = "%s.%d" % (self.baseFilename, i + 1)
                    if os.path.exists(sfn):
                        if os.path.exists(dfn):
                            try:
                                os.remove(dfn)
                            except (OSError, PermissionError):
                                pass
                        try:
                            shutil.move(sfn, dfn)
                        except (OSError, PermissionError):
                            # اگر فایل lock شده، skip می‌کنیم
                            pass
                
                dfn = self.baseFilename + ".1"
                if os.path.exists(dfn):
                    try:
                        os.remove(dfn)
                    except (OSError, PermissionError):
                        pass
                try:
                    if os.path.exists(self.baseFilename):
                        shutil.move(self.baseFilename, dfn)
                except (OSError, PermissionError):
                    # اگر فایل lock شده، فقط ادامه می‌دهیم بدون rotate
                    pass
        except Exception:
            # اگر هر خطایی رخ داد، فقط ادامه می‌دهیم
            pass
        finally:
            # همیشه stream را باز می‌کنیم
            if self.stream is None and not self.delay:
                self.stream = self._open()

def _setup_logging(flask_app):
    try:
        logs_dir = os.path.join(flask_app.instance_path, "logs")
        os.makedirs(logs_dir, exist_ok=True)
        
        # حذف تمام handlerهای قبلی از نوع RotatingFileHandler
        flask_app.logger.handlers = [
            h for h in flask_app.logger.handlers 
            if not isinstance(h, (RotatingFileHandler, SafeRotatingFileHandler))
        ]
        
        # استفاده از SafeRotatingFileHandler به جای RotatingFileHandler
        # delay=True: فایل را تا زمانی که نیاز نباشد باز نمی‌کند
        log_file = os.path.join(logs_dir, "app.log")
        fh = SafeRotatingFileHandler(
            log_file, 
            maxBytes=2*1024*1024,  # 2MB
            backupCount=5, 
            encoding="utf-8",
            delay=True  # فایل را تا اولین log باز نمی‌کند
        )
        fh.setLevel(logging.INFO)
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        
        flask_app.logger.setLevel(logging.INFO)
        flask_app.logger.addHandler(fh)
    except Exception as e:
        # اگر logging setup با خطا مواجه شد، فقط print می‌کنیم
        # تا برنامه crash نکند
        print(f"Log setup error: {e}", file=sys.stderr)

_setup_logging(app)

@app.route("/favicon.ico")
def _favicon():
    static_dir = os.path.join(app.root_path, "static")
    path = os.path.join(static_dir, "favicon.ico")
    if os.path.exists(path):
        return send_from_directory(static_dir, "favicon.ico")
    return ("", 204)

@app.errorhandler(404)
def _nf(e):
    if request.path.startswith("/static/"): 
        return ("", 404)
    return jsonify({"error":"Not Found","path":request.path}), 404

if __name__ == "__main__":
    # با bootstrap آفلاین، reloader دانلود/pip را قطع می‌کند — پیش‌فرض reloader خاموش
    auto_boot = os.environ.get("VINOR_AI_AUTO_BOOTSTRAP", "1").lower() not in (
        "0", "false", "no",
    )
    use_reloader = os.environ.get(
        "FLASK_USE_RELOADER",
        "0" if auto_boot else "1",
    ).lower() in ("1", "true", "yes")
    app.run(
        debug=True,
        use_reloader=use_reloader,
        host=os.environ.get("FLASK_RUN_HOST", "0.0.0.0"),
        port=int(os.environ.get("FLASK_RUN_PORT", "5000")),
    )
