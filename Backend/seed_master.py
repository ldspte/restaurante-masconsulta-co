# -*- coding: utf-8 -*-
"""
================================================================
  RESTAURANTE · DDL y semilla de la base MAESTRA  (MySQL)
================================================================
La base maestra es el directorio del sistema: qué sedes existen, quién puede
entrar y a cuáles. NO contiene datos operativos —ventas, inventario, nómina—:
esos viven en la base de cada sede.

Esa separación es la que hace escalable el modelo. Una sede nueva no toca
tablas compartidas: se le crea su propia base. El crecimiento es horizontal.

Los índices se declaran DENTRO del CREATE TABLE. MySQL no admite
`CREATE INDEX IF NOT EXISTS`, así que declararlos aparte obligaría a consultar
information_schema antes de cada uno; dentro de la tabla, el
`CREATE TABLE IF NOT EXISTS` ya garantiza la idempotencia.

Autor: Arquitectura de Software · Unidad 1
================================================================
"""

TABLAS = [
    # ── Sedes (tenants) ──────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS tenants (
        id            INT AUTO_INCREMENT PRIMARY KEY,
        nombre        VARCHAR(160) NOT NULL,
        slug          VARCHAR(48)  NOT NULL,
        db_name       VARCHAR(64)  NOT NULL,
        nit           VARCHAR(32),
        direccion     VARCHAR(200),
        ciudad        VARCHAR(120),
        telefono      VARCHAR(40),
        moneda        VARCHAR(8)   NOT NULL DEFAULT 'COP',
        iva_pct       DECIMAL(6,2) NOT NULL DEFAULT 8.00,
        propina_pct   DECIMAL(6,2) NOT NULL DEFAULT 10.00,
        plan          VARCHAR(24)  NOT NULL DEFAULT 'basico',
        activo        TINYINT      NOT NULL DEFAULT 1,
        creado_en     VARCHAR(32),
        UNIQUE KEY uq_tenant_slug (slug),
        KEY ix_tenant_activo (activo)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,

    # ── Usuarios globales (una identidad puede operar en varias sedes) ────
    """
    CREATE TABLE IF NOT EXISTS usuarios_globales (
        id            INT AUTO_INCREMENT PRIMARY KEY,
        nombre        VARCHAR(160) NOT NULL,
        email         VARCHAR(160) NOT NULL,
        pass_hash     VARCHAR(255) NOT NULL,
        es_superadmin TINYINT      NOT NULL DEFAULT 0,
        token_version INT          NOT NULL DEFAULT 0,
        activo        TINYINT      NOT NULL DEFAULT 1,
        creado_en     VARCHAR(32),
        UNIQUE KEY uq_usuario_email (email)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,

    # ── Asignación usuario ↔ sede con rol ────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS usuario_tenant (
        id         INT AUTO_INCREMENT PRIMARY KEY,
        usuario_id INT NOT NULL,
        tenant_id  INT NOT NULL,
        rol        VARCHAR(24) NOT NULL DEFAULT 'mesero',
        activo     TINYINT NOT NULL DEFAULT 1,
        UNIQUE KEY uq_usuario_tenant (usuario_id, tenant_id),
        KEY ix_ut_tenant (tenant_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,

    # ── Bitácora de auditoría transversal ────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS audit_log (
        id         BIGINT AUTO_INCREMENT PRIMARY KEY,
        ts         VARCHAR(32),
        tenant_id  INT,
        usuario    VARCHAR(160),
        accion     VARCHAR(64),
        entidad    VARCHAR(64),
        entidad_id INT,
        detalle    TEXT,
        ip         VARCHAR(64),
        KEY ix_audit_ts (ts),
        KEY ix_audit_tenant (tenant_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
]

# ══════════════════ ROLES ══════════════════
# El rol es el eje de autorización. Se mantiene plano —sin permisos granulares
# por endpoint— porque un restaurante tiene perfiles reales bien definidos y un
# modelo ACL completo sería complejidad sin beneficio. El punto de extensión,
# si el negocio lo pide, es `require_rol`.
ROLES = [
    {"key": "admin",      "label": "Administrador",
     "desc": "Control total: configuración, nómina, contabilidad, sedes y usuarios."},
    {"key": "gerente",    "label": "Gerente de operación",
     "desc": "Opera el restaurante completo: salón, cocina, compras, personal y reportes."},
    {"key": "cajero",     "label": "Cajero",
     "desc": "Abre y cierra caja, cobra cuentas, factura y liquida propinas del turno."},
    {"key": "mesero",     "label": "Mesero",
     "desc": "Asigna mesas, toma comandas, envía a cocina y entrega los platos."},
    {"key": "cocina",     "label": "Cocina y producción",
     "desc": "Ve la cola de preparación por estación y ejecuta órdenes de producción."},
    {"key": "bodega",     "label": "Almacén y compras",
     "desc": "Recibe mercancía, ajusta inventario, gestiona proveedores y órdenes de compra."},
    {"key": "sst",        "label": "Responsable SG-SST",
     "desc": "Administra la matriz de peligros, el plan anual y los incidentes laborales."},
]

ROLES_VALIDOS = {r["key"] for r in ROLES}

# Matriz rol → módulos visibles. La consumen el frontend para armar el menú y el
# backend para el guard: una sola fuente de verdad en los dos lados evita el
# error clásico de ocultar un botón sin proteger su endpoint.
MODULOS_POR_ROL = {
    "admin":   ["dashboard", "salon", "comandas", "cocina", "caja", "facturacion",
                "productos", "produccion", "inventario", "compras", "perdidas",
                "consumo", "propinas", "rrhh", "sgsst", "contabilidad", "web", "accesos"],
    "gerente": ["dashboard", "salon", "comandas", "cocina", "caja", "facturacion",
                "productos", "produccion", "inventario", "compras", "perdidas",
                "consumo", "propinas", "rrhh", "sgsst", "contabilidad", "web"],
    "cajero":  ["dashboard", "salon", "comandas", "caja", "facturacion", "productos",
                "propinas"],
    "mesero":  ["salon", "comandas", "productos"],
    "cocina":  ["cocina", "produccion", "productos", "inventario"],
    "bodega":  ["dashboard", "inventario", "compras", "produccion", "perdidas",
                "consumo", "productos"],
    "sst":     ["dashboard", "sgsst", "rrhh"],
}
