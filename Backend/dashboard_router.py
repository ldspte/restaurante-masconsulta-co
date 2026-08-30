# -*- coding: utf-8 -*-
"""
================================================================
  CAFETERÍA · Módulo TABLERO (lectura consolidada)
================================================================
Vista transversal del negocio: ventas, márgenes, mermas y alertas de stock.

SEPARACIÓN LECTURA / ESCRITURA
------------------------------
Este módulo NO escribe nada ni publica eventos: solo consulta y agrega. Es una
aplicación acotada del principio de CQRS —separar el modelo de lectura del de
escritura—. Aquí se materializa en que las consultas del tablero pueden
optimizarse, cachearse o mudarse a una réplica de solo lectura sin tocar una
línea de la lógica de negocio, porque no hay ninguna aquí.

Ruta
  GET /api/dashboard   KPIs del período solicitado

Autor: Arquitectura de Software · Unidad 1
================================================================
"""
from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db import ahora_local, q, q1, serial
from dependencias import get_tenant_db
from seguridad import verify_token

router = APIRouter(tags=["Tablero"])


@router.get("/api/dashboard")
def dashboard(dias: int = 7, cur: dict = Depends(verify_token),
              db: Session = Depends(get_tenant_db)):
    dias = max(1, min(int(dias or 7), 365))
    # La fecha del NEGOCIO, no la del servidor: en un hosting en otro huso
    # «ventas de hoy» se corta dos horas antes o después de lo que debe.
    hoy = ahora_local().date()
    desde = (hoy - datetime.timedelta(days=dias - 1)).isoformat()
    p = {"d": desde}

    # ── Ventas del período ──
    ventas = q1(db,
                "SELECT COUNT(*) AS n, COALESCE(SUM(total),0) AS total, "
                "       COALESCE(SUM(subtotal),0) AS subtotal, "
                "       COALESCE(SUM(impuestos),0) AS impuestos, "
                "       COALESCE(SUM(costo),0) AS costo "
                "FROM ventas WHERE estado='pagada' AND ts >= :d", p) or {}

    n_ventas = int(ventas.get("n") or 0)
    subtotal = round(float(ventas.get("subtotal") or 0), 2)
    costo = round(float(ventas.get("costo") or 0), 2)
    total = round(float(ventas.get("total") or 0), 2)

    # ── Ventas de hoy (comparativo del día en curso) ──
    hoy_row = q1(db, "SELECT COUNT(*) AS n, COALESCE(SUM(total),0) AS total "
                     "FROM ventas WHERE estado='pagada' AND ts >= :h",
                 {"h": hoy.isoformat()}) or {}

    # ── Serie diaria: alimenta la gráfica de tendencia ──
    serie = serial(q(db,
                     "SELECT SUBSTR(ts,1,10) AS dia, COUNT(*) AS n, "
                     "       ROUND(SUM(total),2) AS total, ROUND(SUM(costo),2) AS costo "
                     "FROM ventas WHERE estado='pagada' AND ts >= :d "
                     "GROUP BY SUBSTR(ts,1,10) ORDER BY dia", p))

    # ── Productos más vendidos ──
    top = serial(q(db,
                   "SELECT vi.nombre, ROUND(SUM(vi.cantidad),2) AS unidades, "
                   "       ROUND(SUM(vi.total),2) AS ingreso "
                   "FROM venta_items vi JOIN ventas v ON v.id = vi.venta_id "
                   "WHERE v.estado='pagada' AND v.ts >= :d "
                   "GROUP BY vi.nombre ORDER BY unidades DESC LIMIT 8", p))

    # ── Mezcla de medios de pago ──
    medios = serial(q(db,
                      "SELECT pg.metodo, COUNT(*) AS n, ROUND(SUM(pg.monto),2) AS monto "
                      "FROM pagos pg JOIN ventas v ON v.id = pg.venta_id "
                      "WHERE v.estado='pagada' AND v.ts >= :d "
                      "GROUP BY pg.metodo ORDER BY monto DESC", p))

    # ── Pérdidas ──
    perdidas = q1(db, "SELECT COUNT(*) AS n, COALESCE(SUM(costo_total),0) AS costo "
                      "FROM perdidas WHERE ts >= :d", p) or {}
    costo_perdidas = round(float(perdidas.get("costo") or 0), 2)

    # ── Inventario ──
    inv = q1(db, "SELECT COUNT(*) AS n, "
                 "       COALESCE(SUM(stock * costo_prom),0) AS valor, "
                 "       SUM(CASE WHEN stock <= stock_min THEN 1 ELSE 0 END) AS alertas "
                 "FROM insumos WHERE activo = 1") or {}

    alertas = serial(q(db,
                       "SELECT nombre, stock, stock_min FROM insumos "
                       "WHERE activo=1 AND stock <= stock_min "
                       "ORDER BY (stock - stock_min) LIMIT 5"))

    utilidad_bruta = round(subtotal - costo, 2)

    return {
        "ok": True,
        "periodo": {"dias": dias, "desde": desde, "hasta": hoy.isoformat()},
        "kpis": {
            "ventas_num": n_ventas,
            "ventas_total": total,
            "ventas_subtotal": subtotal,
            "impuestos": round(float(ventas.get("impuestos") or 0), 2),
            "costo_ventas": costo,
            "utilidad_bruta": utilidad_bruta,
            # Margen y ticket sobre cero no existen: None lo dice; 0 mentiría.
            "margen_pct": round(utilidad_bruta / subtotal * 100, 1) if subtotal else None,
            "ticket_promedio": round(total / n_ventas, 2) if n_ventas else None,
            "hoy_num": int(hoy_row.get("n") or 0),
            "hoy_total": round(float(hoy_row.get("total") or 0), 2),
            "perdidas_num": int(perdidas.get("n") or 0),
            "perdidas_costo": costo_perdidas,
            "perdidas_pct_ventas": round(costo_perdidas / subtotal * 100, 2) if subtotal else None,
            "inventario_valor": round(float(inv.get("valor") or 0), 2),
            "inventario_alertas": int(inv.get("alertas") or 0),
            "insumos_total": int(inv.get("n") or 0),
        },
        "serie": serie,
        "top_productos": top,
        "medios_pago": medios,
        "alertas_stock": alertas,
    }
