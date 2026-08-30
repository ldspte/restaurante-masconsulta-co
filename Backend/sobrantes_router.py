# -*- coding: utf-8 -*-
"""
================================================================
  RESTAURANTE · APROVECHAMIENTO DE SOBRANTES  (el calentado)
================================================================
El módulo que separa un punto de venta genérico de un sistema hecho para una
cafetería de barrio.

EL PROBLEMA QUE RESUELVE
------------------------
A las nueve de la noche la cocina apaga la estufa y en las ollas queda comida.
Un inventario común solo conoce dos destinos para eso: se vendió o se perdió.
En la realidad hay un tercero, y es el que sostiene el margen del negocio: el
arroz, los fríjoles y la carne de hoy son el calentado de mañana a las seis de
la mañana. El pan que no se vendió hoy se vende mañana a mitad de precio.

Ese tercer estado necesita algo que el inventario normal no tiene: **un reloj**.
Un bulto de harina se vence en meses; una olla de arroz cocido, en veinticuatro
horas. Por eso el sobrante no es un saldo, es un **lote con fecha de muerte**.

LAS TRES REGLAS DEL MÓDULO
--------------------------
1. **No todo se guarda.** Solo los insumos con `apto_calentado = 1` pueden ir
   al pool. La leche, los jugos y la ensalada no aparecen siquiera como opción.
   Es una decisión sanitaria y el sistema no la deja negociar.

2. **Todo lote tiene temperatura y responsable.** Sin registro de cadena de
   frío no hay defensa ante una visita de la autoridad sanitaria
   (Resolución 2674 de 2013). El campo no es opcional.

3. **Lo vencido se pierde solo.** Al abrir el día, lo que pasó su hora se
   convierte en pérdida contable sin que nadie decida nada. Si vencer
   dependiera de que alguien se acuerde, el pool se volvería un cementerio
   donde todo figura «disponible» para siempre.

CÓMO SE CONSUME
---------------
Aquí está la parte elegante, y es puro bus de eventos: **este módulo no toca
la venta**. Cuando se vende un calentado, Inventario descuenta arroz y
fríjoles como con cualquier otra receta. Este módulo, suscrito al MISMO
evento, marca los lotes consumidos por orden de vencimiento (FIFO por
caducidad, no por entrada). Ni Caja ni Inventario saben que existe.

Quitar este archivo y su suscripción deja el sistema funcionando igual, solo
que sin trazabilidad de sobrantes. Eso es acoplamiento cero.

CONTABILIDAD — por qué guardar NO genera asiento
-------------------------------------------------
Decisión deliberada. La comida guardada para calentado **no ha perdido valor**:
sigue en la bodega, sigue costando lo que costó y se va a vender. Castigarla
contablemente al guardarla obligaría a sostener una reconciliación permanente
entre el kardex y la cuenta 1435 a cambio de ninguna información nueva.

El castigo ocurre cuando corresponde: si el lote vence sin usarse, ahí sí es
una merma real y se contabiliza como tal. Los otros dos destinos —consumo del
personal y merma directa— reutilizan los eventos que ya existen.

Rutas
  GET   /api/sobrantes/candidatos      qué hay en la cocina y se puede guardar
  POST  /api/sobrantes/cierre          cierra la cocina del día
  GET   /api/sobrantes/pool            lotes vigentes, por vencimiento
  POST  /api/sobrantes/vencer          barre lo vencido (se llama al abrir)
  POST  /api/sobrantes/{id}/descartar  bota un lote antes de que venza
  GET   /api/sobrantes/cierres         historial de cierres
  GET   /api/sobrantes/tablero         cuánto se salvó y cuánto se botó

Autor: Arquitectura de Software · Unidad 1
================================================================
"""
from __future__ import annotations

import datetime as dt
import logging

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from db import ahora_local, ahora, hoy, q, q1, run_sin_commit, serial
from eventos import Evento, TipoEvento, publicar
from dependencias import get_tenant_db
from seguridad import autor, require_rol, verify_token

log = logging.getLogger("restaurante.sobrantes")
router = APIRouter(tags=["Sobrantes"])

ROLES_COCINA = ("admin", "gerente", "cocina")
ROLES_CIERRE = ("admin", "gerente", "cocina")

DESTINOS = ("calentado", "consumo", "merma")

# Umbral de la cadena de frío. Por encima de esto, el alimento preparado no
# puede guardarse: no es una recomendación, es el límite de la norma.
TEMP_MAX_REFRIGERADO = 8.0


# ══════════════════════════════════════════════════════════════════════
#  UTILIDADES DE TIEMPO
# ══════════════════════════════════════════════════════════════════════
def _sumar_horas(horas: int) -> str:
    return (dt.datetime.now() + dt.timedelta(hours=int(horas or 0))).strftime("%Y-%m-%d %H:%M:%S")


def _horas_restantes(vence_en: str | None) -> float | None:
    """Horas que le quedan al lote. Negativo significa vencido."""
    if not vence_en:
        return None
    try:
        v = dt.datetime.strptime(str(vence_en)[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return round((v - dt.datetime.now()).total_seconds() / 3600.0, 1)


# ══════════════════════════════════════════════════════════════════════
#  CANDIDATOS — qué se puede guardar
# ══════════════════════════════════════════════════════════════════════
@router.get("/api/sobrantes/candidatos")
def candidatos(cur: dict = Depends(verify_token), db: Session = Depends(get_tenant_db)):
    """Lo que hay en existencia y admite aprovechamiento.

    Se devuelve el stock del sistema como SUGERENCIA, no como verdad. Lo que
    de verdad quedó en la olla lo sabe quien está en la cocina, y casi nunca
    coincide con el saldo teórico: parte se sirvió de más, parte se probó,
    parte se pegó al fondo. Por eso el cierre pide contar, no confirmar.
    """
    filas = q(db,
              "SELECT i.id, i.codigo, i.nombre, i.stock, i.costo_prom, i.vida_util_horas, "
              "       u.nombre AS unidad "
              "FROM insumos i LEFT JOIN cat_unidades u ON u.id = i.unidad_id "
              "WHERE i.activo = 1 AND i.apto_calentado = 1 "
              "ORDER BY i.nombre")
    items = []
    for f in filas:
        items.append({
            "insumo_id": f["id"], "codigo": f["codigo"], "nombre": f["nombre"],
            "stock_teorico": float(f["stock"] or 0),
            "costo_unit": float(f["costo_prom"] or 0),
            "vida_util_horas": int(f["vida_util_horas"] or 0),
            "unidad": f["unidad"] or "und",
        })

    ultimo = q1(db, "SELECT fecha, turno FROM cierres_cocina ORDER BY id DESC LIMIT 1")
    return {"ok": True, "items": items, "fecha": hoy(),
            "temp_max": TEMP_MAX_REFRIGERADO,
            "ultimo_cierre": dict(ultimo) if ultimo else None,
            "ya_cerrado_hoy": bool(ultimo and ultimo["fecha"] == hoy())}


# ══════════════════════════════════════════════════════════════════════
#  CIERRE DE COCINA
# ══════════════════════════════════════════════════════════════════════
@router.post("/api/sobrantes/cierre", status_code=201)
def cerrar_cocina(body: dict = Body(...), cur: dict = Depends(require_rol(*ROLES_CIERRE)),
                  db: Session = Depends(get_tenant_db)):
    """Registra qué quedó en la cocina y a dónde va cada cosa.

    Es una sola transacción a propósito: un cierre a medias —tres líneas
    guardadas y dos perdidas por un error en la cuarta— deja el inventario
    peor de como estaba. O queda todo el cierre, o no queda nada.
    """
    from inventario_router import mover

    fecha = (body.get("fecha") or hoy()).strip()[:10]
    turno = (body.get("turno") or "noche").strip()[:24]
    lineas = body.get("lineas") or []
    if not isinstance(lineas, list) or not lineas:
        raise HTTPException(400, "Indique al menos un renglón de sobrante")

    if q1(db, "SELECT id FROM cierres_cocina WHERE fecha=:f AND turno=:t",
          {"f": fecha, "t": turno}):
        raise HTTPException(409, f"La cocina del {fecha} ({turno}) ya fue cerrada")

    quien = autor(cur)
    ts = ahora()
    total = {"calentado": 0.0, "consumo": 0.0, "merma": 0.0}
    creadas: list[dict] = []

    try:
        res = run_sin_commit(db,
                             "INSERT INTO cierres_cocina (fecha, turno, responsable, estado, "
                             "observaciones, creado_en) VALUES (:f,:t,:r,'cerrado',:o,:ts)",
                             {"f": fecha, "t": turno, "r": quien,
                              "o": (body.get("observaciones") or "").strip() or None,
                              "ts": ts})
        cierre_id = int(res.lastrowid or 0)

        for n, ln in enumerate(lineas, start=1):
            insumo_id = int(ln.get("insumo_id") or 0)
            cantidad = round(float(ln.get("cantidad") or 0), 4)
            destino = (ln.get("destino") or "").strip().lower()

            if cantidad <= 0:
                raise HTTPException(400, f"Renglón {n}: la cantidad debe ser mayor que cero")
            if destino not in DESTINOS:
                raise HTTPException(400, f"Renglón {n}: destino inválido «{destino}»")

            ins = q1(db, "SELECT id, nombre, costo_prom, stock, apto_calentado, vida_util_horas "
                         "FROM insumos WHERE id=:i AND activo=1", {"i": insumo_id})
            if not ins:
                raise HTTPException(404, f"Renglón {n}: insumo no encontrado")

            costo_unit = float(ins["costo_prom"] or 0)
            valor = round(cantidad * costo_unit, 2)
            total[destino] += valor

            # ── Guardar para calentado ────────────────────────────────
            if destino == "calentado":
                if not int(ins["apto_calentado"] or 0):
                    raise HTTPException(
                        400, f"«{ins['nombre']}» no admite aprovechamiento. "
                             "Su destino solo puede ser consumo del personal o merma.")
                temp = ln.get("temperatura")
                if temp is None or str(temp).strip() == "":
                    raise HTTPException(
                        400, f"Renglón {n}: registre la temperatura de «{ins['nombre']}». "
                             "Sin cadena de frío documentada no se puede guardar.")
                temp = round(float(temp), 2)
                if temp > TEMP_MAX_REFRIGERADO:
                    raise HTTPException(
                        400, f"«{ins['nombre']}» está a {temp} °C. Por encima de "
                             f"{TEMP_MAX_REFRIGERADO} °C el alimento preparado no puede "
                             "guardarse: debe registrarse como merma.")

                horas = int(ins["vida_util_horas"] or 24)
                vence = _sumar_horas(horas)
                r2 = run_sin_commit(db,
                                    "INSERT INTO sobrantes (cierre_id, insumo_id, cantidad, "
                                    "disponible, costo_unit, valor, destino, temperatura, "
                                    "vence_en, estado, responsable, observacion, creado_en) "
                                    "VALUES (:c,:i,:q,:q,:cu,:v,'calentado',:t,:ve,"
                                    "'disponible',:r,:o,:ts)",
                                    {"c": cierre_id, "i": insumo_id, "q": cantidad,
                                     "cu": costo_unit, "v": valor, "t": temp, "ve": vence,
                                     "r": quien,
                                     "o": (ln.get("observacion") or "").strip()[:240] or None,
                                     "ts": ts})
                lote_id = int(r2.lastrowid or 0)
                creadas.append({"id": lote_id, "insumo": ins["nombre"], "cantidad": cantidad,
                                "vence_en": vence, "valor": valor})

                # El lote NO mueve inventario: la comida sigue ahí, solo que
                # ahora tiene fecha de muerte. Ver la nota de contabilidad en
                # la cabecera del módulo.
                publicar(db, Evento(
                    tipo=TipoEvento.SOBRANTE_APROVECHADO, entidad="sobrante",
                    entidad_id=lote_id,
                    payload={"insumo_id": insumo_id, "insumo": ins["nombre"],
                             "cantidad": cantidad, "valor": valor, "vence_en": vence,
                             "temperatura": temp, "horas": horas},
                    usuario=quien))

            # ── Consumo del personal ──────────────────────────────────
            elif destino == "consumo":
                mover(db, insumo_id=insumo_id, tipo="salida", cantidad=cantidad,
                      costo_unit=costo_unit, ref_tipo="cierre_cocina", ref_id=cierre_id,
                      motivo="Sobrante al cierre — alimentación del personal",
                      usuario=quien, permitir_negativo=True)
                # No se escribe en `consumo_interno`: esa tabla registra platos
                # servidos al personal (lleva producto y beneficiario). Aquí lo
                # que se entrega es materia prima de la olla. Forzarla en esa
                # tabla obligaría a inventar un producto que nadie preparó.
                # El evento basta: es lo que la contabilidad necesita.
                publicar(db, Evento(
                    tipo=TipoEvento.CONSUMO_INTERNO, entidad="cierre_cocina",
                    entidad_id=cierre_id,
                    payload={"insumo_id": insumo_id, "producto": ins["nombre"],
                             "beneficiario": "Personal de cocina",
                             "cantidad": cantidad, "costo_total": valor,
                             "motivo": "Sobrante al cierre de cocina"},
                    usuario=quien))

            # ── Merma ─────────────────────────────────────────────────
            else:
                motivo = (ln.get("observacion") or "").strip() or "Sobrante no aprovechable"
                # NO se llama a `mover` aquí. `PERDIDA_REGISTRADA` ya tiene a
                # `inventario_router._descontar_por_perdida` suscrito, y hacer
                # ambas cosas descontaba la existencia dos veces.
                r3 = run_sin_commit(db,
                                    "INSERT INTO perdidas (ts, insumo_id, cantidad, costo_unit, "
                                    "costo_total, motivo, observacion, usuario) "
                                    "VALUES (:ts,:i,:q,:cu,:ct,:m,:o,:u)",
                                    {"ts": ts, "i": insumo_id, "q": cantidad, "cu": costo_unit,
                                     "ct": valor, "m": "Merma al cierre de cocina",
                                     "o": motivo[:240], "u": quien})
                publicar(db, Evento(
                    tipo=TipoEvento.PERDIDA_REGISTRADA, entidad="perdida",
                    entidad_id=int(r3.lastrowid or 0),
                    payload={"insumo_id": insumo_id, "insumo": ins["nombre"],
                             "cantidad": cantidad, "costo_unit": costo_unit,
                             "costo_total": valor, "motivo": "Merma al cierre de cocina"},
                    usuario=quien))

        run_sin_commit(db,
                       "UPDATE cierres_cocina SET val_calentado=:a, val_consumo=:c, "
                       "val_merma=:m, lineas=:n WHERE id=:id",
                       {"a": round(total["calentado"], 2), "c": round(total["consumo"], 2),
                        "m": round(total["merma"], 2), "n": len(lineas), "id": cierre_id})

        publicar(db, Evento(
            tipo=TipoEvento.COCINA_CERRADA, entidad="cierre_cocina", entidad_id=cierre_id,
            payload={"fecha": fecha, "turno": turno, "lineas": len(lineas),
                     "val_calentado": round(total["calentado"], 2),
                     "val_consumo": round(total["consumo"], 2),
                     "val_merma": round(total["merma"], 2)},
            usuario=quien))
        db.commit()
    except Exception:
        db.rollback()
        raise

    salvado = round(total["calentado"], 2)
    botado = round(total["merma"], 2)
    base = salvado + botado
    log.info("Cocina cerrada %s/%s: salvado %.2f, botado %.2f", fecha, turno, salvado, botado)
    return {"ok": True, "cierre_id": cierre_id, "fecha": fecha, "turno": turno,
            "val_calentado": salvado, "val_consumo": round(total["consumo"], 2),
            "val_merma": botado, "lotes": creadas,
            "aprovechamiento_pct": round(salvado / base * 100, 1) if base else None,
            "mensaje": (f"Cocina cerrada. Se guardaron ${salvado:,.0f} para el calentado "
                        f"y se dieron de baja ${botado:,.0f}.")}


# ══════════════════════════════════════════════════════════════════════
#  POOL — lo que hay guardado
# ══════════════════════════════════════════════════════════════════════
@router.get("/api/sobrantes/pool")
def pool(incluir_agotados: int = 0, cur: dict = Depends(verify_token),
         db: Session = Depends(get_tenant_db)):
    """Lotes vigentes, ordenados por el que vence primero.

    Ese orden no es cosmético: es el orden en que el sistema los consume y el
    orden en que la cocina debe usarlos. La pantalla muestra lo mismo que hace
    el motor, para que nadie tenga que adivinar cuál sacar de la nevera.
    """
    estados = "('disponible')" if not incluir_agotados else "('disponible','agotado','vencido')"
    filas = q(db,
              f"SELECT s.*, i.nombre AS insumo, i.codigo, u.nombre AS unidad "
              f"FROM sobrantes s "
              f"JOIN insumos i ON i.id = s.insumo_id "
              f"LEFT JOIN cat_unidades u ON u.id = i.unidad_id "
              f"WHERE s.destino='calentado' AND s.estado IN {estados} "
              f"ORDER BY s.vence_en, s.id LIMIT 200")

    items, valor_total, vencidos = [], 0.0, 0
    for f in filas:
        h = _horas_restantes(f["vence_en"])
        disp = float(f["disponible"] or 0)
        val = round(disp * float(f["costo_unit"] or 0), 2)
        if f["estado"] == "disponible":
            valor_total += val
            if h is not None and h < 0:
                vencidos += 1
        items.append({
            "id": f["id"], "insumo": f["insumo"], "codigo": f["codigo"],
            "unidad": f["unidad"] or "und",
            "cantidad": float(f["cantidad"] or 0), "disponible": disp,
            "costo_unit": float(f["costo_unit"] or 0), "valor": val,
            "temperatura": float(f["temperatura"]) if f["temperatura"] is not None else None,
            "vence_en": f["vence_en"], "horas_restantes": h,
            "estado": f["estado"], "responsable": f["responsable"],
            "creado_en": f["creado_en"],
            # Semáforo pensado para una cocina, no para un tablero: rojo es
            # «úselo hoy o bótelo», no «revise cuando pueda».
            "alerta": ("vencido" if (h is not None and h < 0)
                       else "urgente" if (h is not None and h <= 6)
                       else "pronto" if (h is not None and h <= 12)
                       else "ok"),
        })
    return {"ok": True, "items": items, "valor_disponible": round(valor_total, 2),
            "vencidos_sin_barrer": vencidos}


# ══════════════════════════════════════════════════════════════════════
#  VENCIMIENTO AUTOMÁTICO
# ══════════════════════════════════════════════════════════════════════
def barrer_vencidos(db: Session, usuario: str = "sistema") -> dict:
    """Convierte en pérdida todo lote que pasó su hora. NO hace commit.

    Es función suelta y no solo endpoint porque la llama el arranque del día
    además del botón. Que vencer dependa de que alguien se acuerde de oprimir
    algo convierte el pool en un cementerio donde todo figura «disponible».
    """
    from inventario_router import mover

    ahora_dt = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    filas = q(db, "SELECT s.*, i.nombre AS insumo FROM sobrantes s "
                  "JOIN insumos i ON i.id = s.insumo_id "
                  "WHERE s.estado='disponible' AND s.destino='calentado' "
                  "AND s.vence_en IS NOT NULL AND s.vence_en <= :n", {"n": ahora_dt})

    total, detalle = 0.0, []
    for f in filas:
        disp = round(float(f["disponible"] or 0), 4)
        costo = float(f["costo_unit"] or 0)
        valor = round(disp * costo, 2)

        run_sin_commit(db, "UPDATE sobrantes SET estado='vencido', disponible=0, "
                           "cerrado_en=:ts WHERE id=:id", {"ts": ahora(), "id": f["id"]})
        if disp <= 0:
            continue

        # El descuento lo hace el suscriptor de `PERDIDA_REGISTRADA`.
        r = run_sin_commit(db,
                           "INSERT INTO perdidas (ts, insumo_id, cantidad, costo_unit, "
                           "costo_total, motivo, observacion, usuario) "
                           "VALUES (:ts,:i,:q,:cu,:ct,:m,:o,:u)",
                           {"ts": ahora(), "i": f["insumo_id"], "q": disp, "cu": costo,
                            "ct": valor, "m": "Sobrante vencido",
                            "o": f"Lote #{f['id']} guardado el {f['creado_en']}", "u": usuario})
        publicar(db, Evento(
            tipo=TipoEvento.PERDIDA_REGISTRADA, entidad="perdida",
            entidad_id=int(r.lastrowid or 0),
            payload={"insumo_id": f["insumo_id"], "insumo": f["insumo"], "cantidad": disp,
                     "costo_unit": costo, "costo_total": valor, "motivo": "Sobrante vencido"},
            usuario=usuario))
        publicar(db, Evento(
            tipo=TipoEvento.SOBRANTE_VENCIDO, entidad="sobrante", entidad_id=int(f["id"]),
            payload={"insumo": f["insumo"], "cantidad": disp, "valor": valor},
            usuario=usuario))
        total += valor
        detalle.append({"lote": f["id"], "insumo": f["insumo"], "cantidad": disp,
                        "valor": valor})

    return {"lotes": len(filas), "perdidos": len(detalle),
            "valor": round(total, 2), "detalle": detalle}


@router.post("/api/sobrantes/vencer")
def vencer(cur: dict = Depends(require_rol(*ROLES_COCINA)),
           db: Session = Depends(get_tenant_db)):
    try:
        r = barrer_vencidos(db, autor(cur))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True, **r,
            "mensaje": (f"Se dieron de baja {r['perdidos']} lote(s) por ${r['valor']:,.0f}."
                        if r["perdidos"] else "No había lotes vencidos.")}


@router.post("/api/sobrantes/{lote_id}/descartar")
def descartar(lote_id: int, body: dict = Body(default={}),
              cur: dict = Depends(require_rol(*ROLES_COCINA)),
              db: Session = Depends(get_tenant_db)):
    """Bota un lote antes de que venza: se vio mal, olió mal, se cortó."""
    from inventario_router import mover

    f = q1(db, "SELECT s.*, i.nombre AS insumo FROM sobrantes s "
               "JOIN insumos i ON i.id = s.insumo_id WHERE s.id=:i", {"i": lote_id})
    if not f:
        raise HTTPException(404, "Lote no encontrado")
    if f["estado"] != "disponible":
        raise HTTPException(409, f"El lote ya está «{f['estado']}»")

    motivo = (body.get("motivo") or "").strip()
    if not motivo:
        raise HTTPException(400, "Diga por qué se descarta el lote")

    disp = round(float(f["disponible"] or 0), 4)
    costo = float(f["costo_unit"] or 0)
    valor = round(disp * costo, 2)
    quien = autor(cur)
    try:
        run_sin_commit(db, "UPDATE sobrantes SET estado='descartado', disponible=0, "
                           "cerrado_en=:ts, observacion=:o WHERE id=:i",
                       {"ts": ahora(), "o": motivo[:240], "i": lote_id})
        if disp > 0:
            # Igual que arriba: publicar el hecho basta, el suscriptor descuenta.
            r = run_sin_commit(db,
                               "INSERT INTO perdidas (ts, insumo_id, cantidad, costo_unit, "
                               "costo_total, motivo, observacion, usuario) "
                               "VALUES (:ts,:i,:q,:cu,:ct,'Sobrante descartado',:o,:u)",
                               {"ts": ahora(), "i": f["insumo_id"], "q": disp, "cu": costo,
                                "ct": valor, "o": motivo[:240], "u": quien})
            publicar(db, Evento(
                tipo=TipoEvento.PERDIDA_REGISTRADA, entidad="perdida",
                entidad_id=int(r.lastrowid or 0),
                payload={"insumo_id": f["insumo_id"], "insumo": f["insumo"], "cantidad": disp,
                         "costo_unit": costo, "costo_total": valor,
                         "motivo": "Sobrante descartado"},
                usuario=quien))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True, "valor": valor,
            "mensaje": f"Lote descartado. Se dieron de baja ${valor:,.0f}."}


# ══════════════════════════════════════════════════════════════════════
#  CONSUMO POR VENTA  —  el suscriptor
# ══════════════════════════════════════════════════════════════════════
def _consumir_por_venta(db: Session, evento: Evento) -> None:
    """Descuenta del pool lo que la venta acaba de gastar.

    Reacciona al MISMO evento que Inventario, sin que Inventario lo sepa.
    Aquí no se mueve stock —eso ya lo hizo Inventario—; solo se marca cuál
    lote se gastó, que es lo que permite responder «el calentado de hoy salió
    del arroz del martes» cuando alguien pregunte.

    Si el consumo excede lo guardado, la diferencia salió de producción
    fresca: se agota el lote y se sigue. No es un error.
    """
    items = evento.payload.get("items") or []
    if not items:
        return

    # Se expanden las recetas para saber cuánto insumo consumió la venta.
    necesidad: dict[int, float] = {}
    for it in items:
        pid = it.get("producto_id")
        cant = float(it.get("cantidad") or 0)
        if not pid or cant <= 0:
            continue
        for r in q(db, "SELECT insumo_id, cantidad FROM receta WHERE producto_id=:p",
                   {"p": pid}):
            iid = int(r["insumo_id"])
            necesidad[iid] = necesidad.get(iid, 0.0) + float(r["cantidad"] or 0) * cant

    if not necesidad:
        return

    for insumo_id, requerido in necesidad.items():
        restante = round(requerido, 4)
        lotes = q(db, "SELECT id, disponible FROM sobrantes "
                      "WHERE insumo_id=:i AND estado='disponible' AND destino='calentado' "
                      "ORDER BY vence_en, id", {"i": insumo_id})
        for lote in lotes:
            if restante <= 0:
                break
            disp = float(lote["disponible"] or 0)
            usar = min(disp, restante)
            queda = round(disp - usar, 4)
            run_sin_commit(db,
                           "UPDATE sobrantes SET disponible=:d, estado=:e, cerrado_en=:ts "
                           "WHERE id=:i",
                           {"d": queda, "e": "agotado" if queda <= 0 else "disponible",
                            "ts": ahora() if queda <= 0 else None, "i": lote["id"]})
            restante = round(restante - usar, 4)


def registrar_suscriptores() -> None:
    """Cableado del módulo. Se invoca desde `cablear_eventos()` en main.py."""
    from eventos import suscribir
    suscribir(TipoEvento.VENTA_REGISTRADA, _consumir_por_venta)


# ══════════════════════════════════════════════════════════════════════
#  HISTORIAL Y TABLERO
# ══════════════════════════════════════════════════════════════════════
@router.get("/api/sobrantes/cierres")
def cierres(limite: int = 30, cur: dict = Depends(verify_token),
            db: Session = Depends(get_tenant_db)):
    limite = max(1, min(int(limite or 30), 120))
    filas = serial(q(db, "SELECT * FROM cierres_cocina ORDER BY fecha DESC, id DESC "
                         "LIMIT :l", {"l": limite}))
    for f in filas:
        base = float(f["val_calentado"] or 0) + float(f["val_merma"] or 0)
        f["aprovechamiento_pct"] = (round(float(f["val_calentado"] or 0) / base * 100, 1)
                                    if base else None)
    return {"ok": True, "items": filas}


@router.get("/api/sobrantes/tablero")
def tablero(dias: int = 30, cur: dict = Depends(verify_token),
            db: Session = Depends(get_tenant_db)):
    """Cuánto se salvó y cuánto se botó.

    El indicador que importa es el porcentaje de aprovechamiento, no el peso
    salvado. Una cafetería que salva $200.000 al mes pero bota $600.000 no está
    aprovechando: está botando con buena conciencia.
    """
    desde = (ahora_local().date() - dt.timedelta(days=max(1, min(int(dias or 30), 365)))).isoformat()

    tot = q1(db, "SELECT COALESCE(SUM(val_calentado),0) AS salvado, "
                 "       COALESCE(SUM(val_consumo),0) AS consumo, "
                 "       COALESCE(SUM(val_merma),0) AS merma, COUNT(*) AS cierres "
                 "FROM cierres_cocina WHERE fecha >= :d", {"d": desde}) or {}
    salvado = float(tot.get("salvado") or 0)
    merma = float(tot.get("merma") or 0)
    consumo = float(tot.get("consumo") or 0)

    vencido = q1(db, "SELECT COALESCE(SUM(cantidad*costo_unit),0) AS v, COUNT(*) AS n "
                     "FROM sobrantes WHERE estado='vencido' AND creado_en >= :d",
                 {"d": desde}) or {}
    # Lo aprovechado de verdad es lo guardado MENOS lo que se venció guardado.
    # Contar como éxito el arroz que se guardó y luego se botó sería medir la
    # intención, no el resultado.
    perdido_guardado = float(vencido.get("v") or 0)
    real = max(salvado - perdido_guardado, 0.0)
    base = real + merma + perdido_guardado

    peores = q(db, "SELECT i.nombre, COUNT(*) AS veces, "
                   "       COALESCE(SUM(s.cantidad*s.costo_unit),0) AS valor "
                   "FROM sobrantes s JOIN insumos i ON i.id = s.insumo_id "
                   "WHERE s.estado IN ('vencido','descartado') AND s.creado_en >= :d "
                   "GROUP BY i.nombre ORDER BY valor DESC LIMIT 5", {"d": desde})

    serie = q(db, "SELECT fecha, val_calentado, val_merma FROM cierres_cocina "
                  "WHERE fecha >= :d ORDER BY fecha", {"d": desde})

    return {"ok": True, "desde": desde, "cierres": int(tot.get("cierres") or 0),
            "salvado": round(salvado, 2), "consumo_personal": round(consumo, 2),
            "merma_directa": round(merma, 2),
            "vencido_guardado": round(perdido_guardado, 2),
            "lotes_vencidos": int(vencido.get("n") or 0),
            "aprovechado_real": round(real, 2),
            "aprovechamiento_pct": round(real / base * 100, 1) if base else None,
            "peores": serial(peores), "serie": serial(serie)}
