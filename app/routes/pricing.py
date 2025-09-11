# app/routes/pricing.py
from __future__ import annotations
from decimal import Decimal
import json

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required
from sqlalchemy import func

from app import db
from app.models import (
    Solicitud,
    SolicitudServicio,
    Concepto,
    CotizacionOpcion,
    CotizacionItem,
    TipoServicio,
    Modalidad,
)

bp = Blueprint("pricing", __name__)  # el url_prefix lo añade create_app al registrar


# ---------- Helpers ----------
def _is_lcl(sol: Solicitud, tipo: str) -> bool:
    # tipo viene en minúsculas: 'aereo' | 'maritimo' | 'terrestre'
    svc = (
        SolicitudServicio.query
        .filter_by(solicitud_id=sol.id)
        .filter(SolicitudServicio.tipo_servicio == TipoServicio(tipo))
        .first()
    )
    return bool(svc and svc.modalidad == Modalidad.LCL)


def _cbm_prefill(sol: Solicitud) -> float | None:
    return sol.cbm_totales or sol.volumen_cbm or None


def _tipo_servicio_referencial(s: Solicitud) -> str:
    first = s.servicios.order_by(SolicitudServicio.id.asc()).first()
    return first.tipo_servicio.value if first else "maritimo"


# ---------- Rutas de navegación de Pricing (navbar) ----------
@bp.route("/panel")
@login_required
def panel():
    # Muestra algo simple para arrancar el panel (ajusta tu template como gustes)
    recientes = Solicitud.query.order_by(Solicitud.id.desc()).limit(20).all()
    conteos = dict(
        pendientes=db.session.query(func.count()).select_from(Solicitud).filter(Solicitud.estatus == "pendiente").scalar(),
        en_cotizacion=db.session.query(func.count()).select_from(Solicitud).filter(Solicitud.estatus == "en_cotizacion").scalar(),
        cerradas=db.session.query(func.count()).select_from(Solicitud).filter(Solicitud.estatus == "cerrada").scalar(),
    )
    return render_template("Pricing/panel.html", recientes=recientes, conteos=conteos)


@bp.route("/pendientes")
@login_required
def pendientes():
    # Lista solicitudes pendientes/en_cotizacion
    q = (Solicitud.query
         .filter(Solicitud.estatus.in_(["pendiente", "en_cotizacion"]))
         .order_by(Solicitud.id.desc()))
    solicitudes = q.limit(200).all()
    return render_template("Pricing/pendientes.html", solicitudes=solicitudes)


# ---------- Cotizar ----------
@bp.route("/cotizar/<int:sol_id>/<string:tipo>", methods=["GET", "POST"])
@bp.route("/cotizar/<int:sol_id>/<string:tipo>/opcion/<int:op_id>", methods=["GET", "POST"])
@login_required
def cotizar(sol_id: int, tipo: str, op_id: int | None = None):
    tipo = tipo.lower().strip()
    if tipo not in ("aereo", "maritimo", "terrestre"):
        abort(404)

    s = Solicitud.query.get_or_404(sol_id)
    opcion = CotizacionOpcion.query.get(op_id) if op_id else None
    if op_id and (not opcion or opcion.solicitud_id != sol_id):
        abort(404)

    is_lcl = _is_lcl(s, tipo)
    cbm_prefill = _cbm_prefill(s)

    # Catálogo para el <script type="application/json" id="catalogo-json">
    conceptos = Concepto.query.order_by(Concepto.clave).all()
    conceptos_json = [
        dict(
            id=c.id, clave=c.clave, descripcion=c.descripcion,
            moneda=c.moneda, unidad=(c.unidad or ""),
            iva_pct=float(c.iva_pct or 0),
            ret_iva_pct=float(c.ret_iva_pct or 0),
            isr_pct=float(c.isr_pct or 0),
        )
        for c in conceptos
    ]

    # Ítems existentes (si editas)
    items = []
    if opcion:
        for it in opcion.items.order_by(CotizacionItem.id):
            items.append(dict(
                concepto_id=it.concepto_id,
                concepto_nombre=it.concepto_nombre,
                proveedor=it.proveedor or "",
                moneda=it.moneda,
                unidad=it.unidad or "",
                cantidad=float(it.cantidad or 0),
                precio_unit=float(it.precio_unit or 0),
                iva_pct=float(it.iva_pct or 0),
                ret_iva_pct=float(it.ret_iva_pct or 0),
                isr_pct=float(it.isr_pct or 0),
            ))

    if request.method == "POST":
        proveedor = request.form.get("proveedor", "").strip()
        moneda = (request.form.get("moneda") or "MXN").strip().upper()
        cbm_cotizado = request.form.get("cbm_cotizado")
        origen_final = request.form.get("origen_final") or None
        destino_final = request.form.get("destino_final") or None
        frecuencia = request.form.get("frecuencia") or None
        tt_dias = request.form.get("transito_estimado_dias") or None
        dias_libres = request.form.get("dias_libres_destino") or None
        terminos = request.form.get("terminos_condiciones") or None
        items_json = request.form.get("items_json") or "[]"

        try:
            items_data = json.loads(items_json)
            assert isinstance(items_data, list)
        except Exception:
            flash("Formato de items inválido.", "danger")
            return redirect(request.url)

        if not proveedor:
            flash("Proveedor (global) es requerido.", "warning")
            return redirect(request.url)

        if opcion is None:
            opcion = CotizacionOpcion(
                solicitud_id=s.id,
                tipo_servicio=tipo,
            )
            db.session.add(opcion)

        opcion.proveedor = proveedor
        opcion.moneda = moneda
        opcion.cbm_cotizado = float(cbm_cotizado) if cbm_cotizado not in (None, "",) else None
        opcion.origen_final = origen_final
        opcion.destino_final = destino_final
        opcion.frecuencia = frecuencia
        opcion.transito_estimado_dias = int(tt_dias) if tt_dias else None
        opcion.dias_libres_destino = int(dias_libres) if dias_libres else None
        opcion.terminos_condiciones = terminos

        # Limpia items previos si estás editando
        if opcion.id:
            opcion.items.delete()  # por cascade delete-orphan

        # Regla LCL server-side (CBM en (0,1) => 1) cuando la unidad es CBM
        def norm_cant(unidad: str | None, cant: float) -> float:
            if is_lcl and (unidad or "").upper() == "CBM" and 0 < cant < 1:
                return 1.0
            return cant

        # Inserta ítems
        for it in items_data:
            cantidad = float(it.get("cantidad") or 0)
            unidad = (it.get("unidad") or "").upper()
            item = CotizacionItem(
                opcion=opcion,
                concepto_id=it.get("concepto_id"),
                concepto_nombre=(it.get("concepto_nombre") or "").strip() or None,
                proveedor=(it.get("proveedor") or "").strip() or None,
                moneda=(it.get("moneda") or moneda).upper(),
                unidad=unidad or None,
                cantidad=Decimal(str(norm_cant(unidad, cantidad))),
                precio_unit=Decimal(str(it.get("precio_unit") or 0)),
                iva_pct=Decimal(str(it.get("iva_pct") or 0)),
                ret_iva_pct=Decimal(str(it.get("ret_iva_pct") or 0)),
                isr_pct=Decimal(str(it.get("isr_pct") or 0)),
            )
            db.session.add(item)

        if s.estatus == "pendiente":
            s.estatus = "en_cotizacion"

        db.session.commit()
        flash("Opción guardada.", "success")
        return redirect(url_for("pricing.solicitud", sol_id=s.id))

    # GET
    return render_template(
        "Pricing/cotizar.html",
        s=s,
        opcion=opcion,
        tipo=tipo,
        has_lcl=is_lcl,
        is_lcl=is_lcl,
        cbm_prefill=cbm_prefill,
        conceptos=conceptos_json,
        items=items,
        moneda_default=opcion.moneda if opcion else "MXN",
    )


@bp.route("/solicitud/<int:sol_id>")
@login_required
def solicitud(sol_id: int):
    s = db.session.get(Solicitud, sol_id)
    if not s:
        abort(404)
    opciones = s.cotizacion_opciones.order_by(CotizacionOpcion.created_at.desc()).all()
    tipo = _tipo_servicio_referencial(s)
    return render_template("Pricing/solicitud.html", s=s, opciones=opciones, tipo=tipo)
