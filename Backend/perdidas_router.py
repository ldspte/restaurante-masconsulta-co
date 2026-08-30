# -*- coding: utf-8 -*-
"""
================================================================
  CAFETERÍA · Módulo PÉRDIDAS (mermas)
================================================================
Registro y análisis de todo insumo que sale del inventario sin generar venta:
vencimiento, derrames, errores de preparación, sustracción o cortesías.

POR QUÉ ES UN MÓDULO Y NO UN TIPO DE MOVIMIENTO MÁS
---------------------------------------------------
Técnicamente una merma es una salida de inventario y podría vivir dentro de
Inventario. Se separa porque responde a una pregunta de negocio distinta: no
«cuánto tengo» sino «cuánto se está perdiendo y por qué». Esa pregunta necesita
motivo obligatorio, autorización de un supervisor y un reporte propio por causa
—cosas que no aplican a una salida ordinaria.

El módulo solo registra el hecho y lo publica. Quién descuenta el inventario y
quién lo contabiliza son suscriptores del bus; este módulo no los conoce.

Rutas
  GET    /api/perdidas/catalogos    motivos e insumos
  GET    /api/perdidas              listado con filtros de fecha
  POST   /api/perdidas              registra una pérdida
  POST   /api/perdidas/motivos      catálogo extensible («➕ Otro…»)
  GET    /api/perdidas/reporte      análisis por motivo y por insumo

Autor: Arquitectura de Software · Unidad 1
================================================================
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from db import ahora, q, q1, run, run_sin_commit, serial
from dependencias import get_tenant_db
from eventos import Evento, TipoEvento, publicar
from seguridad import autor, require_rol, verify_token

router = APIRouter(tags=["Pérdidas"])

# Registrar una merma reduce el patrimonio de la empresa sin contraprestación:
# no es una operación de cajero.
ROLES_PERDIDA = ("admin", "supervisor", "bodega")


@router.get("/api/perdidas/catalogos")
def catalogos(cur: dict = Depends(verify_token), db: Session = Depends(get_tenant_db)):
    return {"ok": True,
            "motivos": serial(q(db, "SELECT id, nombre FROM cat_motivos_perdida "
                                    "WHERE activo = 1 ORDER BY nombre")),
            "insumos": serial(q(db, "SELECT i.id, i.codigo, i.nombre, i.stock, i.costo_prom, "
                                    "COALESCE(u.nombre,'') AS unidad FROM insumos i "
                                    "LEFT JOIN cat_unidades u ON u.id = i.unidad_id "
                                    "WHERE i.activo = 1 ORDER BY i.nombre"))}


@router.post("/api/perdidas/motivos", status_code=201)
def motivo_crear(body: dict = Body(...), cur: dict = Depends(require_rol(*ROLES_PERDIDA)),
                 db: Session = Depends(get_tenant_db)):
    """Alta de motivo desde «➕ Otro…». Los motivos de pérdida varían por
    negocio; una lista cerrada obligaría al usuario a forzar su caso dentro de
    una categoría equivocada, arruinando el reporte que justifica el módulo."""
    nombre = (body.get("nombre") or "").strip()
    if not nombre:
        raise HTTPException(400, "El nombre del motivo es obligatorio")
    existente = q1(db, "SELECT id FROM cat_motivos_perdida WHERE LOWER(nombre)=LOWER(:n)",
                   {"n": nombre})
    if existente:
        run(db, "UPDATE cat_motivos_perdida SET activo=1 WHERE id=:i", {"i": existente["id"]})
        return {"ok": True, "id": existente["id"], "reactivado": True}
    res = run(db, "INSERT INTO cat_motivos_perdida (nombre, activo) VALUES (:n, 1)",
              {"n": nombre})
    return {"ok": True, "id": getattr(res, "lastrowid", 0)}


@router.post("/api/perdidas", status_code=201)
def registrar(body: dict = Body(...), cur: dict = Depends(require_rol(*ROLES_PERDIDA)),
              db: Session = Depends(get_tenant_db)):
    insumo_id = int(body.get("insumo_id") or 0)
    cantidad = float(body.get("cantidad") or 0)
    motivo_id = body.get("motivo_id")

    if not insumo_id or cantidad <= 0:
        raise HTTPException(400, "Indique el insumo y una cantidad mayor que cero")
    if not motivo_id:
        raise HTTPException(400, "El motivo es obligatorio")

    insumo = q1(db, "SELECT id, nombre, costo_prom, stock FROM insumos WHERE id=:i AND activo=1",
                {"i": insumo_id})
    if not insumo:
        raise HTTPException(404, "Insumo no encontrado")
    motivo = q1(db, "SELECT id, nombre FROM cat_motivos_perdida WHERE id=:i", {"i": motivo_id})
    if not motivo:
        raise HTTPException(400, "El motivo indicado no existe")

    # La pérdida se valora al costo promedio del momento del registro. Ese
    # valor se congela en la fila: si el costo del insumo cambia después, la
    # pérdida histórica debe seguir valiendo lo que valió cuando ocurrió.
    costo_unit = float(insumo["costo_prom"] or 0)
    costo_total = round(cantidad * costo_unit, 2)

    try:
        res = run_sin_commit(db,
                             "INSERT INTO perdidas (ts, insumo_id, cantidad, costo_unit, "
                             "costo_total, motivo_id, motivo, observacion, usuario) "
                             "VALUES (:ts,:i,:q,:cu,:ct,:mi,:m,:o,:u)",
                             {"ts": ahora(), "i": insumo_id, "q": cantidad,
                              "cu": costo_unit, "ct": costo_total,
                              "mi": motivo["id"], "m": motivo["nombre"],
                              "o": (body.get("observacion") or "").strip() or None,
                              "u": autor(cur)})
        pid = int(res.lastrowid or 0)

        publicar(db, Evento(
            tipo=TipoEvento.PERDIDA_REGISTRADA, entidad="perdida", entidad_id=pid,
            payload={"insumo_id": insumo_id, "insumo": insumo["nombre"],
                     "cantidad": cantidad, "costo_unit": costo_unit,
                     "costo_total": costo_total, "motivo": motivo["nombre"]},
            usuario=autor(cur)))
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {"ok": True, "id": pid, "costo_total": costo_total}


@router.get("/api/perdidas")
def listar(desde: str = "", hasta: str = "", limite: int = 100,
           cur: dict = Depends(verify_token), db: Session = Depends(get_tenant_db)):
    limite = max(1, min(int(limite or 100), 500))
    where, params = ["1=1"], {"l": limite}
    if desde:
        where.append("p.ts >= :d"); params["d"] = desde
    if hasta:
        where.append("p.ts <= :h"); params["h"] = hasta + "T23:59:59"

    filas = serial(q(db, "SELECT p.*, i.codigo, i.nombre AS insumo, "
                         "       COALESCE(u.nombre,'') AS unidad "
                         "FROM perdidas p JOIN insumos i ON i.id = p.insumo_id "
                         "LEFT JOIN cat_unidades u ON u.id = i.unidad_id "
                         "WHERE " + " AND ".join(where) +
                         " ORDER BY p.id DESC LIMIT :l", params))
    return {"ok": True, "items": filas,
            "kpis": {"registros": len(filas),
                     "costo_total": round(sum(float(f.get("costo_total") or 0)
                                              for f in filas), 2)}}


@router.get("/api/perdidas/reporte")
def reporte(desde: str = "", hasta: str = "",
            cur: dict = Depends(require_rol("admin", "supervisor")),
            db: Session = Depends(get_tenant_db)):
    """Análisis por motivo y por insumo, más el peso de la merma sobre las
    ventas del período. El porcentaje es el indicador que realmente importa:
    perder 200.000 pesos es distinto si se vendieron dos millones o veinte."""
    where, params = ["1=1"], {}
    if desde:
        where.append("ts >= :d"); params["d"] = desde
    if hasta:
        where.append("ts <= :h"); params["h"] = hasta + "T23:59:59"
    clausula = " AND ".join(where)

    por_motivo = serial(q(db,
                          f"SELECT COALESCE(motivo,'(sin motivo)') AS motivo, "
                          f"COUNT(*) AS n, ROUND(SUM(costo_total),2) AS costo "
                          f"FROM perdidas WHERE {clausula} "
                          f"GROUP BY motivo ORDER BY costo DESC", params))
    por_insumo = serial(q(db,
                          f"SELECT i.nombre AS insumo, COUNT(*) AS n, "
                          f"ROUND(SUM(p.costo_total),2) AS costo, "
                          f"ROUND(SUM(p.cantidad),3) AS cantidad "
                          f"FROM perdidas p JOIN insumos i ON i.id = p.insumo_id "
                          f"WHERE {clausula.replace('ts', 'p.ts')} "
                          f"GROUP BY i.nombre ORDER BY costo DESC LIMIT 15", params))

    total = round(sum(float(m["costo"] or 0) for m in por_motivo), 2)

    ventas_where = clausula.replace("ts", "v.ts")
    fila = q1(db, f"SELECT COALESCE(SUM(v.subtotal),0) AS ventas FROM ventas v "
                  f"WHERE v.estado='pagada' AND {ventas_where}", params)
    ventas = float((fila or {}).get("ventas") or 0)

    return {"ok": True, "por_motivo": por_motivo, "por_insumo": por_insumo,
            "total": total, "ventas_periodo": round(ventas, 2),
            "pct_sobre_ventas": round(total / ventas * 100, 2) if ventas else None}
