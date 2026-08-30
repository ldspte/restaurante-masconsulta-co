# -*- coding: utf-8 -*-
"""
================================================================
  INSTALADOR / ACTUALIZADOR  ·  se puede correr las veces que haga falta
================================================================
    python instalar.py

Qué hace:

  1. Comprueba que pueda conectarse a la base de datos y lo dice claro si no.
  2. Crea las tablas que falten (todo el DDL usa `CREATE TABLE IF NOT EXISTS`).
  3. Agrega las COLUMNAS nuevas que hayan aparecido desde la última versión.
  4. Siembra la sede inicial solo si todavía no existe.

Es IDEMPOTENTE: correrlo dos veces no duplica nada ni borra nada. Esa es la
condición para poder usarlo también al actualizar, y no solo al instalar.

POR QUÉ NO HAY «MIGRACIONES» NUMERADAS
--------------------------------------
Un sistema de migraciones versionadas (Alembic y compañía) es lo correcto
cuando varias personas cambian el esquema en paralelo. Aquí el esquema vive
completo en `seed_tenant.TABLAS` y las diferencias se resuelven comparando
contra `information_schema`. Es más simple y no puede desincronizarse del
código, porque LEE el código. Cuando el equipo crezca, se cambia.
================================================================
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
os.chdir(BASE_DIR)

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    print("  Falta python-dotenv:  pip install -r requirements.txt")
    sys.exit(1)


def titulo(t):
    print("\n" + "=" * 70)
    print("  " + t)
    print("=" * 70)


def paso(t):
    print("  · " + t)


# ══════════════════════════════════════════════════════════════════════
titulo("INSTALADOR · Sistema de Gestión del Restaurante")

# ── 1. Conexión ───────────────────────────────────────────────────────
try:
    from db import MASTER_DB, TENANT_PREFIX, probar_conexion
except Exception as e:
    print("\n  No se pudo cargar la configuración: %s" % e)
    sys.exit(1)

vivo, detalle = probar_conexion()
if not vivo:
    # Se muestra LO QUE SE LEYÓ del .env, no lo que debería decir. «Access
    # denied» sin más deja a quien instala adivinando entre un usuario mal
    # escrito, una contraseña con un espacio de sobra y un privilegio que
    # falta. La contraseña NUNCA se imprime: solo su longitud y si trae
    # espacios o comillas, que es lo que de verdad delata el problema.
    _u = os.getenv("RST_DB_USER", "")
    _p = os.getenv("RST_DB_PASS", "")
    _rarezas = []
    if _p != _p.strip():
        _rarezas.append("empieza o termina en ESPACIO")
    if len(_p) >= 2 and _p[0] == _p[-1] and _p[0] in "\"'":
        _rarezas.append("viene entre COMILLAS (quítelas)")
    if "#" in _p:
        _rarezas.append("contiene '#', que .env puede tomar como comentario")
    if not _p:
        _rarezas.append("está VACÍA")

    print("""
  NO HAY CONEXIÓN CON LA BASE DE DATOS

  %s

  ESTO ES LO QUE SE LEYÓ DE Backend/.env
    RST_DB_HOST    %r
    RST_DB_PORT    %r
    RST_DB_USER    %r
    RST_DB_PASS    %s caracteres%s
    RST_MASTER_DB  %r
    RST_TENANT_PREFIX %r

  «Access denied … using password: YES» quiere decir que el servidor SÍ
  recibió una contraseña y NO coincide. La base no es el problema: si no
  existiera, el error diría «Unknown database».

  QUÉ HACER, EN ESTE ORDEN
    1. Cambie la contraseña del usuario en cPanel → «Bases de datos MySQL»
       → «Usuarios actuales» → «Cambiar contraseña». Use solo letras y
       números: los signos se prestan a errores al copiarlos al .env.
    2. Escríbala en RST_DB_PASS SIN comillas y SIN espacios alrededor.
    3. Confirme que el usuario está AÑADIDO a las DOS bases con «Todos los
       privilegios». Crearlos por separado no basta.
""" % (detalle, os.getenv("RST_DB_HOST", ""), os.getenv("RST_DB_PORT", ""),
       _u, len(_p),
       (" ← " + "; ".join(_rarezas)) if _rarezas else "",
       os.getenv("RST_MASTER_DB", ""), os.getenv("RST_TENANT_PREFIX", "")))
    sys.exit(1)

paso("Conexión correcta · %s" % detalle)

# ── 2. Versión del motor ──────────────────────────────────────────────
from db import crear_base_si_no_existe, get_sessionmaker, q, q1, run  # noqa: E402

mdb = get_sessionmaker(MASTER_DB)()
try:
    v = q1(mdb, "SELECT VERSION() AS v")
    paso("Motor: %s" % v["v"])
finally:
    mdb.close()

# ── 3. Esquema ────────────────────────────────────────────────────────
titulo("ESQUEMA")

import seed_master   # noqa: E402
import seed_tenant   # noqa: E402

crear_base_si_no_existe(MASTER_DB)
mdb = get_sessionmaker(MASTER_DB)()
try:
    for ddl in seed_master.TABLAS:
        run(mdb, ddl)
    paso("Base maestra al día · %s tablas" % len(seed_master.TABLAS))
finally:
    mdb.close()


def columnas_de(db, base, tabla):
    return {r["c"] for r in q(db,
                              "SELECT COLUMN_NAME AS c FROM information_schema.columns "
                              "WHERE table_schema=:e AND table_name=:t",
                              {"e": base, "t": tabla})}


def sincronizar_sede(db_name: str) -> None:
    """Crea las tablas que falten y agrega las columnas nuevas.

    El DDL declara las columnas dentro del `CREATE TABLE`, así que una tabla
    que ya existe NO recibe columnas nuevas por sí sola. Se comparan contra
    `information_schema` y se agregan una a una.
    """
    import re

    db = get_sessionmaker(db_name)()
    try:
        for ddl in seed_tenant.TABLAS:
            run(db, ddl)

        agregadas = 0
        for ddl in seed_tenant.TABLAS:
            m = re.search(r"CREATE TABLE IF NOT EXISTS (\w+)", ddl)
            if not m:
                continue
            tabla = m.group(1)
            existentes = columnas_de(db, db_name, tabla)
            if not existentes:
                continue
            cuerpo = ddl[ddl.index("(") + 1:ddl.rindex(")")]
            anterior = None
            for linea in cuerpo.split("\n"):
                linea = linea.strip().rstrip(",")
                if not linea or linea.startswith(("--", "KEY", "UNIQUE", "PRIMARY",
                                                  "CONSTRAINT", "INDEX", ")")):
                    continue
                partes = linea.split()
                if len(partes) < 2:
                    continue
                col, tipo = partes[0], " ".join(partes[1:])
                if col in existentes:
                    anterior = col
                    continue
                sufijo = (" AFTER %s" % anterior) if anterior else ""
                run(db, "ALTER TABLE %s ADD COLUMN %s %s%s" % (tabla, col, tipo, sufijo))
                print("      + %s.%s" % (tabla, col))
                agregadas += 1
                anterior = col
        if agregadas:
            paso("  %s columna(s) agregada(s)" % agregadas)
    finally:
        db.close()


mdb = get_sessionmaker(MASTER_DB)()
try:
    sedes = q(mdb, "SELECT slug, db_name, nombre FROM tenants WHERE activo=1")
finally:
    mdb.close()

if sedes:
    for s in sedes:
        paso("Sede «%s» (%s)" % (s["nombre"], s["db_name"]))
        sincronizar_sede(s["db_name"])
else:
    paso("No hay sedes todavía · se creará la inicial")

# ── 4. Sede inicial ───────────────────────────────────────────────────
if not sedes:
    titulo("SEDE INICIAL")
    import provisioning
    sede = provisioning.bootstrap()
    paso("Creada: %s · %s" % (sede["nombre"], sede["db_name"]))
    print("""
  USUARIOS CREADOS — cambie estas contraseñas HOY MISMO desde
  el módulo «Accesos». Están publicadas en el código.
""")
    for nombre, email, clave, rol, _sa, cargo, _sal in provisioning.DEMO:
        print("    %-9s %-26s %s" % (rol, email, clave))

# ── 5. Carpeta de anexos ──────────────────────────────────────────────
titulo("ARCHIVOS")
anexos = BASE_DIR / "data" / "anexos"
anexos.mkdir(parents=True, exist_ok=True)
paso("Carpeta de anexos lista: %s" % anexos)

guardia = anexos.parent / ".htaccess"
if not guardia.exists():
    guardia.write_text(
        "# Los anexos NO se sirven por URL: se entregan por un endpoint que\n"
        "# verifica que el archivo pertenezca a la sede de quien pregunta.\n"
        "Require all denied\n", encoding="utf-8")
    paso("Protección de la carpeta de datos instalada")

# ── 6. Clave de firma ─────────────────────────────────────────────────
titulo("REVISIÓN FINAL")
def _escribir_en_env(variable: str, valor: str) -> bool:
    """Deja `variable=valor` en Backend/.env, respetando el resto del archivo.

    Si la línea ya existe se reemplaza; si no, se añade al final. No se
    reescribe el archivo completo: llevaría por delante los comentarios y las
    demás credenciales.
    """
    ruta = BASE_DIR / ".env"
    try:
        lineas = ruta.read_text(encoding="utf-8").splitlines() if ruta.exists() else []
        nuevas, puesta = [], False
        for ln in lineas:
            if ln.strip().startswith(variable + "="):
                nuevas.append("%s=%s" % (variable, valor))
                puesta = True
            else:
                nuevas.append(ln)
        if not puesta:
            nuevas.append("%s=%s" % (variable, valor))
        salto = chr(10)   # se evita el escape para no depender del editor
        ruta.write_text(salto.join(nuevas) + salto, encoding="utf-8")
        return True
    except Exception as e:
        print("  No se pudo escribir en %s: %s" % (ruta, e))
        return False


# La clave de firma NO se pide: se genera.
#
# Antes esto era solo una advertencia con el comando para generarla a mano. Una
# advertencia que exige un paso aparte es exactamente donde la gente deja la
# clave vacía «por ahora» y el sistema sale a producción firmando tokens con
# una cadena predecible: cualquiera fabrica uno válido y entra como
# administrador. Generarla aquí quita esa decisión del camino.
clave = os.getenv("RST_SECRET_KEY", "")
if len(clave) < 32:
    import secrets

    nueva = secrets.token_urlsafe(48)
    if _escribir_en_env("RST_SECRET_KEY", nueva):
        os.environ["RST_SECRET_KEY"] = nueva
        paso("Clave de firma GENERADA y guardada en Backend/.env (%s caracteres)"
             % len(nueva))
        print("     No hay que copiarla a ningún lado. Si algún día la cambia,")
        print("     todas las sesiones abiertas se cierran: es lo esperado.")
    else:
        print("""
  ATENCIÓN · no se pudo escribir la clave de firma.

  Genere una así y péguela en `Backend/.env` como RST_SECRET_KEY:

      python -c "import secrets; print(secrets.token_urlsafe(48))"
""")
else:
    paso("Clave de firma correcta (%s caracteres)" % len(clave))

origenes = os.getenv("RST_CORS_ORIGINS", "")
if "localhost" in origenes or not origenes:
    print("""
  ATENCIÓN · `RST_CORS_ORIGINS` apunta a localhost o está vacío.
  En producción debe ser el dominio real, por ejemplo:

      RST_CORS_ORIGINS=https://restaurante.masconsulta.co
""")
else:
    paso("Orígenes permitidos: %s" % origenes)

print("""
======================================================================
  LISTO
======================================================================
  Abra el subdominio en el navegador.

    /            la carta del restaurante (lo que ve el cliente)
    /sistema     el sistema de gestión (el personal)

  Si algo falla, el navegador muestra el motivo: `passenger_wsgi.py`
  devuelve el error en texto en lugar de un 500 mudo.
""")
