# -*- coding: utf-8 -*-
"""
================================================================
  RESTAURANTE · Módulo COMANDAS Y COCINA
================================================================
La comanda es el documento de SERVICIO; la venta es el documento COMERCIAL.
Son cosas distintas y por eso son módulos distintos: una mesa puede pedir tres
veces y pagar una sola cuenta, o pedir una vez y dividirla en dos.

    Mesero toma pedido ──▶ comanda abierta
              │
              └─▶ ENVIAR A COCINA ──▶ cada línea entra a la cola de SU estación
                                        │
                          Cocina: pendiente → en_preparacion → listo
                                        │
                          Mesero: entregado
              │
              └─▶ Caja: cerrar comanda ──▶ VENTA (dispara el bus de eventos)

EL ESTADO VIVE EN LA LÍNEA, NO EN LA COMANDA
--------------------------------------------
Un café sale en dos minutos y un pollo a la plancha en dieciocho. Si el estado
fuera de la comanda completa, no se podría entregar la bebida mientras el plato
se cocina —que es exactamente como trabaja un restaurante—.

EL INVENTARIO SE DESCUENTA AL COBRAR, NO AL PEDIR
-------------------------------------------------
Decisión deliberada. Descontar al enviar a cocina parece más fiel a la realidad
física, pero una comanda anulada o un plato devuelto obligarían a reponer, y
esa reposición se olvida. Al descontar contra la venta, el inventario se mueve
una sola vez y siempre contra un hecho económico consumado. Lo que se prepara y
se pierde entra por Pérdidas, con su motivo.

Rutas
  POST /api/comandas                     abre comanda (mesa, llevar, domicilio)
  GET  /api/comandas                     abiertas
  GET  /api/comandas/{id}
  POST /api/comandas/{id}/items          agrega líneas
  POST /api/comandas/{id}/enviar         manda a cocina lo pendiente
  DELETE /api/comandas/items/{item_id}   anula una línea
  POST /api/comandas/{id}/cerrar         genera la cuenta para la caja
  GET  /api/cocina/cola                  pantalla de cocina (KDS)
  POST /api/cocina/items/{id}/estado     avanza el estado de una línea

Autor: Arquitectura de Software · Unidad 1
================================================================
"""
from __future__ import annotations

import datetime

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from db import anio_actual, ahora, q, q1, run, run_sin_commit, serial, siguiente_consecutivo
from dependencias import get_tenant_db
from seguridad import autor, require_rol, verify_token

router = APIRouter(tags=["Comandas y cocina"])

ROLES_COMANDA = ("admin", "gerente", "mesero", "cajero")
ROLES_COCINA = ("admin", "gerente", "cocina")

TIPOS = ("mesa", "llevar", "domicilio")
ESTADOS_ITEM = ("pendiente", "en_preparacion", "listo", "entregado", "anulado")

# Flujo de la línea. Solo se avanza; retroceder exigiría reponer inventario y
# rehacer tiempos, y en la práctica se resuelve anulando y volviendo a pedir.
_SIGUIENTE = {
    "pendiente": {"en_preparacion", "anulado"},
    "en_preparacion": {"listo", "anulado"},
    "listo": {"entregado"},
    "entregado": set(),
    "anulado": set(),
}


# ══════════════════════════════════════════════════════════════════════
#  APERTURA
# ══════════════════════════════════════════════════════════════════════
def abrir_comanda(db: Session, *, mesa_id: int | None, mesero: str, personas: int = 1,
                  tipo: str = "mesa", notas: str | None = None) -> dict:
    """Crea la comanda. NO hace commit — la llama el salón dentro de su
    transacción para que ocupar la mesa y abrir la cuenta sean atómicos."""
    if tipo not in TIPOS:
        raise HTTPException(400, f"Tipo de comanda inválido: {tipo}")
    if tipo == "mesa" and not mesa_id:
        raise HTTPException(400, "Una comanda de mesa requiere indicar la mesa")

    if mesa_id:
        abierta = q1(db, "SELECT numero FROM comandas WHERE mesa_id=:m "
                         "AND estado NOT IN ('cerrada','anulada') LIMIT 1", {"m": mesa_id})
        if abierta:
            raise HTTPException(409, f"La mesa ya tiene la comanda {abierta['numero']} abierta")

    anio = anio_actual()
    numero = f"C-{anio}-{siguiente_consecutivo(db, 'comanda', anio):05d}"
    res = run_sin_commit(db,
                         "INSERT INTO comandas (numero, mesa_id, mesero, tipo, personas, "
                         "estado, apertura_ts, notas) "
                         "VALUES (:n,:m,:me,:t,:p,'abierta',:ts,:no)",
                         {"n": numero, "m": mesa_id, "me": mesero, "t": tipo,
                          "p": max(1, int(personas or 1)), "ts": ahora(), "no": notas})
    return {"id": int(res.lastrowid or 0), "numero": numero, "tipo": tipo}


@router.post("/api/comandas", status_code=201)
def comanda_crear(body: dict = Body(...), cur: dict = Depends(require_rol(*ROLES_COMANDA)),
                  db: Session = Depends(get_tenant_db)):
    """Comanda sin mesa: pedidos para llevar y domicilios."""
    try:
        comanda = abrir_comanda(db, mesa_id=body.get("mesa_id"), mesero=autor(cur),
                                personas=int(body.get("personas") or 1),
                                tipo=body.get("tipo") or "llevar",
                                notas=body.get("notas"))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True, **comanda}


# ══════════════════════════════════════════════════════════════════════
#  CONSULTA
# ══════════════════════════════════════════════════════════════════════
@router.get("/api/comandas")
def comandas_listar(estado: str = "", cur: dict = Depends(require_rol(*ROLES_COMANDA)),
                    db: Session = Depends(get_tenant_db)):
    where = ["c.estado NOT IN ('cerrada','anulada')"] if not estado else ["c.estado = :e"]
    params = {} if not estado else {"e": estado}
    filas = serial(q(db,
                     "SELECT c.*, m.codigo AS mesa, "
                     "  (SELECT COUNT(*) FROM comanda_items i WHERE i.comanda_id=c.id "
                     "     AND i.estado<>'anulado') AS lineas, "
                     "  (SELECT COUNT(*) FROM comanda_items i WHERE i.comanda_id=c.id "
                     "     AND i.estado='pendiente') AS sin_enviar, "
                     "  (SELECT COUNT(*) FROM comanda_items i WHERE i.comanda_id=c.id "
                     "     AND i.estado='listo') AS por_entregar, "
                     "  (SELECT COALESCE(SUM(i.cantidad*i.precio_unit),0) FROM comanda_items i "
                     "     WHERE i.comanda_id=c.id AND i.estado<>'anulado') AS subtotal "
                     "FROM comandas c LEFT JOIN mesas m ON m.id=c.mesa_id "
                     "WHERE " + " AND ".join(where) +
                     " ORDER BY c.id DESC LIMIT 200", params))
    return {"ok": True, "items": filas}


@router.get("/api/comandas/{cid}")
def comanda_detalle(cid: int, cur: dict = Depends(require_rol(*ROLES_COMANDA)),
                    db: Session = Depends(get_tenant_db)):
    comanda = q1(db, "SELECT c.*, m.codigo AS mesa FROM comandas c "
                     "LEFT JOIN mesas m ON m.id=c.mesa_id WHERE c.id=:i", {"i": cid})
    if not comanda:
        raise HTTPException(404, "Comanda no encontrada")

    items = serial(q(db, "SELECT i.*, COALESCE(e.nombre,'Sin estación') AS estacion, "
                         "       COALESCE(e.color,'#94a3b8') AS estacion_color "
                         "FROM comanda_items i "
                         "LEFT JOIN estaciones e ON e.id=i.estacion_id "
                         "WHERE i.comanda_id=:c ORDER BY i.id", {"c": cid}))
    return {"ok": True, "comanda": serial(dict(comanda))[0], "items": items,
            "puestos": _puestos(db, cid, comanda, items),
            "totales": _totales(items)}


def _puestos(db: Session, cid: int, comanda: dict, items: list[dict]) -> list[dict]:
    """Estado de cada asiento de la mesa, del 1 al número de comensales.

    Se devuelven TODOS, incluidos los que no pidieron nada. Ese es el punto:
    un asiento ausente de la lista sería indistinguible de uno que nadie ha
    atendido, y el mesero necesita saber si le falta alguien.
    """
    personas = int(comanda.get("personas") or 0)
    if personas <= 0:
        return []

    marcas = {int(r["puesto"]): r for r in
              q(db, "SELECT * FROM comanda_puestos WHERE comanda_id=:c", {"c": cid})}

    con_pedido, valor = {}, {}
    for i in items:
        if i.get("estado") == "anulado":
            continue
        p = int(i.get("puesto") or 0)
        con_pedido[p] = con_pedido.get(p, 0) + 1
        valor[p] = valor.get(p, 0.0) + float(i["cantidad"]) * float(i["precio_unit"])

    salida = []
    for p in range(1, personas + 1):
        m = marcas.get(p) or {}
        n = con_pedido.get(p, 0)
        sin = bool(int(m.get("sin_consumo") or 0))
        salida.append({
            "puesto": p,
            "nombre": m.get("nombre"),
            "sin_consumo": sin,
            "platos": n,
            "valor": round(valor.get(p, 0.0), 2),
            # pidio / sin_consumo / pendiente — los tres estados posibles, y
            # el tercero es el que obliga a volver a la mesa.
            "estado": "pidio" if n else ("sin_consumo" if sin else "pendiente"),
        })
    return salida


def _totales(items: list[dict]) -> dict:
    sub = iva = 0.0
    for i in items:
        if i["estado"] == "anulado":
            continue
        linea = float(i["cantidad"]) * float(i["precio_unit"])
        sub += linea
        iva += linea * float(i.get("iva_pct") or 0) / 100.0
    return {"subtotal": round(sub, 2), "impuestos": round(iva, 2),
            "total": round(sub + iva, 2)}


# ══════════════════════════════════════════════════════════════════════
#  LÍNEAS
# ══════════════════════════════════════════════════════════════════════
@router.post("/api/comandas/{cid}/items", status_code=201)
def items_agregar(cid: int, body: dict = Body(...),
                  cur: dict = Depends(require_rol(*ROLES_COMANDA)),
                  db: Session = Depends(get_tenant_db)):
    """Agrega líneas. El PRECIO lo resuelve el servidor contra el catálogo:
    lo que envíe el cliente se ignora."""
    comanda = q1(db, "SELECT * FROM comandas WHERE id=:i", {"i": cid})
    if not comanda:
        raise HTTPException(404, "Comanda no encontrada")
    if comanda["estado"] in ("cerrada", "anulada"):
        raise HTTPException(409, "La comanda ya está cerrada")

    entradas = body.get("items") or []
    if not entradas:
        raise HTTPException(400, "No se indicó ningún producto")

    agregadas = []
    try:
        for it in entradas:
            pid = int(it.get("producto_id") or 0)
            cant = float(it.get("cantidad") or 1)
            # El puesto se acota al número de comensales de la mesa: un plato
            # para el puesto 7 en una mesa de cuatro es un error de digitación,
            # y guardarlo produce un renglón que nadie va a poder servir.
            try:
                puesto = int(it.get("puesto") or 0)
            except (TypeError, ValueError):
                puesto = 0
            tope = int(comanda.get("personas") or 0)
            if puesto < 0 or (tope and puesto > tope):
                raise HTTPException(
                    400, f"El puesto {puesto} no existe: la mesa es para {tope} persona(s)")
            if cant <= 0:
                raise HTTPException(400, "Las cantidades deben ser mayores que cero")
            prod = q1(db, "SELECT id, nombre, precio, iva_pct, estacion_id FROM productos "
                          "WHERE id=:i AND activo=1", {"i": pid})
            if not prod:
                raise HTTPException(400, f"El producto {pid} no existe o está inactivo")

            res = run_sin_commit(db,
                                 "INSERT INTO comanda_items (comanda_id, producto_id, nombre, "
                                 "cantidad, precio_unit, iva_pct, estacion_id, puesto, estado, notas) "
                                 "VALUES (:c,:p,:n,:q,:pr,:iva,:e,:pu,'pendiente',:no)",
                                 {"c": cid, "p": pid, "n": prod["nombre"], "q": cant,
                                  "pr": float(prod["precio"]), "iva": float(prod["iva_pct"] or 0),
                                  "e": prod["estacion_id"],
                                  "no": (it.get("notas") or "")[:240] or None,
                                  "pu": puesto})
            agregadas.append({"id": int(res.lastrowid or 0), "nombre": prod["nombre"],
                              "cantidad": cant})
        # Reabre la comanda si estaba servida y llega un pedido nuevo.
        if comanda["estado"] == "servida":
            run_sin_commit(db, "UPDATE comandas SET estado='abierta' WHERE id=:i", {"i": cid})
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True, "items": agregadas}


@router.delete("/api/comandas/items/{item_id}")
def item_anular(item_id: int, body: dict = Body(default={}),
                cur: dict = Depends(require_rol(*ROLES_COMANDA)),
                db: Session = Depends(get_tenant_db)):
    item = q1(db, "SELECT * FROM comanda_items WHERE id=:i", {"i": item_id})
    if not item:
        raise HTTPException(404, "Línea no encontrada")
    if item["estado"] == "entregado":
        raise HTTPException(
            409, "La línea ya fue entregada. Si el cliente la devolvió, regístrela en "
                 "Pérdidas con su motivo: el producto ya se preparó y consumió insumos.")
    run(db, "UPDATE comanda_items SET estado='anulado' WHERE id=:i", {"i": item_id})
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════
#  ENVÍO A COCINA
# ══════════════════════════════════════════════════════════════════════
@router.post("/api/comandas/{cid}/enviar")
def enviar_a_cocina(cid: int, cur: dict = Depends(require_rol(*ROLES_COMANDA)),
                    db: Session = Depends(get_tenant_db)):
    """Marca las líneas pendientes como enviadas y las hace visibles en la cola
    de su estación. La marca de tiempo es la que permite medir después cuánto
    tardó cada plato."""
    comanda = q1(db, "SELECT * FROM comandas WHERE id=:i", {"i": cid})
    if not comanda:
        raise HTTPException(404, "Comanda no encontrada")

    pendientes = q(db, "SELECT id, estacion_id FROM comanda_items "
                       "WHERE comanda_id=:c AND estado='pendiente'", {"c": cid})
    if not pendientes:
        raise HTTPException(409, "No hay líneas pendientes de enviar")

    run(db, "UPDATE comanda_items SET estado='en_preparacion', enviado_ts=:ts "
            "WHERE comanda_id=:c AND estado='pendiente'", {"ts": ahora(), "c": cid})
    run(db, "UPDATE comandas SET estado='en_cocina' WHERE id=:i", {"i": cid})
    return {"ok": True, "enviadas": len(pendientes)}


# ══════════════════════════════════════════════════════════════════════
#  COCINA · pantalla de preparación (KDS)
# ══════════════════════════════════════════════════════════════════════
@router.get("/api/cocina/cola")
def cola(estacion_id: int = 0, cur: dict = Depends(require_rol(*ROLES_COCINA)),
         db: Session = Depends(get_tenant_db)):
    """Cola de preparación agrupada por estación.

    Se ordena por antigüedad del envío, no por número de comanda: en cocina
    manda quién lleva más esperando, no quién pidió primero en otra mesa.
    """
    where = ["i.estado IN ('en_preparacion','listo')"]
    params = {}
    if estacion_id:
        where.append("i.estacion_id = :e")
        params["e"] = estacion_id

    filas = serial(q(db,
                     "SELECT i.*, c.numero AS comanda, c.tipo, m.codigo AS mesa, "
                     "       c.mesero, COALESCE(e.nombre,'Sin estación') AS estacion, "
                     "       COALESCE(e.color,'#94a3b8') AS estacion_color, "
                     "       p.minutos_prep "
                     "FROM comanda_items i "
                     "JOIN comandas c ON c.id = i.comanda_id "
                     "JOIN productos p ON p.id = i.producto_id "
                     "LEFT JOIN mesas m ON m.id = c.mesa_id "
                     "LEFT JOIN estaciones e ON e.id = i.estacion_id "
                     "WHERE " + " AND ".join(where) +
                     " ORDER BY i.enviado_ts, i.id", params))

    for f in filas:
        f["minutos"] = _minutos(f.get("enviado_ts"))
        objetivo = int(f.get("minutos_prep") or 5)
        # Semáforo: verde dentro del tiempo, ámbar al superarlo, rojo al doble.
        # Es la información que hace útil una pantalla de cocina.
        f["alerta"] = ("retrasado" if (f["minutos"] or 0) > objetivo * 2
                       else ("atencion" if (f["minutos"] or 0) > objetivo else "ok"))

    estaciones = serial(q(db, "SELECT e.id, e.nombre, e.color, e.icono, "
                              "  (SELECT COUNT(*) FROM comanda_items i "
                              "    WHERE i.estacion_id=e.id AND i.estado='en_preparacion') AS pendientes "
                              "FROM estaciones e WHERE e.activo=1 ORDER BY e.orden"))

    return {"ok": True, "items": filas, "estaciones": estaciones,
            "kpis": {"en_preparacion": sum(1 for f in filas if f["estado"] == "en_preparacion"),
                     "listos": sum(1 for f in filas if f["estado"] == "listo"),
                     "retrasados": sum(1 for f in filas if f["alerta"] == "retrasado")}}


def _minutos(ts: str | None) -> int | None:
    if not ts:
        return None
    try:
        inicio = datetime.datetime.fromisoformat(ts)
        if inicio.tzinfo is None:
            inicio = inicio.replace(tzinfo=datetime.timezone.utc)
        return max(0, int((datetime.datetime.now(datetime.timezone.utc) - inicio)
                          .total_seconds() // 60))
    except Exception:
        return None


@router.post("/api/cocina/items/{item_id}/estado")
def item_estado(item_id: int, body: dict = Body(...), cur: dict = Depends(verify_token),
                db: Session = Depends(get_tenant_db)):
    """Avanza el estado de una línea validando la transición.

    Cocina marca `listo`; el mesero marca `entregado`. Que sean roles distintos
    no es burocracia: es lo que permite medir cuánto tarda un plato listo en
    llegar a la mesa, que suele ser donde se pierde la temperatura.
    """
    nuevo = (body.get("estado") or "").strip()
    if nuevo not in ESTADOS_ITEM:
        raise HTTPException(400, f"Estado inválido: {nuevo}")

    item = q1(db, "SELECT * FROM comanda_items WHERE id=:i", {"i": item_id})
    if not item:
        raise HTTPException(404, "Línea no encontrada")
    if nuevo not in _SIGUIENTE.get(item["estado"], set()):
        raise HTTPException(409, f"No se puede pasar de «{item['estado']}» a «{nuevo}»")

    rol = cur.get("rol")
    es_super = int(cur.get("es_superadmin") or 0) == 1
    if nuevo in ("en_preparacion", "listo") and rol not in ROLES_COCINA and not es_super:
        raise HTTPException(403, "Solo cocina puede marcar la preparación")
    if nuevo == "entregado" and rol not in ROLES_COMANDA and not es_super:
        raise HTTPException(403, "Solo el personal de salón puede marcar la entrega")

    columna = {"listo": "listo_ts", "entregado": "entregado_ts"}.get(nuevo)
    sets = "estado=:e" + (f", {columna}=:ts" if columna else "")
    params = {"e": nuevo, "i": item_id}
    if columna:
        params["ts"] = ahora()
    run(db, f"UPDATE comanda_items SET {sets} WHERE id=:i", params)

    # Si ya no queda nada por preparar ni por entregar, la comanda pasa a
    # «servida»: la caja sabe que puede cobrar.
    fila = q1(db, "SELECT COUNT(*) AS n FROM comanda_items WHERE comanda_id=:c "
                  "AND estado IN ('pendiente','en_preparacion','listo')",
              {"c": item["comanda_id"]})
    if not int((fila or {}).get("n") or 0):
        run(db, "UPDATE comandas SET estado='servida' WHERE id=:i AND estado<>'cerrada'",
            {"i": item["comanda_id"]})

    return {"ok": True, "estado": nuevo}


# ══════════════════════════════════════════════════════════════════════
#  CIERRE — entrega la cuenta a la caja
# ══════════════════════════════════════════════════════════════════════
@router.post("/api/comandas/{cid}/cerrar")
def comanda_cerrar(cid: int, cur: dict = Depends(require_rol(*ROLES_COMANDA)),
                   db: Session = Depends(get_tenant_db)):
    """Prepara la cuenta. NO cobra: devuelve el detalle para que la caja lo
    convierta en venta. La separación es la que permite dividir la cuenta,
    aplicar descuentos o cambiar el medio de pago sin tocar el servicio."""
    comanda = q1(db, "SELECT c.*, m.codigo AS mesa FROM comandas c "
                     "LEFT JOIN mesas m ON m.id=c.mesa_id WHERE c.id=:i", {"i": cid})
    if not comanda:
        raise HTTPException(404, "Comanda no encontrada")
    if comanda["estado"] == "cerrada":
        raise HTTPException(409, "La comanda ya fue cobrada")

    items = serial(q(db, "SELECT * FROM comanda_items WHERE comanda_id=:c "
                         "AND estado<>'anulado'", {"c": cid}))
    if not items:
        raise HTTPException(409, "La comanda no tiene productos")

    sin_entregar = [i for i in items if i["estado"] != "entregado"]
    totales = _totales(items)

    perfil = q1(db, "SELECT propina_pct FROM sede_perfil WHERE id=1") or {}
    pct = float(perfil.get("propina_pct") or 10)
    return {"ok": True, "comanda": serial(dict(comanda))[0], "items": items,
            "totales": totales,
            # La propina se SUGIERE, nunca se impone: por ley es voluntaria y el
            # cliente debe poder rechazarla sin fricción. El porcentaje es
            # configurable por sede, no una constante del código.
            "propina_pct": pct,
            "propina_sugerida": round(totales["subtotal"] * pct / 100.0, 2),
            "advertencia": (f"{len(sin_entregar)} producto(s) aún no se han entregado."
                            if sin_entregar else None)}


# ══════════════════════════════════════════════════════════════════════
#  ASIENTOS DE LA MESA
# ══════════════════════════════════════════════════════════════════════
@router.put("/api/comandas/{cid}/personas")
def comanda_personas(cid: int, body: dict = Body(...),
                     cur: dict = Depends(require_rol(*ROLES_COMANDA)),
                     db: Session = Depends(get_tenant_db)):
    """Declara cuántas personas se sentaron.

    No se puede reducir por debajo del asiento más alto que ya pidió: eso
    dejaría platos huérfanos, asignados a un puesto que dejó de existir.
    """
    comanda = q1(db, "SELECT * FROM comandas WHERE id=:i", {"i": cid})
    if not comanda:
        raise HTTPException(404, "Comanda no encontrada")
    if comanda["estado"] in ("cerrada", "anulada"):
        raise HTTPException(409, "La comanda ya está cerrada")

    try:
        personas = int(body.get("personas") or 0)
    except (TypeError, ValueError):
        personas = 0
    if personas < 1:
        raise HTTPException(400, "Indique cuántas personas hay en la mesa")
    if personas > 40:
        raise HTTPException(400, "Para grupos de más de 40 use varias mesas")

    tope = q1(db, "SELECT COALESCE(MAX(puesto),0) AS m FROM comanda_items "
                  "WHERE comanda_id=:c AND estado <> 'anulado'", {"c": cid}) or {}
    maximo = int(tope.get("m") or 0)
    if personas < maximo:
        raise HTTPException(
            409, f"No se puede bajar a {personas}: el asiento {maximo} ya tiene pedido. "
                 "Anule primero esos platos o reasígnelos.")

    # Al reducir la mesa, las marcas de los asientos que dejan de existir se
    # borran. Dejarlas produciría un «no quiere nada» de alguien que se fue.
    run(db, "DELETE FROM comanda_puestos WHERE comanda_id=:c AND puesto > :p",
        {"c": cid, "p": personas})
    run(db, "UPDATE comandas SET personas=:p WHERE id=:i", {"p": personas, "i": cid})
    return {"ok": True, "personas": personas,
            "mensaje": f"La mesa quedó con {personas} persona(s)."}


@router.put("/api/comandas/{cid}/puestos/{puesto}")
def comanda_puesto(cid: int, puesto: int, body: dict = Body(...),
                   cur: dict = Depends(require_rol(*ROLES_COMANDA)),
                   db: Session = Depends(get_tenant_db)):
    """Marca un asiento como «no quiere nada», o le pone nombre.

    Marcar sin consumo es una AFIRMACIÓN del mesero —«ya le pregunté»—, no
    una consecuencia de que el asiento esté vacío. Por eso se guarda.
    """
    comanda = q1(db, "SELECT * FROM comandas WHERE id=:i", {"i": cid})
    if not comanda:
        raise HTTPException(404, "Comanda no encontrada")
    personas = int(comanda.get("personas") or 0)
    if puesto < 1 or (personas and puesto > personas):
        raise HTTPException(400, f"El asiento {puesto} no existe en esta mesa")

    sin = 1 if body.get("sin_consumo") else 0
    if sin:
        n = q1(db, "SELECT COUNT(*) AS n FROM comanda_items "
                   "WHERE comanda_id=:c AND puesto=:p AND estado <> 'anulado'",
               {"c": cid, "p": puesto}) or {}
        if int(n.get("n") or 0):
            raise HTTPException(
                409, f"El asiento {puesto} ya tiene platos. No se puede marcar "
                     "como «no quiere nada».")

    nombre = (body.get("nombre") or "").strip()[:120] or None
    run(db, "INSERT INTO comanda_puestos (comanda_id, puesto, sin_consumo, nombre, "
            "actualizado_en) VALUES (:c,:p,:s,:n,:ts) "
            "ON DUPLICATE KEY UPDATE sin_consumo=:s, nombre=:n, actualizado_en=:ts",
        {"c": cid, "p": puesto, "s": sin, "n": nombre, "ts": ahora()})
    return {"ok": True,
            "mensaje": (f"Asiento {puesto}: no consume." if sin
                        else f"Asiento {puesto} disponible para pedir.")}
