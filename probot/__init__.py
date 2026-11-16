"""1probot — ربات نردبان دیوار روی بله، ادغام‌شده در بک‌اند وینور.

import این پکیج هیچ اثر جانبی ندارد. پنل وب: probot.web_app.bp (زیر /probot).
پروسهٔ ربات: python -m probot.run (راهنما: probot/README.md).
"""


def register_probot(app):
    """Blueprint پنل را روی اپ وینور ثبت می‌کند. اگر وابستگی‌ها نصب نباشد خطا را بالا می‌دهد
    تا create_app آن را فقط لاگ کند (وینور هرگز به‌خاطر ربات نمی‌خوابد)."""
    from .web_app import bp

    app.register_blueprint(bp)

    @app.before_request
    def _probot_autostart_tick():
        try:
            from .runner import maybe_autostart

            maybe_autostart()
        except Exception:
            pass
        return None

    return bp
