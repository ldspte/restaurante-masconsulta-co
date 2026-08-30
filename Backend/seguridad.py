# -*- coding: utf-8 -*-
"""
================================================================
  RESTAURANTE · Seguridad, Identidad y Autorización
================================================================
Componente transversal. Resuelve tres preguntas y nada más:

    ¿Quién eres?        → hash de contraseña + emisión de JWT
    ¿Sigue vigente?     → validación de firma, expiración y token_version
    ¿Puedes hacer esto? → guard por rol (`require_rol`)

DECISIÓN — PBKDF2 de la biblioteca estándar
-------------------------------------------
Se usa `hashlib.pbkdf2_hmac` con 240.000 iteraciones y sal aleatoria por
usuario, en lugar de una dependencia externa. Argon2/bcrypt son mejores, pero
PBKDF2-SHA256 con este factor de trabajo es aceptable (recomendación OWASP) y
mantiene el prototipo sin dependencias nativas que compilar. El formato del
hash lleva el algoritmo y las iteraciones embebidos, de modo que subir el
factor de trabajo más adelante no invalida los hashes existentes.

DECISIÓN — token_version para revocación
----------------------------------------
Un JWT es válido hasta que expira: no se puede "cerrar sesión" del lado del
servidor sin estado adicional. Se resuelve con un contador por usuario que se
incrementa al cerrar sesión o cambiar la contraseña; el token trae ese número y
se rechaza si no coincide. Es una sola lectura por request contra la maestra a
cambio de poder revocar sesiones de verdad.

Autor: Arquitectura de Software · Unidad 1
================================================================
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import os
import secrets
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer

from db import MASTER_DB, get_sessionmaker, q1

# ── Parámetros ───────────────────────────────────────────────────────────
SECRET_KEY = os.getenv("RST_SECRET_KEY", "")
if not SECRET_KEY:
    # En desarrollo se genera una clave efímera: reiniciar el servidor invalida
    # las sesiones, que es el comportamiento correcto y avisa que falta config.
    SECRET_KEY = secrets.token_hex(32)
ALGORITHM = "HS256"
TOKEN_EXP_HORAS = int(os.getenv("RST_TOKEN_EXP_HORAS", "12"))
AUTH_COOKIE = "rst_token"

_PBKDF2_ITER = 240_000

oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


# ══════════════════════════════════════════════════════════════════════
#  Contraseñas
# ══════════════════════════════════════════════════════════════════════
def hash_password(password: str) -> str:
    """Devuelve `pbkdf2_sha256$<iter>$<sal_hex>$<hash_hex>`."""
    if not password:
        raise ValueError("La contraseña no puede estar vacía")
    sal = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), sal, _PBKDF2_ITER)
    return f"pbkdf2_sha256${_PBKDF2_ITER}${sal.hex()}${dk.hex()}"


def verify_password(password: str, almacenado: str) -> bool:
    """Compara en tiempo constante. Nunca lanza: un hash corrupto es un
    fallo de autenticación, no un error 500 que revele el estado interno."""
    try:
        algo, iters, sal_hex, hash_hex = (almacenado or "").split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", (password or "").encode("utf-8"),
            bytes.fromhex(sal_hex), int(iters),
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════
#  Tokens
# ══════════════════════════════════════════════════════════════════════
SCOPE_SESION = "sesion"          # token de trabajo: ya tiene sede resuelta
SCOPE_SELECCION = "seleccion"    # token intermedio: solo sirve para elegir sede
MINUTOS_SELECCION = 10


def emitir_token(usuario: dict, tenant: dict, rol: str, token_version: int = 0) -> str:
    """Emite el JWT de sesión ya resuelto contra una sede.

    Los claims llevan `tenant_id` y `db_name`: con eso, cada request sabe a qué
    base conectarse sin volver a consultar la maestra. `db_name` se valida
    igualmente al resolver la sesión — el token es de confianza porque va
    firmado, pero el nombre de base nunca se concatena sin pasar por la
    validación de slug de `db.py`.
    """
    ahora_utc = datetime.datetime.now(datetime.timezone.utc)
    return jwt.encode(
        {
            "user_id": usuario["id"],
            "nombre": usuario["nombre"],
            "email": usuario["email"],
            "es_superadmin": int(usuario.get("es_superadmin") or 0),
            "tenant_id": tenant["id"],
            "tenant_nombre": tenant["nombre"],
            "db_name": tenant["db_name"],
            "rol": rol,
            "scope": SCOPE_SESION,
            "tv": int(token_version or 0),
            "iat": ahora_utc,
            "exp": ahora_utc + datetime.timedelta(hours=TOKEN_EXP_HORAS),
        },
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def emitir_token_seleccion(usuario: dict, token_version: int = 0) -> str:
    """Token intermedio para quien tiene acceso a varias sedes.

    Existe porque la autenticación y la elección de sede son dos pasos: entre
    uno y otro el usuario está identificado pero todavía no opera sobre ningún
    dato. Se distingue del token de trabajo por el claim `scope`, y sirve
    ÚNICAMENTE para llamar a `/api/auth/seleccionar-sede`.

    Sin esa distinción habría que aceptar tokens sin sede en la dependencia
    general, y un token a medio autenticar podría alcanzar endpoints de negocio.
    Vive diez minutos: es un paso de trámite, no una sesión.
    """
    ahora_utc = datetime.datetime.now(datetime.timezone.utc)
    return jwt.encode(
        {
            "user_id": usuario["id"],
            "nombre": usuario["nombre"],
            "email": usuario["email"],
            "es_superadmin": int(usuario.get("es_superadmin") or 0),
            "scope": SCOPE_SELECCION,
            "tv": int(token_version or 0),
            "iat": ahora_utc,
            "exp": ahora_utc + datetime.timedelta(minutes=MINUTOS_SELECCION),
        },
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def decodificar_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "La sesión expiró. Vuelva a iniciar sesión.")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Token inválido")


def _leer_token(request: Optional[Request], header_token: Optional[str]) -> Optional[str]:
    """Autenticación dual: encabezado Authorization o cookie HttpOnly.

    El encabezado sirve a clientes de prueba (curl, pytest); la cookie protege
    al navegador de exfiltración por XSS, ya que JavaScript no puede leerla.
    """
    if header_token:
        return header_token
    if request is None:
        return None
    return request.cookies.get(AUTH_COOKIE)


def _claims_validados(request: Request, token: str | None) -> dict:
    """Decodifica el token y comprueba que el usuario siga habilitado."""
    eff = _leer_token(request, token)
    if not eff:
        raise HTTPException(401, "Autenticación requerida")
    claims = decodificar_token(eff)

    # Revocación: el sello del token debe coincidir con el del usuario.
    mdb = get_sessionmaker(MASTER_DB)()
    try:
        fila = q1(
            mdb,
            "SELECT COALESCE(token_version,0) AS tv, activo "
            "FROM usuarios_globales WHERE id = :i",
            {"i": claims.get("user_id")},
        )
    finally:
        mdb.close()

    if not fila:
        raise HTTPException(401, "Usuario no encontrado")
    if not int(fila.get("activo") or 0):
        raise HTTPException(403, "Usuario inactivo")
    if int(fila.get("tv") or 0) != int(claims.get("tv") or 0):
        raise HTTPException(401, "La sesión fue cerrada. Vuelva a iniciar sesión.")

    return claims


def verify_token(request: Request, token: str = Depends(oauth2)) -> dict:
    """Dependencia de autenticación para los endpoints de negocio.

    Exige un token de trabajo con sede resuelta. Un token de selección aquí es
    un 401 explícito: está a medio camino del proceso de ingreso.
    """
    claims = _claims_validados(request, token)

    if claims.get("scope") == SCOPE_SELECCION or not claims.get("tenant_id"):
        raise HTTPException(401, "Seleccione una sede antes de continuar")
    return claims


def verify_token_seleccion(request: Request, token: str = Depends(oauth2)) -> dict:
    """Dependencia exclusiva del paso «elegir sede».

    Acepta tanto el token de selección como uno de trabajo: el segundo caso
    permite que un usuario ya dentro del sistema cambie de sede sin volver a
    escribir su contraseña.
    """
    return _claims_validados(request, token)


# ══════════════════════════════════════════════════════════════════════
#  Autorización por rol
# ══════════════════════════════════════════════════════════════════════
def require_rol(*roles: str):
    """Fábrica de dependencias que exige uno de los roles indicados.

    Uso:
        @router.post("/api/inventario/entradas")
        def entrada(cur: dict = Depends(require_rol("admin", "bodega"))):
            ...

    El superadministrador atraviesa todos los guards por diseño: es la cuenta
    de soporte del proveedor del software y debe poder diagnosticar cualquier
    sede sin que el cliente le abra permisos uno por uno.
    """
    permitidos = set(roles)

    def _guard(cur: dict = Depends(verify_token)) -> dict:
        if int(cur.get("es_superadmin") or 0) == 1:
            return cur
        if cur.get("rol") not in permitidos:
            raise HTTPException(
                403,
                "Su rol («%s») no tiene permiso para esta operación. "
                "Se requiere: %s." % (cur.get("rol"), ", ".join(sorted(permitidos))),
            )
        return cur

    return _guard


def autor(cur: dict | None) -> str:
    """Nombre legible para las columnas de trazabilidad (`usuario`)."""
    cur = cur or {}
    return cur.get("nombre") or cur.get("email") or "sistema"
