# app/services/catalogo_import.py
import re
from decimal import Decimal
from app.models import db, Concepto

IVA_MAP = {
    "NO OBJETO": ("No objeto", Decimal("0.0000")),
    "N/A":       ("N/A",       Decimal("0.0000")),
    "NA":        ("N/A",       Decimal("0.0000")),
    "-":         ("N/A",       Decimal("0.0000")),
    "0%":        ("0%",        Decimal("0.0000")),
    "16%":       ("16%",       Decimal("0.1600")),
    "8%":        ("8%",        Decimal("0.0800")),
    "4%":        ("4%",        Decimal("0.0400")),
}

def _parse_pct(label: str) -> tuple[str, Decimal]:
    u = (label or "").strip().upper()
    if u in IVA_MAP:
        return IVA_MAP[u]
    if u.endswith("%"):
        n = Decimal(u[:-1].strip())/Decimal("100")
        return (label.strip(), n.quantize(Decimal("0.0001")))
    return (label.strip(), Decimal("0.0000"))

def _split_concepto(raw: str) -> tuple[str, str]:
    # "Texto (CLAVE)" -> (Texto, CLAVE). Si no hay (), generamos clave a partir del texto.
    m = re.match(r"^(.*)\(([^)]+)\)\s*$", raw.strip())
    if m:
        return (m.group(1).strip(), m.group(2).strip())
    base = raw.strip()
    clave = re.sub(r"\W+", "", base.upper())[:32]
    return (base, clave)

def import_catalogo_from_text(text: str, default_currency: str = "USD") -> int:
    rows = [r for r in text.splitlines() if r.strip()]
    if not rows:
        return 0
    # Encabezado
    head = rows[0].upper()
    if head.startswith("CONCEPTO"):
        rows = rows[1:]

    count = 0
    for line in rows:
        parts = [p.strip() for p in line.split("\t")]
        if len(parts) < 3:
            continue
        concepto_raw, iva_raw, ret_raw = parts[:3]
        moneda = (parts[3].upper() if len(parts) >= 4 and parts[3].strip() else default_currency).upper()

        desc, clave = _split_concepto(concepto_raw)
        iva_label, iva_pct = _parse_pct(iva_raw)
        ret_label, ret_pct = _parse_pct(ret_raw)

        obj = Concepto.query.filter_by(clave=clave).first()
        if not obj:
            obj = Concepto(clave=clave)
            db.session.add(obj)

        obj.descripcion = desc
        obj.moneda_default = moneda
        obj.iva_label = iva_label
        obj.ret_iva_label = ret_label
        obj.iva_pct = iva_pct
        obj.ret_iva_pct = ret_pct

        count += 1

    db.session.commit()
    return count
