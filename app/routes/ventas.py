from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, Any, Tuple, Optional

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import and_

from app import db
from app.models import (
    Solicitud, SolicitudServicio, TipoServicio,
    Cliente, ClienteTipo, Modalidad
)

bp = Blueprint("ventas", __name__)

# Helpers
def generar_numero_serie() -> str:
    hoy = datetime.utcnow()
    ini = datetime(hoy.year, 1, 1)
    fin = datetime(hoy.year, 12, 31, 23, 59, 59, 999999)
    count = (Solicitud.query
             .filter(and_(Solicitud.fecha_solicitud >= ini,
                          Solicitud.fecha_solicitud <= fin))
             .count())
    return f"Q{count + 1:04d}{hoy.year}"

def _bool_from_radio(val: str | None) -> bool:
    return (val or "").strip().lower() in {"si", "sí", "true", "1", "on", "yes"}

def _to_float_or_none(v: Any) -> Optional[float]:
    if v is None: return None
    s = str(v).strip()
    if s == "": return None
    try: return float(s)
    except ValueError: return None

def _get_serv_detail(prefix: str) -> Dict[str, Any]:
    modalidad = (request.form.get(f"{prefix}_modalidad") or "FCL").upper()
    d = {
        "modalidad": modalidad,
        "tipo_embarque": request.form.get(f"{prefix}_tipo_embarque") or "",
        "incoterm": request.form.get(f"{prefix}_incoterm") or "",
        "un_clase": request.form.get(f"{prefix}_un_clase") or "",
        "estibable": _bool_from_radio(request.form.get(f"{prefix}_estibable")),
        "seguro": _bool_from_radio(request.form.get(f"{prefix}_seguro") or "no"),
        "valor_factura": (request.form.get(f"{prefix}_valor_factura") or "").strip(),
        "tipo_cambio": request.form.get(f"{prefix}_tipo_cambio") or "",
        "origen": {
            "pais": request.form.get(f"{prefix}_origen_pais") or "",
            "ciudad": request.form.get(f"{prefix}_origen_ciudad") or "",
            "cp": request.form.get(f"{prefix}_origen_cp") or "",
            "recoleccion": request.form.get(f"{prefix}_origen_recoleccion") or "",
            "puerto": request.form.get(f"{prefix}_origen_puerto") or "",
            "cruce": request.form.get(f"{prefix}_origen_cruce") or "",
            "despacho": request.form.get(f"{prefix}_origen_despacho") or "",
        },
        "destino": {
            "pais": request.form.get(f"{prefix}_destino_pais") or "",
            "ciudad": request.form.get(f"{prefix}_destino_ciudad") or "",
            "cp": request.form.get(f"{prefix}_destino_cp") or "",
            "entrega": request.form.get(f"{prefix}_destino_entrega") or "",
            "puerto": request.form.get(f"{prefix}_destino_puerto") or "",
            "cruce": request.form.get(f"{prefix}_destino_cruce") or "",
            "despacho": request.form.get(f"{prefix}_destino_despacho") or "",
        },
        "unidad": request.form.get(f"{prefix}_unidad") or "",
        "servicio_unidad": request.form.get(f"{prefix}_servicio_unidad") or "",
        "maniobra": request.form.get(f"{prefix}_maniobra") or "",
    }
    if modalidad == "FCL":
        cont_types = []
        for k, v in request.form.items():
            if k.startswith(f"{prefix}_cont_") and k.endswith("_tipo") and v:
                base = k[:-5]
                cant = (request.form.get(f"{base}_cantidad") or "").strip()
                cont_types.append({"tipo": v, "cantidad": int(cant or "0")})
        if cont_types:
            d["contenedores"] = cont_types
            d["numero_contenedor"] = sum(c["cantidad"] for c in cont_types)
    return d

def _ensure_cliente_for_name(nombre: str) -> Cliente:
    nm = (nombre or "").strip()
    if not nm: raise ValueError("Nombre de cliente vacío.")
    c = Cliente.query.filter(Cliente.nombre.ilike(nm)).first()
    if c: return c
    c = Cliente(nombre=nm, activo=True)
    db.session.add(c); db.session.flush()
    return c

def _resolver_cliente(form):
    tipo_raw = (form.get("cliente_tipo") or "cliente").strip().lower()
    cli_tipo = ClienteTipo.PROSPECTO if tipo_raw == "prospecto" else ClienteTipo.CLIENTE

    cliente_label = (form.get("cliente") or "").strip()
    cliente_id = None
    prospecto_nombre = None

    if cli_tipo == ClienteTipo.CLIENTE:
        cliente_id_str = (form.get("cliente_id") or "").strip()
        if cliente_id_str.isdigit():
            cliente_id = int(cliente_id_str)
            if not cliente_label:
                obj = db.session.get(Cliente, cliente_id)
                cliente_label = (obj.nombre if obj else "").strip()
        else:
            nombre_cli = cliente_label or (form.get("cliente") or "").strip()
            if not nombre_cli:
                return cli_tipo, None, None, ""
            cliente = _ensure_cliente_for_name(nombre_cli)
            cliente_id = cliente.id
            cliente_label = cliente.nombre.strip()
    else:
        prospecto_nombre = (form.get("prospecto_nombre") or "").strip()
        if not prospecto_nombre and not cliente_label:
            return cli_tipo, None, None, ""
        if not cliente_label:
            cliente_label = prospecto_nombre

    return cli_tipo, cliente_id, (prospecto_nombre or None), cliente_label.strip()

# Vistas
@bp.get("/dashboard")
@login_required
def dashboard():
    return render_template("Ventas/dashboard.html")

@bp.get("/solicitudes")
@login_required
def listar_solicitudes():
    solicitudes = (Solicitud.query
                   .order_by(Solicitud.fecha_solicitud.desc())
                   .limit(200).all())
    return render_template("Ventas/historial.html", solicitudes=solicitudes)

@bp.route("/nueva", methods=["GET", "POST"])
@login_required
def crear_solicitud():
    if request.method == "GET":
        clientes = Cliente.query.filter_by(activo=True).order_by(Cliente.nombre.asc()).all()
        return render_template("Ventas/nueva_solicitud.html", clientes=clientes)

    numero_serie = generar_numero_serie()

    cliente_tipo, cliente_id, prospecto_nombre, cliente_label = _resolver_cliente(request.form)
    if not cliente_label:
        flash("Debes seleccionar un cliente o escribir el nombre del prospecto.", "warning")
        return redirect(url_for("ventas.crear_solicitud"))

    servicios_sel = [s for s in request.form.getlist("servicios[]") if s in {"aereo", "maritimo", "terrestre"}]
    if not servicios_sel:
        flash("Selecciona al menos un tipo de servicio.", "warning")
        return redirect(url_for("ventas.crear_solicitud"))

    detalle_por_tipo: Dict[str, Dict[str, Any]] = {s: _get_serv_detail(s) for s in servicios_sel}
    first = servicios_sel[0]; gen = detalle_por_tipo[first]

    solicitud = Solicitud(
        numero_serie=numero_serie,
        usuario_id=current_user.id,
        departamento=request.form.get("departamento") or "C",
        vendedor=request.form.get("vendedor") or "",
        sales_support=(getattr(current_user, "nombre", None) or current_user.email),
        prioridad=request.form.get("prioridad") or "estándar",

        cliente=cliente_label,
        cliente_tipo=cliente_tipo,
        cliente_id=cliente_id,
        prospecto_nombre=prospecto_nombre,

        tipo_embarque=gen.get("tipo_embarque", ""),
        incoterm=gen.get("incoterm", ""),
        un_clase=gen.get("un_clase") or None,
        estibable=bool(gen.get("estibable", False)),
        tipo_cambio=(gen.get("tipo_cambio") or "") or None,
        valor_factura=_to_float_or_none(gen.get("valor_factura")) if gen.get("seguro") else None,
        seguro=bool(gen.get("seguro", False)),

        origen_pais=gen.get("origen", {}).get("pais", ""),
        origen_ciudad=gen.get("origen", {}).get("ciudad", ""),
        origen_cp=gen.get("origen", {}).get("cp", ""),
        origen_recoleccion=gen.get("origen", {}).get("recoleccion") or None,
        origen_puerto=gen.get("origen", {}).get("puerto") or None,
        origen_cruce=gen.get("origen", {}).get("cruce") or None,
        origen_despacho=gen.get("origen", {}).get("despacho") or None,

        destino_pais=gen.get("destino", {}).get("pais", ""),
        destino_ciudad=gen.get("destino", {}).get("ciudad", ""),
        destino_cp=gen.get("destino", {}).get("cp", ""),
        destino_entrega=gen.get("destino", {}).get("entrega") or None,
        destino_puerto=gen.get("destino", {}).get("puerto") or None,
        destino_cruce=gen.get("destino", {}).get("cruce") or None,
        destino_despacho=gen.get("destino", {}).get("despacho") or None,

        unidad=gen.get("unidad", "") or "N/A",
        servicio_unidad=gen.get("servicio_unidad", "") or "sencillo",
        maniobra=gen.get("maniobra", "") or "ninguna",
        numero_contenedor=str(gen.get("numero_contenedor", "") or ""),
        tipo_contenedor=(request.form.get(f"{first}_tipo_contenedor") or "") or None,

        commodity=request.form.get("commodity") or "",
        tipo_carga=request.form.get("tipo_carga") or "",
        peso_unidad=request.form.get("peso_unidad") or "kg",
        longitud_unidad=request.form.get("longitud_unidad") or "cm",
        volumen_cbm=_to_float_or_none(request.form.get("volumen_cbm")) or 0.0,

        cotiza_por=request.form.get("cotiza_por") or "totales",

        no_s=int(request.form.get("no_s") or 0) or None,
        dimensiones_totales=(request.form.get("dimensiones_totales") or "").strip()[:200] or None,
        cbm_totales=_to_float_or_none(request.form.get("cbm_totales")),
        gw_totales=_to_float_or_none(request.form.get("gw_totales")),
        vw_totales=_to_float_or_none(request.form.get("vw_totales")),

        no_dim=int(request.form.get("no_dim") or 0) or None,
        largo_dim=_to_float_or_none(request.form.get("largo_dim")),
        ancho_dim=_to_float_or_none(request.form.get("ancho_dim")),
        alto_dim=_to_float_or_none(request.form.get("alto_dim")),
        peso_dim=_to_float_or_none(request.form.get("peso_dim")),

        totales_json=(request.form.get("totales_json") or None),
        dimensiones_json=(request.form.get("dimensiones_json") or None),

        servicios_solicitados=json.dumps(servicios_sel),
        comentarios=request.form.get("comentarios") or None,
        asunto_email=request.form.get("asunto_email") or None,

        estatus="pendiente",
    )
    db.session.add(solicitud); db.session.flush()

    tipo_map = {
        "aereo": TipoServicio.AEREO,
        "maritimo": TipoServicio.MARITIMO,
        "terrestre": TipoServicio.TERRESTRE
    }
    for s in servicios_sel:
        det = detalle_por_tipo.get(s, {})
        srv = SolicitudServicio(
            solicitud_id=solicitud.id,
            tipo_servicio=tipo_map[s],
            modalidad=(Modalidad(det.get("modalidad")) if det.get("modalidad") in {"FCL","LCL"} else None),
            detalle_json=det
        )
        db.session.add(srv)

    db.session.commit()
    flash(f"Solicitud {solicitud.numero_serie} creada correctamente.", "success")
    return redirect(url_for("ventas.listar_solicitudes"))
