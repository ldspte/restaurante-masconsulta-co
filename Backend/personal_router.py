# -*- coding: utf-8 -*-
"""
================================================================
  RESTAURANTE · Módulo PERSONAL — consumo interno y propinas
================================================================
Dos hechos que el POS típico maltrata y que aquí tienen tratamiento propio.

1· CONSUMO INTERNO (el desayuno del personal)
   No es venta —no hay ingreso— ni pérdida —no es desperdicio—: es un beneficio
   laboral. Registrarlo como venta a precio cero distorsiona el ticket promedio;
   registrarlo como merma dispara el indicador que vigila el desperdicio. Va a
   su propia cuenta de gasto (5165) y sale del inventario con su motivo.

2· PROPINAS
   En Colombia la propina es VOLUNTARIA y NO constituye salario. Mientras no se
   reparte, ese dinero NO es de la empresa: es un PASIVO con el personal
   (cuenta 2335). Registrarla como ingreso inflaría ventas, IVA y base de renta,
   y haría que la empresa tribute sobre plata ajena.

       Cobro con propina:   Caja 1105 (D)  →  Propinas por pagar 2335 (C)
       Reparto al personal: Propinas 2335 (D)  →  Caja 1105 (C)

Rutas
  GET/POST  /api/consumo                  consumo interno
  GET       /api/consumo/reporte
  GET       /api/propinas/pozo            propinas sin repartir
  POST      /api/propinas/repartos        calcula el reparto
  POST      /api/propinas/repartos/{id}/pagar

Autor: Arquitectura de Software · Unidad 1
================================================================
"""
from __future__ import annotations

import datetime

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from db import anio_actual, ahora, hoy, q, q1, run, run_sin_commit, serial, siguiente_consecutivo
from dependencias import get_tenant_db
from eventos import Evento, TipoEvento, publicar
from seguridad import autor, require_rol, verify_token

router = APIRouter(tags=["Personal"])

ROLES_CONSUMO = ("admin", "gerente", "cocina", "bodega")
ROLES_PROPINA = ("admin", "gerente", "cajero")

TIPOS_CONSUMO = ["desayuno", "almuerzo", "cena", "refrigerio", "capacitación", "cortesía"]


# ══════════════════════════════════════════════════════════════════════
#  CONSUMO INTERNO
# ══════════════════════════════════════════════════════════════════════
@router.get("/api/consumo")
def consumo_listar(desde: str = "", hasta: str = "", cur: dict = Depends(verify_token),
                   db: Session = Depends(get_tenant_db)):
    where, params = ["1=1"], {}
    if desde:
        where.append("c.ts >= :d"); params["d"] = desde
    if hasta:
        where.append("c.ts <= :h"); params["h"] = hasta + "T23:59:59"

    filas = serial(q(db, "SELECT c.*, p.codigo FROM consumo_interno c "
                         "JOIN productos p ON p.id=c.producto_id "
                         "WHERE " + " AND ".join(where) +
                         " ORDER BY c.id DESC LIMIT 300", params))
    return {"ok": True, "items": filas, "tipos": TIPOS_CONSUMO,
            "kpis": {"registros": len(filas),
                     "costo_total": round(sum(float(f["costo_total"] or 0) for f in filas), 2),
                     "raciones": round(sum(float(f["cantidad"] or 0) for f in filas), 2)}}


@router.post("/api/consumo", status_code=201)
def consumo_registrar(body: dict = Body(...), cur: dict = Depends(require_rol(*ROLES_CONSUMO)),
                      db: Session = Depends(get_tenant_db)):
    """Registra el consumo del personal.

    Descuenta los insumos de la receta igual que una venta, pero SIN generar
    ingreso: el plato se preparó y los insumos se fueron, aunque nadie pagó.
    """
    from inventario_router import costo_receta_venta, mover

    producto_id = int(body.get("producto_id") or 0)
    cantidad = float(body.get("cantidad") or 1)
    beneficiario = (body.get("beneficiario") or "").strip()

    if cantidad <= 0:
        raise HTTPException(400, "La cantidad debe ser mayor que cero")
    if not beneficiario:
        raise HTTPException(400, "Indique quién consume: el registro sin beneficiario "
                                 "no permite controlar el beneficio ni auditarlo")
    prod = q1(db, "SELECT id, nombre FROM productos WHERE id=:i AND activo=1",
              {"i": producto_id})
    if not prod:
        raise HTTPException(404, "Producto no encontrado")

    costo = costo_receta_venta(db, producto_id, cantidad)

    try:
        res = run_sin_commit(db,
                             "INSERT INTO consumo_interno (ts, empleado_id, beneficiario, "
                             "producto_id, nombre, cantidad, costo_total, tipo, observacion, "
                             "autorizado_por) VALUES (:ts,:e,:b,:p,:n,:q,:c,:t,:o,:a)",
                             {"ts": ahora(), "e": body.get("empleado_id") or None,
                              "b": beneficiario[:160], "p": producto_id, "n": prod["nombre"],
                              "q": cantidad, "c": costo,
                              "t": body.get("tipo") or "desayuno",
                              "o": body.get("observacion"), "a": autor(cur)})
        cid = int(res.lastrowid or 0)

        for linea in q(db, "SELECT insumo_id, cantidad FROM receta WHERE producto_id=:p",
                       {"p": producto_id}):
            mover(db, insumo_id=int(linea["insumo_id"]),
                  cantidad=float(linea["cantidad"]) * cantidad, tipo="salida",
                  ref_tipo="consumo", ref_id=cid,
                  motivo=f"Consumo interno · {beneficiario}",
                  usuario=autor(cur), permitir_negativo=True)

        publicar(db, Evento(
            tipo=TipoEvento.CONSUMO_INTERNO, entidad="consumo", entidad_id=cid,
            payload={"beneficiario": beneficiario, "producto": prod["nombre"],
                     "cantidad": cantidad, "costo_total": costo,
                     "tipo": body.get("tipo") or "desayuno"},
            usuario=autor(cur)))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True, "id": cid, "costo_total": costo}


@router.get("/api/consumo/reporte")
def consumo_reporte(desde: str = "", hasta: str = "",
                    cur: dict = Depends(require_rol("admin", "gerente")),
                    db: Session = Depends(get_tenant_db)):
    """Costo del beneficio por persona y por tipo.

    Es un dato de gestión de personal, no solo contable: permite saber cuánto
    cuesta realmente alimentar al equipo y compararlo con lo presupuestado.
    """
    where, params = ["1=1"], {}
    if desde:
        where.append("ts >= :d"); params["d"] = desde
    if hasta:
        where.append("ts <= :h"); params["h"] = hasta + "T23:59:59"
    clausula = " AND ".join(where)

    por_persona = serial(q(db, f"SELECT beneficiario, COUNT(*) AS n, "
                               f"ROUND(SUM(costo_total),2) AS costo "
                               f"FROM consumo_interno WHERE {clausula} "
                               f"GROUP BY beneficiario ORDER BY costo DESC", params))
    por_tipo = serial(q(db, f"SELECT tipo, COUNT(*) AS n, ROUND(SUM(costo_total),2) AS costo "
                            f"FROM consumo_interno WHERE {clausula} "
                            f"GROUP BY tipo ORDER BY costo DESC", params))
    total = round(sum(float(p["costo"] or 0) for p in por_tipo), 2)
    return {"ok": True, "por_persona": por_persona, "por_tipo": por_tipo, "total": total,
            "promedio_persona": round(total / len(por_persona), 2) if por_persona else 0}


# ══════════════════════════════════════════════════════════════════════
#  PROPINAS
# ══════════════════════════════════════════════════════════════════════
def registrar_propina(db: Session, *, venta_id: int, comanda_id: int | None,
                      monto: float, medio: str, mesero: str) -> int:
    """Registra la propina recibida. NO hace commit — la llama la caja dentro de
    la transacción de la venta."""
    res = run_sin_commit(db, "INSERT INTO propinas (venta_id, comanda_id, ts, monto, "
                             "medio, mesero, distribuida) VALUES (:v,:c,:ts,:m,:me,:mes,0)",
                         {"v": venta_id, "c": comanda_id, "ts": ahora(),
                          "m": round(float(monto), 2), "me": medio, "mes": mesero})
    return int(res.lastrowid or 0)


@router.get("/api/propinas/pozo")
def pozo(cur: dict = Depends(require_rol(*ROLES_PROPINA)),
         db: Session = Depends(get_tenant_db)):
    """Propinas recibidas y todavía no repartidas.

    Es dinero del personal en poder de la empresa: el saldo debe coincidir con
    la cuenta 2335 del balance. Que no coincida significa que se repartió algo
    sin registrar, o al revés.
    """
    pendiente = q1(db, "SELECT COUNT(*) AS n, COALESCE(SUM(monto),0) AS total, "
                       "MIN(ts) AS desde FROM propinas WHERE distribuida=0") or {}
    por_mesero = serial(q(db, "SELECT COALESCE(mesero,'(sin asignar)') AS mesero, "
                              "COUNT(*) AS n, ROUND(SUM(monto),2) AS total "
                              "FROM propinas WHERE distribuida=0 "
                              "GROUP BY mesero ORDER BY total DESC"))
    repartos = serial(q(db, "SELECT * FROM repartos_propina ORDER BY id DESC LIMIT 20"))

    empleados = serial(q(db, "SELECT id, CONCAT(nombres,' ',apellidos) AS nombre, cargo, "
                             "puntos_propina FROM empleados WHERE activo=1 "
                             "AND puntos_propina > 0 ORDER BY nombres"))
    return {"ok": True,
            "pozo": {"registros": int(pendiente.get("n") or 0),
                     "total": round(float(pendiente.get("total") or 0), 2),
                     "desde": pendiente.get("desde")},
            "por_mesero": por_mesero, "repartos": repartos, "empleados": empleados}


@router.post("/api/propinas/repartos", status_code=201)
def reparto_calcular(body: dict = Body(...), cur: dict = Depends(require_rol("admin", "gerente")),
                     db: Session = Depends(get_tenant_db)):
    """Calcula el reparto del pozo entre el personal, por puntos.

    El sistema de puntos es el que usan los restaurantes: un mesero suma más que
    un auxiliar de cocina porque atiende directamente, pero la cocina participa
    —hizo el plato—. Los puntos son configurables por empleado; el criterio lo
    define el acuerdo con el personal, no el software.

    Se crea en BORRADOR: nadie reparte dinero sin revisar primero el cálculo.
    """
    desde = (body.get("desde") or "").strip()
    hasta = (body.get("hasta") or hoy()).strip()
    if not desde:
        raise HTTPException(400, "Indique la fecha inicial del período")

    fila = q1(db, "SELECT COALESCE(SUM(monto),0) AS total, COUNT(*) AS n FROM propinas "
                  "WHERE distribuida=0 AND ts >= :d AND ts <= :h",
              {"d": desde, "h": hasta + "T23:59:59"})
    total = round(float((fila or {}).get("total") or 0), 2)
    if total <= 0:
        raise HTTPException(409, "No hay propinas pendientes de repartir en ese período")

    participantes = body.get("participantes")
    if not participantes:
        participantes = [{"empleado_id": e["id"], "nombre": e["nombre"],
                          "puntos": float(e["puntos_propina"] or 1)}
                         for e in q(db, "SELECT id, CONCAT(nombres,' ',apellidos) AS nombre, "
                                        "puntos_propina FROM empleados WHERE activo=1 "
                                        "AND puntos_propina > 0")]
    if not participantes:
        raise HTTPException(409, "No hay empleados activos con puntos de propina asignados")

    puntos_total = sum(float(p.get("puntos") or 0) for p in participantes)
    if puntos_total <= 0:
        raise HTTPException(400, "La suma de puntos debe ser mayor que cero")

    anio = anio_actual()
    numero = f"RP-{anio}-{siguiente_consecutivo(db, 'reparto', anio):04d}"
    try:
        res = run_sin_commit(db, "INSERT INTO repartos_propina (numero, desde, hasta, total, "
                                 "criterio, estado, creado_por, creado_en) "
                                 "VALUES (:n,:d,:h,:t,'puntos','borrador',:u,:ts)",
                             {"n": numero, "d": desde, "h": hasta, "t": total,
                              "u": autor(cur), "ts": ahora()})
        rid = int(res.lastrowid or 0)

        detalle, asignado = [], 0.0
        for i, p in enumerate(participantes):
            puntos = float(p.get("puntos") or 0)
            # El último absorbe el redondeo: repartir por porcentaje deja
            # centavos sueltos y el pozo debe quedar en cero exacto.
            monto = (round(total - asignado, 2) if i == len(participantes) - 1
                     else round(total * puntos / puntos_total, 2))
            asignado += monto
            run_sin_commit(db, "INSERT INTO reparto_detalle (reparto_id, empleado_id, "
                               "nombre, puntos, monto) VALUES (:r,:e,:n,:p,:m)",
                           {"r": rid, "e": p.get("empleado_id"), "n": p.get("nombre"),
                            "p": puntos, "m": monto})
            detalle.append({"nombre": p.get("nombre"), "puntos": puntos, "monto": monto})
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {"ok": True, "id": rid, "numero": numero, "total": total,
            "detalle": detalle, "estado": "borrador"}


@router.get("/api/propinas/repartos/{rid}")
def reparto_detalle(rid: int, cur: dict = Depends(require_rol(*ROLES_PROPINA)),
                    db: Session = Depends(get_tenant_db)):
    reparto = q1(db, "SELECT * FROM repartos_propina WHERE id=:i", {"i": rid})
    if not reparto:
        raise HTTPException(404, "Reparto no encontrado")
    return {"ok": True, "reparto": serial(dict(reparto))[0],
            "detalle": serial(q(db, "SELECT * FROM reparto_detalle WHERE reparto_id=:r "
                                    "ORDER BY monto DESC", {"r": rid}))}


@router.post("/api/propinas/repartos/{rid}/pagar")
def reparto_pagar(rid: int, cur: dict = Depends(require_rol("admin", "gerente")),
                  db: Session = Depends(get_tenant_db)):
    """Confirma el pago: marca las propinas como distribuidas y cancela el pasivo."""
    reparto = q1(db, "SELECT * FROM repartos_propina WHERE id=:i", {"i": rid})
    if not reparto:
        raise HTTPException(404, "Reparto no encontrado")
    if reparto["estado"] == "pagado":
        raise HTTPException(409, "El reparto ya fue pagado")

    try:
        run_sin_commit(db, "UPDATE propinas SET distribuida=1, reparto_id=:r "
                           "WHERE distribuida=0 AND ts >= :d AND ts <= :h",
                       {"r": rid, "d": str(reparto["desde"]),
                        "h": str(reparto["hasta"]) + "T23:59:59"})
        run_sin_commit(db, "UPDATE repartos_propina SET estado='pagado', pagado_en=:ts "
                           "WHERE id=:i", {"ts": ahora(), "i": rid})

        publicar(db, Evento(
            tipo=TipoEvento.PROPINA_REPARTIDA, entidad="reparto", entidad_id=rid,
            payload={"numero": reparto["numero"], "total": float(reparto["total"] or 0)},
            usuario=autor(cur)))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True, "numero": reparto["numero"], "total": float(reparto["total"] or 0)}
