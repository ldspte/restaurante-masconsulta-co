# -*- coding: utf-8 -*-
"""
================================================================
  RESTAURANTE · MAQUINARIA Y EQUIPO  ·  PROPIEDAD, PLANTA Y EQUIPO
================================================================
El horno rotatorio cuesta más que tres meses de ventas. No registrarlo tiene
dos consecuencias, y la segunda es la grave:

  1. El balance queda incompleto: hay ochenta millones en equipo que no
     figuran en ninguna parte.
  2. **La utilidad sale inflada.** Nadie está cargando el desgaste del horno
     al costo del pan que ese horno produce. El dueño cree que gana más de lo
     que gana, y el día que el horno se muera va a descubrir que no apartó
     nada para reponerlo.

Este módulo existe sobre todo por la segunda.

LÍNEA RECTA, Y POR QUÉ
----------------------
    cuota mensual = (valor de compra − valor residual) / vida útil en meses

Se eligió línea recta y no un método acelerado por una razón práctica: es el
método que el artículo 137 del Estatuto Tributario acepta sin exigir
conciliación fiscal aparte, y una cafetería de barrio no va a llevar dos
juegos de libros. Las tasas de la tabla —10 % anual para maquinaria, 20 % para
cómputo— son los topes que la DIAN admite como deducibles.

El **valor residual** no es un adorno. Un horno industrial de diez años no vale
cero: vale su chatarra y su mercado de segunda. Depreciar hasta cero exagera el
gasto y luego produce una utilidad ficticia el día de la venta.

DOS INVARIANTES QUE EL CÓDIGO NO NEGOCIA
-----------------------------------------
· **Nunca se deprecia por debajo del residual.** La última cuota se recorta a
  lo que falte. Sin esto, un activo con vida útil vencida sigue generando
  gasto para siempre y la 1592 termina mayor que la 1520.

· **Un período no se cierra dos veces.** `ultimo_periodo` en cada activo es la
  marca; el período cerrado es inmutable. Recalcular un mes ya contabilizado
  duplicaría el gasto en silencio.

Rutas
  GET    /api/activos                      maestro con su depreciación al día
  POST   /api/activos                      registra una compra de equipo
  GET    /api/activos/{id}                 ficha, historial y proyección
  POST   /api/activos/{id}/baja            retiro por venta, daño u obsolescencia
  POST   /api/activos/{id}/mantenimiento   registra un mantenimiento
  GET    /api/activos/mantenimientos       agenda: lo vencido y lo próximo
  GET    /api/activos/depreciacion/previa  simula el mes sin contabilizar
  POST   /api/activos/depreciacion/cerrar  contabiliza el mes
  GET    /api/activos/depreciacion         períodos cerrados
  GET    /api/activos/tablero              resumen para el tablero

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

log = logging.getLogger("restaurante.activos")
router = APIRouter(tags=["Maquinaria y equipo"])

ROLES_ADMIN = ("admin", "gerente")
ROLES_MANT = ("admin", "gerente", "cocina", "bodega")

ESTADOS = ("activo", "mantenimiento", "baja", "vendido")


# ══════════════════════════════════════════════════════════════════════
#  CÁLCULO  —  funciones puras, sin base de datos
#  Separarlas permite probar la aritmética de la depreciación sin montar un
#  período, un activo y una transacción. Es la parte que más importa que sea
#  correcta y la que más barato sale verificar.
# ══════════════════════════════════════════════════════════════════════
def meses_entre(desde: str, hasta: str) -> int:
    """Meses completos entre dos períodos AAAA-MM, inclusive el de destino."""
    a1, m1 = int(desde[:4]), int(desde[5:7])
    a2, m2 = int(hasta[:4]), int(hasta[5:7])
    return (a2 - a1) * 12 + (m2 - m1)


def cuota_mensual(valor_compra: float, valor_residual: float, vida_util_meses: int) -> float:
    base = max(float(valor_compra or 0) - float(valor_residual or 0), 0.0)
    meses = max(int(vida_util_meses or 0), 1)
    return round(base / meses, 2)


def calcular_cuota(activo: dict, periodo: str) -> dict:
    """Cuánto se deprecia este activo en `periodo` (AAAA-MM).

    Devuelve `cuota = 0` con un motivo legible cuando no corresponde. Que la
    respuesta diga *por qué* no se depreció evita la pregunta más común del
    contador: «¿por qué este equipo no salió en el mes?».
    """
    valor = float(activo.get("valor_compra") or 0)
    residual = float(activo.get("valor_residual") or 0)
    vida = int(activo.get("vida_util_meses") or 0)
    acum = float(activo.get("deprec_acum") or 0)
    base = max(valor - residual, 0.0)
    cuota_plena = cuota_mensual(valor, residual, vida)

    vacio = {"cuota": 0.0, "base": base, "acum_antes": acum,
             "acum_despues": acum, "meses": 0}

    if activo.get("estado") in ("baja", "vendido"):
        return {**vacio, "motivo": "dado de baja"}

    compra = str(activo.get("fecha_compra") or "")[:7]
    if not compra or compra > periodo:
        return {**vacio, "motivo": "adquirido después del período"}

    ultimo = str(activo.get("ultimo_periodo") or "")[:7]
    if ultimo and ultimo >= periodo:
        return {**vacio, "motivo": "ya depreciado en este período"}

    # Meses pendientes. Si el activo se registró con atraso —cosa habitual: el
    # equipo entró en febrero y el sistema se montó en agosto—, el primer
    # cierre recupera todos los meses de una vez en lugar de perderlos.
    arranque = ultimo or _mes_anterior(compra)
    meses = max(meses_entre(arranque, periodo), 0)
    if meses <= 0:
        return {**vacio, "motivo": "sin meses pendientes"}

    cuota = round(cuota_plena * meses, 2)
    # Invariante: jamás por debajo del valor residual.
    if acum + cuota > base:
        cuota = round(max(base - acum, 0.0), 2)
    if cuota <= 0:
        return {**vacio, "motivo": "totalmente depreciado"}

    return {"cuota": cuota, "base": base, "acum_antes": acum,
            "acum_despues": round(acum + cuota, 2), "meses": meses, "motivo": ""}


def _mes_anterior(periodo: str) -> str:
    a, m = int(periodo[:4]), int(periodo[5:7])
    return f"{a - 1}-12" if m == 1 else f"{a}-{m - 1:02d}"


def _periodo_actual() -> str:
    """El mes en curso del NEGOCIO. La depreciacion se cierra por mes y el
    primer dia del mes, de madrugada, el servidor todavia esta en el anterior."""
    return ahora_local().strftime("%Y-%m")


def _con_calculo(f: dict) -> dict:
    """Enriquece una fila del maestro con lo que la pantalla necesita."""
    d = dict(f)
    valor = float(d.get("valor_compra") or 0)
    residual = float(d.get("valor_residual") or 0)
    acum = float(d.get("deprec_acum") or 0)
    base = max(valor - residual, 0.0)
    d["valor_compra"] = valor
    d["valor_residual"] = residual
    d["deprec_acum"] = acum
    d["base_depreciable"] = base
    d["valor_libros"] = round(valor - acum, 2)
    d["cuota_mensual"] = cuota_mensual(valor, residual, int(d.get("vida_util_meses") or 1))
    d["avance_pct"] = round(acum / base * 100, 1) if base else 100.0
    d["meses_restantes"] = (int((base - acum) / d["cuota_mensual"])
                            if d["cuota_mensual"] > 0 and base > acum else 0)
    return d


# ══════════════════════════════════════════════════════════════════════
#  MAESTRO
# ══════════════════════════════════════════════════════════════════════
@router.get("/api/activos")
def listar(estado: str = "", categoria_id: int = 0, buscar: str = "",
           cur: dict = Depends(verify_token), db: Session = Depends(get_tenant_db)):
    donde, par = ["1=1"], {}
    if estado:
        donde.append("a.estado = :e"); par["e"] = estado
    if categoria_id:
        donde.append("a.categoria_id = :c"); par["c"] = categoria_id
    if buscar:
        donde.append("(a.nombre LIKE :b OR a.codigo LIKE :b OR a.marca LIKE :b "
                     "OR a.serie LIKE :b)")
        par["b"] = f"%{buscar.strip()}%"

    filas = q(db, "SELECT a.*, c.nombre AS categoria, c.cuenta_activo, c.cuenta_deprec, "
                  "       c.cuenta_gasto "
                  "FROM activos a JOIN cat_activos c ON c.id = a.categoria_id "
                  f"WHERE {' AND '.join(donde)} ORDER BY c.orden, a.codigo", par)
    items = [_con_calculo(f) for f in serial(filas)]

    vivos = [i for i in items if i["estado"] not in ("baja", "vendido")]
    return {"ok": True, "items": items,
            "categorias": serial(q(db, "SELECT * FROM cat_activos ORDER BY orden, nombre")),
            "resumen": {
                "unidades": len(vivos),
                "valor_compra": round(sum(i["valor_compra"] for i in vivos), 2),
                "deprec_acum": round(sum(i["deprec_acum"] for i in vivos), 2),
                "valor_libros": round(sum(i["valor_libros"] for i in vivos), 2),
                "cuota_mensual": round(sum(i["cuota_mensual"] for i in vivos
                                           if i["deprec_acum"] < i["base_depreciable"]), 2),
            }}


@router.post("/api/activos", status_code=201)
def crear(body: dict = Body(...), cur: dict = Depends(require_rol(*ROLES_ADMIN)),
          db: Session = Depends(get_tenant_db)):
    """Registra una compra de equipo y la contabiliza.

    La vida útil se hereda de la categoría si no se indica. Es lo correcto por
    omisión: quien compra una licuadora no tiene por qué saber que va a la
    cuenta 1520 y se deprecia en ciento veinte meses.
    """
    nombre = (body.get("nombre") or "").strip()
    categoria_id = int(body.get("categoria_id") or 0)
    valor = round(float(body.get("valor_compra") or 0), 2)
    fecha = (body.get("fecha_compra") or hoy())[:10]

    if not nombre:
        raise HTTPException(400, "El nombre del equipo es obligatorio")
    if valor <= 0:
        raise HTTPException(400, "El valor de compra debe ser mayor que cero")

    cat = q1(db, "SELECT * FROM cat_activos WHERE id=:i", {"i": categoria_id})
    if not cat:
        raise HTTPException(400, "Indique una categoría de activo válida")

    residual = round(float(body.get("valor_residual") or 0), 2)
    if residual >= valor:
        raise HTTPException(400, "El valor residual no puede igualar ni superar el de compra")

    vida = int(body.get("vida_util_meses") or cat["vida_util_meses"])
    if vida <= 0:
        raise HTTPException(400, "La vida útil debe ser mayor que cero")

    codigo = (body.get("codigo") or "").strip().upper()
    if not codigo:
        ult = q1(db, "SELECT codigo FROM activos WHERE codigo LIKE 'EQ-%' "
                     "ORDER BY codigo DESC LIMIT 1")
        n = int(str(ult["codigo"])[3:]) + 1 if ult and str(ult["codigo"])[3:].isdigit() else 1
        codigo = f"EQ-{n:03d}"
    if q1(db, "SELECT id FROM activos WHERE codigo=:c", {"c": codigo}):
        raise HTTPException(409, f"Ya existe un activo con el código {codigo}")

    quien = autor(cur)
    try:
        res = run_sin_commit(db,
                             "INSERT INTO activos (codigo, nombre, categoria_id, marca, modelo, "
                             "serie, fecha_compra, valor_compra, valor_residual, "
                             "vida_util_meses, ubicacion, responsable, proveedor, factura, "
                             "estado, creado_en) "
                             "VALUES (:c,:n,:ca,:ma,:mo,:se,:f,:v,:r,:vu,:ub,:re,:pr,:fa,"
                             "'activo',:ts)",
                             {"c": codigo, "n": nombre[:180], "ca": categoria_id,
                              "ma": (body.get("marca") or "").strip()[:80] or None,
                              "mo": (body.get("modelo") or "").strip()[:80] or None,
                              "se": (body.get("serie") or "").strip()[:80] or None,
                              "f": fecha, "v": valor, "r": residual, "vu": vida,
                              "ub": (body.get("ubicacion") or "").strip()[:120] or None,
                              "re": (body.get("responsable") or "").strip()[:160] or None,
                              "pr": (body.get("proveedor") or "").strip()[:180] or None,
                              "fa": (body.get("factura") or "").strip()[:60] or None,
                              "ts": ahora()})
        aid = int(res.lastrowid or 0)
        publicar(db, Evento(
            tipo=TipoEvento.ACTIVO_ADQUIRIDO, entidad="activo", entidad_id=aid,
            payload={"codigo": codigo, "nombre": nombre, "valor": valor,
                     "cuenta_activo": cat["cuenta_activo"],
                     "credito": (body.get("forma_pago") or "contado"),
                     "proveedor": body.get("proveedor") or ""},
            usuario=quien))
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {"ok": True, "id": aid, "codigo": codigo,
            "cuota_mensual": cuota_mensual(valor, residual, vida),
            "mensaje": f"{nombre} registrado como {codigo}."}


@router.post("/api/activos/{activo_id}/baja")
def dar_baja(activo_id: int, body: dict = Body(...),
             cur: dict = Depends(require_rol(*ROLES_ADMIN)),
             db: Session = Depends(get_tenant_db)):
    """Retira un activo: se vendió, se dañó o quedó obsoleto.

    El asiento cancela el costo y su depreciación acumulada. Lo que quede sin
    depreciar es pérdida del período: es la parte del equipo que se pagó y no
    se alcanzó a usar.
    """
    f = q1(db, "SELECT a.*, c.cuenta_activo, c.cuenta_deprec FROM activos a "
               "JOIN cat_activos c ON c.id = a.categoria_id WHERE a.id=:i", {"i": activo_id})
    if not f:
        raise HTTPException(404, "Activo no encontrado")
    if f["estado"] in ("baja", "vendido"):
        raise HTTPException(409, "El activo ya está dado de baja")

    motivo = (body.get("motivo") or "").strip()
    if not motivo:
        raise HTTPException(400, "Diga por qué se retira el activo")

    valor = float(f["valor_compra"] or 0)
    acum = float(f["deprec_acum"] or 0)
    venta = round(float(body.get("valor_venta") or 0), 2)
    libros = round(valor - acum, 2)
    resultado = round(venta - libros, 2)      # positivo = utilidad
    fecha = (body.get("fecha") or hoy())[:10]
    estado = "vendido" if venta > 0 else "baja"
    quien = autor(cur)

    try:
        run_sin_commit(db, "UPDATE activos SET estado=:e, fecha_baja=:f, motivo_baja=:m "
                           "WHERE id=:i",
                       {"e": estado, "f": fecha, "m": motivo[:240], "i": activo_id})
        publicar(db, Evento(
            tipo=TipoEvento.ACTIVO_DADO_BAJA, entidad="activo", entidad_id=activo_id,
            payload={"codigo": f["codigo"], "nombre": f["nombre"], "valor_compra": valor,
                     "deprec_acum": acum, "valor_libros": libros, "valor_venta": venta,
                     "resultado": resultado, "motivo": motivo,
                     "cuenta_activo": f["cuenta_activo"], "cuenta_deprec": f["cuenta_deprec"]},
            usuario=quien))
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {"ok": True, "estado": estado, "valor_libros": libros,
            "valor_venta": venta, "resultado": resultado,
            "mensaje": (f"{f['nombre']} dado de baja. "
                        + (f"Utilidad de ${resultado:,.0f}." if resultado > 0
                           else f"Pérdida de ${abs(resultado):,.0f}." if resultado < 0
                           else "Sin efecto en resultados."))}


# ══════════════════════════════════════════════════════════════════════
#  MANTENIMIENTO
# ══════════════════════════════════════════════════════════════════════
@router.post("/api/activos/{activo_id}/mantenimiento", status_code=201)
def mantenimiento(activo_id: int, body: dict = Body(...),
                  cur: dict = Depends(require_rol(*ROLES_MANT)),
                  db: Session = Depends(get_tenant_db)):
    """Registra un mantenimiento.

    El costo va a gasto (5145) y NO al valor del activo. Solo se capitaliza lo
    que aumenta la capacidad o la vida útil; cambiar un termostato repone la
    condición original, no la mejora. Sumarlo al activo inflaría el balance y
    el gasto de depreciación de los años siguientes.
    """
    f = q1(db, "SELECT id, codigo, nombre FROM activos WHERE id=:i", {"i": activo_id})
    if not f:
        raise HTTPException(404, "Activo no encontrado")

    tipo = (body.get("tipo") or "preventivo").strip().lower()
    if tipo not in ("preventivo", "correctivo", "calibracion"):
        raise HTTPException(400, "Tipo inválido: preventivo, correctivo o calibracion")
    desc = (body.get("descripcion") or "").strip()
    if not desc:
        raise HTTPException(400, "Describa el mantenimiento realizado")

    costo = round(float(body.get("costo") or 0), 2)
    fecha = (body.get("fecha") or hoy())[:10]
    proximo = (body.get("proximo") or "").strip()[:10] or None
    quien = autor(cur)

    try:
        res = run_sin_commit(db,
                             "INSERT INTO activo_mantenimientos (activo_id, fecha, tipo, "
                             "descripcion, costo, proveedor, proximo, responsable, creado_en) "
                             "VALUES (:a,:f,:t,:d,:c,:p,:px,:r,:ts)",
                             {"a": activo_id, "f": fecha, "t": tipo, "d": desc[:400],
                              "c": costo,
                              "p": (body.get("proveedor") or "").strip()[:180] or None,
                              "px": proximo, "r": quien, "ts": ahora()})
        mid = int(res.lastrowid or 0)
        if costo > 0:
            publicar(db, Evento(
                tipo=TipoEvento.MANTENIMIENTO_REGISTRADO, entidad="mantenimiento",
                entidad_id=mid,
                payload={"activo": f["nombre"], "codigo": f["codigo"], "tipo": tipo,
                         "costo": costo, "descripcion": desc,
                         "credito": (body.get("forma_pago") or "contado")},
                usuario=quien))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True, "id": mid, "mensaje": f"Mantenimiento registrado para {f['nombre']}."}


@router.get("/api/activos/mantenimientos/agenda")
def agenda(cur: dict = Depends(verify_token), db: Session = Depends(get_tenant_db)):
    """Lo vencido y lo que viene. Es la pantalla que evita que el horno se
    detenga un sábado a las seis de la mañana."""
    filas = q(db, "SELECT m.*, a.codigo, a.nombre AS activo, a.ubicacion "
                  "FROM activo_mantenimientos m JOIN activos a ON a.id = m.activo_id "
                  "WHERE m.proximo IS NOT NULL AND a.estado NOT IN ('baja','vendido') "
                  "ORDER BY m.proximo")
    h = hoy()
    # Solo el último programado por activo: los anteriores ya se ejecutaron y
    # mostrarlos llenaría la agenda de fechas muertas.
    ultimo: dict[int, dict] = {}
    for f in filas:
        ultimo[int(f["activo_id"])] = f

    items = []
    for f in sorted(ultimo.values(), key=lambda x: str(x["proximo"])):
        dias = (dt.date.fromisoformat(str(f["proximo"])[:10]) - dt.date.fromisoformat(h)).days
        items.append({**dict(f), "dias": dias,
                      "alerta": ("vencido" if dias < 0 else "urgente" if dias <= 7
                                 else "pronto" if dias <= 30 else "ok")})
    return {"ok": True, "items": serial(items),
            "vencidos": sum(1 for i in items if i["alerta"] == "vencido"),
            "proximos": sum(1 for i in items if i["alerta"] in ("urgente", "pronto"))}


# ══════════════════════════════════════════════════════════════════════
#  DEPRECIACIÓN
# ══════════════════════════════════════════════════════════════════════
def _calcular_periodo(db: Session, periodo: str) -> tuple[list[dict], float]:
    filas = q(db, "SELECT a.*, c.cuenta_gasto, c.cuenta_deprec FROM activos a "
                  "JOIN cat_activos c ON c.id = a.categoria_id "
                  "WHERE a.estado NOT IN ('baja','vendido') ORDER BY a.codigo")
    detalle, total = [], 0.0
    for f in filas:
        c = calcular_cuota(dict(f), periodo)
        if c["cuota"] <= 0:
            continue
        detalle.append({"activo_id": int(f["id"]), "codigo": f["codigo"],
                        "nombre": f["nombre"], **c,
                        "cuenta_gasto": f["cuenta_gasto"],
                        "cuenta_deprec": f["cuenta_deprec"]})
        total += c["cuota"]
    return detalle, round(total, 2)


@router.get("/api/activos/depreciacion/previa")
def previa(periodo: str = "", cur: dict = Depends(verify_token),
           db: Session = Depends(get_tenant_db)):
    """Simula el mes SIN contabilizar nada.

    Existe porque un cierre contable no debería ser la primera vez que alguien
    ve las cifras. Se mira, se revisa y después se cierra.
    """
    periodo = (periodo or _periodo_actual())[:7]
    if q1(db, "SELECT id FROM deprec_periodos WHERE periodo=:p AND estado='cerrado'",
          {"p": periodo}):
        raise HTTPException(409, f"El período {periodo} ya fue cerrado")
    detalle, total = _calcular_periodo(db, periodo)
    return {"ok": True, "periodo": periodo, "detalle": detalle, "total": total,
            "activos": len(detalle)}


@router.post("/api/activos/depreciacion/cerrar")
def cerrar(body: dict = Body(default={}), cur: dict = Depends(require_rol(*ROLES_ADMIN)),
           db: Session = Depends(get_tenant_db)):
    """Contabiliza la depreciación del mes. Irreversible por diseño.

    Se marca `ultimo_periodo` en cada activo dentro de la misma transacción
    que el asiento. Es lo que impide que un segundo clic duplique el gasto: la
    marca y el asiento viven o mueren juntos.
    """
    periodo = (body.get("periodo") or _periodo_actual())[:7]
    if len(periodo) != 7 or periodo[4] != "-":
        raise HTTPException(400, "El período debe tener el formato AAAA-MM")
    if periodo > _periodo_actual():
        raise HTTPException(400, "No se puede depreciar un período futuro")
    if q1(db, "SELECT id FROM deprec_periodos WHERE periodo=:p AND estado='cerrado'",
          {"p": periodo}):
        raise HTTPException(409, f"El período {periodo} ya fue cerrado")

    detalle, total = _calcular_periodo(db, periodo)
    if not detalle:
        raise HTTPException(409, "No hay activos con depreciación pendiente en este período")

    quien = autor(cur)
    try:
        res = run_sin_commit(db,
                             "INSERT INTO deprec_periodos (periodo, estado, total, activos, "
                             "creado_en, cerrado_en, cerrado_por) "
                             "VALUES (:p,'cerrado',:t,:n,:ts,:ts,:u)",
                             {"p": periodo, "t": total, "n": len(detalle),
                              "ts": ahora(), "u": quien})
        pid = int(res.lastrowid or 0)

        for d in detalle:
            run_sin_commit(db,
                           "INSERT INTO deprec_detalle (periodo_id, activo_id, base, cuota, "
                           "acum_antes, acum_despues, cuenta_gasto, cuenta_deprec) "
                           "VALUES (:p,:a,:b,:c,:aa,:ad,:cg,:cd)",
                           {"p": pid, "a": d["activo_id"], "b": d["base"], "c": d["cuota"],
                            "aa": d["acum_antes"], "ad": d["acum_despues"],
                            "cg": d["cuenta_gasto"], "cd": d["cuenta_deprec"]})
            run_sin_commit(db, "UPDATE activos SET deprec_acum=:a, ultimo_periodo=:p "
                               "WHERE id=:i",
                           {"a": d["acum_despues"], "p": periodo, "i": d["activo_id"]})

        publicar(db, Evento(
            tipo=TipoEvento.DEPRECIACION_CERRADA, entidad="deprec_periodo", entidad_id=pid,
            payload={"periodo": periodo, "total": total, "activos": len(detalle),
                     "detalle": [{"cuenta_gasto": d["cuenta_gasto"],
                                  "cuenta_deprec": d["cuenta_deprec"],
                                  "cuota": d["cuota"]} for d in detalle]},
            usuario=quien))
        db.commit()
    except Exception:
        db.rollback()
        raise

    log.info("Depreciación %s cerrada: %s activos, $%.2f", periodo, len(detalle), total)
    return {"ok": True, "periodo": periodo, "total": total, "activos": len(detalle),
            "mensaje": f"Depreciación de {periodo} contabilizada: ${total:,.0f}."}


@router.get("/api/activos/depreciacion")
def periodos(cur: dict = Depends(verify_token), db: Session = Depends(get_tenant_db)):
    return {"ok": True,
            "items": serial(q(db, "SELECT * FROM deprec_periodos ORDER BY periodo DESC "
                                  "LIMIT 36"))}


# ══════════════════════════════════════════════════════════════════════
#  TABLERO
# ══════════════════════════════════════════════════════════════════════
@router.get("/api/activos/tablero")
def tablero(cur: dict = Depends(verify_token), db: Session = Depends(get_tenant_db)):
    filas = [_con_calculo(f) for f in serial(
        q(db, "SELECT a.*, c.nombre AS categoria FROM activos a "
              "JOIN cat_activos c ON c.id = a.categoria_id "
              "WHERE a.estado NOT IN ('baja','vendido')"))]

    por_cat: dict[str, dict] = {}
    for f in filas:
        g = por_cat.setdefault(f["categoria"], {"categoria": f["categoria"], "unidades": 0,
                                                "valor_compra": 0.0, "deprec_acum": 0.0,
                                                "valor_libros": 0.0})
        g["unidades"] += 1
        g["valor_compra"] += f["valor_compra"]
        g["deprec_acum"] += f["deprec_acum"]
        g["valor_libros"] += f["valor_libros"]

    anio = hoy()[:4]
    mant = q1(db, "SELECT COALESCE(SUM(costo),0) AS c, COUNT(*) AS n "
                  "FROM activo_mantenimientos WHERE fecha LIKE :a", {"a": f"{anio}%"}) or {}
    ult = q1(db, "SELECT periodo, total FROM deprec_periodos WHERE estado='cerrado' "
                 "ORDER BY periodo DESC LIMIT 1")

    # Los que ya cumplieron su vida útil pero siguen trabajando. Es la lista
    # que anticipa la próxima inversión: valen cero en libros y el día que
    # fallen hay que reponerlos de contado.
    agotados = [{"codigo": f["codigo"], "nombre": f["nombre"],
                 "valor_compra": f["valor_compra"], "categoria": f["categoria"]}
                for f in filas if f["base_depreciable"] > 0
                and f["deprec_acum"] >= f["base_depreciable"]]

    return {"ok": True,
            "unidades": len(filas),
            "valor_compra": round(sum(f["valor_compra"] for f in filas), 2),
            "deprec_acum": round(sum(f["deprec_acum"] for f in filas), 2),
            "valor_libros": round(sum(f["valor_libros"] for f in filas), 2),
            "cuota_mensual": round(sum(f["cuota_mensual"] for f in filas
                                       if f["deprec_acum"] < f["base_depreciable"]), 2),
            "por_categoria": sorted(por_cat.values(), key=lambda x: -x["valor_libros"]),
            "mantenimiento_anio": round(float(mant.get("c") or 0), 2),
            "mantenimientos": int(mant.get("n") or 0),
            "ultimo_periodo": dict(ult) if ult else None,
            "periodo_actual": _periodo_actual(),
            "totalmente_depreciados": agotados}


# ══════════════════════════════════════════════════════════════════════
#  FICHA DEL ACTIVO
#  Va al final del archivo a propósito: `/api/activos/{activo_id}` compite
#  con `/api/activos/tablero` y `/api/activos/depreciacion`, y el orden de
#  declaración decide cuál gana. Declarada arriba, «tablero» se intentaría
#  leer como un número y la respuesta sería un 422 desconcertante.
# ══════════════════════════════════════════════════════════════════════
@router.get("/api/activos/{activo_id}")
def ficha(activo_id: int, cur: dict = Depends(verify_token),
          db: Session = Depends(get_tenant_db)):
    f = q1(db, "SELECT a.*, c.nombre AS categoria, c.cuenta_activo, c.cuenta_deprec, "
               "       c.cuenta_gasto, c.tasa_anual "
               "FROM activos a JOIN cat_activos c ON c.id = a.categoria_id WHERE a.id=:i",
           {"i": activo_id})
    if not f:
        raise HTTPException(404, "Activo no encontrado")
    d = _con_calculo(dict(f))

    mant = serial(q(db, "SELECT * FROM activo_mantenimientos WHERE activo_id=:i "
                        "ORDER BY fecha DESC", {"i": activo_id}))
    hist = serial(q(db, "SELECT d.*, p.periodo FROM deprec_detalle d "
                        "JOIN deprec_periodos p ON p.id = d.periodo_id "
                        "WHERE d.activo_id=:i ORDER BY p.periodo DESC LIMIT 36",
                    {"i": activo_id}))

    # Proyección: los próximos doce meses. Sirve para presupuestar y para ver
    # de un vistazo cuándo el equipo deja de generar gasto.
    proy, acum, cuota = [], d["deprec_acum"], d["cuota_mensual"]
    per = _periodo_actual()
    for _ in range(12):
        a, m = int(per[:4]), int(per[5:7])
        per = f"{a + 1}-01" if m == 12 else f"{a}-{m + 1:02d}"
        c = min(cuota, max(d["base_depreciable"] - acum, 0.0))
        if c <= 0:
            break
        acum = round(acum + c, 2)
        proy.append({"periodo": per, "cuota": round(c, 2),
                     "acumulado": acum, "valor_libros": round(d["valor_compra"] - acum, 2)})

    return {"ok": True, "activo": d, "mantenimientos": mant,
            "costo_mantenimiento": round(sum(float(x["costo"] or 0) for x in mant), 2),
            "historial": hist, "proyeccion": proy}
