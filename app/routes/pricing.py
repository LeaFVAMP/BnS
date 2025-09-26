# app/routes/pricing.py
from __future__ import annotations
from decimal import Decimal
import json
import csv
from io import TextIOWrapper

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
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

# Orden canónico de tipos para el selector
TIPOS_CANON = ("aereo", "maritimo", "terrestre")


# ---------- Helpers ----------
def _siblings_for_pills(sol: Solicitud) -> dict[str, int]:
    """
    Devuelve {'aereo': id, 'maritimo': id, 'terrestre': id} para las hijas del mismo folio.
    Si la solicitud no tiene folio, retorna solo su propio tipo -> id.
    """
    out: dict[str, int] = {}

    # tipo de la solicitud actual
    cur_srv = sol.servicios.first()
    if cur_srv:
        out[cur_srv.tipo_servicio.value] = sol.id

    # Si no hay folio no hay hermanas
    if not sol.folio_id:
        return out

    # Junta todas las solicitudes del mismo folio y mapea por tipo
    hermanas = (
        Solicitud.query
        .join(SolicitudServicio, SolicitudServicio.solicitud_id == Solicitud.id)
        .filter(Solicitud.folio_id == sol.folio_id)
        .all()
    )
    for h in hermanas:
        srv = h.servicios.first()
        if srv:
            out[srv.tipo_servicio.value] = h.id

    return out


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
    recientes = Solicitud.query.order_by(Solicitud.id.desc()).limit(20).all()
    conteos = dict(
        pendientes=db.session.query(func.count()).select_from(Solicitud)
        .filter(Solicitud.estatus == "pendiente").scalar(),
        en_cotizacion=db.session.query(func.count()).select_from(Solicitud)
        .filter(Solicitud.estatus == "en cotizacion").scalar(),
        cerradas=db.session.query(func.count()).select_from(Solicitud)
        .filter(Solicitud.estatus == "cerrada").scalar(),
    )
    return render_template("Pricing/panel.html", recientes=recientes, conteos=conteos)


@bp.route("/pendientes")
@login_required
def pendientes():
    q = (Solicitud.query
         .filter(Solicitud.estatus.in_(["pendiente", "en cotizacion"]))
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

    s = db.session.get(Solicitud, sol_id)
    if not s:
        abort(404)

    # mapa para píldoras (aereo/maritimo/terrestre)
    siblings = _siblings_for_pills(s)

    opcion = db.session.get(CotizacionOpcion, op_id) if op_id else None
    if op_id and (not opcion or opcion.solicitud_id != sol_id):
        abort(404)

    is_lcl = _is_lcl(s, tipo)
    cbm_prefill = _cbm_prefill(s)

    # --- Selector de las 3 solicitudes del mismo folio para tabs visuales ---
    selector_tres = []
    if s.folio_id:
        try:
            folio_sols = s.folio.solicitudes.order_by(Solicitud.id.asc()).all()
        except Exception:
            folio_sols = Solicitud.query.filter_by(folio_id=s.folio_id).all()

        by_tipo = {}
        for sx in folio_sols:
            t = (_tipo_servicio_referencial(sx) or "").lower()
            if t in TIPOS_CANON:
                by_tipo[t] = sx

        for t in TIPOS_CANON:
            sx = by_tipo.get(t)
            selector_tres.append(dict(
                tipo=t,
                exists=bool(sx),
                sol_id=(sx.id if sx else None),
                is_current=bool(sx and sx.id == s.id),
                etiqueta=t.capitalize(),
            ))
    else:
        selector_tres.append(dict(tipo=tipo, exists=True, sol_id=s.id, is_current=True, etiqueta=tipo.capitalize()))

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
        # Estos dos campos quedan como opcionales/auxiliares (sin validación obligatoria)
        proveedor = (request.form.get("proveedor") or "").strip()
        moneda = (request.form.get("moneda") or "MXN").strip().upper()

        # Campos adicionales
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

        if opcion is None:
            opcion = CotizacionOpcion(
                solicitud_id=s.id,
                tipo_servicio=tipo,
            )
            db.session.add(opcion)

        # Asignaciones a la opción
        opcion.proveedor = proveedor
        opcion.moneda = moneda
        try:
            opcion.cbm_cotizado = float(cbm_cotizado) if cbm_cotizado not in (None, "",) else None
        except Exception:
            opcion.cbm_cotizado = None
        opcion.origen_final = origen_final
        opcion.destino_final = destino_final
        opcion.frecuencia = frecuencia
        opcion.transito_estimado_dias = int(tt_dias) if (tt_dias and tt_dias.isdigit()) else None
        opcion.dias_libres_destino = int(dias_libres) if (dias_libres and dias_libres.isdigit()) else None
        opcion.terminos_condiciones = terminos

        # Limpia items previos si estás editando
        if opcion.id:
            # relación lazy="dynamic": borra en bloque
            opcion.items.delete(synchronize_session=False)

        # Regla LCL server-side (CBM en (0,1) => 1) cuando la unidad es CBM
        def norm_cant(unidad: str | None, cant: float) -> float:
            if is_lcl and (unidad or "").upper() == "CBM" and 0 < cant < 1:
                return 1.0
            return cant

        # Inserta ítems
        for it in items_data:
            try:
                cantidad = float(it.get("cantidad") or 0)
            except Exception:
                cantidad = 0.0
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
                iva_pct=Decimal(str(it.get("iva_pct") or 0)),       # 0–1
                ret_iva_pct=Decimal(str(it.get("ret_iva_pct") or 0)),# 0–1
                isr_pct=Decimal(str(it.get("isr_pct") or 0)),       # 0–1
            )
            db.session.add(item)

        if s.estatus == "pendiente":
            s.estatus = "en cotizacion"

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
        moneda_default=(opcion.moneda if (opcion and opcion.moneda) else "MXN"),
        siblings=siblings,
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


# --- Importar catálogo de conceptos desde CSV ---
def _norm_rate(x):
    """
    Acepta 16, 0.16, '16%', '0.16', '' -> devuelve Decimal en 0–1.
    """
    if x is None:
        return Decimal("0")
    s = str(x).strip().replace("%", "").replace(",", ".")
    if s == "":
        return Decimal("0")
    try:
        val = Decimal(s)
    except Exception:
        return Decimal("0")
    # si viene como 16 => 0.16 ; si ya es 0.16 => queda igual
    return (val / Decimal("100")) if val > 1 else val


def _require_admin_or_pricing():
    rol = (getattr(current_user, "rol", "") or "").lower()
    if rol not in ("admin", "pricing"):
        abort(403)


@bp.route("/conceptos/importar", methods=["GET", "POST"])
@login_required
def importar_conceptos():
    _require_admin_or_pricing()

    if request.method == "POST":
        f = request.files.get("file")
        if not f or f.filename == "":
            flash("Sube un archivo CSV.", "warning")
            return redirect(request.url)

        # CSV UTF-8 con encabezados:
        # clave,descripcion,moneda,unidad,iva_pct,ret_iva_pct,isr_pct
        reader = csv.DictReader(TextIOWrapper(f.stream, encoding="utf-8"))
        inserted, updated, errors = 0, 0, 0

        for i, row in enumerate(reader, start=2):  # 2 por el header
            try:
                clave = (row.get("clave") or "").strip()
                if not clave:
                    errors += 1
                    continue

                c = Concepto.query.filter_by(clave=clave).first()
                payload = dict(
                    descripcion=(row.get("descripcion") or "").strip(),
                    moneda=(row.get("moneda") or "MXN").strip().upper()[:3] or "MXN",
                    unidad=((row.get("unidad") or "").strip() or None),
                    iva_pct=_norm_rate(row.get("iva_pct")),
                    ret_iva_pct=_norm_rate(row.get("ret_iva_pct")),
                    isr_pct=_norm_rate(row.get("isr_pct")),
                )

                if c:
                    c.descripcion = payload["descripcion"]
                    c.moneda = payload["moneda"]
                    c.unidad = payload["unidad"]
                    c.iva_pct = payload["iva_pct"]
                    c.ret_iva_pct = payload["ret_iva_pct"]
                    c.isr_pct = payload["isr_pct"]
                    updated += 1
                else:
                    c = Concepto(clave=clave, **payload)
                    db.session.add(c)
                    inserted += 1
            except Exception:
                errors += 1

        db.session.commit()
        flash(
            f"Catálogo procesado. Insertados: {inserted}, Actualizados: {updated}, Errores: {errors}.",
            "success",
        )
        # al terminar, el cotizador ya verá el catálogo actualizado automáticamente
        return redirect(url_for("ventas.listar_solicitudes"))

    return render_template("Pricing/importar_conceptos.html")
