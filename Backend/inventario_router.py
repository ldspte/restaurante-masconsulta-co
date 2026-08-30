# -*- coding: utf-8 -*-
"""
================================================================
  CAFETERÍA · Módulo INVENTARIO
================================================================
Insumos, kardex y valorización. Todo cambio de existencias pasa por una sola
función —`mover()`— y queda registrado como movimiento. No hay ningún camino
que actualice `insumos.stock` sin dejar su rastro en `inv_movimientos`.

Esa restricción es lo que hace auditable el inventario: el stock actual siempre
es reconstruible sumando el kardex, y cualquier diferencia entre ambos delata
una manipulación directa de la base.

VALORIZACIÓN — costo promedio ponderado
---------------------------------------
Al entrar mercancía, el costo unitario del insumo se recalcula como promedio
ponderado entre lo que había y lo que llega. Se eligió sobre PEPS/UEPS porque
no exige mantener lotes —irrelevante para insumos a granel de una cafetería— y
porque es el método que la normativa colombiana admite sin requisitos
adicionales.

SUSCRIPTORES DE EVENTOS
-----------------------
Este módulo escucha al bus y reacciona a hechos que ocurren en otros módulos:
    venta.registrada    → descuenta los insumos de la receta
    venta.anulada       → los devuelve
    perdida.registrada  → descuenta como merma
Caja y Pérdidas no saben que este módulo existe.

Autor: Arquitectura de Software · Unidad 1
================================================================
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from db import ahora, q, q1, run, run_sin_commit, serial
from dependencias import get_tenant_db
from eventos import Evento, TipoEvento, suscribir
from seguridad import autor, require_rol, verify_token

log = logging.getLogger("cafeteria.inventario")
router = APIRouter(tags=["Inventario"])

TIPOS_MOVIMIENTO = ("entrada", "salida", "ajuste", "merma")


# ══════════════════════════════════════════════════════════════════════
#  NÚCLEO: el único camino para mover existencias
# ══════════════════════════════════════════════════════════════════════
def mover(db: Session, *, insumo_id: int, tipo: str, cantidad: float,
          costo_unit: float | None = None, ref_tipo: str = "", ref_id: int | None = None,
          motivo: str = "", usuario: str = "sistema",
          permitir_negativo: bool = False, suma: bool | None = None) -> dict:
    """Registra un movimiento y actualiza el saldo del insumo.

    NO hace commit: el llamador decide, para que un movimiento disparado por
    una venta pertenezca a la misma transacción que la venta.

    `cantidad` siempre es positiva; el signo lo determina `tipo`. Aceptar
    cantidades negativas duplicaría la semántica ("entrada de -5" vs "salida de
    5") y haría ambigua cualquier suma del kardex.

    `suma` solo aplica a los ajustes por conteo, que son el único movimiento
    que puede ir en cualquier dirección: True si el conteo halló MÁS de lo
    registrado, False si halló menos.
    """
    if tipo not in TIPOS_MOVIMIENTO:
        raise HTTPException(400, f"Tipo de movimiento inválido: {tipo}")
    cantidad = round(float(cantidad or 0), 4)
    if cantidad <= 0:
        raise HTTPException(400, "La cantidad debe ser mayor que cero")

    insumo = q1(db, "SELECT id, nombre, stock, costo_prom FROM insumos WHERE id = :i",
                {"i": insumo_id})
    if not insumo:
        raise HTTPException(404, f"Insumo {insumo_id} no encontrado")

    stock_actual = float(insumo["stock"] or 0)
    costo_actual = float(insumo["costo_prom"] or 0)

    # ¿El movimiento suma o resta existencias?
    if tipo == "entrada":
        incrementa = True
    elif tipo == "ajuste":
        if suma is None:
            raise HTTPException(400, "Un ajuste debe indicar su dirección")
        incrementa = bool(suma)
    else:                       # salida, merma
        incrementa = False

    if incrementa:
        costo_entrada = float(costo_unit if costo_unit is not None else costo_actual)
        if costo_entrada < 0:
            raise HTTPException(400, "El costo unitario no puede ser negativo")
        nuevo_stock = stock_actual + cantidad
        # Promedio ponderado solo en compras. Un ajuste al alza no es una
        # adquisición: aparecen unidades que ya estaban, así que su costo es el
        # que ya tenía el insumo y ponderar lo distorsionaría.
        if tipo == "entrada" and stock_actual > 0:
            nuevo_costo = ((stock_actual * costo_actual) + (cantidad * costo_entrada)) / nuevo_stock
        elif tipo == "entrada":
            nuevo_costo = costo_entrada
        else:
            nuevo_costo = costo_actual
        costo_mov = costo_entrada
    else:
        nuevo_stock = stock_actual - cantidad
        nuevo_costo = costo_actual
        costo_mov = float(costo_unit if costo_unit is not None else costo_actual)
        if nuevo_stock < 0 and not permitir_negativo:
            raise HTTPException(
                409,
                f"Existencias insuficientes de «{insumo['nombre']}»: "
                f"hay {stock_actual:g} y se requieren {cantidad:g}.",
            )

    nuevo_stock = round(nuevo_stock, 4)
    nuevo_costo = round(nuevo_costo, 6)

    run_sin_commit(db,
                   "INSERT INTO inv_movimientos (ts, insumo_id, tipo, cantidad, costo_unit, "
                   "saldo, ref_tipo, ref_id, motivo, usuario) "
                   "VALUES (:ts,:i,:tp,:q,:co,:sal,:rt,:ri,:mo,:us)",
                   {"ts": ahora(), "i": insumo_id, "tp": tipo, "q": cantidad,
                    "co": costo_mov, "sal": nuevo_stock, "rt": ref_tipo or None,
                    "ri": ref_id, "mo": motivo or None, "us": usuario})
    run_sin_commit(db, "UPDATE insumos SET stock = :s, costo_prom = :c WHERE id = :i",
                   {"s": nuevo_stock, "c": nuevo_costo, "i": insumo_id})

    return {"insumo_id": insumo_id, "nombre": insumo["nombre"], "tipo": tipo,
            "cantidad": cantidad, "saldo": nuevo_stock, "costo_unit": costo_mov,
            "costo_total": round(cantidad * costo_mov, 2)}


def costo_receta_venta(db: Session, producto_id: int, unidades: float) -> float:
    """Costo de insumos para N unidades de un producto, según su receta."""
    fila = q1(db, "SELECT COALESCE(SUM(r.cantidad * i.costo_prom),0) AS c "
                  "FROM receta r JOIN insumos i ON i.id=r.insumo_id "
                  "WHERE r.producto_id = :p", {"p": producto_id})
    return round(float((fila or {}).get("c") or 0) * float(unidades or 0), 2)


# ══════════════════════════════════════════════════════════════════════
#  SUSCRIPTORES DEL BUS DE EVENTOS
# ══════════════════════════════════════════════════════════════════════
def _descontar_por_venta(db: Session, evento: Evento) -> None:
    """`venta.registrada` → descuenta los insumos de cada producto vendido.

    Se permite saldo negativo deliberadamente. Un POS no puede rechazar el
    cobro de un café ya servido porque el sistema cree que no queda leche: el
    inventario teórico se desvía del físico todo el tiempo. El negativo es la
    señal visible de esa desviación y se corrige con un conteo físico; bloquear
    la venta solo lograría que el cajero deje de registrarla.
    """
    for item in evento.payload.get("items", []):
        producto_id = int(item["producto_id"])
        unidades = float(item["cantidad"])
        receta = q(db, "SELECT insumo_id, cantidad FROM receta WHERE producto_id = :p",
                   {"p": producto_id})
        for linea in receta:
            mover(db,
                  insumo_id=int(linea["insumo_id"]),
                  tipo="salida",
                  cantidad=float(linea["cantidad"]) * unidades,
                  ref_tipo="venta", ref_id=evento.entidad_id,
                  motivo=f"Venta {evento.payload.get('folio', '')} · {item.get('nombre', '')}",
                  usuario=evento.usuario,
                  permitir_negativo=True)


def _reponer_por_anulacion(db: Session, evento: Evento) -> None:
    """`venta.anulada` → devuelve al inventario lo consumido por esa venta.

    Se reponen las cantidades EXACTAS que salieron, leídas del kardex, y no las
    que la receta indica hoy: si la receta cambió entre la venta y la anulación,
    recalcularla dejaría el inventario descuadrado.
    """
    salidas = q(db,
                "SELECT insumo_id, cantidad, costo_unit FROM inv_movimientos "
                "WHERE ref_tipo = 'venta' AND ref_id = :v AND tipo = 'salida'",
                {"v": evento.entidad_id})
    for s in salidas:
        mover(db, insumo_id=int(s["insumo_id"]), tipo="entrada",
              cantidad=float(s["cantidad"]), costo_unit=float(s["costo_unit"] or 0),
              ref_tipo="anulacion", ref_id=evento.entidad_id,
              motivo=f"Reversa de venta {evento.payload.get('folio', '')}",
              usuario=evento.usuario)


def _descontar_por_perdida(db: Session, evento: Evento) -> None:
    """`perdida.registrada` → salida de tipo `merma`.

    Se distingue de una salida por venta para que el estado de resultados pueda
    separar el costo de lo vendido del costo de lo perdido. Mezclarlos ocultaría
    exactamente el indicador que el módulo de Pérdidas existe para vigilar.
    """
    mover(db,
          insumo_id=int(evento.payload["insumo_id"]),
          tipo="merma",
          cantidad=float(evento.payload["cantidad"]),
          costo_unit=float(evento.payload.get("costo_unit") or 0),
          ref_tipo="perdida", ref_id=evento.entidad_id,
          motivo=evento.payload.get("motivo") or "Pérdida registrada",
          usuario=evento.usuario,
          permitir_negativo=True)


def registrar_suscriptores() -> None:
    suscribir(TipoEvento.VENTA_REGISTRADA, _descontar_por_venta)
    suscribir(TipoEvento.VENTA_ANULADA, _reponer_por_anulacion)
    suscribir(TipoEvento.PERDIDA_REGISTRADA, _descontar_por_perdida)


# ══════════════════════════════════════════════════════════════════════
#  ENDPOINTS
# ══════════════════════════════════════════════════════════════════════
@router.get("/api/inventario/insumos")
def insumos_listar(solo_alerta: int = 0, cur: dict = Depends(verify_token),
                   db: Session = Depends(get_tenant_db)):
    filas = serial(q(db,
                     "SELECT i.*, COALESCE(u.nombre,'') AS unidad, "
                     "       ROUND(i.stock * i.costo_prom, 2) AS valor "
                     "FROM insumos i LEFT JOIN cat_unidades u ON u.id = i.unidad_id "
                     "WHERE i.activo = 1 ORDER BY i.nombre"))
    for f in filas:
        stock = float(f.get("stock") or 0)
        minimo = float(f.get("stock_min") or 0)
        f["alerta"] = "agotado" if stock <= 0 else ("bajo" if stock <= minimo else "ok")

    if solo_alerta:
        filas = [f for f in filas if f["alerta"] != "ok"]

    return {"ok": True, "items": filas,
            "kpis": {"total": len(filas),
                     "bajo_minimo": sum(1 for f in filas if f["alerta"] == "bajo"),
                     "agotados": sum(1 for f in filas if f["alerta"] == "agotado"),
                     "valor_total": round(sum(float(f.get("valor") or 0) for f in filas), 2)}}


@router.post("/api/inventario/insumos", status_code=201)
def insumo_crear(body: dict = Body(...),
                 cur: dict = Depends(require_rol("admin", "supervisor", "bodega")),
                 db: Session = Depends(get_tenant_db)):
    nombre = (body.get("nombre") or "").strip()
    if not nombre:
        raise HTTPException(400, "El nombre del insumo es obligatorio")
    codigo = (body.get("codigo") or "").strip() or _siguiente_codigo(db)
    if q1(db, "SELECT id FROM insumos WHERE codigo = :c", {"c": codigo}):
        raise HTTPException(409, f"Ya existe un insumo con el código {codigo}")

    res = run(db, "INSERT INTO insumos (codigo, nombre, unidad_id, stock, stock_min, "
                  "costo_prom, activo, creado_en) VALUES (:c,:n,:u,0,:m,:co,1,:ts)",
              {"c": codigo, "n": nombre, "u": body.get("unidad_id") or None,
               "m": float(body.get("stock_min") or 0),
               "co": float(body.get("costo_prom") or 0), "ts": ahora()})
    iid = int(getattr(res, "lastrowid", 0) or 0)

    # Un saldo inicial se registra como entrada, nunca como UPDATE al stock:
    # de lo contrario nacería un insumo con existencias sin origen en el kardex.
    inicial = float(body.get("stock_inicial") or 0)
    if inicial > 0:
        mover(db, insumo_id=iid, tipo="entrada", cantidad=inicial,
              costo_unit=float(body.get("costo_prom") or 0),
              ref_tipo="apertura", motivo="Saldo inicial", usuario=autor(cur))
        db.commit()
    return {"ok": True, "id": iid, "codigo": codigo}


@router.put("/api/inventario/insumos/{iid}")
def insumo_editar(iid: int, body: dict = Body(...),
                  cur: dict = Depends(require_rol("admin", "supervisor", "bodega")),
                  db: Session = Depends(get_tenant_db)):
    if not q1(db, "SELECT id FROM insumos WHERE id = :i", {"i": iid}):
        raise HTTPException(404, "Insumo no encontrado")
    sets, params = [], {"i": iid}
    for campo in ("codigo", "nombre", "unidad_id", "stock_min", "activo"):
        if campo in body:
            sets.append(f"{campo} = :{campo}")
            params[campo] = body[campo]
    # `stock` y `costo_prom` NO son editables por esta vía: se cambian con un
    # movimiento (entrada/ajuste), que es lo que deja rastro auditable.
    if sets:
        run(db, f"UPDATE insumos SET {', '.join(sets)} WHERE id = :i", params)
    return {"ok": True}


@router.post("/api/inventario/entradas", status_code=201)
def entrada(body: dict = Body(...),
            cur: dict = Depends(require_rol("admin", "supervisor", "bodega")),
            db: Session = Depends(get_tenant_db)):
    """Compra o recepción de mercancía. Emite `inventario.entrada` para que
    contabilidad registre el asiento correspondiente."""
    from eventos import publicar

    insumo_id = int(body.get("insumo_id") or 0)
    cantidad = float(body.get("cantidad") or 0)
    costo_unit = float(body.get("costo_unit") or 0)
    if not insumo_id or cantidad <= 0:
        raise HTTPException(400, "Indique insumo y una cantidad mayor que cero")

    try:
        resultado = mover(db, insumo_id=insumo_id, tipo="entrada", cantidad=cantidad,
                          costo_unit=costo_unit, ref_tipo="compra",
                          motivo=(body.get("motivo") or "Compra a proveedor"),
                          usuario=autor(cur))
        publicar(db, Evento(
            tipo=TipoEvento.INVENTARIO_ENTRADA, entidad="insumo", entidad_id=insumo_id,
            payload={"cantidad": cantidad, "costo_unit": costo_unit,
                     "costo_total": resultado["costo_total"],
                     "insumo": resultado["nombre"],
                     "contado": bool(body.get("contado", False))},
            usuario=autor(cur)))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True, "movimiento": resultado}


@router.post("/api/inventario/ajustes", status_code=201)
def ajuste(body: dict = Body(...),
           cur: dict = Depends(require_rol("admin", "supervisor", "bodega")),
           db: Session = Depends(get_tenant_db)):
    """Ajuste por conteo físico: fija el stock al valor contado y registra la
    diferencia como movimiento. El motivo es OBLIGATORIO — un ajuste sin
    explicación es indistinguible de un faltante encubierto."""
    insumo_id = int(body.get("insumo_id") or 0)
    contado = body.get("stock_contado")
    motivo = (body.get("motivo") or "").strip()
    if not insumo_id or contado is None:
        raise HTTPException(400, "Indique el insumo y el stock contado")
    if not motivo:
        raise HTTPException(400, "El motivo del ajuste es obligatorio")

    insumo = q1(db, "SELECT stock, costo_prom, nombre FROM insumos WHERE id=:i",
                {"i": insumo_id})
    if not insumo:
        raise HTTPException(404, "Insumo no encontrado")

    diferencia = round(float(contado) - float(insumo["stock"] or 0), 4)
    if abs(diferencia) < 1e-9:
        return {"ok": True, "sin_cambios": True,
                "mensaje": "El conteo coincide con el sistema."}

    try:
        resultado = mover(db, insumo_id=insumo_id, tipo="ajuste",
                          cantidad=abs(diferencia), suma=(diferencia > 0),
                          costo_unit=float(insumo["costo_prom"] or 0),
                          ref_tipo="conteo",
                          motivo=f"{motivo} (dif. {diferencia:+g})",
                          usuario=autor(cur), permitir_negativo=True)
        db.commit()
    except Exception:
        db.rollback()
        raise

    resultado["diferencia"] = diferencia
    return {"ok": True, "movimiento": resultado}


@router.get("/api/inventario/kardex")
def kardex(insumo_id: int = 0, limite: int = 200, cur: dict = Depends(verify_token),
           db: Session = Depends(get_tenant_db)):
    limite = max(1, min(int(limite or 200), 1000))
    where, params = [], {"l": limite}
    if insumo_id:
        where.append("m.insumo_id = :i")
        params["i"] = insumo_id
    clausula = ("WHERE " + " AND ".join(where)) if where else ""
    filas = serial(q(db,
                     "SELECT m.*, i.nombre AS insumo, i.codigo, "
                     "       COALESCE(u.nombre,'') AS unidad "
                     "FROM inv_movimientos m JOIN insumos i ON i.id = m.insumo_id "
                     "LEFT JOIN cat_unidades u ON u.id = i.unidad_id "
                     f"{clausula} ORDER BY m.id DESC LIMIT :l", params))
    return {"ok": True, "items": filas}


@router.get("/api/inventario/alertas")
def alertas(cur: dict = Depends(verify_token), db: Session = Depends(get_tenant_db)):
    """Insumos en o por debajo del mínimo. Alimenta el aviso del tablero."""
    filas = serial(q(db,
                     "SELECT i.id, i.codigo, i.nombre, i.stock, i.stock_min, "
                     "       COALESCE(u.nombre,'') AS unidad "
                     "FROM insumos i LEFT JOIN cat_unidades u ON u.id = i.unidad_id "
                     "WHERE i.activo = 1 AND i.stock <= i.stock_min "
                     "ORDER BY (i.stock - i.stock_min), i.nombre"))
    return {"ok": True, "items": filas, "total": len(filas)}


def _siguiente_codigo(db: Session) -> str:
    fila = q1(db, "SELECT COUNT(*) AS n FROM insumos")
    return "INS-%03d" % (int((fila or {}).get("n") or 0) + 1)
