from __future__ import annotations
import re, json
from decimal import Decimal
from pathlib import Path
import click
from flask import current_app
from app import db
from app.models import Concepto

def _parse_pct(s: str) -> Decimal:
    s = (s or "").strip().lower()
    if s in ("n/a", "na", "no aplica", "no objeto", "noobjeto"):
        return Decimal("0")
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*%", s)
    if m:
        return Decimal(m.group(1)) / Decimal("100")
    try:
        # si viene 0.16 o "0.16"
        return Decimal(s)
    except Exception:
        return Decimal("0")

def _split_desc_and_clave(raw: str) -> tuple[str, str]:
    # "Flete Marítimo de Exportación (EMFME)" -> ("Flete Marítimo de Exportación", "EMFME")
    m = re.match(r"^(.*)\(([^)]+)\)\s*$", raw.strip())
    if not m:
        # sin clave, usa la descripción como clave "normalizada"
        desc = raw.strip()
        clave = re.sub(r"\W+", "", desc.upper())[:20] or "CONCEPTO"
        return desc, clave
    desc = m.group(1).strip()
    clave = m.group(2).strip().upper()
    return desc, clave

@click.command("import_catalogo")
@click.argument("ruta", type=click.Path(exists=True, dir_okay=False))
@click.option("--moneda-default", default="MXN", show_default=True, help="Moneda por defecto para conceptos.")
def import_catalogo_cmd(ruta: str, moneda_default: str):
    """Importa/actualiza CONCEPTO desde un TXT con columnas: CONCEPTO \t TASA IVA \t RET IVA.
    Acepta UTF-16 o UTF-8. Upsert por CLAVE."""
    p = Path(ruta)
    raw = p.read_bytes()
    # intenta decodificaciones comunes
    for enc in ("utf-16", "utf-8-sig", "utf-8", "latin-1"):
        try:
            txt = raw.decode(enc)
            break
        except Exception:
            continue
    else:
        raise click.ClickException("No pude decodificar el archivo.")

    rows = [r for r in txt.splitlines() if r.strip()]
    if not rows:
        raise click.ClickException("Archivo vacío.")

    # detecta delimitador (tab por defecto)
    delim = "\t" if rows[0].count("\t") >= 1 else ","

    # salta encabezado si lo detecta
    start = 1 if "concepto" in rows[0].lower() else 0

    upserts = 0
    for line in rows[start:]:
        parts = [c.strip() for c in line.split(delim)]
        if len(parts) < 3:
            continue
        desc_raw, iva_raw, ret_raw = parts[0], parts[1], parts[2]
        desc, clave = _split_desc_and_clave(desc_raw)
        iva = _parse_pct(iva_raw)
        ret = _parse_pct(ret_raw)

        obj = Concepto.query.filter_by(clave=clave).first()
        if not obj:
            obj = Concepto(clave=clave)
            db.session.add(obj)
        obj.descripcion = desc
        obj.moneda = moneda_default.upper()
        obj.iva_pct = iva
        obj.ret_iva_pct = ret
        upserts += 1

    db.session.commit()
    click.echo(f"Conceptos procesados: {upserts}")
