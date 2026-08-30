# -*- coding: utf-8 -*-
"""
================================================================
  RESTAURANTE · Módulo PRODUCCIÓN PROPIA
================================================================
Quién hace el pan, quién prepara la base de los jugos. La producción interna es
el eslabón que falta en casi todo POS de restaurante y sin el cual el costeo
miente.

    Harina + levadura ──(orden de producción)──▶ Pan ──(receta)──▶ Plato vendido

Dos tipos de receta, deliberadamente distintos:

  · Receta de VENTA (`receta`)         qué consume un producto al venderse
  · Ficha de PRODUCCIÓN (`fichas_...`) qué consume un insumo al fabricarse

Sin el segundo, el pan tendría que darse de alta como una compra ficticia y el
costo real de la panadería —incluida la mano de obra— se perdería.

EL COSTO DE LO PRODUCIDO INCLUYE MANO DE OBRA
---------------------------------------------
El pan no cuesta solo la harina: cuesta también las tres horas del panadero. La
orden permite imputar ese costo, y el promedio ponderado del insumo producido
lo absorbe. Ignorarlo haría ver la panadería propia como gratis frente a
comprarle a un proveedor, que es exactamente la decisión que el dueño necesita
comparar bien.

Rutas
  GET/POST/PUT  /api/produccion/fichas
  GET/POST      /api/produccion/ordenes
  POST          /api/produccion/ordenes/{id}/iniciar
  POST          /api/produccion/ordenes/{id}/terminar

Autor: Arquitectura de Software · Unidad 1
================================================================
"""
from __future__ import annotations

import datetime

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from db import anio_actual, ahora, q, q1, run, run_sin_commit, serial, siguiente_consecutivo
from dependencias import get_tenant_db
from eventos import Evento, TipoEvento, publicar
from seguridad import autor, require_rol, verify_token

router = APIRouter(tags=["Producción"])

ROLES_PROD = ("admin", "gerente", "cocina", "bodega")


# ══════════════════════════════════════════════════════════════════════
#  FICHAS TÉCNICAS
# ══════════════════════════════════════════════════════════════════════
def costo_ficha(db: Session, ficha_id: int) -> dict:
    """Costo del lote y costo unitario según el rendimiento declarado."""
    ficha = q1(db, "SELECT * FROM fichas_produccion WHERE id=:i", {"i": ficha_id})
    if not ficha:
        raise HTTPException(404, "Ficha no encontrada")
    fila = q1(db, "SELECT COALESCE(SUM(fi.cantidad * i.costo_prom),0) AS c "
                  "FROM ficha_ingredientes fi JOIN insumos i ON i.id=fi.insumo_id "
                  "WHERE fi.ficha_id=:f", {"f": ficha_id})
    lote = round(float((fila or {}).get("c") or 0), 2)
    rendimiento = float(ficha["rendimiento"] or 1) or 1
    return {"costo_lote": lote, "rendimiento": rendimiento,
            "costo_unitario": round(lote / rendimiento, 4)}


@router.get("/api/produccion/fichas")
def fichas_listar(cur: dict = Depends(verify_token), db: Session = Depends(get_tenant_db)):
    filas = serial(q(db, "SELECT f.*, i.codigo AS destino_codigo, i.nombre AS destino, "
                         "       i.stock AS stock_destino, "
                         "       COALESCE(u.nombre,'') AS unidad, "
                         "       COALESCE(e.nombre,'Sin estación') AS estacion, "
                         "       COALESCE(e.color,'#94a3b8') AS estacion_color, "
                         "  (SELECT COUNT(*) FROM ficha_ingredientes x WHERE x.ficha_id=f.id) AS ingredientes "
                         "FROM fichas_produccion f "
                         "JOIN insumos i ON i.id=f.insumo_destino "
                         "LEFT JOIN cat_unidades u ON u.id=i.unidad_id "
                         "LEFT JOIN estaciones e ON e.id=f.estacion_id "
                         "WHERE f.activo=1 ORDER BY f.nombre"))
    for f in filas:
        f.update(costo_ficha(db, int(f["id"])))
    return {"ok": True, "items": filas}


@router.get("/api/produccion/fichas/{fid}")
def ficha_detalle(fid: int, cur: dict = Depends(verify_token),
                  db: Session = Depends(get_tenant_db)):
    ficha = q1(db, "SELECT f.*, i.nombre AS destino FROM fichas_produccion f "
                   "JOIN insumos i ON i.id=f.insumo_destino WHERE f.id=:i", {"i": fid})
    if not ficha:
        raise HTTPException(404, "Ficha no encontrada")
    ingredientes = serial(q(db, "SELECT fi.*, i.codigo, i.nombre, i.stock, i.costo_prom, "
                                "COALESCE(u.nombre,'') AS unidad, "
                                "ROUND(fi.cantidad * i.costo_prom, 2) AS costo_linea "
                                "FROM ficha_ingredientes fi JOIN insumos i ON i.id=fi.insumo_id "
                                "LEFT JOIN cat_unidades u ON u.id=i.unidad_id "
                                "WHERE fi.ficha_id=:f ORDER BY i.nombre", {"f": fid}))
    return {"ok": True, "ficha": serial(dict(ficha))[0], "ingredientes": ingredientes,
            **costo_ficha(db, fid)}


@router.post("/api/produccion/fichas", status_code=201)
def ficha_crear(body: dict = Body(...), cur: dict = Depends(require_rol("admin", "gerente", "cocina")),
                db: Session = Depends(get_tenant_db)):
    destino = int(body.get("insumo_destino") or 0)
    insumo = q1(db, "SELECT id, es_producido FROM insumos WHERE id=:i", {"i": destino})
    if not insumo:
        raise HTTPException(404, "El insumo de destino no existe")
    if not (body.get("nombre") or "").strip():
        raise HTTPException(400, "El nombre de la ficha es obligatorio")
    if float(body.get("rendimiento") or 0) <= 0:
        raise HTTPException(400, "El rendimiento debe ser mayor que cero")

    # Marcar el destino como producido: es lo que lo excluye de la reposición
    # automática por compra. Sin esta marca, el sistema pediría pan al proveedor.
    if not int(insumo["es_producido"] or 0):
        run(db, "UPDATE insumos SET es_producido=1 WHERE id=:i", {"i": destino})

    res = run(db, "INSERT INTO fichas_produccion (insumo_destino, nombre, estacion_id, "
                  "rendimiento, minutos, instrucciones, activo) VALUES (:d,:n,:e,:r,:m,:ins,1)",
              {"d": destino, "n": body["nombre"], "e": body.get("estacion_id") or None,
               "r": float(body["rendimiento"]), "m": int(body.get("minutos") or 30),
               "ins": body.get("instrucciones")})
    fid = int(getattr(res, "lastrowid", 0) or 0)
    if body.get("ingredientes"):
        _guardar_ingredientes(db, fid, body["ingredientes"])
    return {"ok": True, "id": fid}


@router.put("/api/produccion/fichas/{fid}")
def ficha_editar(fid: int, body: dict = Body(...),
                 cur: dict = Depends(require_rol("admin", "gerente", "cocina")),
                 db: Session = Depends(get_tenant_db)):
    if not q1(db, "SELECT id FROM fichas_produccion WHERE id=:i", {"i": fid}):
        raise HTTPException(404, "Ficha no encontrada")
    campos = {k: body[k] for k in ("nombre", "estacion_id", "rendimiento", "minutos",
                                   "instrucciones", "activo") if k in body}
    if campos:
        sets = ", ".join(f"{k}=:{k}" for k in campos)
        run(db, f"UPDATE fichas_produccion SET {sets} WHERE id=:id", dict(campos, id=fid))
    if "ingredientes" in body:
        _guardar_ingredientes(db, fid, body["ingredientes"])
    return {"ok": True, **costo_ficha(db, fid)}


def _guardar_ingredientes(db: Session, fid: int, items: list) -> None:
    """Reemplaza la lista completa. Es trivialmente correcto: no hay forma de
    dejar un ingrediente huérfano que el usuario creyó haber borrado."""
    limpios, vistos = [], set()
    for it in items or []:
        iid = int(it.get("insumo_id") or 0)
        cant = float(it.get("cantidad") or 0)
        if not iid or cant <= 0:
            continue
        if iid in vistos:
            raise HTTPException(400, "La ficha tiene el mismo insumo repetido")
        if not q1(db, "SELECT id FROM insumos WHERE id=:i AND activo=1", {"i": iid}):
            raise HTTPException(400, f"El insumo {iid} no existe o está inactivo")
        vistos.add(iid)
        limpios.append((iid, cant))

    run(db, "DELETE FROM ficha_ingredientes WHERE ficha_id=:f", {"f": fid})
    for iid, cant in limpios:
        run(db, "INSERT INTO ficha_ingredientes (ficha_id, insumo_id, cantidad) "
                "VALUES (:f,:i,:q)", {"f": fid, "i": iid, "q": cant})


# ══════════════════════════════════════════════════════════════════════
#  ÓRDENES DE PRODUCCIÓN
# ══════════════════════════════════════════════════════════════════════
@router.get("/api/produccion/ordenes")
def ordenes_listar(estado: str = "", cur: dict = Depends(verify_token),
                   db: Session = Depends(get_tenant_db)):
    where, params = ["1=1"], {}
    if estado:
        where.append("o.estado = :e"); params["e"] = estado
    filas = serial(q(db, "SELECT o.*, f.nombre AS ficha, i.nombre AS produce, "
                         "COALESCE(u.nombre,'') AS unidad, "
                         "COALESCE(e.nombre,'Sin estación') AS estacion "
                         "FROM ordenes_produccion o "
                         "JOIN fichas_produccion f ON f.id=o.ficha_id "
                         "JOIN insumos i ON i.id=f.insumo_destino "
                         "LEFT JOIN cat_unidades u ON u.id=i.unidad_id "
                         "LEFT JOIN estaciones e ON e.id=o.estacion_id "
                         "WHERE " + " AND ".join(where) +
                         " ORDER BY o.id DESC LIMIT 150", params))
    return {"ok": True, "items": filas,
            "kpis": {"programadas": sum(1 for f in filas if f["estado"] == "programada"),
                     "en_proceso": sum(1 for f in filas if f["estado"] == "en_proceso"),
                     "terminadas": sum(1 for f in filas if f["estado"] == "terminada"),
                     "costo_periodo": round(sum(float(f["costo_insumos"] or 0) +
                                                float(f["costo_mo"] or 0) for f in filas), 2)}}


@router.post("/api/produccion/ordenes", status_code=201)
def orden_crear(body: dict = Body(...), cur: dict = Depends(require_rol(*ROLES_PROD)),
                db: Session = Depends(get_tenant_db)):
    """Programa una producción. Verifica ANTES si alcanzan los ingredientes:
    enterarse a mitad de la horneada de que falta levadura no sirve de nada."""
    ficha = q1(db, "SELECT * FROM fichas_produccion WHERE id=:i AND activo=1",
               {"i": int(body.get("ficha_id") or 0)})
    if not ficha:
        raise HTTPException(404, "Ficha de producción no encontrada")
    lotes = float(body.get("lotes") or 1)
    if lotes <= 0:
        raise HTTPException(400, "Los lotes deben ser mayores que cero")

    faltantes = []
    for ing in q(db, "SELECT fi.cantidad, i.id, i.nombre, i.stock "
                     "FROM ficha_ingredientes fi JOIN insumos i ON i.id=fi.insumo_id "
                     "WHERE fi.ficha_id=:f", {"f": ficha["id"]}):
        requiere = float(ing["cantidad"]) * lotes
        if float(ing["stock"]) < requiere:
            faltantes.append({"insumo": ing["nombre"], "requiere": round(requiere, 3),
                              "disponible": float(ing["stock"])})
    if faltantes and not body.get("forzar"):
        detalle = "; ".join(f"{f['insumo']}: requiere {f['requiere']:g}, "
                            f"hay {f['disponible']:g}" for f in faltantes)
        raise HTTPException(409, f"No alcanzan los ingredientes. {detalle}")

    anio = anio_actual()
    numero = f"OP-{anio}-{siguiente_consecutivo(db, 'op', anio):05d}"
    res = run(db, "INSERT INTO ordenes_produccion (numero, ficha_id, lotes, estado, "
                  "responsable, estacion_id, programada_ts, notas) "
                  "VALUES (:n,:f,:l,'programada',:r,:e,:ts,:no)",
              {"n": numero, "f": ficha["id"], "l": lotes,
               "r": body.get("responsable") or autor(cur),
               "e": ficha.get("estacion_id"), "ts": ahora(), "no": body.get("notas")})
    return {"ok": True, "id": getattr(res, "lastrowid", 0), "numero": numero,
            "faltantes": faltantes,
            "cantidad_esperada": round(float(ficha["rendimiento"]) * lotes, 3)}


@router.post("/api/produccion/ordenes/{oid}/iniciar")
def orden_iniciar(oid: int, cur: dict = Depends(require_rol(*ROLES_PROD)),
                  db: Session = Depends(get_tenant_db)):
    orden = q1(db, "SELECT * FROM ordenes_produccion WHERE id=:i", {"i": oid})
    if not orden:
        raise HTTPException(404, "Orden no encontrada")
    if orden["estado"] != "programada":
        raise HTTPException(409, f"La orden está en estado «{orden['estado']}»")
    run(db, "UPDATE ordenes_produccion SET estado='en_proceso', iniciada_ts=:ts, "
            "responsable=:r WHERE id=:i", {"ts": ahora(), "r": autor(cur), "i": oid})
    return {"ok": True}


@router.post("/api/produccion/ordenes/{oid}/terminar")
def orden_terminar(oid: int, body: dict = Body(...),
                   cur: dict = Depends(require_rol(*ROLES_PROD)),
                   db: Session = Depends(get_tenant_db)):
    """Cierra la producción: consume los ingredientes y da entrada al producido.

    La cantidad REAL puede diferir de la esperada —así es la panadería—, y esa
    diferencia se registra como merma de producción en lugar de disimularse.
    """
    from inventario_router import mover

    orden = q1(db, "SELECT * FROM ordenes_produccion WHERE id=:i", {"i": oid})
    if not orden:
        raise HTTPException(404, "Orden no encontrada")
    if orden["estado"] == "terminada":
        raise HTTPException(409, "La orden ya fue terminada")

    ficha = q1(db, "SELECT * FROM fichas_produccion WHERE id=:i", {"i": orden["ficha_id"]})
    lotes = float(orden["lotes"] or 1)
    esperada = float(ficha["rendimiento"] or 1) * lotes
    producida = float(body.get("cantidad_producida") if body.get("cantidad_producida")
                      is not None else esperada)
    if producida < 0:
        raise HTTPException(400, "La cantidad producida no puede ser negativa")
    costo_mo = float(body.get("costo_mano_obra") or 0)

    try:
        # 1· Consumir ingredientes
        costo_insumos = 0.0
        for ing in q(db, "SELECT fi.insumo_id, fi.cantidad FROM ficha_ingredientes fi "
                         "WHERE fi.ficha_id=:f", {"f": ficha["id"]}):
            consumo = float(ing["cantidad"]) * lotes
            r = mover(db, insumo_id=int(ing["insumo_id"]), tipo="salida", cantidad=consumo,
                      ref_tipo="produccion", ref_id=oid,
                      motivo=f"Producción {orden['numero']} · {ficha['nombre']}",
                      usuario=autor(cur), permitir_negativo=True)
            costo_insumos += r["costo_total"]

        # 2· Dar entrada a lo producido. Su costo unitario absorbe insumos y mano
        #    de obra: es lo que hace comparable «hacerlo» contra «comprarlo».
        costo_total = costo_insumos + costo_mo
        costo_unit = (costo_total / producida) if producida > 0 else 0.0
        if producida > 0:
            mover(db, insumo_id=int(ficha["insumo_destino"]), tipo="entrada",
                  cantidad=producida, costo_unit=costo_unit, ref_tipo="produccion",
                  ref_id=oid, motivo=f"Producción {orden['numero']}", usuario=autor(cur))

        merma = round(esperada - producida, 4)
        run_sin_commit(db, "UPDATE ordenes_produccion SET estado='terminada', "
                           "cantidad_prod=:c, merma=:m, costo_insumos=:ci, costo_mo=:cm, "
                           "terminada_ts=:ts WHERE id=:i",
                       {"c": producida, "m": max(0.0, merma), "ci": round(costo_insumos, 2),
                        "cm": costo_mo, "ts": ahora(), "i": oid})

        publicar(db, Evento(
            tipo=TipoEvento.PRODUCCION_TERMINADA, entidad="orden_produccion", entidad_id=oid,
            payload={"numero": orden["numero"], "producto": ficha["nombre"],
                     "cantidad": producida, "costo_insumos": round(costo_insumos, 2),
                     "costo_mo": costo_mo, "merma": max(0.0, merma)},
            usuario=autor(cur)))
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {"ok": True, "numero": orden["numero"], "cantidad_producida": producida,
            "esperada": esperada, "merma": max(0.0, merma),
            "costo_insumos": round(costo_insumos, 2), "costo_mano_obra": costo_mo,
            "costo_unitario": round(costo_unit, 4)}
