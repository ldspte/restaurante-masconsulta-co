# -*- coding: utf-8 -*-
"""
================================================================
  RESTAURANTE · DDL y semilla de la base de una SEDE  (MySQL)
================================================================
Todo el dato operativo de una sede vive aquí: carta, insumos, producción,
salón, comandas, caja, compras, propinas, nómina, SG-SST y contabilidad.

CONCENTRACIÓN DELIBERADA DEL DDL
--------------------------------
Ningún router crea tablas por su cuenta: todas se declaran en `TABLAS`. Así el
esquema completo se lee en un solo archivo. Es lo contrario de lo que hace NIGC
—donde 138 routers auto-reparan su propio esquema— y responde a una lección
concreta: la auto-reparación evita que una migración fallida rompa una sede,
pero a cambio nadie puede leer el esquema completo en ningún lado.

CONVENCIONES DE TIPOS
---------------------
  DECIMAL(14,2)  importes en pesos      DECIMAL acumula sin error; DOUBLE no,
  DECIMAL(14,4)  cantidades de receta   y un arqueo que difiere en centavos es
  DECIMAL(6,2)   porcentajes            indistinguible de un faltante real.
  VARCHAR(32)    marcas de tiempo UTC en ISO-8601

Los índices van DENTRO del CREATE TABLE: MySQL no admite
`CREATE INDEX IF NOT EXISTS`.

Autor: Arquitectura de Software · Unidad 1
================================================================
"""

_ENG = "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"

TABLAS = [
    # ══════════════════════════════════════════════════════════════════
    #  BASE
    # ══════════════════════════════════════════════════════════════════
    f"""
    CREATE TABLE IF NOT EXISTS usuarios (
        id     INT PRIMARY KEY,
        nombre VARCHAR(160) NOT NULL,
        email  VARCHAR(160),
        rol    VARCHAR(24)  NOT NULL DEFAULT 'mesero',
        activo TINYINT      NOT NULL DEFAULT 1
    ) {_ENG}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS consecutivos (
        tipo   VARCHAR(24) NOT NULL,
        anio   INT         NOT NULL,
        ultimo INT         NOT NULL DEFAULT 0,
        PRIMARY KEY (tipo, anio)
    ) {_ENG}
    """,
    # Bitácora de eventos de dominio: el registro de por qué el inventario y la
    # contabilidad quedaron como quedaron.
    f"""
    CREATE TABLE IF NOT EXISTS eventos (
        id         BIGINT AUTO_INCREMENT PRIMARY KEY,
        ts         VARCHAR(32) NOT NULL,
        tipo       VARCHAR(48) NOT NULL,
        entidad    VARCHAR(32),
        entidad_id INT,
        payload    JSON,
        usuario    VARCHAR(160),
        estado     VARCHAR(16) NOT NULL DEFAULT 'ok',
        error      TEXT,
        KEY ix_eventos_ts (ts),
        KEY ix_eventos_tipo (tipo)
    ) {_ENG}
    """,

    # ══════════════════════════════════════════════════════════════════
    #  CATÁLOGOS EXTENSIBLES
    #  REGLA: ningún desplegable tiene opciones fijas en código. Todos leen
    #  de una tabla y ofrecen «➕ Otra…». Una taxonomía quemada se rompe en
    #  cuanto el sistema se instala en otro negocio o en otro país.
    # ══════════════════════════════════════════════════════════════════
    f"""
    CREATE TABLE IF NOT EXISTS cat_categorias (
        id     INT AUTO_INCREMENT PRIMARY KEY,
        nombre VARCHAR(120) NOT NULL,
        color  VARCHAR(16)  DEFAULT '#6366f1',
        orden  INT          DEFAULT 0,
        activo TINYINT      NOT NULL DEFAULT 1,
        UNIQUE KEY uq_categoria (nombre)
    ) {_ENG}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS cat_unidades (
        id     INT AUTO_INCREMENT PRIMARY KEY,
        nombre VARCHAR(60) NOT NULL,
        activo TINYINT     NOT NULL DEFAULT 1,
        UNIQUE KEY uq_unidad (nombre)
    ) {_ENG}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS cat_metodos_pago (
        id          INT AUTO_INCREMENT PRIMARY KEY,
        nombre      VARCHAR(60) NOT NULL,
        cuenta_puc  VARCHAR(12) NOT NULL DEFAULT '1105',
        es_efectivo TINYINT     NOT NULL DEFAULT 0,
        codigo_dian VARCHAR(4)  NOT NULL DEFAULT '10',
        activo      TINYINT     NOT NULL DEFAULT 1,
        UNIQUE KEY uq_metodo (nombre)
    ) {_ENG}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS cat_motivos_perdida (
        id     INT AUTO_INCREMENT PRIMARY KEY,
        nombre VARCHAR(120) NOT NULL,
        activo TINYINT      NOT NULL DEFAULT 1,
        UNIQUE KEY uq_motivo (nombre)
    ) {_ENG}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS estaciones (
        id     INT AUTO_INCREMENT PRIMARY KEY,
        nombre VARCHAR(60) NOT NULL,
        color  VARCHAR(16) DEFAULT '#0ea5e9',
        icono  VARCHAR(8)  DEFAULT '',
        orden  INT         DEFAULT 0,
        activo TINYINT     NOT NULL DEFAULT 1,
        UNIQUE KEY uq_estacion (nombre)
    ) {_ENG}
    """,

    # ══════════════════════════════════════════════════════════════════
    #  CARTA E INVENTARIO
    # ══════════════════════════════════════════════════════════════════
    f"""
    CREATE TABLE IF NOT EXISTS productos (
        id           INT AUTO_INCREMENT PRIMARY KEY,
        codigo       VARCHAR(32)  NOT NULL,
        nombre       VARCHAR(160) NOT NULL,
        categoria_id INT,
        estacion_id  INT,
        precio       DECIMAL(14,2) NOT NULL DEFAULT 0,
        iva_pct      DECIMAL(6,2)  NOT NULL DEFAULT 8.00,
        minutos_prep INT           NOT NULL DEFAULT 5,
        emoji        VARCHAR(8)    DEFAULT '',
        activo       TINYINT       NOT NULL DEFAULT 1,
        creado_en    VARCHAR(32),
        UNIQUE KEY uq_producto_codigo (codigo),
        KEY ix_producto_cat (categoria_id),
        KEY ix_producto_est (estacion_id),
        CONSTRAINT fk_prod_cat FOREIGN KEY (categoria_id) REFERENCES cat_categorias(id),
        CONSTRAINT fk_prod_est FOREIGN KEY (estacion_id)  REFERENCES estaciones(id)
    ) {_ENG}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS insumos (
        id         INT AUTO_INCREMENT PRIMARY KEY,
        codigo     VARCHAR(32)  NOT NULL,
        nombre     VARCHAR(160) NOT NULL,
        unidad_id  INT,
        stock      DECIMAL(14,4) NOT NULL DEFAULT 0,
        stock_min  DECIMAL(14,4) NOT NULL DEFAULT 0,
        stock_max  DECIMAL(14,4) NOT NULL DEFAULT 0,
        costo_prom DECIMAL(14,4) NOT NULL DEFAULT 0,
        es_producido TINYINT     NOT NULL DEFAULT 0,
        -- Ficha de aprovechamiento. Va en el insumo y no en una tabla aparte
        -- porque es propiedad del alimento, no de un evento: el arroz cocido
        -- dura 24 horas siempre, no solo el día que sobra.
        apto_calentado  TINYINT   NOT NULL DEFAULT 0,
        vida_util_horas INT       NOT NULL DEFAULT 0,
        activo     TINYINT       NOT NULL DEFAULT 1,
        creado_en  VARCHAR(32),
        UNIQUE KEY uq_insumo_codigo (codigo),
        KEY ix_insumo_stock (stock, stock_min),
        CONSTRAINT fk_ins_uni FOREIGN KEY (unidad_id) REFERENCES cat_unidades(id)
    ) {_ENG}
    """,
    # Receta de VENTA: qué consume un producto al venderse.
    f"""
    CREATE TABLE IF NOT EXISTS receta (
        id          INT AUTO_INCREMENT PRIMARY KEY,
        producto_id INT NOT NULL,
        insumo_id   INT NOT NULL,
        cantidad    DECIMAL(14,4) NOT NULL DEFAULT 0,
        tipo        VARCHAR(12) NOT NULL DEFAULT 'primario',
        merma_pct   DECIMAL(6,2) NOT NULL DEFAULT 0,
        UNIQUE KEY uq_receta (producto_id, insumo_id),
        CONSTRAINT fk_rec_prod FOREIGN KEY (producto_id) REFERENCES productos(id) ON DELETE CASCADE,
        CONSTRAINT fk_rec_ins  FOREIGN KEY (insumo_id)   REFERENCES insumos(id)
    ) {_ENG}
    """,
    # Kardex. `saldo` guarda el stock RESULTANTE: sin ese campo no se puede
    # auditar el inventario hacia atrás en el tiempo.
    f"""
    CREATE TABLE IF NOT EXISTS inv_movimientos (
        id         BIGINT AUTO_INCREMENT PRIMARY KEY,
        ts         VARCHAR(32)   NOT NULL,
        insumo_id  INT           NOT NULL,
        tipo       VARCHAR(16)   NOT NULL,
        cantidad   DECIMAL(14,4) NOT NULL,
        costo_unit DECIMAL(14,4) NOT NULL DEFAULT 0,
        saldo      DECIMAL(14,4) NOT NULL DEFAULT 0,
        ref_tipo   VARCHAR(24),
        ref_id     INT,
        motivo     VARCHAR(240),
        usuario    VARCHAR(160),
        KEY ix_mov_insumo (insumo_id, ts),
        KEY ix_mov_ref (ref_tipo, ref_id),
        CONSTRAINT fk_mov_ins FOREIGN KEY (insumo_id) REFERENCES insumos(id)
    ) {_ENG}
    """,

    # Costos INDIRECTOS por plato: preparación, gas, energía, agua, empaque.
    # Sin ellos el costo de un producto es solo el de sus ingredientes, y el
    # margen sale inflado: un salmón que «cuesta» 4,70 en pescado cuesta 8,18
    # cuando se suman la mano de obra de preparación y los servicios. Esa
    # diferencia es la que decide si el plato deja utilidad o la consume.
    f"""
    CREATE TABLE IF NOT EXISTS producto_costos_ind (
        id          INT AUTO_INCREMENT PRIMARY KEY,
        producto_id INT NOT NULL,
        concepto    VARCHAR(80) NOT NULL,
        valor       DECIMAL(14,4) NOT NULL DEFAULT 0,
        orden       INT DEFAULT 0,
        UNIQUE KEY uq_pci (producto_id, concepto),
        CONSTRAINT fk_pci_prod FOREIGN KEY (producto_id) REFERENCES productos(id) ON DELETE CASCADE
    ) {_ENG}
    """,
    # Plantilla de conceptos indirectos, para no redigitarlos en cada plato.
    f"""
    CREATE TABLE IF NOT EXISTS cat_costos_ind (
        id       INT AUTO_INCREMENT PRIMARY KEY,
        nombre   VARCHAR(80) NOT NULL,
        valor_def DECIMAL(14,4) NOT NULL DEFAULT 0,
        orden    INT DEFAULT 0,
        activo   TINYINT NOT NULL DEFAULT 1,
        UNIQUE KEY uq_cci (nombre)
    ) {_ENG}
    """,

    # ══════════════════════════════════════════════════════════════════
    #  PRODUCCIÓN PROPIA
    #  El pan no se compra: se HACE. Eso obliga a un segundo tipo de receta.
    #    Harina + levadura ──(orden de producción)──▶ Pan ──(receta)──▶ Venta
    #  Sin este eslabón el pan tendría que darse de alta como compra ficticia
    #  y el costo de la panadería se perdería.
    # ══════════════════════════════════════════════════════════════════
    f"""
    CREATE TABLE IF NOT EXISTS fichas_produccion (
        id             INT AUTO_INCREMENT PRIMARY KEY,
        insumo_destino INT NOT NULL,
        nombre         VARCHAR(160) NOT NULL,
        estacion_id    INT,
        rendimiento    DECIMAL(14,4) NOT NULL DEFAULT 1,
        minutos        INT NOT NULL DEFAULT 30,
        instrucciones  TEXT,
        activo         TINYINT NOT NULL DEFAULT 1,
        KEY ix_ficha_est (estacion_id),
        CONSTRAINT fk_fic_ins FOREIGN KEY (insumo_destino) REFERENCES insumos(id),
        CONSTRAINT fk_fic_est FOREIGN KEY (estacion_id)    REFERENCES estaciones(id)
    ) {_ENG}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS ficha_ingredientes (
        id        INT AUTO_INCREMENT PRIMARY KEY,
        ficha_id  INT NOT NULL,
        insumo_id INT NOT NULL,
        cantidad  DECIMAL(14,4) NOT NULL DEFAULT 0,
        UNIQUE KEY uq_ficha_ing (ficha_id, insumo_id),
        CONSTRAINT fk_fing_fic FOREIGN KEY (ficha_id)  REFERENCES fichas_produccion(id) ON DELETE CASCADE,
        CONSTRAINT fk_fing_ins FOREIGN KEY (insumo_id) REFERENCES insumos(id)
    ) {_ENG}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS ordenes_produccion (
        id            INT AUTO_INCREMENT PRIMARY KEY,
        numero        VARCHAR(24) NOT NULL,
        ficha_id      INT NOT NULL,
        lotes         DECIMAL(14,4) NOT NULL DEFAULT 1,
        cantidad_prod DECIMAL(14,4) NOT NULL DEFAULT 0,
        merma         DECIMAL(14,4) NOT NULL DEFAULT 0,
        estado        VARCHAR(16) NOT NULL DEFAULT 'programada',
        responsable   VARCHAR(160),
        estacion_id   INT,
        costo_insumos DECIMAL(14,2) NOT NULL DEFAULT 0,
        costo_mo      DECIMAL(14,2) NOT NULL DEFAULT 0,
        programada_ts VARCHAR(32),
        iniciada_ts   VARCHAR(32),
        terminada_ts  VARCHAR(32),
        notas         TEXT,
        UNIQUE KEY uq_op_numero (numero),
        KEY ix_op_estado (estado),
        CONSTRAINT fk_op_fic FOREIGN KEY (ficha_id)    REFERENCES fichas_produccion(id),
        CONSTRAINT fk_op_est FOREIGN KEY (estacion_id) REFERENCES estaciones(id)
    ) {_ENG}
    """,

    # ══════════════════════════════════════════════════════════════════
    #  SALÓN: ZONAS, MESAS Y RESERVAS
    # ══════════════════════════════════════════════════════════════════
    f"""
    CREATE TABLE IF NOT EXISTS zonas (
        id     INT AUTO_INCREMENT PRIMARY KEY,
        nombre VARCHAR(80) NOT NULL,
        color  VARCHAR(16) DEFAULT '#6366f1',
        orden  INT DEFAULT 0,
        activo TINYINT NOT NULL DEFAULT 1,
        UNIQUE KEY uq_zona (nombre)
    ) {_ENG}
    """,
    # `estado` se GUARDA en la mesa y no se deduce de si hay comanda abierta,
    # porque hay estados sin comanda: reservada y en limpieza. Deducirlo
    # obligaría a consultas frágiles en la pantalla que más se refresca.
    f"""
    CREATE TABLE IF NOT EXISTS mesas (
        id         INT AUTO_INCREMENT PRIMARY KEY,
        zona_id    INT,
        codigo     VARCHAR(16) NOT NULL,
        nombre     VARCHAR(80),
        capacidad  INT NOT NULL DEFAULT 4,
        estado     VARCHAR(16) NOT NULL DEFAULT 'libre',
        mesero     VARCHAR(160),
        ocupada_ts VARCHAR(32),
        activo     TINYINT NOT NULL DEFAULT 1,
        UNIQUE KEY uq_mesa_codigo (codigo),
        KEY ix_mesa_estado (estado),
        CONSTRAINT fk_mesa_zona FOREIGN KEY (zona_id) REFERENCES zonas(id)
    ) {_ENG}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS reservas (
        id         INT AUTO_INCREMENT PRIMARY KEY,
        mesa_id    INT,
        cliente_id INT,
        nombre     VARCHAR(160) NOT NULL,
        telefono   VARCHAR(40),
        email      VARCHAR(160),
        fecha      DATE NOT NULL,
        hora       VARCHAR(8) NOT NULL,
        personas   INT NOT NULL DEFAULT 2,
        estado     VARCHAR(16) NOT NULL DEFAULT 'pendiente',
        origen     VARCHAR(16) NOT NULL DEFAULT 'interno',
        notas      TEXT,
        codigo     VARCHAR(12),
        creado_por VARCHAR(160),
        creado_en  VARCHAR(32),
        KEY ix_reserva_fecha (fecha, hora),
        KEY ix_reserva_estado (estado),
        CONSTRAINT fk_res_mesa FOREIGN KEY (mesa_id) REFERENCES mesas(id)
    ) {_ENG}
    """,

    # ══════════════════════════════════════════════════════════════════
    #  COMANDAS
    #  La comanda es el documento de SERVICIO; la venta es el documento
    #  COMERCIAL. Son tablas distintas porque una mesa puede pedir tres
    #  veces y pagar una sola cuenta, o dividirla en dos.
    # ══════════════════════════════════════════════════════════════════
    f"""
    CREATE TABLE IF NOT EXISTS comandas (
        id          INT AUTO_INCREMENT PRIMARY KEY,
        numero      VARCHAR(24) NOT NULL,
        mesa_id     INT,
        mesero      VARCHAR(160),
        tipo        VARCHAR(16) NOT NULL DEFAULT 'mesa',
        personas    INT NOT NULL DEFAULT 1,
        estado      VARCHAR(16) NOT NULL DEFAULT 'abierta',
        apertura_ts VARCHAR(32) NOT NULL,
        cierre_ts   VARCHAR(32),
        venta_id    INT,
        notas       TEXT,
        UNIQUE KEY uq_comanda_numero (numero),
        KEY ix_comanda_estado (estado),
        KEY ix_comanda_mesa (mesa_id),
        CONSTRAINT fk_com_mesa FOREIGN KEY (mesa_id) REFERENCES mesas(id)
    ) {_ENG}
    """,
    # Cada línea lleva SU PROPIO estado y sus marcas de tiempo: un café sale en
    # dos minutos y un plato caliente en quince. Manejar el estado a nivel de
    # comanda impediría entregar lo que ya está listo.
    f"""
    CREATE TABLE IF NOT EXISTS comanda_items (
        id           INT AUTO_INCREMENT PRIMARY KEY,
        comanda_id   INT NOT NULL,
        producto_id  INT NOT NULL,
        nombre       VARCHAR(160),
        cantidad     DECIMAL(14,4) NOT NULL DEFAULT 1,
        precio_unit  DECIMAL(14,2) NOT NULL DEFAULT 0,
        iva_pct      DECIMAL(6,2)  NOT NULL DEFAULT 0,
        estacion_id  INT,
        -- Puesto de la mesa al que va el plato. 0 = de la mesa (para
        -- compartir): una picada o una jarra no son de nadie en particular,
        -- y obligar a asignarlas sería inventar un dato.
        puesto       INT NOT NULL DEFAULT 0,
        estado       VARCHAR(16) NOT NULL DEFAULT 'pendiente',
        notas        VARCHAR(240),
        enviado_ts   VARCHAR(32),
        listo_ts     VARCHAR(32),
        entregado_ts VARCHAR(32),
        KEY ix_citem_comanda (comanda_id),
        KEY ix_citem_estado (estado, estacion_id),
        CONSTRAINT fk_ci_com  FOREIGN KEY (comanda_id)  REFERENCES comandas(id) ON DELETE CASCADE,
        CONSTRAINT fk_ci_prod FOREIGN KEY (producto_id) REFERENCES productos(id),
        CONSTRAINT fk_ci_est  FOREIGN KEY (estacion_id) REFERENCES estaciones(id)
    ) {_ENG}
    """,

    # ══════════════════════════════════════════════════════════════════
    #  CAJA Y VENTAS
    # ══════════════════════════════════════════════════════════════════
    f"""
    CREATE TABLE IF NOT EXISTS cajas (
        id                INT AUTO_INCREMENT PRIMARY KEY,
        terminal          VARCHAR(24) NOT NULL DEFAULT 'CAJA-1',
        apertura_ts       VARCHAR(32) NOT NULL,
        cierre_ts         VARCHAR(32),
        usuario_apertura  VARCHAR(160),
        usuario_cierre    VARCHAR(160),
        base_inicial      DECIMAL(14,2) NOT NULL DEFAULT 0,
        efectivo_esperado DECIMAL(14,2) NOT NULL DEFAULT 0,
        efectivo_contado  DECIMAL(14,2),
        diferencia        DECIMAL(14,2),
        total_ventas      DECIMAL(14,2) NOT NULL DEFAULT 0,
        total_propinas    DECIMAL(14,2) NOT NULL DEFAULT 0,
        num_ventas        INT NOT NULL DEFAULT 0,
        observacion       TEXT,
        estado            VARCHAR(16) NOT NULL DEFAULT 'abierta',
        KEY ix_caja_estado (estado, usuario_apertura)
    ) {_ENG}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS ventas (
        id          INT AUTO_INCREMENT PRIMARY KEY,
        folio       VARCHAR(24) NOT NULL,
        caja_id     INT NOT NULL,
        comanda_id  INT,
        ts          VARCHAR(32) NOT NULL,
        subtotal    DECIMAL(14,2) NOT NULL DEFAULT 0,
        impuestos   DECIMAL(14,2) NOT NULL DEFAULT 0,
        propina     DECIMAL(14,2) NOT NULL DEFAULT 0,
        total       DECIMAL(14,2) NOT NULL DEFAULT 0,
        costo       DECIMAL(14,2) NOT NULL DEFAULT 0,
        estado      VARCHAR(16) NOT NULL DEFAULT 'pagada',
        usuario     VARCHAR(160),
        cliente_id  INT,
        idem_key    VARCHAR(64),
        anulada_ts  VARCHAR(32),
        anulada_por VARCHAR(160),
        UNIQUE KEY uq_venta_folio (folio),
        UNIQUE KEY uq_venta_idem (idem_key),
        KEY ix_venta_caja (caja_id),
        KEY ix_venta_ts (ts),
        CONSTRAINT fk_venta_caja FOREIGN KEY (caja_id) REFERENCES cajas(id)
    ) {_ENG}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS venta_items (
        id          INT AUTO_INCREMENT PRIMARY KEY,
        venta_id    INT NOT NULL,
        producto_id INT NOT NULL,
        nombre      VARCHAR(160),
        cantidad    DECIMAL(14,4) NOT NULL DEFAULT 1,
        precio_unit DECIMAL(14,2) NOT NULL DEFAULT 0,
        iva_pct     DECIMAL(6,2)  NOT NULL DEFAULT 0,
        subtotal    DECIMAL(14,2) NOT NULL DEFAULT 0,
        impuesto    DECIMAL(14,2) NOT NULL DEFAULT 0,
        total       DECIMAL(14,2) NOT NULL DEFAULT 0,
        KEY ix_vitem_venta (venta_id),
        CONSTRAINT fk_vi_venta FOREIGN KEY (venta_id)   REFERENCES ventas(id) ON DELETE CASCADE,
        CONSTRAINT fk_vi_prod  FOREIGN KEY (producto_id) REFERENCES productos(id)
    ) {_ENG}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS pagos (
        id         INT AUTO_INCREMENT PRIMARY KEY,
        venta_id   INT NOT NULL,
        metodo_id  INT,
        metodo     VARCHAR(60),
        monto      DECIMAL(14,2) NOT NULL DEFAULT 0,
        referencia VARCHAR(120),
        KEY ix_pago_venta (venta_id),
        CONSTRAINT fk_pago_venta FOREIGN KEY (venta_id) REFERENCES ventas(id) ON DELETE CASCADE
    ) {_ENG}
    """,

    # ══════════════════════════════════════════════════════════════════
    #  PROPINAS
    #  En Colombia la propina es VOLUNTARIA y NO constituye salario.
    #  Mientras no se reparte, el dinero NO es de la empresa: es un PASIVO
    #  con el personal. Registrarla como ingreso inflaría ventas, IVA y la
    #  base de renta.
    # ══════════════════════════════════════════════════════════════════
    f"""
    CREATE TABLE IF NOT EXISTS propinas (
        id          INT AUTO_INCREMENT PRIMARY KEY,
        venta_id    INT,
        comanda_id  INT,
        ts          VARCHAR(32) NOT NULL,
        monto       DECIMAL(14,2) NOT NULL DEFAULT 0,
        medio       VARCHAR(40),
        mesero      VARCHAR(160),
        distribuida TINYINT NOT NULL DEFAULT 0,
        reparto_id  INT,
        KEY ix_propina_ts (ts, distribuida)
    ) {_ENG}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS repartos_propina (
        id         INT AUTO_INCREMENT PRIMARY KEY,
        numero     VARCHAR(24) NOT NULL,
        desde      DATE NOT NULL,
        hasta      DATE NOT NULL,
        total      DECIMAL(14,2) NOT NULL DEFAULT 0,
        criterio   VARCHAR(24) NOT NULL DEFAULT 'puntos',
        estado     VARCHAR(16) NOT NULL DEFAULT 'borrador',
        creado_por VARCHAR(160),
        creado_en  VARCHAR(32),
        pagado_en  VARCHAR(32),
        UNIQUE KEY uq_reparto (numero)
    ) {_ENG}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS reparto_detalle (
        id          INT AUTO_INCREMENT PRIMARY KEY,
        reparto_id  INT NOT NULL,
        empleado_id INT,
        nombre      VARCHAR(160) NOT NULL,
        puntos      DECIMAL(8,2)  NOT NULL DEFAULT 1,
        monto       DECIMAL(14,2) NOT NULL DEFAULT 0,
        KEY ix_rd_reparto (reparto_id),
        CONSTRAINT fk_rd_rep FOREIGN KEY (reparto_id) REFERENCES repartos_propina(id) ON DELETE CASCADE
    ) {_ENG}
    """,

    # ══════════════════════════════════════════════════════════════════
    #  PÉRDIDAS Y CONSUMO INTERNO
    # ══════════════════════════════════════════════════════════════════
    f"""
    CREATE TABLE IF NOT EXISTS perdidas (
        id          INT AUTO_INCREMENT PRIMARY KEY,
        ts          VARCHAR(32) NOT NULL,
        insumo_id   INT NOT NULL,
        cantidad    DECIMAL(14,4) NOT NULL DEFAULT 0,
        costo_unit  DECIMAL(14,4) NOT NULL DEFAULT 0,
        costo_total DECIMAL(14,2) NOT NULL DEFAULT 0,
        motivo_id   INT,
        motivo      VARCHAR(120),
        observacion TEXT,
        usuario     VARCHAR(160),
        KEY ix_perdida_ts (ts),
        CONSTRAINT fk_per_ins FOREIGN KEY (insumo_id) REFERENCES insumos(id)
    ) {_ENG}
    """,
    # El desayuno del personal NO es venta (no hay ingreso) ni pérdida (no es
    # desperdicio): es un beneficio laboral. Mezclarlo con cualquiera de los dos
    # distorsiona el margen o el indicador de merma, que son justamente las dos
    # cifras que el negocio vigila.
    f"""
    CREATE TABLE IF NOT EXISTS consumo_interno (
        id             INT AUTO_INCREMENT PRIMARY KEY,
        ts             VARCHAR(32) NOT NULL,
        empleado_id    INT,
        beneficiario   VARCHAR(160) NOT NULL,
        producto_id    INT NOT NULL,
        nombre         VARCHAR(160),
        cantidad       DECIMAL(14,4) NOT NULL DEFAULT 1,
        costo_total    DECIMAL(14,2) NOT NULL DEFAULT 0,
        tipo           VARCHAR(24) NOT NULL DEFAULT 'desayuno',
        observacion    TEXT,
        autorizado_por VARCHAR(160),
        KEY ix_consumo_ts (ts),
        CONSTRAINT fk_con_prod FOREIGN KEY (producto_id) REFERENCES productos(id)
    ) {_ENG}
    """,

    # ══════════════════════════════════════════════════════════════════
    #  PROVEEDORES Y COMPRAS
    # ══════════════════════════════════════════════════════════════════
    f"""
    CREATE TABLE IF NOT EXISTS proveedores (
        id             INT AUTO_INCREMENT PRIMARY KEY,
        nit            VARCHAR(24),
        dv             VARCHAR(2),
        razon_social   VARCHAR(200) NOT NULL,
        contacto       VARCHAR(160),
        email          VARCHAR(160),
        telefono       VARCHAR(40),
        direccion      VARCHAR(200),
        ciudad         VARCHAR(120),
        dias_entrega   INT NOT NULL DEFAULT 2,
        condicion_pago VARCHAR(40) DEFAULT 'Contado',
        activo         TINYINT NOT NULL DEFAULT 1,
        creado_en      VARCHAR(32),
        KEY ix_prov_nit (nit)
    ) {_ENG}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS insumo_proveedor (
        id           INT AUTO_INCREMENT PRIMARY KEY,
        insumo_id    INT NOT NULL,
        proveedor_id INT NOT NULL,
        precio       DECIMAL(14,4) NOT NULL DEFAULT 0,
        cantidad_min DECIMAL(14,4) NOT NULL DEFAULT 1,
        preferido    TINYINT NOT NULL DEFAULT 0,
        UNIQUE KEY uq_ins_prov (insumo_id, proveedor_id),
        CONSTRAINT fk_ip_ins  FOREIGN KEY (insumo_id)    REFERENCES insumos(id) ON DELETE CASCADE,
        CONSTRAINT fk_ip_prov FOREIGN KEY (proveedor_id) REFERENCES proveedores(id) ON DELETE CASCADE
    ) {_ENG}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS ordenes_compra (
        id           INT AUTO_INCREMENT PRIMARY KEY,
        numero       VARCHAR(24) NOT NULL,
        proveedor_id INT NOT NULL,
        estado       VARCHAR(20) NOT NULL DEFAULT 'sugerida',
        automatica   TINYINT NOT NULL DEFAULT 0,
        subtotal     DECIMAL(14,2) NOT NULL DEFAULT 0,
        creada_en    VARCHAR(32),
        emitida_en   VARCHAR(32),
        recibida_en  VARCHAR(32),
        creada_por   VARCHAR(160),
        notas        TEXT,
        UNIQUE KEY uq_oc_numero (numero),
        KEY ix_oc_estado (estado),
        CONSTRAINT fk_oc_prov FOREIGN KEY (proveedor_id) REFERENCES proveedores(id)
    ) {_ENG}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS oc_items (
        id          INT AUTO_INCREMENT PRIMARY KEY,
        oc_id       INT NOT NULL,
        insumo_id   INT NOT NULL,
        nombre      VARCHAR(160),
        cantidad    DECIMAL(14,4) NOT NULL DEFAULT 0,
        precio_unit DECIMAL(14,4) NOT NULL DEFAULT 0,
        recibido    DECIMAL(14,4) NOT NULL DEFAULT 0,
        KEY ix_oci_oc (oc_id),
        CONSTRAINT fk_oci_oc  FOREIGN KEY (oc_id)     REFERENCES ordenes_compra(id) ON DELETE CASCADE,
        CONSTRAINT fk_oci_ins FOREIGN KEY (insumo_id) REFERENCES insumos(id)
    ) {_ENG}
    """,

    # ══════════════════════════════════════════════════════════════════
    #  CLIENTES Y FACTURACIÓN ELECTRÓNICA
    # ══════════════════════════════════════════════════════════════════
    f"""
    CREATE TABLE IF NOT EXISTS cat_tipos_doc_id (
        codigo VARCHAR(4)  PRIMARY KEY,
        nombre VARCHAR(80) NOT NULL,
        sigla  VARCHAR(12) NOT NULL,
        usa_dv TINYINT NOT NULL DEFAULT 0,
        orden  INT DEFAULT 0,
        activo TINYINT NOT NULL DEFAULT 1
    ) {_ENG}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS cat_responsabilidades (
        codigo VARCHAR(12) PRIMARY KEY,
        nombre VARCHAR(120) NOT NULL,
        orden  INT DEFAULT 0,
        activo TINYINT NOT NULL DEFAULT 1
    ) {_ENG}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS clientes (
        id               INT AUTO_INCREMENT PRIMARY KEY,
        tipo_persona     VARCHAR(12)  NOT NULL DEFAULT 'natural',
        tipo_doc         VARCHAR(4)   NOT NULL DEFAULT '13',
        numero_doc       VARCHAR(24)  NOT NULL,
        dv               VARCHAR(2),
        razon_social     VARCHAR(200) NOT NULL,
        email            VARCHAR(160),
        telefono         VARCHAR(40),
        direccion        VARCHAR(200),
        ciudad           VARCHAR(120),
        departamento     VARCHAR(120),
        pais             VARCHAR(4) NOT NULL DEFAULT 'CO',
        responsabilidad  VARCHAR(12) NOT NULL DEFAULT 'R-99-PN',
        visitas          INT NOT NULL DEFAULT 0,
        total_comprado   DECIMAL(14,2) NOT NULL DEFAULT 0,
        puntos           DECIMAL(14,2) NOT NULL DEFAULT 0,
        nivel            VARCHAR(16) NOT NULL DEFAULT 'nuevo',
        ultima_visita    VARCHAR(32),
        notas            TEXT,
        activo           TINYINT NOT NULL DEFAULT 1,
        creado_en        VARCHAR(32),
        UNIQUE KEY uq_cliente_doc (tipo_doc, numero_doc),
        KEY ix_cliente_num (numero_doc),
        KEY ix_cliente_nivel (nivel)
    ) {_ENG}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS facturacion_config (
        id               INT PRIMARY KEY,
        emisor_razon     VARCHAR(200),
        emisor_nit       VARCHAR(24),
        emisor_dv        VARCHAR(2),
        emisor_email     VARCHAR(160),
        emisor_direccion VARCHAR(200),
        emisor_ciudad    VARCHAR(120),
        emisor_resp      VARCHAR(12) DEFAULT 'R-99-PN',
        resolucion       VARCHAR(40),
        fecha_resolucion VARCHAR(12),
        prefijo          VARCHAR(8) DEFAULT 'SETP',
        rango_desde      INT DEFAULT 1,
        rango_hasta      INT DEFAULT 5000,
        clave_tecnica    VARCHAR(120),
        ambiente         VARCHAR(12) NOT NULL DEFAULT 'pruebas',
        proveedor        VARCHAR(40) NOT NULL DEFAULT 'simulado',
        actualizado_en   VARCHAR(32)
    ) {_ENG}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS documentos_dian (
        id          INT AUTO_INCREMENT PRIMARY KEY,
        venta_id    INT NOT NULL,
        cliente_id  INT,
        tipo        VARCHAR(24) NOT NULL DEFAULT 'pos',
        prefijo     VARCHAR(8),
        numero      INT,
        numero_full VARCHAR(32),
        cufe        VARCHAR(200),
        forma_pago  VARCHAR(2) NOT NULL DEFAULT '1',
        medio_pago  VARCHAR(4) NOT NULL DEFAULT '10',
        subtotal    DECIMAL(14,2) NOT NULL DEFAULT 0,
        impuestos   DECIMAL(14,2) NOT NULL DEFAULT 0,
        total       DECIMAL(14,2) NOT NULL DEFAULT 0,
        estado      VARCHAR(24) NOT NULL DEFAULT 'pendiente',
        mensaje     TEXT,
        payload     JSON,
        emitido_en  VARCHAR(32),
        KEY ix_dian_venta (venta_id),
        KEY ix_dian_estado (estado),
        CONSTRAINT fk_dian_venta FOREIGN KEY (venta_id) REFERENCES ventas(id)
    ) {_ENG}
    """,

    # ══════════════════════════════════════════════════════════════════
    #  TALENTO HUMANO Y NÓMINA
    # ══════════════════════════════════════════════════════════════════
    f"""
    CREATE TABLE IF NOT EXISTS empleados (
        id                 INT AUTO_INCREMENT PRIMARY KEY,
        usuario_id         INT,
        tipo_doc           VARCHAR(4) NOT NULL DEFAULT '13',
        numero_doc         VARCHAR(24) NOT NULL,
        nombres            VARCHAR(120) NOT NULL,
        apellidos          VARCHAR(120) NOT NULL,
        cargo              VARCHAR(120),
        estacion_id        INT,
        tipo_contrato      VARCHAR(40) NOT NULL DEFAULT 'Término indefinido',
        fecha_ingreso      DATE,
        fecha_retiro       DATE,
        salario_base       DECIMAL(14,2) NOT NULL DEFAULT 0,
        aplica_auxilio     TINYINT NOT NULL DEFAULT 1,
        eps                VARCHAR(120),
        afp                VARCHAR(120),
        arl                VARCHAR(120),
        clase_riesgo       VARCHAR(4) NOT NULL DEFAULT 'II',
        caja_compensacion  VARCHAR(120),
        puntos_propina     DECIMAL(8,2) NOT NULL DEFAULT 1,
        email              VARCHAR(160),
        telefono           VARCHAR(40),
        activo             TINYINT NOT NULL DEFAULT 1,
        creado_en          VARCHAR(32),
        UNIQUE KEY uq_emp_doc (numero_doc),
        KEY ix_emp_activo (activo),
        CONSTRAINT fk_emp_est FOREIGN KEY (estacion_id) REFERENCES estaciones(id)
    ) {_ENG}
    """,
    # Parámetros legales POR AÑO. Nunca se queman en el código: el salario
    # mínimo y el auxilio de transporte cambian cada año, y una liquidación
    # vieja debe poder reproducirse con los valores que regían entonces.
    f"""
    CREATE TABLE IF NOT EXISTS nomina_parametros (
        anio               INT PRIMARY KEY,
        smmlv              DECIMAL(14,2) NOT NULL,
        auxilio_transporte DECIMAL(14,2) NOT NULL,
        uvt                DECIMAL(14,2) NOT NULL DEFAULT 0,
        salud_empleado     DECIMAL(6,2) NOT NULL DEFAULT 4.00,
        salud_empleador    DECIMAL(6,2) NOT NULL DEFAULT 8.50,
        pension_empleado   DECIMAL(6,2) NOT NULL DEFAULT 4.00,
        pension_empleador  DECIMAL(6,2) NOT NULL DEFAULT 12.00,
        sena               DECIMAL(6,2) NOT NULL DEFAULT 2.00,
        icbf               DECIMAL(6,2) NOT NULL DEFAULT 3.00,
        caja               DECIMAL(6,2) NOT NULL DEFAULT 4.00,
        cesantias          DECIMAL(6,2) NOT NULL DEFAULT 8.33,
        int_cesantias      DECIMAL(6,2) NOT NULL DEFAULT 12.00,
        prima              DECIMAL(6,2) NOT NULL DEFAULT 8.33,
        vacaciones         DECIMAL(6,2) NOT NULL DEFAULT 4.17,
        exonerado_1607     TINYINT NOT NULL DEFAULT 1,
        vigente            TINYINT NOT NULL DEFAULT 1
    ) {_ENG}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS arl_tarifas (
        clase       VARCHAR(4) PRIMARY KEY,
        tarifa      DECIMAL(8,4) NOT NULL,
        descripcion VARCHAR(200)
    ) {_ENG}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS nomina_periodos (
        id                 INT AUTO_INCREMENT PRIMARY KEY,
        numero             VARCHAR(24) NOT NULL,
        desde              DATE NOT NULL,
        hasta              DATE NOT NULL,
        dias               INT NOT NULL DEFAULT 30,
        anio               INT NOT NULL,
        estado             VARCHAR(16) NOT NULL DEFAULT 'borrador',
        total_devengado    DECIMAL(14,2) NOT NULL DEFAULT 0,
        total_deducido     DECIMAL(14,2) NOT NULL DEFAULT 0,
        total_neto         DECIMAL(14,2) NOT NULL DEFAULT 0,
        total_aportes      DECIMAL(14,2) NOT NULL DEFAULT 0,
        total_prestaciones DECIMAL(14,2) NOT NULL DEFAULT 0,
        creado_por         VARCHAR(160),
        creado_en          VARCHAR(32),
        cerrado_en         VARCHAR(32),
        UNIQUE KEY uq_periodo (numero)
    ) {_ENG}
    """,
    # Un renglón por empleado y período con TODOS los conceptos abiertos. Se
    # guardan calculados y NO se recalculan al consultar: una liquidación es un
    # hecho histórico y debe seguir mostrando lo que se pagó, aunque después
    # cambien las tarifas o el salario.
    f"""
    CREATE TABLE IF NOT EXISTS nomina_detalle (
        id                 INT AUTO_INCREMENT PRIMARY KEY,
        periodo_id         INT NOT NULL,
        empleado_id        INT NOT NULL,
        nombre             VARCHAR(240),
        cargo              VARCHAR(120),
        dias               INT NOT NULL DEFAULT 30,
        salario            DECIMAL(14,2) NOT NULL DEFAULT 0,
        auxilio_transporte DECIMAL(14,2) NOT NULL DEFAULT 0,
        horas_extra        DECIMAL(14,2) NOT NULL DEFAULT 0,
        recargo_nocturno   DECIMAL(14,2) NOT NULL DEFAULT 0,
        recargo_dominical  DECIMAL(14,2) NOT NULL DEFAULT 0,
        otros_devengados   DECIMAL(14,2) NOT NULL DEFAULT 0,
        no_salarial        DECIMAL(14,2) NOT NULL DEFAULT 0,
        exceso_40          DECIMAL(14,2) NOT NULL DEFAULT 0,
        total_devengado    DECIMAL(14,2) NOT NULL DEFAULT 0,
        base_seguridad     DECIMAL(14,2) NOT NULL DEFAULT 0,
        salud_empleado     DECIMAL(14,2) NOT NULL DEFAULT 0,
        pension_empleado   DECIMAL(14,2) NOT NULL DEFAULT 0,
        fondo_solidaridad  DECIMAL(14,2) NOT NULL DEFAULT 0,
        retefuente         DECIMAL(14,2) NOT NULL DEFAULT 0,
        otras_deducciones  DECIMAL(14,2) NOT NULL DEFAULT 0,
        total_deducido     DECIMAL(14,2) NOT NULL DEFAULT 0,
        neto_pagar         DECIMAL(14,2) NOT NULL DEFAULT 0,
        salud_empleador    DECIMAL(14,2) NOT NULL DEFAULT 0,
        pension_empleador  DECIMAL(14,2) NOT NULL DEFAULT 0,
        arl                DECIMAL(14,2) NOT NULL DEFAULT 0,
        caja_compensacion  DECIMAL(14,2) NOT NULL DEFAULT 0,
        sena               DECIMAL(14,2) NOT NULL DEFAULT 0,
        icbf               DECIMAL(14,2) NOT NULL DEFAULT 0,
        cesantias          DECIMAL(14,2) NOT NULL DEFAULT 0,
        int_cesantias      DECIMAL(14,2) NOT NULL DEFAULT 0,
        prima              DECIMAL(14,2) NOT NULL DEFAULT 0,
        vacaciones         DECIMAL(14,2) NOT NULL DEFAULT 0,
        KEY ix_nd_periodo (periodo_id),
        CONSTRAINT fk_nd_per FOREIGN KEY (periodo_id)  REFERENCES nomina_periodos(id) ON DELETE CASCADE,
        CONSTRAINT fk_nd_emp FOREIGN KEY (empleado_id) REFERENCES empleados(id)
    ) {_ENG}
    """,

    # ══════════════════════════════════════════════════════════════════
    #  SG-SST  (Decreto 1072/2015 · Resolución 0312/2019)
    #  Un restaurante concentra riesgos muy concretos: cortes, quemaduras,
    #  pisos húmedos y carga física.
    # ══════════════════════════════════════════════════════════════════
    f"""
    CREATE TABLE IF NOT EXISTS sst_peligros (
        id                 INT AUTO_INCREMENT PRIMARY KEY,
        proceso            VARCHAR(120) NOT NULL,
        actividad          VARCHAR(200),
        clasificacion      VARCHAR(60) NOT NULL,
        peligro            VARCHAR(200) NOT NULL,
        efecto             VARCHAR(240),
        nivel_deficiencia  INT NOT NULL DEFAULT 2,
        nivel_exposicion   INT NOT NULL DEFAULT 3,
        nivel_consecuencia INT NOT NULL DEFAULT 25,
        nivel_riesgo       INT NOT NULL DEFAULT 0,
        interpretacion     VARCHAR(24),
        aceptabilidad      VARCHAR(60),
        controles          TEXT,
        epp                VARCHAR(240),
        responsable        VARCHAR(160),
        activo             TINYINT NOT NULL DEFAULT 1,
        actualizado_en     VARCHAR(32),
        KEY ix_peligro_proc (proceso)
    ) {_ENG}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS sst_actividades (
        id          INT AUTO_INCREMENT PRIMARY KEY,
        tipo        VARCHAR(40) NOT NULL,
        nombre      VARCHAR(200) NOT NULL,
        descripcion TEXT,
        responsable VARCHAR(160),
        fecha_plan  DATE,
        fecha_real  DATE,
        estado      VARCHAR(16) NOT NULL DEFAULT 'planeada',
        evidencia   VARCHAR(300),
        anio        INT,
        creado_en   VARCHAR(32),
        KEY ix_sstact (anio, estado)
    ) {_ENG}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS sst_incidentes (
        id               INT AUTO_INCREMENT PRIMARY KEY,
        consecutivo      VARCHAR(24) NOT NULL,
        ts               VARCHAR(32) NOT NULL,
        empleado_id      INT,
        nombre           VARCHAR(200),
        tipo             VARCHAR(24) NOT NULL DEFAULT 'incidente',
        lugar            VARCHAR(160),
        descripcion      TEXT,
        parte_cuerpo     VARCHAR(120),
        dias_incapacidad INT NOT NULL DEFAULT 0,
        causa_raiz       TEXT,
        acciones         TEXT,
        reportado_arl    TINYINT NOT NULL DEFAULT 0,
        estado           VARCHAR(16) NOT NULL DEFAULT 'abierto',
        creado_por       VARCHAR(160),
        UNIQUE KEY uq_inc (consecutivo),
        KEY ix_inc_ts (ts)
    ) {_ENG}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS sst_estandares (
        id          INT AUTO_INCREMENT PRIMARY KEY,
        ciclo       VARCHAR(12) NOT NULL,
        item        VARCHAR(12) NOT NULL,
        descripcion VARCHAR(300) NOT NULL,
        peso        DECIMAL(6,2) NOT NULL DEFAULT 0,
        cumple      TINYINT NOT NULL DEFAULT 0,
        justifica   TEXT,
        UNIQUE KEY uq_estandar (item)
    ) {_ENG}
    """,

    # ══════════════════════════════════════════════════════════════════
    #  CONTABILIDAD
    # ══════════════════════════════════════════════════════════════════
    f"""
    CREATE TABLE IF NOT EXISTS puc (
        codigo     VARCHAR(12) PRIMARY KEY,
        nombre     VARCHAR(160) NOT NULL,
        tipo       VARCHAR(16)  NOT NULL,
        naturaleza VARCHAR(8)   NOT NULL
    ) {_ENG}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS asientos (
        id       INT AUTO_INCREMENT PRIMARY KEY,
        numero   VARCHAR(24) NOT NULL,
        ts       VARCHAR(32) NOT NULL,
        tipo     VARCHAR(32) NOT NULL,
        concepto VARCHAR(240),
        ref_tipo VARCHAR(24),
        ref_id   INT,
        usuario  VARCHAR(160),
        anulado  TINYINT NOT NULL DEFAULT 0,
        UNIQUE KEY uq_asiento (numero),
        KEY ix_asiento_ts (ts),
        KEY ix_asiento_ref (ref_tipo, ref_id)
    ) {_ENG}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS asiento_lineas (
        id         BIGINT AUTO_INCREMENT PRIMARY KEY,
        asiento_id INT NOT NULL,
        cuenta     VARCHAR(12) NOT NULL,
        nombre     VARCHAR(160),
        debito     DECIMAL(14,2) NOT NULL DEFAULT 0,
        credito    DECIMAL(14,2) NOT NULL DEFAULT 0,
        KEY ix_linea_asiento (asiento_id),
        KEY ix_linea_cuenta (cuenta),
        CONSTRAINT fk_lin_as FOREIGN KEY (asiento_id) REFERENCES asientos(id) ON DELETE CASCADE
    ) {_ENG}
    """,

    # ══════════════════════════════════════════════════════════════════
    #  SITIO PÚBLICO
    # ══════════════════════════════════════════════════════════════════
    f"""
    CREATE TABLE IF NOT EXISTS sede_perfil (
        id              INT PRIMARY KEY,
        titular         VARCHAR(160),
        lema            VARCHAR(240),
        descripcion     TEXT,
        direccion       VARCHAR(200),
        ciudad          VARCHAR(120),
        telefono        VARCHAR(40),
        whatsapp        VARCHAR(40),
        email           VARCHAR(160),
        instagram       VARCHAR(120),
        facebook        VARCHAR(120),
        mapa_url        VARCHAR(400),
        horarios        TEXT,
        acepta_reservas TINYINT NOT NULL DEFAULT 1,
        aforo_max       INT NOT NULL DEFAULT 40,
        propina_pct     DECIMAL(6,2) NOT NULL DEFAULT 10.00,
        publicado       TINYINT NOT NULL DEFAULT 1,
        actualizado_en  VARCHAR(32)
    ) {_ENG}
    """,
    # Reseñas con MODERACIÓN obligatoria: nacen pendientes. Publicar
    # automáticamente lo que escribe un desconocido convierte la página del
    # negocio en un tablón abierto a insultos y spam.
    f"""
    CREATE TABLE IF NOT EXISTS resenas (
        id             INT AUTO_INCREMENT PRIMARY KEY,
        nombre         VARCHAR(160) NOT NULL,
        email          VARCHAR(160),
        calificacion   INT NOT NULL DEFAULT 5,
        comentario     TEXT,
        estado         VARCHAR(16) NOT NULL DEFAULT 'pendiente',
        respuesta      TEXT,
        respondida_por VARCHAR(160),
        ip             VARCHAR(64),
        creado_en      VARCHAR(32) NOT NULL,
        moderado_en    VARCHAR(32),
        KEY ix_resena_estado (estado)
    ) {_ENG}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS carta_publica (
        producto_id INT PRIMARY KEY,
        visible     TINYINT NOT NULL DEFAULT 1,
        destacado   TINYINT NOT NULL DEFAULT 0,
        descripcion VARCHAR(300),
        orden       INT DEFAULT 0,
        CONSTRAINT fk_carta_prod FOREIGN KEY (producto_id) REFERENCES productos(id) ON DELETE CASCADE
    ) {_ENG}
    """,

    # ══════════════════════════════════════════════════════════════════
    #  APROVECHAMIENTO DE SOBRANTES  ·  el calentado
    # ══════════════════════════════════════════════════════════════════
    # Lo que queda en la cocina al cerrar no es basura ni es venta: es un
    # tercer estado que casi ningún sistema modela y que en una cafetería de
    # barrio decide el margen del mes. El arroz, los fríjoles y la carne de
    # hoy son el calentado de mañana a las seis de la mañana.
    #
    # Modelarlo bien exige tres cosas que un inventario común no tiene:
    #   · un RELOJ — la comida preparada vence en horas, no en meses;
    #   · una TEMPERATURA — sin registro de cadena de frío no hay defensa
    #     ante una visita sanitaria (Resolución 2674 de 2013);
    #   · un RESPONSABLE — alguien firma que eso quedó en condiciones.
    f"""
    CREATE TABLE IF NOT EXISTS nomina_novedades (
        id          INT AUTO_INCREMENT PRIMARY KEY,
        periodo_id  INT NOT NULL,
        empleado_id INT NOT NULL,
        tipo        VARCHAR(30) NOT NULL,
        concepto    VARCHAR(200),
        valor       DECIMAL(14,2) NOT NULL DEFAULT 0,
        creado_por  VARCHAR(160),
        creado_en   VARCHAR(32) NOT NULL,
        KEY ix_nov_periodo (periodo_id, empleado_id),
        CONSTRAINT fk_nov_per FOREIGN KEY (periodo_id) REFERENCES nomina_periodos(id) ON DELETE CASCADE,
        CONSTRAINT fk_nov_emp FOREIGN KEY (empleado_id) REFERENCES empleados(id)
    ) {_ENG}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS anexos (
        id          INT AUTO_INCREMENT PRIMARY KEY,
        entidad     VARCHAR(40) NOT NULL,
        entidad_id  INT NOT NULL,
        nombre      VARCHAR(255) NOT NULL,
        archivo     VARCHAR(120) NOT NULL,
        tipo        VARCHAR(100),
        tamano      INT NOT NULL DEFAULT 0,
        sha256      VARCHAR(64),
        descripcion VARCHAR(300),
        subido_por  VARCHAR(160),
        subido_en   VARCHAR(32) NOT NULL,
        KEY ix_anexo (entidad, entidad_id),
        KEY ix_anexo_sha (sha256)
    ) {_ENG}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS comanda_puestos (
        comanda_id     INT NOT NULL,
        puesto         INT NOT NULL,
        sin_consumo    TINYINT NOT NULL DEFAULT 0,
        nombre         VARCHAR(120),
        actualizado_en VARCHAR(32),
        PRIMARY KEY (comanda_id, puesto),
        CONSTRAINT fk_cp_com FOREIGN KEY (comanda_id) REFERENCES comandas(id) ON DELETE CASCADE
    ) {_ENG}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS cierres_cocina (
        id            INT AUTO_INCREMENT PRIMARY KEY,
        fecha         VARCHAR(10) NOT NULL,
        turno         VARCHAR(24) NOT NULL DEFAULT 'noche',
        responsable   VARCHAR(160),
        estado        VARCHAR(16) NOT NULL DEFAULT 'cerrado',
        val_calentado DECIMAL(14,2) NOT NULL DEFAULT 0,
        val_consumo   DECIMAL(14,2) NOT NULL DEFAULT 0,
        val_merma     DECIMAL(14,2) NOT NULL DEFAULT 0,
        lineas        INT NOT NULL DEFAULT 0,
        observaciones TEXT,
        creado_en     VARCHAR(32) NOT NULL,
        UNIQUE KEY uq_cierre_fecha_turno (fecha, turno)
    ) {_ENG}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS sobrantes (
        id          INT AUTO_INCREMENT PRIMARY KEY,
        cierre_id   INT,
        insumo_id   INT NOT NULL,
        cantidad    DECIMAL(14,4) NOT NULL,
        disponible  DECIMAL(14,4) NOT NULL DEFAULT 0,
        costo_unit  DECIMAL(14,4) NOT NULL DEFAULT 0,
        valor       DECIMAL(14,2) NOT NULL DEFAULT 0,
        destino     VARCHAR(20) NOT NULL,
        temperatura DECIMAL(6,2),
        vence_en    VARCHAR(32),
        estado      VARCHAR(16) NOT NULL DEFAULT 'disponible',
        responsable VARCHAR(160),
        observacion VARCHAR(240),
        creado_en   VARCHAR(32) NOT NULL,
        cerrado_en  VARCHAR(32),
        KEY ix_sob_pool (estado, insumo_id, vence_en),
        CONSTRAINT fk_sob_ins FOREIGN KEY (insumo_id) REFERENCES insumos(id),
        CONSTRAINT fk_sob_cie FOREIGN KEY (cierre_id) REFERENCES cierres_cocina(id) ON DELETE SET NULL
    ) {_ENG}
    """,

    # ══════════════════════════════════════════════════════════════════
    #  PROPIEDAD, PLANTA Y EQUIPO
    # ══════════════════════════════════════════════════════════════════
    # El horno rotatorio vale más que tres meses de ventas. No registrarlo
    # tiene dos consecuencias: el balance queda incompleto y —peor— la
    # utilidad sale inflada, porque nadie carga el desgaste del equipo al
    # costo del pan que ese equipo produce.
    #
    # La cuenta contable y la vida útil viven en la CATEGORÍA, no en cada
    # activo: así, registrar una licuadora nueva no obliga a que quien la
    # registra sepa que va a la 1520 y se deprecia en diez años.
    f"""
    CREATE TABLE IF NOT EXISTS cat_activos (
        id              INT AUTO_INCREMENT PRIMARY KEY,
        nombre          VARCHAR(120) NOT NULL,
        cuenta_activo   VARCHAR(10) NOT NULL,
        cuenta_deprec   VARCHAR(10) NOT NULL,
        cuenta_gasto    VARCHAR(10) NOT NULL,
        vida_util_meses INT NOT NULL DEFAULT 120,
        tasa_anual      DECIMAL(6,2) NOT NULL DEFAULT 10.00,
        orden           INT DEFAULT 0,
        UNIQUE KEY uq_cat_activo (nombre)
    ) {_ENG}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS activos (
        id              INT AUTO_INCREMENT PRIMARY KEY,
        codigo          VARCHAR(32) NOT NULL,
        nombre          VARCHAR(180) NOT NULL,
        categoria_id    INT NOT NULL,
        marca           VARCHAR(80),
        modelo          VARCHAR(80),
        serie           VARCHAR(80),
        fecha_compra    VARCHAR(10) NOT NULL,
        valor_compra    DECIMAL(16,2) NOT NULL,
        valor_residual  DECIMAL(16,2) NOT NULL DEFAULT 0,
        vida_util_meses INT NOT NULL,
        deprec_acum     DECIMAL(16,2) NOT NULL DEFAULT 0,
        ultimo_periodo  VARCHAR(7),
        ubicacion       VARCHAR(120),
        responsable     VARCHAR(160),
        proveedor       VARCHAR(180),
        factura         VARCHAR(60),
        estado          VARCHAR(16) NOT NULL DEFAULT 'activo',
        fecha_baja      VARCHAR(10),
        motivo_baja     VARCHAR(240),
        creado_en       VARCHAR(32) NOT NULL,
        UNIQUE KEY uq_activo_codigo (codigo),
        KEY ix_activo_estado (estado, categoria_id),
        CONSTRAINT fk_act_cat FOREIGN KEY (categoria_id) REFERENCES cat_activos(id)
    ) {_ENG}
    """,
    # El mantenimiento no es un adorno del maestro de activos: en una cocina
    # que trabaja doce horas diarias, el horno que no recibe preventivo se
    # detiene un sábado a las seis de la mañana y ese día no hay pan.
    f"""
    CREATE TABLE IF NOT EXISTS activo_mantenimientos (
        id          INT AUTO_INCREMENT PRIMARY KEY,
        activo_id   INT NOT NULL,
        fecha       VARCHAR(10) NOT NULL,
        tipo        VARCHAR(20) NOT NULL DEFAULT 'preventivo',
        descripcion VARCHAR(400),
        costo       DECIMAL(14,2) NOT NULL DEFAULT 0,
        proveedor   VARCHAR(180),
        proximo     VARCHAR(10),
        responsable VARCHAR(160),
        creado_en   VARCHAR(32) NOT NULL,
        KEY ix_mant_activo (activo_id, fecha),
        CONSTRAINT fk_mant_act FOREIGN KEY (activo_id) REFERENCES activos(id) ON DELETE CASCADE
    ) {_ENG}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS deprec_periodos (
        id          INT AUTO_INCREMENT PRIMARY KEY,
        periodo     VARCHAR(7) NOT NULL,
        estado      VARCHAR(16) NOT NULL DEFAULT 'abierto',
        total       DECIMAL(16,2) NOT NULL DEFAULT 0,
        activos     INT NOT NULL DEFAULT 0,
        asiento_id  INT,
        creado_en   VARCHAR(32) NOT NULL,
        cerrado_en  VARCHAR(32),
        cerrado_por VARCHAR(160),
        UNIQUE KEY uq_deprec_periodo (periodo)
    ) {_ENG}
    """,
    f"""
    CREATE TABLE IF NOT EXISTS deprec_detalle (
        id            INT AUTO_INCREMENT PRIMARY KEY,
        periodo_id    INT NOT NULL,
        activo_id     INT NOT NULL,
        base          DECIMAL(16,2) NOT NULL,
        cuota         DECIMAL(16,2) NOT NULL,
        acum_antes    DECIMAL(16,2) NOT NULL,
        acum_despues  DECIMAL(16,2) NOT NULL,
        cuenta_gasto  VARCHAR(10),
        cuenta_deprec VARCHAR(10),
        KEY ix_dep_periodo (periodo_id),
        CONSTRAINT fk_dep_per FOREIGN KEY (periodo_id) REFERENCES deprec_periodos(id) ON DELETE CASCADE,
        CONSTRAINT fk_dep_act FOREIGN KEY (activo_id) REFERENCES activos(id)
    ) {_ENG}
    """,
]


# ══════════════════════════════════════════════════════════════════════
#  DATOS SEMILLA
#  Una sede recién creada debe poder operar en el minuto uno. Son un punto
#  de partida editable, no una taxonomía cerrada.
# ══════════════════════════════════════════════════════════════════════

ESTACIONES = [
    ("Barra / Bebidas",  "#0891b2", "🥤", 1),
    ("Cocina caliente",  "#dc2626", "🔥", 2),
    ("Cocina fría",      "#16a34a", "🥗", 3),
    ("Panadería",        "#d97706", "🥖", 4),
    ("Repostería",       "#db2777", "🍰", 5),
]

CATEGORIAS = [
    ("Entradas",          "#65a30d", 1),
    ("Platos fuertes",    "#dc2626", 2),
    ("Sopas",             "#ea580c", 3),
    ("Bebidas calientes", "#b45309", 4),
    ("Jugos naturales",   "#16a34a", 5),
    ("Bebidas frías",     "#0ea5e9", 6),
    ("Panadería",         "#d97706", 7),
    ("Postres",           "#db2777", 8),
    ("Desayunos",         "#0891b2", 0),
]

UNIDADES = ["Gramo", "Kilogramo", "Mililitro", "Litro", "Unidad", "Paquete", "Onza", "Porción"]

METODOS_PAGO = [
    # (nombre, cuenta PUC, es_efectivo, código DIAN del medio de pago)
    ("Efectivo",          "1105", 1, "10"),
    ("Tarjeta débito",    "1110", 0, "49"),
    ("Tarjeta crédito",   "1110", 0, "48"),
    ("Transferencia",     "1110", 0, "47"),
    ("Billetera digital", "1110", 0, "47"),
]

# Conceptos de costo indirecto por plato. Los valores por defecto son un punto
# de partida en pesos colombianos por porción; se ajustan por producto.
COSTOS_INDIRECTOS = [
    ("Preparación (mano de obra)", 800.0, 1),
    ("Gas",                        120.0, 2),
    ("Energía eléctrica",          110.0, 3),
    ("Agua",                       100.0, 4),
    ("Empaque y desechables",       80.0, 5),
]

MOTIVOS_PERDIDA = [
    "Vencimiento",
    "Producto dañado en preparación",
    "Derrame o accidente",
    "Error de despacho",
    "Devolución del cliente",
    "Sustracción",
    "Cortesía o degustación",
    "Ajuste por conteo físico",
]

# Códigos del anexo técnico de facturación electrónica de la DIAN.
TIPOS_DOC_ID = [
    ("13", "Cédula de ciudadanía",                   "CC",    0, 1),
    ("31", "NIT",                                     "NIT",   1, 2),
    ("22", "Cédula de extranjería",                  "CE",    0, 3),
    ("41", "Pasaporte",                               "PAS",   0, 4),
    ("12", "Tarjeta de identidad",                   "TI",    0, 5),
    ("47", "Permiso especial de permanencia",        "PEP",   0, 6),
    ("42", "Documento de identificación extranjero", "DIE",   0, 7),
    ("50", "NIT de otro país",                       "NIT-E", 0, 8),
    ("91", "NUIP",                                    "NUIP",  0, 9),
]

RESPONSABILIDADES = [
    ("R-99-PN", "No responsable de IVA",         1),
    ("O-13",    "Gran contribuyente",            2),
    ("O-15",    "Autorretenedor",                3),
    ("O-23",    "Agente de retención de IVA",    4),
    ("O-47",    "Régimen simple de tributación", 5),
]

# Tarifas ARL por clase de riesgo (Decreto 1772 de 1994). Un restaurante suele
# clasificarse en clase II o III según la actividad.
ARL_TARIFAS = [
    ("I",   0.522,  "Riesgo mínimo — labores administrativas"),
    ("II",  1.044,  "Riesgo bajo — servicio en salón, atención al cliente"),
    ("III", 2.436,  "Riesgo medio — cocina, manipulación de equipos"),
    ("IV",  4.350,  "Riesgo alto"),
    ("V",   6.960,  "Riesgo máximo"),
]

# Plan de cuentas alineado con el PUC colombiano (Decreto 2650).
PUC = [
    ("1105", "Caja general",                     "activo",     "debito"),
    ("1110", "Bancos",                           "activo",     "debito"),
    ("1435", "Inventario de insumos",            "activo",     "debito"),
    ("2205", "Proveedores nacionales",           "pasivo",     "credito"),
    ("2335", "Propinas por pagar al personal",   "pasivo",     "credito"),
    ("2370", "Retenciones y aportes de nómina",  "pasivo",     "credito"),
    ("2380", "Mano de obra de producción por pagar", "pasivo",  "credito"),
    ("2408", "IVA por pagar",                    "pasivo",     "credito"),
    # El restaurante de barrio no factura IVA: causa impuesto nacional al
    # consumo (8 %, art. 512-1 E.T.), que se declara aparte y no es
    # descontable. Cuenta propia para no contaminar la declaración de IVA.
    ("2413", "Impuesto nacional al consumo por pagar", "pasivo", "credito"),
    ("2505", "Salarios por pagar",                "pasivo",     "credito"),
    ("2510", "Cesantías consolidadas",           "pasivo",     "credito"),
    ("2515", "Intereses sobre cesantías",        "pasivo",     "credito"),
    ("2525", "Prima de servicios",               "pasivo",     "credito"),
    ("2530", "Vacaciones consolidadas",          "pasivo",     "credito"),
    ("3115", "Aportes sociales",                 "patrimonio", "credito"),
    ("4135", "Ingresos por venta de alimentos",  "ingreso",    "credito"),
    ("5105", "Gastos de personal — salarios",    "gasto",      "debito"),
    ("5110", "Gastos de personal — prestaciones", "gasto",     "debito"),
    ("5115", "Aportes a seguridad social",       "gasto",      "debito"),
    ("5120", "Aportes parafiscales",             "gasto",      "debito"),
    ("5165", "Alimentación del personal",        "gasto",      "debito"),
    ("5195", "Pérdidas y mermas de inventario",  "gasto",      "debito"),
    ("5305", "Descuentos y devoluciones",        "gasto",      "debito"),
    ("6135", "Costo de ventas",                  "costo",      "debito"),
    # Propiedad, planta y equipo. La 1592 es de naturaleza crédito aunque
    # viva en el activo: es la que lo va restando.
    ("1520", "Maquinaria y equipo",              "activo",     "debito"),
    ("1524", "Equipo de oficina",                "activo",     "debito"),
    ("1528", "Equipo de cómputo y comunicación", "activo",     "debito"),
    ("1592", "Depreciación acumulada",           "activo",     "credito"),
    ("5160", "Depreciación de propiedad, planta y equipo", "gasto", "debito"),
    ("5145", "Mantenimiento y reparaciones",     "gasto",      "debito"),
    ("5310", "Pérdida en retiro de activos",     "gasto",      "debito"),
]

# ══════════════════════════════════════════════════════════════════════
#  CATEGORÍAS DE ACTIVO FIJO
#  Vida útil y tasa según el artículo 137 del Estatuto Tributario: son las
#  tasas máximas que la DIAN acepta como deducibles. Usar otras obliga a
#  llevar una conciliación fiscal aparte, que una cafetería no va a hacer.
#  (nombre, cta activo, cta depreciación acumulada, cta gasto, meses, tasa %)
# ══════════════════════════════════════════════════════════════════════
CAT_ACTIVOS = [
    ("Maquinaria y equipo de cocina", "1520", "1592", "5160", 120, 10.00, 1),
    ("Equipo de refrigeración",       "1520", "1592", "5160", 120, 10.00, 2),
    ("Muebles y enseres",             "1524", "1592", "5160", 120, 10.00, 3),
    ("Equipo de cómputo y POS",       "1528", "1592", "5160",  60, 20.00, 4),
]

# ══════════════════════════════════════════════════════════════════════
#  EQUIPO CON EL QUE ABRE LA CAFETERÍA
#  (código, nombre, categoría, marca, modelo, fecha, valor, residual,
#   ubicación, responsable, proveedor)
# ══════════════════════════════════════════════════════════════════════
ACTIVOS = [
    ("EQ-001", "Horno rotatorio de panadería 10 bandejas", "Maquinaria y equipo de cocina",
     "Nova", "MAX-1000", "2024-02-15", 18500000, 1850000, "Panadería", "Jefe de panadería",
     "Equipos Industriales del Norte S.A.S."),
    ("EQ-002", "Amasadora espiral 25 kg", "Maquinaria y equipo de cocina",
     "Javar", "AE-25", "2024-02-15", 6800000, 680000, "Panadería", "Jefe de panadería",
     "Equipos Industriales del Norte S.A.S."),
    ("EQ-003", "Máquina de espresso 2 grupos", "Maquinaria y equipo de cocina",
     "La Cimbali", "M26", "2024-03-01", 9500000, 950000, "Barra", "Barista principal",
     "Cafeteras y Molinos Ltda."),
    ("EQ-004", "Molino de café dosificador", "Maquinaria y equipo de cocina",
     "Mahlkönig", "E65S", "2024-03-01", 4200000, 420000, "Barra", "Barista principal",
     "Cafeteras y Molinos Ltda."),
    ("EQ-005", "Estufa industrial 4 puestos con horno", "Maquinaria y equipo de cocina",
     "Javar", "EI-4H", "2024-02-20", 3900000, 390000, "Cocina caliente", "Jefe de cocina",
     "Equipos Industriales del Norte S.A.S."),
    ("EQ-006", "Campana extractora con filtro de grasa", "Maquinaria y equipo de cocina",
     "Inoxidables JC", "CE-240", "2024-02-20", 2800000, 0, "Cocina caliente", "Jefe de cocina",
     "Inoxidables JC S.A.S."),
    ("EQ-007", "Freidora de dos canastillas", "Maquinaria y equipo de cocina",
     "Javar", "FR-2C", "2024-02-20", 2400000, 240000, "Cocina caliente", "Jefe de cocina",
     "Equipos Industriales del Norte S.A.S."),
    ("EQ-008", "Licuadora industrial 4 litros", "Maquinaria y equipo de cocina",
     "Oster", "BLSTVB", "2024-03-05", 850000, 0, "Barra", "Barista principal",
     "Distribuidora Hogar y Cocina"),
    ("EQ-009", "Exprimidor de cítricos industrial", "Maquinaria y equipo de cocina",
     "Zumex", "Versatile", "2024-03-05", 1200000, 120000, "Barra", "Barista principal",
     "Distribuidora Hogar y Cocina"),
    ("EQ-010", "Lavavajillas industrial de canastilla", "Maquinaria y equipo de cocina",
     "Winterhalter", "UC-M", "2024-04-10", 5200000, 520000, "Lavado", "Jefe de cocina",
     "Equipos Industriales del Norte S.A.S."),
    ("EQ-011", "Nevera vertical 2 puertas en acero", "Equipo de refrigeración",
     "Indufrial", "NV-2P", "2024-02-18", 4800000, 480000, "Cocina caliente", "Jefe de cocina",
     "Refrigeración Andina S.A.S."),
    ("EQ-012", "Congelador horizontal 400 litros", "Equipo de refrigeración",
     "Haceb", "CH-400", "2024-02-18", 3200000, 320000, "Bodega", "Jefe de cocina",
     "Refrigeración Andina S.A.S."),
    ("EQ-013", "Vitrina refrigerada de exhibición", "Equipo de refrigeración",
     "Indufrial", "VR-150", "2024-03-12", 3600000, 360000, "Salón", "Administrador",
     "Refrigeración Andina S.A.S."),
    ("EQ-014", "Mesas y sillas de salón (12 juegos)", "Muebles y enseres",
     "Rimax", "Bistró", "2024-03-20", 4200000, 0, "Salón", "Administrador",
     "Muebles y Diseño del Café"),
    ("EQ-015", "Barra en madera y acero a la medida", "Muebles y enseres",
     "A la medida", "—", "2024-03-20", 5600000, 0, "Salón", "Administrador",
     "Muebles y Diseño del Café"),
    ("EQ-016", "Estación POS: computador, cajón e impresora", "Equipo de cómputo y POS",
     "Lenovo", "M70q", "2024-04-01", 2900000, 290000, "Caja", "Administrador",
     "Soluciones Punto de Venta S.A.S."),
    ("EQ-017", "Pantalla de cocina (KDS) 21 pulgadas", "Equipo de cómputo y POS",
     "Samsung", "F22T", "2024-04-01", 950000, 0, "Cocina caliente", "Jefe de cocina",
     "Soluciones Punto de Venta S.A.S."),
]

# ══════════════════════════════════════════════════════════════════════
#  MANTENIMIENTOS YA EJECUTADOS
#  (código de activo, fecha, tipo, descripción, costo, proveedor, próximo)
# ══════════════════════════════════════════════════════════════════════
MANTENIMIENTOS = [
    ("EQ-001", "2026-02-10", "preventivo", "Calibración de quemadores y cambio de empaques de puerta",
     420000, "Equipos Industriales del Norte S.A.S.", "2026-08-10"),
    ("EQ-003", "2026-03-05", "preventivo", "Descalcificación de caldera y cambio de gomas de grupo",
     280000, "Cafeteras y Molinos Ltda.", "2026-09-05"),
    ("EQ-006", "2026-04-18", "preventivo", "Lavado de filtros de grasa y ducto (exigido por bomberos)",
     350000, "Inoxidables JC S.A.S.", "2026-10-18"),
    ("EQ-011", "2026-05-22", "correctivo", "Cambio de termostato: la nevera no sostenía los 4 °C",
     540000, "Refrigeración Andina S.A.S.", None),
    ("EQ-010", "2026-06-30", "preventivo", "Limpieza de brazos aspersores y revisión de resistencia",
     190000, "Equipos Industriales del Norte S.A.S.", "2026-12-30"),
]

ZONAS = [
    ("Salón principal", "#6366f1", 1),
    ("Terraza",         "#16a34a", 2),
    ("Barra",           "#b45309", 3),
]

# (código, zona, capacidad)
MESAS = [
    ("M01", "Salón principal", 4), ("M02", "Salón principal", 4),
    ("M03", "Salón principal", 2), ("M04", "Salón principal", 6),
    ("M05", "Salón principal", 4), ("M06", "Salón principal", 2),
    ("T01", "Terraza", 4), ("T02", "Terraza", 4), ("T03", "Terraza", 6),
    ("B01", "Barra", 1), ("B02", "Barra", 1), ("B03", "Barra", 1),
]

# (código, nombre, unidad, stock inicial, mínimo, máximo, costo unitario, es_producido)
# El costo va SIEMPRE en la unidad de medida del insumo, no en la de compra: es
# la confusión más fácil de cometer. El café se compra por kilo pero la receta
# lo consume por gramo, así que el costo se expresa por gramo. Equivocarse en
# ese factor de mil no rompe nada visible, pero produce márgenes del 98 % que
# nadie cuestiona hasta compararlos con la realidad.
INSUMOS = [
    ("INS-001", "Café en grano",        "Gramo",     20000, 3000, 40000,   45.0, 0),
    ("INS-002", "Leche entera",         "Mililitro", 30000, 5000, 60000,    4.0, 0),
    ("INS-003", "Azúcar",               "Gramo",     10000, 2000, 20000,    3.0, 0),
    ("INS-004", "Vaso desechable 8 oz", "Unidad",      800,  150,  2000,  120.0, 0),
    ("INS-005", "Harina de trigo",      "Gramo",     25000, 5000, 50000,    5.0, 0),
    ("INS-006", "Queso mozzarella",     "Gramo",      6000, 1000, 12000,   28.0, 0),
    ("INS-007", "Chocolate cobertura",  "Gramo",      4000,  800,  8000,   38.0, 0),
    ("INS-008", "Hielo",                "Gramo",     12000, 2000, 25000,    1.0, 0),
    ("INS-009", "Levadura",             "Gramo",      2000,  400,  4000,   22.0, 0),
    ("INS-010", "Mantequilla",          "Gramo",      5000, 1000, 10000,   18.0, 0),
    ("INS-011", "Huevo",                "Unidad",      300,   60,   600,  650.0, 0),
    ("INS-012", "Naranja",              "Unidad",      200,   50,   400,  900.0, 0),
    ("INS-013", "Mora",                 "Gramo",      4000,  800,  8000,   12.0, 0),
    ("INS-014", "Pechuga de pollo",     "Gramo",     10000, 2000, 20000,   22.0, 0),
    ("INS-015", "Arroz",                "Gramo",     15000, 3000, 30000,    4.5, 0),
    ("INS-016", "Papa",                 "Gramo",     20000, 4000, 40000,    2.8, 0),
    ("INS-017", "Aceite vegetal",       "Mililitro", 10000, 2000, 20000,    9.0, 0),
    ("INS-018", "Sal",                  "Gramo",      5000, 1000, 10000,    1.8, 0),
    ("INS-019", "Tomate",               "Gramo",      8000, 1500, 15000,    5.5, 0),
    ("INS-020", "Lechuga",              "Gramo",      4000,  800,  8000,    7.0, 0),
    # Producidos internamente: nacen en cero y solo entran por producción.
    ("PRD-101", "Pan artesanal",        "Unidad",        0,   20,   200,    0.0, 1),
    ("PRD-102", "Base de jugo natural", "Mililitro",     0, 2000, 20000,    0.0, 1),
    # Materia prima del desayuno de barrio.
    ("INS-021", "Fríjol cargamanto",   "Gramo",      8000, 1500, 16000,    8.5, 0),
    ("INS-022", "Plátano maduro",      "Unidad",       60,   15,   120,  900.0, 0),
    ("INS-023", "Cebolla larga",       "Gramo",      3000,  600,  6000,    4.2, 0),
    ("INS-024", "Carne de res magra",  "Gramo",      6000, 1500, 12000,   26.0, 0),
    ("INS-025", "Arepa de maíz",       "Unidad",      120,   30,   250,  450.0, 0),
    # Preparados de olla. Son los que sobran al cierre y los que vuelven al
    # día siguiente como calentado.
    ("PRD-103", "Arroz cocido",        "Gramo",         0,    0, 12000,    0.0, 1),
    ("PRD-104", "Fríjoles cocidos",    "Gramo",         0,    0, 10000,    0.0, 1),
    ("PRD-105", "Carne guisada",       "Gramo",         0,    0,  6000,    0.0, 1),
]

# ══════════════════════════════════════════════════════════════════════
#  FICHA DE APROVECHAMIENTO  (código de insumo, horas de vida útil)
#  Solo lo que aquí aparece puede guardarse para el calentado. La lista es
#  corta a propósito: es una decisión sanitaria, no comercial. Lo que no
#  está —la leche, los jugos, la ensalada, el huevo ya servido— se bota, y
#  el sistema no ofrece la opción de guardarlo.
#  Referencia: Resolución 2674 de 2013, cadena de frío 0–4 °C.
# ══════════════════════════════════════════════════════════════════════
APTOS_CALENTADO = [
    ("PRD-103", 24),   # arroz cocido
    ("PRD-104", 48),   # fríjoles: aguantan más, incluso mejoran
    ("PRD-105", 24),   # carne guisada
    ("PRD-101", 24),   # pan del día: mañana se vende como pan de ayer
]

# (código, nombre, categoría, estación, precio, emoji, minutos, receta)
PRODUCTOS = [
    ("PRD-001", "Café americano",    "Bebidas calientes", "Barra / Bebidas", 4500, "☕", 3,
     [("INS-001", 18), ("INS-004", 1)]),
    ("PRD-002", "Café con leche",    "Bebidas calientes", "Barra / Bebidas", 5500, "🥛", 4,
     [("INS-001", 18), ("INS-002", 150), ("INS-004", 1)]),
    ("PRD-003", "Capuchino",         "Bebidas calientes", "Barra / Bebidas", 6500, "☕", 5,
     [("INS-001", 20), ("INS-002", 180), ("INS-004", 1)]),
    ("PRD-004", "Chocolate caliente", "Bebidas calientes", "Barra / Bebidas", 6000, "🍫", 6,
     [("INS-007", 30), ("INS-002", 200), ("INS-004", 1)]),
    ("PRD-005", "Café helado",       "Bebidas frías",     "Barra / Bebidas", 7000, "🧋", 5,
     [("INS-001", 20), ("INS-002", 120), ("INS-008", 150), ("INS-004", 1)]),
    ("PRD-006", "Jugo de naranja",   "Jugos naturales",   "Barra / Bebidas", 6500, "🍊", 4,
     [("INS-012", 4), ("INS-008", 80), ("INS-004", 1)]),
    ("PRD-007", "Jugo de mora",      "Jugos naturales",   "Barra / Bebidas", 6500, "🫐", 4,
     [("INS-013", 120), ("INS-003", 20), ("INS-008", 80), ("INS-004", 1)]),
    ("PRD-008", "Pan de queso",      "Panadería",         "Panadería",       3500, "🥐", 2,
     [("PRD-101", 1), ("INS-006", 40)]),
    ("PRD-009", "Croissant",         "Panadería",         "Panadería",       4000, "🥐", 2,
     [("PRD-101", 1), ("INS-010", 20)]),
    ("PRD-010", "Brownie",           "Postres",           "Repostería",      5000, "🍰", 3,
     [("INS-005", 50), ("INS-007", 45), ("INS-003", 30), ("INS-011", 1)]),
    ("PRD-011", "Pollo a la plancha", "Platos fuertes",   "Cocina caliente", 24000, "🍗", 18,
     [("INS-014", 220), ("INS-015", 150), ("INS-016", 120), ("INS-017", 20), ("INS-018", 5)]),
    ("PRD-012", "Ensalada de la casa", "Entradas",        "Cocina fría",     14000, "🥗", 8,
     [("INS-020", 120), ("INS-019", 80), ("INS-006", 30), ("INS-017", 10)]),
    ("PRD-013", "Sopa del día",      "Sopas",             "Cocina caliente", 12000, "🍲", 10,
     [("INS-016", 150), ("INS-014", 80), ("INS-018", 5), ("INS-019", 50)]),
    ("PRD-014", "Huevos al gusto",   "Entradas",          "Cocina caliente",  9000, "🍳", 7,
     [("INS-011", 2), ("INS-017", 10), ("INS-018", 3), ("PRD-101", 1)]),
    # El calentado se arma con lo de la olla de ayer. La receta apunta a los
    # mismos preparados: es el sistema el que decide, al descontar, servirse
    # primero del lote que vence antes.
    ("PRD-015", "Calentado paisa",   "Desayunos",         "Cocina caliente", 11000, "🍳", 10,
     [("PRD-103", 180), ("PRD-104", 150), ("INS-011", 1), ("INS-025", 1), ("INS-017", 10)]),
    ("PRD-016", "Calentado con carne", "Desayunos",       "Cocina caliente", 15500, "🥩", 12,
     [("PRD-103", 180), ("PRD-104", 150), ("PRD-105", 120), ("INS-011", 1), ("INS-025", 1)]),
    ("PRD-017", "Pan de ayer (x3)",  "Panadería",         "Panadería",        4500, "🥖", 1,
     [("PRD-101", 3)]),
]

# Fichas de producción: (insumo destino, nombre, estación, rendimiento, minutos, ingredientes)
FICHAS_PRODUCCION = [
    ("PRD-101", "Horneada de pan artesanal", "Panadería", 40, 180,
     [("INS-005", 4000), ("INS-009", 80), ("INS-010", 300), ("INS-018", 60)]),
    ("PRD-102", "Base de jugo natural",      "Barra / Bebidas", 5000, 30,
     [("INS-012", 20), ("INS-003", 300)]),
    ("PRD-103", "Olla de arroz",             "Cocina caliente", 6000, 45,
     [("INS-015", 2000), ("INS-018", 30), ("INS-017", 40)]),
    ("PRD-104", "Olla de fríjoles",          "Cocina caliente", 5000, 180,
     [("INS-021", 1500), ("INS-023", 100), ("INS-022", 2), ("INS-018", 25)]),
    ("PRD-105", "Carne guisada",             "Cocina caliente", 3000, 90,
     [("INS-024", 3500), ("INS-019", 300), ("INS-023", 150), ("INS-018", 20)]),
]

PROVEEDORES = [
    ("900123456", "Distribuidora de Café del Huila S.A.S.", "Ana Ruiz",
     "ventas@cafehuila.co", "601 555 0110", 2, "Crédito 30 días"),
    ("900987654", "Lácteos y Derivados La Pradera Ltda.", "Jorge Muñoz",
     "pedidos@lapradera.co", "601 555 0120", 1, "Contado"),
    ("901222333", "Suministros Gastronómicos del Centro", "Marcela Díaz",
     "compras@sumigastro.co", "601 555 0130", 3, "Crédito 15 días"),
]

# Matriz de peligros típica de un restaurante (metodología GTC 45).
SST_PELIGROS = [
    ("Cocina", "Manipulación de cuchillos y mandolinas", "Mecánico",
     "Corte con elemento cortopunzante", "Herida, amputación parcial", 6, 4, 25,
     "Guantes anticorte, afilado periódico, tabla antideslizante, inducción al puesto",
     "Guantes anticorte nivel 5", "Chef ejecutivo"),
    ("Cocina", "Operación de freidora, plancha y horno", "Físico",
     "Quemadura por contacto o salpicadura", "Quemadura de primer a tercer grado", 6, 4, 25,
     "Guantes térmicos, delantal, procedimiento de vaciado en frío, señalización",
     "Guantes térmicos, delantal de cuero", "Chef ejecutivo"),
    ("Cocina", "Exposición prolongada a fuente de calor", "Físico",
     "Estrés térmico", "Deshidratación, fatiga", 2, 4, 10,
     "Extracción mecánica, hidratación disponible, rotación de puesto",
     "Uniforme transpirable", "Responsable SG-SST"),
    ("Salón", "Desplazamiento en pisos húmedos", "Locativo",
     "Caída al mismo nivel", "Contusión, esguince, fractura", 6, 4, 25,
     "Calzado antideslizante, señalización de piso húmedo, limpieza inmediata de derrames",
     "Calzado antideslizante certificado", "Gerente de operación"),
    ("Salón", "Transporte manual de bandejas", "Biomecánico",
     "Sobreesfuerzo y postura forzada", "Lumbalgia, tendinitis de hombro", 2, 4, 10,
     "Pausas activas, capacitación en manipulación de cargas, carros de servicio",
     "—", "Responsable SG-SST"),
    ("Almacén", "Levantamiento de bultos de insumos", "Biomecánico",
     "Manipulación manual de cargas", "Lumbalgia, hernia discal", 6, 3, 25,
     "Límite de 25 kg por persona, ayudas mecánicas, técnica de levantamiento",
     "Faja lumbar, guantes", "Jefe de almacén"),
    ("Aseo", "Uso de desinfectantes y desengrasantes", "Químico",
     "Contacto con sustancia irritante", "Dermatitis, irritación respiratoria", 2, 3, 25,
     "Fichas de seguridad visibles, dilución señalizada, ventilación, prohibido trasvasar",
     "Guantes de nitrilo, gafas, tapabocas", "Responsable SG-SST"),
    ("Cocina", "Manipulación de alimentos crudos", "Biológico",
     "Contaminación cruzada", "Enfermedad transmitida por alimentos", 2, 4, 25,
     "Tablas por color, cadena de frío, lavado de manos, curso de manipulación vigente",
     "Cofia, tapabocas, guantes desechables", "Chef ejecutivo"),
]

# Estándares mínimos aplicables a empresas de 11 a 50 trabajadores, riesgo I-III
# (Resolución 0312 de 2019, artículo 9). Se siembra un subconjunto verificable.
SST_ESTANDARES = [
    ("I", "1.1.1", "Asignación de persona que diseña el SG-SST", 0.5),
    ("I", "1.1.2", "Asignación de responsabilidades en SG-SST", 0.5),
    ("I", "1.1.3", "Asignación de recursos para el SG-SST", 0.5),
    ("I", "1.1.4", "Afiliación al sistema general de riesgos laborales", 0.5),
    ("I", "1.1.6", "Conformación y funcionamiento del COPASST", 0.5),
    ("I", "1.1.8", "Conformación del comité de convivencia laboral", 0.5),
    ("I", "1.2.1", "Programa de capacitación anual en SST", 2.0),
    ("I", "1.2.2", "Inducción y reinducción en SST", 2.0),
    ("I", "1.2.3", "Responsables del SG-SST con curso virtual de 50 horas", 2.0),
    ("I", "2.1.1", "Política del SG-SST firmada, fechada y divulgada", 1.0),
    ("I", "2.4.1", "Plan anual de trabajo con objetivos y cronograma", 2.0),
    ("I", "2.5.1", "Archivo y retención documental del SG-SST", 2.0),
    ("H", "3.1.1", "Descripción sociodemográfica y diagnóstico de salud", 1.0),
    ("H", "3.1.2", "Actividades de promoción y prevención en salud", 1.0),
    ("H", "3.1.4", "Realización de evaluaciones médicas ocupacionales", 1.0),
    ("H", "3.1.6", "Restricciones y recomendaciones médico-laborales", 1.0),
    ("H", "3.2.1", "Reporte de accidentes y enfermedades laborales", 2.0),
    ("H", "3.2.2", "Investigación de incidentes y accidentes de trabajo", 2.0),
    ("H", "4.1.1", "Metodología para identificar peligros y valorar riesgos", 4.0),
    ("H", "4.1.2", "Identificación de peligros con participación de los trabajadores", 4.0),
    ("H", "4.2.1", "Implementación de medidas de prevención y control", 2.5),
    ("H", "4.2.4", "Inspecciones sistemáticas a instalaciones y equipos", 2.5),
    ("H", "4.2.5", "Mantenimiento periódico de equipos e instalaciones", 2.5),
    ("H", "4.2.6", "Entrega y reposición de elementos de protección personal", 2.5),
    ("V", "5.1.1", "Plan de prevención, preparación y respuesta ante emergencias", 5.0),
    ("V", "5.1.2", "Conformación y capacitación de la brigada de emergencias", 5.0),
    ("A", "6.1.1", "Definición de indicadores del SG-SST", 1.25),
    ("A", "6.1.2", "Auditoría anual con participación del COPASST", 1.25),
    ("A", "6.1.3", "Revisión anual por la alta dirección", 1.25),
    ("A", "7.1.1", "Definición de acciones preventivas y correctivas", 2.5),
]

# ══════════════════════════════════════════════════════════════════════
#  TEXTOS DE LA CARTA PÚBLICA
#  Van aparte de PRODUCTOS a propósito: el nombre interno del producto
#  sirve para operar (buscarlo en el POS, imprimirlo en la comanda) y la
#  descripción sirve para vender. Mezclarlos obliga a elegir entre las dos
#  cosas y siempre se pierde una.
#  (código, descripción, destacado, orden)
# ══════════════════════════════════════════════════════════════════════
CARTA_TEXTOS = [
    ("PRD-001", "Grano del Huila, tostión media. Cuerpo limpio y final dulce.", 0, 10),
    ("PRD-002", "Nuestro americano con leche entera vaporizada.", 0, 11),
    ("PRD-003", "Doble carga de espresso y espuma de leche bien densa.", 1, 12),
    ("PRD-004", "Chocolate en pastilla batido a mano. Pídalo con queso.", 0, 13),
    ("PRD-005", "Café frío sobre hielo, con un toque de leche.", 0, 20),
    ("PRD-006", "Cuatro naranjas exprimidas al momento. Sin azúcar añadida.", 1, 30),
    ("PRD-007", "Mora de Silvania, en agua o en leche.", 0, 31),
    ("PRD-008", "Recién salido del horno, con queso costeño por dentro.", 1, 40),
    ("PRD-009", "Hojaldre de mantequilla, laminado en casa. Se acaba temprano.", 0, 41),
    ("PRD-010", "Chocolate al 60 %, húmedo por dentro. Va tibio.", 0, 50),
    ("PRD-011", "Pechuga a la plancha con papa criolla y ensalada del día.", 1, 60),
    ("PRD-012", "Verdes frescos, tomate, queso y vinagreta de la casa.", 0, 70),
    ("PRD-013", "Cambia todos los días según lo que llegue del mercado.", 0, 71),
    ("PRD-014", "Como usted los quiera, con pan de la casa recién horneado.", 0, 72),
    ("PRD-015", "Arroz, fríjoles, huevo y arepa. Como debe ser, desde las 6 a. m.", 1, 1),
    ("PRD-016", "El calentado completo, con carne guisada de la casa.", 1, 2),
    ("PRD-017", "Pan del día anterior, a mitad de precio. Perfecto para tostar.", 0, 42),
]

# ══════════════════════════════════════════════════════════════════════
#  PLAN DE TRABAJO ANUAL DEL SG-SST
#  Repartido a lo largo del año a propósito. Un plan con todo programado
#  para diciembre no es un plan: es una lista de buenos deseos, y en el
#  cronograma se nota de inmediato.
#  Las actividades son las que una cocina de verdad necesita, no un
#  formulario genérico: manipulación de alimentos, extintores, ruido y
#  el examen de manipulador que exige la Resolución 2674.
#  (mes, día, tipo, nombre, responsable)
# ══════════════════════════════════════════════════════════════════════
PLAN_ANUAL = [
    (1, 20, "Capacitación", "Inducción en SST para personal nuevo del año", "Responsable SG-SST"),
    (2, 10, "Inspección", "Inspección de extintores y señalización de evacuación", "Jefe de cocina"),
    (2, 24, "Capacitación", "Manipulación higiénica de alimentos (Res. 2674 de 2013)", "Responsable SG-SST"),
    (3, 15, "Examen médico", "Exámenes periódicos y certificado de manipulador", "Gerencia"),
    (4, 12, "Capacitación", "Manejo seguro de cuchillos y prevención de cortes", "Jefe de cocina"),
    (4, 28, "Inspección", "Inspección de puestos de trabajo en cocina caliente", "Responsable SG-SST"),
    (5, 18, "Simulacro", "Simulacro de evacuación por incendio", "Responsable SG-SST"),
    (6, 9,  "Capacitación", "Prevención de quemaduras: freidora, plancha y horno", "Jefe de cocina"),
    (7, 14, "Medición", "Medición de ruido y temperatura en cocina", "Proveedor externo"),
    (8, 11, "Inspección", "Revisión de la matriz de peligros con el COPASST", "COPASST"),
    (9, 8,  "Capacitación", "Higiene postural y manejo manual de cargas en bodega", "Responsable SG-SST"),
    (10, 6, "Inspección", "Inspección de instalaciones eléctricas y de gas", "Proveedor externo"),
    (11, 10, "Capacitación", "Primeros auxilios y uso del botiquín", "Proveedor externo"),
    (11, 24, "Auditoría", "Auditoría interna anual del SG-SST", "Responsable SG-SST"),
    (12, 5, "Revisión", "Revisión por la alta dirección y plan del año siguiente", "Gerencia"),
]

FACTURACION = {
    "emisor_razon": "Restaurante Central S.A.S.",
    "emisor_nit": "901234567",
    "emisor_email": "facturacion@qmspm.com",
    "emisor_direccion": "Calle 100 # 15-20",
    "emisor_ciudad": "Bogotá D.C.",
    "emisor_resp": "R-99-PN",
    "resolucion": "18760000001",
    "fecha_resolucion": "2026-01-01",
    "prefijo": "SETP",
    "rango_desde": 1,
    "rango_hasta": 5000,
    "ambiente": "pruebas",
    "proveedor": "simulado",
}

# ══════════════════════════════════════════════════════════════════════
#  OPINIONES DE DEMOSTRACIÓN
#  Una página de restaurante sin una sola opinión transmite lo contrario de
#  lo que busca: no parece nueva, parece cerrada. Van dos con respuesta del
#  dueño, que es la mejor herramienta que tiene un negocio pequeño.
#  (nombre, estrellas, comentario, respuesta)
# ══════════════════════════════════════════════════════════════════════
RESENAS_DEMO = [
    ("Marcela Ortiz", 5,
     "El pan de queso sale del horno mientras uno espera. Volvimos tres domingos "
     "seguidos por eso.", None),
    ("Andrés Cifuentes", 5,
     "Pedí el pollo a la plancha y la papa criolla estaba en su punto. La atención, "
     "rápida y sin afanes.",
     "Gracias, Andrés. Le contamos que la papa nos llega de Une, Cundinamarca."),
    ("Diana Restrepo", 4,
     "Muy buen jugo de naranja, se nota que lo exprimen ahí mismo. El local se llena "
     "a la hora del almuerzo, vayan temprano.", None),
    ("Jorge Baena", 5,
     "El calentado de las seis de la mañana es el mejor del barrio. Y el capuchino "
     "tiene una espuma seria.", None),
    ("Liliana Peña", 4,
     "La sopa del día cambia y eso me encanta. Un punto menos porque faltó sal el "
     "martes.",
     "Tomamos nota, Liliana. Ya lo revisamos con la cocina."),
    ("Camilo Estrada", 5,
     "Me gusta que vendan el pan del día anterior más barato en vez de botarlo. "
     "Eso dice mucho de una cocina.", None),
]

PERFIL_PUBLICO = {
    "titular": "Restaurante Central",
    "lema": "Cocina de siempre, con producto de hoy",
    "descripcion": (
        "Panadería propia desde las cuatro de la mañana, jugos exprimidos al momento y "
        "una carta corta que cambia con lo que llega fresco del mercado. Somos un lugar "
        "de barrio con oficio de restaurante."),
    "direccion": "Calle 100 # 15-20",
    "ciudad": "Bogotá D.C.",
    "telefono": "601 555 0100",
    "whatsapp": "310 211 5483",
    "email": "hola@qmspm.com",
    "instagram": "restaurantecentral",
    "horarios": ("Lunes a viernes: 7:00 a. m. – 9:00 p. m.\n"
                 "Sábados: 8:00 a. m. – 10:00 p. m.\n"
                 "Domingos y festivos: 8:00 a. m. – 4:00 p. m."),
    "aforo_max": 40,
}
