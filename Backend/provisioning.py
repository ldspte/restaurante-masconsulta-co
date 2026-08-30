# -*- coding: utf-8 -*-
"""
================================================================
  RESTAURANTE · Aprovisionamiento  (MySQL)
================================================================
Crea el esquema y los datos mínimos para que el sistema opere. Es IDEMPOTENTE
de principio a fin: ejecutarlo diez veces deja el mismo estado que ejecutarlo
una. Esa propiedad permite llamarlo en cada arranque sin miedo y evita
necesitar un motor de migraciones para el prototipo.

Autor: Arquitectura de Software · Unidad 1
================================================================
"""
from __future__ import annotations

import datetime
import logging

from sqlalchemy.orm import Session

import seed_master
import seed_tenant
from db import (MASTER_DB, ahora, ahora_local, anio_actual, crear_base_si_no_existe, get_sessionmaker,
                nombre_db_tenant, q, q1, run)
from seguridad import hash_password

log = logging.getLogger("restaurante.provisioning")


# ══════════════════════════════════════════════════════════════════════
#  MAESTRA
# ══════════════════════════════════════════════════════════════════════
_TEXTOS_CARTA = {c: (d, dest, o) for c, d, dest, o in seed_tenant.CARTA_TEXTOS}


def crear_maestra() -> None:
    crear_base_si_no_existe(MASTER_DB)
    db = get_sessionmaker(MASTER_DB)()
    try:
        for ddl in seed_master.TABLAS:
            run(db, ddl)
    finally:
        db.close()


def crear_usuario_global(db: Session, nombre: str, email: str, password: str,
                         es_superadmin: int = 0) -> int:
    """Crea el usuario si no existe y devuelve su id. NO pisa la contraseña de
    un usuario existente: el arranque no debe revertir un cambio de clave."""
    email = (email or "").strip().lower()
    fila = q1(db, "SELECT id FROM usuarios_globales WHERE email = :e", {"e": email})
    if fila:
        return int(fila["id"])
    res = run(db,
              "INSERT INTO usuarios_globales (nombre, email, pass_hash, es_superadmin, "
              "activo, creado_en) VALUES (:n, :e, :p, :s, 1, :ts)",
              {"n": nombre, "e": email, "p": hash_password(password),
               "s": int(es_superadmin), "ts": ahora()})
    return int(getattr(res, "lastrowid", 0) or 0)


def asignar_a_sede(db: Session, usuario_id: int, tenant_id: int, rol: str) -> None:
    if rol not in seed_master.ROLES_VALIDOS:
        raise ValueError(f"Rol desconocido: {rol}")
    run(db, "INSERT INTO usuario_tenant (usuario_id, tenant_id, rol, activo) "
            "VALUES (:u, :t, :r, 1) "
            "ON DUPLICATE KEY UPDATE rol = VALUES(rol), activo = 1",
        {"u": usuario_id, "t": tenant_id, "r": rol})


# ══════════════════════════════════════════════════════════════════════
#  SEDE
# ══════════════════════════════════════════════════════════════════════
def crear_sede(nombre: str, slug: str, *, ciudad: str = "", direccion: str = "",
               nit: str = "", telefono: str = "", iva_pct: float = 8.0,
               con_datos_demo: bool = True) -> dict:
    """Registra la sede, crea su base física y la deja lista para operar."""
    db_name = nombre_db_tenant(slug)      # valida el código (lista blanca)
    mdb = get_sessionmaker(MASTER_DB)()
    try:
        fila = q1(mdb, "SELECT * FROM tenants WHERE slug = :s", {"s": slug})
        if not fila:
            run(mdb,
                "INSERT INTO tenants (nombre, slug, db_name, nit, direccion, ciudad, "
                "telefono, moneda, iva_pct, plan, activo, creado_en) "
                "VALUES (:n,:s,:d,:nit,:dir,:ciu,:tel,'COP',:iva,'basico',1,:ts)",
                {"n": nombre, "s": slug, "d": db_name, "nit": nit, "dir": direccion,
                 "ciu": ciudad, "tel": telefono, "iva": iva_pct, "ts": ahora()})
            fila = q1(mdb, "SELECT * FROM tenants WHERE slug = :s", {"s": slug})
    finally:
        mdb.close()

    aprovisionar_base_sede(db_name, con_datos_demo=con_datos_demo)
    return dict(fila)


def aprovisionar_base_sede(db_name: str, *, con_datos_demo: bool = True) -> None:
    crear_base_si_no_existe(db_name)
    db = get_sessionmaker(db_name)()
    try:
        for ddl in seed_tenant.TABLAS:
            run(db, ddl)
        _sembrar_catalogos(db)
        if con_datos_demo:
            _sembrar_operacion(db)
            _sembrar_salon(db)
            _sembrar_compras(db)
            _sembrar_sst(db)
    finally:
        db.close()


# ── Catálogos ────────────────────────────────────────────────────────────
def _sembrar_catalogos(db: Session) -> None:
    """Catálogos base. `INSERT ... ON DUPLICATE KEY UPDATE` los hace
    idempotentes sin consultar antes, y sin revivir lo que el usuario
    desactivó deliberadamente (no se toca `activo`)."""
    for nombre, color, orden in seed_tenant.CATEGORIAS:
        run(db, "INSERT INTO cat_categorias (nombre, color, orden, activo) "
                "VALUES (:n,:c,:o,1) ON DUPLICATE KEY UPDATE color=VALUES(color)",
            {"n": nombre, "c": color, "o": orden})

    for nombre, color, icono, orden in seed_tenant.ESTACIONES:
        run(db, "INSERT INTO estaciones (nombre, color, icono, orden, activo) "
                "VALUES (:n,:c,:i,:o,1) ON DUPLICATE KEY UPDATE color=VALUES(color)",
            {"n": nombre, "c": color, "i": icono, "o": orden})

    for nombre in seed_tenant.UNIDADES:
        run(db, "INSERT INTO cat_unidades (nombre, activo) VALUES (:n,1) "
                "ON DUPLICATE KEY UPDATE nombre=VALUES(nombre)", {"n": nombre})

    for nombre, cuenta, efectivo, dian in seed_tenant.METODOS_PAGO:
        run(db, "INSERT INTO cat_metodos_pago (nombre, cuenta_puc, es_efectivo, "
                "codigo_dian, activo) VALUES (:n,:c,:e,:d,1) "
                "ON DUPLICATE KEY UPDATE cuenta_puc=VALUES(cuenta_puc), "
                "codigo_dian=VALUES(codigo_dian)",
            {"n": nombre, "c": cuenta, "e": efectivo, "d": dian})

    for nombre, valor, orden in seed_tenant.COSTOS_INDIRECTOS:
        run(db, "INSERT INTO cat_costos_ind (nombre, valor_def, orden, activo) "
                "VALUES (:n,:v,:o,1) ON DUPLICATE KEY UPDATE valor_def=VALUES(valor_def)",
            {"n": nombre, "v": valor, "o": orden})

    for nombre in seed_tenant.MOTIVOS_PERDIDA:
        run(db, "INSERT INTO cat_motivos_perdida (nombre, activo) VALUES (:n,1) "
                "ON DUPLICATE KEY UPDATE nombre=VALUES(nombre)", {"n": nombre})

    for codigo, nombre, sigla, dv, orden in seed_tenant.TIPOS_DOC_ID:
        run(db, "INSERT INTO cat_tipos_doc_id (codigo, nombre, sigla, usa_dv, orden, activo) "
                "VALUES (:c,:n,:s,:d,:o,1) ON DUPLICATE KEY UPDATE nombre=VALUES(nombre)",
            {"c": codigo, "n": nombre, "s": sigla, "d": dv, "o": orden})

    for codigo, nombre, orden in seed_tenant.RESPONSABILIDADES:
        run(db, "INSERT INTO cat_responsabilidades (codigo, nombre, orden, activo) "
                "VALUES (:c,:n,:o,1) ON DUPLICATE KEY UPDATE nombre=VALUES(nombre)",
            {"c": codigo, "n": nombre, "o": orden})

    for clase, tarifa, desc in seed_tenant.ARL_TARIFAS:
        run(db, "INSERT INTO arl_tarifas (clase, tarifa, descripcion) VALUES (:c,:t,:d) "
                "ON DUPLICATE KEY UPDATE tarifa=VALUES(tarifa)",
            {"c": clase, "t": tarifa, "d": desc})

    for codigo, nombre, tipo, naturaleza in seed_tenant.PUC:
        run(db, "INSERT INTO puc (codigo, nombre, tipo, naturaleza) VALUES (:c,:n,:t,:na) "
                "ON DUPLICATE KEY UPDATE nombre=VALUES(nombre)",
            {"c": codigo, "n": nombre, "t": tipo, "na": naturaleza})

    # Configuración de facturación y perfil público: fila única (id = 1).
    f = seed_tenant.FACTURACION
    run(db, "INSERT INTO facturacion_config (id, emisor_razon, emisor_nit, emisor_email, "
            "emisor_direccion, emisor_ciudad, emisor_resp, resolucion, fecha_resolucion, "
            "prefijo, rango_desde, rango_hasta, ambiente, proveedor, actualizado_en) "
            "VALUES (1,:r,:nit,:em,:dir,:ciu,:resp,:res,:fres,:pre,:rd,:rh,:amb,:prov,:ts) "
            "ON DUPLICATE KEY UPDATE id = id",
        {"r": f["emisor_razon"], "nit": f["emisor_nit"], "em": f["emisor_email"],
         "dir": f["emisor_direccion"], "ciu": f["emisor_ciudad"], "resp": f["emisor_resp"],
         "res": f["resolucion"], "fres": f["fecha_resolucion"], "pre": f["prefijo"],
         "rd": f["rango_desde"], "rh": f["rango_hasta"], "amb": f["ambiente"],
         "prov": f["proveedor"], "ts": ahora()})

    p = seed_tenant.PERFIL_PUBLICO
    run(db, "INSERT INTO sede_perfil (id, titular, lema, descripcion, direccion, ciudad, "
            "telefono, whatsapp, email, instagram, horarios, aforo_max, publicado, "
            "acepta_reservas, actualizado_en) "
            "VALUES (1,:t,:l,:d,:dir,:ciu,:tel,:wa,:em,:ig,:hor,:af,1,1,:ts) "
            "ON DUPLICATE KEY UPDATE id = id",
        {"t": p["titular"], "l": p["lema"], "d": p["descripcion"], "dir": p["direccion"],
         "ciu": p["ciudad"], "tel": p["telefono"], "wa": p["whatsapp"], "em": p["email"],
         "ig": p["instagram"], "hor": p["horarios"], "af": p["aforo_max"], "ts": ahora()})

    _sembrar_parametros_nomina(db)


def _sembrar_parametros_nomina(db: Session) -> None:
    """Parámetros legales del año en curso.

    IMPORTANTE: el salario mínimo y el auxilio de transporte que se siembran son
    un MARCADOR DE POSICIÓN. Cambian por decreto cada diciembre y deben
    actualizarse en «Nómina → Parámetros» antes de liquidar. El sistema avisa
    mientras no se confirmen.
    """
    anio = anio_actual()
    if q1(db, "SELECT anio FROM nomina_parametros WHERE anio = :a", {"a": anio}):
        return
    run(db, "INSERT INTO nomina_parametros (anio, smmlv, auxilio_transporte, uvt, vigente) "
            "VALUES (:a, 0, 0, 0, 0)", {"a": anio})


# ── Operación: insumos, carta, producción ────────────────────────────────
def _sembrar_operacion(db: Session) -> None:
    """Insumos, productos, recetas y fichas de producción.

    El saldo inicial se registra como MOVIMIENTO de entrada, no como UPDATE al
    stock. Sin su movimiento en el kardex, el inventario nacería descuadrado y
    ninguna auditoría posterior cerraría.
    """
    if q1(db, "SELECT id FROM productos LIMIT 1"):
        return

    unidades = {r["nombre"]: r["id"] for r in q(db, "SELECT id, nombre FROM cat_unidades")}
    categorias = {r["nombre"]: r["id"] for r in q(db, "SELECT id, nombre FROM cat_categorias")}
    estaciones = {r["nombre"]: r["id"] for r in q(db, "SELECT id, nombre FROM estaciones")}
    ts = ahora()

    for codigo, nombre, unidad, stock, minimo, maximo, costo, producido in seed_tenant.INSUMOS:
        res = run(db, "INSERT INTO insumos (codigo, nombre, unidad_id, stock, stock_min, "
                      "stock_max, costo_prom, es_producido, activo, creado_en) "
                      "VALUES (:c,:n,:u,0,:mi,:ma,:co,:p,1,:ts)",
                  {"c": codigo, "n": nombre, "u": unidades.get(unidad), "mi": minimo,
                   "ma": maximo, "co": costo, "p": producido, "ts": ts})
        iid = int(getattr(res, "lastrowid", 0) or 0)
        if stock > 0:
            run(db, "INSERT INTO inv_movimientos (ts, insumo_id, tipo, cantidad, costo_unit, "
                    "saldo, ref_tipo, motivo, usuario) "
                    "VALUES (:ts,:i,'entrada',:q,:co,:q,'apertura','Saldo inicial de apertura','sistema')",
                {"ts": ts, "i": iid, "q": stock, "co": costo})
            run(db, "UPDATE insumos SET stock = :q WHERE id = :i", {"q": stock, "i": iid})

    _asiento_apertura_inventario(db)
    _sembrar_activos(db, ts)
    _sembrar_aprovechamiento(db)
    _sembrar_resenas(db, ts)
    _sembrar_plan_sst(db, ts)

    insumos = {r["codigo"]: r["id"] for r in q(db, "SELECT id, codigo FROM insumos")}
    for codigo, nombre, cat, est, precio, emoji, minutos, receta in seed_tenant.PRODUCTOS:
        res = run(db, "INSERT INTO productos (codigo, nombre, categoria_id, estacion_id, "
                      "precio, iva_pct, minutos_prep, emoji, activo, creado_en) "
                      "VALUES (:c,:n,:ca,:es,:p,8.00,:m,:e,1,:ts)",
                  {"c": codigo, "n": nombre, "ca": categorias.get(cat),
                   "es": estaciones.get(est), "p": precio, "m": minutos,
                   "e": emoji, "ts": ts})
        pid = int(getattr(res, "lastrowid", 0) or 0)
        for ins_cod, cant in receta:
            if insumos.get(ins_cod):
                run(db, "INSERT INTO receta (producto_id, insumo_id, cantidad) "
                        "VALUES (:p,:i,:q)", {"p": pid, "i": insumos[ins_cod], "q": cant})
        # Todo lo que se vende se publica por defecto en la carta web, con su
        # texto de venta si lo tiene. Un plato sin descripción igual aparece:
        # es preferible una carta completa y sobria a una carta con huecos.
        txt = _TEXTOS_CARTA.get(codigo, ("", 0, 0))
        run(db, "INSERT INTO carta_publica (producto_id, visible, destacado, descripcion, orden) "
                "VALUES (:p, 1, :d, :de, :o) ON DUPLICATE KEY UPDATE producto_id = producto_id",
            {"p": pid, "d": txt[1], "de": txt[0] or None, "o": txt[2]})
        # Costos indirectos desde la plantilla. Sembrarlos aquí evita que la
        # carta nazca con un food cost irreal: en la práctica, lo que no se
        # carga al crear el producto no se carga nunca.
        for cn, cv, co in seed_tenant.COSTOS_INDIRECTOS:
            run(db, "INSERT INTO producto_costos_ind (producto_id, concepto, valor, orden) "
                    "VALUES (:p,:c,:v,:o) ON DUPLICATE KEY UPDATE valor=VALUES(valor)",
                {"p": pid, "c": cn, "v": cv, "o": co})

    for destino, nombre, est, rendimiento, minutos, ingredientes in seed_tenant.FICHAS_PRODUCCION:
        if not insumos.get(destino):
            continue
        res = run(db, "INSERT INTO fichas_produccion (insumo_destino, nombre, estacion_id, "
                      "rendimiento, minutos, activo) VALUES (:d,:n,:e,:r,:m,1)",
                  {"d": insumos[destino], "n": nombre, "e": estaciones.get(est),
                   "r": rendimiento, "m": minutos})
        fid = int(getattr(res, "lastrowid", 0) or 0)
        for ins_cod, cant in ingredientes:
            if insumos.get(ins_cod):
                run(db, "INSERT INTO ficha_ingredientes (ficha_id, insumo_id, cantidad) "
                        "VALUES (:f,:i,:q)", {"f": fid, "i": insumos[ins_cod], "q": cant})





def _sembrar_plan_sst(db: Session, ts: str) -> None:
    """Plan de trabajo anual del año en curso.

    Las actividades del pasado quedan como ejecutadas con su evidencia; las
    futuras, planeadas. Sembrar todo como pendiente daría un cumplimiento del
    0 % que no representa a ninguna empresa en marcha.
    """
    anio = anio_actual()
    hoy_ = ahora_local().date()
    for mes, dia, tipo, nombre, resp in seed_tenant.PLAN_ANUAL:
        fecha = datetime.date(anio, mes, dia)
        paso = fecha < hoy_
        run(db, "INSERT INTO sst_actividades (tipo, nombre, responsable, fecha_plan, "
                "fecha_real, estado, evidencia, anio, creado_en) "
                "VALUES (:t,:n,:r,:f,:fr,:e,:ev,:a,:ts)",
            {"t": tipo, "n": nombre, "r": resp, "f": fecha.isoformat(),
             "fr": fecha.isoformat() if paso else None,
             "e": "ejecutada" if paso else "planeada",
             "ev": f"Acta {fecha.isoformat()} · listado de asistencia" if paso else None,
             "a": anio, "ts": ts})


def _sembrar_resenas(db: Session, ts: str) -> None:
    """Opiniones publicadas de arranque, con dos respuestas del restaurante."""
    for nombre, cal, comentario, respuesta in seed_tenant.RESENAS_DEMO:
        run(db, "INSERT INTO resenas (nombre, calificacion, comentario, estado, "
                "respuesta, respondida_por, creado_en, moderado_en) "
                "VALUES (:n,:c,:co,'publicada',:r,:rp,:ts,:ts)",
            {"n": nombre, "c": cal, "co": comentario, "r": respuesta,
             "rp": seed_tenant.PERFIL_PUBLICO["titular"] if respuesta else None,
             "ts": ts})


def _sembrar_aprovechamiento(db: Session) -> None:
    """Marca qué insumos admiten guardarse para el calentado.

    Se hace por código y no por nombre: el nombre lo puede editar cualquiera
    desde la pantalla de insumos, y el día que alguien escriba «Arroz cocido
    (olla grande)» la política sanitaria dejaría de aplicarse en silencio.
    """
    for codigo, horas in seed_tenant.APTOS_CALENTADO:
        run(db, "UPDATE insumos SET apto_calentado=1, vida_util_horas=:h WHERE codigo=:c",
            {"h": horas, "c": codigo})


def _sembrar_activos(db: Session, ts: str) -> None:
    """Maestro de maquinaria y equipo, con su asiento de apertura.

    El asiento va contra patrimonio (3115) y no contra caja: el equipo con el
    que abre el negocio es aporte de los socios, no una compra del período. Si
    entrara por caja, el flujo del primer mes mostraría una salida de ochenta
    millones que nunca ocurrió.
    """
    cats = {}
    for nombre, c_act, c_dep, c_gas, meses, tasa, orden in seed_tenant.CAT_ACTIVOS:
        res = run(db, "INSERT INTO cat_activos (nombre, cuenta_activo, cuenta_deprec, "
                      "cuenta_gasto, vida_util_meses, tasa_anual, orden) "
                      "VALUES (:n,:a,:d,:g,:m,:t,:o)",
                  {"n": nombre, "a": c_act, "d": c_dep, "g": c_gas,
                   "m": meses, "t": tasa, "o": orden})
        cats[nombre] = int(getattr(res, "lastrowid", 0) or 0)

    # Cierre del mes anterior: hasta ahí llega la depreciación de apertura.
    hoy_ = ahora_local().date()
    corte = (f"{hoy_.year - 1}-12" if hoy_.month == 1
             else f"{hoy_.year}-{hoy_.month - 1:02d}")

    ids, por_cuenta = {}, {}
    acum_total = 0.0
    for (cod, nom, cat, marca, modelo, fecha, valor, residual,
         ubic, resp, prov) in seed_tenant.ACTIVOS:
        cid = cats.get(cat)
        if not cid:
            continue
        meses = dict((c[0], c[4]) for c in seed_tenant.CAT_ACTIVOS)[cat]
        cuenta = dict((c[0], c[1]) for c in seed_tenant.CAT_ACTIVOS)[cat]

        # Depreciación ya corrida entre la compra y el corte de apertura.
        base = max(float(valor) - float(residual), 0.0)
        cuota = round(base / max(meses, 1), 2)
        corridos = max((int(corte[:4]) - int(fecha[:4])) * 12
                       + (int(corte[5:7]) - int(fecha[5:7])), 0)
        acum = round(min(cuota * corridos, base), 2)

        res = run(db, "INSERT INTO activos (codigo, nombre, categoria_id, marca, modelo, "
                      "fecha_compra, valor_compra, valor_residual, vida_util_meses, "
                      "deprec_acum, ultimo_periodo, ubicacion, responsable, proveedor, "
                      "estado, creado_en) "
                      "VALUES (:c,:n,:ca,:ma,:mo,:f,:v,:r,:vu,:ac,:up,:ub,:re,:pr,"
                      "'activo',:ts)",
                  {"c": cod, "n": nom, "ca": cid, "ma": marca, "mo": modelo, "f": fecha,
                   "v": valor, "r": residual, "vu": meses, "ac": acum,
                   "up": corte if acum > 0 else None,
                   "ub": ubic, "re": resp, "pr": prov, "ts": ts})
        ids[cod] = int(getattr(res, "lastrowid", 0) or 0)
        por_cuenta[cuenta] = round(por_cuenta.get(cuenta, 0.0) + float(valor), 2)
        acum_total = round(acum_total + acum, 2)

    for cod, fecha, tipo, desc, costo, prov, proximo in seed_tenant.MANTENIMIENTOS:
        aid = ids.get(cod)
        if not aid:
            continue
        run(db, "INSERT INTO activo_mantenimientos (activo_id, fecha, tipo, descripcion, "
                "costo, proveedor, proximo, responsable, creado_en) "
                "VALUES (:a,:f,:t,:d,:c,:p,:px,'Administrador',:ts)",
            {"a": aid, "f": fecha, "t": tipo, "d": desc, "c": costo, "p": prov,
             "px": proximo, "ts": ts})

    if por_cuenta:
        from contabilidad_router import _registrar_asiento
        lineas = [{"cuenta": cta, "debito": val, "credito": 0}
                  for cta, val in sorted(por_cuenta.items())]
        total = round(sum(por_cuenta.values()), 2)
        if acum_total > 0:
            lineas.append({"cuenta": "1592", "debito": 0, "credito": acum_total})
        lineas.append({"cuenta": "3115", "debito": 0,
                       "credito": round(total - acum_total, 2)})
        _registrar_asiento(db, tipo="apertura_ppe",
                           concepto=(f"Apertura · maquinaria y equipo aportado "
                                     f"(neto de depreciación al {corte})"),
                           lineas=lineas, ref_tipo="apertura", ref_id=0,
                           usuario="sistema")


def _asiento_apertura_inventario(db: Session) -> None:
    """Contabiliza el inventario inicial.

    DEFECTO QUE CORRIGE: al sembrar los insumos se registraban sus entradas en el
    kardex pero NO su asiento. La cuenta 1435 nacía en cero mientras el
    inventario físico ya valía millones, y al primer costo de ventas el saldo
    contable se volvía NEGATIVO —un imposible que invalida el balance—.

    El tratamiento correcto de existencias aportadas al constituir el negocio es
    cargarlas al inventario contra el patrimonio: es un aporte en especie.
    """
    from contabilidad_router import CTA_INVENTARIO, _registrar_asiento

    fila = q1(db, "SELECT COALESCE(SUM(stock * costo_prom), 0) AS valor FROM insumos")
    valor = round(float((fila or {}).get("valor") or 0), 2)
    if valor <= 0:
        return
    _registrar_asiento(db, tipo="apertura",
                       concepto="Inventario inicial aportado a la apertura de la sede",
                       lineas=[{"cuenta": CTA_INVENTARIO, "debito": valor, "credito": 0},
                               {"cuenta": "3115", "debito": 0, "credito": valor}],
                       ref_tipo="apertura", usuario="sistema")
    db.commit()


def _sembrar_salon(db: Session) -> None:
    if q1(db, "SELECT id FROM mesas LIMIT 1"):
        return
    for nombre, color, orden in seed_tenant.ZONAS:
        run(db, "INSERT INTO zonas (nombre, color, orden, activo) VALUES (:n,:c,:o,1) "
                "ON DUPLICATE KEY UPDATE color=VALUES(color)",
            {"n": nombre, "c": color, "o": orden})
    zonas = {r["nombre"]: r["id"] for r in q(db, "SELECT id, nombre FROM zonas")}
    for codigo, zona, capacidad in seed_tenant.MESAS:
        run(db, "INSERT INTO mesas (zona_id, codigo, capacidad, estado, activo) "
                "VALUES (:z,:c,:cap,'libre',1) ON DUPLICATE KEY UPDATE capacidad=VALUES(capacidad)",
            {"z": zonas.get(zona), "c": codigo, "cap": capacidad})


def _sembrar_compras(db: Session) -> None:
    if q1(db, "SELECT id FROM proveedores LIMIT 1"):
        return
    from facturacion_router import calcular_dv

    ids = []
    for nit, razon, contacto, email, tel, dias, condicion in seed_tenant.PROVEEDORES:
        try:
            dv = str(calcular_dv(nit))
        except Exception:
            dv = None
        res = run(db, "INSERT INTO proveedores (nit, dv, razon_social, contacto, email, "
                      "telefono, dias_entrega, condicion_pago, activo, creado_en) "
                      "VALUES (:nit,:dv,:r,:c,:e,:t,:d,:cp,1,:ts)",
                  {"nit": nit, "dv": dv, "r": razon, "c": contacto, "e": email,
                   "t": tel, "d": dias, "cp": condicion, "ts": ahora()})
        ids.append(int(getattr(res, "lastrowid", 0) or 0))

    # Reparto de insumos entre proveedores para que la reposición automática
    # tenga a quién comprarle desde el primer día.
    insumos = q(db, "SELECT id, costo_prom FROM insumos WHERE es_producido = 0 ORDER BY id")
    for i, ins in enumerate(insumos):
        run(db, "INSERT INTO insumo_proveedor (insumo_id, proveedor_id, precio, "
                "cantidad_min, preferido) VALUES (:i,:p,:pr,1,1) "
                "ON DUPLICATE KEY UPDATE precio=VALUES(precio)",
            {"i": ins["id"], "p": ids[i % len(ids)], "pr": float(ins["costo_prom"] or 0)})


def _sembrar_sst(db: Session) -> None:
    if q1(db, "SELECT id FROM sst_peligros LIMIT 1"):
        return
    from sgsst_router import calcular_nivel_riesgo

    for (proc, act, clas, pel, efe, nd, ne, nc, ctrl, epp, resp) in seed_tenant.SST_PELIGROS:
        nr, interp, acept = calcular_nivel_riesgo(nd, ne, nc)
        run(db, "INSERT INTO sst_peligros (proceso, actividad, clasificacion, peligro, "
                "efecto, nivel_deficiencia, nivel_exposicion, nivel_consecuencia, "
                "nivel_riesgo, interpretacion, aceptabilidad, controles, epp, responsable, "
                "activo, actualizado_en) "
                "VALUES (:p,:a,:c,:pe,:e,:nd,:ne,:nc,:nr,:i,:ac,:ct,:epp,:r,1,:ts)",
            {"p": proc, "a": act, "c": clas, "pe": pel, "e": efe, "nd": nd, "ne": ne,
             "nc": nc, "nr": nr, "i": interp, "ac": acept, "ct": ctrl, "epp": epp,
             "r": resp, "ts": ahora()})

    for ciclo, item, desc, peso in seed_tenant.SST_ESTANDARES:
        run(db, "INSERT INTO sst_estandares (ciclo, item, descripcion, peso, cumple) "
                "VALUES (:c,:i,:d,:p,0) ON DUPLICATE KEY UPDATE descripcion=VALUES(descripcion)",
            {"c": ciclo, "i": item, "d": desc, "p": peso})


# ── Espejo de usuarios ───────────────────────────────────────────────────
def sincronizar_usuarios_sede(tenant_id: int, db_name: str) -> None:
    """Copia a la base de la sede los usuarios que acceden a ella.

    El espejo local evita que cada consulta que necesita un nombre cruce dos
    bases. El costo es mantenerlo sincronizado; se hace al aprovisionar y al
    modificar accesos.
    """
    mdb = get_sessionmaker(MASTER_DB)()
    try:
        filas = q(mdb, "SELECT u.id, u.nombre, u.email, ut.rol, ut.activo "
                       "FROM usuario_tenant ut JOIN usuarios_globales u ON u.id = ut.usuario_id "
                       "WHERE ut.tenant_id = :t", {"t": tenant_id})
    finally:
        mdb.close()

    tdb = get_sessionmaker(db_name)()
    try:
        for f in filas:
            run(tdb, "INSERT INTO usuarios (id, nombre, email, rol, activo) "
                     "VALUES (:i,:n,:e,:r,:a) ON DUPLICATE KEY UPDATE "
                     "nombre=VALUES(nombre), email=VALUES(email), rol=VALUES(rol), "
                     "activo=VALUES(activo)",
                {"i": f["id"], "n": f["nombre"], "e": f["email"],
                 "r": f["rol"], "a": f["activo"]})
    finally:
        tdb.close()


# ══════════════════════════════════════════════════════════════════════
#  ARRANQUE
# ══════════════════════════════════════════════════════════════════════
DEMO = [
    # (nombre, email, contraseña, rol, superadmin, cargo, salario base)
    ("Gerencia",           "manager@qmspm.com",     "Manager123*",  "admin",   1,
     "Gerente general",        4500000),
    ("Contabilidad",       "contador@luispardo.co", "Contador123*", "gerente", 0,
     "Contador",               3200000),
    ("Control de Calidad", "calidad@luispardo.co",  "Calidad123*",  "sst",     0,
     "Responsable SG-SST",     2800000),
    ("Caja Mostrador",     "cajero@qmspm.com",      "Cajero123*",   "cajero",  0,
     "Cajero",                 1600000),
    ("Salón",              "mesero@qmspm.com",      "Mesero123*",   "mesero",  0,
     "Mesero",                 1400000),
    ("Cocina",             "cocina@qmspm.com",      "Cocina123*",   "cocina",  0,
     "Cocinero",               1900000),
    ("Almacén",            "bodega@qmspm.com",      "Bodega123*",   "bodega",  0,
     "Auxiliar de almacén",    1500000),
]


def _sembrar_empleados(db_name: str) -> None:
    """Crea la ficha laboral de los usuarios de demostración.

    Usuario y empleado son cosas distintas: el usuario entra al sistema, el
    empleado tiene contrato, EPS y salario. Un cocinero puede no tener usuario, y
    el contador externo puede tener usuario sin ser empleado.
    """
    db = get_sessionmaker(db_name)()
    try:
        if q1(db, "SELECT id FROM empleados LIMIT 1"):
            return
        estaciones = {r["nombre"]: r["id"] for r in q(db, "SELECT id, nombre FROM estaciones")}
        mapa_est = {"Cocinero": "Cocina caliente", "Mesero": None}
        riesgo = {"Cocinero": "III", "Auxiliar de almacén": "III", "Mesero": "II"}
        puntos = {"Mesero": 2.0, "Cocinero": 1.5, "Cajero": 1.0}

        for i, (nombre, email, _pw, _rol, _sa, cargo, salario) in enumerate(DEMO, start=1):
            run(db, "INSERT INTO empleados (numero_doc, nombres, apellidos, cargo, "
                    "estacion_id, tipo_contrato, fecha_ingreso, salario_base, "
                    "aplica_auxilio, eps, afp, arl, clase_riesgo, caja_compensacion, "
                    "puntos_propina, email, activo, creado_en) "
                    "VALUES (:doc,:n,:ap,:c,:e,'Término indefinido',:fi,:s,:aux,"
                    "'EPS Sura','Porvenir','ARL Sura',:r,'Compensar',:pt,:em,1,:ts) "
                    "ON DUPLICATE KEY UPDATE numero_doc = numero_doc",
                {"doc": f"10000000{i}", "n": nombre, "ap": "Demo",
                 "c": cargo, "e": estaciones.get(mapa_est.get(cargo) or ""),
                 "fi": "2026-01-15", "s": salario,
                 "aux": 1 if salario < 3000000 else 0,
                 "r": riesgo.get(cargo, "II"), "pt": puntos.get(cargo, 1.0),
                 "em": email, "ts": ahora()})
    finally:
        db.close()


def bootstrap() -> dict:
    """Deja el sistema listo para usarse: maestra, sede demo, usuarios y fichas."""
    crear_maestra()
    sede = crear_sede("Restaurante Central", "central",
                      ciudad="Bogotá D.C.", direccion="Calle 100 # 15-20",
                      nit="901.234.567-8", telefono="601 555 0100")

    mdb = get_sessionmaker(MASTER_DB)()
    try:
        for nombre, email, password, rol, sa, _cargo, _sal in DEMO:
            uid = crear_usuario_global(mdb, nombre, email, password, sa)
            asignar_a_sede(mdb, uid, int(sede["id"]), rol)
    finally:
        mdb.close()

    sincronizar_usuarios_sede(int(sede["id"]), sede["db_name"])
    _sembrar_empleados(sede["db_name"])
    log.info("Aprovisionamiento completo · sede=%s db=%s", sede["nombre"], sede["db_name"])
    return dict(sede)


if __name__ == "__main__":   # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    s = bootstrap()
    print("Sede lista:", s["nombre"], "->", s["db_name"])
    for nombre, email, password, rol, _sa, cargo, _sal in DEMO:
        print(f"  {rol:<9} {email:<26} {password:<14} {cargo}")
