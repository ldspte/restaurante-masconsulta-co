# -*- coding: utf-8 -*-
"""
================================================================
  RESTAURANTE · ANEXOS  ·  soportes y evidencias
================================================================
Marcar «cumple» sin adjuntar el documento es una afirmación; el inspector pide
el papel. Lo mismo vale para la nómina —el desprendible firmado—, para las
compras —la factura del proveedor— y para el SG-SST —el acta de la
capacitación—. Sin archivos, esos módulos guardan promesas, no pruebas.

ESTE ES EL ÚNICO MÓDULO QUE RECIBE ARCHIVOS DE UN USUARIO
---------------------------------------------------------
Y por eso concentra las defensas. Subir archivos es la vía más directa que
existe para comprometer un servidor, así que cada decisión aquí está tomada
contra un ataque concreto:

  1. **El nombre lo pone el sistema, no el usuario.** Se guarda con un UUID y
     la extensión validada. El nombre original solo se conserva como texto
     para mostrarlo. Sin esto, un archivo llamado `../../main.py` sobrescribe
     el servidor, y uno llamado `factura.php` se ejecuta si algún día alguien
     pone un PHP delante.

  2. **Lista blanca de extensiones Y verificación de los bytes.** Un archivo
     que dice `.pdf` pero empieza con `MZ` es un ejecutable de Windows
     disfrazado. Confiar en la extensión —o en el `Content-Type` que manda el
     navegador— es confiar en el atacante.

  3. **Los archivos viven FUERA del árbol de estáticos.** No hay URL que los
     alcance adivinando. Se sirven por un endpoint que primero verifica que el
     anexo pertenezca a la sede de quien pregunta.

  4. **Se entregan siempre como descarga**, con `X-Content-Type-Options:
     nosniff`. Un SVG o un HTML subido no se renderiza en el origen de la
     aplicación, así que no puede ejecutar guiones con la sesión de nadie.

  5. **Una carpeta por sede.** El aislamiento entre locales que la base ya
     tiene se extiende al disco.

  6. **SHA-256 de cada archivo.** Sirve para detectar el mismo documento
     subido dos veces y para probar que no se alteró después.

Rutas
  POST   /api/anexos/{entidad}/{entidad_id}   sube un archivo
  GET    /api/anexos/{entidad}/{entidad_id}   lista los de esa ficha
  GET    /api/anexos/{anexo_id}/descargar     descarga uno
  DELETE /api/anexos/{anexo_id}               lo borra
  GET    /api/anexos/resumen/{entidad}        cuántos tiene cada ficha

Autor: Arquitectura de Software · Unidad 1
================================================================
"""
from __future__ import annotations

import hashlib
import logging
import os
import pathlib
import re
import uuid

from fastapi import (APIRouter, Depends, File, Form, HTTPException, UploadFile)
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from db import ahora, nombre_db_tenant, q, q1, run, serial
from dependencias import get_tenant_db
from seguridad import autor, require_rol, verify_token

log = logging.getLogger("restaurante.anexos")
router = APIRouter(tags=["Anexos"])

ROLES_SUBIR = ("admin", "gerente", "sst", "bodega")
ROLES_BORRAR = ("admin", "gerente")

# Raíz del almacén. Fuera de FrontEnd/ a propósito: nada de lo que hay aquí
# debe poder alcanzarse por URL directa.
RAIZ = pathlib.Path(__file__).resolve().parent / "data" / "anexos"

TOPE_BYTES = 10 * 1024 * 1024          # 10 MB
TOPE_POR_FICHA = 20

# A qué se puede adjuntar. Lista blanca: sin ella, alguien podría colgar
# archivos de una entidad inventada y el almacén se volvería un basurero sin
# dueño que nadie sabe cuándo borrar.
ENTIDADES = {
    "sst_estandar":    ("Estándar mínimo",   "sst_estandares"),
    "sst_actividad":   ("Actividad del plan", "sst_actividades"),
    "sst_incidente":   ("Incidente",          "sst_incidentes"),
    "nomina_periodo":  ("Período de nómina",  "nomina_periodos"),
    "orden_compra":    ("Orden de compra",    "ordenes_compra"),
    "activo":          ("Equipo",             "activos"),
    "mantenimiento":   ("Mantenimiento",      "activo_mantenimientos"),
    "producto":        ("Producto",           "productos"),
}

# Extensión permitida → firmas de bytes aceptables. `None` significa que el
# formato no tiene firma fija (texto plano, CSV) y se valida de otra forma.
FIRMAS = {
    ".pdf":  [b"%PDF"],
    ".png":  [b"\x89PNG\r\n\x1a\n"],
    ".jpg":  [b"\xff\xd8\xff"],
    ".jpeg": [b"\xff\xd8\xff"],
    ".webp": [b"RIFF"],
    ".xlsx": [b"PK\x03\x04"],
    ".xls":  [b"\xd0\xcf\x11\xe0", b"PK\x03\x04"],
    ".docx": [b"PK\x03\x04"],
    ".doc":  [b"\xd0\xcf\x11\xe0"],
    ".zip":  [b"PK\x03\x04"],
    ".csv":  None,
    ".txt":  None,
}

MIME = {
    ".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg", ".webp": "image/webp", ".csv": "text/csv",
    ".txt": "text/plain", ".zip": "application/zip",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
}


# ══════════════════════════════════════════════════════════════════════
#  UTILIDADES
# ══════════════════════════════════════════════════════════════════════
def _carpeta(cur: dict) -> pathlib.Path:
    """Carpeta de la sede. El nombre de base pasa por la misma validación de
    lista blanca que usa la cadena de conexión: es un dato del token, y aunque
    el token va firmado, un valor que termina siendo una ruta jamás se
    concatena sin validar."""
    db_name = nombre_db_tenant(str(cur.get("db_name") or "").replace("rst_", "", 1))
    d = RAIZ / db_name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _extension(nombre: str) -> str:
    ext = os.path.splitext(nombre or "")[1].lower()
    if ext not in FIRMAS:
        raise HTTPException(
            400, "Ese tipo de archivo no se admite. Se aceptan PDF, imágenes, "
                 "Excel, Word, CSV y ZIP.")
    return ext


def _verificar_bytes(ext: str, crudo: bytes) -> None:
    """Comprueba que el contenido corresponda a la extensión.

    Es la defensa contra el archivo disfrazado: uno llamado `acta.pdf` que en
    realidad empieza con `MZ` es un ejecutable. La extensión y el
    `Content-Type` los escribe quien sube; los primeros bytes, no.
    """
    firmas = FIRMAS.get(ext)
    if firmas is None:
        # Texto: se rechaza si trae bytes nulos, que delatan un binario.
        if b"\x00" in crudo[:4096]:
            raise HTTPException(400, "El archivo dice ser texto pero contiene binario.")
        return
    if not any(crudo.startswith(f) for f in firmas):
        raise HTTPException(
            400, f"El contenido del archivo no corresponde a un {ext[1:].upper()}. "
                 "Verifique que no se haya renombrado la extensión.")


def _limpiar_nombre(nombre: str) -> str:
    """Deja el nombre original apto para MOSTRARLO. Nunca se usa como ruta."""
    n = os.path.basename(nombre or "archivo")
    n = re.sub(r"[\r\n\t]", " ", n).strip()
    return (n or "archivo")[:255]


def _validar_ficha(db: Session, entidad: str, entidad_id: int) -> str:
    if entidad not in ENTIDADES:
        raise HTTPException(400, f"No se pueden adjuntar archivos a «{entidad}»")
    etiqueta, tabla = ENTIDADES[entidad]
    if not q1(db, f"SELECT id FROM {tabla} WHERE id = :i", {"i": entidad_id}):
        raise HTTPException(404, f"{etiqueta} no encontrado")
    return etiqueta


def _humano(n: int) -> str:
    n = float(n or 0)
    for u in ("B", "KB", "MB"):
        if n < 1024 or u == "MB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} MB"


# ══════════════════════════════════════════════════════════════════════
#  SUBIR
# ══════════════════════════════════════════════════════════════════════
@router.post("/api/anexos/{entidad}/{entidad_id}", status_code=201)
async def subir(entidad: str, entidad_id: int,
                archivo: UploadFile = File(...), descripcion: str = Form(""),
                cur: dict = Depends(require_rol(*ROLES_SUBIR)),
                db: Session = Depends(get_tenant_db)):
    _validar_ficha(db, entidad, entidad_id)

    n = q1(db, "SELECT COUNT(*) AS n FROM anexos WHERE entidad=:e AND entidad_id=:i",
           {"e": entidad, "i": entidad_id}) or {}
    if int(n.get("n") or 0) >= TOPE_POR_FICHA:
        raise HTTPException(409, f"Esta ficha ya tiene {TOPE_POR_FICHA} anexos. "
                                 "Borre alguno antes de subir otro.")

    ext = _extension(archivo.filename or "")
    crudo = await archivo.read()
    if not crudo:
        raise HTTPException(400, "El archivo está vacío")
    if len(crudo) > TOPE_BYTES:
        raise HTTPException(400, f"El archivo pesa {_humano(len(crudo))} y el tope "
                                 f"es {_humano(TOPE_BYTES)}.")
    _verificar_bytes(ext, crudo)

    sha = hashlib.sha256(crudo).hexdigest()
    repetido = q1(db, "SELECT id, nombre FROM anexos WHERE entidad=:e AND entidad_id=:i "
                      "AND sha256=:s", {"e": entidad, "i": entidad_id, "s": sha})
    if repetido:
        raise HTTPException(409, f"Ese archivo ya está adjunto como "
                                 f"«{repetido['nombre']}».")

    # El nombre en disco lo genera el sistema. Es la defensa contra el salto de
    # directorio y contra la extensión ejecutable.
    en_disco = f"{uuid.uuid4().hex}{ext}"
    destino = _carpeta(cur) / en_disco
    destino.write_bytes(crudo)

    try:
        res = run(db, "INSERT INTO anexos (entidad, entidad_id, nombre, archivo, tipo, "
                      "tamano, sha256, descripcion, subido_por, subido_en) "
                      "VALUES (:e,:i,:n,:a,:t,:tam,:s,:d,:u,:ts)",
                  {"e": entidad, "i": entidad_id,
                   "n": _limpiar_nombre(archivo.filename), "a": en_disco,
                   "t": MIME.get(ext, "application/octet-stream"),
                   "tam": len(crudo), "s": sha,
                   "d": (descripcion or "").strip()[:300] or None,
                   "u": autor(cur), "ts": ahora()})
    except Exception:
        # Si la fila no se pudo escribir, el archivo en disco sobra: dejarlo
        # produciría un huérfano que nadie sabe a qué pertenece.
        destino.unlink(missing_ok=True)
        raise

    log.info("Anexo subido: %s/%s · %s (%s)", entidad, entidad_id,
             archivo.filename, _humano(len(crudo)))
    return {"ok": True, "id": int(getattr(res, "lastrowid", 0) or 0),
            "nombre": _limpiar_nombre(archivo.filename),
            "tamano": len(crudo), "tamano_humano": _humano(len(crudo)),
            "mensaje": "Anexo guardado."}


# ══════════════════════════════════════════════════════════════════════
#  LISTAR, DESCARGAR Y BORRAR
# ══════════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════════════
#  ORDEN DE LAS RUTAS — no es cosmético
#
#  `/api/anexos/{entidad}/{entidad_id}` tiene dos parámetros y se traga
#  cualquier par de segmentos: `/api/anexos/1/descargar` entra ahí con
#  entidad="1" y entidad_id="descargar", y responde 422 en vez de servir el
#  archivo. FastAPI resuelve por ORDEN DE DECLARACIÓN, así que las rutas con
#  segmento literal van PRIMERO.
# ══════════════════════════════════════════════════════════════════════
@router.get("/api/anexos/resumen/{entidad}")
def resumen(entidad: str, cur: dict = Depends(verify_token),
            db: Session = Depends(get_tenant_db)):
    """Cuántos anexos tiene cada ficha, en una sola consulta.

    Existe para que una tabla de treinta estándares pueda mostrar el contador
    de cada uno sin hacer treinta llamadas.
    """
    if entidad not in ENTIDADES:
        raise HTTPException(400, "Entidad no válida")
    filas = q(db, "SELECT entidad_id, COUNT(*) AS n FROM anexos WHERE entidad=:e "
                  "GROUP BY entidad_id", {"e": entidad})
    return {"ok": True, "conteo": {str(f["entidad_id"]): int(f["n"]) for f in filas}}


@router.get("/api/anexos/{anexo_id}/descargar")
def descargar(anexo_id: int, cur: dict = Depends(verify_token),
              db: Session = Depends(get_tenant_db)):
    """Entrega el archivo. SIEMPRE como descarga, nunca en línea.

    `get_tenant_db` ya resolvió la base a partir del token, así que esta
    consulta solo puede encontrar anexos de la sede de quien pregunta: el
    aislamiento no depende de que este endpoint se acuerde de filtrarlo.

    `X-Content-Type-Options: nosniff` más `Content-Disposition: attachment`
    impiden que un SVG o un HTML subido se ejecute en el origen de la
    aplicación con la sesión de quien lo abre.
    """
    a = q1(db, "SELECT * FROM anexos WHERE id=:i", {"i": anexo_id})
    if not a:
        raise HTTPException(404, "Anexo no encontrado")

    ruta = _carpeta(cur) / str(a["archivo"])
    # Comprobación de contención: aunque el nombre lo genera el sistema, se
    # verifica que la ruta resuelta siga dentro de la carpeta de la sede.
    if not str(ruta.resolve()).startswith(str(_carpeta(cur).resolve())):
        raise HTTPException(400, "Ruta de archivo inválida")
    if not ruta.exists():
        raise HTTPException(410, "El archivo ya no está en el servidor.")

    return FileResponse(
        str(ruta), media_type=a["tipo"] or "application/octet-stream",
        filename=a["nombre"],
        headers={"X-Content-Type-Options": "nosniff",
                 "Content-Disposition": f'attachment; filename="{a["nombre"]}"'})


@router.get("/api/anexos/{entidad}/{entidad_id}")
def listar(entidad: str, entidad_id: int, cur: dict = Depends(verify_token),
           db: Session = Depends(get_tenant_db)):
    if entidad not in ENTIDADES:
        raise HTTPException(400, "Entidad no válida")
    filas = serial(q(db, "SELECT id, nombre, tipo, tamano, descripcion, subido_por, "
                         "subido_en FROM anexos WHERE entidad=:e AND entidad_id=:i "
                         "ORDER BY id DESC", {"e": entidad, "i": entidad_id}))
    for f in filas:
        f["tamano_humano"] = _humano(f["tamano"])
    return {"ok": True, "items": filas, "tope": TOPE_POR_FICHA}


@router.delete("/api/anexos/{anexo_id}")
def borrar(anexo_id: int, cur: dict = Depends(require_rol(*ROLES_BORRAR)),
           db: Session = Depends(get_tenant_db)):
    a = q1(db, "SELECT * FROM anexos WHERE id=:i", {"i": anexo_id})
    if not a:
        raise HTTPException(404, "Anexo no encontrado")

    # Primero la fila, después el archivo. Al revés, un fallo al borrar la
    # fila dejaría un registro que apunta a un archivo inexistente.
    run(db, "DELETE FROM anexos WHERE id=:i", {"i": anexo_id})
    (_carpeta(cur) / str(a["archivo"])).unlink(missing_ok=True)
    log.info("Anexo borrado: %s · %s", anexo_id, a["nombre"])
    return {"ok": True, "mensaje": f"«{a['nombre']}» eliminado."}
