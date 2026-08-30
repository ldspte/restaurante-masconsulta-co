# -*- coding: utf-8 -*-
"""
================================================================
  RESTAURANTE · Bus de Eventos de Dominio  (patrón Observador)
================================================================
Pieza central de la arquitectura. Resuelve el problema de acoplamiento más
grave de un sistema de punto de venta: **una venta no es solo una venta**.
Cuando se cobra un capuchino ocurren tres cosas a la vez:

    1. Se registra el documento de venta          (módulo Caja)
    2. Se descuentan café, leche y vaso            (módulo Inventario)
    3. Se contabiliza ingreso, IVA y costo         (módulo Contabilidad)

La solución ingenua es que el módulo de Caja llame directamente a Inventario y
a Contabilidad. Eso hace que Caja dependa de los dos, que no se pueda probar
por separado y que agregar una cuarta reacción (puntos de fidelidad, factura
electrónica) obligue a editar Caja otra vez.

Aquí Caja solo **publica un hecho**: `venta.registrada`. Quién reacciona y cómo
es decisión de los suscriptores. Caja no los conoce.

    Caja ──publica──▶ [ BUS ] ──▶ Inventario
                          └─────▶ Contabilidad
                          └─────▶ (futuro: fidelidad, DIAN, notificaciones)

TRANSACCIONALIDAD — decisión explícita
--------------------------------------
El despacho es **síncrono y dentro de la misma transacción** del publicador.
Es deliberado: si la contabilización falla, la venta NO debe quedar registrada.
Un POS que vende sin descontar inventario produce un descuadre que alguien
tendrá que corregir a mano. Se prefiere fallar la operación completa.

El precio es latencia: la venta tarda lo que tarden sus suscriptores. Para el
volumen de una cafetería (decenas de ventas por hora) es irrelevante. Si el
sistema creciera a cientos de sedes, la evolución natural es mover los
suscriptores no críticos (notificaciones, analítica) a una cola asíncrona
—Redis o SQS— dejando en la transacción solo inventario y contabilidad. La
firma de este módulo no cambiaría: `publicar()` seguiría siendo el punto único.

Autor: Arquitectura de Software · Unidad 1
================================================================
"""
from __future__ import annotations

import json
import logging
import traceback
from dataclasses import dataclass, field
from typing import Callable

from sqlalchemy.orm import Session

from db import ahora, run_sin_commit

log = logging.getLogger("cafeteria.eventos")


# ── Tipos de evento del dominio ──────────────────────────────────────────
# Constantes en vez de cadenas sueltas: un error de tipeo en un nombre de
# evento produce un suscriptor que nunca se dispara y un fallo silencioso.
class TipoEvento:
    # Venta y caja
    VENTA_REGISTRADA = "venta.registrada"
    VENTA_ANULADA = "venta.anulada"
    CAJA_CERRADA = "caja.cerrada"
    # Inventario
    PERDIDA_REGISTRADA = "perdida.registrada"
    INVENTARIO_ENTRADA = "inventario.entrada"
    INVENTARIO_AJUSTE = "inventario.ajuste"
    INVENTARIO_BAJO_MINIMO = "inventario.bajo_minimo"
    # Produccion propia
    PRODUCCION_TERMINADA = "produccion.terminada"
    # Personal
    CONSUMO_INTERNO = "consumo.interno"
    PROPINA_RECIBIDA = "propina.recibida"
    PROPINA_REPARTIDA = "propina.repartida"
    NOMINA_CERRADA = "nomina.cerrada"
    # Salon
    COMANDA_CERRADA = "comanda.cerrada"
    # Aprovechamiento de sobrantes (el calentado)
    COCINA_CERRADA = "cocina.cerrada"
    SOBRANTE_APROVECHADO = "sobrante.aprovechado"
    SOBRANTE_VENCIDO = "sobrante.vencido"
    # Propiedad, planta y equipo
    ACTIVO_ADQUIRIDO = "activo.adquirido"
    ACTIVO_DADO_BAJA = "activo.baja"
    MANTENIMIENTO_REGISTRADO = "mantenimiento.registrado"
    DEPRECIACION_CERRADA = "depreciacion.cerrada"


@dataclass
class Evento:
    """Hecho ya ocurrido. Se nombra en pasado: describe algo consumado, no una
    orden. Esa diferencia es la que permite que haya cero o muchos
    suscriptores sin que el publicador cambie."""

    tipo: str
    entidad: str
    entidad_id: int
    payload: dict = field(default_factory=dict)
    usuario: str = "sistema"


# ── Registro de suscriptores ─────────────────────────────────────────────
Manejador = Callable[[Session, Evento], None]
_SUSCRIPTORES: dict[str, list[Manejador]] = {}


def suscribir(tipo: str, manejador: Manejador) -> None:
    """Registra un manejador para un tipo de evento. IDEMPOTENTE.

    El cableado se hace en un solo lugar auditable (`cablear_eventos()` en
    main.py) y no como efecto secundario de importar cada módulo.

    La idempotencia no es un adorno: es una salvaguarda contra el fallo más
    caro de esta arquitectura. Si por cualquier razón el cableado se ejecuta dos
    veces —doble import del módulo, un `reload`, una prueba que reinicializa—,
    cada venta descontaría el inventario dos veces y duplicaría sus asientos
    contables. Y lo haría en silencio: no hay error, solo datos corruptos que
    alguien descubre semanas después al cuadrar el inventario.

    Registrar dos veces el mismo manejador para el mismo evento es siempre un
    error de programación, nunca una intención legítima. Por eso se ignora y se
    deja advertencia, en lugar de acumular el duplicado.
    """
    manejadores = _SUSCRIPTORES.setdefault(tipo, [])
    if manejador in manejadores:
        log.warning("Suscriptor duplicado ignorado: %s → %s",
                    tipo, getattr(manejador, "__name__", manejador))
        return
    manejadores.append(manejador)
    log.debug("Suscriptor registrado: %s → %s", tipo, getattr(manejador, "__name__", manejador))


def suscriptores_de(tipo: str) -> list[Manejador]:
    return list(_SUSCRIPTORES.get(tipo, []))


def mapa_suscriptores() -> dict[str, list[str]]:
    """Introspección del bus: qué reacciona a qué.

    Se expone en `/api/health/eventos`. En un sistema orientado a eventos, la
    pregunta «¿quién está escuchando esto?» es la más frecuente al depurar, y
    responderla leyendo imports es lento y poco confiable.
    """
    return {
        tipo: [getattr(h, "__name__", repr(h)) for h in hs]
        for tipo, hs in sorted(_SUSCRIPTORES.items())
    }


# ── Publicación ──────────────────────────────────────────────────────────
def publicar(db: Session, evento: Evento) -> None:
    """Registra el evento y ejecuta sus suscriptores en la MISMA transacción.

    NO hace commit. El publicador decide cuándo confirmar, de modo que la
    operación completa —hecho de negocio y todas sus consecuencias— sea atómica.

    REGLA PARA QUIEN PUBLICA
    ------------------------
    Publicar un hecho y ADEMÁS ejecutar su consecuencia produce la consecuencia
    dos veces. Si `perdida.registrada` ya tiene a Inventario suscrito, quien
    publica ese evento NO debe descontar el stock también: eso lo hace el
    suscriptor. Suena obvio y aun así ocurrió —la merma del cierre de cocina
    descontaba el doble— y no lo mostraba ninguna pantalla, porque los dos
    números viven en módulos distintos.

    Ante la duda: `GET /api/health/eventos` dice quién está escuchando qué.

    Si un manejador lanza, la excepción se propaga: el publicador hará rollback
    y la operación entera se deshace. Es intencional; ver la nota de
    transaccionalidad en la cabecera del módulo.
    """
    run_sin_commit(
        db,
        "INSERT INTO eventos (ts, tipo, entidad, entidad_id, payload, usuario, estado) "
        "VALUES (:ts, :tp, :en, :ei, :pl, :us, 'ok')",
        {
            "ts": ahora(),
            "tp": evento.tipo,
            "en": evento.entidad,
            "ei": evento.entidad_id,
            "pl": json.dumps(evento.payload, ensure_ascii=False, default=str),
            "us": evento.usuario,
        },
    )

    manejadores = _SUSCRIPTORES.get(evento.tipo, [])
    if not manejadores:
        log.info("Evento %s sin suscriptores", evento.tipo)
        return

    for manejador in manejadores:
        nombre = getattr(manejador, "__name__", repr(manejador))
        try:
            manejador(db, evento)
        except Exception as exc:
            # Se deja rastro del manejador exacto que falló ANTES de propagar.
            # Sin esto, el usuario ve «error al guardar la venta» y no hay forma
            # de saber si falló inventario o contabilidad.
            log.error(
                "Manejador %s falló ante %s(%s): %s\n%s",
                nombre, evento.tipo, evento.entidad_id, exc, traceback.format_exc(),
            )
            raise RuntimeError(
                f"El evento «{evento.tipo}» falló en «{nombre}»: {exc}"
            ) from exc


def limpiar_suscriptores() -> None:
    """Vacía el registro. Uso exclusivo de las pruebas, para que cada caso
    parta de un bus limpio y no herede suscriptores de otro test."""
    _SUSCRIPTORES.clear()
