# -*- coding: utf-8 -*-
"""
================================================================
  CAFETERÍA · Módulo ACCESOS
================================================================
Autenticación, sesión y administración de usuarios y sedes.

Es el único módulo que escribe en la base maestra. Todos los demás operan
exclusivamente sobre la base de su sede; esa separación mantiene el aislamiento
multi-tenant como una propiedad estructural y no como una disciplina que cada
programador deba recordar.

Rutas
  POST   /api/auth/login                 credenciales → sedes disponibles o token
  POST   /api/auth/seleccionar-sede      elige sede → token de trabajo
  GET    /api/auth/yo                    perfil, rol y módulos visibles
  POST   /api/auth/logout                revoca las sesiones del usuario
  POST   /api/auth/cambiar-password      cambio propio (revoca sesiones)
  GET    /api/accesos/usuarios           listado de la sede
  POST   /api/accesos/usuarios           alta + asignación
  PUT    /api/accesos/usuarios/{id}      rol / estado
  GET    /api/accesos/sedes              sedes visibles
  POST   /api/accesos/sedes              nueva sede (solo superadmin)
  GET    /api/accesos/auditoria          bitácora

Autor: Arquitectura de Software · Unidad 1
================================================================
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

import provisioning
import seed_master
from db import MASTER_DB, ahora, get_sessionmaker, q, q1, run, serial
from dependencias import client_ip, get_master_db, invalidar_cache_sedes
from seguridad import (AUTH_COOKIE, TOKEN_EXP_HORAS, emitir_token,
                       emitir_token_seleccion, hash_password, require_rol,
                       verify_password, verify_token, verify_token_seleccion)

router = APIRouter(tags=["Accesos"])


# ── Bitácora ─────────────────────────────────────────────────────────────
def auditar(accion: str, entidad: str, entidad_id, detalle: str,
            cur: dict | None = None, ip: str = "") -> None:
    """Registro de auditoría. Nunca interrumpe la operación: si la bitácora
    falla, el negocio debe seguir. Se registra en un `try` por eso mismo."""
    try:
        mdb = get_sessionmaker(MASTER_DB)()
        try:
            run(mdb,
                "INSERT INTO audit_log (ts, tenant_id, usuario, accion, entidad, "
                "entidad_id, detalle, ip) VALUES (:ts,:t,:u,:a,:e,:ei,:d,:ip)",
                {"ts": ahora(), "t": (cur or {}).get("tenant_id"),
                 "u": (cur or {}).get("email") or "anónimo", "a": accion,
                 "e": entidad, "ei": entidad_id, "d": detalle, "ip": ip})
        finally:
            mdb.close()
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════
#  AUTENTICACIÓN
# ══════════════════════════════════════════════════════════════════════
@router.post("/api/auth/login")
def login(request: Request, response: Response, body: dict = Body(...),
          mdb: Session = Depends(get_master_db)):
    """Valida credenciales y devuelve las sedes a las que el usuario accede.

    Si solo tiene una, ya emite el token de trabajo: obligar a elegir entre una
    única opción es fricción sin propósito.
    """
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    if not email or not password:
        raise HTTPException(400, "Correo y contraseña son obligatorios")

    u = q1(mdb, "SELECT * FROM usuarios_globales WHERE email = :e", {"e": email})

    # Mensaje idéntico para «no existe» y «clave incorrecta»: distinguirlos
    # permitiría enumerar qué correos están registrados en el sistema.
    if not u or not verify_password(password, u.get("pass_hash") or ""):
        auditar("login_fallido", "usuario", None, email, None, client_ip(request))
        raise HTTPException(401, "Credenciales incorrectas")
    if not int(u.get("activo") or 0):
        raise HTTPException(403, "Usuario inactivo. Contacte al administrador.")

    sedes = q(mdb,
              "SELECT t.id, t.nombre, t.slug, t.db_name, t.ciudad, ut.rol "
              "FROM usuario_tenant ut JOIN tenants t ON t.id = ut.tenant_id "
              "WHERE ut.usuario_id = :u AND ut.activo = 1 AND t.activo = 1 "
              "ORDER BY t.nombre", {"u": u["id"]})

    if int(u.get("es_superadmin") or 0) == 1 and not sedes:
        sedes = q(mdb, "SELECT id, nombre, slug, db_name, ciudad, 'admin' AS rol "
                       "FROM tenants WHERE activo = 1 ORDER BY nombre")
    if not sedes:
        raise HTTPException(403, "Su usuario no tiene ninguna sede asignada.")

    perfil = {"id": u["id"], "nombre": u["nombre"], "email": u["email"],
              "es_superadmin": int(u.get("es_superadmin") or 0)}

    if len(sedes) == 1:
        sede = sedes[0]
        token = emitir_token(perfil, sede, sede["rol"], u.get("token_version") or 0)
        _set_cookie(response, token)
        auditar("login", "usuario", u["id"], f"sede={sede['slug']}",
                {"tenant_id": sede["id"], "email": email}, client_ip(request))
        return {"ok": True, "token": token, "usuario": perfil, "sede": sede,
                "rol": sede["rol"],
                "modulos": seed_master.MODULOS_POR_ROL.get(sede["rol"], [])}

    # Varias sedes: token de selección de vida corta, sin sede resuelta.
    token_sel = emitir_token_seleccion(perfil, u.get("token_version") or 0)
    return {"ok": True, "requiere_seleccion": True, "token_seleccion": token_sel,
            "usuario": perfil, "sedes": serial(sedes)}


@router.post("/api/auth/seleccionar-sede")
def seleccionar_sede(request: Request, response: Response, body: dict = Body(...),
                     cur: dict = Depends(verify_token_seleccion),
                     mdb: Session = Depends(get_master_db)):
    sede_id = int(body.get("sede_id") or 0)
    if not sede_id:
        raise HTTPException(400, "Indique la sede")

    if int(cur.get("es_superadmin") or 0) == 1:
        fila = q1(mdb, "SELECT id, nombre, slug, db_name, 'admin' AS rol "
                       "FROM tenants WHERE id=:i AND activo=1", {"i": sede_id})
    else:
        fila = q1(mdb,
                  "SELECT t.id, t.nombre, t.slug, t.db_name, ut.rol "
                  "FROM usuario_tenant ut JOIN tenants t ON t.id = ut.tenant_id "
                  "WHERE ut.usuario_id=:u AND t.id=:i AND ut.activo=1 AND t.activo=1",
                  {"u": cur["user_id"], "i": sede_id})
    if not fila:
        raise HTTPException(403, "No tiene acceso a esa sede")

    u = q1(mdb, "SELECT id, nombre, email, es_superadmin, token_version "
                "FROM usuarios_globales WHERE id=:i", {"i": cur["user_id"]})
    token = emitir_token(u, fila, fila["rol"], u.get("token_version") or 0)
    _set_cookie(response, token)
    auditar("seleccionar_sede", "sede", sede_id, fila["nombre"],
            {"tenant_id": sede_id, "email": u["email"]}, client_ip(request))
    return {"ok": True, "token": token, "sede": fila, "rol": fila["rol"],
            "modulos": seed_master.MODULOS_POR_ROL.get(fila["rol"], [])}


@router.get("/api/auth/yo")
def yo(cur: dict = Depends(verify_token)):
    """Perfil de la sesión. El frontend lo pide al arrancar para construir el
    menú; devolver los módulos desde el servidor evita que el cliente decida
    por su cuenta qué puede ver."""
    rol = cur.get("rol")
    return {"ok": True,
            "usuario": {"id": cur.get("user_id"), "nombre": cur.get("nombre"),
                        "email": cur.get("email"),
                        "es_superadmin": cur.get("es_superadmin")},
            "sede": {"id": cur.get("tenant_id"), "nombre": cur.get("tenant_nombre")},
            "rol": rol,
            "modulos": seed_master.MODULOS_POR_ROL.get(rol, []),
            "roles": seed_master.ROLES}


@router.post("/api/auth/logout")
def logout(response: Response, cur: dict = Depends(verify_token),
           mdb: Session = Depends(get_master_db)):
    """Cierre de sesión real: sube `token_version`, con lo que TODOS los tokens
    emitidos para ese usuario quedan invalidados de inmediato."""
    run(mdb, "UPDATE usuarios_globales SET token_version = COALESCE(token_version,0) + 1 "
             "WHERE id = :i", {"i": cur["user_id"]})
    response.delete_cookie(AUTH_COOKIE)
    auditar("logout", "usuario", cur["user_id"], "", cur)
    return {"ok": True}


@router.post("/api/auth/cambiar-password")
def cambiar_password(response: Response, body: dict = Body(...),
                     cur: dict = Depends(verify_token),
                     mdb: Session = Depends(get_master_db)):
    actual = body.get("actual") or ""
    nueva = body.get("nueva") or ""
    if len(nueva) < 8:
        raise HTTPException(400, "La nueva contraseña debe tener al menos 8 caracteres")
    u = q1(mdb, "SELECT pass_hash FROM usuarios_globales WHERE id=:i", {"i": cur["user_id"]})
    if not u or not verify_password(actual, u["pass_hash"]):
        raise HTTPException(403, "La contraseña actual no es correcta")
    run(mdb, "UPDATE usuarios_globales SET pass_hash=:p, "
             "token_version = COALESCE(token_version,0) + 1 WHERE id=:i",
        {"p": hash_password(nueva), "i": cur["user_id"]})
    response.delete_cookie(AUTH_COOKIE)
    auditar("cambio_password", "usuario", cur["user_id"], "", cur)
    return {"ok": True, "mensaje": "Contraseña actualizada. Inicie sesión nuevamente."}


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        AUTH_COOKIE, token, httponly=True, samesite="lax",
        max_age=TOKEN_EXP_HORAS * 3600,
        secure=False,   # en producción tras HTTPS: True
    )


# ══════════════════════════════════════════════════════════════════════
#  ADMINISTRACIÓN DE USUARIOS
# ══════════════════════════════════════════════════════════════════════
@router.get("/api/accesos/usuarios")
def usuarios_listar(cur: dict = Depends(require_rol("admin")),
                    mdb: Session = Depends(get_master_db)):
    filas = q(mdb,
              "SELECT u.id, u.nombre, u.email, u.es_superadmin, u.activo, "
              "       ut.rol, ut.activo AS acceso_activo "
              "FROM usuario_tenant ut JOIN usuarios_globales u ON u.id = ut.usuario_id "
              "WHERE ut.tenant_id = :t ORDER BY u.nombre",
              {"t": cur["tenant_id"]})
    return {"ok": True, "items": serial(filas), "roles": seed_master.ROLES}


@router.post("/api/accesos/usuarios", status_code=201)
def usuarios_crear(request: Request, body: dict = Body(...),
                   cur: dict = Depends(require_rol("admin")),
                   mdb: Session = Depends(get_master_db)):
    nombre = (body.get("nombre") or "").strip()
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    rol = (body.get("rol") or "cajero").strip()

    if not nombre or not email:
        raise HTTPException(400, "Nombre y correo son obligatorios")
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(400, "El correo no tiene un formato válido")
    if rol not in seed_master.ROLES_VALIDOS:
        raise HTTPException(400, f"Rol desconocido: {rol}")
    if len(password) < 8:
        raise HTTPException(400, "La contraseña debe tener al menos 8 caracteres")

    existente = q1(mdb, "SELECT id FROM usuarios_globales WHERE email=:e", {"e": email})
    if existente:
        # El usuario ya existe en otra sede: se le concede acceso a esta,
        # sin tocar su contraseña. Una identidad, varias sedes.
        uid = int(existente["id"])
    else:
        uid = provisioning.crear_usuario_global(mdb, nombre, email, password, 0)

    provisioning.asignar_a_sede(mdb, uid, int(cur["tenant_id"]), rol)
    provisioning.sincronizar_usuarios_sede(int(cur["tenant_id"]), cur["db_name"])
    auditar("crear_usuario", "usuario", uid, f"{email} rol={rol}", cur, client_ip(request))
    return {"ok": True, "id": uid, "reutilizado": bool(existente)}


@router.put("/api/accesos/usuarios/{uid}")
def usuarios_editar(uid: int, request: Request, body: dict = Body(...),
                    cur: dict = Depends(require_rol("admin")),
                    mdb: Session = Depends(get_master_db)):
    fila = q1(mdb, "SELECT id, rol FROM usuario_tenant WHERE usuario_id=:u AND tenant_id=:t",
              {"u": uid, "t": cur["tenant_id"]})
    if not fila:
        raise HTTPException(404, "El usuario no pertenece a esta sede")

    # Un administrador no puede quitarse a sí mismo el acceso: dejaría la sede
    # sin quien administre y solo el proveedor podría recuperarla.
    if int(uid) == int(cur["user_id"]):
        if body.get("rol") and body["rol"] != "admin":
            raise HTTPException(400, "No puede cambiar su propio rol de administrador")
        if body.get("activo") == 0:
            raise HTTPException(400, "No puede desactivar su propio usuario")

    if "rol" in body:
        if body["rol"] not in seed_master.ROLES_VALIDOS:
            raise HTTPException(400, f"Rol desconocido: {body['rol']}")
        run(mdb, "UPDATE usuario_tenant SET rol=:r WHERE id=:i",
            {"r": body["rol"], "i": fila["id"]})
    if "activo" in body:
        run(mdb, "UPDATE usuario_tenant SET activo=:a WHERE id=:i",
            {"a": int(bool(body["activo"])), "i": fila["id"]})
        # Revoca sus sesiones vivas: desactivar sin revocar deja al usuario
        # operando hasta que expire su token.
        run(mdb, "UPDATE usuarios_globales SET token_version = COALESCE(token_version,0)+1 "
                 "WHERE id=:i", {"i": uid})
    if body.get("password"):
        if len(body["password"]) < 8:
            raise HTTPException(400, "La contraseña debe tener al menos 8 caracteres")
        run(mdb, "UPDATE usuarios_globales SET pass_hash=:p, "
                 "token_version = COALESCE(token_version,0)+1 WHERE id=:i",
            {"p": hash_password(body["password"]), "i": uid})

    provisioning.sincronizar_usuarios_sede(int(cur["tenant_id"]), cur["db_name"])
    auditar("editar_usuario", "usuario", uid, str(body.get("rol") or body.get("activo")),
            cur, client_ip(request))
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════
#  SEDES
# ══════════════════════════════════════════════════════════════════════
@router.get("/api/accesos/sedes")
def sedes_listar(cur: dict = Depends(verify_token), mdb: Session = Depends(get_master_db)):
    if int(cur.get("es_superadmin") or 0) == 1:
        filas = q(mdb, "SELECT id, nombre, slug, ciudad, activo, 'admin' AS rol "
                       "FROM tenants ORDER BY nombre")
    else:
        filas = q(mdb, "SELECT t.id, t.nombre, t.slug, t.ciudad, t.activo, ut.rol "
                       "FROM usuario_tenant ut JOIN tenants t ON t.id=ut.tenant_id "
                       "WHERE ut.usuario_id=:u AND ut.activo=1 ORDER BY t.nombre",
                  {"u": cur["user_id"]})
    return {"ok": True, "items": serial(filas)}


@router.post("/api/accesos/sedes", status_code=201)
def sedes_crear(request: Request, body: dict = Body(...),
                cur: dict = Depends(verify_token)):
    """Alta de sede. Es la operación que materializa la escalabilidad
    horizontal: crea una base nueva y aislada, sin tocar las existentes."""
    if int(cur.get("es_superadmin") or 0) != 1:
        raise HTTPException(403, "Solo el superadministrador puede crear sedes")
    nombre = (body.get("nombre") or "").strip()
    slug = (body.get("slug") or "").strip().lower()
    if not nombre or not slug:
        raise HTTPException(400, "Nombre y código de sede son obligatorios")
    try:
        sede = provisioning.crear_sede(
            nombre, slug,
            ciudad=(body.get("ciudad") or "").strip(),
            direccion=(body.get("direccion") or "").strip(),
            nit=(body.get("nit") or "").strip(),
            telefono=(body.get("telefono") or "").strip(),
            con_datos_demo=bool(body.get("con_datos_demo", True)),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    mdb = get_sessionmaker(MASTER_DB)()
    try:
        provisioning.asignar_a_sede(mdb, int(cur["user_id"]), int(sede["id"]), "admin")
    finally:
        mdb.close()
    provisioning.sincronizar_usuarios_sede(int(sede["id"]), sede["db_name"])
    invalidar_cache_sedes()
    auditar("crear_sede", "sede", sede["id"], slug, cur, client_ip(request))
    return {"ok": True, "sede": serial(dict(sede))[0]}


@router.get("/api/accesos/auditoria")
def auditoria(limite: int = 100, cur: dict = Depends(require_rol("admin")),
              mdb: Session = Depends(get_master_db)):
    limite = max(1, min(int(limite or 100), 500))   # cota dura: evita volcar la tabla
    filas = q(mdb, "SELECT * FROM audit_log WHERE tenant_id = :t "
                   "ORDER BY id DESC LIMIT :l",
              {"t": cur["tenant_id"], "l": limite})
    return {"ok": True, "items": serial(filas)}
