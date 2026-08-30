# -*- coding: utf-8 -*-
"""
================================================================
  RESTAURANTE · Módulo CAJA (punto de venta)
================================================================
Turnos de caja, registro de ventas, pagos mixtos, anulación y arqueo.

DOS DECISIONES QUE DEFINEN ESTE MÓDULO
--------------------------------------
1. **Los precios NUNCA vienen del cliente.** El navegador envía qué producto y
   cuántas unidades; el precio, el IVA y el costo los resuelve el servidor
   contra la base. Confiar en el precio que manda el frontend permitiría
   cobrarse un capuchino en un peso alterando una petición con las herramientas
   de desarrollo del navegador. Es la vulnerabilidad más común de un carrito.

2. **Toda venta es idempotente.** El cliente genera una `idem_key` por
   operación. Si la red se cae después de que el servidor grabó pero antes de
   que llegara la respuesta, el reintento devuelve la MISMA venta en vez de
   cobrar dos veces. En un punto de venta sobre wifi de local comercial esto no
   es un lujo: es la diferencia entre un arqueo que cuadra y uno que no.

Rutas
  GET    /api/caja/estado          turno abierto del usuario + catálogo
  POST   /api/caja/abrir           abre turno con base inicial
  POST   /api/caja/cerrar          arqueo y cierre
  GET    /api/caja/ventas          ventas del turno
  POST   /api/caja/ventas          registra una venta
  GET    /api/caja/ventas/{id}     detalle
  POST   /api/caja/ventas/{id}/anular

Autor: Arquitectura de Software · Unidad 1
================================================================
"""
from __future__ import annotations

import datetime
import logging

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from db import (ahora_local, anio_actual, ahora, q, q1, run, run_sin_commit, serial,
                siguiente_consecutivo)
from dependencias import get_tenant_db
from eventos import Evento, TipoEvento, publicar
from inventario_router import costo_receta_venta
from seguridad import autor, require_rol, verify_token

log = logging.getLogger("cafeteria.caja")
router = APIRouter(tags=["Caja"])

ROLES_CAJA = ("admin", "gerente", "cajero")


# ══════════════════════════════════════════════════════════════════════
#  TURNO DE CAJA
# ══════════════════════════════════════════════════════════════════════
def _caja_abierta(db: Session, usuario: str) -> dict | None:
    return q1(db, "SELECT * FROM cajas WHERE estado = 'abierta' "
                  "AND usuario_apertura = :u ORDER BY id DESC LIMIT 1", {"u": usuario})


@router.get("/api/caja/estado")
def estado(cur: dict = Depends(require_rol(*ROLES_CAJA)),
           db: Session = Depends(get_tenant_db)):
    """Estado del turno + todo lo necesario para pintar el POS en una sola
    petición. Encadenar tres llamadas al abrir la pantalla es latencia
    innecesaria en un dispositivo de mostrador."""
    caja = _caja_abierta(db, autor(cur))
    productos = serial(q(db,
                         "SELECT p.id, p.codigo, p.nombre, p.precio, p.iva_pct, p.emoji, "
                         "       COALESCE(c.nombre,'Sin categoría') AS categoria, "
                         "       COALESCE(c.color,'#94a3b8') AS color "
                         "FROM productos p LEFT JOIN cat_categorias c ON c.id = p.categoria_id "
                         "WHERE p.activo = 1 ORDER BY c.orden, p.nombre"))
    metodos = serial(q(db, "SELECT id, nombre, es_efectivo FROM cat_metodos_pago "
                           "WHERE activo = 1 ORDER BY id"))

    resumen = None
    if caja:
        resumen = q1(db,
                     "SELECT COUNT(*) AS n, COALESCE(SUM(total),0) AS total "
                     "FROM ventas WHERE caja_id = :c AND estado = 'pagada'",
                     {"c": caja["id"]})

    # El porcentaje SUGERIDO de propina viaja con el estado del POS. La caja lo
    # necesita para proponerlo al cobrar, y no puede quedar escrito en el
    # JavaScript: cada local fija el suyo y la ley 1935 de 2018 obliga a
    # informarlo al cliente.
    perfil = q1(db, "SELECT propina_pct FROM sede_perfil WHERE id=1") or {}

    return {"ok": True,
            "caja": serial(dict(caja))[0] if caja else None,
            "resumen": serial(dict(resumen))[0] if resumen else None,
            "productos": productos, "metodos_pago": metodos,
            "propina_pct": float(perfil.get("propina_pct") or 0)}


@router.post("/api/caja/abrir", status_code=201)
def abrir(body: dict = Body(...), cur: dict = Depends(require_rol(*ROLES_CAJA)),
          db: Session = Depends(get_tenant_db)):
    usuario = autor(cur)
    if _caja_abierta(db, usuario):
        raise HTTPException(409, "Ya tiene un turno de caja abierto. Ciérrelo primero.")
    base = float(body.get("base_inicial") or 0)
    if base < 0:
        raise HTTPException(400, "La base inicial no puede ser negativa")

    res = run(db, "INSERT INTO cajas (apertura_ts, usuario_apertura, base_inicial, estado) "
                  "VALUES (:ts, :u, :b, 'abierta')",
              {"ts": ahora(), "u": usuario, "b": base})
    return {"ok": True, "caja_id": getattr(res, "lastrowid", 0)}


@router.post("/api/caja/cerrar")
def cerrar(body: dict = Body(...), cur: dict = Depends(require_rol(*ROLES_CAJA)),
           db: Session = Depends(get_tenant_db)):
    """Arqueo. Compara el efectivo esperado con el contado y registra la
    diferencia. Se guarda aunque no cuadre: forzar el cuadre destruiría
    justamente la información que el arqueo existe para producir."""
    usuario = autor(cur)
    caja = _caja_abierta(db, usuario)
    if not caja:
        raise HTTPException(404, "No tiene ningún turno de caja abierto")

    contado = body.get("efectivo_contado")
    if contado is None:
        raise HTTPException(400, "Indique el efectivo contado")
    contado = float(contado)

    # Solo el efectivo se cuenta físicamente; las tarjetas se concilian con el
    # datáfono, no con el cajón.
    fila = q1(db,
              "SELECT COALESCE(SUM(pg.monto),0) AS efectivo "
              "FROM pagos pg JOIN ventas v ON v.id = pg.venta_id "
              "JOIN cat_metodos_pago m ON m.id = pg.metodo_id "
              "WHERE v.caja_id = :c AND v.estado = 'pagada' AND m.es_efectivo = 1",
              {"c": caja["id"]})
    efectivo_ventas = float((fila or {}).get("efectivo") or 0)

    tot = q1(db, "SELECT COUNT(*) AS n, COALESCE(SUM(total),0) AS total "
                 "FROM ventas WHERE caja_id = :c AND estado = 'pagada'",
             {"c": caja["id"]})
    esperado = round(float(caja["base_inicial"] or 0) + efectivo_ventas, 2)
    diferencia = round(contado - esperado, 2)

    run(db, "UPDATE cajas SET cierre_ts=:ts, usuario_cierre=:u, efectivo_esperado=:esp, "
            "efectivo_contado=:con, diferencia=:dif, total_ventas=:tv, num_ventas=:nv, "
            "observacion=:obs, estado='cerrada' WHERE id=:i",
        {"ts": ahora(), "u": usuario, "esp": esperado, "con": contado, "dif": diferencia,
         "tv": float(tot["total"] or 0), "nv": int(tot["n"] or 0),
         "obs": (body.get("observacion") or "").strip() or None, "i": caja["id"]})

    return {"ok": True, "arqueo": {
        "caja_id": caja["id"], "base_inicial": float(caja["base_inicial"] or 0),
        "efectivo_ventas": efectivo_ventas, "efectivo_esperado": esperado,
        "efectivo_contado": contado, "diferencia": diferencia,
        "num_ventas": int(tot["n"] or 0), "total_ventas": float(tot["total"] or 0),
        "estado_arqueo": "cuadrada" if abs(diferencia) < 0.01
                         else ("sobrante" if diferencia > 0 else "faltante")}}


@router.get("/api/caja/turnos")
def turnos(limite: int = 30, cur: dict = Depends(require_rol("admin", "gerente")),
           db: Session = Depends(get_tenant_db)):
    limite = max(1, min(int(limite or 30), 200))
    return {"ok": True,
            "items": serial(q(db, "SELECT * FROM cajas ORDER BY id DESC LIMIT :l",
                              {"l": limite}))}


# ══════════════════════════════════════════════════════════════════════
#  VENTAS
# ══════════════════════════════════════════════════════════════════════
@router.post("/api/caja/ventas", status_code=201)
def vender(body: dict = Body(...), cur: dict = Depends(require_rol(*ROLES_CAJA)),
           db: Session = Depends(get_tenant_db)):
    """Registra una venta completa de forma atómica.

    Secuencia: validar → calcular en el servidor → grabar venta, ítems y pagos
    → publicar `venta.registrada` → confirmar. El evento dispara el descuento
    de inventario y el asiento contable DENTRO de la misma transacción; si
    alguno falla, no queda ni la venta.
    """
    usuario = autor(cur)
    caja = _caja_abierta(db, usuario)
    if not caja:
        raise HTTPException(409, "Debe abrir un turno de caja antes de vender")

    # ── Idempotencia: si esta clave ya se procesó, devolver aquella venta ──
    idem = (body.get("idem_key") or "").strip()[:64] or None
    if idem:
        previa = q1(db, "SELECT id, folio, total FROM ventas WHERE idem_key = :k",
                    {"k": idem})
        if previa:
            log.info("Venta idempotente reutilizada: %s", previa["folio"])
            return {"ok": True, "duplicada": True, "venta_id": previa["id"],
                    "folio": previa["folio"], "total": float(previa["total"] or 0)}

    # Una venta puede nacer de una COMANDA del salón o directamente del POS
    # (mostrador, para llevar). En el primer caso las líneas se toman de la
    # comanda: volver a digitarlas invitaría a cobrar algo distinto de lo servido.
    comanda_id = body.get("comanda_id")
    comanda = None
    if comanda_id:
        comanda = q1(db, "SELECT * FROM comandas WHERE id=:i", {"i": int(comanda_id)})
        if not comanda:
            raise HTTPException(404, "Comanda no encontrada")
        if comanda["estado"] == "cerrada":
            raise HTTPException(409, "La comanda ya fue cobrada")
        items_in = [{"producto_id": r["producto_id"], "cantidad": float(r["cantidad"])}
                    for r in q(db, "SELECT producto_id, cantidad FROM comanda_items "
                                   "WHERE comanda_id=:c AND estado<>'anulado'",
                               {"c": int(comanda_id)})]
        if not items_in:
            raise HTTPException(409, "La comanda no tiene productos que cobrar")
    else:
        items_in = body.get("items") or []
    if not items_in:
        raise HTTPException(400, "La venta no tiene productos")

    # ── Cálculo del lado del servidor ──
    lineas, subtotal, impuestos, costo_total = [], 0.0, 0.0, 0.0
    for it in items_in:
        pid = int(it.get("producto_id") or 0)
        cant = float(it.get("cantidad") or 0)
        if cant <= 0:
            raise HTTPException(400, "Las cantidades deben ser mayores que cero")

        prod = q1(db, "SELECT id, nombre, precio, iva_pct FROM productos "
                      "WHERE id = :i AND activo = 1", {"i": pid})
        if not prod:
            raise HTTPException(400, f"El producto {pid} no existe o está inactivo")

        # El precio SIEMPRE sale de la base, nunca del cuerpo de la petición.
        precio = float(prod["precio"] or 0)
        iva_pct = float(prod["iva_pct"] or 0)
        linea_sub = round(precio * cant, 2)
        linea_iva = round(linea_sub * iva_pct / 100.0, 2)

        lineas.append({"producto_id": pid, "nombre": prod["nombre"], "cantidad": cant,
                       "precio_unit": precio, "iva_pct": iva_pct,
                       "subtotal": linea_sub, "impuesto": linea_iva,
                       "total": round(linea_sub + linea_iva, 2)})
        subtotal += linea_sub
        impuestos += linea_iva
        costo_total += costo_receta_venta(db, pid, cant)

    subtotal = round(subtotal, 2)
    impuestos = round(impuestos, 2)
    # La propina la cobra la caja junto con la cuenta, pero NO es ingreso de la
    # empresa: es dinero del personal. Suma al total a pagar y al efectivo del
    # arqueo, y se acredita a un pasivo (ver contabilidad_router).
    propina = round(float(body.get("propina") or 0), 2)
    if propina < 0:
        raise HTTPException(400, "La propina no puede ser negativa")
    total = round(subtotal + impuestos + propina, 2)
    costo_total = round(costo_total, 2)

    # ── Pagos: deben cubrir exactamente el total ──
    pagos_in = body.get("pagos") or [{"metodo_id": None, "monto": total}]
    pagos, suma_pagos = [], 0.0
    for pg in pagos_in:
        monto = round(float(pg.get("monto") or 0), 2)
        if monto <= 0:
            continue
        mid = pg.get("metodo_id")
        metodo = q1(db, "SELECT id, nombre, cuenta_puc, es_efectivo, codigo_dian "
                        "FROM cat_metodos_pago WHERE id = :i AND activo = 1",
                    {"i": mid}) if mid else None
        if not metodo:
            metodo = q1(db, "SELECT id, nombre, cuenta_puc, es_efectivo, codigo_dian "
                            "FROM cat_metodos_pago WHERE es_efectivo = 1 AND activo = 1 "
                            "ORDER BY id LIMIT 1")
        if not metodo:
            raise HTTPException(400, "No hay métodos de pago configurados")
        pagos.append({"metodo_id": metodo["id"], "metodo": metodo["nombre"],
                      "cuenta_puc": metodo["cuenta_puc"],
                      "es_efectivo": int(metodo["es_efectivo"] or 0),
                      "codigo_dian": metodo.get("codigo_dian") or "10",
                      "monto": monto, "referencia": (pg.get("referencia") or "")[:120]})
        suma_pagos += monto

    # Tolerancia de un centavo por el redondeo de los pagos mixtos; más que eso
    # es un error real que no debe grabarse.
    if abs(round(suma_pagos, 2) - total) > 0.01:
        raise HTTPException(
            400, f"Los pagos suman {suma_pagos:,.2f} y el total es {total:,.2f}.")

    anio = anio_actual()
    try:
        numero = siguiente_consecutivo(db, "venta", anio)
        folio = f"V-{anio}-{numero:05d}"

        # Adquiriente: si vienen datos de facturación, se resuelve o se crea.
        cliente_id = None
        if body.get("cliente_id") or body.get("cliente"):
            from facturacion_router import obtener_o_crear_cliente
            datos = body.get("cliente") or {}
            # El POS enviaba aqui un TEXTO libre («Juan Perez»). Al llegar como
            # cadena, `datos.get(...)` reventaba con AttributeError y el cobro
            # devolvia un 500 sin explicacion: el cajero perdia la venta por
            # escribir un nombre. Un dato de entrada mal formado tiene que
            # producir un mensaje, nunca un 500.
            if isinstance(datos, str):
                datos = {"razon_social": datos.strip()}
            if not isinstance(datos, dict):
                raise HTTPException(400, "El adquiriente debe enviarse como objeto")
            if body.get("cliente_id"):
                datos = dict(datos, cliente_id=body["cliente_id"])
            cliente_id = obtener_o_crear_cliente(db, datos)

        res = run_sin_commit(db,
                             "INSERT INTO ventas (folio, caja_id, comanda_id, ts, subtotal, "
                             "impuestos, propina, total, costo, estado, usuario, cliente_id, "
                             "idem_key) "
                             "VALUES (:f,:c,:com,:ts,:sub,:imp,:pro,:tot,:cos,'pagada',:u,:cli,:k)",
                             {"f": folio, "c": caja["id"],
                              "com": int(comanda_id) if comanda_id else None,
                              "ts": ahora(), "sub": subtotal, "imp": impuestos,
                              "pro": propina, "tot": total, "cos": costo_total,
                              "u": usuario, "cli": cliente_id, "k": idem})
        venta_id = int(res.lastrowid or 0)

        for ln in lineas:
            run_sin_commit(db,
                           "INSERT INTO venta_items (venta_id, producto_id, nombre, cantidad, "
                           "precio_unit, iva_pct, subtotal, impuesto, total) "
                           "VALUES (:v,:p,:n,:q,:pu,:iva,:sub,:imp,:tot)",
                           {"v": venta_id, "p": ln["producto_id"], "n": ln["nombre"],
                            "q": ln["cantidad"], "pu": ln["precio_unit"],
                            "iva": ln["iva_pct"], "sub": ln["subtotal"],
                            "imp": ln["impuesto"], "tot": ln["total"]})
        for pg in pagos:
            run_sin_commit(db,
                           "INSERT INTO pagos (venta_id, metodo_id, metodo, monto, referencia) "
                           "VALUES (:v,:mi,:m,:mo,:r)",
                           {"v": venta_id, "mi": pg["metodo_id"], "m": pg["metodo"],
                            "mo": pg["monto"], "r": pg["referencia"] or None})

        # Propina al pozo del personal
        if propina > 0:
            from personal_router import registrar_propina
            registrar_propina(db, venta_id=venta_id,
                              comanda_id=int(comanda_id) if comanda_id else None,
                              monto=propina,
                              medio=pagos[0]["metodo"] if pagos else "",
                              mesero=(comanda or {}).get("mesero") or usuario)

        # Cierra la comanda y deja la mesa por limpiar: cobrar y liberar son el
        # mismo gesto en el salón.
        if comanda:
            run_sin_commit(db, "UPDATE comandas SET estado='cerrada', cierre_ts=:ts, "
                               "venta_id=:v WHERE id=:i",
                           {"ts": ahora(), "v": venta_id, "i": comanda["id"]})
            if comanda.get("mesa_id"):
                run_sin_commit(db, "UPDATE mesas SET estado='limpieza', mesero=NULL, "
                                   "ocupada_ts=NULL WHERE id=:m", {"m": comanda["mesa_id"]})

        publicar(db, Evento(
            tipo=TipoEvento.VENTA_REGISTRADA, entidad="venta", entidad_id=venta_id,
            payload={"folio": folio, "items": lineas, "pagos": pagos,
                     "subtotal": subtotal, "impuestos": impuestos, "propina": propina,
                     "total": total, "costo": costo_total},
            usuario=usuario))

        # Documento electrónico: factura si se identificó al adquiriente,
        # documento equivalente POS si fue consumidor final.
        from facturacion_router import TIPO_FACTURA, TIPO_POS, preparar_documento
        documento = preparar_documento(
            db, venta_id=venta_id, cliente_id=cliente_id,
            tipo=TIPO_FACTURA if cliente_id else TIPO_POS,
            medio_pago=(pagos[0].get("codigo_dian") if pagos else "10") or "10")

        db.commit()
    except Exception:
        db.rollback()
        raise

    return {"ok": True, "venta_id": venta_id, "folio": folio, "subtotal": subtotal,
            "impuestos": impuestos, "propina": propina, "total": total,
            "costo": costo_total, "utilidad": round(subtotal - costo_total, 2),
            "documento": documento}


@router.get("/api/caja/ventas")
def ventas_listar(caja_id: int = 0, limite: int = 50,
                  cur: dict = Depends(require_rol(*ROLES_CAJA)),
                  db: Session = Depends(get_tenant_db)):
    limite = max(1, min(int(limite or 50), 500))
    if not caja_id:
        caja = _caja_abierta(db, autor(cur))
        caja_id = int(caja["id"]) if caja else 0

    filas = serial(q(db, "SELECT * FROM ventas WHERE caja_id = :c "
                         "ORDER BY id DESC LIMIT :l",
                     {"c": caja_id, "l": limite})) if caja_id else []
    return {"ok": True, "items": filas, "caja_id": caja_id}


@router.get("/api/caja/ventas/{vid}")
def venta_detalle(vid: int, cur: dict = Depends(require_rol(*ROLES_CAJA)),
                  db: Session = Depends(get_tenant_db)):
    venta = q1(db, "SELECT * FROM ventas WHERE id = :i", {"i": vid})
    if not venta:
        raise HTTPException(404, "Venta no encontrada")
    return {"ok": True,
            "venta": serial(dict(venta))[0],
            "items": serial(q(db, "SELECT * FROM venta_items WHERE venta_id = :v", {"v": vid})),
            "pagos": serial(q(db, "SELECT * FROM pagos WHERE venta_id = :v", {"v": vid}))}


@router.post("/api/caja/ventas/{vid}/anular")
def anular(vid: int, body: dict = Body(default={}),
           cur: dict = Depends(require_rol("admin", "gerente")),
           db: Session = Depends(get_tenant_db)):
    """Anula una venta: repone inventario y genera el asiento de reversa.

    Restringido a supervisor o administrador. Si el cajero pudiera anular sus
    propias ventas, podría cobrar en efectivo, anular y quedarse con el dinero
    sin que el arqueo lo detecte. Es el control interno más elemental de un POS.
    """
    venta = q1(db, "SELECT * FROM ventas WHERE id = :i", {"i": vid})
    if not venta:
        raise HTTPException(404, "Venta no encontrada")
    if venta["estado"] == "anulada":
        raise HTTPException(409, "La venta ya está anulada")

    motivo = (body.get("motivo") or "").strip()
    if not motivo:
        raise HTTPException(400, "Debe indicar el motivo de la anulación")

    usuario = autor(cur)
    try:
        run_sin_commit(db, "UPDATE ventas SET estado='anulada', anulada_ts=:ts, "
                           "anulada_por=:u WHERE id=:i",
                       {"ts": ahora(), "u": usuario, "i": vid})
        publicar(db, Evento(
            tipo=TipoEvento.VENTA_ANULADA, entidad="venta", entidad_id=vid,
            payload={"folio": venta["folio"], "total": float(venta["total"] or 0),
                     "subtotal": float(venta["subtotal"] or 0),
                     "impuestos": float(venta["impuestos"] or 0),
                     "costo": float(venta["costo"] or 0),
                     "propina": float(venta["propina"] or 0), "motivo": motivo},
            usuario=usuario))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True, "folio": venta["folio"]}
