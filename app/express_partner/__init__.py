from flask import Blueprint

# Blueprint پنل همکار — قالب‌ها از همین بسته خوانده می‌شوند
express_partner_bp = Blueprint(
    'express_partner', __name__,
    url_prefix='/express/partner',
    template_folder='templates'
)

from . import routes  # noqa: F401
from . import consultant_ui  # noqa: F401


