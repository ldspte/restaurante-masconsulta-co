/* ══════════════════════════════════════════════════════════════════════
   RESTAURANTE · Núcleo de la aplicación

   Responsabilidades de este archivo y de ningún otro:
     · Sesión (ingreso, elección de sede, cierre)
     · Cliente HTTP unificado (`api`)
     · Navegación entre módulos y construcción del menú según el rol
     · Primitivas de interfaz compartidas: aviso emergente, modal, formato

   Cada módulo de negocio vive en su propio archivo y solo se comunica con
   este a través de tres contratos:
       window.<modulo>Inyectar()   crea su botón de menú y su página
       window.<modulo>AlAbrir()    carga sus datos cuando se le navega
       window.api(...)             habla con el backend

   Es la misma frontera que en el backend: módulos que no se conocen entre sí.
   ══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  var CLAVE_TOKEN = 'rst_token';
  var sesion = { token: null, usuario: null, sede: null, rol: null, modulos: [] };
  window.RST = sesion;
  window.CAF = sesion;   // alias retrocompatible

  // ══════════════════════════════════════════════════════════════════
  //  CLIENTE HTTP
  // ══════════════════════════════════════════════════════════════════
  /**
   * Punto único de salida hacia el backend.
   *
   * Concentrarlo permite resolver en un solo sitio tres cosas que de otro modo
   * se repetirían —y se olvidarían— en cada llamada: adjuntar el token,
   * normalizar el error que devuelve FastAPI (`{detail: …}`) y cerrar la
   * sesión automáticamente cuando el servidor responde 401.
   */
  window.api = function (ruta, opciones) {
    opciones = opciones || {};
    var cab = Object.assign({ 'Content-Type': 'application/json' }, opciones.headers || {});
    if (sesion.token) cab['Authorization'] = 'Bearer ' + sesion.token;

    var cfg = { method: opciones.method || 'GET', headers: cab, credentials: 'same-origin' };
    if (opciones.body !== undefined) cfg.body = JSON.stringify(opciones.body);

    return fetch(ruta, cfg).catch(function (fallo) {
      // `fetch` solo rechaza cuando la petición NO llegó a salir o no hubo
      // respuesta: servidor apagado, DNS, CORS. El navegador lo reporta como
      // «Failed to fetch», que no distingue una de otra. Se traduce a algo
      // accionable, porque en la práctica la causa casi siempre es la misma.
      var err = new Error(
        'No hay conexión con el servidor. Verifique que esté iniciado: ' +
        'abra una consola en Cafeteria\\Backend y ejecute «python main.py».');
      err.red = true;
      err.original = String(fallo && fallo.message || fallo);
      throw err;
    }).then(function (r) {
      if (r.status === 401 && sesion.token) {
        cerrarSesionLocal();
        toast('La sesión expiró. Ingrese nuevamente.', 'warn');
        throw new Error('Sesión expirada');
      }
      return r.text().then(function (txt) {
        var datos = null;
        try { datos = txt ? JSON.parse(txt) : {}; } catch (e) { datos = { detail: txt }; }
        if (!r.ok) {
          var msg = (datos && datos.detail) || r.statusText || 'Error del servidor';
          if (typeof msg !== 'string') msg = JSON.stringify(msg);
          var err = new Error(msg);
          err.status = r.status;
          // El identificador de traza permite ubicar el error exacto en el
          // registro del servidor cuando el usuario reporta un problema.
          err.traza = r.headers.get('X-Request-ID');
          throw err;
        }
        return datos;
      });
    });
  };

  // ══════════════════════════════════════════════════════════════════
  //  PRIMITIVAS DE INTERFAZ
  // ══════════════════════════════════════════════════════════════════
  var relojToast;
  window.toast = function (mensaje, tipo) {
    var t = document.getElementById('toast');
    if (!t) return;
    t.textContent = mensaje;
    t.className = 'on ' + (tipo || '');
    clearTimeout(relojToast);
    relojToast = setTimeout(function () { t.className = ''; }, tipo === 'err' ? 5200 : 3200);
  };

  window.errToast = function (e) {
    var m = (e && e.message) || 'Ocurrió un error inesperado';
    if (e && e.traza) m += ' (ref. ' + e.traza + ')';
    toast(m, 'err');
  };

  /** Formato de moneda colombiana, sin decimales: los centavos no circulan. */
  /**
   * Dinero en formato colombiano.
   *
   * `useGrouping: true` NO sobra. En los locales españoles el agrupamiento por
   * defecto es «min2»: los números de cuatro cifras se escriben SIN separador,
   * así que $9000 salía sin punto mientras $15.500 sí lo tenía. Firefox aplica
   * esa regla y Chrome no, de modo que el mismo precio se veía distinto según
   * el navegador. En una carta de restaurante eso no es un matiz tipográfico:
   * es un precio que se lee mal.
   */
  function agrupar(n, dec) {
    try {
      return new Intl.NumberFormat('es-CO', {
        minimumFractionDigits: 0, maximumFractionDigits: dec, useGrouping: true
      }).format(n);
    } catch (e) {
      // Sin Intl se arma a mano. Un precio siempre se pinta.
      var partes = Math.abs(n).toFixed(dec).split('.');
      partes[0] = partes[0].replace(/\B(?=(\d{3})+(?!\d))/g, '.');
      return (n < 0 ? '-' : '') + partes.join(',');
    }
  }

  window.money = function (v) {
    return '$' + agrupar(Math.round(Number(v || 0)), 0);
  };

  window.numero = function (v, dec) {
    return agrupar(Number(v || 0), dec == null ? 2 : dec);
  };

  /** Fecha legible a partir del ISO-8601 UTC que devuelve el backend. */
  window.fecha = function (iso, conHora) {
    if (!iso) return '—';
    try {
      var d = new Date(iso.length <= 10 ? iso + 'T00:00:00' : iso);
      var o = { day: '2-digit', month: 'short', year: 'numeric' };
      if (conHora) { o.hour = '2-digit'; o.minute = '2-digit'; }
      return d.toLocaleDateString('es-CO', o);
    } catch (e) { return iso; }
  };

  /* ── Modal genérico ───────────────────────────────────────────────── */
  var accionModal = null;
  window.modal = function (titulo, cuerpoHtml, textoAceptar, alAceptar) {
    document.getElementById('modal-t').textContent = titulo;
    document.getElementById('modal-b').innerHTML = cuerpoHtml;
    var btn = document.getElementById('modal-ok');
    btn.textContent = textoAceptar || 'Guardar';
    btn.style.display = alAceptar ? '' : 'none';
    accionModal = alAceptar || null;
    document.getElementById('modal').classList.add('on');
  };
  window.modalCerrar = function () {
    document.getElementById('modal').classList.remove('on');
    accionModal = null;
  };
  window.modalAceptar = function () {
    if (typeof accionModal === 'function') accionModal();
  };
  window.modalConfirmar = function (mensaje, alAceptar) {
    modal('Confirmar', '<p>' + esc(mensaje) + '</p>', 'Sí, continuar', function () {
      modalCerrar(); alAceptar();
    });
  };
  /** Lee el valor de un campo del modal sin repetir getElementById. */
  window.val = function (id) {
    var e = document.getElementById(id);
    return e ? e.value.trim() : '';
  };

  // ══════════════════════════════════════════════════════════════════
  //  SESIÓN
  // ══════════════════════════════════════════════════════════════════
  window.ingresar = function () {
    var email = val('lg-email'), pass = val('lg-pass');
    if (!email || !pass) return toast('Ingrese correo y contraseña', 'warn');

    var btn = document.getElementById('lg-btn');
    btn.disabled = true; btn.textContent = 'Verificando…';

    api('/api/auth/login', { method: 'POST', body: { email: email, password: pass } })
      .then(function (r) {
        if (r.requiere_seleccion) {
          sesion.token = r.token_seleccion;
          return elegirSede(r.sedes);
        }
        aplicarSesion(r);
      })
      .catch(function (e) { errToast(e); })
      .then(function () { btn.disabled = false; btn.textContent = 'Ingresar'; });
  };

  window.usarDemo = function (email, pass) {
    document.getElementById('lg-email').value = email;
    document.getElementById('lg-pass').value = pass;
    ingresar();
  };

  function elegirSede(sedes) {
    var html = sedes.map(function (s) {
      return '<button class="btn mb" style="width:100%;text-align:left;padding:12px 14px" ' +
        'data-act="seleccionarSede" data-args="' + arg(s.id) + '">' +
        '<b>' + esc(s.nombre) + '</b>' +
        '<div class="peq mut">' + esc(s.ciudad || '') + ' · ' + esc(s.rol) + '</div></button>';
    }).join('');
    modal('¿En qué sede va a trabajar?', html, null, null);
  }

  window.seleccionarSede = function (sedeId) {
    api('/api/auth/seleccionar-sede', { method: 'POST', body: { sede_id: Number(sedeId) } })
      .then(function (r) { modalCerrar(); aplicarSesion(r); })
      .catch(errToast);
  };

  function aplicarSesion(r) {
    sesion.token = r.token;
    sesion.usuario = r.usuario || sesion.usuario;
    sesion.sede = r.sede;
    sesion.rol = r.rol;
    sesion.modulos = r.modulos || [];
    localStorage.setItem(CLAVE_TOKEN, r.token);
    arrancarApp();
  }

  window.cerrarSesion = function () {
    api('/api/auth/logout', { method: 'POST' })
      .catch(function () { /* el cierre local ocurre igual */ })
      .then(cerrarSesionLocal);
  };

  function cerrarSesionLocal() {
    localStorage.removeItem(CLAVE_TOKEN);
    sesion.token = null;
    document.getElementById('app').classList.remove('on');
    document.getElementById('login').style.display = 'flex';
    var p = document.getElementById('lg-pass'); if (p) p.value = '';
  }

  // ══════════════════════════════════════════════════════════════════
  //  MÓDULOS Y NAVEGACIÓN
  // ══════════════════════════════════════════════════════════════════
  // Registro declarativo. `clave` debe coincidir con el nombre que el backend
  // devuelve en `modulos`: es lo que garantiza que el menú del navegador y el
  // permiso del servidor no puedan desincronizarse.
  var MODULOS = [
    { clave: 'dashboard',    ico: '📊', color: '#2563EB', titulo: 'Tablero',      grupo: 'Operación' },
    { clave: 'salon',        ico: '🪑', color: '#0891B2', titulo: 'Salón',        grupo: 'Operación' },
    { clave: 'comandas',     ico: '📝', color: '#7C3AED', titulo: 'Comandas',     grupo: 'Operación' },
    { clave: 'cocina',       ico: '🔥', color: '#DC2626', titulo: 'Cocina',       grupo: 'Operación' },
    { clave: 'caja',         ico: '🧾', color: '#16A34A', titulo: 'Caja',         grupo: 'Operación' },
    { clave: 'facturacion',  ico: '🧮', color: '#0284C7', titulo: 'Facturación',  grupo: 'Operación' },

    { clave: 'productos',    ico: '🍽️', color: '#6F4E37', titulo: 'Carta',        grupo: 'Catálogo' },
    { clave: 'escandallo',   ico: '💰', color: '#CA8A04', titulo: 'Costo de platos', grupo: 'Catálogo' },
    { clave: 'produccion',   ico: '🥖', color: '#D97706', titulo: 'Producción',   grupo: 'Catálogo' },
    { clave: 'inventario',   ico: '📦', color: '#EA580C', titulo: 'Inventario',   grupo: 'Catálogo' },
    { clave: 'compras',      ico: '🚚', color: '#0D9488', titulo: 'Compras',      grupo: 'Catálogo' },

    { clave: 'sobrantes',    ico: '🍲', color: '#0891B2', titulo: 'Sobrantes',    grupo: 'Control' },
    { clave: 'perdidas',     ico: '⚠️', color: '#DC2626', titulo: 'Pérdidas',     grupo: 'Control' },
    { clave: 'consumo',      ico: '🍳', color: '#65A30D', titulo: 'Consumo interno', grupo: 'Control' },
    { clave: 'propinas',     ico: '🪙', color: '#B45309', titulo: 'Propinas',     grupo: 'Control' },
    { clave: 'contabilidad', ico: '📒', color: '#7C3AED', titulo: 'Contabilidad', grupo: 'Control' },
    { clave: 'activos',      ico: '🏭', color: '#7C3AED', titulo: 'Maquinaria',   grupo: 'Control' },

    { clave: 'rrhh',         ico: '👥', color: '#4F46E5', titulo: 'Nómina',       grupo: 'Personal' },
    { clave: 'sgsst',        ico: '🦺', color: '#F59E0B', titulo: 'SG-SST',       grupo: 'Personal' },

    { clave: 'web',          ico: '🌐', color: '#DB2777', titulo: 'Sitio web',    grupo: 'Administración' },
    { clave: 'accesos',      ico: '🔐', color: '#475569', titulo: 'Accesos',      grupo: 'Administración' }
  ];
  window.CAF_MODULOS = MODULOS;

  function arrancarApp() {
    document.getElementById('login').style.display = 'none';
    document.getElementById('app').classList.add('on');

    document.getElementById('sb-sede').textContent = (sesion.sede && sesion.sede.nombre) || '';
    document.getElementById('sb-user').textContent = (sesion.usuario && sesion.usuario.nombre) || '';
    document.getElementById('sb-rol').textContent = sesion.rol || '';

    construirMenu();

    // Cada módulo crea su propia página. Se les da la oportunidad ahora, una
    // sola vez, para que la navegación posterior sea instantánea.
    MODULOS.forEach(function (m) {
      var fn = window[m.clave + 'Inyectar'];
      if (typeof fn === 'function') { try { fn(); } catch (e) { console.error(m.clave, e); } }
    });

    var primero = sesion.modulos[0] || 'dashboard';
    nav(primero);
  }

  function construirMenu() {
    var nav = document.getElementById('sb-nav');
    nav.innerHTML = '';
    var grupoActual = null;

    MODULOS.forEach(function (m) {
      // El menú se construye desde la lista que envió el SERVIDOR. Ocultar un
      // botón no protege nada por sí solo —el endpoint tiene su propio guard—
      // pero evita ofrecer al usuario acciones que le serán denegadas.
      if (sesion.modulos.indexOf(m.clave) === -1) return;

      if (m.grupo !== grupoActual) {
        grupoActual = m.grupo;
        var lbl = document.createElement('div');
        lbl.className = 'sb-lbl';
        lbl.textContent = m.grupo;
        nav.appendChild(lbl);
      }

      var b = document.createElement('button');
      b.className = 'sr';
      b.id = 'nav-' + m.clave;
      b.setAttribute('data-act', 'nav');
      b.setAttribute('data-args', m.clave);
      b.innerHTML = '<span class="ico" style="background:' + m.color + '22">' + m.ico + '</span>' +
        '<span>' + esc(m.titulo) + '</span>';
      nav.appendChild(b);
    });
  }

  window.nav = function (clave) {
    if (sesion.modulos.indexOf(clave) === -1) {
      return toast('Su rol no tiene acceso a ese módulo', 'warn');
    }
    document.querySelectorAll('.page').forEach(function (p) { p.classList.remove('on'); });
    document.querySelectorAll('.sr').forEach(function (b) { b.classList.remove('on'); });

    var pagina = document.getElementById('page-' + clave);
    if (pagina) pagina.classList.add('on');
    var boton = document.getElementById('nav-' + clave);
    if (boton) boton.classList.add('on');

    var alAbrir = window[clave + 'AlAbrir'];
    if (typeof alAbrir === 'function') {
      try { alAbrir(); } catch (e) { console.error(clave, e); errToast(e); }
    }
  };

  /**
   * Crea la cáscara de una página. La usan todos los módulos para no repetir
   * la misma estructura de encabezado siete veces.
   */
  window.crearPagina = function (clave, ico, titulo, subtitulo, color) {
    if (document.getElementById('page-' + clave)) return document.getElementById('cont-' + clave);
    var pg = document.createElement('div');
    pg.className = 'page';
    pg.id = 'page-' + clave;
    pg.innerHTML =
      '<div class="ph"><div class="barra" style="background:' + color + '"></div>' +
      '<div><div class="pht">' + ico + ' ' + esc(titulo) + '</div>' +
      '<div class="phs">' + esc(subtitulo) + '</div></div>' +
      '<div class="sp"></div><div class="btns" id="acc-' + clave + '"></div></div>' +
      '<div id="cont-' + clave + '"></div>';
    document.getElementById('paginas').appendChild(pg);
    return document.getElementById('cont-' + clave);
  };

  window.cargando = function (idContenedor) {
    var c = document.getElementById(idContenedor);
    if (c) c.innerHTML = '<div class="vacio"><span class="e">⏳</span>Cargando…</div>';
  };

  window.vacio = function (emoji, mensaje) {
    return '<div class="vacio"><span class="e">' + emoji + '</span>' + esc(mensaje) + '</div>';
  };

  // ══════════════════════════════════════════════════════════════════
  //  ARRANQUE
  // ══════════════════════════════════════════════════════════════════
  /**
   * Detecta que la página se abrió como archivo local en vez de servida.
   *
   * Es el tropiezo más probable de quien recibe el proyecto: hace doble clic en
   * `index.html` y el navegador lo abre con `file://`. Las rutas de la API son
   * relativas, así que `fetch('/api/auth/login')` intenta leer
   * `file:///api/auth/login`, que no existe, y el navegador responde con un
   * escueto «Failed to fetch» que no orienta a nadie.
   *
   * Vale la pena detectarlo y decir qué hacer, en lugar de dejar que el usuario
   * concluya que el sistema está roto.
   */
  function protocoloInvalido() {
    // Se comprueba por lista blanca y no buscando 'file:'. La página puede
    // llegar al navegador por varias vías que no son el servidor —file:, data:,
    // blob:, una vista previa incrustada— y en todas el resultado es el mismo:
    // las rutas relativas de la API no apuntan a ninguna parte.
    if (location.protocol === 'http:' || location.protocol === 'https:') return false;
    document.getElementById('login').innerHTML =
      '<div class="login-card" style="max-width:520px">' +
      '<div class="login-logo">🔌</div>' +
      '<h1>Falta iniciar el servidor</h1>' +
      '<div class="sub">Esta página se abrió como archivo local, no a través de la ' +
      'aplicación. Sin el servidor no hay a quién pedirle los datos.</div>' +
      '<div class="aviso w" style="text-align:left">' +
      '<b>1.</b> Abra una consola en la carpeta <code>Cafeteria\\Backend</code><br>' +
      '<b>2.</b> Ejecute <code>python main.py</code><br>' +
      '<b>3.</b> Entre a <b>http://127.0.0.1:8100</b></div>' +
      '<p class="peq mut" style="margin-top:14px">También puede hacer doble clic en ' +
      '<code>iniciar.bat</code>, en la raíz del proyecto: instala lo necesario y ' +
      'levanta el servidor.</p>' +
      '<a class="btn btn-p" href="http://127.0.0.1:8100" ' +
      'style="display:block;text-align:center;margin-top:16px;text-decoration:none">' +
      'Ir a http://127.0.0.1:8100</a></div>';
    return true;
  }

  document.addEventListener('DOMContentLoaded', function () {
    if (protocoloInvalido()) return;

    var guardado = localStorage.getItem(CLAVE_TOKEN);
    if (!guardado) return;

    // Se reanuda la sesión preguntando al servidor, no confiando en lo que
    // haya en el almacenamiento local: el token pudo ser revocado desde otro
    // dispositivo o el rol del usuario pudo cambiar.
    sesion.token = guardado;
    api('/api/auth/yo')
      .then(function (r) {
        sesion.usuario = r.usuario;
        sesion.sede = r.sede;
        sesion.rol = r.rol;
        sesion.modulos = r.modulos || [];
        arrancarApp();
      })
      .catch(function () { cerrarSesionLocal(); });
  });
})();
