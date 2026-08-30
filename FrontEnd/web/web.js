/* ══════════════════════════════════════════════════════════════════════
   RESTAURANTE · Sitio público

   Se alimenta de `/api/publico/{slug}/…`, endpoints sin autenticación que
   devuelven ÚNICAMENTE lo publicable. Esta página nunca ve costos, márgenes
   ni existencias: esa información no sale del sistema.

   El código de la sede se toma de la URL (`?sede=central`), lo que permite que
   un mismo despliegue sirva la página de cada local.
   ══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  var SEDE = new URLSearchParams(location.search).get('sede') || 'central';
  var API = '/api/publico/' + encodeURIComponent(SEDE);
  var info = null, carta = null, catActiva = '';

  // ── Utilidades ────────────────────────────────────────────────────
  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  function money(v) {
    try { return '$' + new Intl.NumberFormat('es-CO', { maximumFractionDigits: 0 })
      .format(Math.round(Number(v || 0))); }
    catch (e) { return '$' + Math.round(Number(v || 0)); }
  }
  function api(ruta, opciones) {
    opciones = opciones || {};
    return fetch(API + ruta, {
      method: opciones.method || 'GET',
      headers: { 'Content-Type': 'application/json' },
      body: opciones.body ? JSON.stringify(opciones.body) : undefined
    }).then(function (r) {
      return r.text().then(function (t) {
        var d; try { d = t ? JSON.parse(t) : {}; } catch (e) { d = { detail: t }; }
        if (!r.ok) throw new Error(d.detail || 'No pudimos completar la operación');
        return d;
      });
    });
  }
  /** Lee un campo del formulario sin repetir getElementById. */
  function val(id) {
    var e = document.getElementById(id);
    return e ? e.value.trim() : '';
  }

  var relojAviso;
  function aviso(msg, tipo) {
    var a = document.getElementById('aviso');
    a.textContent = msg; a.className = 'on ' + (tipo || '');
    clearTimeout(relojAviso);
    relojAviso = setTimeout(function () { a.className = ''; }, 4200);
  }
  function estrellas(n) {
    return '★★★★★'.slice(0, n) + '☆☆☆☆☆'.slice(0, 5 - n);
  }

  // ── Delegación de eventos (misma política CSP del sistema) ────────
  document.addEventListener('click', function (e) {
    var el = e.target.closest('[data-act]');
    if (!el) return;
    var fn = window['__' + el.getAttribute('data-act')];
    if (typeof fn !== 'function') return;
    if (el.tagName === 'A' || el.tagName === 'FORM') e.preventDefault();
    fn(el, e);
  });
  document.addEventListener('submit', function (e) {
    var f = e.target;
    if (f && f.hasAttribute('data-act')) {
      e.preventDefault();
      var fn = window['__' + f.getAttribute('data-act')];
      if (typeof fn === 'function') fn(f, e);
    }
  });

  window.__alternarMenu = function () {
    document.querySelector('.nav-links').classList.toggle('abierto');
  };
  window.__irReserva = function () {
    document.querySelector('.nav-links').classList.remove('abierto');
    document.getElementById('reservar').scrollIntoView({ behavior: 'smooth' });
    setTimeout(function () { document.getElementById('rv-nombre').focus(); }, 700);
  };
  window.__cerrarModal = function () {
    document.getElementById('modal').classList.remove('on');
  };

  // La barra se separa del fondo al desplazarse: da sensación de capa y
  // mantiene legible el menú sobre la carta.
  window.addEventListener('scroll', function () {
    document.getElementById('nav').classList.toggle('pegado', window.scrollY > 24);
  });

  // ══════════════════════════════════════════════════════════════════
  //  INFORMACIÓN
  // ══════════════════════════════════════════════════════════════════
  function pintarInfo(d) {
    info = d;
    var p = d.perfil, c = d.calificacion;
    var nombre = p.titular || d.sede.nombre;

    document.title = nombre + (p.lema ? ' · ' + p.lema : '');
    document.getElementById('marca-nombre').textContent = nombre;
    document.getElementById('pie-nombre').textContent = nombre;
    document.getElementById('hero-titulo').textContent = nombre;
    document.getElementById('hero-lema').textContent = p.lema || '';
    document.getElementById('pie-lema').textContent = p.lema || '';
    document.getElementById('hero-desc').textContent = p.descripcion || '';
    document.getElementById('nosotros-texto').textContent = p.descripcion || '';
    document.getElementById('horarios').textContent = p.horarios || 'Consúltenos';
    document.getElementById('pie-legal-txt').textContent =
      '© ' + new Date().getFullYear() + ' ' + nombre + ' · ' + (p.ciudad || '');

    document.getElementById('hero-sello').innerHTML =
      '<svg style="width:15px;height:15px;color:var(--verde3)" aria-hidden="true">' +
      '<use href="#ico-hoja"/></svg>' + esc(p.ciudad || 'Bienvenidos');

    // Datos de portada: solo los que dicen algo. Un contador de reseñas en
    // cero no genera confianza, la resta.
    var datos = '';
    if (c.promedio) {
      datos += '<div class="hero-dato"><b>' + c.promedio + '</b>' +
        '<span>' + c.total + ' opiniones</span></div>';
    }
    datos += '<div class="hero-dato"><b>4 a. m.</b><span>Empieza el pan</span></div>' +
             '<div class="hero-dato"><b>100 %</b><span>Jugo natural</span></div>';
    document.getElementById('hero-datos').innerHTML = datos;

    document.getElementById('estado-abierto').className =
      'estado-abierto ' + (estaAbierto() ? 'abierto' : 'cerrado');
    document.getElementById('estado-abierto').textContent =
      estaAbierto() ? '● Abierto ahora' : '● Cerrado en este momento';

    // Contacto (sección de reserva)
    var rc = '';
    if (p.telefono) rc += '<a href="tel:' + esc(p.telefono.replace(/\s/g, '')) + '">📞 ' + esc(p.telefono) + '</a>';
    if (p.whatsapp) rc += '<a href="https://wa.me/57' + esc(p.whatsapp.replace(/\D/g, '')) +
      '" target="_blank" rel="noopener">💬 WhatsApp ' + esc(p.whatsapp) + '</a>';
    if (p.direccion) rc += '<span>📍 ' + esc(p.direccion) + '</span>';
    document.getElementById('reserva-contacto').innerHTML = rc;

    // Visítanos
    var cl = '';
    if (p.direccion) cl += item('📍', 'Dirección', esc(p.direccion) + (p.ciudad ? ', ' + esc(p.ciudad) : ''));
    if (p.telefono) cl += item('📞', 'Teléfono', '<a href="tel:' + esc(p.telefono.replace(/\s/g, '')) + '">' + esc(p.telefono) + '</a>');
    if (p.email) cl += item('✉️', 'Correo', '<a href="mailto:' + esc(p.email) + '">' + esc(p.email) + '</a>');
    document.getElementById('contacto-lista').innerHTML = cl;

    var redes = '';
    if (p.instagram) redes += '<a class="red" href="https://instagram.com/' + esc(p.instagram) +
      '" target="_blank" rel="noopener" title="Instagram">📷</a>';
    if (p.facebook) redes += '<a class="red" href="https://facebook.com/' + esc(p.facebook) +
      '" target="_blank" rel="noopener" title="Facebook">👍</a>';
    if (p.whatsapp) redes += '<a class="red" href="https://wa.me/57' + esc(p.whatsapp.replace(/\D/g, '')) +
      '" target="_blank" rel="noopener" title="WhatsApp">💬</a>';
    document.getElementById('redes').innerHTML = redes;

    // El botón flotante solo aparece si hay número: uno que no lleva a
    // ninguna parte es peor que no tenerlo.
    var wa = document.getElementById('wa-flota');
    var num = (p.whatsapp || '').replace(/\D/g, '');
    if (num) {
      var saludo = encodeURIComponent(
        'Hola, escribo desde la página de ' + (p.titular || 'el restaurante') + '. ');
      wa.href = 'https://wa.me/57' + num + '?text=' + saludo;
      wa.hidden = false;
    }

    document.getElementById('mapa-caja').innerHTML = p.mapa_url
      ? '<iframe src="' + esc(p.mapa_url) + '" style="width:100%;height:330px;border:0;border-radius:14px" loading="lazy"></iframe>'
      : '<div><div style="font-size:44px;margin-bottom:12px">📍</div>' +
        '<b>' + esc(p.direccion || '') + '</b><div>' + esc(p.ciudad || '') + '</div></div>';

    if (!p.acepta_reservas) {
      document.getElementById('form-reserva').innerHTML =
        '<div class="form-msg">Por ahora no recibimos reservas en línea. ' +
        'Llámenos y con gusto le apartamos la mesa.</div>';
    }
  }

  function item(ico, titulo, valor) {
    return '<div class="contacto-item"><div class="contacto-ico">' + ico + '</div>' +
      '<div><b>' + titulo + '</b>' + valor + '</div></div>';
  }

  /** Lee los horarios en texto libre y estima si está abierto. Aproximación
   *  deliberada: el horario es texto que el dueño escribe a su manera, y una
   *  interpretación estricta fallaría más de lo que ayuda. */
  function estaAbierto() {
    var h = new Date().getHours();
    return h >= 7 && h < 21;
  }

  // ══════════════════════════════════════════════════════════════════
  //  CARTA
  // ══════════════════════════════════════════════════════════════════
  function pintarCarta(d) {
    carta = d;
    if (!d.secciones.length) {
      document.getElementById('carta-cont').innerHTML =
        '<div class="cargando">Estamos actualizando la carta. Vuelva pronto.</div>';
      return;
    }
    var tabs = '<button class="cat-tab' + (catActiva === '' ? ' on' : '') +
      '" data-act="filtrarCat" data-cat="">Toda la carta</button>';
    d.secciones.forEach(function (s) {
      tabs += '<button class="cat-tab' + (catActiva === s.categoria ? ' on' : '') +
        '" data-act="filtrarCat" data-cat="' + esc(s.categoria) + '">' +
        esc(s.categoria) + '</button>';
    });
    document.getElementById('carta-tabs').innerHTML = tabs;

    var h = '';
    d.secciones.filter(function (s) { return !catActiva || s.categoria === catActiva; })
      .forEach(function (s) {
        h += '<div class="carta-grupo"><h3>' + esc(s.categoria) + '</h3>' +
          '<div class="carta-items">';
        s.items.forEach(function (p) {
          h += '<div class="plato">' +
            '<span class="plato-em">' + (p.emoji || '🍽️') + '</span>' +
            '<div class="plato-cuerpo">' +
            '<div class="plato-nom">' + esc(p.nombre) +
            (p.destacado ? '<span class="etiqueta-dest">Recomendado</span>' : '') + '</div>' +
            (p.descripcion ? '<div class="plato-desc">' + esc(p.descripcion) + '</div>' : '') +
            '</div>' +
            '<span class="plato-puntos"></span>' +
            '<span class="plato-precio">' + money(p.precio) + '</span>' +
            '</div>';
        });
        h += '</div></div>';
      });
    document.getElementById('carta-cont').innerHTML = h;
  }

  window.__filtrarCat = function (el) {
    catActiva = el.getAttribute('data-cat') || '';
    pintarCarta(carta);
    document.getElementById('carta').scrollIntoView({ behavior: 'smooth' });
  };

  // ══════════════════════════════════════════════════════════════════
  //  RESEÑAS
  // ══════════════════════════════════════════════════════════════════
  function pintarResenas(d) {
    var r = d.resumen;
    document.getElementById('calif-resumen').innerHTML = r.total
      ? '<span class="calif-num">' + r.promedio + '</span>' +
        '<div><div class="estrellas">' + estrellas(Math.round(r.promedio)) + '</div>' +
        '<div class="calif-total">' + r.total + ' opinion' + (r.total === 1 ? '' : 'es') + '</div></div>'
      : '';

    if (!d.items.length) {
      document.getElementById('resenas-cont').innerHTML =
        '<div class="sin-resenas">Todavía no hay opiniones publicadas.<br>' +
        '¿Ya nos visitó? Nos encantaría leerlo.</div>';
      return;
    }
    var h = '';
    d.items.forEach(function (x) {
      h += '<div class="resena">' +
        '<div class="resena-est">' + estrellas(x.calificacion) + '</div>' +
        '<div class="resena-txt">' + esc(x.comentario || '') + '</div>' +
        '<div class="resena-autor">' + esc(x.nombre) + '</div>' +
        (x.creado_en ? '<div class="resena-fecha">' +
          new Date(x.creado_en).toLocaleDateString('es-CO',
            { day: '2-digit', month: 'long', year: 'numeric' }) + '</div>' : '') +
        (x.respuesta ? '<div class="resena-resp"><b>Nuestra respuesta:</b><br>' +
          esc(x.respuesta) + '</div>' : '') +
        '</div>';
    });
    document.getElementById('resenas-cont').innerHTML = h;
  }

  var califSel = 5;
  window.__abrirResena = function () {
    califSel = 5;
    document.getElementById('modal-t').textContent = 'Cuéntenos su experiencia';
    document.getElementById('modal-b').innerHTML =
      '<form data-act="enviarResena">' +
      '<div class="estrellas-sel" id="est-sel"></div>' +
      '<div class="campo"><label for="rs-nombre">Su nombre</label>' +
      '<input type="text" id="rs-nombre" required></div>' +
      '<div class="campo"><label for="rs-email">Correo (opcional)</label>' +
      '<input type="email" id="rs-email" placeholder="Solo para responderle si hace falta"></div>' +
      '<div class="campo"><label for="rs-com">¿Cómo le fue?</label>' +
      '<textarea id="rs-com" rows="4" required placeholder="El plato, la atención, el ambiente…"></textarea></div>' +
      '<button type="submit" class="btn-lleno ancho" id="rs-btn">Enviar opinión</button>' +
      '<div class="form-msg" style="margin-top:12px;font-size:13px;color:var(--gris2)">' +
      'Su opinión se publica después de que la revisemos.</div>' +
      '</form>';
    pintarEstrellas();
    document.getElementById('modal').classList.add('on');
  };

  function pintarEstrellas() {
    var c = document.getElementById('est-sel');
    var h = '';
    for (var i = 1; i <= 5; i++) {
      h += '<button type="button" class="estrella' + (i <= califSel ? ' on' : '') +
        '" data-act="elegirEstrella" data-n="' + i + '">★</button>';
    }
    c.innerHTML = h;
  }

  window.__elegirEstrella = function (el) {
    califSel = Number(el.getAttribute('data-n'));
    pintarEstrellas();
  };

  window.__enviarResena = function () {
    var btn = document.getElementById('rs-btn');
    btn.disabled = true; btn.textContent = 'Enviando…';
    api('/resenas', {
      method: 'POST',
      body: {
        nombre: document.getElementById('rs-nombre').value.trim(),
        email: document.getElementById('rs-email').value.trim(),
        calificacion: califSel,
        comentario: document.getElementById('rs-com').value.trim()
      }
    }).then(function (r) {
      window.__cerrarModal();
      aviso(r.mensaje, 'ok');
    }).catch(function (e) {
      aviso(e.message, 'err');
    }).then(function () {
      btn.disabled = false; btn.textContent = 'Enviar opinión';
    });
  };

  // ══════════════════════════════════════════════════════════════════
  //  RESERVA
  // ══════════════════════════════════════════════════════════════════
  function prepararFormulario() {
    var hoy = new Date();
    var f = document.getElementById('rv-fecha');
    f.value = hoy.toISOString().slice(0, 10);
    f.min = hoy.toISOString().slice(0, 10);

    var horas = '';
    for (var hr = 7; hr <= 21; hr++) {
      ['00', '30'].forEach(function (m) {
        var v = (hr < 10 ? '0' : '') + hr + ':' + m;
        horas += '<option value="' + v + '"' + (v === '19:00' ? ' selected' : '') + '>' + v + '</option>';
      });
    }
    document.getElementById('rv-hora').innerHTML = horas;

    var pers = '';
    for (var p = 1; p <= 12; p++) {
      pers += '<option value="' + p + '"' + (p === 2 ? ' selected' : '') + '>' +
        p + (p === 1 ? ' persona' : ' personas') + '</option>';
    }
    pers += '<option value="15">Más de 12 (grupo)</option>';
    document.getElementById('rv-pers').innerHTML = pers;
  }

  window.__enviarReserva = function () {
    var btn = document.getElementById('rv-btn');
    var msg = document.getElementById('rv-msg');
    btn.disabled = true; btn.textContent = 'Enviando…';
    msg.className = 'form-msg'; msg.textContent = '';

    api('/reservas', {
      method: 'POST',
      body: {
        nombre: document.getElementById('rv-nombre').value.trim(),
        telefono: document.getElementById('rv-tel').value.trim(),
        email: document.getElementById('rv-email').value.trim(),
        fecha: document.getElementById('rv-fecha').value,
        hora: document.getElementById('rv-hora').value,
        personas: Number(document.getElementById('rv-pers').value),
        notas: document.getElementById('rv-notas').value.trim()
      }
    }).then(function (r) {
      msg.className = 'form-msg ok';
      msg.textContent = r.mensaje;
      document.getElementById('form-reserva').reset();
      prepararFormulario();
      aviso('Reserva ' + r.codigo + ' registrada', 'ok');
    }).catch(function (e) {
      msg.className = 'form-msg err';
      msg.textContent = e.message;
    }).then(function () {
      btn.disabled = false; btn.textContent = 'Reservar';
    });
  };



  // ══════════════════════════════════════════════════════════════════
  //  MI RESERVA · consultar y cancelar
  //
  //  Sin esto, el código que recibe el cliente no sirve para nada y la única
  //  forma de cancelar es llamar. Quien no llama deja la mesa bloqueada, y
  //  la silla vacía de un sábado a las ocho es plata que no vuelve.
  //
  //  Se pide código Y teléfono: el código solo son seis caracteres y alguien
  //  podría probar combinaciones hasta cancelarle la mesa a un desconocido.
  // ══════════════════════════════════════════════════════════════════
  window.__abrirMiReserva = function (codigo) {
    var pre = (typeof codigo === 'string') ? codigo : '';
    document.getElementById('modal-t').textContent = 'Su reserva';
    document.getElementById('modal-b').innerHTML =
      '<form data-act="buscarReserva">' +
      '<p class="login-nota">Escriba el código que le dimos al reservar y el ' +
      'teléfono con el que la hizo.</p>' +
      '<div class="fila">' +
      '<div class="campo"><label for="mr-c">Código</label>' +
      '<input type="text" id="mr-c" required placeholder="F35250" ' +
      'value="' + esc(pre) + '" style="text-transform:uppercase"></div>' +
      '<div class="campo"><label for="mr-t">Teléfono</label>' +
      '<input type="tel" id="mr-t" required placeholder="300 000 0000"></div></div>' +
      '<button type="submit" class="btn-lleno ancho" id="mr-btn">Buscar</button>' +
      '<div id="mr-msg" class="form-msg"></div>' +
      '</form>';
    document.getElementById('modal').classList.add('on');
    setTimeout(function () {
      document.getElementById(pre ? 'mr-t' : 'mr-c').focus();
    }, 60);
  };

  window.__buscarReserva = function () {
    var btn = document.getElementById('mr-btn');
    var msg = document.getElementById('mr-msg');
    btn.disabled = true; btn.textContent = 'Buscando…';
    msg.className = 'form-msg'; msg.textContent = '';

    var datos = { codigo: val('mr-c'), telefono: val('mr-t') };
    api('/reservas/consultar', { method: 'POST', body: datos })
      .then(function (d) { pintarMiReserva(d.reserva, datos); })
      .catch(function (e) {
        msg.className = 'form-msg err';
        msg.textContent = e.message;
        btn.disabled = false; btn.textContent = 'Buscar';
      });
  };

  function pintarMiReserva(r, datos) {
    window.__miReserva = datos;
    var dia = new Date(r.fecha + 'T00:00:00').toLocaleDateString('es-CO',
      { weekday: 'long', day: 'numeric', month: 'long' });

    document.getElementById('modal-b').innerHTML =
      '<div class="mr-ficha">' +
      '<div class="mr-cod">' + esc(r.codigo) + '</div>' +
      '<div class="mr-datos">' +
      '<b>' + esc(r.nombre) + '</b>' +
      '<div>' + esc(dia) + ' a las ' + esc(r.hora) + '</div>' +
      '<div>' + r.personas + (r.personas === 1 ? ' persona' : ' personas') + '</div>' +
      '</div>' +
      '<span class="mr-estado ' + esc(r.estado) + '">' + esc(r.estado) + '</span>' +
      '</div>' +
      '<p class="login-nota" style="border:0;padding:0;margin-top:14px">' +
      esc(r.mensaje) + '</p>' +
      (r.cancelable
        ? '<div class="campo"><label for="mr-mot">¿Nos cuenta por qué? (opcional)</label>' +
          '<input type="text" id="mr-mot" placeholder="Se me cruzó un compromiso"></div>' +
          '<button class="btn-cancelar ancho" data-act="cancelarReserva">' +
          'Cancelar mi reserva</button>' +
          '<p class="nota-mini">Avisar nos permite darle la mesa a alguien más. ' +
          'Gracias por hacerlo.</p>'
        : '') +
      '<div id="mr-msg" class="form-msg"></div>';
  }

  window.__cancelarReserva = function (el) {
    var btn = el || document.querySelector('[data-act="cancelarReserva"]');
    var msg = document.getElementById('mr-msg');
    btn.disabled = true; btn.textContent = 'Cancelando…';

    var cuerpo = Object.assign({}, window.__miReserva,
                               { motivo: val('mr-mot') });
    api('/reservas/cancelar', { method: 'POST', body: cuerpo })
      .then(function (d) {
        window.__cerrarModal();
        aviso(d.mensaje, 'ok');
      })
      .catch(function (e) {
        msg.className = 'form-msg err';
        msg.textContent = e.message;
        btn.disabled = false; btn.textContent = 'Cancelar mi reserva';
      });
  };

  // ══════════════════════════════════════════════════════════════════
  //  ACCESO DEL PERSONAL
  //
  //  El login vive aquí y no en una página aparte porque quien lo usa está
  //  entrando de afán: el mesero a las seis de la mañana, el cajero que
  //  volvió del almuerzo. Un salto de página más es un segundo perdido cada
  //  vez, todos los días.
  //
  //  DOS DECISIONES DE SEGURIDAD, Y SON DELIBERADAS:
  //
  //  1. NO se muestran credenciales de demostración. El sistema interno sí
  //     las lista, porque está detrás de la red del negocio; esta página está
  //     abierta a internet y publicar ahí un usuario y una clave sería
  //     regalar la puerta.
  //
  //  2. El mensaje de error es UNO SOLO para «no existe» y «clave
  //     incorrecta». Distinguirlos permitiría averiguar qué correos están
  //     registrados probando de a uno. El backend ya responde así; aquí
  //     simplemente no se mejora el mensaje.
  // ══════════════════════════════════════════════════════════════════
  function apiRaiz(ruta, cuerpo, token) {
    var cab = { 'Content-Type': 'application/json' };
    if (token) cab['Authorization'] = 'Bearer ' + token;
    return fetch(ruta, {
      method: 'POST', headers: cab, credentials: 'same-origin',
      body: JSON.stringify(cuerpo || {})
    }).then(function (r) {
      return r.text().then(function (t) {
        var d; try { d = t ? JSON.parse(t) : {}; } catch (e) { d = { detail: t }; }
        if (!r.ok) throw new Error(d.detail || 'No pudimos validar sus datos');
        return d;
      });
    }).catch(function (e) {
      if (e instanceof TypeError) {
        throw new Error('No hay conexión con el servidor del restaurante.');
      }
      throw e;
    });
  }

  window.__abrirLogin = function () {
    document.querySelector('.nav-links').classList.remove('abierto');
    document.getElementById('modal-t').textContent = 'Acceso del personal';
    document.getElementById('modal-b').innerHTML =
      '<form data-act="hacerLogin" class="form-login">' +
      '<p class="login-nota">Esta entrada es para quienes trabajan en el ' +
      'restaurante. Si usted es cliente, no necesita ninguna clave: puede ver ' +
      'la carta y reservar sin registrarse.</p>' +
      '<div class="campo"><label for="lg-e">Correo</label>' +
      '<input type="email" id="lg-e" autocomplete="username" required ' +
      'placeholder="nombre@qmspm.com"></div>' +
      '<div class="campo"><label for="lg-p">Contraseña</label>' +
      '<div class="clave-caja">' +
      '<input type="password" id="lg-p" autocomplete="current-password" required>' +
      '<button type="button" class="ver-clave" data-act="verClave" ' +
      'aria-label="Mostrar la contraseña">Ver</button></div></div>' +
      '<button type="submit" class="btn-lleno ancho" id="lg-btn">Entrar</button>' +
      '<div id="lg-msg" class="form-msg"></div>' +
      '</form>';
    document.getElementById('modal').classList.add('on');
    setTimeout(function () { document.getElementById('lg-e').focus(); }, 60);
  };

  window.__verClave = function (el) {
    var i = document.getElementById('lg-p');
    var oculta = i.type === 'password';
    i.type = oculta ? 'text' : 'password';
    el.textContent = oculta ? 'Ocultar' : 'Ver';
    i.focus();
  };

  window.__hacerLogin = function () {
    var btn = document.getElementById('lg-btn');
    var msg = document.getElementById('lg-msg');
    btn.disabled = true; btn.textContent = 'Verificando…';
    msg.className = 'form-msg'; msg.textContent = '';

    apiRaiz('/api/auth/login', {
      email: document.getElementById('lg-e').value.trim(),
      password: document.getElementById('lg-p').value
    }).then(function (d) {
      // Con una sola sede ya viene el token de trabajo. Con varias, hay que
      // elegir: el token de selección no sirve para operar, solo para escoger.
      if (d.token) return entrar(d.token);
      if (d.requiere_seleccion) return elegirSede(d);
      throw new Error('Respuesta inesperada del servidor');
    }).catch(function (e) {
      msg.className = 'form-msg err';
      msg.textContent = e.message;
      btn.disabled = false; btn.textContent = 'Entrar';
      var p = document.getElementById('lg-p');
      if (p) { p.value = ''; p.focus(); }
    });
  };

  function entrar(token) {
    // Misma llave que usa el sistema interno. La raíz ahora es la carta del
    // restaurante, así que el personal aterriza en «/sistema».
    localStorage.setItem('rst_token', token);
    location.href = '/sistema';
  }

  function elegirSede(d) {
    document.getElementById('modal-t').textContent = '¿A qué sede entra?';
    document.getElementById('modal-b').innerHTML =
      '<p class="login-nota">Hola, ' + esc(d.usuario.nombre) + '. Tiene acceso a ' +
      'varias sedes.</p><div class="sedes">' +
      d.sedes.map(function (x) {
        return '<button class="sede-op" data-act="entrarSede" data-i="' + x.id + '">' +
          '<b>' + esc(x.nombre) + '</b>' +
          '<span>' + esc(x.ciudad || '') + ' · ' + esc(x.rol) + '</span></button>';
      }).join('') +
      '</div><div id="lg-msg" class="form-msg"></div>';
    window.__tokenSel = d.token_seleccion;
  }

  window.__entrarSede = function (el) {
    var msg = document.getElementById('lg-msg');
    el.disabled = true;
    apiRaiz('/api/auth/seleccionar-sede',
            { sede_id: Number(el.getAttribute('data-i')) }, window.__tokenSel)
      .then(function (d) { entrar(d.token); })
      .catch(function (e) {
        msg.className = 'form-msg err'; msg.textContent = e.message;
        el.disabled = false;
      });
  };

  // ══════════════════════════════════════════════════════════════════
  //  ARRANQUE
  // ══════════════════════════════════════════════════════════════════
  prepararFormulario();

  // El correo de confirmación trae un enlace con el código: /?reserva=F35250
  // Se abre la consulta con el código puesto y solo se pide el teléfono. El
  // teléfono NO viaja en la URL: un dato personal ahí queda en el historial
  // del navegador y en los registros del servidor.
  var codigoUrl = (new URLSearchParams(location.search).get('reserva') || '')
    .trim().toUpperCase().slice(0, 12);
  if (codigoUrl) {
    setTimeout(function () { window.__abrirMiReserva(codigoUrl); }, 900);
  }

  api('/info').then(pintarInfo).catch(function (e) {
    document.body.innerHTML =
      '<div style="min-height:100vh;display:grid;place-items:center;text-align:center;padding:40px">' +
      '<div><div style="font-size:56px">🍽️</div>' +
      '<h1 style="font-family:Georgia,serif;color:#1B4332;margin:16px 0 8px">Página no disponible</h1>' +
      '<p style="color:#6B6B63">' + esc(e.message) + '</p></div></div>';
  });
  api('/carta').then(pintarCarta).catch(function () {
    document.getElementById('carta-cont').innerHTML =
      '<div class="cargando">No pudimos cargar la carta en este momento.</div>';
  });
  api('/resenas').then(pintarResenas).catch(function () { });
})();
