# -*- coding: utf-8 -*-
"""
Reclasifica el impuesto al consumo de la 2408 (IVA) a la 2413 (INC).

POR QUÉ
-------
El servicio de restaurante en Colombia no causa IVA: causa **impuesto nacional
al consumo al 8 %** (art. 512-1 y 512-9 E.T.). El sistema ya calculaba el 8 %
correcto, pero lo acreditaba en la 2408 —la cuenta del IVA— y lo llamaba «IVA»
en pantalla. Dos tributos distintos, dos formularios distintos: el INC va en el
310, no en el 300, y **no es descontable**.

Dejarlo así habría producido una declaración de IVA inflada con plata que nunca
fue IVA.

CÓMO
----
NO se editan los asientos ya publicados. Se registra un asiento de
RECLASIFICACIÓN que debita la 2408 y acredita la 2413 por el saldo acumulado,
igual que se hizo con el error #6. Un libro contable se corrige agregando, no
borrando: el rastro de lo que pasó tiene que quedar.

Es IDEMPOTENTE: si ya se corrió, no vuelve a reclasificar.

    python Backend/_migracion_inc_2413.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from db import get_sessionmaker, q1, run_sin_commit          # noqa: E402
from contabilidad_router import _registrar_asiento           # noqa: E402

CUENTA = ("2413", "Impuesto nacional al consumo por pagar", "pasivo", "credito")
MARCA = "Reclasificación IVA → impuesto al consumo"


def migrar(nombre_db: str) -> None:
    db = get_sessionmaker(nombre_db)()
    try:
        # 1 · La cuenta tiene que existir antes de usarla.
        if not q1(db, "SELECT codigo FROM puc WHERE codigo=:c", {"c": CUENTA[0]}):
            run_sin_commit(db, "INSERT INTO puc (codigo, nombre, tipo, naturaleza) "
                               "VALUES (:c,:n,:t,:na)",
                           {"c": CUENTA[0], "n": CUENTA[1], "t": CUENTA[2], "na": CUENTA[3]})
            print("  + cuenta %s creada" % CUENTA[0])
        else:
            print("  = cuenta %s ya existía" % CUENTA[0])

        # 2 · ¿Ya se reclasificó? No se hace dos veces.
        previo = q1(db, "SELECT id FROM asientos WHERE concepto LIKE :c LIMIT 1",
                    {"c": MARCA + "%"})
        if previo:
            print("  = ya estaba reclasificado (asiento %s). Nada que hacer." % previo["id"])
            db.commit()
            return

        # 3 · Saldo acumulado en la 2408 que en realidad es INC.
        fila = q1(db, "SELECT COALESCE(SUM(credito),0)-COALESCE(SUM(debito),0) AS saldo "
                      "FROM asiento_lineas WHERE cuenta='2408'") or {}
        saldo = round(float(fila.get("saldo") or 0), 2)
        if saldo <= 0:
            print("  = la 2408 no tiene saldo por reclasificar (%.2f)" % saldo)
            db.commit()
            return

        _registrar_asiento(
            db, tipo="reclasificacion",
            concepto="%s · art. 512-1 E.T." % MARCA,
            lineas=[{"cuenta": "2408", "debito": saldo, "credito": 0},
                    {"cuenta": "2413", "debito": 0, "credito": saldo}],
            usuario="migracion")
        db.commit()
        print("  > reclasificados $%s de 2408 a 2413" % f"{saldo:,.0f}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    prefijo = os.getenv("RST_TENANT_PREFIX", "rst_")
    objetivo = sys.argv[1] if len(sys.argv) > 1 else prefijo + "central"
    print("Base: %s" % objetivo)
    migrar(objetivo)
    print("Listo.")
