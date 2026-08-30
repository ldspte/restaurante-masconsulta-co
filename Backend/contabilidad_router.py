# -*- coding: utf-8 -*-
"""
================================================================
  RESTAURANTE · Módulo CONTABILIDAD
================================================================
Partida doble automática. Ningún usuario digita asientos: cada hecho económico
llega por el bus de eventos y una FÁBRICA lo traduce a su asiento.

PATRÓN FÁBRICA (Factory Method)
-------------------------------
`_FABRICAS` mapea tipo de evento → función que construye las líneas del
asiento. Agregar un hecho contabilizable nuevo —una propina, una devolución a
proveedor— es escribir una función y registrarla en ese diccionario. No se toca
ninguna de las existentes ni el código que las despacha.

INVARIANTE INNEGOCIABLE
-----------------------
Todo asiento debe cuadrar: Σ débitos = Σ créditos. Se verifica ANTES de
grabar, en `_registrar_asiento`. Un asiento descuadrado no se corrige después:
se rechaza, y como el bus corre dentro de la transacción del publicador, la
operación de negocio completa se revierte. Es preferible una venta que falla a
una contabilidad que miente.

Rutas
  GET /api/contabilidad/puc
  GET /api/contabilidad/asientos
  GET /api/contabilidad/asientos/{id}
  GET /api/contabilidad/libro-diario
  GET /api/contabilidad/balance-prueba
  GET /api/contabilidad/estado-resultados

Autor: Arquitectura de Software · Unidad 1
================================================================
"""
from __future__ import annotations

import datetime
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db import anio_actual, ahora, q, q1, run_sin_commit, serial, siguiente_consecutivo
from dependencias import get_tenant_db
from eventos import Evento, TipoEvento, suscribir
from seguridad import require_rol, verify_token

log = logging.getLogger("cafeteria.contabilidad")
router = APIRouter(tags=["Contabilidad"])

# Cuentas usadas por las fábricas. Centralizadas para que un cambio de plan de
# cuentas no obligue a buscar códigos sueltos por todo el módulo.
CTA_CAJA = "1105"
CTA_BANCOS = "1110"
CTA_INVENTARIO = "1435"
CTA_PROVEEDORES = "2205"
# El servicio de restaurante en Colombia NO causa IVA: causa IMPUESTO NACIONAL
# AL CONSUMO al 8 % (art. 512-1 y 512-9 E.T.). Son dos tributos distintos y se
# declaran en formularios distintos —el 310, no el 300—, y el INC **no es
# descontable**: para quien lo paga es costo, no un saldo a favor.
#
# Acreditarlo en la 2408 mezclaba el INC con el IVA y habría producido una
# declaración de IVA inflada con plata que nunca fue IVA. Por eso tiene cuenta
# propia. La 2408 se conserva para el caso que sí genera IVA: los restaurantes
# que operan bajo contrato de franquicia (par. art. 512-1).
CTA_IVA = "2408"                    # solo franquicias
CTA_INC = "2413"                    # impuesto nacional al consumo, 8 %
CTA_INGRESOS = "4135"
CTA_COSTO_VENTAS = "6135"
# Propiedad, planta y equipo
CTA_PPE_MAQUINARIA = "1520"
CTA_DEPREC_ACUM = "1592"
CTA_DEPRECIACION = "5160"
CTA_MANTENIMIENTO = "5145"
CTA_PERDIDA_RETIRO = "5310"
CTA_PROVEEDORES = "2205"
CTA_MERMAS = "5195"
CTA_DEVOLUCIONES = "5305"
CTA_PROPINAS = "2335"          # pasivo: dinero del personal en poder de la empresa
CTA_ALIMENTACION = "5165"      # beneficio laboral, no merma ni costo de ventas
CTA_MO_POR_PAGAR = "2380"
# El neto de la nómina tiene cuenta PROPIA y no comparte la 2380. Son dos
# pasivos que se pagan a personas distintas en momentos distintos: la 2380 es
# la mano de obra imputada a una orden de producción; la 2505 es lo que se le
# consigna al empleado el día 30. Mezclarlos hace ilegible el saldo de ambas.
CTA_SALARIOS_POR_PAGAR = "2505"      # obligacion con el personal por la mano de obra aplicada
CTA_SALARIOS = "5105"
CTA_PRESTACIONES = "5110"
CTA_SEG_SOCIAL = "5115"
CTA_PARAFISCALES = "5120"
CTA_RETENCIONES_NOM = "2370"   # lo retenido al trabajador, pendiente de girar
CTA_CESANTIAS = "2510"
CTA_INT_CESANTIAS = "2515"
CTA_PRIMA = "2525"
CTA_VACACIONES = "2530"

TOLERANCIA = 0.01   # un centavo, por redondeos de IVA en pagos mixtos


# ══════════════════════════════════════════════════════════════════════
#  MOTOR DE ASIENTOS
# ══════════════════════════════════════════════════════════════════════
def _nombre_cuenta(db: Session, codigo: str) -> str:
    fila = q1(db, "SELECT nombre FROM puc WHERE codigo = :c", {"c": codigo})
    return (fila or {}).get("nombre") or codigo


def _registrar_asiento(db: Session, *, tipo: str, concepto: str, lineas: list[dict],
                       ref_tipo: str = "", ref_id: int | None = None,
                       usuario: str = "sistema") -> int:
    """Graba un asiento validando la partida doble. NO hace commit.

    `lineas`: [{"cuenta": "1105", "debito": 1000, "credito": 0}, ...]
    """
    limpias = [ln for ln in lineas
               if round(float(ln.get("debito") or 0), 2) > 0
               or round(float(ln.get("credito") or 0), 2) > 0]
    if not limpias:
        raise ValueError(f"El asiento «{tipo}» no tiene líneas con valor")

    debitos = round(sum(float(ln.get("debito") or 0) for ln in limpias), 2)
    creditos = round(sum(float(ln.get("credito") or 0) for ln in limpias), 2)

    if abs(debitos - creditos) > TOLERANCIA:
        raise ValueError(
            f"Asiento «{tipo}» descuadrado: débitos {debitos:,.2f} ≠ "
            f"créditos {creditos:,.2f} (diferencia {debitos - creditos:,.2f})")

    anio = anio_actual()
    numero = f"AS-{anio}-{siguiente_consecutivo(db, 'asiento', anio):05d}"

    res = run_sin_commit(db,
                         "INSERT INTO asientos (numero, ts, tipo, concepto, ref_tipo, "
                         "ref_id, usuario) VALUES (:n,:ts,:tp,:c,:rt,:ri,:u)",
                         {"n": numero, "ts": ahora(), "tp": tipo, "c": concepto[:240],
                          "rt": ref_tipo or None, "ri": ref_id, "u": usuario})
    asiento_id = int(res.lastrowid or 0)

    for ln in limpias:
        cuenta = str(ln["cuenta"])
        run_sin_commit(db,
                       "INSERT INTO asiento_lineas (asiento_id, cuenta, nombre, debito, credito) "
                       "VALUES (:a,:c,:n,:d,:cr)",
                       {"a": asiento_id, "c": cuenta, "n": _nombre_cuenta(db, cuenta),
                        "d": round(float(ln.get("debito") or 0), 2),
                        "cr": round(float(ln.get("credito") or 0), 2)})

    log.info("Asiento %s (%s) por %.2f", numero, tipo, debitos)
    return asiento_id


# ══════════════════════════════════════════════════════════════════════
#  FÁBRICAS: evento → líneas del asiento
# ══════════════════════════════════════════════════════════════════════
def _asiento_venta(db: Session, evento: Evento) -> None:
    """Venta. Son DOS hechos económicos y por eso dos asientos separados:

      1. El ingreso   → entra dinero, se causa el IVA y se reconoce la venta.
      2. El costo     → sale inventario y se reconoce el costo de lo vendido.

    Mezclarlos en un solo asiento funcionaría aritméticamente, pero impediría
    leer el libro diario y entender qué pasó. La separación es la práctica
    contable estándar.
    """
    p = evento.payload
    folio = p.get("folio", "")

    # ── Asiento 1: ingreso ──
    lineas = []
    for pago in p.get("pagos", []):
        # Cada método de pago entra por su propia cuenta: el efectivo a caja,
        # las tarjetas a bancos. Así el saldo de caja del libro corresponde con
        # lo que realmente debe haber en el cajón al cierre.
        lineas.append({"cuenta": pago.get("cuenta_puc") or CTA_CAJA,
                       "debito": pago["monto"], "credito": 0})
    lineas.append({"cuenta": CTA_INGRESOS, "debito": 0, "credito": p["subtotal"]})
    if round(float(p.get("impuestos") or 0), 2) > 0:
        lineas.append({"cuenta": CTA_INC, "debito": 0, "credito": p["impuestos"]})

    # La propina entró con el pago pero NO es ingreso de la empresa: es un
    # pasivo con el personal hasta que se reparte. Acreditarla a ingresos haría
    # tributar renta e IVA sobre plata ajena.
    propina = round(float(p.get("propina") or 0), 2)
    if propina > 0:
        lineas.append({"cuenta": CTA_PROPINAS, "debito": 0, "credito": propina})

    _registrar_asiento(db, tipo="venta", concepto=f"Venta {folio}", lineas=lineas,
                       ref_tipo="venta", ref_id=evento.entidad_id, usuario=evento.usuario)

    # ── Asiento 2: costo de ventas ──
    costo = round(float(p.get("costo") or 0), 2)
    if costo > 0:
        _registrar_asiento(
            db, tipo="costo_venta", concepto=f"Costo de ventas {folio}",
            lineas=[{"cuenta": CTA_COSTO_VENTAS, "debito": costo, "credito": 0},
                    {"cuenta": CTA_INVENTARIO, "debito": 0, "credito": costo}],
            ref_tipo="venta", ref_id=evento.entidad_id, usuario=evento.usuario)


def _asiento_anulacion(db: Session, evento: Evento) -> None:
    """Anulación: reversa de ingreso y de costo.

    Se registra un asiento NUEVO en sentido contrario, no se borra el original.
    Eliminar asientos destruye la trazabilidad y es inadmisible en contabilidad:
    el libro debe mostrar que hubo una venta y que fue anulada, no fingir que
    nunca existió.
    """
    p = evento.payload
    folio = p.get("folio", "")
    subtotal = round(float(p.get("subtotal") or 0), 2)
    impuestos = round(float(p.get("impuestos") or 0), 2)
    total = round(float(p.get("total") or 0), 2)

    lineas = [{"cuenta": CTA_DEVOLUCIONES, "debito": subtotal, "credito": 0}]
    if impuestos > 0:
        lineas.append({"cuenta": CTA_INC, "debito": impuestos, "credito": 0})
    lineas.append({"cuenta": CTA_CAJA, "debito": 0, "credito": total})

    _registrar_asiento(db, tipo="anulacion",
                       concepto=f"Anulación de {folio} · {p.get('motivo', '')}",
                       lineas=lineas, ref_tipo="venta", ref_id=evento.entidad_id,
                       usuario=evento.usuario)

    costo = round(float(p.get("costo") or 0), 2)
    if costo > 0:
        _registrar_asiento(
            db, tipo="reversa_costo", concepto=f"Reversa costo {folio}",
            lineas=[{"cuenta": CTA_INVENTARIO, "debito": costo, "credito": 0},
                    {"cuenta": CTA_COSTO_VENTAS, "debito": 0, "credito": costo}],
            ref_tipo="venta", ref_id=evento.entidad_id, usuario=evento.usuario)


def _asiento_perdida(db: Session, evento: Evento) -> None:
    """Merma: el inventario disminuye contra un gasto, no contra el costo de
    ventas. Cargarla al costo de ventas inflaría artificialmente el costo del
    producto vendido y escondería la merma dentro del margen."""
    p = evento.payload
    costo = round(float(p.get("costo_total") or 0), 2)
    if costo <= 0:
        return
    _registrar_asiento(
        db, tipo="perdida",
        concepto=f"Pérdida de {p.get('insumo', '')} · {p.get('motivo', '')}",
        lineas=[{"cuenta": CTA_MERMAS, "debito": costo, "credito": 0},
                {"cuenta": CTA_INVENTARIO, "debito": 0, "credito": costo}],
        ref_tipo="perdida", ref_id=evento.entidad_id, usuario=evento.usuario)


def _asiento_compra(db: Session, evento: Evento) -> None:
    """Entrada de inventario. Contra caja si fue de contado, contra proveedores
    si quedó a crédito."""
    p = evento.payload
    costo = round(float(p.get("costo_total") or 0), 2)
    if costo <= 0:
        return
    contrapartida = CTA_CAJA if p.get("contado") else CTA_PROVEEDORES
    _registrar_asiento(
        db, tipo="compra",
        concepto=f"Compra de {p.get('insumo', '')}",
        lineas=[{"cuenta": CTA_INVENTARIO, "debito": costo, "credito": 0},
                {"cuenta": contrapartida, "debito": 0, "credito": costo}],
        ref_tipo="compra", ref_id=evento.entidad_id, usuario=evento.usuario)


def _asiento_consumo_interno(db: Session, evento: Evento) -> None:
    """Desayuno del personal: sale inventario contra un GASTO DE PERSONAL.

    No va a costo de ventas —no hubo venta— ni a mermas —no fue desperdicio—.
    Tiene cuenta propia (5165) para que el dueño pueda ver cuánto cuesta
    realmente alimentar al equipo, que es una decisión de gestión.
    """
    p = evento.payload
    costo = round(float(p.get("costo_total") or 0), 2)
    if costo <= 0:
        return
    _registrar_asiento(
        db, tipo="consumo_interno",
        concepto=f"Consumo interno · {p.get('beneficiario', '')} · {p.get('producto', '')}",
        lineas=[{"cuenta": CTA_ALIMENTACION, "debito": costo, "credito": 0},
                {"cuenta": CTA_INVENTARIO, "debito": 0, "credito": costo}],
        ref_tipo="consumo", ref_id=evento.entidad_id, usuario=evento.usuario)


def _asiento_reparto_propinas(db: Session, evento: Evento) -> None:
    """Pago de propinas: cancela el PASIVO contra la caja.

    El ingreso nunca existió: la propina entró como pasivo al cobrarse (ver
    `_asiento_venta`) y aquí simplemente se le entrega a quien siempre fue suya.
    """
    p = evento.payload
    total = round(float(p.get("total") or 0), 2)
    if total <= 0:
        return
    _registrar_asiento(
        db, tipo="reparto_propinas",
        concepto=f"Reparto de propinas {p.get('numero', '')}",
        lineas=[{"cuenta": CTA_PROPINAS, "debito": total, "credito": 0},
                {"cuenta": CTA_CAJA, "debito": 0, "credito": total}],
        ref_tipo="reparto", ref_id=evento.entidad_id, usuario=evento.usuario)


def _asiento_produccion(db: Session, evento: Evento) -> None:
    """Producción propia: la mano de obra se incorpora al inventario.

    Los insumos ya se movieron de cuenta a cuenta dentro del mismo inventario
    (salieron harina y levadura, entró pan), así que ese traslado no genera
    asiento. Lo que sí lo genera es la MANO DE OBRA: agrega valor al producto
    y por eso capitaliza contra el inventario en lugar de irse como gasto.

    DEFECTO QUE CORRIGE: la contrapartida era una cuenta de COSTO acreditada,
    lo que la dejaba con saldo NEGATIVO y restaba del costo total. En la corrida
    de prueba la utilidad salió en 81.420 sobre ingresos de 67.500 —más ganancia
    que venta—, un imposible que delataba el error.

    La contrapartida correcta es un PASIVO: el trabajo del panadero ya se hizo y
    todavía no se ha pagado, así que es una obligación con el personal. Cuando
    la nómina se liquide, debitará esta misma cuenta y la cancelará.
    """
    p = evento.payload
    costo_mo = round(float(p.get("costo_mo") or 0), 2)
    if costo_mo <= 0:
        return
    _registrar_asiento(
        db, tipo="produccion",
        concepto=f"Mano de obra de producción · {p.get('producto', '')}",
        lineas=[{"cuenta": CTA_INVENTARIO, "debito": costo_mo, "credito": 0},
                {"cuenta": CTA_MO_POR_PAGAR, "debito": 0, "credito": costo_mo}],
        ref_tipo="produccion", ref_id=evento.entidad_id, usuario=evento.usuario)


def _asiento_nomina(db: Session, evento: Evento) -> None:
    """Cierre de nómina. Son TRES asientos porque son tres hechos distintos, y
    mezclarlos impediría leer el libro y responder «¿cuánto costó la nómina?».

      1· Devengado    gasto de salarios contra lo retenido y lo neto por pagar
      2· Aportes      seguridad social y parafiscales a cargo del EMPLEADOR
      3· Prestaciones provisión de cesantías, intereses, prima y vacaciones

    La distinción clave es la del asiento 2: esos aportes NO se le descuentan al
    trabajador, son costo adicional de la empresa. Contabilizarlos junto al
    salario haría creer que un empleado de un millón cuesta un millón.
    """
    p = evento.payload
    devengado = round(float(p.get("devengado") or 0), 2)
    deducido = round(float(p.get("deducido") or 0), 2)
    neto = round(float(p.get("neto") or 0), 2)
    aportes = round(float(p.get("aportes") or 0), 2)
    prestaciones = round(float(p.get("prestaciones") or 0), 2)
    numero = p.get("numero", "")

    if devengado > 0:
        _registrar_asiento(
            db, tipo="nomina", concepto=f"Nómina {numero} · devengado",
            lineas=[{"cuenta": CTA_SALARIOS, "debito": devengado, "credito": 0},
                    {"cuenta": CTA_RETENCIONES_NOM, "debito": 0, "credito": deducido},
                    {"cuenta": CTA_SALARIOS_POR_PAGAR, "debito": 0, "credito": neto}],
            ref_tipo="nomina", ref_id=evento.entidad_id, usuario=evento.usuario)

    if aportes > 0:
        # Se separan seguridad social y parafiscales porque se pagan a entidades
        # distintas y se concilian por separado en la planilla.
        seg = round(aportes * 0.75, 2)
        para = round(aportes - seg, 2)
        _registrar_asiento(
            db, tipo="nomina_aportes", concepto=f"Nómina {numero} · aportes del empleador",
            lineas=[{"cuenta": CTA_SEG_SOCIAL, "debito": seg, "credito": 0},
                    {"cuenta": CTA_PARAFISCALES, "debito": para, "credito": 0},
                    {"cuenta": CTA_RETENCIONES_NOM, "debito": 0, "credito": aportes}],
            ref_tipo="nomina", ref_id=evento.entidad_id, usuario=evento.usuario)

    if prestaciones > 0:
        # Provisión: el gasto se causa mes a mes aunque el pago sea anual. No
        # provisionar produce el problema clásico de diciembre, cuando la prima
        # aparece completa en un solo mes y descuadra el resultado.
        det = p.get("detalle_prestaciones") or {}
        ces = round(float(det.get("cesantias") or prestaciones * 0.45), 2)
        ic = round(float(det.get("int_cesantias") or prestaciones * 0.05), 2)
        pri = round(float(det.get("prima") or prestaciones * 0.30), 2)
        vac = round(prestaciones - ces - ic - pri, 2)
        _registrar_asiento(
            db, tipo="nomina_prestaciones",
            concepto=f"Nómina {numero} · provisión de prestaciones",
            lineas=[{"cuenta": CTA_PRESTACIONES, "debito": prestaciones, "credito": 0},
                    {"cuenta": CTA_CESANTIAS, "debito": 0, "credito": ces},
                    {"cuenta": CTA_INT_CESANTIAS, "debito": 0, "credito": ic},
                    {"cuenta": CTA_PRIMA, "debito": 0, "credito": pri},
                    {"cuenta": CTA_VACACIONES, "debito": 0, "credito": vac}],
            ref_tipo="nomina", ref_id=evento.entidad_id, usuario=evento.usuario)


# Registro de la fábrica. Este diccionario ES el punto de extensión del módulo:
# contabilizar un hecho nuevo es escribir su función y añadirla aquí.
# ══════════════════════════════════════════════════════════════════════
#  PROPIEDAD, PLANTA Y EQUIPO
# ══════════════════════════════════════════════════════════════════════
def _asiento_compra_activo(db: Session, evento: Evento) -> None:
    """Compra de equipo: entra al activo, no al gasto.

    Es la distinción que más plata mueve en el estado de resultados de un
    negocio pequeño. Un horno de dieciocho millones cargado al gasto arruina
    el mes en que se compró y regala los diez años siguientes; llevado al
    activo, reparte su costo en los meses en que efectivamente trabaja.
    """
    p = evento.payload
    valor = round(float(p.get("valor") or 0), 2)
    if valor <= 0:
        return
    contra = CTA_PROVEEDORES if str(p.get("credito", "")).lower() == "credito" else CTA_CAJA
    _registrar_asiento(
        db, tipo="compra_activo",
        concepto=f"Compra de equipo · {p.get('codigo', '')} {p.get('nombre', '')}",
        lineas=[{"cuenta": p.get("cuenta_activo") or CTA_PPE_MAQUINARIA,
                 "debito": valor, "credito": 0},
                {"cuenta": contra, "debito": 0, "credito": valor}],
        ref_tipo="activo", ref_id=evento.entidad_id, usuario=evento.usuario)


def _asiento_depreciacion(db: Session, evento: Evento) -> None:
    """Depreciación del mes, agrupada por par de cuentas.

    Se agrupa en vez de escribir un renglón por activo: un asiento con
    diecisiete líneas idénticas salvo el importe no informa más que uno con
    dos, y el detalle por activo ya vive en `deprec_detalle`.
    """
    p = evento.payload
    total = round(float(p.get("total") or 0), 2)
    if total <= 0:
        return

    grupos: dict[tuple, float] = {}
    for d in p.get("detalle") or []:
        clave = (d.get("cuenta_gasto") or CTA_DEPRECIACION,
                 d.get("cuenta_deprec") or CTA_DEPREC_ACUM)
        grupos[clave] = round(grupos.get(clave, 0.0) + float(d.get("cuota") or 0), 2)

    lineas = []
    for (gasto, acum), monto in sorted(grupos.items()):
        lineas.append({"cuenta": gasto, "debito": monto, "credito": 0})
        lineas.append({"cuenta": acum, "debito": 0, "credito": monto})
    if not lineas:
        lineas = [{"cuenta": CTA_DEPRECIACION, "debito": total, "credito": 0},
                  {"cuenta": CTA_DEPREC_ACUM, "debito": 0, "credito": total}]

    _registrar_asiento(
        db, tipo="depreciacion",
        concepto=f"Depreciación de {p.get('periodo', '')} · {p.get('activos', 0)} activos",
        lineas=lineas, ref_tipo="deprec_periodo", ref_id=evento.entidad_id,
        usuario=evento.usuario)


def _asiento_baja_activo(db: Session, evento: Evento) -> None:
    """Retiro de un activo: se cancelan costo y depreciación acumulada.

    El saldo sin depreciar es pérdida del período, salvo que la venta lo
    cubra. Es la cifra que le dice al dueño cuánto le costó de verdad que la
    nevera se dañara antes de tiempo.
    """
    p = evento.payload
    valor = round(float(p.get("valor_compra") or 0), 2)
    if valor <= 0:
        return
    acum = round(float(p.get("deprec_acum") or 0), 2)
    venta = round(float(p.get("valor_venta") or 0), 2)
    libros = round(valor - acum, 2)

    lineas = [{"cuenta": p.get("cuenta_deprec") or CTA_DEPREC_ACUM,
               "debito": acum, "credito": 0}] if acum > 0 else []
    if venta > 0:
        lineas.append({"cuenta": CTA_CAJA, "debito": venta, "credito": 0})

    resultado = round(venta - libros, 2)
    if resultado < 0:
        lineas.append({"cuenta": CTA_PERDIDA_RETIRO, "debito": abs(resultado), "credito": 0})
    elif resultado > 0:
        # La utilidad en venta de activos es un ingreso, no una menor pérdida.
        lineas.append({"cuenta": CTA_INGRESOS, "debito": 0, "credito": resultado})

    lineas.append({"cuenta": p.get("cuenta_activo") or CTA_PPE_MAQUINARIA,
                   "debito": 0, "credito": valor})

    _registrar_asiento(
        db, tipo="baja_activo",
        concepto=f"Retiro de activo · {p.get('codigo', '')} {p.get('nombre', '')}",
        lineas=lineas, ref_tipo="activo", ref_id=evento.entidad_id, usuario=evento.usuario)


def _asiento_mantenimiento(db: Session, evento: Evento) -> None:
    """Mantenimiento al gasto (5145), nunca al valor del activo.

    Solo se capitaliza lo que aumenta la capacidad o alarga la vida útil.
    Cambiar un termostato repone la condición original; sumarlo al activo
    inflaría el balance y el gasto de depreciación de los años siguientes.
    """
    p = evento.payload
    costo = round(float(p.get("costo") or 0), 2)
    if costo <= 0:
        return
    contra = CTA_PROVEEDORES if str(p.get("credito", "")).lower() == "credito" else CTA_CAJA
    _registrar_asiento(
        db, tipo="mantenimiento",
        concepto=f"Mantenimiento {p.get('tipo', '')} · {p.get('activo', '')}",
        lineas=[{"cuenta": CTA_MANTENIMIENTO, "debito": costo, "credito": 0},
                {"cuenta": contra, "debito": 0, "credito": costo}],
        ref_tipo="mantenimiento", ref_id=evento.entidad_id, usuario=evento.usuario)


_FABRICAS = {
    TipoEvento.VENTA_REGISTRADA: _asiento_venta,
    TipoEvento.VENTA_ANULADA: _asiento_anulacion,
    TipoEvento.PERDIDA_REGISTRADA: _asiento_perdida,
    TipoEvento.INVENTARIO_ENTRADA: _asiento_compra,
    TipoEvento.CONSUMO_INTERNO: _asiento_consumo_interno,
    TipoEvento.PROPINA_REPARTIDA: _asiento_reparto_propinas,
    TipoEvento.PRODUCCION_TERMINADA: _asiento_produccion,
    TipoEvento.NOMINA_CERRADA: _asiento_nomina,
    TipoEvento.ACTIVO_ADQUIRIDO: _asiento_compra_activo,
    TipoEvento.DEPRECIACION_CERRADA: _asiento_depreciacion,
    TipoEvento.ACTIVO_DADO_BAJA: _asiento_baja_activo,
    TipoEvento.MANTENIMIENTO_REGISTRADO: _asiento_mantenimiento,
}


def _contabilizar(db: Session, evento: Evento) -> None:
    fabrica = _FABRICAS.get(evento.tipo)
    if fabrica:
        fabrica(db, evento)


def registrar_suscriptores() -> None:
    for tipo in _FABRICAS:
        suscribir(tipo, _contabilizar)


# ══════════════════════════════════════════════════════════════════════
#  CONSULTAS
# ══════════════════════════════════════════════════════════════════════
ROLES_CONTA = ("admin", "supervisor")


@router.get("/api/contabilidad/puc")
def puc(cur: dict = Depends(verify_token), db: Session = Depends(get_tenant_db)):
    return {"ok": True, "items": serial(q(db, "SELECT * FROM puc ORDER BY codigo"))}


@router.get("/api/contabilidad/asientos")
def asientos(desde: str = "", hasta: str = "", tipo: str = "", limite: int = 100,
             cur: dict = Depends(require_rol(*ROLES_CONTA)),
             db: Session = Depends(get_tenant_db)):
    limite = max(1, min(int(limite or 100), 500))
    where, params = ["a.anulado = 0"], {"l": limite}
    if desde:
        where.append("a.ts >= :d"); params["d"] = desde
    if hasta:
        where.append("a.ts <= :h"); params["h"] = hasta + "T23:59:59"
    if tipo:
        where.append("a.tipo = :tp"); params["tp"] = tipo

    filas = serial(q(db,
                     "SELECT a.*, "
                     "  (SELECT ROUND(SUM(debito),2) FROM asiento_lineas WHERE asiento_id=a.id) AS debitos, "
                     "  (SELECT ROUND(SUM(credito),2) FROM asiento_lineas WHERE asiento_id=a.id) AS creditos "
                     "FROM asientos a WHERE " + " AND ".join(where) +
                     " ORDER BY a.id DESC LIMIT :l", params))
    return {"ok": True, "items": filas}


@router.get("/api/contabilidad/asientos/{aid}")
def asiento_detalle(aid: int, cur: dict = Depends(require_rol(*ROLES_CONTA)),
                    db: Session = Depends(get_tenant_db)):
    asiento = q1(db, "SELECT * FROM asientos WHERE id = :i", {"i": aid})
    if not asiento:
        raise HTTPException(404, "Asiento no encontrado")
    return {"ok": True, "asiento": serial(dict(asiento))[0],
            "lineas": serial(q(db, "SELECT * FROM asiento_lineas WHERE asiento_id=:a "
                                   "ORDER BY id", {"a": aid}))}


@router.get("/api/contabilidad/libro-diario")
def libro_diario(desde: str = "", hasta: str = "", limite: int = 200,
                 cur: dict = Depends(require_rol(*ROLES_CONTA)),
                 db: Session = Depends(get_tenant_db)):
    limite = max(1, min(int(limite or 200), 1000))
    where, params = ["a.anulado = 0"], {"l": limite}
    if desde:
        where.append("a.ts >= :d"); params["d"] = desde
    if hasta:
        where.append("a.ts <= :h"); params["h"] = hasta + "T23:59:59"

    filas = serial(q(db,
                     "SELECT a.numero, a.ts, a.tipo, a.concepto, l.cuenta, l.nombre, "
                     "       l.debito, l.credito "
                     "FROM asiento_lineas l JOIN asientos a ON a.id = l.asiento_id "
                     "WHERE " + " AND ".join(where) +
                     " ORDER BY a.id DESC, l.id ASC LIMIT :l", params))
    return {"ok": True, "items": filas,
            "totales": {"debitos": round(sum(float(f["debito"] or 0) for f in filas), 2),
                        "creditos": round(sum(float(f["credito"] or 0) for f in filas), 2)}}


@router.get("/api/contabilidad/balance-prueba")
def balance_prueba(desde: str = "", hasta: str = "",
                   cur: dict = Depends(require_rol(*ROLES_CONTA)),
                   db: Session = Depends(get_tenant_db)):
    """Saldo por cuenta. Es la verificación global del sistema: si la suma de
    débitos no iguala la de créditos, hay un asiento mal grabado y el dato
    contable completo queda en duda."""
    where, params = ["a.anulado = 0"], {}
    if desde:
        where.append("a.ts >= :d"); params["d"] = desde
    if hasta:
        where.append("a.ts <= :h"); params["h"] = hasta + "T23:59:59"

    filas = serial(q(db,
                     "SELECT l.cuenta, l.nombre, p.tipo, p.naturaleza, "
                     "       ROUND(SUM(l.debito),2) AS debitos, "
                     "       ROUND(SUM(l.credito),2) AS creditos "
                     "FROM asiento_lineas l JOIN asientos a ON a.id = l.asiento_id "
                     "LEFT JOIN puc p ON p.codigo = l.cuenta "
                     "WHERE " + " AND ".join(where) +
                     " GROUP BY l.cuenta, l.nombre, p.tipo, p.naturaleza "
                     "ORDER BY l.cuenta", params))

    for f in filas:
        debitos = float(f["debitos"] or 0)
        creditos = float(f["creditos"] or 0)
        # El saldo se presenta según la naturaleza de la cuenta: un activo con
        # saldo débito es positivo; un pasivo con saldo crédito también. Restar
        # siempre débito menos crédito mostraría los pasivos en negativo.
        f["saldo"] = round(debitos - creditos if f.get("naturaleza") == "debito"
                           else creditos - debitos, 2)

    td = round(sum(float(f["debitos"] or 0) for f in filas), 2)
    tc = round(sum(float(f["creditos"] or 0) for f in filas), 2)
    return {"ok": True, "items": filas,
            "totales": {"debitos": td, "creditos": tc,
                        "diferencia": round(td - tc, 2),
                        "cuadra": abs(td - tc) < TOLERANCIA}}


@router.get("/api/contabilidad/estado-resultados")
def estado_resultados(desde: str = "", hasta: str = "",
                      cur: dict = Depends(require_rol(*ROLES_CONTA)),
                      db: Session = Depends(get_tenant_db)):
    """Ingresos − costos − gastos, construido desde los asientos."""
    where, params = ["a.anulado = 0"], {}
    if desde:
        where.append("a.ts >= :d"); params["d"] = desde
    if hasta:
        where.append("a.ts <= :h"); params["h"] = hasta + "T23:59:59"

    filas = q(db,
              "SELECT p.tipo, l.cuenta, l.nombre, "
              "       ROUND(SUM(l.debito),2) AS d, ROUND(SUM(l.credito),2) AS c "
              "FROM asiento_lineas l JOIN asientos a ON a.id = l.asiento_id "
              "JOIN puc p ON p.codigo = l.cuenta "
              "WHERE " + " AND ".join(where) +
              "  AND p.tipo IN ('ingreso','costo','gasto') "
              "GROUP BY p.tipo, l.cuenta, l.nombre ORDER BY l.cuenta", params)

    grupos: dict[str, list] = {"ingreso": [], "costo": [], "gasto": []}
    for f in filas:
        d, c = float(f["d"] or 0), float(f["c"] or 0)
        valor = round(c - d, 2) if f["tipo"] == "ingreso" else round(d - c, 2)
        grupos[f["tipo"]].append({"cuenta": f["cuenta"], "nombre": f["nombre"],
                                  "valor": valor})

    ingresos = round(sum(x["valor"] for x in grupos["ingreso"]), 2)
    costos = round(sum(x["valor"] for x in grupos["costo"]), 2)
    gastos = round(sum(x["valor"] for x in grupos["gasto"]), 2)
    bruta = round(ingresos - costos, 2)
    neta = round(bruta - gastos, 2)

    return {"ok": True, "ingresos": grupos["ingreso"], "costos": grupos["costo"],
            "gastos": grupos["gasto"],
            "resumen": {"ingresos": ingresos, "costos": costos, "gastos": gastos,
                        "utilidad_bruta": bruta, "utilidad_neta": neta,
                        "margen_bruto_pct": round(bruta / ingresos * 100, 1) if ingresos else None,
                        "margen_neto_pct": round(neta / ingresos * 100, 1) if ingresos else None}}
