# -*- coding: utf-8 -*-
"""
================================================================
  RESTAURANTE · SITIO PÚBLICO
================================================================
La cara que ve el cliente: carta, reservas en línea y reseñas.

ESTOS ENDPOINTS NO LLEVAN AUTENTICACIÓN — Y ESO EXIGE CUIDADO
-------------------------------------------------------------
Es el único módulo expuesto a internet abierto, así que cada endpoint aplica
tres defensas que los internos no necesitan:

  1. **Superficie mínima.** Solo se devuelve lo que el cliente debe ver. La
     carta pública NO expone costo, margen, existencias ni proveedor: eso es
     información competitiva y no tiene por qué salir del sistema.
  2. **Límite de tasa estricto.** Reservar y reseñar escriben en la base sin
     que nadie se identifique; sin tope, un script llena la agenda o el muro.
  3. **Moderación obligatoria.** Las reseñas nacen `pendiente`. Publicar
     automáticamente lo que escribe un desconocido convierte la página del
     negocio en un tablón abierto a insultos y spam.

La sede se resuelve por su código en la ruta —`/api/publico/{slug}/…`—, no por
token. Es lo que permite que cada local tenga su propia página.

Rutas
  GET  /api/publico/{slug}/info      datos, horarios y contacto
  GET  /api/publico/{slug}/carta     menú por categorías
  GET  /api/publico/{slug}/resenas   reseñas publicadas
  POST /api/publico/{slug}/reservas  reserva en línea
  POST /api/publico/{slug}/resenas   deja una reseña (queda pendiente)

Autor: Arquitectura de Software · Unidad 1
================================================================
"""
from __future__ import annotations

import collections
import logging
import re
import time

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from db import (MASTER_DB, ahora, get_sessionmaker, nombre_db_tenant, q, q1, run,
                run_sin_commit, serial)
import correo
from dependencias import get_tenant_db
from seguridad import autor, require_rol, verify_token

log = logging.getLogger("restaurante.publico")
router = APIRouter(tags=["Sitio público"])

_EMAIL_OK = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")

# Límite de tasa propio, mucho más estricto que el general de la aplicación.
# Escribir sin identificarse es la puerta natural del abuso.
_VENTANA = 3600
_TOPE = {"reserva": 5, "resena": 3, "consulta": 20}
_HIST: dict[str, collections.deque] = collections.defaultdict(collections.deque)


def _limitar(ip: str, accion: str) -> None:
    clave = f"{ip}:{accion}"
    ahora_s = time.time()
    cola = _HIST[clave]
    while cola and ahora_s - cola[0] > _VENTANA:
        cola.popleft()
    if len(cola) >= _TOPE.get(accion, 5):
        raise HTTPException(429, "Ha enviado varias solicitudes seguidas. "
                                 "Intente de nuevo en un rato, por favor.")
    cola.append(ahora_s)


def _ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() if fwd
            else (request.client.host if request.client else "desconocido"))


def _sede(slug: str) -> tuple[str, dict]:
    """Resuelve la sede por su código. Devuelve (nombre de base, tenant).

    El slug pasa por `nombre_db_tenant`, que valida contra lista blanca: es la
    única entrada de un usuario anónimo que toca una cadena de conexión.
    """
    try:
        nombre_db_tenant(slug)
    except ValueError:
        raise HTTPException(404, "Restaurante no encontrado")

    mdb = get_sessionmaker(MASTER_DB)()
    try:
        t = q1(mdb, "SELECT id, nombre, slug, db_name, ciudad FROM tenants "
                    "WHERE slug=:s AND activo=1", {"s": slug})
    finally:
        mdb.close()
    if not t:
        raise HTTPException(404, "Restaurante no encontrado")
    return t["db_name"], dict(t)


def _abrir(slug: str):
    db_name, tenant = _sede(slug)
    return get_sessionmaker(db_name)(), tenant


# ══════════════════════════════════════════════════════════════════════
#  INFORMACIÓN
# ══════════════════════════════════════════════════════════════════════
@router.get("/api/publico/{slug}/info")
def info(slug: str):
    db, tenant = _abrir(slug)
    try:
        perfil = q1(db, "SELECT * FROM sede_perfil WHERE id=1") or {}
        if not int(perfil.get("publicado") or 0):
            raise HTTPException(404, "Esta página no está publicada")

        calif = q1(db, "SELECT COUNT(*) AS n, AVG(calificacion) AS prom FROM resenas "
                       "WHERE estado='publicada'") or {}
        return {
            "ok": True,
            "sede": {"nombre": tenant["nombre"], "slug": tenant["slug"],
                     "ciudad": perfil.get("ciudad") or tenant.get("ciudad")},
            # Se devuelve solo lo publicable: nada de NIT, resolución ni aforo real.
            "perfil": {
                "titular": perfil.get("titular"), "lema": perfil.get("lema"),
                "descripcion": perfil.get("descripcion"),
                "direccion": perfil.get("direccion"), "ciudad": perfil.get("ciudad"),
                "telefono": perfil.get("telefono"), "whatsapp": perfil.get("whatsapp"),
                "email": perfil.get("email"), "instagram": perfil.get("instagram"),
                "facebook": perfil.get("facebook"), "mapa_url": perfil.get("mapa_url"),
                "horarios": perfil.get("horarios"),
                "acepta_reservas": int(perfil.get("acepta_reservas") or 0),
            },
            "calificacion": {
                "promedio": round(float(calif.get("prom") or 0), 1) if calif.get("prom") else None,
                "total": int(calif.get("n") or 0)},
        }
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════
#  CARTA
# ══════════════════════════════════════════════════════════════════════
@router.get("/api/publico/{slug}/carta")
def carta(slug: str):
    """Menú público agrupado por categoría.

    Se devuelven ÚNICAMENTE nombre, descripción y precio. Costo, margen,
    existencias y proveedor son información competitiva: no salen del sistema.
    """
    db, _ = _abrir(slug)
    try:
        filas = serial(q(db,
                         "SELECT p.id, p.nombre, p.emoji, p.precio, p.minutos_prep, "
                         "       COALESCE(cp.descripcion,'') AS descripcion, "
                         "       COALESCE(cp.destacado,0) AS destacado, "
                         "       COALESCE(c.nombre,'Otros') AS categoria, "
                         "       COALESCE(c.color,'#94a3b8') AS color, "
                         "       COALESCE(c.orden,99) AS orden_cat "
                         "FROM productos p "
                         "JOIN carta_publica cp ON cp.producto_id = p.id AND cp.visible = 1 "
                         "LEFT JOIN cat_categorias c ON c.id = p.categoria_id "
                         "WHERE p.activo = 1 "
                         "ORDER BY c.orden, cp.orden, p.nombre"))

        grupos: dict[str, dict] = {}
        for f in filas:
            g = grupos.setdefault(f["categoria"], {
                "categoria": f["categoria"], "color": f["color"],
                "orden": f["orden_cat"], "items": []})
            g["items"].append({"id": f["id"], "nombre": f["nombre"],
                               "emoji": f["emoji"], "precio": float(f["precio"] or 0),
                               "descripcion": f["descripcion"],
                               "destacado": int(f["destacado"] or 0),
                               "minutos": f["minutos_prep"]})

        secciones = sorted(grupos.values(), key=lambda x: x["orden"])
        destacados = [i for s in secciones for i in s["items"] if i["destacado"]]
        return {"ok": True, "secciones": secciones, "destacados": destacados,
                "total": len(filas)}
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════
#  RESERVAS
# ══════════════════════════════════════════════════════════════════════
@router.post("/api/publico/{slug}/reservas", status_code=201)
def reservar(slug: str, request: Request, body: dict = Body(...)):
    """Reserva en línea. Reutiliza la MISMA función que la pantalla interna.

    Compartirla no es economía de código: es lo que garantiza que el control de
    aforo y de choque de horario se aplique igual por los dos caminos. Una
    validación duplicada es una validación que se desincroniza.
    """
    from salon_router import crear_reserva

    _limitar(_ip(request), "reserva")
    db, _ = _abrir(slug)
    try:
        perfil = q1(db, "SELECT acepta_reservas FROM sede_perfil WHERE id=1") or {}
        if not int(perfil.get("acepta_reservas") or 0):
            raise HTTPException(409, "Este restaurante no recibe reservas en línea por ahora.")

        # OJO: no llamar `correo` a esta variable. Taparía al módulo `correo`
        # y la llamada a `correo.reserva_creada()` de más abajo fallaría con un
        # «'str' object has no attribute», que cuesta rastrear.
        email_cliente = (body.get("email") or "").strip()
        if email_cliente and not _EMAIL_OK.match(email_cliente):
            raise HTTPException(400, "El correo no tiene un formato válido")
        if not (body.get("telefono") or "").strip():
            raise HTTPException(400, "Déjenos un teléfono para confirmarle la reserva")

        creada = crear_reserva(db, body, origen="web", creado_por="sitio web")
        db.commit()
        perfil_correo = q1(db, "SELECT titular, telefono, direccion FROM sede_perfil "
                               "WHERE id=1") or {}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    # El correo va DESPUÉS del commit y fuera de la transacción. Si Resend
    # tarda o falla, la reserva ya está guardada y el cliente ve su código en
    # pantalla igual. `enviar()` nunca lanza, así que no hace falta envolverlo.
    correo_enviado = False
    if email_cliente:
        correo_enviado = bool(correo.reserva_creada(
            {**creada, "email": email_cliente, "nombre": body.get("nombre", "")},
            dict(perfil_correo)))
        if not correo_enviado:
            # No se le oculta al cliente. Decirle «le enviamos un correo»
            # cuando no salió es peor que no prometerlo: se queda esperando en
            # vez de anotar el código.
            log.warning("Reserva %s: el correo a %s NO salió · %s",
                        creada["codigo"], email_cliente, correo.ultimo_error())

    log.info("Reserva web en %s: %s para %s personas", slug, creada["codigo"],
             creada["personas"])
    # El mensaje dice la VERDAD sobre el correo. Prometer uno que no salió deja
    # al cliente esperando en vez de anotar el código, que es lo único que
    # necesita para volver a encontrar su reserva.
    if correo_enviado:
        cierre = (f"Le enviamos el detalle a {email_cliente}. Guarde el código: "
                  f"con él y su teléfono puede consultarla o cancelarla desde "
                  f"esta misma página.")
    else:
        cierre = ("Le confirmaremos por teléfono. ANOTE EL CÓDIGO: con él y su "
                  "teléfono puede consultarla o cancelarla desde esta misma "
                  "página.")

    return {"ok": True, "codigo": creada["codigo"],
            "mensaje": (f"¡Listo! Su reserva quedó con el código {creada['codigo']} para el "
                        f"{creada['fecha']} a las {creada['hora']}. {cierre}"),
            "correo_enviado": correo_enviado,
            "fecha": creada["fecha"], "hora": creada["hora"],
            "personas": creada["personas"]}


# ══════════════════════════════════════════════════════════════════════
#  RESEÑAS
# ══════════════════════════════════════════════════════════════════════
@router.get("/api/publico/{slug}/resenas")
def resenas(slug: str, limite: int = 20):
    db, _ = _abrir(slug)
    try:
        limite = max(1, min(int(limite or 20), 50))
        filas = serial(q(db, "SELECT nombre, calificacion, comentario, respuesta, creado_en "
                             "FROM resenas WHERE estado='publicada' "
                             "ORDER BY id DESC LIMIT :l", {"l": limite}))
        dist = q(db, "SELECT calificacion, COUNT(*) AS n FROM resenas "
                     "WHERE estado='publicada' GROUP BY calificacion")
        mapa = {int(d["calificacion"]): int(d["n"]) for d in dist}
        total = sum(mapa.values())
        prom = (sum(k * v for k, v in mapa.items()) / total) if total else None
        return {"ok": True, "items": filas,
                "resumen": {"total": total,
                            "promedio": round(prom, 1) if prom else None,
                            "distribucion": {str(i): mapa.get(i, 0) for i in range(5, 0, -1)}}}
    finally:
        db.close()


@router.post("/api/publico/{slug}/resenas", status_code=201)
def resena_crear(slug: str, request: Request, body: dict = Body(...)):
    """Recibe una reseña. Queda PENDIENTE de moderación, siempre."""
    _limitar(_ip(request), "resena")
    db, _ = _abrir(slug)
    try:
        nombre = (body.get("nombre") or "").strip()
        comentario = (body.get("comentario") or "").strip()
        try:
            calificacion = int(body.get("calificacion") or 0)
        except (TypeError, ValueError):
            calificacion = 0

        if not nombre:
            raise HTTPException(400, "Déjenos su nombre")
        if not 1 <= calificacion <= 5:
            raise HTTPException(400, "La calificación debe estar entre 1 y 5 estrellas")
        if len(comentario) < 10:
            raise HTTPException(400, "Cuéntenos un poco más sobre su experiencia")
        if len(comentario) > 1200:
            raise HTTPException(400, "El comentario es demasiado largo")

        email_cliente = (body.get("email") or "").strip()
        if email_cliente and not _EMAIL_OK.match(email_cliente):
            raise HTTPException(400, "El correo no tiene un formato válido")

        run(db, "INSERT INTO resenas (nombre, email, calificacion, comentario, estado, "
                "ip, creado_en) VALUES (:n,:e,:c,:co,'pendiente',:ip,:ts)",
            {"n": nombre[:160], "e": email_cliente[:160] or None, "c": calificacion,
             "co": comentario, "ip": _ip(request), "ts": ahora()})
    finally:
        db.close()

    return {"ok": True,
            "mensaje": "¡Gracias por escribirnos! Su reseña se publicará una vez la revisemos."}


# ══════════════════════════════════════════════════════════════════════
#  CONSULTAR Y CANCELAR LA PROPIA RESERVA
#
#  Sin esto, el código que recibe el cliente no sirve para nada y la única
#  forma de cancelar es llamar. Quien no llama deja la mesa bloqueada, y la
#  silla vacía de un sábado a las ocho es plata que no vuelve.
#
#  IDENTIFICACIÓN: código + teléfono, sin cuenta ni contraseña. Pedirle a
#  alguien que se registre para reservar en un restaurante de barrio es perder
#  la reserva. El código solo no basta —son seis caracteres y se pueden
#  probar—; el teléfono es el dato que solo tiene quien reservó.
# ══════════════════════════════════════════════════════════════════════
def _solo_digitos(t: str) -> str:
    return re.sub(r"\D", "", str(t or ""))


def _buscar_reserva(db, codigo: str, telefono: str) -> dict:
    """Halla la reserva o lanza el MISMO error para todos los casos.

    Distinguir «ese código no existe» de «ese teléfono no corresponde»
    permitiría averiguar qué códigos son válidos probando de a uno.
    """
    codigo = (codigo or "").strip().upper()
    tel = _solo_digitos(telefono)
    if not codigo or not tel:
        raise HTTPException(400, "Escriba el código de su reserva y el teléfono "
                                 "con el que la hizo.")

    r = q1(db, "SELECT * FROM reservas WHERE codigo = :c", {"c": codigo})
    if not r or _solo_digitos(r.get("telefono")) != tel:
        raise HTTPException(
            404, "No encontramos esa reserva. Revise el código y el teléfono, "
                 "o llámenos y con gusto lo verificamos.")
    return dict(r)


def _publica(r: dict) -> dict:
    """Solo lo que el cliente debe ver de su propia reserva.

    No se devuelve la mesa asignada ni las notas internas: la primera cambia
    hasta el último momento y las segundas pueden decir cosas del cliente que
    escribió el mesero.
    """
    return {"codigo": r["codigo"], "nombre": r["nombre"], "fecha": str(r["fecha"]),
            "hora": r["hora"], "personas": r["personas"], "estado": r["estado"]}


@router.post("/api/publico/{slug}/reservas/consultar")
def reserva_consultar(slug: str, request: Request, body: dict = Body(...)):
    _limitar(_ip(request), "consulta")
    db, _ = _abrir(slug)
    try:
        r = _buscar_reserva(db, body.get("codigo"), body.get("telefono"))
        salida = _publica(r)
        salida["cancelable"] = r["estado"] in ("pendiente", "confirmada")
        salida["mensaje"] = {
            "pendiente": "Su reserva está registrada. Le confirmaremos por teléfono.",
            "confirmada": "Su reserva está confirmada. ¡Lo esperamos!",
            "cancelada": "Esta reserva fue cancelada.",
            "sentada": "Esta reserva ya fue atendida.",
            "no_show": "Esta reserva figura como no presentada.",
        }.get(r["estado"], "Reserva registrada.")
        return {"ok": True, "reserva": salida}
    finally:
        db.close()


@router.post("/api/publico/{slug}/reservas/cancelar")
def reserva_cancelar(slug: str, request: Request, body: dict = Body(...)):
    """Cancela la reserva del propio cliente.

    Se libera la mesa si estaba apartada: dejarla reservada para alguien que
    ya avisó que no viene es exactamente el desperdicio que este endpoint
    existe para evitar.
    """
    _limitar(_ip(request), "consulta")
    db, _ = _abrir(slug)
    try:
        r = _buscar_reserva(db, body.get("codigo"), body.get("telefono"))

        if r["estado"] == "cancelada":
            return {"ok": True, "ya_estaba": True,
                    "mensaje": "Esa reserva ya estaba cancelada."}
        if r["estado"] not in ("pendiente", "confirmada"):
            raise HTTPException(
                409, "Esta reserva ya no se puede cancelar desde aquí. "
                     "Llámenos y lo resolvemos.")

        motivo = (body.get("motivo") or "").strip()[:200]
        nota = (r.get("notas") or "")
        nota = (nota + "\n" if nota else "") + (
            "Cancelada por el cliente desde la web el %s%s"
            % (ahora()[:16], (" · " + motivo) if motivo else ""))

        run(db, "UPDATE reservas SET estado='cancelada', notas=:n WHERE id=:i",
            {"n": nota, "i": r["id"]})
        # La mesa vuelve a estar disponible.
        if r.get("mesa_id"):
            run(db, "UPDATE mesas SET estado='libre' WHERE id=:m AND estado='reservada'",
                {"m": r["mesa_id"]})

        perfil_correo = q1(db, "SELECT titular, telefono FROM sede_perfil "
                               "WHERE id=1") or {}
        log.info("Reserva %s cancelada por el cliente", r["codigo"])
    finally:
        db.close()

    # Deja constancia. Importa por una razón concreta: si alguien cancelara una
    # reserva que no es suya, este correo es la única señal que tendría el
    # dueño legítimo.
    if r.get("email"):
        correo.reserva_cancelada({**r, "fecha": str(r["fecha"])}, dict(perfil_correo))

    return {"ok": True,
            "mensaje": ("Su reserva del %s a las %s quedó cancelada. "
                        "Gracias por avisarnos." % (r["fecha"], r["hora"]))}

# ══════════════════════════════════════════════════════════════════════
#  ADMINISTRACIÓN DEL SITIO  —  esta mitad SÍ pide autenticación
#
#  Vive en el mismo archivo que la parte pública a propósito: son las dos
#  caras del mismo dominio y separarlas obligaría a mantener sincronizadas
#  dos definiciones de qué es publicable. Lo que cambia es la puerta.
# ══════════════════════════════════════════════════════════════════════
ROLES_SITIO = ("admin", "gerente")


@router.get("/api/sitio/perfil")
def sitio_perfil(cur: dict = Depends(verify_token), db: Session = Depends(get_tenant_db)):
    p = q1(db, "SELECT * FROM sede_perfil WHERE id=1") or {}
    return {"ok": True, "perfil": serial([p])[0] if p else {}}


@router.put("/api/sitio/perfil")
def sitio_perfil_guardar(body: dict = Body(...),
                         cur: dict = Depends(require_rol(*ROLES_SITIO)),
                         db: Session = Depends(get_tenant_db)):
    """Guarda lo que el cliente ve.

    La lista de campos es blanca y explícita. Aceptar el cuerpo entero
    permitiría que un `publicado` o un `propina_pct` llegara desde el
    formulario del sitio web y cambiara algo que no es de este módulo.
    """
    campos = ("titular", "lema", "descripcion", "direccion", "ciudad", "telefono",
              "whatsapp", "email", "instagram", "facebook", "mapa_url", "horarios")
    sets, par = [], {}
    for c in campos:
        if c in body:
            sets.append(f"{c} = :{c}")
            par[c] = (str(body.get(c) or "").strip() or None)
    for c in ("acepta_reservas", "publicado"):
        if c in body:
            sets.append(f"{c} = :{c}")
            par[c] = 1 if body.get(c) else 0
    if "aforo_max" in body:
        sets.append("aforo_max = :aforo_max")
        par["aforo_max"] = max(int(body.get("aforo_max") or 0), 0)
    if not sets:
        raise HTTPException(400, "No hay nada que guardar")

    sets.append("actualizado_en = :ts")
    par["ts"] = ahora()
    run(db, f"UPDATE sede_perfil SET {', '.join(sets)} WHERE id=1", par)
    return {"ok": True, "mensaje": "Sitio actualizado."}


@router.get("/api/sitio/carta")
def sitio_carta(cur: dict = Depends(verify_token), db: Session = Depends(get_tenant_db)):
    """Todos los productos con su estado de publicación.

    Se listan también los NO publicados: la pregunta que trae a alguien a esta
    pantalla suele ser «¿por qué el brownie no sale en la carta?», y para
    responderla hay que poder verlo apagado.
    """
    filas = serial(q(db,
                     "SELECT p.id, p.codigo, p.nombre, p.precio, p.emoji, p.activo, "
                     "       COALESCE(c.nombre,'Otros') AS categoria, "
                     "       COALESCE(cp.visible,0) AS visible, "
                     "       COALESCE(cp.destacado,0) AS destacado, "
                     "       COALESCE(cp.descripcion,'') AS descripcion, "
                     "       COALESCE(cp.orden,0) AS orden "
                     "FROM productos p "
                     "LEFT JOIN carta_publica cp ON cp.producto_id = p.id "
                     "LEFT JOIN cat_categorias c ON c.id = p.categoria_id "
                     "ORDER BY c.orden, cp.orden, p.nombre"))
    return {"ok": True, "items": filas,
            "publicados": sum(1 for f in filas if f["visible"]),
            "destacados": sum(1 for f in filas if f["destacado"])}


@router.put("/api/sitio/carta/{producto_id}")
def sitio_carta_guardar(producto_id: int, body: dict = Body(...),
                        cur: dict = Depends(require_rol(*ROLES_SITIO)),
                        db: Session = Depends(get_tenant_db)):
    if not q1(db, "SELECT id FROM productos WHERE id=:i", {"i": producto_id}):
        raise HTTPException(404, "Producto no encontrado")
    run(db, "INSERT INTO carta_publica (producto_id, visible, destacado, descripcion, orden) "
            "VALUES (:p,:v,:d,:de,:o) "
            "ON DUPLICATE KEY UPDATE visible=:v, destacado=:d, descripcion=:de, orden=:o",
        {"p": producto_id,
         "v": 1 if body.get("visible") else 0,
         "d": 1 if body.get("destacado") else 0,
         "de": (str(body.get("descripcion") or "").strip()[:300] or None),
         "o": int(body.get("orden") or 0)})
    return {"ok": True, "mensaje": "Carta actualizada."}


@router.get("/api/sitio/resenas")
def sitio_resenas(estado: str = "", cur: dict = Depends(verify_token),
                  db: Session = Depends(get_tenant_db)):
    donde, par = "1=1", {}
    if estado:
        donde, par = "estado = :e", {"e": estado}
    filas = serial(q(db, f"SELECT * FROM resenas WHERE {donde} ORDER BY "
                     f"CASE estado WHEN 'pendiente' THEN 0 ELSE 1 END, id DESC LIMIT 200",
                     par))
    k = q1(db, "SELECT SUM(estado='pendiente') AS pend, SUM(estado='publicada') AS pub, "
               "SUM(estado='rechazada') AS rech, COUNT(*) AS total, "
               "AVG(CASE WHEN estado='publicada' THEN calificacion END) AS prom "
               "FROM resenas") or {}
    return {"ok": True, "items": filas,
            "kpis": {"pendientes": int(k.get("pend") or 0),
                     "publicadas": int(k.get("pub") or 0),
                     "rechazadas": int(k.get("rech") or 0),
                     "total": int(k.get("total") or 0),
                     "promedio": round(float(k["prom"]), 1) if k.get("prom") else None}}


@router.put("/api/sitio/resenas/{resena_id}")
def sitio_resena_moderar(resena_id: int, body: dict = Body(...),
                         cur: dict = Depends(require_rol(*ROLES_SITIO)),
                         db: Session = Depends(get_tenant_db)):
    """Publica, rechaza o responde una reseña.

    Responder en público a una crítica es la mejor herramienta que tiene un
    restaurante pequeño, y por eso la respuesta se guarda junto a la reseña
    en vez de en un correo que nadie más lee.
    """
    r = q1(db, "SELECT id FROM resenas WHERE id=:i", {"i": resena_id})
    if not r:
        raise HTTPException(404, "Reseña no encontrada")

    estado = (body.get("estado") or "").strip().lower()
    if estado and estado not in ("pendiente", "publicada", "rechazada"):
        raise HTTPException(400, "Estado inválido")

    respuesta = (body.get("respuesta") or "").strip()
    run(db, "UPDATE resenas SET estado = COALESCE(:e, estado), "
            "respuesta = COALESCE(:r, respuesta), "
            "respondida_por = CASE WHEN :r IS NULL THEN respondida_por ELSE :u END, "
            "moderado_en = :ts WHERE id = :i",
        {"e": estado or None, "r": respuesta[:1200] or None,
         "u": autor(cur), "ts": ahora(), "i": resena_id})
    return {"ok": True, "mensaje": "Reseña actualizada."}
