from functools import wraps
from flask import redirect, url_for, request, flash
from flask_login import current_user

def role_required(*roles):
    """
    Permite acceso si current_user.rol está en roles o si es admin.
    Uso: @role_required("ventas")  o  @role_required("pricing","ventas")
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("auth.login", next=request.full_path))
            if current_user.rol == "admin" or current_user.rol in roles:
                return fn(*args, **kwargs)
            flash("No tienes permisos para acceder a esta sección.", "warning")
            return redirect(url_for("auth.index"))
        return wrapper
    return decorator
