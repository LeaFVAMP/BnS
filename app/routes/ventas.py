# app/routes/ventas.py
from __future__ import annotations
import json
from datetime import datetime
from typing import Dict, Any, Optional
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from decimal import Decimal

from flask_login import login_required, current_user
from sqlalchemy import and_
from app import db
from app.models import (
    Solicitud, SolicitudServicio, TipoServicio,
    Cliente, ClienteTipo, Modalidad, Folio,
    CotizacionOpcion, CotizacionItem,
    VentaDecision, VentaDecisionItem
)
from flask import send_file
import os

bp = Blueprint("ventas", __name__)


# ----------------- Helpers -----------------
def generar_numero_serie_anual() -> str:
    """Si quisieras seguir usando esta serie, queda disponible."""
    hoy = datetime.utcnow()
    ini = datetime(hoy.year, 1, 1)
    fin = datetime(hoy.year, 12, 31, 23, 59, 59, 999999)
    count = (Solicitud.query
             .filter(and_(Solicitud.fecha_solicitud >= ini,
                          Solicitud.fecha_solicitud <= fin))
             .count())
    return f"Q{count + 1:04d}{hoy.year}"

def generar_codigo_folio() -> str:
    """Código único de folio padre."""
    return "F-" + datetime.utcnow().strftime("%Y%m%d-%H%M%S")

def _bool_from_radio(val: str | None) -> bool:
    return (val or "").strip().lower() in {"si", "sí", "true", "1", "on", "yes"}

def _to_float_or_none(v: Any) -> Optional[float]:
    if v is None:
        return None
    s = str(v).strip()
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None

def _get_serv_detail(prefix: str) -> Dict[str, Any]:
    """
    Extrae el bloque de campos de un servicio con prefijo: aereo|maritimo|terrestre.
    'modalidad' sólo aplica realmente a marítimo (FCL/LCL) según tu Enum.
    """
    modalidad = (request.form.get(f"{prefix}_modalidad") or "").upper().strip()
    d = {
        "modalidad": modalidad,  # útil para marítimo
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

    # Para marítimo-FCL admitimos lista de contenedores (si tu form los manda)
    if modalidad == "FCL" and prefix == "maritimo":
        cont_types = []
        for k, v in request.form.items():
            if k.startswith(f"{prefix}_cont_") and k.endswith("_tipo") and v:
                base = k[:-5]  # quitar _tipo
                cant = (request.form.get(f"{base}_cantidad") or "").strip()
                cont_types.append({"tipo": v, "cantidad": int(cant or "0")})
        if cont_types:
            d["contenedores"] = cont_types
            d["numero_contenedor"] = sum(c["cantidad"] for c in cont_types)
    return d

def _ensure_cliente_for_name(nombre: str) -> Cliente:
    nm = (nombre or "").strip()
    if not nm:
        raise ValueError("Nombre de cliente vacío.")
    c = Cliente.query.filter(Cliente.nombre.ilike(nm)).first()
    if c:
        return c
    c = Cliente(nombre=nm, activo=True)
    db.session.add(c)
    db.session.flush()
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

def _map_modalidad(tipo: str, raw: str | None) -> Modalidad | None:
    """
    Sólo tu Enum: FCL, LCL. Aplica a marítimo.
    Para aéreo/terrestre regresamos None (no hay modalidad en el Enum para esos).
    """
    if tipo != "maritimo":
        return None
    v = (raw or "").strip().upper()
    if v in {"FCL", "LCL"}:
        return Modalidad[v]
    # Por defecto, si no vino valor, asumimos LCL (ajústalo si prefieres FCL)
    return Modalidad.LCL

# ----------------- Vistas -----------------
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

    # --- Cliente / prospecto ---
    cliente_tipo, cliente_id, prospecto_nombre, cliente_label = _resolver_cliente(request.form)
    if not cliente_label:
        flash("Debes seleccionar un cliente o escribir el nombre del prospecto.", "warning")
        return redirect(url_for("ventas.crear_solicitud"))

    # --- Servicios seleccionados (máx 3: aereo/maritimo/terrestre) ---
    servicios_sel = [s for s in request.form.getlist("servicios[]") if s in {"aereo", "maritimo", "terrestre"}]
    if not servicios_sel:
        flash("Selecciona al menos un tipo de servicio.", "warning")
        return redirect(url_for("ventas.crear_solicitud"))

    detalle_por_tipo: Dict[str, Dict[str, Any]] = {s: _get_serv_detail(s) for s in servicios_sel}

    # --- Folio padre ---
    folio = Folio(codigo=generar_codigo_folio())
    db.session.add(folio)
    db.session.flush()  # folio.id

    tipo_map = {
        "aereo": TipoServicio.AEREO,
        "maritimo": TipoServicio.MARITIMO,
        "terrestre": TipoServicio.TERRESTRE,
    }

    creadas: list[Solicitud] = []
    child_seq = 0

    for tipo in servicios_sel:
        det = detalle_por_tipo.get(tipo, {})
        child_seq += 1

        # Serie por hija basada en folio
        numero_serie = f"{folio.codigo}-{child_seq:02d}"

        # Campos comunes, pero tomados del detalle del TIPO correspondiente
        s = Solicitud(
            folio_id=folio.id,
            child_seq=child_seq,
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

            tipo_embarque=det.get("tipo_embarque", ""),
            incoterm=det.get("incoterm", ""),
            un_clase=det.get("un_clase") or None,
            estibable=bool(det.get("estibable", False)),
            tipo_cambio=(det.get("tipo_cambio") or "") or None,
            valor_factura=_to_float_or_none(det.get("valor_factura")) if det.get("seguro") else None,
            seguro=bool(det.get("seguro", False)),

            origen_pais=det.get("origen", {}).get("pais", ""),
            origen_ciudad=det.get("origen", {}).get("ciudad", ""),
            origen_cp=det.get("origen", {}).get("cp", ""),
            origen_recoleccion=det.get("origen", {}).get("recoleccion") or None,
            origen_puerto=det.get("origen", {}).get("puerto") or None,
            origen_cruce=det.get("origen", {}).get("cruce") or None,
            origen_despacho=det.get("origen", {}).get("despacho") or None,

            destino_pais=det.get("destino", {}).get("pais", ""),
            destino_ciudad=det.get("destino", {}).get("ciudad", ""),
            destino_cp=det.get("destino", {}).get("cp", ""),
            destino_entrega=det.get("destino", {}).get("entrega") or None,
            destino_puerto=det.get("destino", {}).get("puerto") or None,
            destino_cruce=det.get("destino", {}).get("cruce") or None,
            destino_despacho=det.get("destino", {}).get("despacho") or None,

            unidad=det.get("unidad", "") or "N/A",
            servicio_unidad=det.get("servicio_unidad", "") or "sencillo",
            maniobra=det.get("maniobra", "") or "ninguna",
            numero_contenedor=str(det.get("numero_contenedor", "") or ""),
            tipo_contenedor=(request.form.get(f"{tipo}_tipo_contenedor") or "") or None,

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

            # Cada hija conoce sólo su tipo
            servicios_solicitados=json.dumps([tipo]),
            comentarios=request.form.get("comentarios") or None,
            asunto_email=request.form.get("asunto_email") or None,

            estatus="pendiente",
        )
        db.session.add(s)
        db.session.flush()  # s.id

        svc = SolicitudServicio(
            solicitud_id=s.id,
            tipo_servicio=tipo_map[tipo],
            modalidad=_map_modalidad(tipo, det.get("modalidad")),
            detalle_json=det,  # JSON
        )
        db.session.add(svc)

        creadas.append(s)

    db.session.commit()
    flash(f"Folio {folio.codigo} creado con {len(creadas)} solicitud(es).", "success")
    return redirect(url_for("ventas.listar_solicitudes"))

# --- COMPARADOR DE OPCIONES ---

@bp.get("/solicitud/<int:sol_id>/opciones")
@login_required
def comparar_opciones(sol_id: int):
    s = db.session.get(Solicitud, sol_id)
    if not s:
        abort(404)
    opciones = (s.cotizacion_opciones
                .order_by(CotizacionOpcion.created_at.asc())
                .all())

    # Prepara items por opción (ligero)
    opciones_items = {}
    for op in opciones:
        rows = (op.items
                  .order_by(CotizacionItem.id.asc())
                  .all())
        opciones_items[op.id] = rows

    return render_template(
        "Ventas/opciones.html",
        s=s,
        opciones=opciones,
        opciones_items=opciones_items,
    )


# --- CONFIRMAR OPCIÓN ELEGIDA ---
# app/routes/ventas.py


# imports necesarios arriba del archivo
from decimal import Decimal
from datetime import datetime
from app.utils.pdf import render_pdf  # <- helper que te pasé
# (si no lo tienes todavía, crea app/utils/pdf.py con render_pdf)

@bp.route("/opcion/<int:op_id>/confirmar", methods=["GET","POST"])
@login_required
def confirmar_opcion(op_id: int):
    op = db.session.get(CotizacionOpcion, op_id)
    if not op:
        abort(404)
    s = db.session.get(Solicitud, op.solicitud_id)
    if not s:
        abort(404)

    if request.method == "POST":
        # ---- leer formulario (igual que ya tenías) ----
        try:
            markup_pct = Decimal(str(request.form.get("markup_pct") or "0"))
        except Exception:
            markup_pct = Decimal("0")
        vigencia = (request.form.get("vigencia_oferta") or "").strip()
        tt_ventas = request.form.get("tt_ventas_dias")
        tt_ventas = int(tt_ventas) if tt_ventas else None

        sol_nombre = (request.form.get("solicitante_nombre") or "").strip()
        sol_email  = (request.form.get("solicitante_email") or "").strip()
        sol_tel    = (request.form.get("solicitante_tel") or "").strip()
        tyc_internos = request.form.get("tyc_internos") or None

        r = (markup_pct / Decimal("100"))  # fracción
        rows = op.items.order_by(CotizacionItem.id.asc()).all()

        dec = VentaDecision(
            solicitud_id=s.id,
            opcion_id=op.id,
            moneda=op.moneda or "MXN",
            markup_pct=markup_pct,
            tt_ventas_dias=tt_ventas,
            vigencia_cotizacion=vigencia,
            solicitante_nombre=sol_nombre,
            solicitante_email=sol_email,
            solicitante_tel=sol_tel,
            tyc_internos=tyc_internos,
        )
        db.session.add(dec)

        # ---- acumular totales (FALTABA) ----
        sum_total  = Decimal("0")
        sum_profit = Decimal("0")
        sum_venta  = Decimal("0")

        for it in rows:
            cantidad   = Decimal(str(it.cantidad or 0))
            costo_unit = Decimal(str(it.precio_unit or 0))  # ya incluye tarifa+ps si aplicaba
            base  = cantidad * costo_unit
            iva   = base * Decimal(str(it.iva_pct or 0))
            ret   = base * Decimal(str(it.ret_iva_pct or 0))
            total = base + iva + ret

            profit = total * r
            venta  = total + profit
            margen = (profit / venta * Decimal("100")) if venta > 0 else Decimal("0")

            # acumular
            sum_total  += total
            sum_profit += profit
            sum_venta  += venta

            db.session.add(VentaDecisionItem(
                decision=dec,
                concepto_nombre=(it.concepto_nombre or (f"{it.concepto.clave} — {it.concepto.descripcion}" if it.concepto else None)),
                proveedor=(it.proveedor or None),
                moneda=(it.moneda or op.moneda or "MXN"),
                unidad=(it.unidad or None),
                cantidad=cantidad,
                tarifa=costo_unit,     # guardas el unitario en "tarifa"
                ps=Decimal("0"),       # y PS en 0 (tu decisión de diseño actual)
                costo_unit=costo_unit,
                base=base, iva=iva, ret=ret, total=total,
                profit=profit, venta=venta, margen_pct=margen,
            ))

        # cerrar totales globales
        dec.profit_total = sum_profit
        dec.venta_total  = sum_venta
        dec.margen_pct   = (sum_profit / sum_venta * Decimal("100")) if sum_venta > 0 else Decimal("0")

        # ---- mover estatus a OFERTADO ----
        s.estatus = "ofertado"

        db.session.commit()  # necesitamos dec.id para nombrar el PDF

        # ---- generar PDF y guardar ruta ----
        out_rel = f"cotizaciones/{s.numero_serie}/cotizacion-op{op.id}-dec{dec.id}.pdf"
        pdf_path = render_pdf(
            "Ventas/pdf_cotizacion.html",   # template del PDF
            out_rel_path=out_rel,
            s=s, op=op, rows=rows, dec=dec, now=datetime.utcnow
        )
        dec.pdf_path = pdf_path
        db.session.commit()

        flash("Opción confirmada, PDF generado y estatus cambiado a 'ofertado'.", "success")
        return redirect(url_for("ventas.listar_solicitudes"))

    # GET
    rows = op.items.order_by(CotizacionItem.id.asc()).all()
    return render_template("Ventas/confirmar_opcion.html", s=s, op=op, rows=rows)

@bp.post("/solicitud/<int:sol_id>/marcar/<string:resultado>")
@login_required
def marcar_resultado(sol_id: int, resultado: str):
    s = db.session.get(Solicitud, sol_id)
    if not s:
        abort(404)

    if s.estatus != "ofertado":
        flash("Solo las solicitudes en estatus 'ofertado' pueden cerrarse.", "warning")
        return redirect(url_for("ventas.listar_solicitudes"))

    if resultado not in ("ganada", "perdida"):
        abort(400)

    s.estatus = resultado
    db.session.commit()
    flash(f"Solicitud marcada como {resultado}.", "success")
    return redirect(url_for("ventas.listar_solicitudes"))

@bp.get("/decision/<int:dec_id>/pdf")
@login_required
def descargar_decision_pdf(dec_id: int):
    dec = db.session.get(VentaDecision, dec_id)
    if not dec:
        abort(404)
    pdf_path = (dec.pdf_path or "").strip()
    if not pdf_path or not os.path.exists(pdf_path):
        flash("El PDF no está disponible en el servidor.", "warning")
        # vuelve al historial o a la solicitud asociada
        if dec.solicitud_id:
            return redirect(url_for("ventas.comparar_opciones", sol_id=dec.solicitud_id))
        return redirect(url_for("ventas.listar_solicitudes"))

    # Sugerimos un nombre amigable de descarga
    filename = f"{dec.moneda or 'MXN'}_{dec.id}.pdf"
    try:
        return send_file(pdf_path, as_attachment=True, download_name=filename)
    except Exception:
        flash("No se pudo enviar el archivo.", "danger")
        if dec.solicitud_id:
            return redirect(url_for("ventas.comparar_opciones", sol_id=dec.solicitud_id))
        return redirect(url_for("ventas.listar_solicitudes"))
