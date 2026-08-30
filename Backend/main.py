# -*- coding: utf-8 -*-
"""
================================================================
  RESTAURANTE · Punto de entrada y composición del sistema
================================================================
Monolito modular: un solo proceso desplegable, dividido internamente en
módulos con frontera explícita. Este archivo es el ÚNICO lugar donde el
sistema se ensambla; los módulos no se conocen entre sí y no se importan salvo
por el contrato del bus de eventos.

POR QUÉ MONOLITO MODULAR Y NO MICROSERVICIOS
--------------------------------------------
Una cafetería con varias sedes maneja decenas de transacciones por hora, no
miles por segundo. Repartir seis módulos en seis servicios añadiría red,
despliegue independiente y consistencia eventual entre inventario y
contabilidad —problemas caros— para resolver una escala que no existe.

La decisión importante es que las FRONTERAS ya están trazadas: cada módulo es
un router con su propio esquema y se comunica por eventos, no por llamadas
directas. Si el volumen lo justificara, extraer un módulo a servicio propio es
mover un archivo y cambiar el transporte del bus (memoria → cola), no rediseñar
el sistema. Es la ventaja del monolito modular sobre el monolito a secas.

CADENA DE MIDDLEWARE (Chain of Responsibility)
----------------------------------------------
    petición → CORS → identificador de traza → límite de tasa → router
Cada eslabón puede atender, transformar o cortar. Ninguno conoce al siguiente.

Ejecución:
    python main.py            → http://127.0.0.1:8100

Autor: Arquitectura de Software · Unidad 1
================================================================
"""
from __future__ import annotations

import collections
import contextlib
import logging
import os
import sys
import time
import uuid
from pathlib import Path

from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# El directorio del backend debe estar en sys.path para que los módulos se
# importen igual tanto si se ejecuta `python main.py` como `uvicorn main:app`.
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# ── DOBLE ARRANQUE: la trampa más costosa de este montaje ────────────────
# Al ejecutar `python main.py`, este archivo se carga con el nombre «__main__».
# Cuando más abajo se llama a `uvicorn.run("main:app")`, Python busca un módulo
# llamado «main», NO lo encuentra en sys.modules (allí está como «__main__») y
# vuelve a ejecutar el archivo COMPLETO. El resultado son dos aplicaciones: los
# routers se montan dos veces y —lo verdaderamente grave— los suscriptores del
# bus quedan duplicados, de modo que cada venta descontaría el inventario dos
# veces y generaría asientos por partida doble repetidos.
#
# Registrar el alias hace que el segundo import encuentre el módulo ya cargado.
# En Windows el proceso hijo del recargador se llama «__mp_main__»; hay que
# cubrir ambos casos o el proceso que realmente atiende quedaría sin rutas.
if __name__ in ("__main__", "__mp_main__"):
    sys.modules["main"] = sys.modules[__name__]

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except Exception:
    pass

logging.basicConfig(
    level=os.getenv("RST_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-7s %(name)s · %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("restaurante")

import accesos_router          # noqa: E402
import comandas_router         # noqa: E402
import compras_router          # noqa: E402
import caja_router             # noqa: E402
import contabilidad_router     # noqa: E402
import dashboard_router        # noqa: E402
import escandallo             # noqa: E402
import facturacion_router      # noqa: E402
import inventario_router       # noqa: E402
import nomina_router          # noqa: E402
import personal_router         # noqa: E402
import perdidas_router         # noqa: E402
import produccion_router       # noqa: E402
import activos_router         # noqa: E402
import correo                 # noqa: E402
import anexos_router          # noqa: E402
import productos_router        # noqa: E402
import sobrantes_router       # noqa: E402
import publico_router         # noqa: E402
import salon_router            # noqa: E402
import sgsst_router            # noqa: E402
import provisioning            # noqa: E402
from eventos import mapa_suscriptores  # noqa: E402

FRONTEND_DIR = BASE_DIR.parent / "FrontEnd"


@contextlib.asynccontextmanager
async def ciclo_de_vida(_app: FastAPI):
    """Arranque y apagado del proceso.

    Aprovisiona la maestra y la sede de demostración. Es idempotente, así que
    puede correr en cada arranque. En producción este paso se movería a un
    trabajo de despliegue; se deja aquí porque el prototipo debe poder
    ejecutarse con un solo comando.
    """
    try:
        sede = provisioning.bootstrap()
        log.info("Sistema listo · sede «%s» (%s)", sede["nombre"], sede["db_name"])
        log.info("Usuarios de demostración:")
        for nombre, email, password, rol, _sa, cargo, _sal in provisioning.DEMO:
            log.info("   %-9s %-26s %-14s %s", rol, email, password, cargo)
    except Exception:
        log.exception("Falló el aprovisionamiento inicial")
        raise

    yield

    log.info("Cerrando conexiones…")


app = FastAPI(
    lifespan=ciclo_de_vida,
    title="Restaurante · Sistema de Gestión",
    description=(
        "Sistema de gestión para restaurantes: salón, cocina, producción propia, "
        "compras, caja, facturación electrónica, nómina y SG-SST. Monolito "
        "modular multi-tenant con bus de eventos de dominio."
    ),
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)


# ══════════════════════════════════════════════════════════════════════
#  MIDDLEWARE
# ══════════════════════════════════════════════════════════════════════
_ORIGENES = [o.strip() for o in os.getenv(
    "RST_CORS_ORIGINS", "http://localhost:8100,http://127.0.0.1:8100").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ORIGENES,
    allow_credentials=True,        # necesario para la cookie HttpOnly
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def traza(request: Request, call_next):
    """Asigna un identificador único a cada petición y mide su duración.

    Sin un identificador de correlación, un error reportado por el usuario es
    imposible de ubicar entre miles de líneas de registro. Se devuelve en la
    cabecera `X-Request-ID` para que el frontend pueda mostrarlo al fallar.
    """
    rid = uuid.uuid4().hex[:12]
    inicio = time.perf_counter()
    try:
        respuesta = await call_next(request)
    except Exception:
        log.exception("[%s] %s %s — excepción no controlada",
                      rid, request.method, request.url.path)
        raise
    ms = (time.perf_counter() - inicio) * 1000
    respuesta.headers["X-Request-ID"] = rid
    respuesta.headers["X-Response-Time-ms"] = f"{ms:.1f}"
    if ms > 800:
        # Umbral de alerta: en un POS, una petición de casi un segundo ya se
        # percibe como lentitud en el mostrador.
        log.warning("[%s] LENTO %.0f ms · %s %s", rid, ms, request.method, request.url.path)
    return respuesta


# ── Límite de tasa (patrón Throttling) ───────────────────────────────────
_VENTANA_SEG = 60
_MAX_PETICIONES = int(os.getenv("RST_RATE_LIMIT", "300"))
_MAX_LOGIN = int(os.getenv("RST_RATE_LIMIT_LOGIN", "10"))
_historial: dict[str, collections.deque] = collections.defaultdict(collections.deque)


@app.middleware("http")
async def limite_tasa(request: Request, call_next):
    """Ventana deslizante por IP.

    El login tiene un límite mucho más estricto que el resto: es el único
    endpoint donde un atacante gana algo repitiendo peticiones (fuerza bruta
    sobre contraseñas). Un límite uniforme obligaría a elegir entre proteger el
    login o dejar operar el POS, que sí hace muchas peticiones legítimas.
    """
    if not request.url.path.startswith("/api/"):
        return await call_next(request)

    ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
          or getattr(request.client, "host", "") or "desconocido")
    es_login = request.url.path == "/api/auth/login"
    clave = f"{ip}:login" if es_login else ip
    tope = _MAX_LOGIN if es_login else _MAX_PETICIONES

    ahora_s = time.time()
    cola = _historial[clave]
    while cola and ahora_s - cola[0] > _VENTANA_SEG:
        cola.popleft()

    if len(cola) >= tope:
        log.warning("Límite de tasa alcanzado por %s en %s", ip, request.url.path)
        return JSONResponse(
            status_code=429,
            content={"detail": "Demasiadas peticiones. Espere un momento e intente de nuevo."},
            headers={"Retry-After": str(_VENTANA_SEG)},
        )
    cola.append(ahora_s)
    return await call_next(request)


@app.middleware("http")
async def cabeceras_seguridad(request: Request, call_next):
    """Cabeceras de endurecimiento del navegador.

    La CSP prohíbe `unsafe-inline` en scripts, razón por la cual el frontend no
    usa atributos `onclick` sino delegación por `data-act`. La restricción de
    la arquitectura y la decisión del frontend son la misma decisión.
    """
    r = await call_next(request)
    r.headers.setdefault("X-Content-Type-Options", "nosniff")
    r.headers.setdefault("X-Frame-Options", "DENY")
    r.headers.setdefault("Referrer-Policy", "same-origin")
    r.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; "
        "frame-src https://www.google.com https://maps.google.com",
    )
    return r


# ══════════════════════════════════════════════════════════════════════
#  COMPOSICIÓN DE MÓDULOS
# ══════════════════════════════════════════════════════════════════════
MODULOS = [
    ("Accesos",      accesos_router.router),
    ("Anexos",       anexos_router.router),
    ("Sitio público", publico_router.router),
    ("Salón",        salon_router.router),
    ("Comandas",     comandas_router.router),
    ("Productos",    productos_router.router),
    ("Escandallo",   escandallo.router),
    ("Producción",   produccion_router.router),
    ("Inventario",   inventario_router.router),
    ("Compras",      compras_router.router),
    ("Caja",         caja_router.router),
    ("Facturación",  facturacion_router.router),
    ("Personal",     personal_router.router),
    ("Pérdidas",     perdidas_router.router),
    ("Sobrantes",    sobrantes_router.router),
    ("Maquinaria y equipo", activos_router.router),
    ("Nómina",       nomina_router.router),
    ("SG-SST",       sgsst_router.router),
    ("Contabilidad", contabilidad_router.router),
    ("Tablero",      dashboard_router.router),
]

for nombre, router in MODULOS:
    app.include_router(router)
    log.info("Módulo montado: %s", nombre)


def cablear_eventos() -> None:
    """Registra los suscriptores del bus.

    Se hace explícitamente aquí, y no como efecto secundario de importar cada
    módulo, para que el cableado del sistema sea legible en un solo sitio: quién
    reacciona a qué es una decisión arquitectónica, no un detalle escondido.
    """
    inventario_router.registrar_suscriptores()
    contabilidad_router.registrar_suscriptores()
    # Sobrantes va DESPUÉS de inventario: descuenta del pool lo que inventario
    # acaba de sacar de existencias. Al revés marcaría lotes por una venta que
    # todavía podría fallar al descontar.
    sobrantes_router.registrar_suscriptores()
    log.info("Bus de eventos cableado: %s", mapa_suscriptores())


cablear_eventos()


# ══════════════════════════════════════════════════════════════════════
#  SALUD Y DIAGNÓSTICO  (patrón Health Endpoint Monitoring)
# ══════════════════════════════════════════════════════════════════════
@app.get("/api/health", tags=["Salud"])
def health():
    """Sonda de vida. La consume el balanceador para decidir si esta instancia
    recibe tráfico; debe ser barata y no requerir autenticación."""
    from db import probar_conexion

    vivo, detalle = probar_conexion()
    bd = "ok" if vivo else f"error: {detalle}"
    if not vivo:
        log.error("Sonda de salud: MySQL inaccesible: %s", detalle)

    estado_ok = bd == "ok"
    return JSONResponse(
        status_code=200 if estado_ok else 503,
        content={"estado": "operativo" if estado_ok else "degradado",
                 "base_datos": bd, "motor": detalle if estado_ok else None,
                 "version": app.version,
                 # Permite responder «¿por qué no llegan los correos?» sin
                 # entrar al servidor a mirar el .env.
                 "correo": correo.backend_activo(),
                 "modulos": [n for n, _ in MODULOS]},
    )


# `require_rol` devuelve la dependencia; se construye aquí, no dentro de una
# función: envolverla en otra haría que FastAPI inyectara la función en lugar
# del usuario, y la ruta quedaría abierta sin que nada lo delatara.
from seguridad import require_rol as _require_rol   # noqa: E402

_ADMIN = _require_rol("admin", "gerente")


@app.get("/api/health/correo", tags=["Salud"])
def health_correo(cur: dict = Depends(_ADMIN)):
    """Qué transporte hay, con qué remitente y por qué falló el último envío.

    Va protegido: el remitente y el motivo del rechazo son datos de
    configuración, no información pública.
    """
    return {"ok": True,
            "transporte": correo.backend_activo(),
            "transportes": correo.transportes(),
            "remitente": correo.remitente(),
            "ultimo_error": correo.ultimo_error() or None,
            "sitio_url": correo.sitio_url()}


@app.post("/api/health/correo/prueba", tags=["Salud"])
def health_correo_prueba(body: dict = Body(...),
                         cur: dict = Depends(_ADMIN)):
    """Manda un correo de prueba y DEVUELVE EL MOTIVO si no sale.

    El fallo más común de Resend —remitente de un dominio sin verificar— se
    responde con un 403 que solo aparece en el registro del servidor. Sin esta
    ruta, averiguar por qué no llega un correo exige entrar por FTP a leer un
    log; con ella son diez segundos desde el navegador.
    """
    destino = (body.get("destino") or "").strip()
    if not destino:
        raise HTTPException(400, "Indique a qué dirección enviar la prueba")

    ok, motivo = correo.probar(destino)

    # No basta con que Resend acepte: acepta y despues puede rebotar. Se le
    # pregunta que paso de verdad. Un par de segundos de espera porque el
    # estado no es instantaneo; sin ellos siempre diria «sent».
    entrega = None
    if ok and correo.backend_activo() == "resend" and correo.ultimo_id():
        import time
        time.sleep(3)
        entrega = correo.estado_resend(correo.ultimo_id())

    return {"ok": ok, "detalle": motivo,
            "transporte": correo.backend_activo(),
            "remitente": correo.remitente(),
            "id_mensaje": correo.ultimo_id() or None,
            "entrega": entrega}


@app.get("/api/health/correo/estado/{id_mensaje}", tags=["Salud"])
def health_correo_estado(id_mensaje: str, cur: dict = Depends(_ADMIN)):
    """Qué pasó con un mensaje ya enviado. `delivered`, `bounced` o `sent`."""
    return correo.estado_resend(id_mensaje)


@app.get("/api/health/eventos", tags=["Salud"])
def health_eventos():
    """Introspección del bus: qué manejador escucha cada evento.

    En un sistema orientado a eventos la pregunta más frecuente al depurar es
    «¿quién está escuchando esto?». Responderla revisando imports es lento y
    poco fiable; el mapa vivo del bus no puede desactualizarse.
    """
    return {"ok": True, "suscriptores": mapa_suscriptores()}


# ══════════════════════════════════════════════════════════════════════
#  FRONTEND ESTÁTICO
# ══════════════════════════════════════════════════════════════════════
if FRONTEND_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    # ══════════════════════════════════════════════════════════════════
    #  CACHÉ · por qué el HTML NUNCA se cachea
    #
    #  Los archivos estáticos llevan `?v=` en su dirección y se cachean una
    #  semana: cambian de nombre cuando cambian, así que es seguro.
    #
    #  Pero el HTML es quien DICE qué versión pedir. Si el navegador se guarda
    #  el HTML, sigue pidiendo las versiones viejas y el `?v=` deja de servir
    #  para nada: se despliega una corrección y el usuario sigue viendo el
    #  error, sin forma de saber por qué. Pasó en producción.
    #
    #  `no-cache` no significa «no guardar»: significa «pregunta siempre si
    #  cambió». Con el ETag, la respuesta suele ser un 304 de unos pocos bytes.
    #  El costo es despreciable y elimina toda una clase de fallo fantasma.
    # ══════════════════════════════════════════════════════════════════
    SIN_CACHE = {"Cache-Control": "no-cache, must-revalidate"}

    @app.get("/", include_in_schema=False)
    @app.get("/web", include_in_schema=False)
    @app.get("/web/", include_in_schema=False)
    def sitio_publico():
        """LA RAÍZ ES LA CARA DEL RESTAURANTE.

        La dirección se le da a los clientes: quien la escriba espera la carta,
        no una caja de usuario y contraseña. El personal entra por `/sistema`.

        `/web` se mantiene como alias para no romper enlaces ya compartidos.
        """
        return FileResponse(str(FRONTEND_DIR / "web" / "index.html"),
                            headers=SIN_CACHE)

    @app.get("/sistema", include_in_schema=False)
    @app.get("/sistema/", include_in_schema=False)
    def sistema_interno():
        """Puerta de servicio: el sistema de gestión del personal."""
        return FileResponse(str(FRONTEND_DIR / "index.html"), headers=SIN_CACHE)

    @app.get("/{archivo:path}", include_in_schema=False)
    def estatico(archivo: str):
        """Sirve el frontend. Resuelve la ruta y verifica que quede DENTRO del
        directorio del frontend: sin esa comprobación, una petición con `../`
        leería archivos arbitrarios del servidor (path traversal)."""
        # Una ruta /api/… que llegue hasta aquí es un endpoint inexistente. Debe
        # responder 404 JSON: devolverle el index.html a una llamada de la API
        # produce el desconcertante «Unexpected token < in JSON» del cliente.
        if archivo.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": "Endpoint no encontrado"})

        destino = (FRONTEND_DIR / archivo).resolve()
        try:
            destino.relative_to(FRONTEND_DIR.resolve())
        except ValueError:
            return JSONResponse(status_code=403, content={"detail": "Ruta no permitida"})
        if destino.is_file():
            return FileResponse(str(destino))
        # Ruta desconocida: se devuelve el index que corresponda. Dentro de
        # `/sistema` manda la aplicación interna; fuera, la del restaurante.
        # Devolver siempre el interno le mostraría la pantalla de ingreso a un
        # cliente que escribió mal una dirección.
        if archivo.split("/")[0] == "sistema":
            return FileResponse(str(FRONTEND_DIR / "index.html"), headers=SIN_CACHE)
        return FileResponse(str(FRONTEND_DIR / "web" / "index.html"),
                            headers=SIN_CACHE)


# ══════════════════════════════════════════════════════════════════════
#  ARRANQUE
# ══════════════════════════════════════════════════════════════════════
def _puerto_ocupado(host: str, puerto: int) -> bool:
    """¿Hay algo escuchando ya en ese puerto?

    Se comprueba ANTES de arrancar. Sin esto, uvicorn ejecuta todo el
    aprovisionamiento, imprime las credenciales de demostración, falla al
    reservar el socket con un «[Errno 10048] … solo se permite un uso de cada
    dirección de socket» y se apaga. El usuario ve un arranque aparentemente
    correcto seguido de un cierre inmediato y concluye que el sistema se cae,
    cuando lo único que ocurre es que ya tenía otra instancia abierta.
    """
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.6)
        return s.connect_ex((host, puerto)) == 0


if __name__ == "__main__":
    import uvicorn

    _host = os.getenv("RST_HOST", "127.0.0.1")
    _puerto = int(os.getenv("RST_PORT", "8100"))

    if _puerto_ocupado(_host, _puerto):
        print()
        print("=" * 70)
        print(f"  EL PUERTO {_puerto} YA ESTA EN USO")
        print("=" * 70)
        print()
        print("  No es un fallo del sistema: ya hay una instancia escuchando ahi.")
        print()
        print(f"  Si es la suya, el sistema YA ESTA FUNCIONANDO. Abra:")
        print(f"      http://{_host}:{_puerto}")
        print()
        print("  Si quedo colgada de un arranque anterior, cierrela con:")
        print(f'      powershell "Get-NetTCPConnection -LocalPort {_puerto} -State Listen |'
              ' ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }"')
        print()
        print("  O levante esta en otro puerto:")
        print(f"      set RST_PORT=8101 && python main.py")
        print()
        raise SystemExit(1)

    uvicorn.run("main:app", host=_host, port=_puerto,
                reload=bool(os.getenv("RST_RELOAD")))
