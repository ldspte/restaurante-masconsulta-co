# -*- coding: utf-8 -*-
"""
================================================================
  RESTAURANTE · Módulo SALÓN
================================================================
Zonas, mesas y reservas. Es la pantalla que el mesero mira todo el turno, así
que su requisito dominante no es la riqueza funcional sino la velocidad: una
sola petición devuelve el mapa completo del salón.

EL ESTADO DE LA MESA SE GUARDA, NO SE DEDUCE
--------------------------------------------
Podría inferirse el estado preguntando si hay comanda abierta, pero hay estados
sin comanda —reservada, en limpieza— y deducirlos exigiría consultas frágiles
en la vista que más se refresca del sistema. El estado vive en la mesa y las
transiciones están centralizadas en `cambiar_estado`, que es lo que impide que
cada módulo invente sus propias reglas.

    libre ──▶ ocupada ──▶ limpieza ──▶ libre
      └──▶ reservada ──▶ ocupada

Rutas
  GET  /api/salon/mapa                estado completo del salón
  POST /api/salon/mesas/{id}/ocupar
  POST /api/salon/mesas/{id}/liberar
  POST /api/salon/mesas/{id}/estado
  GET/POST/PUT  /api/salon/mesas      administración de mesas
  GET/POST      /api/salon/zonas
  GET/POST/PUT  /api/salon/reservas
  POST /api/salon/reservas/{id}/sentar

Autor: Arquitectura de Software · Unidad 1
================================================================
"""
from __future__ import annotations

import datetime
import logging
import secrets

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from db import ahora_local, ahora, hoy, q, q1, run, run_sin_commit, serial
from dependencias import get_tenant_db
from seguridad import autor, require_rol, verify_token

log = logging.getLogger("restaurante.salon")
router = APIRouter(tags=["Salón"])

ROLES_SALON = ("admin", "gerente", "mesero", "cajero")
ROLES_CONFIG = ("admin", "gerente")

ESTADOS = {
    "libre":     {"label": "Libre",       "color": "#16a34a"},
    "ocupada":   {"label": "Ocupada",     "color": "#dc2626"},
    "reservada": {"label": "Reservada",   "color": "#d97706"},
    "limpieza":  {"label": "Por limpiar", "color": "#6b7280"},
}

# Transiciones permitidas. Tenerlas explícitas evita el estado imposible más
# común del salón: una mesa que queda «libre» con la cuenta sin cobrar porque
# alguien la liberó desde otra pantalla.
_TRANSICIONES = {
    "libre":     {"ocupada", "reservada", "limpieza"},
    "ocupada":   {"limpieza", "libre"},
    "reservada": {"ocupada", "libre"},
    "limpieza":  {"libre"},
}


def cambiar_estado(db: Session, mesa_id: int, nuevo: str, *, mesero: str = "",
                   forzar: bool = False) -> dict:
    """Transición validada del estado de una mesa. NO hace commit."""
    if nuevo not in ESTADOS:
        raise HTTPException(400, f"Estado inválido: {nuevo}")
    mesa = q1(db, "SELECT * FROM mesas WHERE id=:i", {"i": mesa_id})
    if not mesa:
        raise HTTPException(404, "Mesa no encontrada")

    actual = mesa["estado"]
    if actual == nuevo:
        return dict(mesa)
    if not forzar and nuevo not in _TRANSICIONES.get(actual, set()):
        raise HTTPException(
            409, f"No se puede pasar la mesa {mesa['codigo']} de «{ESTADOS[actual]['label']}» "
                 f"a «{ESTADOS[nuevo]['label']}».")

    # Liberar con la cuenta abierta es el error caro: la mesa se reasigna y el
    # consumo anterior se pierde.
    if nuevo in ("libre", "limpieza") and not forzar:
        abierta = q1(db, "SELECT numero FROM comandas WHERE mesa_id=:m "
                         "AND estado NOT IN ('cerrada','anulada') LIMIT 1", {"m": mesa_id})
        if abierta:
            raise HTTPException(
                409, f"La mesa {mesa['codigo']} tiene la comanda {abierta['numero']} sin "
                     f"cerrar. Cobre la cuenta antes de liberarla.")

    run_sin_commit(db, "UPDATE mesas SET estado=:e, mesero=:m, ocupada_ts=:ts WHERE id=:i",
                   {"e": nuevo, "m": (mesero or mesa.get("mesero")) if nuevo == "ocupada" else None,
                    "ts": ahora() if nuevo == "ocupada" else None, "i": mesa_id})
    mesa["estado"] = nuevo
    return dict(mesa)


# ══════════════════════════════════════════════════════════════════════
#  MAPA DEL SALÓN
# ══════════════════════════════════════════════════════════════════════
@router.get("/api/salon/mapa")
def mapa(cur: dict = Depends(require_rol(*ROLES_SALON)),
         db: Session = Depends(get_tenant_db)):
    """Todo lo que necesita la pantalla del salón en UNA sola petición.

    Encadenar cuatro llamadas en una vista que se refresca cada pocos segundos
    multiplica la latencia por cuatro y hace parpadear la interfaz.
    """
    mesas = serial(q(db,
                     "SELECT m.*, COALESCE(z.nombre,'Sin zona') AS zona, "
                     "       COALESCE(z.color,'#94a3b8') AS zona_color, "
                     "       c.id AS comanda_id, c.numero AS comanda, "
                     "       c.personas AS comensales, c.apertura_ts, "
                     "       (SELECT COALESCE(SUM(ci.cantidad * ci.precio_unit),0) "
                     "          FROM comanda_items ci "
                     "         WHERE ci.comanda_id = c.id AND ci.estado <> 'anulado') AS consumo "
                     "FROM mesas m "
                     "LEFT JOIN zonas z ON z.id = m.zona_id "
                     "LEFT JOIN comandas c ON c.mesa_id = m.id "
                     "     AND c.estado NOT IN ('cerrada','anulada') "
                     "WHERE m.activo = 1 ORDER BY z.orden, m.codigo"))

    for m in mesas:
        meta = ESTADOS.get(m["estado"], ESTADOS["libre"])
        m["estado_label"] = meta["label"]
        m["estado_color"] = meta["color"]
        m["minutos"] = _minutos_desde(m.get("apertura_ts") or m.get("ocupada_ts"))

    reservas = serial(q(db, "SELECT r.*, m.codigo AS mesa_codigo FROM reservas r "
                            "LEFT JOIN mesas m ON m.id = r.mesa_id "
                            "WHERE r.fecha = :h AND r.estado IN ('pendiente','confirmada') "
                            "ORDER BY r.hora", {"h": hoy()}))

    ocupadas = sum(1 for m in mesas if m["estado"] == "ocupada")
    return {"ok": True, "mesas": mesas, "reservas_hoy": reservas, "estados": ESTADOS,
            "kpis": {"total": len(mesas), "ocupadas": ocupadas,
                     "libres": sum(1 for m in mesas if m["estado"] == "libre"),
                     "reservadas": sum(1 for m in mesas if m["estado"] == "reservada"),
                     "limpieza": sum(1 for m in mesas if m["estado"] == "limpieza"),
                     "ocupacion_pct": round(ocupadas / len(mesas) * 100, 1) if mesas else 0,
                     "comensales": sum(int(m.get("comensales") or 0) for m in mesas),
                     "consumo_salon": round(sum(float(m.get("consumo") or 0) for m in mesas), 2)}}


def _minutos_desde(ts: str | None) -> int | None:
    if not ts:
        return None
    try:
        inicio = datetime.datetime.fromisoformat(ts)
        if inicio.tzinfo is None:
            inicio = inicio.replace(tzinfo=datetime.timezone.utc)
        delta = datetime.datetime.now(datetime.timezone.utc) - inicio
        return max(0, int(delta.total_seconds() // 60))
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════
#  OPERACIÓN DE MESAS
# ══════════════════════════════════════════════════════════════════════
@router.post("/api/salon/mesas/{mid}/ocupar")
def ocupar(mid: int, body: dict = Body(default={}),
           cur: dict = Depends(require_rol(*ROLES_SALON)),
           db: Session = Depends(get_tenant_db)):
    """Sienta comensales y abre la comanda en un solo paso.

    Son dos hechos que en el salón ocurren juntos: nadie ocupa una mesa sin
    intención de pedir. Separarlos obligaría al mesero a dos toques y dejaría
    la puerta abierta a mesas ocupadas sin comanda.
    """
    from comandas_router import abrir_comanda

    mesa = q1(db, "SELECT * FROM mesas WHERE id=:i AND activo=1", {"i": mid})
    if not mesa:
        raise HTTPException(404, "Mesa no encontrada")

    personas = int(body.get("personas") or mesa["capacidad"] or 1)
    if personas < 1:
        raise HTTPException(400, "Indique cuántas personas se sientan")
    if personas > int(mesa["capacidad"] or 0) and not body.get("forzar"):
        raise HTTPException(
            409, f"La mesa {mesa['codigo']} es para {mesa['capacidad']} personas y se "
                 f"indicaron {personas}. Confirme si desea continuar.")

    try:
        cambiar_estado(db, mid, "ocupada", mesero=autor(cur), forzar=bool(body.get("forzar")))
        comanda = abrir_comanda(db, mesa_id=mid, mesero=autor(cur), personas=personas,
                                tipo="mesa", notas=body.get("notas"))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True, "mesa": mesa["codigo"], "comanda": comanda}


@router.post("/api/salon/mesas/{mid}/liberar")
def liberar(mid: int, body: dict = Body(default={}),
            cur: dict = Depends(require_rol(*ROLES_SALON)),
            db: Session = Depends(get_tenant_db)):
    """Pasa la mesa a limpieza tras el cobro; con `directo`, a libre."""
    destino = "libre" if body.get("directo") else "limpieza"
    try:
        cambiar_estado(db, mid, destino, forzar=bool(body.get("forzar")))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True, "estado": destino}


@router.post("/api/salon/mesas/{mid}/liberar-sin-consumo")
def liberar_sin_consumo(mid: int, body: dict = Body(default={}),
                        cur: dict = Depends(require_rol(*ROLES_SALON)),
                        db: Session = Depends(get_tenant_db)):
    """Libera una mesa donde NO se consumió nada.

    Pasa todos los días: se sientan, miran la carta, se levantan y se van. No
    hay nada que cobrar, y hasta ahora la única forma de liberar la mesa era
    cobrar una cuenta que no existe. La mesa quedaba trabada y su comanda
    abierta para siempre, ensuciando el tablero.

    Se exige que el consumo sea CERO. Si hay algo servido, esto no es la salida:
    o se cobra, o se anula plato por plato dejando el rastro de por qué. Una
    mesa con comida servida que se libera sin registro es un hueco de caja.
    """
    mesa = q1(db, "SELECT * FROM mesas WHERE id=:i", {"i": mid})
    if not mesa:
        raise HTTPException(404, "Mesa no encontrada")

    comanda = q1(db, "SELECT * FROM comandas WHERE mesa_id=:m AND estado NOT IN "
                     "('cerrada','anulada') ORDER BY id DESC LIMIT 1", {"m": mid})

    consumo = 0.0
    if comanda:
        fila = q1(db, "SELECT COALESCE(SUM(cantidad*precio_unit),0) AS t "
                      "FROM comanda_items WHERE comanda_id=:c AND estado<>'anulado'",
                  {"c": comanda["id"]}) or {}
        consumo = round(float(fila.get("t") or 0), 2)

    if consumo > 0:
        raise HTTPException(
            409,
            f"La mesa {mesa['codigo']} tiene {consumo:,.0f} en consumo. "
            f"Cóbrela en caja, o anule los platos uno a uno si no se sirvieron.")

    motivo = (body.get("motivo") or "").strip()[:200] or "Se retiraron sin consumir"

    try:
        if comanda:
            nota = (comanda.get("notas") or "").strip()
            nota = (nota + " · " if nota else "") + "ANULADA: " + motivo
            run_sin_commit(db, "UPDATE comandas SET estado='anulada', notas=:n, "
                               "cierre_ts=:ts WHERE id=:i",
                           {"n": nota[:500], "ts": ahora(), "i": comanda["id"]})
        # A «libre» y no a «limpieza»: no se sirvio nada que recoger. Si el
        # local prefiere pasar siempre por limpieza, lo indica con `limpiar`.
        cambiar_estado(db, mid, "limpieza" if body.get("limpiar") else "libre",
                       mesero=autor(cur), forzar=True)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise

    log.info("Mesa %s liberada sin consumo por %s · %s", mesa["codigo"], autor(cur), motivo)
    return {"ok": True, "mesa": mesa["codigo"],
            "comanda_anulada": (comanda or {}).get("numero"),
            "mensaje": f"Mesa {mesa['codigo']} liberada. No había consumo que cobrar."}


@router.post("/api/salon/mesas/{mid}/estado")
def set_estado(mid: int, body: dict = Body(...),
               cur: dict = Depends(require_rol(*ROLES_SALON)),
               db: Session = Depends(get_tenant_db)):
    try:
        mesa = cambiar_estado(db, mid, (body.get("estado") or "").strip(),
                              mesero=autor(cur), forzar=bool(body.get("forzar")))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True, "mesa": serial(mesa)[0]}


# ══════════════════════════════════════════════════════════════════════
#  ADMINISTRACIÓN DE ZONAS Y MESAS
# ══════════════════════════════════════════════════════════════════════
@router.get("/api/salon/zonas")
def zonas_listar(cur: dict = Depends(verify_token), db: Session = Depends(get_tenant_db)):
    return {"ok": True, "items": serial(q(db, "SELECT * FROM zonas WHERE activo=1 "
                                              "ORDER BY orden, nombre"))}


@router.post("/api/salon/zonas", status_code=201)
def zona_crear(body: dict = Body(...), cur: dict = Depends(require_rol(*ROLES_CONFIG)),
               db: Session = Depends(get_tenant_db)):
    nombre = (body.get("nombre") or "").strip()
    if not nombre:
        raise HTTPException(400, "El nombre de la zona es obligatorio")
    res = run(db, "INSERT INTO zonas (nombre, color, orden, activo) VALUES (:n,:c,:o,1) "
                  "ON DUPLICATE KEY UPDATE activo=1, color=VALUES(color)",
              {"n": nombre, "c": body.get("color") or "#6366f1",
               "o": int(body.get("orden") or 99)})
    return {"ok": True, "id": getattr(res, "lastrowid", 0)}


@router.post("/api/salon/mesas", status_code=201)
def mesa_crear(body: dict = Body(...), cur: dict = Depends(require_rol(*ROLES_CONFIG)),
               db: Session = Depends(get_tenant_db)):
    codigo = (body.get("codigo") or "").strip().upper()
    if not codigo:
        raise HTTPException(400, "El código de la mesa es obligatorio")
    if q1(db, "SELECT id FROM mesas WHERE codigo=:c", {"c": codigo}):
        raise HTTPException(409, f"Ya existe una mesa con el código {codigo}")
    res = run(db, "INSERT INTO mesas (zona_id, codigo, nombre, capacidad, estado, activo) "
                  "VALUES (:z,:c,:n,:cap,'libre',1)",
              {"z": body.get("zona_id") or None, "c": codigo, "n": body.get("nombre"),
               "cap": int(body.get("capacidad") or 4)})
    return {"ok": True, "id": getattr(res, "lastrowid", 0)}


@router.put("/api/salon/mesas/{mid}")
def mesa_editar(mid: int, body: dict = Body(...),
                cur: dict = Depends(require_rol(*ROLES_CONFIG)),
                db: Session = Depends(get_tenant_db)):
    if not q1(db, "SELECT id FROM mesas WHERE id=:i", {"i": mid}):
        raise HTTPException(404, "Mesa no encontrada")
    campos = {k: body[k] for k in ("zona_id", "codigo", "nombre", "capacidad", "activo")
              if k in body}
    if not campos:
        return {"ok": True, "sin_cambios": True}
    sets = ", ".join(f"{k}=:{k}" for k in campos)
    run(db, f"UPDATE mesas SET {sets} WHERE id=:id", dict(campos, id=mid))
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════
#  RESERVAS
# ══════════════════════════════════════════════════════════════════════
def crear_reserva(db: Session, datos: dict, *, origen: str = "interno",
                  creado_por: str = "sistema") -> dict:
    """Alta de reserva. La comparten la pantalla interna y el sitio público, de
    modo que las validaciones son las mismas por los dos caminos."""
    nombre = (datos.get("nombre") or "").strip()
    fecha = (datos.get("fecha") or "").strip()
    hora = (datos.get("hora") or "").strip()
    personas = int(datos.get("personas") or 2)

    if not nombre:
        raise HTTPException(400, "El nombre de quien reserva es obligatorio")
    if not fecha or not hora:
        raise HTTPException(400, "Indique fecha y hora de la reserva")
    if personas < 1:
        raise HTTPException(400, "Indique cuántas personas asistirán")

    try:
        dia = datetime.date.fromisoformat(fecha)
    except ValueError:
        raise HTTPException(400, "La fecha no tiene un formato válido (AAAA-MM-DD)")
    if dia < ahora_local().date():
        raise HTTPException(400, "No se puede reservar para una fecha pasada")

    mesa_id = datos.get("mesa_id") or None
    if mesa_id:
        mesa = q1(db, "SELECT * FROM mesas WHERE id=:i AND activo=1", {"i": mesa_id})
        if not mesa:
            raise HTTPException(404, "La mesa indicada no existe")
        if personas > int(mesa["capacidad"] or 0):
            raise HTTPException(409, f"La mesa {mesa['codigo']} admite "
                                     f"{mesa['capacidad']} personas")
        # Choque de reservas: misma mesa, mismo día y misma hora.
        choque = q1(db, "SELECT id FROM reservas WHERE mesa_id=:m AND fecha=:f AND hora=:h "
                        "AND estado IN ('pendiente','confirmada')",
                    {"m": mesa_id, "f": fecha, "h": hora})
        if choque:
            raise HTTPException(409, f"La mesa {mesa['codigo']} ya está reservada "
                                     f"para esa fecha y hora")

    # Control de aforo: la suma de comensales reservados no puede superar la
    # capacidad del local. Sin este tope, la web aceptaría más reservas de las
    # que el salón puede atender.
    perfil = q1(db, "SELECT aforo_max FROM sede_perfil WHERE id=1") or {}
    aforo = int(perfil.get("aforo_max") or 0)
    if aforo:
        fila = q1(db, "SELECT COALESCE(SUM(personas),0) AS n FROM reservas "
                      "WHERE fecha=:f AND hora=:h AND estado IN ('pendiente','confirmada')",
                  {"f": fecha, "h": hora})
        if int((fila or {}).get("n") or 0) + personas > aforo:
            raise HTTPException(409, "No hay disponibilidad para esa hora. "
                                     "Elija otro horario, por favor.")

    codigo = secrets.token_hex(3).upper()
    res = run(db, "INSERT INTO reservas (mesa_id, nombre, telefono, email, fecha, hora, "
                  "personas, estado, origen, notas, codigo, creado_por, creado_en) "
                  "VALUES (:m,:n,:t,:e,:f,:h,:p,'pendiente',:o,:no,:c,:cp,:ts)",
              {"m": mesa_id, "n": nombre[:160], "t": (datos.get("telefono") or "")[:40],
               "e": (datos.get("email") or "")[:160], "f": fecha, "h": hora,
               "p": personas, "o": origen, "no": datos.get("notas"),
               "c": codigo, "cp": creado_por, "ts": ahora()})
    return {"id": int(getattr(res, "lastrowid", 0) or 0), "codigo": codigo,
            "fecha": fecha, "hora": hora, "personas": personas}


@router.get("/api/salon/reservas")
def reservas_listar(fecha: str = "", estado: str = "",
                    cur: dict = Depends(require_rol(*ROLES_SALON)),
                    db: Session = Depends(get_tenant_db)):
    where, params = ["1=1"], {}
    if fecha:
        where.append("r.fecha = :f"); params["f"] = fecha
    if estado:
        where.append("r.estado = :e"); params["e"] = estado

    filas = serial(q(db, "SELECT r.*, m.codigo AS mesa_codigo FROM reservas r "
                         "LEFT JOIN mesas m ON m.id = r.mesa_id "
                         "WHERE " + " AND ".join(where) +
                         " ORDER BY r.fecha DESC, r.hora LIMIT 300", params))
    return {"ok": True, "items": filas,
            "kpis": {"total": len(filas),
                     "pendientes": sum(1 for f in filas if f["estado"] == "pendiente"),
                     "desde_web": sum(1 for f in filas if f["origen"] == "web"),
                     "personas": sum(int(f.get("personas") or 0) for f in filas
                                     if f["estado"] in ("pendiente", "confirmada"))}}


@router.post("/api/salon/reservas", status_code=201)
def reserva_crear(body: dict = Body(...), cur: dict = Depends(require_rol(*ROLES_SALON)),
                  db: Session = Depends(get_tenant_db)):
    try:
        creada = crear_reserva(db, body, origen="interno", creado_por=autor(cur))
        if body.get("mesa_id"):
            cambiar_estado(db, int(body["mesa_id"]), "reservada", forzar=True)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True, **creada}


@router.put("/api/salon/reservas/{rid}")
def reserva_editar(rid: int, body: dict = Body(...),
                   cur: dict = Depends(require_rol(*ROLES_SALON)),
                   db: Session = Depends(get_tenant_db)):
    reserva = q1(db, "SELECT * FROM reservas WHERE id=:i", {"i": rid})
    if not reserva:
        raise HTTPException(404, "Reserva no encontrada")
    campos = {k: body[k] for k in ("mesa_id", "nombre", "telefono", "email", "fecha",
                                   "hora", "personas", "estado", "notas") if k in body}
    if not campos:
        return {"ok": True, "sin_cambios": True}
    sets = ", ".join(f"{k}=:{k}" for k in campos)
    run(db, f"UPDATE reservas SET {sets} WHERE id=:id", dict(campos, id=rid))

    viva = (campos.get("estado") or reserva["estado"]) in ("pendiente", "confirmada")
    mesa_antes = reserva.get("mesa_id")
    mesa_ahora = campos.get("mesa_id", mesa_antes)

    # ── Asignar una mesa la RESERVA de verdad ─────────────────────────
    #
    # Antes solo se guardaba el numero en la reserva y la mesa seguia figurando
    # libre en el mapa: nada impedia sentar a otro cliente ahi. Una reserva que
    # no reserva no sirve. Al reasignar se suelta la anterior, para no dejar
    # bloqueada una mesa que ya nadie espera.
    if viva and str(mesa_ahora or "") != str(mesa_antes or ""):
        try:
            if mesa_antes:
                cambiar_estado(db, int(mesa_antes), "libre", forzar=True)
            if mesa_ahora:
                actual = q1(db, "SELECT estado FROM mesas WHERE id=:i", {"i": int(mesa_ahora)})
                if actual and actual["estado"] == "ocupada":
                    db.rollback()
                    raise HTTPException(409, "Esa mesa está ocupada en este momento.")
                cambiar_estado(db, int(mesa_ahora), "reservada", forzar=True)
            db.commit()
        except HTTPException:
            raise
        except Exception:
            db.rollback()
            raise

    # Cancelar libera la mesa: dejarla reservada bloquearía un puesto vendible.
    if body.get("estado") in ("cancelada", "no_show") and mesa_antes:
        try:
            cambiar_estado(db, int(mesa_antes), "libre", forzar=True)
            db.commit()
        except Exception:
            db.rollback()
    return {"ok": True}


@router.post("/api/salon/reservas/{rid}/sentar")
def reserva_sentar(rid: int, body: dict = Body(default={}),
                   cur: dict = Depends(require_rol(*ROLES_SALON)),
                   db: Session = Depends(get_tenant_db)):
    """Llegó el cliente: ocupa la mesa y abre la comanda."""
    from comandas_router import abrir_comanda

    reserva = q1(db, "SELECT * FROM reservas WHERE id=:i", {"i": rid})
    if not reserva:
        raise HTTPException(404, "Reserva no encontrada")
    if reserva["estado"] not in ("pendiente", "confirmada"):
        raise HTTPException(409, f"La reserva está en estado «{reserva['estado']}»")

    mesa_id = body.get("mesa_id") or reserva.get("mesa_id")
    if not mesa_id:
        raise HTTPException(400, "Indique en qué mesa se sienta")

    try:
        cambiar_estado(db, int(mesa_id), "ocupada", mesero=autor(cur), forzar=True)
        comanda = abrir_comanda(db, mesa_id=int(mesa_id), mesero=autor(cur),
                                personas=int(reserva["personas"] or 1), tipo="mesa",
                                notas=f"Reserva {reserva['codigo']} · {reserva['nombre']}")
        run_sin_commit(db, "UPDATE reservas SET estado='sentada', mesa_id=:m WHERE id=:i",
                       {"m": mesa_id, "i": rid})
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True, "comanda": comanda}
