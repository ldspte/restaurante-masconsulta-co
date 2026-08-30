# 🍽️ Restaurante · Sistema Integral de Gestión Gastronómica

> **Sistema de gestión integral para restaurantes, bares y cafeterías.**  
> Arquitectura de **Monolito Modular Multi-Tenant** orientada a eventos de dominio, con cumplimiento normativo y fiscal para Colombia (Facturación Electrónica DIAN, Nómina Electrónica, PUC y SG-SST).

---

## 📋 Tabla de Contenidos

1. [Visión General](#-visión-general)
2. [Arquitectura del Sistema](#-arquitectura-del-sistema)
3. [Módulos del Sistema](#-módulos-del-sistema)
4. [Estructura del Proyecto](#-estructura-del-proyecto)
5. [Stack Tecnológico](#-stack-tecnológico)
6. [Instalación y Configuración Local](#-instalación-y-configuración-local)
7. [Usuarios y Credenciales de Demostración](#-usuarios-y-credenciales-de-demostración)
8. [Bus de Eventos de Dominio](#-bus-de-eventos-de-dominio)
9. [Despliegue en Producción (cPanel / Passenger / VPS)](#-despliegue-en-producción)
10. [Seguridad y Buenas Prácticas](#-seguridad-y-buenas-prácticas)
11. [Licencia y Créditos](#-licencia-y-créditos)

---

## 🌟 Visión General

**Restaurante** es una solución integral diseñada para optimizar todas las áreas operativas, administrativas, financieras y normativas de un negocio gastronómico, ya sea un local independiente o una cadena multi-sede.

El sistema unifica en una sola plataforma:
* **Operación de Salón y Cocina:** Gestión de mesas interactivas, comandas digitales y sistema KDS (*Kitchen Display System*) por estaciones.
* **Punto de Venta (POS) y Caja:** Facturación rápida, control de turnos, arqueo ciego, múltiples medios de pago y distribución equitativa de propinas.
* **Control de Costos y Producción:** Escandallo de recetas, producción de sub-recetas por lotes con trazabilidad, control de mermas y cocina circular/aprovechamiento de sobrantes.
* **Cadena de Suministro:** Inventario perpetuo valorado por Promedio Ponderado (PMP), kardex automático y gestión de compras a proveedores.
* **Cumplimiento Legal y Contable (Colombia):** Facturación electrónica DIAN, nómina electrónica con liquidación legal completa, plan anual del SG-SST (GTC 45 / Dec. 1072) y contabilidad automática bajo PUC comercial por partida doble.
* **Presencia Digital:** Landing page pública responsiva con menú digital interactivo y sistema de reservas en línea con confirmación por correo electrónico.

---

## 🏛️ Arquitectura del Sistema

### 1. Monolito Modular
* **Despliegue unificado:** Un único proceso autónomo fácil de desplegar y mantener, sin la complejidad ni sobrecostes de red de los microservicios.
* **Fronteras explícitas:** Cada módulo opera como un router independiente de FastAPI con sus propios esquemas y lógica de negocio.
* **Comunicación desacoplada:** Los módulos no se llaman directamente entre sí para operaciones cruzadas; se integran mediante un **Bus de Eventos de Dominio** en memoria.

```
       ┌────────────────────────────────────────────────────────┐
       │                   FastAPI Application                  │
       │                                                        │
       │  [Salón] ──(orden_pagada)──► [Bus de Eventos]          │
       │                                     │                  │
       │             ┌───────────────────────┼────────────────┐ │
       │             ▼                       ▼                ▼ │
       │       [Inventario]            [Contabilidad]   [Sobrantes]
       └────────────────────────────────────────────────────────┘
```

### 2. Aislamiento Multi-Tenant (Base de Datos por Sede)
* **Base de Datos Maestra (`rst_master`):** Administra el registro de sedes (*tenants*), planes de suscripción, licenciamiento y usuarios globales con asignación de roles por sede.
* **Bases de Datos de Sede (`rst_{slug}`):** Cada sede cuenta con su propia base de datos física independiente (ej. `rst_central`), garantizando aislamiento total de datos transaccionales, auditoría y seguridad.

### 3. Persistencia de Alto Rendimiento (SQLAlchemy Core)
* **SQL Declarativo Explícito:** En lugar de un ORM pesado, se utiliza **SQLAlchemy Core** (`create_engine`, `text()`) con helpers uniformes (`q`, `q1`, `run`, `serial`) que previenen inyección SQL por construcción.
* **Precisión Financiera:** Todas las operaciones monetarias se procesan con tipos `DECIMAL` para evitar desfases por redondeo de punto flotante.

### 4. Frontend Ligero y Seguro
* **Vanilla JavaScript (ES6+) y CSS moderno:** Sin frameworks pesados ni dependencias de `npm` / `node_modules` en tiempo de ejecución.
* **Seguridad CSP Estricta:** Implementación de delegación de eventos (`data-act`) que elimina el uso de `unsafe-inline` en scripts.

---

## 📦 Módulos del Sistema

| Módulo | Descripción |
| :--- | :--- |
| **🛋️ Salón y Mesas** | Plano interactivo de mesas con código de colores por estado (libre, ocupada, por cobrar, sucia). Apertura de cuentas, traslado de mesas y división de cuentas. |
| **👨‍🍳 Cocina (KDS)** | Pantalla de cocina en tiempo real filtrada por estación (Cocina caliente, Cocina fría, Bar, Repostería). Tiempos de preparación y cambio de estados (Pendiente ➔ En preparación ➔ Listo). |
| **💳 Caja y POS** | Registro rápido de ventas, emisión de tickets/facturas, apertura/cierre de turnos de caja con arqueo, retiros/ingresos menores y distribución de propinas por puntos. |
| **📑 Facturación Electrónica** | Parámetros DIAN (resolución, prefijos, rangos, ambiente de habilitación/producción), generación de CUFE simulado/real, catálogo de clientes con tipos de documento (CC, NIT, CE, Pasaporte) y responsabilidades fiscales. |
| **📖 Carta y Productos** | Catálogo de platos, bebidas y combos con precios, categorías, IVA/Impoconsumo (8%), estaciones de despacho y fotos/emojis representativos. |
| **⚖️ Escandallo y Recetas** | Ficha técnica de costeo de platos, cálculo de costo unitario por ingrediente, margen de contribución, cálculo de costos indirectos (servicios, empaques) y PVP sugerido. |
| **🏭 Producción Propia** | Órdenes de producción interna (salsas, masas, fondos, porcionados). Descuenta insumos primarios y da entrada automática a productos elaborados con control de lote y vencimiento. |
| **📊 Inventario y Kardex** | Control de existencias en tiempo real, valoración por Promedio Ponderado (PMP), alertas automáticas de stock mínimo/máximo, auditoría de movimientos y ajustes de inventario. |
| **🛒 Compras y Proveedores** | Directorio de proveedores, registro de facturas de compra, recepción de mercancía con actualización automática de existencias y recalculo de costos promedio. |
| **🗑️ Pérdidas y Mermas** | Registro de desperdicios y bajas clasificadas por motivo (caducidad, daño, error de cocina) con cálculo del impacto financiero en la operación. |
| **♻️ Sobrantes y Aprovechamiento** | Módulo de sostenibilidad y gastronomía circular: re-procesamiento de mermas aprovechables, combos de rescate con descuento y métricas de reducción de desperdicio. |
| **🔧 Maquinaria y Activos** | Hoja de vida de maquinaria y equipos, cronograma de mantenimientos preventivos y correctivos, alertas de servicio técnico y control de depreciación. |
| **👥 Personal y RRHH** | Ficha del colaborador, contratos, afiliaciones a seguridad social (EPS, AFP, ARL con clases de riesgo I a V, Caja de Compensación) y ponderación de propinas. |
| **💰 Nómina Electrónica** | Liquidación de nómina bajo normativa laboral colombiana: SMMLV, auxilio de transporte, horas extras, recargos nocturnos/dominicales, deducciones, provisiones de prestaciones sociales y parafiscales. |
| **🦺 SG-SST** | Sistema de Gestión de Seguridad y Salud en el Trabajo: Plan Anual de Trabajo, Matriz de Identificación de Peligros y Valoración de Riesgos (GTC 45), inspecciones, comités (COPASST/Convivencia) e importación/exportación en Excel (.xlsx). |
| **📈 Contabilidad y PUC** | Plan Único de Cuentas comercial integrado. Generación automática de asientos contables por partida doble ante ventas, compras, nómina y ajustes. Balance de comprobación y Estado de Resultados. |
| **📊 Dashboard Gerencial** | Tablero ejecutivo con indicadores clave de rendimiento (KPIs): ventas del día, ticket promedio, platos más vendidos, ocupación de mesas, margen bruto y costos operativos. |
| **🌐 Sitio Web y Reservas** | Portal web público con presentación del restaurante, carta digital con alérgenos y motor de reservas con validación de aforo y envío automático de correos. |

---

## 📁 Estructura del Proyecto

```
restaurante-masconsulta-co/
├── .htaccess                      # Configuración de reescritura para cPanel / Apache
├── passenger_wsgi.py              # Adaptador ASGI ➔ WSGI (a2wsgi) para Phusion Passenger
├── requirements.txt               # Puente de dependencias para instalador de cPanel
├── README.md                      # Documentación principal del sistema
│
├── Backend/                       # Núcleo de la aplicación (Python / FastAPI)
│   ├── .env.example               # Plantilla de variables de entorno
│   ├── requirements.txt           # Dependencias oficiales de Python
│   ├── main.py                    # Punto de entrada, middleware, ciclo de vida y rutas
│   ├── db.py                      # Conexión MySQL, pool de conexiones y helpers SQL
│   ├── seguridad.py               # Autenticación JWT, hashing de claves y permisos RBAC
│   ├── dependencias.py            # Inyección de dependencias de FastAPI (sesión, usuario actual)
│   ├── eventos.py                 # Bus de eventos de dominio desacoplado
│   ├── provisioning.py            # Aprovisionamiento idempotente de esquemas y datos demo
│   ├── instalar.py                # Script CLI de instalación y verificación de BD
│   ├── seed_master.py             # DDL y catálogos de la base de datos maestra
│   ├── seed_tenant.py             # DDL, PUC y catálogos de la base de datos de cada sede
│   ├── correo.py                  # Envío de correos transaccionales (Resend API / SMTP)
│   │
│   └── *_router.py                # Routers de cada módulo funcional:
│       ├── accesos_router.py      # Autenticación, login, logout, perfil y permisos
│       ├── salon_router.py        # Gestión de mesas, estados y áreas del salón
│       ├── comandas_router.py     # Creación, adición y despacho de comandas
│       ├── productos_router.py    # Catálogo de productos y categorías
│       ├── escandallo.py          # Fichas técnicas de recetas y costos
│       ├── produccion_router.py   # Transformación de insumos y lotes
│       ├── inventario_router.py   # Kardex, stock y movimientos de almacén
│       ├── compras_router.py      # Facturas de compra y proveedores
│       ├── caja_router.py         # POS, turnos, arqueos y propinas
│       ├── facturacion_router.py  # Facturación electrónica DIAN y clientes
│       ├── personal_router.py     # Empleados y administración de personal
│       ├── nomina_router.py       # Liquidación legal de nómina
│       ├── activos_router.py      # Maquinaria, equipos y mantenimientos
│       ├── perdidas_router.py     # Registro de mermas y desperdicios
│       ├── sobrantes_router.py    # Cocina circular y aprovechamiento
│       ├── sgsst_router.py        # Seguridad y salud en el trabajo (GTC 45)
│       ├── contabilidad_router.py # Asientos contables, PUC y balances
│       ├── dashboard_router.py    # Métricas y analítica gerencial
│       ├── publico_router.py      # API pública para la web y reservas
│       └── anexos_router.py       # Gestión de archivos adjuntos y evidencias
│
└── FrontEnd/                      # Interfaz de usuario (Vanilla JS, CSS3, HTML5)
    ├── index.html                 # Panel de administración y punto de venta (SPA)
    ├── estilos.css                # Sistema de diseño, temas claro/oscuro y componentes
    ├── app.js                     # Controlador principal de navegación y estado global
    ├── csp_delegate.js            # Delegación de eventos para cumplimiento CSP
    ├── caf_*.js                   # Controladores JS especializados por módulo
    └── web/                       # Sitio web público y portal de reservas
        ├── index.html             # Landing page del restaurante
        ├── web.css                # Estilos visuales del portal público
        └── web.js                 # Lógica interactiva de reservas y carta web
```

---

## 🛠️ Stack Tecnológico

* **Lenguaje Backend:** Python 3.10+ / 3.11 / 3.12
* **Framework Web:** [FastAPI](https://fastapi.tiangolo.com/) (Validación con Pydantic, documentación OpenAPI/Swagger automática)
* **Servidor ASGI:** [Uvicorn](https://www.uvicorn.org/)
* **Puente WSGI/ASGI:** [a2wsgi](https://github.com/abersheeran/a2wsgi) (para entornos cPanel con Phusion Passenger)
* **Acceso a Datos:** [SQLAlchemy 2.0 Core](https://www.sqlalchemy.org/) + [PyMySQL](https://pymysql.readthedocs.io/)
* **Base de Datos:** MySQL 8.0+ o MariaDB 10.5+ (con soporte para `utf8mb4`)
* **Hojas de Cálculo:** [openpyxl](https://openpyxl.readthedocs.io/) (importación/exportación de planes SG-SST)
* **Manejo de Correo:** [Resend API](https://resend.com/) (primario) con fallback automático a **SMTP**
* **Frontend:** HTML5 Semántico, CSS3 Vanilla (Custom Properties, Flexbox, CSS Grid), JavaScript ES6+ Nativo

---

## 🚀 Instalación y Configuración Local

### 1. Prerrequisitos
* Tener instalado **Python 3.10** o superior.
* Servidor **MySQL** o **MariaDB** en ejecución (por ejemplo, mediante XAMPP, Laragon, Docker o servicio nativo).

### 2. Clonar el repositorio
```bash
git clone https://github.com/tu-usuario/restaurante-masconsulta-co.git
cd restaurante-masconsulta-co
```

### 3. Crear y activar el entorno virtual
* **En Windows (PowerShell):**
  ```powershell
  python -m venv .venv
  .venv\Scripts\Activate.ps1
  ```
* **En Linux / macOS:**
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  ```

### 4. Instalar dependencias
```bash
pip install -r Backend/requirements.txt
```

### 5. Configurar Variables de Entorno
Copia el archivo de ejemplo en la carpeta `Backend/`:
```bash
cp Backend/.env.example Backend/.env
```
Edita `Backend/.env` con tus credenciales locales de MySQL:
```ini
# Base de datos
RST_DB_HOST=127.0.0.1
RST_DB_PORT=3306
RST_DB_USER=root
RST_DB_PASS=tu_password_aqui

# Nombre de la base maestra y prefijo de sedes
RST_MASTER_DB=rst_master
RST_TENANT_PREFIX=rst_

# Seguridad (si se deja vacía, el instalador genera una automáticamente)
RST_SECRET_KEY=
RST_TOKEN_EXP_HORAS=12
RST_CORS_ORIGINS=http://127.0.0.1:8100,http://localhost:8100

# URL pública del sitio
RST_SITIO_URL=http://127.0.0.1:8100

# Servicio de Correo (opcional en desarrollo)
RESEND_API_KEY=
EMAIL_FROM=
```

### 6. Ejecutar el Instalador / Aprovisionador Idempotente
Ejecuta el script de instalación para verificar la conexión a MySQL, crear las bases de datos y sembrar los catálogos y datos de prueba:
```bash
python Backend/instalar.py
```

### 7. Iniciar el Servidor de Desarrollo
Puedes iniciar el servidor directamente con Python o con Uvicorn:
```bash
python Backend/main.py
```
*O con recarga automática:*
```bash
uvicorn Backend.main:app --host 127.0.0.1 --port 8100 --reload
```

Accede desde tu navegador:
* 🖥️ **Panel de Gestión / POS:** [http://127.0.0.1:8100](http://127.0.0.1:8100)
* 🌐 **Sitio Web y Reservas:** [http://127.0.0.1:8100/web/](http://127.0.0.1:8100/web/)
* 📚 **Documentación Interactiva Swagger:** [http://127.0.0.1:8100/api/docs](http://127.0.0.1:8100/api/docs)
* 📖 **Documentación ReDoc:** [http://127.0.0.1:8100/api/redoc](http://127.0.0.1:8100/api/redoc)

---

## 🔑 Usuarios y Credenciales de Demostración

El sistema incluye perfiles preconfigurados para probar cada rol y sus niveles de acceso:

| Rol | Correo Electrónico | Contraseña | Cargo / Responsabilidad | Módulos Accesibles |
| :--- | :--- | :--- | :--- | :--- |
| **👑 Administrador** | `manager@qmspm.com` | `Manager123*` | Gerente General (Superadmin) | Acceso total al sistema y configuración |
| **💼 Gerente / Contador** | `contador@luispardo.co` | `Contador123*` | Contador General | Contabilidad, Nómina, Facturación, Reportes, Activos |
| **🦺 SST / Calidad** | `calidad@luispardo.co` | `Calidad123*` | Responsable SG-SST | SG-SST, Inspecciones, Personal, Activos |
| **💵 Cajero** | `cajero@qmspm.com` | `Cajero123*` | Cajero de Mostrador | Caja, POS, Facturación, Salón, Comandas |
| **🍽️ Mesero** | `mesero@qmspm.com` | `Mesero123*` | Mesero / Servicio | Salón, Toma de Comandas, Consulta de Carta |
| **🍳 Cocinero** | `cocina@qmspm.com` | `Cocina123*` | Jefe de Cocina | KDS Cocina, Producción, Escandallo, Pérdidas |
| **📦 Almacén** | `bodega@qmspm.com` | `Bodega123*` | Auxiliar de Almacén | Inventario, Compras, Insumos, Pérdidas |

---

## ⚡ Bus de Eventos de Dominio

El archivo [eventos.py](file:///c:/Users/fabianperez/Downloads/restaurante-masconsulta-co/Backend/eventos.py) gestiona la reactividad del sistema. Cuando ocurre una acción de negocio importante, se publica un evento y los módulos suscritos reaccionan sincrónicamente bajo la misma transacción o contexto:

```
[Módulo Caja / POS] ────────► PUBLICAR: "orden_pagada"
                                       │
            ┌──────────────────────────┼──────────────────────────┐
            ▼                          ▼                          ▼
  [Módulo Inventario]        [Módulo Contabilidad]       [Módulo Sobrantes]
   Descuenta stock de         Genera asiento contable     Actualiza pool de
   insumos según receta       (Caja/Bancos vs Ingresos   lotes y aprovecha-
   (escandallo) y registra    e Impuestos por pagar)     miento de ingredientes
   movimientos de salida      en el PUC                   en cocina
```

### Eventos Principales:
* `orden_pagada`: Dispara la deducción de existencias en almacén por receta y registra el comprobante contable de ingreso e impuestos.
* `compra_registrada`: Incrementa el inventario de insumos, recalcula el Costo Promedio Ponderado (PMP) y asienta la cuenta por pagar a proveedores.
* `produccion_finalizada`: Descuenta la materia prima del lote y da entrada al sub-producto terminado.
* `nomina_liquidada`: Genera los asientos de gasto de personal, retenciones de seguridad social y provisiones de prestaciones.

---

## 🌐 Despliegue en Producción

### Despliegue en Hosting cPanel (con Phusion Passenger)

El repositorio incluye la configuración requerida para alojar en servicios cPanel (GoDaddy, HostGator, cPanel estándar):

1. **Estructura en la raíz del subdominio:**
   ```
   public_html/
   ├── passenger_wsgi.py      # Puente WSGI ➔ ASGI
   ├── requirements.txt      # Apunta a Backend/requirements.txt
   ├── .htaccess             # Redirecciones y reglas de Passenger
   ├── Backend/
   └── FrontEnd/
   ```
2. **Configurar «Setup Python App» en cPanel:**
   * **Python Version:** 3.10 o superior.
   * **Application root:** Directorio del subdominio (donde reside `passenger_wsgi.py`).
   * **Application startup file:** `passenger_wsgi.py`.
   * **Application Entry point:** `application`.
3. **Variables de Entorno:**
   * En `Backend/`, copia `.env.produccion` a `.env` y configura el usuario y contraseña de la base de datos MySQL creada en cPanel.
4. **Instalación:**
   * Abre la terminal de cPanel o SSH, activa el entorno virtual de Passenger y ejecuta:
     ```bash
     pip install -r requirements.txt
     python Backend/instalar.py
     ```

### Despliegue en VPS / Servidor Linux (Ubuntu / Debian con Nginx y Systemd)

1. Crear servicio en `/etc/systemd/system/restaurante.service`:
   ```ini
   [Unit]
   Description=Restaurante MasConsulta Backend
   After=network.target

   [Service]
   User=www-data
   WorkingDirectory=/var/www/restaurante/Backend
   ExecStart=/var/www/restaurante/.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8100 --workers 4
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```
2. Configurar Nginx como Reverse Proxy con terminación SSL (Certbot / Let's Encrypt).

---

## 🔒 Seguridad y Buenas Prácticas

* **Control de Tasa (Throttling / Rate Limiting):** Middleware con ventana deslizante que previene ataques de fuerza bruta en `/api/auth/login` (máximo 10 intentos/minuto) y satura de peticiones en el resto de la API (300 req/minuto).
* **Trazabilidad (Request ID):** Cabecera `X-Request-ID` inyectada en cada respuesta HTTP para correlacionar incidencias del frontend con los registros del servidor.
* **Seguridad de Cookies:** Tokens JWT emitidos en cookies con directivas `HttpOnly`, `SameSite=Lax` y `Secure` (en HTTPS).
* **Content Security Policy (CSP):** Bloqueo total de inyecciones de código en línea, ejecución no autorizada de scripts y protección contra Clickjacking (`X-Frame-Options: DENY`).
* **Protección contra Inyección SQL:** Parametrización estricta de todas las sentencias mediante SQLAlchemy Core.

---

## 📄 Licencia y Créditos

Desarrollado como solución empresarial de gestión gastronómica modular.  
Todos los derechos reservados.
