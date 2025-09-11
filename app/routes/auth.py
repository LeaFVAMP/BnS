from __future__ import annotations
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from app import db, bcrypt
from app.models import User

bp = Blueprint("auth", __name__)

def _redirect_by_role(user: User):
    rol = (user.rol or "").lower()
    if rol in ("pricing", "admin"):
        return redirect(url_for("ventas.listar_solicitudes"))
    if rol == "ventas":
        return redirect(url_for("ventas.dashboard"))
    return redirect(url_for("auth.index"))
    

@bp.get("/")
def index():
    if current_user.is_authenticated:
        return _redirect_by_role(current_user)
    return render_template("index.html")

@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = User.query.filter_by(email=email).first()
        if not user:
            flash("Usuario no encontrado.", "danger")
            return render_template("auth/login.html")

        ok = False
        try:
            ok = bcrypt.check_password_hash(user.password, password)
        except Exception:
            ok = False
        if not ok:
            flash("Credenciales incorrectas.", "danger")
            return render_template("auth/login.html")

        login_user(user)
        flash("Bienvenido.", "success")
        return _redirect_by_role(user)

    return render_template("auth/login.html")

@bp.get("/logout")
@login_required
def logout():
    logout_user()
    flash("Sesión cerrada.", "info")
    return redirect(url_for("auth.login"))
