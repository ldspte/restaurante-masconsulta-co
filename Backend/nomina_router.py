# -*- coding: utf-8 -*-
"""
================================================================
  RESTAURANTE · Módulo NÓMINA Y SEGURIDAD SOCIAL
================================================================
Liquidación de nómina conforme a la legislación laboral colombiana: devengados,
deducciones del trabajador, aportes del empleador y provisión de prestaciones
sociales.

LOS PARÁMETROS LEGALES NO SE QUEMAN EN EL CÓDIGO
------------------------------------------------
El salario mínimo, el auxilio de transporte y la UVT cambian **por decreto cada
diciembre**. Si estuvieran en el código, actualizar el año exigiría desplegar, y
—peor— una liquidación de un período anterior dejaría de poder reproducirse con
los valores que regían entonces.

Viven en `nomina_parametros`, indexados **por año**. El sistema se niega a
liquidar si el año en curso no tiene parámetros cargados y confirmados: es
preferible bloquear a producir una liquidación incorrecta que nadie revisará.

QUÉ SE LIQUIDA
--------------
    DEVENGADO   salario + auxilio de transporte + horas extra + recargos
    DEDUCIDO    salud 4 % + pensión 4 % + fondo de solidaridad + retención
    NETO        devengado − deducido

    APORTES DEL EMPLEADOR (no se descuentan al trabajador)
                salud 8,5 % · pensión 12 % · ARL según clase de riesgo
                caja de compensación 4 % · SENA 2 % · ICBF 3 %

    PRESTACIONES (provisión mensual)
                cesantías 8,33 % · intereses 1 % · prima 8,33 % · vacaciones 4,17 %

EXONERACIÓN DEL ARTÍCULO 114-1
------------------------------
Los empleadores están exonerados de aportar SENA, ICBF y el 8,5 % de salud por
los trabajadores que devenguen **menos de 10 salarios mínimos**. Es una regla que
cambia sustancialmente el costo de la nómina de un restaurante —donde casi toda
la planta está por debajo de ese umbral— y por eso se aplica automáticamente,
con interruptor por si la empresa no califica.

BASE DE COTIZACIÓN
------------------
El auxilio de transporte **no** hace parte de la base de seguridad social. Es el
error más común al liquidar a mano y produce diferencias que la UGPP detecta.

Rutas
  GET/PUT  /api/nomina/parametros
  GET/POST/PUT  /api/nomina/empleados
  GET/POST /api/nomina/periodos
  POST     /api/nomina/periodos/{id}/liquidar
  POST     /api/nomina/periodos/{id}/cerrar
  GET      /api/nomina/periodos/{id}
  GET      /api/nomina/pila            resumen para la planilla de aportes

Autor: Arquitectura de Software · Unidad 1
================================================================
"""
from __future__ import annotations

import datetime
import logging

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from db import anio_actual, ahora, hoy, q, q1, run, run_sin_commit, serial, siguiente_consecutivo
from dependencias import get_tenant_db
from eventos import Evento, TipoEvento, publicar
from seguridad import autor, require_rol, verify_token

log = logging.getLogger("restaurante.nomina")
router = APIRouter(tags=["Nómina"])

ROLES_NOMINA = ("admin", "gerente")

# El auxilio de transporte se paga a quien devengue hasta DOS salarios mínimos.
TOPE_AUXILIO_SMMLV = 2
# Exoneración del artículo 114-1 del Estatuto Tributario.
TOPE_EXONERACION_SMMLV = 10
# Fondo de solidaridad pensional: aporte adicional desde 4 SMMLV.
TOPE_SOLIDARIDAD_SMMLV = 4


# ══════════════════════════════════════════════════════════════════════
#  PARÁMETROS DEL AÑO
# ══════════════════════════════════════════════════════════════════════
def parametros(db: Session, anio: int) -> dict:
    fila = q1(db, "SELECT * FROM nomina_parametros WHERE anio=:a", {"a": anio})
    if not fila:
        raise HTTPException(
            409, f"No hay parámetros de nómina cargados para {anio}. "
                 f"Configure salario mínimo, auxilio de transporte y UVT antes de liquidar.")
    if not int(fila.get("vigente") or 0):
        raise HTTPException(
            409, f"Los parámetros de {anio} están sin confirmar. El salario mínimo y el "
                 f"auxilio de transporte cambian por decreto cada año: verifíquelos y "
                 f"márquelos como vigentes antes de liquidar.")
    if float(fila.get("smmlv") or 0) <= 0:
        raise HTTPException(409, f"El salario mínimo de {anio} está en cero.")
    return dict(fila)


@router.get("/api/nomina/parametros")
def parametros_listar(cur: dict = Depends(require_rol(*ROLES_NOMINA)),
                      db: Session = Depends(get_tenant_db)):
    anio = anio_actual()
    filas = serial(q(db, "SELECT * FROM nomina_parametros ORDER BY anio DESC"))
    actual = next((f for f in filas if int(f["anio"]) == anio), None)

    aviso = None
    if not actual:
        aviso = f"No hay parámetros para {anio}. No se puede liquidar nómina."
    elif not int(actual.get("vigente") or 0) or float(actual.get("smmlv") or 0) <= 0:
        aviso = (f"Los parámetros de {anio} están sin confirmar. Cargue el salario mínimo y "
                 f"el auxilio de transporte del decreto vigente y márquelos como vigentes.")

    return {"ok": True, "items": filas, "anio": anio, "aviso": aviso,
            "arl": serial(q(db, "SELECT * FROM arl_tarifas ORDER BY clase"))}


@router.put("/api/nomina/parametros/{anio}")
def parametros_guardar(anio: int, body: dict = Body(...),
                       cur: dict = Depends(require_rol("admin")),
                       db: Session = Depends(get_tenant_db)):
    campos = ("smmlv", "auxilio_transporte", "uvt", "salud_empleado", "salud_empleador",
              "pension_empleado", "pension_empleador", "sena", "icbf", "caja",
              "cesantias", "int_cesantias", "prima", "vacaciones",
              "exonerado_1607", "vigente")
    datos = {k: body[k] for k in campos if k in body}
    if not datos:
        return {"ok": True, "sin_cambios": True}

    if float(datos.get("smmlv", 1)) < 0 or float(datos.get("auxilio_transporte", 0)) < 0:
        raise HTTPException(400, "Los valores no pueden ser negativos")
    # No se deja marcar vigente un año sin salario mínimo: sería habilitar la
    # liquidación con la base en cero.
    if int(datos.get("vigente", 0)) == 1 and float(datos.get("smmlv") or 0) <= 0:
        actual = q1(db, "SELECT smmlv FROM nomina_parametros WHERE anio=:a", {"a": anio})
        if float((actual or {}).get("smmlv") or 0) <= 0:
            raise HTTPException(400, "Cargue el salario mínimo antes de marcar el año como vigente")

    existe = q1(db, "SELECT anio FROM nomina_parametros WHERE anio=:a", {"a": anio})
    if existe:
        sets = ", ".join(f"{k}=:{k}" for k in datos)
        run(db, f"UPDATE nomina_parametros SET {sets} WHERE anio=:anio", dict(datos, anio=anio))
    else:
        cols = ", ".join(datos.keys())
        ph = ", ".join(f":{k}" for k in datos)
        run(db, f"INSERT INTO nomina_parametros (anio, {cols}) VALUES (:anio, {ph})",
            dict(datos, anio=anio))
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════
#  EMPLEADOS
# ══════════════════════════════════════════════════════════════════════
@router.get("/api/nomina/empleados")
def empleados_listar(cur: dict = Depends(require_rol("admin", "gerente", "sst")),
                     db: Session = Depends(get_tenant_db)):
    filas = serial(q(db, "SELECT e.*, CONCAT(e.nombres,' ',e.apellidos) AS nombre, "
                         "       COALESCE(es.nombre,'') AS estacion, "
                         "       COALESCE(a.tarifa,0) AS tarifa_arl "
                         "FROM empleados e "
                         "LEFT JOIN estaciones es ON es.id=e.estacion_id "
                         "LEFT JOIN arl_tarifas a ON a.clase=e.clase_riesgo "
                         "WHERE e.activo=1 ORDER BY e.apellidos, e.nombres"))
    return {"ok": True, "items": filas,
            "kpis": {"total": len(filas),
                     "masa_salarial": round(sum(float(f["salario_base"] or 0)
                                                for f in filas), 2),
                     "con_auxilio": sum(1 for f in filas if int(f["aplica_auxilio"] or 0))},
            "arl": serial(q(db, "SELECT * FROM arl_tarifas ORDER BY clase")),
            "estaciones": serial(q(db, "SELECT id, nombre FROM estaciones WHERE activo=1"))}


@router.post("/api/nomina/empleados", status_code=201)
def empleado_crear(body: dict = Body(...), cur: dict = Depends(require_rol(*ROLES_NOMINA)),
                   db: Session = Depends(get_tenant_db)):
    doc = (body.get("numero_doc") or "").strip()
    nombres = (body.get("nombres") or "").strip()
    apellidos = (body.get("apellidos") or "").strip()
    salario = float(body.get("salario_base") or 0)

    if not doc or not nombres or not apellidos:
        raise HTTPException(400, "Documento, nombres y apellidos son obligatorios")
    if salario <= 0:
        raise HTTPException(400, "El salario base debe ser mayor que cero")
    if q1(db, "SELECT id FROM empleados WHERE numero_doc=:d", {"d": doc}):
        raise HTTPException(409, f"Ya existe un empleado con el documento {doc}")

    # La afiliación a EPS, AFP y ARL es OBLIGATORIA antes de que la persona
    # empiece a trabajar. Permitir el alta sin ellas convierte el sistema en
    # cómplice de una infracción que, ante un accidente, es muy costosa.
    faltan = [c for c in ("eps", "afp", "arl") if not (body.get(c) or "").strip()]
    if faltan:
        raise HTTPException(400, f"Debe registrar la afiliación a: {', '.join(faltan).upper()}. "
                                 f"Es obligatoria antes del ingreso.")

    anio = anio_actual()
    p = q1(db, "SELECT smmlv FROM nomina_parametros WHERE anio=:a", {"a": anio}) or {}
    smmlv = float(p.get("smmlv") or 0)
    aplica_aux = int(body.get("aplica_auxilio", 1 if (smmlv and salario <= smmlv * TOPE_AUXILIO_SMMLV) else 0))

    res = run(db, "INSERT INTO empleados (tipo_doc, numero_doc, nombres, apellidos, cargo, "
                  "estacion_id, tipo_contrato, fecha_ingreso, salario_base, aplica_auxilio, "
                  "eps, afp, arl, clase_riesgo, caja_compensacion, puntos_propina, email, "
                  "telefono, activo, creado_en) "
                  "VALUES (:td,:d,:n,:a,:c,:e,:tc,:fi,:s,:aux,:eps,:afp,:arl,:cr,:caja,"
                  ":pt,:em,:tel,1,:ts)",
              {"td": body.get("tipo_doc") or "13", "d": doc, "n": nombres, "a": apellidos,
               "c": body.get("cargo"), "e": body.get("estacion_id") or None,
               "tc": body.get("tipo_contrato") or "Término indefinido",
               "fi": body.get("fecha_ingreso") or hoy(), "s": salario, "aux": aplica_aux,
               "eps": body["eps"], "afp": body["afp"], "arl": body["arl"],
               "cr": body.get("clase_riesgo") or "II",
               "caja": body.get("caja_compensacion"),
               "pt": float(body.get("puntos_propina") or 1),
               "em": body.get("email"), "tel": body.get("telefono"), "ts": ahora()})
    return {"ok": True, "id": getattr(res, "lastrowid", 0)}


@router.put("/api/nomina/empleados/{eid}")
def empleado_editar(eid: int, body: dict = Body(...),
                    cur: dict = Depends(require_rol(*ROLES_NOMINA)),
                    db: Session = Depends(get_tenant_db)):
    if not q1(db, "SELECT id FROM empleados WHERE id=:i", {"i": eid}):
        raise HTTPException(404, "Empleado no encontrado")
    campos = {k: body[k] for k in ("cargo", "estacion_id", "tipo_contrato", "salario_base",
                                   "aplica_auxilio", "eps", "afp", "arl", "clase_riesgo",
                                   "caja_compensacion", "puntos_propina", "email",
                                   "telefono", "fecha_retiro", "activo") if k in body}
    if not campos:
        return {"ok": True, "sin_cambios": True}
    sets = ", ".join(f"{k}=:{k}" for k in campos)
    run(db, f"UPDATE empleados SET {sets} WHERE id=:id", dict(campos, id=eid))
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════
#  MOTOR DE LIQUIDACIÓN
# ══════════════════════════════════════════════════════════════════════
def liquidar_empleado(emp: dict, par: dict, dias: int, novedades: dict,
                      tarifa_arl: float) -> dict:
    """Liquida un empleado para un período. Función PURA: no toca la base.

    Serlo es deliberado — permite probar el cálculo con casos conocidos sin
    montar un período completo, que es justamente lo que hace verificable una
    nómina.
    """
    smmlv = float(par["smmlv"])
    salario_mes = float(emp["salario_base"] or 0)
    salario = round(salario_mes * dias / 30.0, 2)

    # ── Devengados ──
    auxilio = 0.0
    if int(emp.get("aplica_auxilio") or 0) and salario_mes <= smmlv * TOPE_AUXILIO_SMMLV:
        auxilio = round(float(par["auxilio_transporte"]) * dias / 30.0, 2)

    extras = round(float(novedades.get("horas_extra") or 0), 2)
    noct = round(float(novedades.get("recargo_nocturno") or 0), 2)
    domi = round(float(novedades.get("recargo_dominical") or 0), 2)
    otros = round(float(novedades.get("otros_devengados") or 0), 2)
    # Pagos pactados como NO constitutivos de salario: bonificaciones
    # ocasionales, auxilios de alimentación o vivienda. Se pagan, pero no
    # cotizan… hasta cierto punto. Ver el tope más abajo.
    no_sal = round(float(novedades.get("no_salarial") or 0), 2)
    devengado = round(salario + auxilio + extras + noct + domi + otros + no_sal, 2)

    # ── Base de cotización ──
    # El auxilio de transporte NO hace parte de la base de seguridad social.
    # Es el error más frecuente al liquidar a mano y produce diferencias que la
    # UGPP detecta en fiscalización.
    base = round(devengado - auxilio - no_sal, 2)

    # TOPE DEL 40 % · artículo 30 de la Ley 1393 de 2010.
    # Los pagos no salariales no pueden superar el 40 % del total de la
    # remuneración. Lo que exceda ese porcentaje SÍ cotiza, aunque las partes
    # lo hayan pactado como no salarial: el acuerdo no le gana a la ley.
    #
    # Ignorar este tope subestima los aportes y produce exactamente la
    # diferencia que la UGPP persigue en fiscalización.
    exceso_40 = 0.0
    if no_sal > 0:
        total_remuneracion = round(devengado - auxilio, 2)
        tope = round(total_remuneracion * 0.40, 2)
        if no_sal > tope:
            exceso_40 = round(no_sal - tope, 2)
            base = round(base + exceso_40, 2)

    # Piso legal: nadie cotiza por debajo de un salario mínimo proporcional.
    base_minima = round(smmlv * dias / 30.0, 2)
    base = max(base, base_minima)

    # ── Deducciones del trabajador ──
    salud_emp = round(base * float(par["salud_empleado"]) / 100, 2)
    pension_emp = round(base * float(par["pension_empleado"]) / 100, 2)

    # Fondo de solidaridad pensional: 1 % adicional desde 4 salarios mínimos.
    solidaridad = 0.0
    if salario_mes >= smmlv * TOPE_SOLIDARIDAD_SMMLV:
        solidaridad = round(base * 1.0 / 100, 2)

    retefuente = round(float(novedades.get("retefuente") or 0), 2)
    otras_ded = round(float(novedades.get("otras_deducciones") or 0), 2)
    deducido = round(salud_emp + pension_emp + solidaridad + retefuente + otras_ded, 2)
    neto = round(devengado - deducido, 2)

    # ── Aportes del empleador ──
    exonerado = (int(par.get("exonerado_1607") or 0) == 1
                 and salario_mes < smmlv * TOPE_EXONERACION_SMMLV)

    salud_pat = 0.0 if exonerado else round(base * float(par["salud_empleador"]) / 100, 2)
    sena = 0.0 if exonerado else round(base * float(par["sena"]) / 100, 2)
    icbf = 0.0 if exonerado else round(base * float(par["icbf"]) / 100, 2)

    pension_pat = round(base * float(par["pension_empleador"]) / 100, 2)
    # La ARL la paga ÍNTEGRAMENTE el empleador y su tarifa depende de la clase
    # de riesgo del cargo: un cocinero no cotiza igual que un administrativo.
    arl = round(base * float(tarifa_arl or 0) / 100, 2)
    caja = round(base * float(par["caja"]) / 100, 2)

    # ── Prestaciones sociales (provisión mensual) ──
    # Se provisionan sobre devengado INCLUYENDO auxilio de transporte —al
    # contrario que la seguridad social—, salvo las vacaciones, que se calculan
    # solo sobre el salario.
    # Lo no salarial tampoco entra aquí: si no es salario, no genera cesantías
    # ni prima. Incluirlo sería provisionar una obligación que no existe.
    base_prest = round(salario + auxilio + extras + noct + domi + otros, 2)
    cesantias = round(base_prest * float(par["cesantias"]) / 100, 2)
    int_ces = round(cesantias * float(par["int_cesantias"]) / 100, 2)
    prima = round(base_prest * float(par["prima"]) / 100, 2)
    vacaciones = round(salario * float(par["vacaciones"]) / 100, 2)

    return {
        "dias": dias, "salario": salario, "auxilio_transporte": auxilio,
        "horas_extra": extras, "recargo_nocturno": noct, "recargo_dominical": domi,
        "otros_devengados": otros, "no_salarial": no_sal,
        "exceso_40": exceso_40, "total_devengado": devengado,
        "base_seguridad": base,
        "salud_empleado": salud_emp, "pension_empleado": pension_emp,
        "fondo_solidaridad": solidaridad, "retefuente": retefuente,
        "otras_deducciones": otras_ded, "total_deducido": deducido, "neto_pagar": neto,
        "salud_empleador": salud_pat, "pension_empleador": pension_pat, "arl": arl,
        "caja_compensacion": caja, "sena": sena, "icbf": icbf,
        "cesantias": cesantias, "int_cesantias": int_ces, "prima": prima,
        "vacaciones": vacaciones,
        "_exonerado": exonerado,
        # Se compara el salario MENSUAL contra el mínimo, no el proporcional:
        # trabajar quince días no autoriza a pagar por debajo del mínimo
        # mensual, autoriza a pagar la mitad de ese mínimo.
        "_bajo_minimo": salario_mes < smmlv,
        "_faltante_minimo": round(max(smmlv - salario_mes, 0), 2),
    }


# ══════════════════════════════════════════════════════════════════════
#  PERÍODOS
# ══════════════════════════════════════════════════════════════════════
@router.get("/api/nomina/periodos")
def periodos_listar(cur: dict = Depends(require_rol(*ROLES_NOMINA)),
                    db: Session = Depends(get_tenant_db)):
    return {"ok": True,
            "items": serial(q(db, "SELECT * FROM nomina_periodos ORDER BY id DESC LIMIT 60"))}


@router.post("/api/nomina/periodos", status_code=201)
def periodo_crear(body: dict = Body(...), cur: dict = Depends(require_rol(*ROLES_NOMINA)),
                  db: Session = Depends(get_tenant_db)):
    desde = (body.get("desde") or "").strip()
    hasta = (body.get("hasta") or "").strip()
    if not desde or not hasta:
        raise HTTPException(400, "Indique el período (desde y hasta)")
    try:
        d1 = datetime.date.fromisoformat(desde)
        d2 = datetime.date.fromisoformat(hasta)
    except ValueError:
        raise HTTPException(400, "Las fechas deben tener formato AAAA-MM-DD")
    if d2 < d1:
        raise HTTPException(400, "La fecha final no puede ser anterior a la inicial")

    anio = d1.year
    parametros(db, anio)      # falla temprano si el año no está configurado

    if q1(db, "SELECT id FROM nomina_periodos WHERE desde=:d AND hasta=:h",
          {"d": desde, "h": hasta}):
        raise HTTPException(409, "Ya existe un período con esas fechas")

    dias = int(body.get("dias") or 30)
    numero = f"NOM-{anio}-{siguiente_consecutivo(db, 'nomina', anio):03d}"
    res = run(db, "INSERT INTO nomina_periodos (numero, desde, hasta, dias, anio, estado, "
                  "creado_por, creado_en) VALUES (:n,:d,:h,:di,:a,'borrador',:u,:ts)",
              {"n": numero, "d": desde, "h": hasta, "di": dias, "a": anio,
               "u": autor(cur), "ts": ahora()})
    return {"ok": True, "id": getattr(res, "lastrowid", 0), "numero": numero}


@router.post("/api/nomina/periodos/{pid}/liquidar")
def periodo_liquidar(pid: int, body: dict = Body(default={}),
                     cur: dict = Depends(require_rol(*ROLES_NOMINA)),
                     db: Session = Depends(get_tenant_db)):
    """Liquida el período completo. Se puede repetir mientras esté en borrador:
    corregir un salario y volver a liquidar es la operación normal."""
    periodo = q1(db, "SELECT * FROM nomina_periodos WHERE id=:i", {"i": pid})
    if not periodo:
        raise HTTPException(404, "Período no encontrado")
    if periodo["estado"] == "cerrado":
        raise HTTPException(409, "El período ya está cerrado. No puede reliquidarse.")

    par = parametros(db, int(periodo["anio"]))
    tarifas = {r["clase"]: float(r["tarifa"] or 0)
               for r in q(db, "SELECT clase, tarifa FROM arl_tarifas")}
    # Las novedades viven en la base, no en el cuerpo de la petición. Es lo
    # que permite registrarlas a lo largo del mes —el bono el día 5, el
    # préstamo el 12— y liquidar al final sin volver a teclearlas.
    novedades = _novedades_del_periodo(db, pid)
    # Se admite además lo que venga en el cuerpo, que gana sobre lo guardado:
    # sirve para simular un escenario sin registrar nada.
    for k, v in (body.get("novedades") or {}).items():
        novedades.setdefault(int(k), {}).update(v or {})

    empleados = q(db, "SELECT * FROM empleados WHERE activo=1 ORDER BY apellidos, nombres")
    if not empleados:
        raise HTTPException(409, "No hay empleados activos para liquidar")

    try:
        run_sin_commit(db, "DELETE FROM nomina_detalle WHERE periodo_id=:p", {"p": pid})

        tot = {"devengado": 0.0, "deducido": 0.0, "neto": 0.0,
               "aportes": 0.0, "prestaciones": 0.0}
        exonerados = 0
        bajo_minimo: list[dict] = []

        for e in empleados:
            nov = novedades.get(int(e["id"]), {})
            dias = int(nov.get("dias") or periodo["dias"] or 30)
            liq = liquidar_empleado(dict(e), par, dias, nov,
                                    tarifas.get(e["clase_riesgo"] or "II", 0))
            if liq.pop("_exonerado"):
                exonerados += 1
            if liq.pop("_bajo_minimo"):
                bajo_minimo.append({
                    "empleado": f"{e['nombres']} {e['apellidos']}",
                    "cargo": e.get("cargo"),
                    "salario": float(e["salario_base"] or 0),
                    "faltante": liq["_faltante_minimo"]})
            liq.pop("_faltante_minimo")

            aportes = (liq["salud_empleador"] + liq["pension_empleador"] + liq["arl"]
                       + liq["caja_compensacion"] + liq["sena"] + liq["icbf"])
            prest = (liq["cesantias"] + liq["int_cesantias"] + liq["prima"]
                     + liq["vacaciones"])
            tot["devengado"] += liq["total_devengado"]
            tot["deducido"] += liq["total_deducido"]
            tot["neto"] += liq["neto_pagar"]
            tot["aportes"] += aportes
            tot["prestaciones"] += prest

            cols = ", ".join(liq.keys())
            ph = ", ".join(f":{k}" for k in liq)
            run_sin_commit(db,
                           f"INSERT INTO nomina_detalle (periodo_id, empleado_id, nombre, "
                           f"cargo, {cols}) VALUES (:pid, :eid, :nom, :car, {ph})",
                           dict(liq, pid=pid, eid=e["id"],
                                nom=f"{e['nombres']} {e['apellidos']}", car=e.get("cargo")))

        run_sin_commit(db, "UPDATE nomina_periodos SET estado='liquidado', "
                           "total_devengado=:d, total_deducido=:de, total_neto=:n, "
                           "total_aportes=:a, total_prestaciones=:pr WHERE id=:i",
                       {"d": round(tot["devengado"], 2), "de": round(tot["deducido"], 2),
                        "n": round(tot["neto"], 2), "a": round(tot["aportes"], 2),
                        "pr": round(tot["prestaciones"], 2), "i": pid})
        db.commit()
    except Exception:
        db.rollback()
        raise

    costo_total = round(tot["devengado"] + tot["aportes"] + tot["prestaciones"], 2)
    log.info("Nómina %s liquidada: %s empleados, costo total %.2f",
             periodo["numero"], len(empleados), costo_total)

    return {"ok": True, "numero": periodo["numero"], "empleados": len(empleados),
            "totales": {k: round(v, 2) for k, v in tot.items()},
            "costo_total_empresa": costo_total,
            # Lo que el dueño realmente necesita saber: por cada peso de sueldo,
            # cuánto sale del bolsillo de la empresa.
            "factor_prestacional": round(costo_total / tot["devengado"], 4)
                                   if tot["devengado"] else None,
            "exonerados_1607": exonerados,
            # Se avisa, no se bloquea: hay jornadas parciales legítimas. La
            # decisión es del gerente; el sistema garantiza que la tome viendo
            # el dato, no descubriéndolo en una inspección.
            "bajo_minimo": bajo_minimo,
            "mensaje": (f"Nómina liquidada: {len(empleados)} empleado(s), "
                        f"costo total ${costo_total:,.0f}."
                        + (f" ATENCIÓN: {len(bajo_minimo)} persona(s) por debajo "
                           f"del salario mínimo." if bajo_minimo else ""))}


@router.get("/api/nomina/periodos/{pid}")
def periodo_detalle(pid: int, cur: dict = Depends(require_rol(*ROLES_NOMINA)),
                    db: Session = Depends(get_tenant_db)):
    periodo = q1(db, "SELECT * FROM nomina_periodos WHERE id=:i", {"i": pid})
    if not periodo:
        raise HTTPException(404, "Período no encontrado")
    detalle = serial(q(db, "SELECT * FROM nomina_detalle WHERE periodo_id=:p "
                           "ORDER BY nombre", {"p": pid}))
    dev = float(periodo["total_devengado"] or 0)
    costo = round(dev + float(periodo["total_aportes"] or 0)
                  + float(periodo["total_prestaciones"] or 0), 2)
    return {"ok": True, "periodo": serial(dict(periodo))[0], "detalle": detalle,
            "costo_total_empresa": costo,
            "factor_prestacional": round(costo / dev, 4) if dev else None}


@router.post("/api/nomina/periodos/{pid}/cerrar")
def periodo_cerrar(pid: int, cur: dict = Depends(require_rol("admin")),
                   db: Session = Depends(get_tenant_db)):
    """Cierra el período y lo contabiliza. Irreversible: una nómina cerrada es un
    hecho histórico y su reliquidación produciría asientos duplicados."""
    periodo = q1(db, "SELECT * FROM nomina_periodos WHERE id=:i", {"i": pid})
    if not periodo:
        raise HTTPException(404, "Período no encontrado")
    if periodo["estado"] != "liquidado":
        raise HTTPException(409, "El período debe estar liquidado antes de cerrarse")

    try:
        run_sin_commit(db, "UPDATE nomina_periodos SET estado='cerrado', cerrado_en=:ts "
                           "WHERE id=:i", {"ts": ahora(), "i": pid})
        publicar(db, Evento(
            tipo=TipoEvento.NOMINA_CERRADA, entidad="nomina", entidad_id=pid,
            payload={"numero": periodo["numero"],
                     "devengado": float(periodo["total_devengado"] or 0),
                     "deducido": float(periodo["total_deducido"] or 0),
                     "neto": float(periodo["total_neto"] or 0),
                     "aportes": float(periodo["total_aportes"] or 0),
                     "prestaciones": float(periodo["total_prestaciones"] or 0)},
            usuario=autor(cur)))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True, "numero": periodo["numero"]}


# ══════════════════════════════════════════════════════════════════════
#  PILA — planilla integrada de aportes
# ══════════════════════════════════════════════════════════════════════
@router.get("/api/nomina/pila")
def pila(periodo_id: int, cur: dict = Depends(require_rol(*ROLES_NOMINA)),
         db: Session = Depends(get_tenant_db)):
    """Resumen de aportes a la seguridad social por entidad.

    Es la vista que se necesita para pagar: la planilla se liquida por
    administradora, no por empleado, y agrupar a mano una planta de veinte
    personas es donde aparecen las diferencias.
    """
    periodo = q1(db, "SELECT * FROM nomina_periodos WHERE id=:i", {"i": periodo_id})
    if not periodo:
        raise HTTPException(404, "Período no encontrado")

    # Los alias son OBLIGATORIOS aquí: `nomina_detalle.arl` es el VALOR del aporte
    # y `empleados.arl` es el NOMBRE de la administradora. Sin alias, el segundo
    # pisa al primero en el diccionario resultante y el intento de sumar produce
    # «could not convert string to float: 'ARL Sura'». Lo mismo aplica a
    # `caja_compensacion`.
    filas = q(db, "SELECT d.*, e.eps AS ent_eps, e.afp AS ent_afp, "
                  "       e.arl AS ent_arl, e.caja_compensacion AS ent_caja, "
                  "       e.numero_doc "
                  "FROM nomina_detalle d JOIN empleados e ON e.id=d.empleado_id "
                  "WHERE d.periodo_id=:p", {"p": periodo_id})

    def agrupar(campo: str, *conceptos: str) -> list[dict]:
        acc: dict[str, dict] = {}
        for f in filas:
            clave = f.get(campo) or "(sin afiliación)"
            d = acc.setdefault(clave, {"entidad": clave, "empleados": 0, "valor": 0.0})
            d["empleados"] += 1
            d["valor"] += sum(float(f.get(c) or 0) for c in conceptos)
        for d in acc.values():
            d["valor"] = round(d["valor"], 2)
        return sorted(acc.values(), key=lambda x: -x["valor"])

    salud = agrupar("ent_eps", "salud_empleado", "salud_empleador")
    pension = agrupar("ent_afp", "pension_empleado", "pension_empleador", "fondo_solidaridad")
    riesgos = agrupar("ent_arl", "arl")
    caja = agrupar("ent_caja", "caja_compensacion")

    total = round(sum(x["valor"] for grupo in (salud, pension, riesgos, caja)
                      for x in grupo), 2)
    return {"ok": True, "periodo": serial(dict(periodo))[0],
            "salud": salud, "pension": pension, "riesgos": riesgos, "caja": caja,
            "parafiscales": {
                "sena": round(sum(float(f.get("sena") or 0) for f in filas), 2),
                "icbf": round(sum(float(f.get("icbf") or 0) for f in filas), 2)},
            "total_planilla": total,
            "empleados": len(filas)}


# ══════════════════════════════════════════════════════════════════════
#  NOVEDADES DEL PERÍODO
#
#  Un bono, unas horas extra, un préstamo o un embargo. Se registran cuando
#  ocurren y la liquidación las recoge al final del mes: obligar a teclearlas
#  todas el día del cierre es la receta para que alguna se olvide.
#
#  TIPOS Y POR QUÉ IMPORTA LA DISTINCIÓN
#  · horas_extra, recargo_nocturno, recargo_dominical → salariales: cotizan y
#    generan prestaciones.
#  · otros_devengados → salariales (comisiones, primas de producción).
#  · no_salarial → pactado como NO constitutivo de salario. No cotiza… hasta
#    el 40 % de la remuneración total. El exceso sí, por el artículo 30 de la
#    Ley 1393 de 2010.
#  · retefuente, otras_deducciones → se le descuentan al trabajador.
# ══════════════════════════════════════════════════════════════════════
TIPOS_NOVEDAD = {
    "horas_extra":       ("Horas extra", "devengado"),
    "recargo_nocturno":  ("Recargo nocturno", "devengado"),
    "recargo_dominical": ("Recargo dominical y festivo", "devengado"),
    "otros_devengados":  ("Bonificación salarial o comisión", "devengado"),
    "no_salarial":       ("Bono NO salarial (auxilio, bonificación ocasional)", "devengado"),
    "retefuente":        ("Retención en la fuente", "deduccion"),
    "otras_deducciones": ("Préstamo, embargo, libranza u otro descuento", "deduccion"),
}


def _novedades_del_periodo(db: Session, pid: int) -> dict:
    """Suma las novedades por empleado y tipo. `{empleado_id: {tipo: valor}}`."""
    salida: dict[int, dict] = {}
    for r in q(db, "SELECT empleado_id, tipo, SUM(valor) AS v FROM nomina_novedades "
                   "WHERE periodo_id=:p GROUP BY empleado_id, tipo", {"p": pid}):
        salida.setdefault(int(r["empleado_id"]), {})[r["tipo"]] = float(r["v"] or 0)
    return salida


@router.get("/api/nomina/periodos/{pid}/novedades")
def novedades_listar(pid: int, cur: dict = Depends(verify_token),
                     db: Session = Depends(get_tenant_db)):
    filas = serial(q(db, "SELECT n.*, CONCAT(e.nombres,' ',e.apellidos) AS empleado, "
                         "       e.cargo "
                         "FROM nomina_novedades n JOIN empleados e ON e.id = n.empleado_id "
                         "WHERE n.periodo_id=:p ORDER BY e.apellidos, n.id", {"p": pid}))
    for f_ in filas:
        etiqueta, clase = TIPOS_NOVEDAD.get(f_["tipo"], (f_["tipo"], "devengado"))
        f_["etiqueta"] = etiqueta
        f_["clase"] = clase
    tot_dev = sum(float(f_["valor"]) for f_ in filas if f_["clase"] == "devengado")
    tot_ded = sum(float(f_["valor"]) for f_ in filas if f_["clase"] == "deduccion")
    return {"ok": True, "items": filas,
            "tipos": [{"clave": k, "etiqueta": v[0], "clase": v[1]}
                      for k, v in TIPOS_NOVEDAD.items()],
            "totales": {"devengados": round(tot_dev, 2),
                        "deducciones": round(tot_ded, 2)}}


@router.post("/api/nomina/periodos/{pid}/novedades", status_code=201)
def novedad_crear(pid: int, body: dict = Body(...),
                  cur: dict = Depends(require_rol(*ROLES_NOMINA)),
                  db: Session = Depends(get_tenant_db)):
    periodo = q1(db, "SELECT * FROM nomina_periodos WHERE id=:i", {"i": pid})
    if not periodo:
        raise HTTPException(404, "Período no encontrado")
    if periodo["estado"] == "cerrado":
        raise HTTPException(409, "El período ya está cerrado. Anúlelo para corregirlo.")

    tipo = (body.get("tipo") or "").strip()
    if tipo not in TIPOS_NOVEDAD:
        raise HTTPException(400, f"Tipo de novedad inválido: «{tipo}»")

    empleado_id = int(body.get("empleado_id") or 0)
    emp = q1(db, "SELECT id, nombres, apellidos FROM empleados WHERE id=:i AND activo=1",
             {"i": empleado_id})
    if not emp:
        raise HTTPException(404, "Empleado no encontrado o inactivo")

    try:
        valor = round(float(body.get("valor") or 0), 2)
    except (TypeError, ValueError):
        valor = 0
    if valor <= 0:
        raise HTTPException(400, "El valor debe ser mayor que cero")

    res = run(db, "INSERT INTO nomina_novedades (periodo_id, empleado_id, tipo, concepto, "
                  "valor, creado_por, creado_en) VALUES (:p,:e,:t,:c,:v,:u,:ts)",
              {"p": pid, "e": empleado_id, "t": tipo,
               "c": (body.get("concepto") or "").strip()[:200] or None,
               "v": valor, "u": autor(cur), "ts": ahora()})
    return {"ok": True, "id": getattr(res, "lastrowid", 0),
            "mensaje": f"Novedad registrada para {emp['nombres']}. "
                       "Vuelva a liquidar para que se refleje."}


@router.delete("/api/nomina/novedades/{nid}")
def novedad_borrar(nid: int, cur: dict = Depends(require_rol(*ROLES_NOMINA)),
                   db: Session = Depends(get_tenant_db)):
    n = q1(db, "SELECT n.*, p.estado FROM nomina_novedades n "
               "JOIN nomina_periodos p ON p.id = n.periodo_id WHERE n.id=:i", {"i": nid})
    if not n:
        raise HTTPException(404, "Novedad no encontrada")
    if n["estado"] == "cerrado":
        raise HTTPException(409, "El período ya está cerrado.")
    run(db, "DELETE FROM nomina_novedades WHERE id=:i", {"i": nid})
    return {"ok": True, "mensaje": "Novedad eliminada. Vuelva a liquidar."}


# ══════════════════════════════════════════════════════════════════════
#  ANULACIÓN DE UN PERÍODO CERRADO
#
#  Un período cerrado no se edita: se ANULA con asientos que revierten los
#  originales, y se vuelve a liquidar. Editar un asiento ya registrado es
#  falsificar el libro; revertirlo deja el rastro de qué cambió y por qué.
#
#  Hace falta de verdad: si se liquidó con un salario mínimo equivocado —o
#  con el auxilio del año pasado—, la única salida honesta es esta.
# ══════════════════════════════════════════════════════════════════════
@router.post("/api/nomina/periodos/{pid}/anular")
def periodo_anular(pid: int, body: dict = Body(...),
                   cur: dict = Depends(require_rol(*ROLES_NOMINA)),
                   db: Session = Depends(get_tenant_db)):
    from contabilidad_router import _registrar_asiento

    periodo = q1(db, "SELECT * FROM nomina_periodos WHERE id=:i", {"i": pid})
    if not periodo:
        raise HTTPException(404, "Período no encontrado")
    if periodo["estado"] != "cerrado":
        raise HTTPException(409, "Solo se anula un período cerrado. "
                                 "Si está en borrador, vuelva a liquidarlo.")

    motivo = (body.get("motivo") or "").strip()
    if not motivo:
        raise HTTPException(400, "Diga por qué se anula el período. "
                                 "Queda en el asiento de reversión.")

    lineas_orig = q(db, "SELECT l.cuenta, l.debito, l.credito, a.tipo "
                        "FROM asiento_lineas l JOIN asientos a ON a.id = l.asiento_id "
                        "WHERE a.ref_tipo='nomina' AND a.ref_id=:i "
                        "AND a.tipo NOT LIKE '%reversion%'", {"i": pid})
    if not lineas_orig:
        raise HTTPException(409, "No se hallaron los asientos de este período.")

    try:
        # Un asiento de reversión por cada tipo original: se invierten débitos
        # y créditos. El neto queda en cero y ambos asientos son visibles.
        por_tipo: dict[str, list] = {}
        for l in lineas_orig:
            por_tipo.setdefault(l["tipo"], []).append(l)

        for tipo, lineas in por_tipo.items():
            _registrar_asiento(
                db, tipo=f"{tipo}_reversion",
                concepto=f"Reversión de {periodo['numero']} · {motivo}",
                lineas=[{"cuenta": l["cuenta"],
                         "debito": float(l["credito"] or 0),
                         "credito": float(l["debito"] or 0)} for l in lineas],
                ref_tipo="nomina_anulada", ref_id=pid, usuario=autor(cur))

        run_sin_commit(db, "UPDATE nomina_periodos SET estado='borrador', "
                           "cerrado_en=NULL WHERE id=:i", {"i": pid})
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {"ok": True, "asientos_revertidos": len(por_tipo),
            "mensaje": (f"{periodo['numero']} anulado y devuelto a borrador. "
                        f"Se generaron {len(por_tipo)} asiento(s) de reversión. "
                        "Ya puede corregir y volver a liquidar.")}
