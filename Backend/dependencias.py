# -*- coding: utf-8 -*-
"""
================================================================
  RESTAURANTE · Dependencias compartidas de FastAPI
================================================================
Aísla la resolución de la sesión de base de datos de la sede activa. Cualquier
endpoint que declare `db: Session = Depends(get_tenant_db)` recibe una sesión
YA apuntando a la base correcta, sin escribir una línea sobre multi-tenancy.

Ese es el valor de la inyección de dependencias aquí: la regla «cada quien ve
solo los datos de su sede» se implementa UNA vez y no puede olvidarse en un
endpoint nuevo, porque el endpoint no tiene otra forma de obtener una sesión.

Autor: Arquitectura de Software · Unidad 1
================================================================
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from db import MASTER_DB, get_sessionmaker, q1
from seguridad import verify_token

# Cache de sedes válidas ya verificadas en este proceso (patrón Cache-Aside).
# Evita ir a la maestra en cada request solo para confirmar que la sede sigue
# activa. Se invalida al desactivar una sede desde administración.
_SEDES_OK: set[str] = set()


def invalidar_cache_sedes() -> None:
    _SEDES_OK.clear()


def get_tenant_db(cur: dict = Depends(verify_token)) -> Session:
    """Sesión a la base de la sede del usuario autenticado.

    El `db_name` viene firmado dentro del JWT, pero igual se confronta contra
    la maestra la primera vez: si una sede se desactiva, las sesiones vigentes
    deben dejar de funcionar sin esperar a que expire su token.
    """
    db_name = cur.get("db_name")
    if not db_name:
        raise HTTPException(401, "El token no identifica una sede")

    if db_name not in _SEDES_OK:
        mdb = get_sessionmaker(MASTER_DB)()
        try:
            fila = q1(mdb, "SELECT id FROM tenants WHERE db_name=:d AND activo=1",
                      {"d": db_name})
        finally:
            mdb.close()
        if not fila:
            raise HTTPException(403, "Sede inactiva o inexistente")
        _SEDES_OK.add(db_name)

    db = get_sessionmaker(db_name)()
    try:
        yield db
    finally:
        db.close()


def get_master_db() -> Session:
    """Sesión a la base maestra (login, sedes, usuarios globales)."""
    db = get_sessionmaker(MASTER_DB)()
    try:
        yield db
    finally:
        db.close()


def client_ip(request: Request) -> str:
    """IP del cliente respetando el proxy inverso.

    Detrás de un balanceador, `request.client.host` es la IP del balanceador y
    no la del usuario: la bitácora de auditoría registraría siempre la misma
    dirección y sería inútil.
    """
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return getattr(request.client, "host", "") or ""
