# -*- coding: utf-8 -*-
"""
================================================================
  RESTAURANTE · ESCANDALLO — ficha técnica de costo por plato
================================================================
Implementa el método estándar de costeo de recetas (recipe cost card), el mismo
que usa la industria y que la hoja de cálculo aportada por el usuario formaliza.

Su aporte sobre una receta simple es que el costo de un plato **no es solo el de
sus ingredientes**:

    Ingredientes primarios      la proteína, el eje del plato
  + Ingredientes secundarios    guarniciones, salsas, acompañamientos
  + Costos indirectos           preparación, gas, energía, agua, empaque
  ─────────────────────────────
  = COSTO TOTAL DEL PLATO

    Food cost %  =  costo total / precio de venta
    Utilidad     =  precio de venta − costo total

POR QUÉ IMPORTAN LOS INDIRECTOS
-------------------------------
En el ejemplo de referencia, un plato de salmón lleva $4,70 de pescado. Sumados
guarniciones ($1,15) y servicios ($2,33), cuesta $8,18: **el 43 % del costo no
está en los ingredientes**. Un sistema que solo suma la receta reporta un margen
inflado, y sobre esa cifra alguien fija precios que no cubren la operación.

EL FOOD COST ES EL INDICADOR DEL NEGOCIO
----------------------------------------
La referencia del sector ronda el 30 %. Por encima del 35 % el plato compromete
la rentabilidad; muy por debajo del 25 % suele indicar que está caro para su
mercado. Por eso se calcula y se semaforiza, en vez de dejarlo al criterio de
quien mire la tabla.

MERMA DE PREPARACIÓN
--------------------
Un kilo de papa no rinde un kilo pelado. Cada ingrediente admite un porcentaje
de merma que ajusta el consumo real:

    consumo_real = cantidad / (1 − merma%)

Ignorarla subestima sistemáticamente el costo de todo plato con producto fresco.

Autor: Arquitectura de Software · Unidad 1
================================================================
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from db import q, q1, run, serial
from dependencias import get_tenant_db
from seguridad import require_rol, verify_token

router = APIRouter(tags=["Escandallo"])

ROLES_COSTEO = ("admin", "gerente", "cocina")

# Umbrales del sector para semaforizar el food cost.
FOOD_COST_OBJETIVO = 30.0
FOOD_COST_ALERTA = 35.0


def _consumo_real(cantidad: float, merma_pct: float) -> float:
    """Cantidad que hay que comprar para obtener `cantidad` ya limpia.

    Se protege contra una merma del 100 %, que dividiría por cero: si alguien la
    digita, se trata como 99 % — no existe un ingrediente del que no quede nada.
    """
    merma = min(float(merma_pct or 0), 99.0)
    return float(cantidad or 0) / (1.0 - merma / 100.0)


def calcular(db: Session, producto_id: int) -> dict:
    """Ficha de costo completa de un producto."""
    prod = q1(db, "SELECT p.*, COALESCE(c.nombre,'Sin categoría') AS categoria "
                  "FROM productos p LEFT JOIN cat_categorias c ON c.id=p.categoria_id "
                  "WHERE p.id=:i", {"i": producto_id})
    if not prod:
        raise HTTPException(404, "Producto no encontrado")

    filas = q(db, "SELECT r.*, i.codigo, i.nombre, i.costo_prom, "
                  "       COALESCE(u.nombre,'') AS unidad "
                  "FROM receta r JOIN insumos i ON i.id=r.insumo_id "
                  "LEFT JOIN cat_unidades u ON u.id=i.unidad_id "
                  "WHERE r.producto_id=:p ORDER BY r.tipo DESC, i.nombre",
              {"p": producto_id})

    primarios, secundarios = [], []
    total_prim = total_sec = 0.0
    for f in serial([dict(x) for x in filas]):
        cantidad = float(f["cantidad"] or 0)
        merma = float(f.get("merma_pct") or 0)
        real = _consumo_real(cantidad, merma)
        costo = round(real * float(f["costo_prom"] or 0), 4)

        linea = {"insumo_id": f["insumo_id"], "codigo": f["codigo"], "nombre": f["nombre"],
                 "unidad": f["unidad"], "cantidad": cantidad, "merma_pct": merma,
                 "consumo_real": round(real, 4),
                 "costo_unitario": float(f["costo_prom"] or 0), "costo_total": costo}

        if (f.get("tipo") or "primario") == "primario":
            primarios.append(linea); total_prim += costo
        else:
            secundarios.append(linea); total_sec += costo

    indirectos = serial(q(db, "SELECT id, concepto, valor FROM producto_costos_ind "
                              "WHERE producto_id=:p ORDER BY orden, concepto",
                          {"p": producto_id}))
    total_ind = sum(float(i["valor"] or 0) for i in indirectos)

    costo_total = round(total_prim + total_sec + total_ind, 2)
    precio = float(prod["precio"] or 0)
    utilidad = round(precio - costo_total, 2)

    # Sobre precio cero el porcentaje no está definido. Devolver None es honesto;
    # devolver 0 haría creer que el plato no cuesta nada.
    food_cost = round(costo_total / precio * 100, 2) if precio else None
    margen = round(utilidad / precio * 100, 2) if precio else None

    if food_cost is None:
        semaforo, mensaje = "sin_precio", "El producto no tiene precio de venta asignado."
    elif food_cost > FOOD_COST_ALERTA:
        semaforo = "alto"
        mensaje = (f"El costo representa el {food_cost}% del precio. Por encima del "
                   f"{FOOD_COST_ALERTA:.0f}% el plato compromete la rentabilidad: revise "
                   f"porciones, proveedor o precio.")
    elif food_cost > FOOD_COST_OBJETIVO:
        semaforo = "atencion"
        mensaje = (f"Costo del {food_cost}%, por encima del objetivo de "
                   f"{FOOD_COST_OBJETIVO:.0f}%. Aceptable, pero con poco margen de maniobra.")
    elif food_cost < 20:
        semaforo = "revisar"
        mensaje = (f"Costo del {food_cost}%, muy por debajo de lo habitual. Verifique que "
                   f"la receta esté completa y que los costos indirectos estén cargados.")
    else:
        semaforo = "ok"
        mensaje = f"Costo del {food_cost}%, dentro del rango saludable del sector."

    # Precio sugerido para alcanzar el food cost objetivo. Es la pregunta que
    # sigue naturalmente a ver un plato caro: ¿en cuánto tendría que venderlo?
    precio_sugerido = round(costo_total / (FOOD_COST_OBJETIVO / 100), 0) if costo_total else 0

    return {
        "producto": {"id": prod["id"], "codigo": prod["codigo"], "nombre": prod["nombre"],
                     "categoria": prod["categoria"], "precio": precio,
                     "emoji": prod.get("emoji") or ""},
        "primarios": primarios,
        "secundarios": secundarios,
        "indirectos": indirectos,
        "totales": {
            "primarios": round(total_prim, 2),
            "secundarios": round(total_sec, 2),
            "indirectos": round(total_ind, 2),
            "costo_total": costo_total,
            "precio_venta": precio,
            "utilidad": utilidad,
            "food_cost_pct": food_cost,
            "margen_pct": margen,
            # Cuánto pesa cada bloque en el costo: revela si el problema está en
            # el producto o en la operación.
            "peso_primarios": round(total_prim / costo_total * 100, 1) if costo_total else 0,
            "peso_secundarios": round(total_sec / costo_total * 100, 1) if costo_total else 0,
            "peso_indirectos": round(total_ind / costo_total * 100, 1) if costo_total else 0,
        },
        "evaluacion": {"semaforo": semaforo, "mensaje": mensaje,
                       "objetivo_pct": FOOD_COST_OBJETIVO,
                       "precio_sugerido": precio_sugerido},
    }


# ══════════════════════════════════════════════════════════════════════
#  ENDPOINTS
# ══════════════════════════════════════════════════════════════════════
@router.get("/api/escandallo/{producto_id}")
def ficha(producto_id: int, cur: dict = Depends(verify_token),
          db: Session = Depends(get_tenant_db)):
    return {"ok": True, **calcular(db, producto_id)}


@router.get("/api/escandallo")
def resumen(cur: dict = Depends(require_rol(*ROLES_COSTEO)),
            db: Session = Depends(get_tenant_db)):
    """Food cost de toda la carta, ordenado por el más problemático primero.

    Es la vista que permite decidir qué platos revisar: no sirve saber el costo
    de uno si no se puede compararlo con el resto.
    """
    productos = q(db, "SELECT id FROM productos WHERE activo=1 ORDER BY nombre")
    items = []
    for p in productos:
        fic = calcular(db, int(p["id"]))
        items.append({**fic["producto"], **fic["totales"],
                      "semaforo": fic["evaluacion"]["semaforo"],
                      "precio_sugerido": fic["evaluacion"]["precio_sugerido"]})

    con_precio = [i for i in items if i["food_cost_pct"] is not None]
    items.sort(key=lambda x: -(x["food_cost_pct"] or 0))

    return {"ok": True, "items": items,
            "kpis": {
                "productos": len(items),
                "food_cost_promedio": round(
                    sum(i["food_cost_pct"] for i in con_precio) / len(con_precio), 2)
                    if con_precio else None,
                "criticos": sum(1 for i in items if i["semaforo"] == "alto"),
                "sin_indirectos": sum(1 for i in items if not i["indirectos"]),
                "objetivo_pct": FOOD_COST_OBJETIVO}}


@router.get("/api/escandallo/catalogos/costos")
def catalogo_costos(cur: dict = Depends(verify_token), db: Session = Depends(get_tenant_db)):
    return {"ok": True,
            "conceptos": serial(q(db, "SELECT id, nombre, valor_def FROM cat_costos_ind "
                                      "WHERE activo=1 ORDER BY orden, nombre"))}


@router.put("/api/escandallo/{producto_id}/receta")
def receta_guardar(producto_id: int, body: dict = Body(...),
                   cur: dict = Depends(require_rol(*ROLES_COSTEO)),
                   db: Session = Depends(get_tenant_db)):
    """Reemplaza la receta completa, con tipo y merma por línea.

    El reemplazo total es trivialmente correcto: no hay forma de dejar una línea
    huérfana que el usuario creyó haber borrado.
    """
    if not q1(db, "SELECT id FROM productos WHERE id=:i", {"i": producto_id}):
        raise HTTPException(404, "Producto no encontrado")

    limpios, vistos = [], set()
    for it in body.get("items") or []:
        iid = int(it.get("insumo_id") or 0)
        cant = float(it.get("cantidad") or 0)
        if not iid or cant <= 0:
            continue
        if iid in vistos:
            raise HTTPException(400, "La receta tiene el mismo insumo repetido")
        if not q1(db, "SELECT id FROM insumos WHERE id=:i AND activo=1", {"i": iid}):
            raise HTTPException(400, f"El insumo {iid} no existe o está inactivo")
        merma = float(it.get("merma_pct") or 0)
        if not 0 <= merma < 100:
            raise HTTPException(400, "La merma debe estar entre 0 y 99 %")
        tipo = "secundario" if (it.get("tipo") == "secundario") else "primario"
        vistos.add(iid)
        limpios.append((iid, cant, tipo, merma))

    run(db, "DELETE FROM receta WHERE producto_id=:p", {"p": producto_id})
    for iid, cant, tipo, merma in limpios:
        run(db, "INSERT INTO receta (producto_id, insumo_id, cantidad, tipo, merma_pct) "
                "VALUES (:p,:i,:q,:t,:m)",
            {"p": producto_id, "i": iid, "q": cant, "t": tipo, "m": merma})
    return {"ok": True, **calcular(db, producto_id)}


@router.put("/api/escandallo/{producto_id}/indirectos")
def indirectos_guardar(producto_id: int, body: dict = Body(...),
                       cur: dict = Depends(require_rol(*ROLES_COSTEO)),
                       db: Session = Depends(get_tenant_db)):
    """Reemplaza los costos indirectos del producto."""
    if not q1(db, "SELECT id FROM productos WHERE id=:i", {"i": producto_id}):
        raise HTTPException(404, "Producto no encontrado")

    run(db, "DELETE FROM producto_costos_ind WHERE producto_id=:p", {"p": producto_id})
    for orden, it in enumerate(body.get("items") or []):
        concepto = (it.get("concepto") or "").strip()
        valor = float(it.get("valor") or 0)
        if not concepto or valor < 0:
            continue
        run(db, "INSERT INTO producto_costos_ind (producto_id, concepto, valor, orden) "
                "VALUES (:p,:c,:v,:o) ON DUPLICATE KEY UPDATE valor=VALUES(valor)",
            {"p": producto_id, "c": concepto[:80], "v": valor, "o": orden})
    return {"ok": True, **calcular(db, producto_id)}


@router.post("/api/escandallo/{producto_id}/indirectos/plantilla")
def aplicar_plantilla(producto_id: int, cur: dict = Depends(require_rol(*ROLES_COSTEO)),
                      db: Session = Depends(get_tenant_db)):
    """Carga los conceptos de la plantilla con sus valores por defecto.

    Evita redigitar gas, agua y energía en cada uno de los platos de la carta,
    que es la razón por la que en la práctica esos costos nunca se cargan.
    """
    if not q1(db, "SELECT id FROM productos WHERE id=:i", {"i": producto_id}):
        raise HTTPException(404, "Producto no encontrado")

    conceptos = q(db, "SELECT nombre, valor_def, orden FROM cat_costos_ind "
                      "WHERE activo=1 ORDER BY orden")
    for c in conceptos:
        run(db, "INSERT INTO producto_costos_ind (producto_id, concepto, valor, orden) "
                "VALUES (:p,:c,:v,:o) ON DUPLICATE KEY UPDATE producto_id=producto_id",
            {"p": producto_id, "c": c["nombre"], "v": float(c["valor_def"] or 0),
             "o": c["orden"]})
    return {"ok": True, "aplicados": len(conceptos), **calcular(db, producto_id)}


@router.post("/api/escandallo/aplicar-plantilla-masivo")
def plantilla_masiva(cur: dict = Depends(require_rol("admin", "gerente")),
                     db: Session = Depends(get_tenant_db)):
    """Aplica la plantilla a todos los productos que aún no tienen indirectos.

    No pisa lo ya configurado: quien ajustó el costo de un plato en particular
    tenía una razón, y una carga masiva no debe borrarla.
    """
    pendientes = q(db, "SELECT p.id FROM productos p WHERE p.activo=1 "
                       "AND NOT EXISTS (SELECT 1 FROM producto_costos_ind x "
                       "                 WHERE x.producto_id = p.id)")
    conceptos = q(db, "SELECT nombre, valor_def, orden FROM cat_costos_ind WHERE activo=1")
    for p in pendientes:
        for c in conceptos:
            run(db, "INSERT INTO producto_costos_ind (producto_id, concepto, valor, orden) "
                    "VALUES (:p,:c,:v,:o) ON DUPLICATE KEY UPDATE producto_id=producto_id",
                {"p": p["id"], "c": c["nombre"], "v": float(c["valor_def"] or 0),
                 "o": c["orden"]})
    return {"ok": True, "productos": len(pendientes), "conceptos": len(conceptos)}
