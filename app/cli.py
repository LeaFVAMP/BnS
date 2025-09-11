# app/cli.py
from __future__ import annotations
import click
from decimal import Decimal

from app import db
from app.models import Concepto
from pathlib import Path

def _read_lines_any_encoding(path_str: str) -> list[str]:
    """
    Lee el archivo como bytes y decodifica según BOM:
      - UTF-16 LE (FF FE)
      - UTF-16 BE (FE FF)
      - UTF-8 con BOM (EF BB BF)
      - UTF-8 sin BOM
      - fallback CP1252 (Windows) si todo falla
    Devuelve las líneas sin saltos finales.
    """
    raw = Path(path_str).read_bytes()
    try:
        if raw.startswith(b"\xff\xfe"):
            text = raw.decode("utf-16-le")
        elif raw.startswith(b"\xfe\xff"):
            text = raw.decode("utf-16-be")
        elif raw.startswith(b"\xef\xbb\xbf"):
            text = raw.decode("utf-8-sig")
        else:
            # intenta utf-8 “limpio”
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                # último recurso: CP1252
                text = raw.decode("cp1252")
    except UnicodeDecodeError:
        # si algo raro pasó, fuerza CP1252
        text = raw.decode("cp1252", errors="replace")

    # normaliza saltos de línea
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _to_decimal_pct(x: str | float | int | None) -> Decimal:
    if x in (None, "", "None"):
        return Decimal("0")
    s = str(x).strip().replace("%","").replace(",", ".")  # <— permite comas
    v = Decimal(s)
    if v > 1:
        v = v / Decimal("100")
    return v.quantize(Decimal("0.0001"))

def _smart_split(line: str) -> list[str]:
    # admite | ; , o tab como separador
    for sep in ("|", ";", "\t", ","):
        if sep in line:
            return [p.strip() for p in line.split(sep)]
    return [line.strip()]

def register_cli(app):
        @app.cli.command("import_catalogo")
        @click.argument("ruta", type=click.Path(exists=True, dir_okay=False))
        @click.option("--moneda-default", default="MXN", show_default=True,
                    help="Moneda por defecto si la línea no trae moneda.")
        def import_catalogo_cmd(ruta, moneda_default):
            """
            Importa/actualiza el catálogo de conceptos desde un TXT.
            Formatos por línea (separador | ; , o tab):
            CLAVE | DESCRIPCION | MONEDA | UNIDAD | IVA% | RET_IVA% | ISR%
            Campos opcionales: MONEDA, UNIDAD, RET_IVA%, ISR%
            """
            added = 0
            updated = 0

            def _strip_bom(s: str) -> str:
                # elimina BOM si quedó pegado al primer token
                return s.lstrip("\ufeff").strip()

            def _is_header_row(parts: list[str]) -> bool:
                # detecta encabezados comunes
                if not parts:
                    return False
                first = _strip_bom(parts[0]).lower()
                return first in {"concepto", "clave", "codigo"}  # ajusta si tu header usa otra palabra


            # Usar lectura robusta de encoding
            for raw in _read_lines_any_encoding(ruta):
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue

                parts = _smart_split(line)
                # limpia BOM del primer campo
                if parts:
                    parts[0] = _strip_bom(parts[0])

                # salta header
                if _is_header_row(parts):
                    continue
                if len(parts) < 2:
                    app.logger.warning("Línea ignorada (faltan campos): %s", line)
                    continue

                clave = parts[0]
                descripcion = parts[1]
                moneda = (parts[2] if len(parts) >= 3 and parts[2] else moneda_default).upper()
                unidad = (parts[3] if len(parts) >= 4 and parts[3] else None)

                iva = _to_decimal_pct(parts[4] if len(parts) >= 5 else "0")
                ret_iva = _to_decimal_pct(parts[5] if len(parts) >= 6 else "0")
                isr = _to_decimal_pct(parts[6] if len(parts) >= 7 else "0")

                c = Concepto.query.filter_by(clave=clave).first()
                if not c:
                    c = Concepto(
                        clave=clave,
                        descripcion=descripcion,
                        moneda=moneda,
                        unidad=unidad,
                        iva_pct=iva,
                        ret_iva_pct=ret_iva,
                        isr_pct=isr,
                    )
                    db.session.add(c)
                    added += 1
                else:
                    c.descripcion = descripcion
                    c.moneda = moneda
                    c.unidad = unidad
                    c.iva_pct = iva
                    c.ret_iva_pct = ret_iva
                    c.isr_pct = isr
                    updated += 1

            db.session.commit()
            click.echo(f"Catálogo importado. Nuevos: {added}, Actualizados: {updated}")
