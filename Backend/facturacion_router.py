# -*- coding: utf-8 -*-
"""
================================================================
  CAFETERÍA · Módulo FACTURACIÓN ELECTRÓNICA
================================================================
Maestro de adquirientes y generación del documento electrónico de venta
conforme a los requisitos de la DIAN (Colombia).

QUÉ HACE Y QUÉ NO — LÍMITE EXPLÍCITO
------------------------------------
Este módulo **prepara** el documento electrónico: valida los datos del
adquiriente, asigna el consecutivo dentro del rango autorizado por la
resolución, calcula el CUFE con el algoritmo publicado por la DIAN y arma el
payload completo.

Lo que **NO** hace es firmarlo digitalmente con el certificado de la empresa ni
transmitirlo a la DIAN. Eso corresponde a un proveedor tecnológico autorizado o
al servicio de facturación gratuita de la DIAN, y exige un certificado de firma
digital y la habilitación del emisor. El sistema deja ese punto resuelto
arquitectónicamente —ver `_PROVEEDORES` más abajo— pero **los documentos que
emite en modo «simulado» no tienen validez fiscal**.

Decirlo así importa: un sistema que aparenta emitir facturas válidas y no lo
hace expone a la empresa a una sanción.

DOS DOCUMENTOS DISTINTOS
------------------------
    Documento equivalente POS  → venta a consumidor final, sin identificar
    Factura electrónica de venta → exige identificar al adquiriente

El cajero elige en el momento del cobro. Por defecto es POS, porque pedir
cédula y correo en cada café haría inoperante el mostrador.

Rutas
  GET  /api/facturacion/catalogos
  GET  /api/facturacion/clientes            listado y búsqueda
  GET  /api/facturacion/clientes/buscar     por número de documento (POS)
  POST /api/facturacion/clientes            alta
  PUT  /api/facturacion/clientes/{id}
  GET  /api/facturacion/dv                  calcula el dígito de verificación
  GET  /api/facturacion/config              resolución vigente
  PUT  /api/facturacion/config
  GET  /api/facturacion/documentos          documentos emitidos
  GET  /api/facturacion/documentos/{id}
  POST /api/facturacion/documentos/{id}/transmitir

Autor: Arquitectura de Software · Unidad 1
================================================================
"""
from __future__ import annotations

import datetime
import hashlib
import json
import logging
import re

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from db import anio_actual, ahora, q, q1, run, run_sin_commit, serial, siguiente_consecutivo
from dependencias import get_tenant_db
from seguridad import require_rol, verify_token

log = logging.getLogger("cafeteria.facturacion")
router = APIRouter(tags=["Facturación electrónica"])

TIPO_POS = "pos"
TIPO_FACTURA = "factura"

_DOC_OK = re.compile(r"^[0-9A-Za-z\-]{4,24}$")
_EMAIL_OK = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


# ══════════════════════════════════════════════════════════════════════
#  DÍGITO DE VERIFICACIÓN DEL NIT
# ══════════════════════════════════════════════════════════════════════
# Pesos definidos por la DIAN. Se aplican de derecha a izquierda sobre el
# número de identificación.
_PESOS_DV = (3, 7, 13, 17, 19, 23, 29, 37, 41, 43, 47, 53, 59, 67, 71)


def calcular_dv(numero: str) -> int:
    """Dígito de verificación de un NIT colombiano.

    Se calcula, no se digita. Pedirlo al usuario introduce un error de tecleo
    que la DIAN rechaza y que nadie sabe interpretar cuando ocurre.
    """
    digitos = re.sub(r"\D", "", numero or "")
    if not digitos:
        raise ValueError("El número de identificación no tiene dígitos")
    if len(digitos) > len(_PESOS_DV):
        raise ValueError("El número de identificación excede la longitud admitida")

    suma = sum(int(d) * p for d, p in zip(reversed(digitos), _PESOS_DV))
    resto = suma % 11
    return resto if resto < 2 else 11 - resto


@router.get("/api/facturacion/dv")
def dv_endpoint(numero: str, cur: dict = Depends(verify_token)):
    """Lo consume el formulario para llenar el campo mientras se escribe."""
    try:
        return {"ok": True, "dv": calcular_dv(numero)}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


# ══════════════════════════════════════════════════════════════════════
#  CATÁLOGOS
# ══════════════════════════════════════════════════════════════════════
@router.get("/api/facturacion/catalogos")
def catalogos(cur: dict = Depends(verify_token), db: Session = Depends(get_tenant_db)):
    return {
        "ok": True,
        "tipos_doc": serial(q(db, "SELECT codigo, nombre, sigla, usa_dv FROM cat_tipos_doc_id "
                                  "WHERE activo=1 ORDER BY orden, nombre")),
        "responsabilidades": serial(q(db, "SELECT codigo, nombre FROM cat_responsabilidades "
                                          "WHERE activo=1 ORDER BY orden")),
        "tipos_persona": [{"key": "natural", "label": "Persona natural"},
                          {"key": "juridica", "label": "Persona jurídica"}],
        "formas_pago": [{"codigo": "1", "label": "Contado"},
                        {"codigo": "2", "label": "Crédito"}],
    }


# ══════════════════════════════════════════════════════════════════════
#  ADQUIRIENTES
# ══════════════════════════════════════════════════════════════════════
def _validar_cliente(db: Session, datos: dict, cliente_id: int | None = None) -> dict:
    """Valida y normaliza los datos del adquiriente.

    Se hace aquí y no en el frontend porque el mismo cliente puede crearse desde
    el cobro, desde el maestro o desde una importación: la regla debe vivir en un
    solo lugar y ser inevitable.
    """
    tipo_doc = (datos.get("tipo_doc") or "13").strip()
    numero = re.sub(r"[.\s]", "", (datos.get("numero_doc") or "")).strip()
    razon = (datos.get("razon_social") or "").strip()
    email = (datos.get("email") or "").strip().lower()

    fila_tipo = q1(db, "SELECT codigo, nombre, usa_dv FROM cat_tipos_doc_id WHERE codigo=:c",
                   {"c": tipo_doc})
    if not fila_tipo:
        raise HTTPException(400, f"Tipo de documento desconocido: {tipo_doc}")
    if not _DOC_OK.match(numero):
        raise HTTPException(400, "El número de documento no tiene un formato válido")
    if not razon:
        raise HTTPException(400, "El nombre o razón social es obligatorio")

    # El correo es obligatorio: la factura electrónica se ENTREGA por ese medio.
    # Sin él, el documento se emite pero el adquiriente nunca lo recibe, y la
    # entrega es parte de la obligación, no un extra.
    if not email:
        raise HTTPException(400, "El correo electrónico es obligatorio para la factura electrónica")
    if not _EMAIL_OK.match(email):
        raise HTTPException(400, f"El correo «{email}» no tiene un formato válido")

    resp = (datos.get("responsabilidad") or "R-99-PN").strip()
    if not q1(db, "SELECT codigo FROM cat_responsabilidades WHERE codigo=:c", {"c": resp}):
        raise HTTPException(400, f"Responsabilidad fiscal desconocida: {resp}")

    # DV: se calcula siempre que el tipo lo use; lo que envíe el cliente se ignora.
    dv = None
    if int(fila_tipo["usa_dv"] or 0):
        try:
            dv = str(calcular_dv(numero))
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    duplicado = q1(db, "SELECT id FROM clientes WHERE tipo_doc=:t AND numero_doc=:n",
                   {"t": tipo_doc, "n": numero})
    if duplicado and (cliente_id is None or int(duplicado["id"]) != int(cliente_id)):
        raise HTTPException(409, f"Ya existe un cliente con el documento {numero}")

    return {
        "tipo_persona": (datos.get("tipo_persona") or "natural").strip(),
        "tipo_doc": tipo_doc, "numero_doc": numero, "dv": dv,
        # Se guarda un solo campo de nombre. La DIAN admite «razón social» tanto
        # para persona jurídica como para natural; desglosar en cuatro campos
        # (dos nombres, dos apellidos) obligaría al cajero a partir el nombre
        # correctamente en el mostrador, y ese dato se digita mal más veces de
        # las que aporta. Si un cliente exige el desglose, se agrega el campo.
        "razon_social": razon[:200],
        "email": email[:160],
        "telefono": (datos.get("telefono") or "").strip()[:40] or None,
        "direccion": (datos.get("direccion") or "").strip()[:200] or None,
        "ciudad": (datos.get("ciudad") or "").strip()[:120] or None,
        "departamento": (datos.get("departamento") or "").strip()[:120] or None,
        "pais": (datos.get("pais") or "CO").strip()[:4],
        "responsabilidad": resp,
    }


def obtener_o_crear_cliente(db: Session, datos: dict) -> int:
    """Devuelve el id del adquiriente, creándolo si aún no existe.

    La llama el módulo de Caja durante el cobro. Que el cajero no tenga que
    decidir «¿ya está registrado?» es lo que hace usable la facturación en el
    mostrador.
    """
    if datos.get("cliente_id"):
        cid = int(datos["cliente_id"])
        if not q1(db, "SELECT id FROM clientes WHERE id=:i AND activo=1", {"i": cid}):
            raise HTTPException(404, "El cliente indicado no existe")
        return cid

    numero = re.sub(r"[.\s]", "", (datos.get("numero_doc") or "")).strip()
    tipo_doc = (datos.get("tipo_doc") or "13").strip()
    existente = q1(db, "SELECT id FROM clientes WHERE tipo_doc=:t AND numero_doc=:n",
                   {"t": tipo_doc, "n": numero})
    if existente:
        return int(existente["id"])

    limpio = _validar_cliente(db, datos)
    cols = ", ".join(limpio.keys())
    ph = ", ".join(f":{k}" for k in limpio)
    limpio_ts = dict(limpio, ts=ahora())
    res = run_sin_commit(db, f"INSERT INTO clientes ({cols}, activo, creado_en) "
                             f"VALUES ({ph}, 1, :ts)", limpio_ts)
    return int(res.lastrowid or 0)


@router.get("/api/facturacion/clientes")
def clientes_listar(buscar: str = "", limite: int = 100,
                    cur: dict = Depends(verify_token),
                    db: Session = Depends(get_tenant_db)):
    limite = max(1, min(int(limite or 100), 300))
    where, params = ["activo = 1"], {"l": limite}
    if buscar:
        where.append("(numero_doc LIKE :b OR razon_social LIKE :b OR email LIKE :b)")
        params["b"] = f"%{buscar.strip()}%"
    filas = serial(q(db, "SELECT * FROM clientes WHERE " + " AND ".join(where) +
                         " ORDER BY razon_social LIMIT :l", params))
    return {"ok": True, "items": filas, "total": len(filas)}


@router.get("/api/facturacion/clientes/buscar")
def cliente_buscar(numero: str, cur: dict = Depends(verify_token),
                   db: Session = Depends(get_tenant_db)):
    """Búsqueda exacta por documento. La usa el cobro para autocompletar en
    cuanto el cajero termina de digitar la cédula."""
    limpio = re.sub(r"[.\s]", "", numero or "").strip()
    if not limpio:
        return {"ok": True, "encontrado": False}
    fila = q1(db, "SELECT * FROM clientes WHERE numero_doc=:n AND activo=1", {"n": limpio})
    return {"ok": True, "encontrado": bool(fila),
            "cliente": serial(dict(fila))[0] if fila else None}


@router.post("/api/facturacion/clientes", status_code=201)
def cliente_crear(body: dict = Body(...),
                  cur: dict = Depends(require_rol("admin", "supervisor", "cajero")),
                  db: Session = Depends(get_tenant_db)):
    limpio = _validar_cliente(db, body)
    cols = ", ".join(limpio.keys())
    ph = ", ".join(f":{k}" for k in limpio)
    res = run(db, f"INSERT INTO clientes ({cols}, activo, creado_en) VALUES ({ph}, 1, :ts)",
              dict(limpio, ts=ahora()))
    return {"ok": True, "id": getattr(res, "lastrowid", 0), "dv": limpio["dv"]}


@router.put("/api/facturacion/clientes/{cid}")
def cliente_editar(cid: int, body: dict = Body(...),
                   cur: dict = Depends(require_rol("admin", "supervisor")),
                   db: Session = Depends(get_tenant_db)):
    actual = q1(db, "SELECT * FROM clientes WHERE id=:i", {"i": cid})
    if not actual:
        raise HTTPException(404, "Cliente no encontrado")
    fusion = dict(actual)
    fusion.update({k: v for k, v in body.items() if v is not None})
    limpio = _validar_cliente(db, fusion, cliente_id=cid)
    sets = ", ".join(f"{k}=:{k}" for k in limpio)
    run(db, f"UPDATE clientes SET {sets} WHERE id=:id", dict(limpio, id=cid))
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════
#  RESOLUCIÓN DE FACTURACIÓN
# ══════════════════════════════════════════════════════════════════════
def config_actual(db: Session) -> dict:
    fila = q1(db, "SELECT * FROM facturacion_config WHERE id = 1")
    return dict(fila) if fila else {}


@router.get("/api/facturacion/config")
def config_ver(cur: dict = Depends(require_rol("admin", "supervisor")),
               db: Session = Depends(get_tenant_db)):
    cfg = config_actual(db)
    usados = q1(db, "SELECT COUNT(*) AS n FROM documentos_dian WHERE tipo='factura'") or {}
    consumidos = int(usados.get("n") or 0)
    desde = int(cfg.get("rango_desde") or 1)
    hasta = int(cfg.get("rango_hasta") or 0)
    disponibles = max(0, hasta - desde + 1 - consumidos)

    return {"ok": True, "config": serial(cfg)[0] if cfg else None,
            "rango": {"consumidos": consumidos, "disponibles": disponibles,
                      # Aviso temprano: quedarse sin numeración detiene la
                      # facturación hasta que la DIAN autorice un rango nuevo,
                      # y ese trámite no es inmediato.
                      "alerta": disponibles < 100},
            "advertencia": _advertencia_ambiente(cfg)}


@router.put("/api/facturacion/config")
def config_guardar(body: dict = Body(...), cur: dict = Depends(require_rol("admin")),
                   db: Session = Depends(get_tenant_db)):
    campos = ("emisor_razon", "emisor_nit", "emisor_email", "emisor_direccion",
              "emisor_ciudad", "emisor_resp", "resolucion", "fecha_resolucion",
              "prefijo", "rango_desde", "rango_hasta", "clave_tecnica",
              "ambiente", "proveedor")
    datos = {k: body[k] for k in campos if k in body}
    if not datos:
        return {"ok": True, "sin_cambios": True}

    if "rango_desde" in datos and "rango_hasta" in datos:
        if int(datos["rango_hasta"]) < int(datos["rango_desde"]):
            raise HTTPException(400, "El rango final no puede ser menor que el inicial")
    if datos.get("ambiente") not in (None, "pruebas", "produccion"):
        raise HTTPException(400, "El ambiente debe ser «pruebas» o «produccion»")

    if datos.get("emisor_nit"):
        try:
            datos["emisor_dv"] = str(calcular_dv(datos["emisor_nit"]))
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    sets = ", ".join(f"{k}=:{k}" for k in datos)
    run(db, f"UPDATE facturacion_config SET {sets}, actualizado_en=:ts WHERE id=1",
        dict(datos, ts=ahora()))
    return {"ok": True, "advertencia": _advertencia_ambiente(config_actual(db))}


def _advertencia_ambiente(cfg: dict) -> str | None:
    """Aviso permanente mientras el sistema no esté habilitado de verdad."""
    if not cfg:
        return "No hay resolución de facturación configurada."
    if (cfg.get("proveedor") or "simulado") == "simulado":
        return ("Modo SIMULADO: los documentos se generan completos pero NO se firman "
                "digitalmente ni se transmiten a la DIAN. No tienen validez fiscal. "
                "Para emitir con validez debe configurarse un proveedor tecnológico "
                "autorizado y el certificado de firma digital.")
    if (cfg.get("ambiente") or "pruebas") == "pruebas":
        return "Ambiente de PRUEBAS (habilitación). Los documentos no tienen validez fiscal."
    return None


# ══════════════════════════════════════════════════════════════════════
#  GENERACIÓN DEL DOCUMENTO
# ══════════════════════════════════════════════════════════════════════
def _cufe(datos: dict, clave_tecnica: str) -> str:
    """Código Único de Factura Electrónica, según el algoritmo de la DIAN.

    Es el SHA-384 de la concatenación de número, fecha, hora, valores, impuestos,
    NIT del emisor, documento del adquiriente, clave técnica y ambiente.

    Se implementa con la estructura real por valor didáctico y para que el
    payload quede completo, pero **sin la clave técnica que la DIAN entrega al
    habilitar al emisor, el resultado no coincide con el CUFE oficial**. Por eso
    el documento se marca como «simulado» mientras esa clave esté vacía.
    """
    cadena = (
        f"{datos['numero_full']}"
        f"{datos['fecha']}"
        f"{datos['hora']}"
        f"{datos['subtotal']:.2f}"
        f"01{datos['impuestos']:.2f}"   # 01 = IVA
        f"04{0:.2f}"                    # 04 = INC
        f"03{0:.2f}"                    # 03 = ICA
        f"{datos['total']:.2f}"
        f"{datos['nit_emisor']}"
        f"{datos['doc_adquiriente']}"
        f"{clave_tecnica or ''}"
        f"{'1' if datos['ambiente'] == 'produccion' else '2'}"
    )
    return hashlib.sha384(cadena.encode("utf-8")).hexdigest()


def preparar_documento(db: Session, *, venta_id: int, cliente_id: int | None,
                       tipo: str, medio_pago: str = "10",
                       forma_pago: str = "1") -> dict:
    """Construye el documento electrónico de una venta. NO hace commit.

    La llama el módulo de Caja al cerrar la venta. Si es POS, se numera con la
    serie interna; si es factura, consume el rango autorizado por la resolución.
    """
    venta = q1(db, "SELECT * FROM ventas WHERE id=:i", {"i": venta_id})
    if not venta:
        raise HTTPException(404, "Venta no encontrada")

    cfg = config_actual(db)
    ambiente = cfg.get("ambiente") or "pruebas"
    prefijo = (cfg.get("prefijo") or "SETP") if tipo == TIPO_FACTURA else "POS"

    if tipo == TIPO_FACTURA:
        if not cliente_id:
            raise HTTPException(400, "La factura electrónica exige identificar al adquiriente")
        desde = int(cfg.get("rango_desde") or 1)
        hasta = int(cfg.get("rango_hasta") or 0)
        numero = desde - 1 + siguiente_consecutivo(db, "factura", anio_actual())
        if hasta and numero > hasta:
            # Detener aquí es lo correcto: emitir fuera del rango produce un
            # documento que la DIAN rechaza y que ya consumió el consecutivo.
            raise HTTPException(
                409, f"Se agotó el rango autorizado por la resolución ({desde}-{hasta}). "
                     f"Solicite una nueva resolución antes de seguir facturando.")
    else:
        numero = siguiente_consecutivo(db, "pos", anio_actual())

    numero_full = f"{prefijo}{numero}"
    cliente = (q1(db, "SELECT * FROM clientes WHERE id=:i", {"i": cliente_id})
               if cliente_id else None)

    ahora_dt = datetime.datetime.now(datetime.timezone.utc)
    base_cufe = {
        "numero_full": numero_full,
        "fecha": ahora_dt.strftime("%Y-%m-%d"),
        "hora": ahora_dt.strftime("%H:%M:%S-05:00"),
        "subtotal": float(venta["subtotal"] or 0),
        "impuestos": float(venta["impuestos"] or 0),
        "total": float(venta["total"] or 0),
        "nit_emisor": re.sub(r"\D", "", cfg.get("emisor_nit") or ""),
        "doc_adquiriente": (cliente or {}).get("numero_doc") or "222222222222",
        "ambiente": ambiente,
    }
    cufe = _cufe(base_cufe, cfg.get("clave_tecnica") or "")

    items = q(db, "SELECT nombre, cantidad, precio_unit, iva_pct, subtotal, impuesto, total "
                  "FROM venta_items WHERE venta_id=:v", {"v": venta_id})

    payload = {
        "tipo_documento": "01" if tipo == TIPO_FACTURA else "documento_equivalente_pos",
        "ambiente": ambiente,
        "numero": numero_full,
        "fecha_emision": base_cufe["fecha"],
        "hora_emision": base_cufe["hora"],
        "cufe": cufe,
        "moneda": "COP",
        "forma_pago": forma_pago,
        "medio_pago": medio_pago,
        "emisor": {
            "razon_social": cfg.get("emisor_razon"),
            "nit": cfg.get("emisor_nit"), "dv": cfg.get("emisor_dv"),
            "responsabilidad": cfg.get("emisor_resp"),
            "direccion": cfg.get("emisor_direccion"), "ciudad": cfg.get("emisor_ciudad"),
            "email": cfg.get("emisor_email"),
            "resolucion": cfg.get("resolucion"),
            "rango": f"{cfg.get('rango_desde')}-{cfg.get('rango_hasta')}",
        },
        "adquiriente": ({
            "tipo_persona": cliente["tipo_persona"], "tipo_doc": cliente["tipo_doc"],
            "numero_doc": cliente["numero_doc"], "dv": cliente["dv"],
            "razon_social": cliente["razon_social"], "email": cliente["email"],
            "telefono": cliente["telefono"], "direccion": cliente["direccion"],
            "ciudad": cliente["ciudad"], "departamento": cliente["departamento"],
            "pais": cliente["pais"], "responsabilidad": cliente["responsabilidad"],
        } if cliente else {"tipo_doc": "13", "numero_doc": "222222222222",
                           "razon_social": "Consumidor final"}),
        "items": serial([dict(i) for i in items]),
        "totales": {"subtotal": base_cufe["subtotal"],
                    "iva": base_cufe["impuestos"],
                    "total": base_cufe["total"]},
    }

    estado = "simulado" if (cfg.get("proveedor") or "simulado") == "simulado" else "pendiente"

    res = run_sin_commit(db,
                         "INSERT INTO documentos_dian (venta_id, cliente_id, tipo, prefijo, "
                         "numero, numero_full, cufe, forma_pago, medio_pago, subtotal, "
                         "impuestos, total, estado, payload, emitido_en) "
                         "VALUES (:v,:c,:t,:p,:n,:nf,:cufe,:fp,:mp,:sub,:imp,:tot,:est,:pl,:ts)",
                         {"v": venta_id, "c": cliente_id, "t": tipo, "p": prefijo,
                          "n": numero, "nf": numero_full, "cufe": cufe,
                          "fp": forma_pago, "mp": medio_pago,
                          "sub": base_cufe["subtotal"], "imp": base_cufe["impuestos"],
                          "tot": base_cufe["total"], "est": estado,
                          "pl": json.dumps(payload, ensure_ascii=False, default=str),
                          "ts": ahora()})

    log.info("Documento %s %s generado para la venta %s", tipo, numero_full, venta_id)

    # ── Entrega al adquiriente ────────────────────────────────────────
    # Solo la FACTURA se envía: el equivalente POS es para consumidor final y
    # no hay a quién mandárselo. El correo del adquiriente es obligatorio para
    # facturar; pedirlo y no usarlo era pedirle un dato al cliente para nada.
    #
    # Va al final y fuera de cualquier decisión de negocio: `enviar()` nunca
    # lanza, así que un fallo de correo no puede deshacer un documento ya
    # emitido y numerado. Si no sale, queda el motivo en el registro.
    if tipo == TIPO_FACTURA and cliente and (cliente.get("email") or "").strip():
        import correo

        propina = q1(db, "SELECT propina FROM ventas WHERE id=:v", {"v": venta_id}) or {}
        enviado = correo.factura_emitida(
            {"numero": numero_full, "cufe": cufe, "estado": estado,
             "subtotal": base_cufe["subtotal"], "impuestos": base_cufe["impuestos"],
             "total": base_cufe["total"], "propina": propina.get("propina") or 0,
             "items": serial([dict(i) for i in items])},
            dict(cliente), payload["emisor"])
        if not enviado:
            log.warning("Documento %s: el correo a %s NO salió · %s",
                        numero_full, cliente.get("email"), correo.ultimo_error())

    return {"id": int(res.lastrowid or 0), "tipo": tipo, "numero": numero_full,
            "cufe": cufe, "estado": estado}


# ══════════════════════════════════════════════════════════════════════
#  TRANSMISIÓN — punto de extensión (patrón Estrategia)
# ══════════════════════════════════════════════════════════════════════
def _transmitir_simulado(documento: dict, cfg: dict) -> dict:
    """Proveedor de prueba. No sale de la máquina."""
    return {"exito": True, "estado": "simulado",
            "mensaje": "Documento generado en modo simulado. NO fue firmado ni "
                       "transmitido a la DIAN; carece de validez fiscal."}


# Registro de proveedores. Integrar uno real —Facture, Carvajal, Siigo, el
# servicio gratuito de la DIAN— es escribir su función y añadirla aquí. Ningún
# otro archivo cambia: ni Caja ni Contabilidad conocen al proveedor.
_PROVEEDORES = {
    "simulado": _transmitir_simulado,
}


@router.post("/api/facturacion/documentos/{did}/transmitir")
def transmitir(did: int, cur: dict = Depends(require_rol("admin", "supervisor")),
               db: Session = Depends(get_tenant_db)):
    doc = q1(db, "SELECT * FROM documentos_dian WHERE id=:i", {"i": did})
    if not doc:
        raise HTTPException(404, "Documento no encontrado")
    if doc["estado"] == "aceptado":
        raise HTTPException(409, "El documento ya fue aceptado por la DIAN")

    cfg = config_actual(db)
    nombre = cfg.get("proveedor") or "simulado"
    proveedor = _PROVEEDORES.get(nombre)
    if not proveedor:
        raise HTTPException(501, f"El proveedor «{nombre}» no está integrado en este sistema")

    resultado = proveedor(dict(doc), cfg)
    run(db, "UPDATE documentos_dian SET estado=:e, mensaje=:m WHERE id=:i",
        {"e": resultado.get("estado", "error"), "m": resultado.get("mensaje"), "i": did})
    return {"ok": resultado.get("exito", False), **resultado}


# ══════════════════════════════════════════════════════════════════════
#  CONSULTA
# ══════════════════════════════════════════════════════════════════════
@router.get("/api/facturacion/documentos")
def documentos(tipo: str = "", limite: int = 100, cur: dict = Depends(verify_token),
               db: Session = Depends(get_tenant_db)):
    limite = max(1, min(int(limite or 100), 500))
    where, params = ["1=1"], {"l": limite}
    if tipo:
        where.append("d.tipo = :t"); params["t"] = tipo

    # La propina viaja con el documento aunque NO sea base gravable: se cobró
    # en la misma transacción y quien cuadra la caja necesita ver el mismo
    # total que el cliente pagó. Omitirla obligaba a cruzar dos pantallas para
    # explicar una diferencia que no es una diferencia.
    filas = serial(q(db, "SELECT d.*, v.folio, v.propina, v.ts AS venta_ts, "
                         "       COALESCE(c.razon_social,'Consumidor final') AS cliente, "
                         "       c.numero_doc, c.email "
                         "FROM documentos_dian d "
                         "JOIN ventas v ON v.id = d.venta_id "
                         "LEFT JOIN clientes c ON c.id = d.cliente_id "
                         "WHERE " + " AND ".join(where) +
                         " ORDER BY d.id DESC LIMIT :l", params))
    return {"ok": True, "items": filas,
            "kpis": {"total": len(filas),
                     "facturas": sum(1 for f in filas if f["tipo"] == TIPO_FACTURA),
                     "pos": sum(1 for f in filas if f["tipo"] == TIPO_POS),
                     "valor": round(sum(float(f["total"] or 0) for f in filas), 2),
                     "propinas": round(sum(float(f.get("propina") or 0)
                                           for f in filas), 2)}}


@router.get("/api/facturacion/documentos/{did}")
def documento_detalle(did: int, cur: dict = Depends(verify_token),
                      db: Session = Depends(get_tenant_db)):
    doc = q1(db, "SELECT * FROM documentos_dian WHERE id=:i", {"i": did})
    if not doc:
        raise HTTPException(404, "Documento no encontrado")
    salida = serial(dict(doc))[0]
    try:
        salida["payload"] = json.loads(salida.get("payload") or "{}")
    except Exception:
        salida["payload"] = {}
    return {"ok": True, "documento": salida}
