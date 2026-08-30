# -*- coding: utf-8 -*-
"""
================================================================
  RESTAURANTE · Capa de Acceso a Datos  (MySQL / MariaDB)
================================================================
Núcleo de persistencia. Concentra tres responsabilidades que el resto de la
aplicación no debe volver a resolver:

  1. Resolución de conexiones multi-tenant (una base por sede).
  2. Caché de motores por base (Singleton por clave).
  3. Helpers de consulta uniformes: q / q1 / run / serial.

DECISIÓN — MySQL como único motor
---------------------------------
Se abandonó el soporte dual con SQLite. Mantener dos dialectos de DDL obliga a
probar los dos, y en la práctica solo se prueba uno: la portabilidad termina
siendo una ilusión que falla el día que se necesita. El destino es MySQL, así
que el DDL se escribe para MySQL.

DECISIÓN — SQL explícito sobre ORM
----------------------------------
Se usa SQLAlchemy Core (motor + `text()`), no el ORM. El sistema es intensivo en
reportes y agregaciones —kardex, arqueo, nómina, estado de resultados— donde el
SQL declarativo es más legible y predecible que un grafo de objetos. El precio
—escribir SQL a mano— se acota concentrando TODO el acceso en tres helpers que
siempre parametrizan y por lo tanto cierran la inyección SQL por construcción.

DECISIÓN — DECIMAL para dinero
------------------------------
`DOUBLE` acumula error en sumas repetidas y un arqueo de caja que difiere en
centavos es indistinguible de un faltante real. Todo importe monetario usa
DECIMAL; las cantidades de receta, que sí admiten fracciones finas, usan
DECIMAL con cuatro decimales.

Autor: Arquitectura de Software · Unidad 1
================================================================
"""
from __future__ import annotations

import datetime
import decimal
import logging
import os
import re
import threading
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

log = logging.getLogger("restaurante.db")

BASE_DIR = Path(__file__).resolve().parent

# ── Conexión ─────────────────────────────────────────────────────────────
DB_HOST = os.getenv("RST_DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("RST_DB_PORT", "3306"))
DB_USER = os.getenv("RST_DB_USER", "root")
DB_PASS = os.getenv("RST_DB_PASS", "")

MASTER_DB = os.getenv("RST_MASTER_DB", "rst_master")
TENANT_PREFIX = os.getenv("RST_TENANT_PREFIX", "rst_")

DB_POOL_SIZE = int(os.getenv("RST_POOL_SIZE", "5"))
DB_MAX_OVERFLOW = int(os.getenv("RST_MAX_OVERFLOW", "5"))
DB_POOL_RECYCLE = int(os.getenv("RST_POOL_RECYCLE", "1800"))

_SLUG_OK = re.compile(r"^[a-z0-9_]{1,48}$")


def db_url(db_name: str = "") -> str:
    """URL de conexión. Sin `db_name` apunta al servidor, sin base seleccionada
    —necesario para poder crear la base de una sede nueva."""
    from urllib.parse import quote_plus

    cred = f"{DB_USER}:{quote_plus(DB_PASS)}@" if DB_PASS else f"{DB_USER}@"
    destino = f"/{db_name}" if db_name else "/"
    return f"mysql+pymysql://{cred}{DB_HOST}:{DB_PORT}{destino}?charset=utf8mb4"


# ── Caché de motores (Singleton por nombre de base) ──────────────────────
# Abrir un motor por petición agotaría conexiones y perdería el pool. El cerrojo
# protege la creación concurrente: sin él, dos peticiones simultáneas de la
# misma sede crearían dos motores y uno quedaría huérfano sin cerrar.
_ENGINES: dict[str, Engine] = {}
_SESSIONMAKERS: dict[str, sessionmaker] = {}
_ENGINE_LOCK = threading.Lock()


def get_engine(db_name: str) -> Engine:
    eng = _ENGINES.get(db_name)
    if eng is not None:
        return eng
    with _ENGINE_LOCK:
        eng = _ENGINES.get(db_name)          # doble verificación bajo cerrojo
        if eng is not None:
            return eng
        eng = create_engine(
            db_url(db_name), future=True,
            pool_pre_ping=True,              # descarta conexiones que MySQL cerró
            pool_size=DB_POOL_SIZE,
            max_overflow=DB_MAX_OVERFLOW,
            pool_recycle=DB_POOL_RECYCLE,    # por debajo del wait_timeout de MySQL
        )
        _ENGINES[db_name] = eng
        return eng


def get_sessionmaker(db_name: str) -> sessionmaker:
    sm = _SESSIONMAKERS.get(db_name)
    if sm is None:
        sm = sessionmaker(bind=get_engine(db_name), autoflush=False, future=True)
        _SESSIONMAKERS[db_name] = sm
    return sm


def nombre_db_tenant(slug: str) -> str:
    """Nombre físico de la base de una sede a partir de su código.

    Valida contra lista blanca. El nombre de base NO puede parametrizarse en SQL
    —va en la cadena de conexión y en el CREATE DATABASE—, así que es el único
    punto donde un valor externo toca SQL sin ligar: la validación estricta es
    la defensa.
    """
    slug = (slug or "").strip().lower()
    if not _SLUG_OK.match(slug):
        raise ValueError(f"Código de sede inválido: {slug!r}. "
                         f"Use solo minúsculas, números y guion bajo.")
    return TENANT_PREFIX + slug


def crear_base_si_no_existe(db_name: str) -> None:
    """Crea la base física. Idempotente.

    `db_name` ya pasó por `nombre_db_tenant`, o es el nombre de la maestra
    definido en el entorno: en ningún caso proviene directamente del usuario.
    """
    if not re.match(r"^[A-Za-z0-9_]{1,64}$", db_name):
        raise ValueError(f"Nombre de base inválido: {db_name!r}")
    servidor = create_engine(db_url(), future=True, poolclass=None)
    try:
        with servidor.connect() as c:
            c.execute(text(f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
                           f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"))
            c.commit()
    finally:
        servidor.dispose()


def probar_conexion() -> tuple[bool, str]:
    """Verifica que el servidor responda. La usa la sonda de salud y el arranque,
    para fallar con un mensaje entendible en vez de un rastro de excepciones."""
    try:
        servidor = create_engine(db_url(), future=True)
        try:
            with servidor.connect() as c:
                version = c.execute(text("SELECT VERSION()")).scalar()
            return True, str(version)
        finally:
            servidor.dispose()
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


# ── Helpers de consulta ──────────────────────────────────────────────────
def q(db: Session, sql: str | Any, params: dict | None = None) -> list[dict]:
    """Ejecuta una consulta y devuelve una lista de diccionarios."""
    if isinstance(sql, str):
        sql = text(sql)
    rows = db.execute(sql, params or {}).mappings().all()
    return [dict(r) for r in rows]


def q1(db: Session, sql: str | Any, params: dict | None = None) -> Optional[dict]:
    """Ejecuta una consulta y devuelve la primera fila o None."""
    rows = q(db, sql, params)
    return rows[0] if rows else None


def run(db: Session, sql: str | Any, params: dict | None = None):
    """Ejecuta una escritura y hace commit.

    IMPORTANTE: `lastrowid` se captura ANTES del commit. Tras el commit la
    conexión vuelve al pool, y `LAST_INSERT_ID()` es POR CONEXIÓN en MySQL: una
    consulta posterior puede ejecutarse en otra conexión y devolver 0. Es un
    fallo silencioso clásico —el insert funciona, el id llega en cero y el
    frontend «no guarda»—.
    """
    if isinstance(sql, str):
        sql = text(sql)
    result = db.execute(sql, params or {})
    try:
        last = result.lastrowid
    except Exception:
        last = None
    db.commit()
    try:
        result.lastrowid = last
    except Exception:
        pass
    return result


def run_sin_commit(db: Session, sql: str | Any, params: dict | None = None):
    """Igual que `run` pero SIN commit: para operaciones que deben ser atómicas
    en conjunto (venta + ítems + pagos + movimientos + asientos). El llamador es
    responsable del `commit()` o del `rollback()`."""
    if isinstance(sql, str):
        sql = text(sql)
    return db.execute(sql, params or {})


def serial(rows):
    """Normaliza a JSON los tipos que no lo son (fechas, Decimal, bytes).

    Se aplica en el borde de salida de cada router para que ningún endpoint
    tenga que acordarse de convertir un Decimal a float.
    """
    if rows is None:
        return []
    if isinstance(rows, dict):
        rows = [rows]
    for row in rows:
        for k, v in list(row.items()):
            if isinstance(v, decimal.Decimal):
                row[k] = float(v)
            elif isinstance(v, (datetime.datetime, datetime.date, datetime.time)):
                row[k] = v.isoformat()
            elif isinstance(v, datetime.timedelta):
                row[k] = str(v)
            elif isinstance(v, (bytes, bytearray)):
                row[k] = v.decode("utf-8", "replace")
    return rows


def siguiente_consecutivo(db: Session, tipo: str, anio: int) -> int:
    """Serie consecutiva atómica por (tipo, año).

    Dos cajas no pueden emitir el mismo folio. `SELECT MAX(...)+1` tiene una
    condición de carrera evidente entre terminales simultáneas; el UPSERT la
    resuelve porque MySQL serializa la escritura sobre la fila.

    `LAST_INSERT_ID(expr)` fija el valor devuelto por la conexión actual, así
    que el número se lee sin una segunda consulta y sin riesgo de leer el de
    otra terminal.
    """
    res = run(db, "INSERT INTO consecutivos (tipo, anio, ultimo) "
                  "VALUES (:t, :y, LAST_INSERT_ID(1)) "
                  "ON DUPLICATE KEY UPDATE ultimo = LAST_INSERT_ID(ultimo + 1)",
              {"t": tipo, "y": anio})
    numero = getattr(res, "lastrowid", 0) or 0
    if not numero:      # respaldo defensivo si el driver no expone lastrowid
        fila = q1(db, "SELECT ultimo FROM consecutivos WHERE tipo=:t AND anio=:y",
                  {"t": tipo, "y": anio})
        numero = int((fila or {}).get("ultimo") or 1)
    return int(numero)


def ahora() -> str:
    """Marca de tiempo UTC en ISO-8601. Todo el sistema almacena UTC; la
    conversión a hora local es responsabilidad del frontend."""
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


# ══════════════════════════════════════════════════════════════════════
#  ZONA HORARIA DEL NEGOCIO
#
#  `datetime.date.today()` devuelve el dia del SERVIDOR. En un hosting
#  compartido eso no es el dia del restaurante: el de este despliegue esta en
#  Phoenix (UTC-7) y el restaurante en Bogota (UTC-5), dos horas por delante.
#  Entre medianoche y las 2 a.m. el servidor seguia en la fecha anterior, asi
#  que «las reservas de hoy» salian vacias con reservas de hoy en la base.
#
#  El mismo error afecta al consecutivo anual: una venta del 1 de enero a las
#  00:30 recibia un folio del ano pasado.
#
#  Las marcas de tiempo siguen guardandose en UTC —eso esta bien y no cambia—.
#  Lo que se corrige es la nocion de «que dia es hoy AQUI».
# ══════════════════════════════════════════════════════════════════════
TZ_NEGOCIO = os.getenv("RST_TZ", "America/Bogota")


def _zona():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(TZ_NEGOCIO)
    except Exception:
        # Sin base de datos de zonas horarias en el sistema, se usa un desfase
        # fijo. Colombia no tiene horario de verano, asi que -5 es exacto todo
        # el ano; para otros paises se ajusta con RST_TZ_OFFSET.
        horas = float(os.getenv("RST_TZ_OFFSET", "-5"))
        return datetime.timezone(datetime.timedelta(hours=horas))


def ahora_local() -> datetime.datetime:
    """El instante actual EN LA ZONA DEL NEGOCIO."""
    return datetime.datetime.now(_zona())


def hoy() -> str:
    """La fecha de hoy para el restaurante, no para el servidor."""
    return ahora_local().date().isoformat()


def anio_actual() -> int:
    """El ano en curso del negocio. Lo usan los consecutivos.

    Se llama `anio_actual` y no `anio` a proposito: varios routers usan
    `anio` como variable local, y `anio = anio_actual()` es un UnboundLocalError
    que solo aparece al arrancar.
    """
    return ahora_local().year
