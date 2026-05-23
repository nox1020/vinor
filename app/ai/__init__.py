from flask import Blueprint

ai_bp = Blueprint(
    "ai",
    __name__,
    url_prefix="/ai",
    template_folder="templates",
    static_folder="static",
    static_url_path="/static",
)

from . import routes  # noqa: F401
