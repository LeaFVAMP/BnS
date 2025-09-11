from __future__ import annotations

from datetime import datetime
import enum
from sqlalchemy import Enum, ForeignKey, func, Numeric
from sqlalchemy.orm import relationship, Mapped, mapped_column
from flask_login import UserMixin
from app import db, bcrypt
from decimal import Decimal


# ---------- Enums ----------
class ItemTipo(enum.Enum):
    ORIGEN = "Origen"
    FLETE = "Flete"
    DESTINO = "Destino"
    OTROS = "Otros"


class TipoServicio(enum.Enum):
    AEREO = "aereo"
    MARITIMO = "maritimo"
    TERRESTRE = "terrestre"

class Modalidad(enum.Enum):
    FCL = "FCL"
    LCL = "LCL"

class ClienteTipo(enum.Enum):
    CLIENTE = "CLIENTE"
    PROSPECTO = "PROSPECTO"


# ---------- Modelos ----------
class User(UserMixin, db.Model):
    __tablename__ = "usuario"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(db.String(120), unique=True, index=True, nullable=False)
    password: Mapped[str] = mapped_column(db.String(255), nullable=False)
    rol: Mapped[str] = mapped_column(db.String(20), nullable=False, default="ventas")  # ventas | pricing | admin
    nombre: Mapped[str] = mapped_column(db.String(120), nullable=False, default="")

    def set_password(self, raw: str):
        self.password = bcrypt.generate_password_hash(raw).decode("utf-8")


class Cliente(db.Model):
    __tablename__ = "cliente"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(db.String(200), unique=True, nullable=False)
    activo: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True)


class Solicitud(db.Model):
    __tablename__ = "solicitud"

    id: Mapped[int] = mapped_column(primary_key=True)
    fecha_solicitud: Mapped[datetime] = mapped_column(db.DateTime, nullable=False, default=func.now())
    numero_serie: Mapped[str] = mapped_column(db.String(32), nullable=False, index=True, unique=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id"), nullable=False)

    departamento: Mapped[str] = mapped_column(db.String(2), nullable=False, default="C")
    vendedor: Mapped[str] = mapped_column(db.String(120), nullable=False, default="")
    sales_support: Mapped[str] = mapped_column(db.String(120), nullable=False, default="")
    prioridad: Mapped[str] = mapped_column(db.String(20), nullable=False, default="estándar")

    # Cliente/prospecto
    cliente: Mapped[str] = mapped_column(db.String(200), nullable=False)  # legible SIEMPRE
    cliente_tipo: Mapped[ClienteTipo] = mapped_column(Enum(ClienteTipo, name="cliente_tipo_enum"), nullable=False)
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("cliente.id"), nullable=True)
    prospecto_nombre: Mapped[str | None] = mapped_column(db.String(200))

    # Generales (heredados del 1er servicio seleccionado)
    tipo_embarque: Mapped[str] = mapped_column(db.String(10), nullable=False, default="")
    incoterm: Mapped[str] = mapped_column(db.String(10), nullable=False, default="")
    un_clase: Mapped[str | None] = mapped_column(db.String(50))
    estibable: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)
    tipo_cambio: Mapped[str | None] = mapped_column(db.String(10))
    valor_factura: Mapped[float | None] = mapped_column(db.Float)
    seguro: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)

    # Origen
    origen_pais: Mapped[str] = mapped_column(db.String(80), nullable=False, default="")
    origen_ciudad: Mapped[str] = mapped_column(db.String(80), nullable=False, default="")
    origen_cp: Mapped[str] = mapped_column(db.String(10), nullable=False, default="")
    origen_recoleccion: Mapped[str | None] = mapped_column(db.String(200))
    origen_puerto: Mapped[str | None] = mapped_column(db.String(120))
    origen_cruce: Mapped[str | None] = mapped_column(db.String(120))
    origen_despacho: Mapped[str | None] = mapped_column(db.String(10))

    # Destino
    destino_pais: Mapped[str] = mapped_column(db.String(80), nullable=False, default="")
    destino_ciudad: Mapped[str] = mapped_column(db.String(80), nullable=False, default="")
    destino_cp: Mapped[str] = mapped_column(db.String(10), nullable=False, default="")
    destino_entrega: Mapped[str | None] = mapped_column(db.String(200))
    destino_puerto: Mapped[str | None] = mapped_column(db.String(120))
    destino_cruce: Mapped[str | None] = mapped_column(db.String(120))
    destino_despacho: Mapped[str | None] = mapped_column(db.String(10))

    # Unidad
    unidad: Mapped[str] = mapped_column(db.String(80), nullable=False, default="N/A")
    servicio_unidad: Mapped[str] = mapped_column(db.String(80), nullable=False, default="sencillo")
    maniobra: Mapped[str] = mapped_column(db.String(80), nullable=False, default="ninguna")
    numero_contenedor: Mapped[str] = mapped_column(db.String(50), nullable=False, default="")
    tipo_contenedor: Mapped[str | None] = mapped_column(db.String(50))

    # Carga
    commodity: Mapped[str] = mapped_column(db.String(200), nullable=False, default="")
    tipo_carga: Mapped[str] = mapped_column(db.String(50), nullable=False, default="")
    peso_unidad: Mapped[str] = mapped_column(db.String(10), nullable=False, default="kg")
    longitud_unidad: Mapped[str] = mapped_column(db.String(10), nullable=False, default="cm")
    volumen_cbm: Mapped[float] = mapped_column(db.Float, nullable=False, default=0.0)

    cotiza_por: Mapped[str] = mapped_column(db.String(20), nullable=False, default="totales")

    # Totales
    no_s: Mapped[int | None] = mapped_column(db.Integer)
    dimensiones_totales: Mapped[str | None] = mapped_column(db.String(200))
    cbm_totales: Mapped[float | None] = mapped_column(db.Float)
    gw_totales: Mapped[float | None] = mapped_column(db.Float)
    vw_totales: Mapped[float | None] = mapped_column(db.Float)

    # Dimensiones unitarias
    no_dim: Mapped[int | None] = mapped_column(db.Integer)
    largo_dim: Mapped[float | None] = mapped_column(db.Float)
    ancho_dim: Mapped[float | None] = mapped_column(db.Float)
    alto_dim: Mapped[float | None] = mapped_column(db.Float)
    peso_dim: Mapped[float | None] = mapped_column(db.Float)

    # JSONs
    totales_json: Mapped[str | None] = mapped_column(db.Text)
    dimensiones_json: Mapped[str | None] = mapped_column(db.Text)

    # Auditoría / estado
    servicios_solicitados: Mapped[str] = mapped_column(db.Text, nullable=False, default="[]")  # json str
    comentarios: Mapped[str | None] = mapped_column(db.Text)
    asunto_email: Mapped[str | None] = mapped_column(db.String(200))
    estatus: Mapped[str] = mapped_column(db.String(40), nullable=False, default="pendiente", index=True)

    # relaciones
    servicios = relationship(
        "SolicitudServicio",
        back_populates="solicitud",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    cotizaciones = relationship(
        "Cotizacion",
        back_populates="solicitud",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    cotizacion_opciones = relationship(
    "CotizacionOpcion",
    back_populates="solicitud",
    lazy="dynamic",
    cascade="all, delete-orphan",
    )

    # --- agrupación por folio padre ---
    folio_id: Mapped[int | None] = mapped_column(ForeignKey("folio.id"), nullable=True, index=True)
    child_seq: Mapped[int | None] = mapped_column(db.Integer, nullable=True)
    folio = relationship("Folio", back_populates="solicitudes")
   

    __table_args__ = (
        db.UniqueConstraint("folio_id", "child_seq", name="uq_folio_childseq"),
    )



class SolicitudServicio(db.Model):
    __tablename__ = "solicitud_servicio"

    id: Mapped[int] = mapped_column(primary_key=True)
    solicitud_id: Mapped[int] = mapped_column(ForeignKey("solicitud.id"), nullable=False, index=True)
    tipo_servicio: Mapped[TipoServicio] = mapped_column(Enum(TipoServicio, name="tipo_servicio_enum"), nullable=False)
    modalidad: Mapped[Modalidad | None] = mapped_column(Enum(Modalidad, name="modalidad_enum"))
    detalle_json: Mapped[dict | str | None] = mapped_column(db.JSON)

    created_at: Mapped[datetime] = mapped_column(db.DateTime, nullable=False, default=func.now())

    solicitud = relationship("Solicitud", back_populates="servicios")


class Cotizacion(db.Model):
    __tablename__ = "cotizacion"

    id: Mapped[int] = mapped_column(primary_key=True)
    solicitud_id: Mapped[int] = mapped_column(ForeignKey("solicitud.id"), nullable=False, index=True)
    tipo_servicio: Mapped[str] = mapped_column(db.String(20), nullable=False)  # "aereo"/"maritimo"/"terrestre"
    estado: Mapped[str] = mapped_column(db.String(20), nullable=False, default="pendiente")  # pendiente/aprobada/...
    tarifas_json: Mapped[str | None] = mapped_column(db.Text)
    comentarios: Mapped[str | None] = mapped_column(db.Text)
    creada_por: Mapped[int | None] = mapped_column(db.Integer)
    created_at: Mapped[datetime] = mapped_column(db.DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(db.DateTime, nullable=False, default=func.now(), onupdate=func.now())

    solicitud = relationship("Solicitud", back_populates="cotizaciones")

class Folio(db.Model):
    __tablename__ = "folio"
    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(db.String(32), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(db.DateTime, nullable=False, default=func.now())

    solicitudes = relationship("Solicitud", back_populates="folio", lazy="dynamic")

class Concepto(db.Model):
    __tablename__ = "concepto"

    id: Mapped[int] = mapped_column(primary_key=True)
    clave: Mapped[str] = mapped_column(db.String(64), nullable=False, unique=True, index=True)
    descripcion: Mapped[str] = mapped_column(db.String(255), nullable=False)

    # Moneda es requerida para tu flujo
    moneda: Mapped[str] = mapped_column(db.String(3), nullable=False, default="MXN")

    # opcional
    unidad: Mapped[str | None] = mapped_column(db.String(32))

    # Tasas normalizadas (0–1)
    iva_pct: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0.0000"))
    ret_iva_pct: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0.0000"))
    isr_pct: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0.0000"))

    created_at: Mapped[datetime] = mapped_column(db.DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(db.DateTime, nullable=False, default=func.now(), onupdate=func.now())


class CotizacionOpcion(db.Model):
    __tablename__ = "cotizacion_opcion"

    id: Mapped[int] = mapped_column(primary_key=True)
    solicitud_id: Mapped[int] = mapped_column(ForeignKey("solicitud.id"), nullable=False, index=True)

    proveedor: Mapped[str] = mapped_column(db.String(200), nullable=False, default="")
    moneda: Mapped[str] = mapped_column(db.String(3), nullable=False, default="MXN")
    cbm_cotizado: Mapped[float | None] = mapped_column(db.Float, nullable=True)

    # Ruta / condiciones
    origen_final: Mapped[str | None] = mapped_column(db.String(200), nullable=True)
    destino_final: Mapped[str | None] = mapped_column(db.String(200), nullable=True)
    frecuencia: Mapped[str | None] = mapped_column(db.String(100), nullable=True)
    transito_estimado_dias: Mapped[int | None] = mapped_column(db.Integer, nullable=True)
    dias_libres_destino: Mapped[int | None] = mapped_column(db.Integer, nullable=True)
    terminos_condiciones: Mapped[str | None] = mapped_column(db.Text, nullable=True)

    # por si te sirve filtrar
    tipo_servicio: Mapped[str | None] = mapped_column(db.String(20), nullable=True)

    created_at: Mapped[datetime] = mapped_column(db.DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(db.DateTime, nullable=False, default=func.now(), onupdate=func.now())

    solicitud = relationship("Solicitud", back_populates="cotizacion_opciones")
    items = relationship("CotizacionItem", back_populates="opcion",
                         cascade="all, delete-orphan", lazy="dynamic")

    @db.validates("cbm_cotizado")
    def _round_lcl(self, key, value):
        """Si la solicitud tiene algún servicio LCL, y 0<cbm<1 => 1"""
        if value in (None, ""):
            return value
        v = Decimal(str(value))
        try:
            svcs = self.solicitud.servicios.all()  # lazy="dynamic"
        except Exception:
            svcs = list(self.solicitud.servicios or [])
        is_lcl = any(s.modalidad == Modalidad.LCL for s in svcs if hasattr(s, "modalidad"))
        if is_lcl and Decimal("0") < v < Decimal("1"):
            return 1.0
        return float(v)

class CotizacionItem(db.Model):
    __tablename__ = "cotizacion_item"

    id: Mapped[int] = mapped_column(primary_key=True)
    opcion_id: Mapped[int] = mapped_column(ForeignKey("cotizacion_opcion.id"), nullable=False, index=True)

    concepto_id: Mapped[int | None] = mapped_column(ForeignKey("concepto.id"))
    concepto_nombre: Mapped[str | None] = mapped_column(db.String(255))
    proveedor: Mapped[str | None] = mapped_column(db.String(200))

    moneda: Mapped[str] = mapped_column(db.String(3), nullable=False, default="MXN")
    unidad: Mapped[str | None] = mapped_column(db.String(32))

    cantidad: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    precio_unit: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))

    iva_pct: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0"))
    ret_iva_pct: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0"))
    isr_pct: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0"))

    opcion = relationship("CotizacionOpcion", back_populates="items")
    concepto = relationship("Concepto", lazy="joined")

    __table_args__ = (
        db.Index("ix_cotizacion_item_opcion_id", "opcion_id"),
    )
