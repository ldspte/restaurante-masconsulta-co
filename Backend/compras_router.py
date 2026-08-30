# -*- coding: utf-8 -*-
"""
================================================================
  RESTAURANTE · Módulo COMPRAS
================================================================
Maestro de proveedores y órdenes de compra, con REPOSICIÓN AUTOMÁTICA.

LA REPOSICIÓN AUTOMÁTICA ES EL VALOR DEL MÓDULO
-----------------------------------------------
Un restaurante no se queda sin harina por falta de dinero: se queda sin harina
porque nadie miró el estante. El sistema ya sabe cuánto hay, cuál es el mínimo
y quién es el proveedor preferido de cada insumo; con eso puede proponer la
orden solo.

    inventario.bajo_minimo ──▶ [BUS] ──▶ genera orden SUGERIDA
                                          agrupada por proveedor

Se genera SUGERIDA, no emitida. Comprar es un compromiso de dinero y debe
autorizarlo una persona: un sistema que emite órdenes solo termina generando
compras que nadie pidió.

Cantidad a pedir = stock_max − stock_actual. Pedir solo hasta el mínimo dejaría
el insumo en el punto de reorden y la orden se repetiría al día siguiente.

Rutas
  GET/POST/PUT  /api/compras/proveedores
  GET/POST      /api/compras/proveedores/{id}/insumos
  GET           /api/compras/sugerencias        qué habría que reponer hoy
  POST          /api/compras/generar-automatica
  GET/POST      /api/compras/ordenes
  POST          /api/compras/ordenes/{id}/emitir
  POST          /api/compras/ordenes/{id}/recibir

Autor: Arquitectura de Software · Unidad 1
================================================================
"""
from __future__ import annotations

import datetime
import logging

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from db import anio_actual, ahora, q, q1, run, run_sin_commit, serial, siguiente_consecutivo
from dependencias import get_tenant_db
from seguridad import autor, require_rol, verify_token

log = logging.getLogger("restaurante.compras")
router = APIRouter(tags=["Compras"])

ROLES_COMPRAS = ("admin", "gerente", "bodega")

ESTADOS_OC = {
    "sugerida": "Sugerida por el sistema",
    "emitida": "Emitida al proveedor",
    "recibida_parcial": "Recibida parcialmente",
    "recibida": "Recibida completa",
    "anulada": "Anulada",
}


# ══════════════════════════════════════════════════════════════════════
#  PROVEEDORES
# ══════════════════════════════════════════════════════════════════════
@router.get("/api/compras/proveedores")
def proveedores_listar(cur: dict = Depends(verify_token), db: Session = Depends(get_tenant_db)):
    filas = serial(q(db, "SELECT p.*, "
                         "  (SELECT COUNT(*) FROM insumo_proveedor ip WHERE ip.proveedor_id=p.id) AS insumos, "
                         "  (SELECT COUNT(*) FROM ordenes_compra o WHERE o.proveedor_id=p.id "
                         "     AND o.estado IN ('sugerida','emitida')) AS ordenes_abiertas "
                         "FROM proveedores p WHERE p.activo=1 ORDER BY p.razon_social"))
    return {"ok": True, "items": filas, "total": len(filas)}


@router.post("/api/compras/proveedores", status_code=201)
def proveedor_crear(body: dict = Body(...), cur: dict = Depends(require_rol(*ROLES_COMPRAS)),
                    db: Session = Depends(get_tenant_db)):
    from facturacion_router import calcular_dv

    razon = (body.get("razon_social") or "").strip()
    if not razon:
        raise HTTPException(400, "La razón social es obligatoria")

    nit = (body.get("nit") or "").strip() or None
    dv = None
    if nit:
        if q1(db, "SELECT id FROM proveedores WHERE nit=:n AND activo=1", {"n": nit}):
            raise HTTPException(409, f"Ya existe un proveedor con el NIT {nit}")
        try:
            dv = str(calcular_dv(nit))
        except ValueError:
            dv = None

    res = run(db, "INSERT INTO proveedores (nit, dv, razon_social, contacto, email, telefono, "
                  "direccion, ciudad, dias_entrega, condicion_pago, activo, creado_en) "
                  "VALUES (:nit,:dv,:r,:c,:e,:t,:d,:ci,:de,:cp,1,:ts)",
              {"nit": nit, "dv": dv, "r": razon, "c": body.get("contacto"),
               "e": body.get("email"), "t": body.get("telefono"),
               "d": body.get("direccion"), "ci": body.get("ciudad"),
               "de": int(body.get("dias_entrega") or 2),
               "cp": body.get("condicion_pago") or "Contado", "ts": ahora()})
    return {"ok": True, "id": getattr(res, "lastrowid", 0), "dv": dv}


@router.put("/api/compras/proveedores/{pid}")
def proveedor_editar(pid: int, body: dict = Body(...),
                     cur: dict = Depends(require_rol(*ROLES_COMPRAS)),
                     db: Session = Depends(get_tenant_db)):
    if not q1(db, "SELECT id FROM proveedores WHERE id=:i", {"i": pid}):
        raise HTTPException(404, "Proveedor no encontrado")
    campos = {k: body[k] for k in ("razon_social", "contacto", "email", "telefono",
                                   "direccion", "ciudad", "dias_entrega",
                                   "condicion_pago", "activo") if k in body}
    if not campos:
        return {"ok": True, "sin_cambios": True}
    sets = ", ".join(f"{k}=:{k}" for k in campos)
    run(db, f"UPDATE proveedores SET {sets} WHERE id=:id", dict(campos, id=pid))
    return {"ok": True}


@router.get("/api/compras/proveedores/{pid}/insumos")
def proveedor_insumos(pid: int, cur: dict = Depends(verify_token),
                      db: Session = Depends(get_tenant_db)):
    filas = serial(q(db, "SELECT ip.*, i.codigo, i.nombre, i.stock, i.stock_min, "
                         "       COALESCE(u.nombre,'') AS unidad "
                         "FROM insumo_proveedor ip JOIN insumos i ON i.id=ip.insumo_id "
                         "LEFT JOIN cat_unidades u ON u.id=i.unidad_id "
                         "WHERE ip.proveedor_id=:p ORDER BY i.nombre", {"p": pid}))
    return {"ok": True, "items": filas}


@router.post("/api/compras/proveedores/{pid}/insumos", status_code=201)
def proveedor_insumo_asignar(pid: int, body: dict = Body(...),
                             cur: dict = Depends(require_rol(*ROLES_COMPRAS)),
                             db: Session = Depends(get_tenant_db)):
    """Asocia un insumo a un proveedor con su precio.

    Marcar `preferido` desmarca a los demás para ese insumo: la reposición
    automática necesita UN destinatario inequívoco, no una lista de candidatos.
    """
    insumo_id = int(body.get("insumo_id") or 0)
    if not q1(db, "SELECT id FROM insumos WHERE id=:i", {"i": insumo_id}):
        raise HTTPException(404, "Insumo no encontrado")

    preferido = int(bool(body.get("preferido")))
    if preferido:
        run(db, "UPDATE insumo_proveedor SET preferido=0 WHERE insumo_id=:i", {"i": insumo_id})

    run(db, "INSERT INTO insumo_proveedor (insumo_id, proveedor_id, precio, cantidad_min, "
            "preferido) VALUES (:i,:p,:pr,:cm,:pf) "
            "ON DUPLICATE KEY UPDATE precio=VALUES(precio), "
            "cantidad_min=VALUES(cantidad_min), preferido=VALUES(preferido)",
        {"i": insumo_id, "p": pid, "pr": float(body.get("precio") or 0),
         "cm": float(body.get("cantidad_min") or 1), "pf": preferido})
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════
#  REPOSICIÓN AUTOMÁTICA
# ══════════════════════════════════════════════════════════════════════
def calcular_sugerencias(db: Session) -> list[dict]:
    """Insumos en o por debajo del mínimo, con su proveedor y cantidad a pedir.

    Excluye los insumos PRODUCIDOS internamente: el pan no se compra, se hornea.
    Su reposición es una orden de producción, no una orden de compra.
    """
    filas = q(db,
              "SELECT i.id, i.codigo, i.nombre, i.stock, i.stock_min, i.stock_max, "
              "       i.costo_prom, COALESCE(u.nombre,'') AS unidad, "
              "       ip.proveedor_id, ip.precio, ip.cantidad_min, "
              "       p.razon_social AS proveedor, p.dias_entrega "
              "FROM insumos i "
              "LEFT JOIN cat_unidades u ON u.id = i.unidad_id "
              "LEFT JOIN insumo_proveedor ip ON ip.insumo_id = i.id AND ip.preferido = 1 "
              "LEFT JOIN proveedores p ON p.id = ip.proveedor_id AND p.activo = 1 "
              "WHERE i.activo = 1 AND i.es_producido = 0 AND i.stock <= i.stock_min "
              "ORDER BY p.razon_social, i.nombre")

    sugerencias = []
    for f in serial(filas):
        stock = float(f["stock"] or 0)
        maximo = float(f["stock_max"] or 0)
        minimo = float(f["stock_min"] or 0)
        # Reponer hasta el MÁXIMO. Pedir solo hasta el mínimo dejaría el insumo
        # en el punto de reorden y la sugerencia volvería a salir mañana.
        objetivo = maximo if maximo > minimo else minimo * 3
        cantidad = max(objetivo - stock, float(f.get("cantidad_min") or 1))
        precio = float(f.get("precio") or f.get("costo_prom") or 0)

        f["cantidad_sugerida"] = round(cantidad, 4)
        f["costo_estimado"] = round(cantidad * precio, 2)
        f["precio_unit"] = precio
        f["urgencia"] = "agotado" if stock <= 0 else "bajo"
        f["sin_proveedor"] = not f.get("proveedor_id")
        sugerencias.append(f)
    return sugerencias


@router.get("/api/compras/sugerencias")
def sugerencias(cur: dict = Depends(require_rol(*ROLES_COMPRAS)),
                db: Session = Depends(get_tenant_db)):
    items = calcular_sugerencias(db)
    huerfanos = [s for s in items if s["sin_proveedor"]]
    return {"ok": True, "items": items,
            "kpis": {"total": len(items),
                     "agotados": sum(1 for s in items if s["urgencia"] == "agotado"),
                     "sin_proveedor": len(huerfanos),
                     "costo_estimado": round(sum(s["costo_estimado"] for s in items), 2)},
            # Un insumo bajo mínimo sin proveedor preferido no se puede reponer
            # solo: hay que decirlo, no dejarlo caer en silencio.
            "advertencia": (f"{len(huerfanos)} insumo(s) bajo el mínimo no tienen proveedor "
                            f"preferido asignado y quedarán fuera de la orden automática."
                            if huerfanos else None)}


@router.post("/api/compras/generar-automatica", status_code=201)
def generar_automatica(cur: dict = Depends(require_rol(*ROLES_COMPRAS)),
                       db: Session = Depends(get_tenant_db)):
    """Crea órdenes SUGERIDAS agrupadas por proveedor.

    Agrupar importa: tres órdenes al mismo proveedor el mismo día son tres
    fletes y tres facturas por conciliar.
    """
    items = [s for s in calcular_sugerencias(db) if not s["sin_proveedor"]]
    if not items:
        return {"ok": True, "generadas": 0,
                "mensaje": "No hay insumos bajo el mínimo con proveedor asignado."}

    por_proveedor: dict[int, list] = {}
    for s in items:
        por_proveedor.setdefault(int(s["proveedor_id"]), []).append(s)

    anio = anio_actual()
    creadas = []
    try:
        for proveedor_id, lineas in por_proveedor.items():
            # No duplicar: si ya hay una sugerida abierta para ese proveedor, se
            # deja como está. De lo contrario cada visita a la pantalla crearía
            # otra orden idéntica.
            abierta = q1(db, "SELECT numero FROM ordenes_compra WHERE proveedor_id=:p "
                             "AND estado='sugerida'", {"p": proveedor_id})
            if abierta:
                continue

            numero = f"OC-{anio}-{siguiente_consecutivo(db, 'oc', anio):05d}"
            subtotal = round(sum(l["costo_estimado"] for l in lineas), 2)
            res = run_sin_commit(db,
                                 "INSERT INTO ordenes_compra (numero, proveedor_id, estado, "
                                 "automatica, subtotal, creada_en, creada_por, notas) "
                                 "VALUES (:n,:p,'sugerida',1,:s,:ts,:u,:no)",
                                 {"n": numero, "p": proveedor_id, "s": subtotal,
                                  "ts": ahora(), "u": autor(cur),
                                  "no": "Generada automáticamente por nivel de existencias"})
            oc_id = int(res.lastrowid or 0)
            for l in lineas:
                run_sin_commit(db,
                               "INSERT INTO oc_items (oc_id, insumo_id, nombre, cantidad, "
                               "precio_unit) VALUES (:o,:i,:n,:q,:p)",
                               {"o": oc_id, "i": l["id"], "n": l["nombre"],
                                "q": l["cantidad_sugerida"], "p": l["precio_unit"]})
            creadas.append({"numero": numero, "proveedor": lineas[0]["proveedor"],
                            "lineas": len(lineas), "subtotal": subtotal})
        db.commit()
    except Exception:
        db.rollback()
        raise

    log.info("Reposición automática: %s orden(es) sugeridas", len(creadas))
    return {"ok": True, "generadas": len(creadas), "ordenes": creadas}


# ══════════════════════════════════════════════════════════════════════
#  ÓRDENES DE COMPRA
# ══════════════════════════════════════════════════════════════════════
@router.get("/api/compras/ordenes")
def ordenes_listar(estado: str = "", cur: dict = Depends(verify_token),
                   db: Session = Depends(get_tenant_db)):
    where, params = ["1=1"], {}
    if estado:
        where.append("o.estado = :e"); params["e"] = estado
    filas = serial(q(db, "SELECT o.*, p.razon_social AS proveedor, p.email, p.telefono, "
                         "  (SELECT COUNT(*) FROM oc_items x WHERE x.oc_id=o.id) AS lineas "
                         "FROM ordenes_compra o JOIN proveedores p ON p.id=o.proveedor_id "
                         "WHERE " + " AND ".join(where) +
                         " ORDER BY o.id DESC LIMIT 200", params))
    return {"ok": True, "items": filas, "estados": ESTADOS_OC,
            "kpis": {"total": len(filas),
                     "sugeridas": sum(1 for f in filas if f["estado"] == "sugerida"),
                     "emitidas": sum(1 for f in filas if f["estado"] == "emitida"),
                     "valor_abierto": round(sum(float(f["subtotal"] or 0) for f in filas
                                                if f["estado"] in ("sugerida", "emitida")), 2)}}


@router.get("/api/compras/ordenes/{oid}")
def orden_detalle(oid: int, cur: dict = Depends(verify_token),
                  db: Session = Depends(get_tenant_db)):
    orden = q1(db, "SELECT o.*, p.razon_social AS proveedor, p.email, p.telefono, "
                   "p.condicion_pago, p.dias_entrega "
                   "FROM ordenes_compra o JOIN proveedores p ON p.id=o.proveedor_id "
                   "WHERE o.id=:i", {"i": oid})
    if not orden:
        raise HTTPException(404, "Orden no encontrada")
    items = serial(q(db, "SELECT x.*, i.codigo, i.stock, COALESCE(u.nombre,'') AS unidad "
                         "FROM oc_items x JOIN insumos i ON i.id=x.insumo_id "
                         "LEFT JOIN cat_unidades u ON u.id=i.unidad_id "
                         "WHERE x.oc_id=:o ORDER BY x.id", {"o": oid}))
    return {"ok": True, "orden": serial(dict(orden))[0], "items": items}


@router.post("/api/compras/ordenes", status_code=201)
def orden_crear(body: dict = Body(...), cur: dict = Depends(require_rol(*ROLES_COMPRAS)),
                db: Session = Depends(get_tenant_db)):
    """Orden manual, para lo que no cabe en la reposición automática."""
    proveedor_id = int(body.get("proveedor_id") or 0)
    if not q1(db, "SELECT id FROM proveedores WHERE id=:i AND activo=1", {"i": proveedor_id}):
        raise HTTPException(404, "Proveedor no encontrado")
    entradas = body.get("items") or []
    if not entradas:
        raise HTTPException(400, "La orden no tiene líneas")

    anio = anio_actual()
    try:
        numero = f"OC-{anio}-{siguiente_consecutivo(db, 'oc', anio):05d}"
        res = run_sin_commit(db, "INSERT INTO ordenes_compra (numero, proveedor_id, estado, "
                                 "automatica, subtotal, creada_en, creada_por, notas) "
                                 "VALUES (:n,:p,'sugerida',0,0,:ts,:u,:no)",
                             {"n": numero, "p": proveedor_id, "ts": ahora(),
                              "u": autor(cur), "no": body.get("notas")})
        oc_id = int(res.lastrowid or 0)
        subtotal = 0.0
        for it in entradas:
            insumo = q1(db, "SELECT id, nombre FROM insumos WHERE id=:i",
                        {"i": int(it.get("insumo_id") or 0)})
            if not insumo:
                raise HTTPException(400, f"Insumo {it.get('insumo_id')} no encontrado")
            cant = float(it.get("cantidad") or 0)
            precio = float(it.get("precio_unit") or 0)
            if cant <= 0:
                raise HTTPException(400, "Las cantidades deben ser mayores que cero")
            subtotal += cant * precio
            run_sin_commit(db, "INSERT INTO oc_items (oc_id, insumo_id, nombre, cantidad, "
                               "precio_unit) VALUES (:o,:i,:n,:q,:p)",
                           {"o": oc_id, "i": insumo["id"], "n": insumo["nombre"],
                            "q": cant, "p": precio})
        run_sin_commit(db, "UPDATE ordenes_compra SET subtotal=:s WHERE id=:i",
                       {"s": round(subtotal, 2), "i": oc_id})
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True, "id": oc_id, "numero": numero, "subtotal": round(subtotal, 2)}


@router.post("/api/compras/ordenes/{oid}/emitir")
def orden_emitir(oid: int, cur: dict = Depends(require_rol("admin", "gerente")),
                 db: Session = Depends(get_tenant_db)):
    """Autoriza la orden. Es la frontera entre sugerencia y compromiso de dinero,
    y por eso la restringe a administración: bodega propone, gerencia autoriza."""
    orden = q1(db, "SELECT * FROM ordenes_compra WHERE id=:i", {"i": oid})
    if not orden:
        raise HTTPException(404, "Orden no encontrada")
    if orden["estado"] != "sugerida":
        raise HTTPException(409, f"La orden está en estado «{orden['estado']}»")
    run(db, "UPDATE ordenes_compra SET estado='emitida', emitida_en=:ts WHERE id=:i",
        {"ts": ahora(), "i": oid})
    return {"ok": True, "numero": orden["numero"]}


@router.post("/api/compras/ordenes/{oid}/recibir")
def orden_recibir(oid: int, body: dict = Body(...),
                  cur: dict = Depends(require_rol(*ROLES_COMPRAS)),
                  db: Session = Depends(get_tenant_db)):
    """Recibe mercancía: registra la entrada en el kardex y la contabiliza.

    Admite recepción PARCIAL, que es lo normal: el proveedor manda ocho de los
    diez bultos y el resto queda pendiente. Forzar «todo o nada» obligaría al
    almacén a mentir para poder guardar.
    """
    from eventos import Evento, TipoEvento, publicar
    from inventario_router import mover

    orden = q1(db, "SELECT * FROM ordenes_compra WHERE id=:i", {"i": oid})
    if not orden:
        raise HTTPException(404, "Orden no encontrada")
    if orden["estado"] in ("recibida", "anulada"):
        raise HTTPException(409, f"La orden está en estado «{orden['estado']}»")

    recepciones = body.get("items") or []
    if not recepciones:
        raise HTTPException(400, "Indique qué cantidades se recibieron")

    recibido_total = 0.0
    try:
        for r in recepciones:
            item = q1(db, "SELECT * FROM oc_items WHERE id=:i AND oc_id=:o",
                      {"i": int(r.get("item_id") or 0), "o": oid})
            if not item:
                continue
            cant = float(r.get("cantidad") or 0)
            if cant <= 0:
                continue
            pendiente = float(item["cantidad"]) - float(item["recibido"])
            if cant > pendiente + 1e-6:
                raise HTTPException(
                    400, f"De «{item['nombre']}» quedan {pendiente:g} por recibir "
                         f"y se indicaron {cant:g}.")

            precio = float(r.get("precio_unit") or item["precio_unit"] or 0)
            resultado = mover(db, insumo_id=int(item["insumo_id"]), tipo="entrada",
                              cantidad=cant, costo_unit=precio, ref_tipo="compra",
                              ref_id=oid, motivo=f"Recepción {orden['numero']}",
                              usuario=autor(cur))
            run_sin_commit(db, "UPDATE oc_items SET recibido = recibido + :q WHERE id=:i",
                           {"q": cant, "i": item["id"]})
            recibido_total += resultado["costo_total"]

        # ¿Quedó completa?
        pend = q1(db, "SELECT COUNT(*) AS n FROM oc_items WHERE oc_id=:o "
                      "AND recibido < cantidad - 0.0001", {"o": oid})
        completa = not int((pend or {}).get("n") or 0)
        run_sin_commit(db, "UPDATE ordenes_compra SET estado=:e, recibida_en=:ts WHERE id=:i",
                       {"e": "recibida" if completa else "recibida_parcial",
                        "ts": ahora() if completa else None, "i": oid})

        if recibido_total > 0:
            publicar(db, Evento(
                tipo=TipoEvento.INVENTARIO_ENTRADA, entidad="orden_compra", entidad_id=oid,
                payload={"costo_total": round(recibido_total, 2),
                         "insumo": f"Orden {orden['numero']}",
                         "contado": bool(body.get("contado", False))},
                usuario=autor(cur)))
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {"ok": True, "completa": completa, "valor_recibido": round(recibido_total, 2)}
