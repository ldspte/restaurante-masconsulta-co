# -*- coding: utf-8 -*-
"""
================================================================
  PUENTE PARA cPANEL  ·  restaurante.masconsulta.co
================================================================
cPanel ejecuta aplicaciones Python con **Passenger**, que habla WSGI.
FastAPI habla ASGI. `a2wsgi` traduce entre los dos.

CUIDADO: cPANEL SOBRESCRIBE ESTE ARCHIVO
----------------------------------------
Al crear la aplicacion, «Setup Python App» escribe su propio
`passenger_wsgi.py` con este contenido:

    import imp
    wsgi = imp.load_source('wsgi', 'passenger_wsgi.py')
    application = wsgi.application

Eso carga `passenger_wsgi.py` desde dentro de `passenger_wsgi.py`: se llama a
si mismo. Falla antes de definir `application`, y Passenger tapa el motivo con
su «Web application could not be started», que no dice nada. Ademas `imp` esta
eliminado desde Python 3.12.

**Si la aplicacion deja de arrancar de un dia para otro, lo primero que hay que
mirar es si este archivo sigue siendo este.** Se pierde cada vez que se recrea
la aplicacion desde el panel.

ESTRUCTURA
----------
Este archivo va en la RAIZ del subdominio, no dentro de Backend/:

    restaurante.masconsulta.co/
        passenger_wsgi.py     <- este archivo
        requirements.txt
        .htaccess
        Backend/    main.py, .env, data/...
        FrontEnd/   index.html, web/...

`main.py` resuelve el `.env` y el frontend a partir de la ubicacion del propio
archivo, no del directorio de trabajo. Por eso no hace falta `chdir` y por eso
aplanar las carpetas rompe el sitio: FrontEnd/ debe ser hermana de Backend/.

QUE HACER SI ALGO FALLA
-----------------------
El bloque de abajo devuelve el motivo EN TEXTO en el navegador, en lugar de un
500 mudo. Si aun asi aparece el mensaje generico de Passenger, es que este
archivo fue reemplazado por el de cPanel.
================================================================
"""
import os
import sys

# Ruta absoluta, igual que en el despliegue de NIGC que ya funciona en este
# mismo servidor. Se prefiere a deducirla de `__file__` porque Passenger puede
# invocar el archivo desde un directorio de trabajo distinto.
RAIZ_FIJA = "/home/hhii3aoach68/public_html/restaurante.masconsulta.co"
RAIZ = RAIZ_FIJA if os.path.isdir(RAIZ_FIJA) else os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(RAIZ, "Backend")

try:
    # Todas las comprobaciones van DENTRO del try. Si algo falla aqui fuera,
    # `application` no llega a existir y Passenger oculta la razon.
    if not os.path.isdir(BACKEND):
        raise RuntimeError(
            "No existe Backend/ junto a passenger_wsgi.py.\n"
            "Raiz usada: %s\nContenido: %s"
            % (RAIZ, ", ".join(sorted(os.listdir(RAIZ))[:30]) or "(vacio)"))

    if not os.path.isfile(os.path.join(BACKEND, "main.py")):
        raise RuntimeError("Backend/ existe pero le falta main.py.\nContenido: %s"
                           % ", ".join(sorted(os.listdir(BACKEND))[:30]))

    if not os.path.isfile(os.path.join(BACKEND, ".env")):
        raise RuntimeError(
            "Falta Backend/.env con las credenciales de MySQL.\n"
            "Renombre .env.produccion a .env y complete los valores.")

    sys.path.insert(0, BACKEND)
    os.environ.setdefault("RST_ENTORNO", "produccion")

    from main import app                # noqa: E402

    try:
        from a2wsgi import ASGIMiddleware   # noqa: E402
    except ImportError:
        # NO se cae al `application = app` que se ve en otros despliegues.
        # FastAPI habla ASGI y Passenger habla WSGI: entregarle la app sin
        # traducir produce otra vez el «could not be started» generico, y el
        # diagnostico apuntaria a las rutas cuando el problema es una
        # dependencia que falta. Mejor decirlo.
        raise RuntimeError(
            """Falta el paquete a2wsgi, que traduce de ASGI a WSGI.
Instalelo DENTRO del entorno virtual de la aplicacion:
    pip install -r Backend/requirements.txt""")

    application = ASGIMiddleware(app)

except BaseException as exc:            # pragma: no cover
    # BaseException, no Exception: un SystemExit durante el arranque tambien
    # dejaria a Passenger sin `application`, y este bloque existe justamente
    # para que el motivo nunca quede oculto.
    import traceback

    # El nombre del `except ... as exc` se BORRA al salir del bloque (PEP 3110).
    # La funcion de abajo corre despues, asi que buscarlo ahi lanzaba NameError
    # y Passenger volvia a tapar el motivo con su mensaje generico: el
    # manejador de errores se rompia justo cuando hacia falta. Se copian los
    # datos a variables propias ANTES de salir del bloque.
    _tipo = type(exc).__name__
    _mensaje = str(exc)
    _detalle = traceback.format_exc()

    def application(environ, start_response):
        cuerpo = (
            "La aplicacion no pudo arrancar.\n\n"
            "%s: %s\n\n"
            "Revisiones mas frecuentes:\n"
            "  1. pip install -r Backend/requirements.txt (en el entorno virtual)\n"
            "  2. Existe Backend/.env con las credenciales de MySQL\n"
            "  3. La base de datos y el usuario existen, y el usuario esta\n"
            "     ANADIDO a la base con todos los privilegios\n"
            "  4. La raiz de la aplicacion NO apunta a Backend/, sino un nivel arriba\n\n"
            "Detalle:\n%s"
        ) % (_tipo, _mensaje, _detalle)
        datos = cuerpo.encode("utf-8")
        start_response("500 Internal Server Error", [
            ("Content-Type", "text/plain; charset=utf-8"),
            ("Content-Length", str(len(datos))),
        ])
        return [datos]
