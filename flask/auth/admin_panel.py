from flask import redirect, url_for, request, flash
from flask_admin.contrib.sqla import ModelView
from flask_admin import AdminIndexView
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
from flask_jwt_extended.exceptions import JWTExtendedException
import logging

from auth.models import Organizer

logger = logging.getLogger(__name__)

class SecureModelView(ModelView):
    """
    A custom ModelView for Flask-Admin that checks for a valid JWT token
    and ensures the authenticated Organizer has the is_admin flag set to True.
    """
    def is_accessible(self):
        try:
            verify_jwt_in_request(locations=["cookies"])
            email = get_jwt_identity()
            if email:
                user = Organizer.query.filter_by(email=email).first()
                if user and user.is_admin:
                    return True
        except Exception as e:
            pass
            
        return False

    def on_model_delete(self, model):
        flash(f"user {model.email} is deleted", "success")

    def inaccessible_callback(self, name, **kwargs):
        # Redirect to login page if user doesn't have access
        logger.warning(f"Unauthorized access attempt to admin panel by {get_jwt_identity()}")
        return redirect(url_for('auth.login_page', next=request.url))


class SecureAdminIndexView(AdminIndexView):
    """ Protects the /admin/ root dashboard """
    def is_accessible(self):
        try:
            verify_jwt_in_request(locations=["cookies"])
            email = get_jwt_identity()
            if email:
                user = Organizer.query.filter_by(email=email).first()
                if user and user.is_admin:
                    return True
        except Exception:
            pass
        return False

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for('auth.login_page', next=request.url))
