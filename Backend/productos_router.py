# -*- coding: utf-8 -*-
"""
================================================================
  CAFETERÍA · Módulo PRODUCTOS
================================================================
Catálogo de venta y su RECETA: qué insumos y en qué cantidad consume cada
producto. La receta es la bisagra entre este módulo y el de Inventario; sin
ella, vender no podría descontar existencias y el costo de ventas sería una
cifra inventada.

Rutas
  GET    /api/productos/catalogos       categorías, unidades e insumos
  GET    /api/productos                 listado con costo y margen calculados
  POST   /api/productos                 alta
  PUT    /api/productos/{id}            edición
  DELETE /api/productos/{id}            baja lógica
  GET    /api/productos/{id}/receta     receta detallada
  PUT    /api/productos/{id}/receta     reemplaza la receta completa
  POST   /api/productos/categorias      catálogo extensible («➕ Otra…»)

Autor: Arquitectura de Software · Unidad 1
================================================================
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from db import ahora, q, q1, run, serial
from dependencias import get_tenant_db
from seguridad import require_rol, verify_token

router = APIRouter(tags=["Productos"])


# ── Cálculo de costo desde la receta ─────────────────────────────────────
def costo_producto(db: Session, producto_id: int) -> float:
    """Costo de un producto = Σ (cantidad de insumo × costo promedio del insumo).

    Se calcula al vuelo y no se guarda: si se almacenara, quedaría obsoleto en
    cuanto cambiara el precio de un insumo, y nadie recordaría recalcularlo.
    El costo de una venta ya ocurrida sí se congela en `ventas.costo`, porque
    ahí representa un hecho histórico y no debe moverse.
    """
    fila = q1(db,
              "SELECT COALESCE(SUM(r.cantidad * i.costo_prom), 0) AS costo "
              "FROM receta r JOIN insumos i ON i.id = r.insumo_id "
              "WHERE r.producto_id = :p", {"p": producto_id})
    return round(float((fila or {}).get("costo") or 0), 2)


def costos_todos(db: Session) -> dict[int, float]:
    """Igual que `costo_producto` pero para todo el catálogo en UNA consulta.

    Calcular producto por producto dentro del listado sería el problema N+1:
    con 80 productos serían 81 consultas por cada apertura de la pantalla.
    """
    filas = q(db,
              "SELECT r.producto_id AS pid, "
              "       COALESCE(SUM(r.cantidad * i.costo_prom), 0) AS costo "
              "FROM receta r JOIN insumos i ON i.id = r.insumo_id "
              "GROUP BY r.producto_id")
    return {int(f["pid"]): round(float(f["costo"] or 0), 2) for f in filas}


# ══════════════════════════════════════════════════════════════════════
#  CATÁLOGOS
# ══════════════════════════════════════════════════════════════════════
@router.get("/api/productos/catalogos")
def catalogos(cur: dict = Depends(verify_token), db: Session = Depends(get_tenant_db)):
    return {
        "ok": True,
        "categorias": serial(q(db, "SELECT id, nombre, color FROM cat_categorias "
                                   "WHERE activo=1 ORDER BY orden, nombre")),
        "unidades": serial(q(db, "SELECT id, nombre FROM cat_unidades "
                                 "WHERE activo=1 ORDER BY nombre")),
        "insumos": serial(q(db, "SELECT i.id, i.codigo, i.nombre, i.costo_prom, i.stock, "
                                "       COALESCE(u.nombre,'') AS unidad "
                                "FROM insumos i LEFT JOIN cat_unidades u ON u.id = i.unidad_id "
                                "WHERE i.activo=1 ORDER BY i.nombre")),
    }


@router.post("/api/productos/categorias", status_code=201)
def categoria_crear(body: dict = Body(...),
                    cur: dict = Depends(require_rol("admin", "supervisor")),
                    db: Session = Depends(get_tenant_db)):
    """Alta de categoría desde la opción «➕ Otra…» del desplegable.

    REGLA DE DISEÑO: ningún desplegable del sistema tiene opciones cerradas.
    Una taxonomía fija en el código se rompe apenas el sistema se instala en
    otro negocio o en otro país; el usuario debe poder ampliarla sin esperar
    una nueva versión del software.
    """
    nombre = (body.get("nombre") or "").strip()
    if not nombre:
        raise HTTPException(400, "El nombre de la categoría es obligatorio")
    existente = q1(db, "SELECT id FROM cat_categorias WHERE LOWER(nombre)=LOWER(:n)",
                   {"n": nombre})
    if existente:
        # Reactivar en vez de fallar: si el usuario la había desactivado, lo
        # que quiere ahora es tenerla de vuelta, no un mensaje de error.
        run(db, "UPDATE cat_categorias SET activo=1 WHERE id=:i", {"i": existente["id"]})
        return {"ok": True, "id": existente["id"], "reactivada": True}
    res = run(db, "INSERT INTO cat_categorias (nombre, color, orden, activo) "
                  "VALUES (:n, :c, 99, 1)",
              {"n": nombre, "c": (body.get("color") or "#6366f1")})
    return {"ok": True, "id": getattr(res, "lastrowid", 0)}


# ══════════════════════════════════════════════════════════════════════
#  PRODUCTOS
# ══════════════════════════════════════════════════════════════════════
@router.get("/api/productos")
def listar(incluir_inactivos: int = 0, cur: dict = Depends(verify_token),
           db: Session = Depends(get_tenant_db)):
    where = "" if incluir_inactivos else "WHERE p.activo = 1"
    filas = serial(q(db,
                     "SELECT p.*, COALESCE(c.nombre,'Sin categoría') AS categoria, "
                     "       COALESCE(c.color,'#94a3b8') AS color "
                     "FROM productos p LEFT JOIN cat_categorias c ON c.id = p.categoria_id "
                     f"{where} ORDER BY c.orden, p.nombre"))
    costos = costos_todos(db)
    recetas = {int(f["pid"]): int(f["n"]) for f in
               q(db, "SELECT producto_id AS pid, COUNT(*) AS n FROM receta GROUP BY producto_id")}

    for p in filas:
        costo = costos.get(int(p["id"]), 0.0)
        precio = float(p.get("precio") or 0)
        p["costo"] = costo
        p["margen"] = round(precio - costo, 2)
        # El margen porcentual sobre precio 0 no está definido: devolver None es
        # honesto; devolver 0 haría creer que el producto no deja utilidad.
        p["margen_pct"] = round((precio - costo) / precio * 100, 1) if precio else None
        p["items_receta"] = recetas.get(int(p["id"]), 0)

    return {"ok": True, "items": filas,
            "kpis": {"total": len(filas),
                     "sin_receta": sum(1 for p in filas if not p["items_receta"]),
                     "margen_promedio": round(
                         sum(p["margen_pct"] or 0 for p in filas) / len(filas), 1) if filas else 0}}


_CAMPOS = ("codigo", "nombre", "categoria_id", "precio", "iva_pct", "emoji", "activo")


@router.post("/api/productos", status_code=201)
def crear(body: dict = Body(...),
          cur: dict = Depends(require_rol("admin", "supervisor")),
          db: Session = Depends(get_tenant_db)):
    nombre = (body.get("nombre") or "").strip()
    if not nombre:
        raise HTTPException(400, "El nombre del producto es obligatorio")
    precio = float(body.get("precio") or 0)
    if precio < 0:
        raise HTTPException(400, "El precio no puede ser negativo")

    codigo = (body.get("codigo") or "").strip() or _siguiente_codigo(db)
    if q1(db, "SELECT id FROM productos WHERE codigo = :c", {"c": codigo}):
        raise HTTPException(409, f"Ya existe un producto con el código {codigo}")

    res = run(db,
              "INSERT INTO productos (codigo, nombre, categoria_id, precio, iva_pct, "
              "emoji, activo, creado_en) VALUES (:c,:n,:ca,:p,:iva,:e,1,:ts)",
              {"c": codigo, "n": nombre, "ca": body.get("categoria_id") or None,
               "p": precio, "iva": float(body.get("iva_pct") or 8.0),
               "e": (body.get("emoji") or "")[:8], "ts": ahora()})
    pid = int(getattr(res, "lastrowid", 0) or 0)

    if body.get("receta"):
        _guardar_receta(db, pid, body["receta"])
    return {"ok": True, "id": pid, "codigo": codigo}


@router.put("/api/productos/{pid}")
def editar(pid: int, body: dict = Body(...),
           cur: dict = Depends(require_rol("admin", "supervisor")),
           db: Session = Depends(get_tenant_db)):
    if not q1(db, "SELECT id FROM productos WHERE id = :i", {"i": pid}):
        raise HTTPException(404, "Producto no encontrado")
    if "precio" in body and float(body["precio"] or 0) < 0:
        raise HTTPException(400, "El precio no puede ser negativo")
    if "codigo" in body:
        dup = q1(db, "SELECT id FROM productos WHERE codigo=:c AND id<>:i",
                 {"c": body["codigo"], "i": pid})
        if dup:
            raise HTTPException(409, "Ese código ya está en uso por otro producto")

    sets, params = [], {"i": pid}
    for campo in _CAMPOS:
        if campo in body:
            sets.append(f"{campo} = :{campo}")
            params[campo] = body[campo]
    if sets:
        run(db, f"UPDATE productos SET {', '.join(sets)} WHERE id = :i", params)
    if "receta" in body:
        _guardar_receta(db, pid, body["receta"])
    return {"ok": True}


@router.delete("/api/productos/{pid}")
def eliminar(pid: int, cur: dict = Depends(require_rol("admin", "supervisor")),
             db: Session = Depends(get_tenant_db)):
    """Baja LÓGICA. Un producto vendido está referenciado por `venta_items`;
    borrarlo físicamente dejaría ventas históricas sin nombre de producto y
    rompería cualquier reporte hacia atrás."""
    if not q1(db, "SELECT id FROM productos WHERE id = :i", {"i": pid}):
        raise HTTPException(404, "Producto no encontrado")
    run(db, "UPDATE productos SET activo = 0 WHERE id = :i", {"i": pid})
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════
#  RECETA
# ══════════════════════════════════════════════════════════════════════
@router.get("/api/productos/{pid}/receta")
def receta_ver(pid: int, cur: dict = Depends(verify_token),
               db: Session = Depends(get_tenant_db)):
    filas = serial(q(db,
                     "SELECT r.insumo_id, r.cantidad, i.codigo, i.nombre, i.costo_prom, "
                     "       i.stock, COALESCE(u.nombre,'') AS unidad, "
                     "       ROUND(r.cantidad * i.costo_prom, 2) AS costo_linea "
                     "FROM receta r JOIN insumos i ON i.id = r.insumo_id "
                     "LEFT JOIN cat_unidades u ON u.id = i.unidad_id "
                     "WHERE r.producto_id = :p ORDER BY i.nombre", {"p": pid}))
    return {"ok": True, "items": filas, "costo_total": costo_producto(db, pid)}


@router.put("/api/productos/{pid}/receta")
def receta_guardar(pid: int, body: dict = Body(...),
                   cur: dict = Depends(require_rol("admin", "supervisor")),
                   db: Session = Depends(get_tenant_db)):
    if not q1(db, "SELECT id FROM productos WHERE id = :i", {"i": pid}):
        raise HTTPException(404, "Producto no encontrado")
    _guardar_receta(db, pid, body.get("items") or [])
    return {"ok": True, "costo_total": costo_producto(db, pid)}


def _guardar_receta(db: Session, pid: int, items: list) -> None:
    """Reemplaza la receta completa (borrar + insertar).

    Se prefiere sobre un merge incremental porque la receta es pequeña y el
    reemplazo total es trivialmente correcto: no hay forma de dejar una línea
    huérfana que el usuario creyó haber borrado.
    """
    vistos: set[int] = set()
    limpios = []
    for it in items or []:
        iid = int(it.get("insumo_id") or 0)
        cant = float(it.get("cantidad") or 0)
        if not iid or cant <= 0:
            continue
        if iid in vistos:
            raise HTTPException(400, "La receta tiene el mismo insumo repetido")
        if not q1(db, "SELECT id FROM insumos WHERE id=:i AND activo=1", {"i": iid}):
            raise HTTPException(400, f"El insumo {iid} no existe o está inactivo")
        vistos.add(iid)
        limpios.append((iid, cant))

    run(db, "DELETE FROM receta WHERE producto_id = :p", {"p": pid})
    for iid, cant in limpios:
        run(db, "INSERT INTO receta (producto_id, insumo_id, cantidad) VALUES (:p,:i,:q)",
            {"p": pid, "i": iid, "q": cant})


def _siguiente_codigo(db: Session) -> str:
    fila = q1(db, "SELECT COUNT(*) AS n FROM productos")
    return "PRD-%03d" % (int((fila or {}).get("n") or 0) + 1)
