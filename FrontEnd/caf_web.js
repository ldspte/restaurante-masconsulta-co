/* ══════════════════════════════════════════════════════════════════════
   RESTAURANTE · Módulo SITIO WEB

   La cara que ve el cliente, administrada desde adentro. Tres cosas:

   · LOS DATOS del restaurante — dirección, horarios, teléfono. Lo aburrido
     y lo que más se consulta.
   · QUÉ SALE EN LA CARTA — no todo lo que se vende se publica. El almuerzo
     del personal y los preparados de cocina existen en el sistema y no
     tienen por qué aparecerle a nadie.
   · LA MODERACIÓN de reseñas — nacen pendientes y alguien decide. Publicar
     automáticamente lo que escribe un desconocido convierte la página del
     negocio en un tablón abierto a insultos.

   El botón «Ver el sitio» abre la página real, no una vista previa
   simulada: la única forma honesta de saber cómo quedó.

   Backend: /api/sitio/*
   ══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var COLOR = '#DB2777';
  var pestana = 'datos';

  window.webInyectar = function () {
    crearPagina('web', '🌐', 'Sitio web del restaurante',
      'Lo que ve el cliente: datos, carta publicada y las opiniones que ' +
      'esperan revisión.', COLOR);
    document.getElementById('acc-web').innerHTML =
      '<button class="btn" data-act="webVer">↗ Ver el sitio</button>';
  };

  window.webAlAbrir = function () { cargar(); };

  window.webVer = function () {
    var slug = (RST.sede && (RST.sede.slug || RST.sede.codigo)) || 'central';
    window.open('/?sede=' + encodeURIComponent(slug), '_blank', 'noopener');
  };

  function cargar() {
    cargando('cont-web');
    Promise.all([api('/api/sitio/perfil'), api('/api/sitio/carta'),
                 api('/api/sitio/resenas')])
      .then(function (r) { pintar(r[0], r[1], r[2]); })
      .catch(errToast);
  }

  function pintar(per, car, res) {
    var p = per.perfil || {}, k = res.kpis || {};
    var h = '<div class="grid g4" style="margin-bottom:16px">' +
      kpi('Estado', p.publicado ? 'Publicado' : 'Oculto',
          p.publicado ? 'El sitio está en línea' : 'Nadie lo puede ver',
          p.publicado ? 'ok' : 'bad') +
      kpi('En la carta', car.publicados || 0,
          (car.destacados || 0) + ' recomendados', 'info') +
      kpi('Calificación', k.promedio == null ? '—' : numero(k.promedio, 1),
          (k.publicadas || 0) + ' opiniones publicadas', 'ok') +
      kpi('Por revisar', k.pendientes || 0, 'Esperan moderación',
          (k.pendientes || 0) > 0 ? 'warn' : 'ok') +
      '</div>';

    // La dirección pública, visible y copiable. Antes solo existía el botón
    // «Ver el sitio», que abre con window.open: discreto de encontrar y, si el
    // navegador bloquea emergentes, no pasa nada y nadie se entera.
    // La raíz del dominio es la carta: es la dirección que se le da al cliente.
    var url = location.origin + '/?sede=' +
      encodeURIComponent((RST.sede && RST.sede.slug) || 'central');
    h += '<div class="url-publica">' +
      '<span class="up-et">La cara visible · esto es lo que ve su cliente</span>' +
      '<a class="up-link" href="' + url + '" target="_blank" rel="noopener">' + esc(url) + '</a>' +
      '<button class="btn btn-sm" data-act="webCopiar" data-u="' + esc(url) + '">Copiar</button>' +
      '<a class="btn btn-sm btn-p" href="' + url + '" target="_blank" rel="noopener">Abrir ↗</a>' +
      '</div>';

    if (k.pendientes) {
      h += '<div class="aviso-alerta" style="margin-bottom:14px">💬 Hay ' + k.pendientes +
        ' opinión(es) esperando revisión. Mientras no se aprueben, nadie las ve.</div>';
    }
    if (!p.publicado) {
      h += '<div class="aviso-alerta" style="margin-bottom:14px">🔒 El sitio está oculto. ' +
        'Actívelo en «Datos del restaurante» cuando esté listo.</div>';
    }

    h += '<div class="tabs">' +
      tab('datos', '🏠 Datos del restaurante') +
      tab('carta', '🍽️ Qué sale en la carta') +
      tab('resenas', '💬 Opiniones' + (k.pendientes ? ' (' + k.pendientes + ')' : '')) +
      '</div><div id="web-cuerpo"></div>';

    document.getElementById('cont-web').innerHTML = h;
    cuerpo(p, car, res);
  }

  function tab(k, t) {
    return '<button class="tab' + (pestana === k ? ' on' : '') +
      '" data-act="webTab" data-k="' + k + '">' + t + '</button>';
  }

  window.webTab = function () { pestana = this.getAttribute('data-k'); cargar(); };

  function cuerpo(p, car, res) {
    var h = '';

    // ── Datos ─────────────────────────────────────────────────────────
    if (pestana === 'datos') {
      h += '<div class="card"><div class="card-h">🏠 Lo que el cliente lee</div>' +
        '<div class="card-b">' +
        '<div class="fila"><div class="campo" style="flex:2">' +
        '<label for="wp-t">Nombre del restaurante</label>' +
        '<input type="text" id="wp-t" value="' + esc(p.titular || '') + '"></div>' +
        '<div class="campo" style="flex:2"><label for="wp-l">Lema</label>' +
        '<input type="text" id="wp-l" value="' + esc(p.lema || '') +
        '" placeholder="Cocina de siempre, con producto de hoy"></div></div>' +
        '<div class="campo"><label for="wp-d">Descripción</label>' +
        '<textarea id="wp-d" rows="3">' + esc(p.descripcion || '') + '</textarea>' +
        '<div class="sug">Dos o tres frases. Es lo primero que se lee bajo el nombre.</div>' +
        '</div>' +
        '<div class="fila"><div class="campo" style="flex:2">' +
        '<label for="wp-dir">Dirección</label>' +
        '<input type="text" id="wp-dir" value="' + esc(p.direccion || '') + '"></div>' +
        '<div class="campo"><label for="wp-c">Ciudad</label>' +
        '<input type="text" id="wp-c" value="' + esc(p.ciudad || '') + '"></div></div>' +
        '<div class="fila"><div class="campo"><label for="wp-tel">Teléfono</label>' +
        '<input type="text" id="wp-tel" value="' + esc(p.telefono || '') + '"></div>' +
        '<div class="campo"><label for="wp-wa">WhatsApp</label>' +
        '<input type="text" id="wp-wa" value="' + esc(p.whatsapp || '') + '"></div>' +
        '<div class="campo"><label for="wp-e">Correo</label>' +
        '<input type="email" id="wp-e" value="' + esc(p.email || '') + '"></div></div>' +
        '<div class="fila"><div class="campo"><label for="wp-ig">Instagram</label>' +
        '<input type="text" id="wp-ig" value="' + esc(p.instagram || '') +
        '" placeholder="sin la arroba"></div>' +
        '<div class="campo"><label for="wp-fb">Facebook</label>' +
        '<input type="text" id="wp-fb" value="' + esc(p.facebook || '') + '"></div></div>' +
        '<div class="campo"><label for="wp-h">Horarios</label>' +
        '<textarea id="wp-h" rows="3">' + esc(p.horarios || '') + '</textarea>' +
        '<div class="sug">Una línea por rango. Se muestra tal cual, así que escríbalo ' +
        'como quiere que se lea.</div></div>' +
        '<div class="campo"><label for="wp-m">Mapa incrustado (URL de Google Maps)</label>' +
        '<input type="text" id="wp-m" value="' + esc(p.mapa_url || '') + '"></div>' +
        '<div class="fila"><div class="campo"><label>' +
        '<input type="checkbox" id="wp-ar"' + (p.acepta_reservas ? ' checked' : '') +
        '> Recibir reservas en línea</label></div>' +
        '<div class="campo"><label>' +
        '<input type="checkbox" id="wp-pu"' + (p.publicado ? ' checked' : '') +
        '> Sitio visible al público</label></div>' +
        '<div class="campo"><label for="wp-af">Aforo máximo</label>' +
        '<input type="number" id="wp-af" min="0" value="' + (p.aforo_max || 0) +
        '"></div></div>' +
        '<button class="btn btn-p" data-act="webGuardar">Guardar</button>' +
        '</div></div>';
    }

    // ── Carta ─────────────────────────────────────────────────────────
    if (pestana === 'carta') {
      h += '<div class="card"><div class="card-h">🍽️ Qué se publica</div>' +
        '<div class="card-b">' +
        '<p class="nota">No todo lo que se vende se publica. Los preparados de cocina ' +
        'y lo que se hace por encargo existen en el sistema y no tienen por qué ' +
        'aparecerle a nadie.</p>' +
        '<div class="tabla-wrap"><table><thead><tr><th style="width:70px">Publicar</th>' +
        '<th style="width:80px">Destacar</th><th>Producto</th>' +
        '<th class="num">Precio</th><th>Descripción para el cliente</th>' +
        '<th style="width:70px">Orden</th><th></th></tr></thead><tbody>';
      (car.items || []).forEach(function (i) {
        h += '<tr' + (i.activo ? '' : ' class="fila-baja"') + '>' +
          '<td><input type="checkbox" id="cw-v' + i.id + '"' +
          (i.visible ? ' checked' : '') + '></td>' +
          '<td><input type="checkbox" id="cw-d' + i.id + '"' +
          (i.destacado ? ' checked' : '') + '></td>' +
          '<td><b>' + (i.emoji || '') + ' ' + esc(i.nombre) + '</b>' +
          '<div class="sug">' + esc(i.categoria) +
          (i.activo ? '' : ' · producto inactivo') + '</div></td>' +
          '<td class="num">' + money(i.precio) + '</td>' +
          '<td><input type="text" id="cw-t' + i.id + '" value="' +
          esc(i.descripcion || '') + '" placeholder="Cómo se lo describe al cliente"></td>' +
          '<td><input type="number" id="cw-o' + i.id + '" value="' + (i.orden || 0) +
          '" style="width:60px"></td>' +
          '<td><button class="btn btn-sm" data-act="webCarta" data-id="' + i.id +
          '">Guardar</button></td></tr>';
      });
      h += '</tbody></table></div></div></div>';
    }

    // ── Reseñas ───────────────────────────────────────────────────────
    if (pestana === 'resenas') {
      h += '<div class="card"><div class="card-h">💬 Opiniones de los clientes</div>' +
        '<div class="card-b">';
      if (!(res.items || []).length) {
        h += vacio('💬', 'Todavía nadie ha escrito. Las opiniones llegan desde el sitio.');
      } else {
        res.items.forEach(function (r) {
          h += '<div class="resena-adm ' + r.estado + '">' +
            '<div class="ra-cab">' +
            '<span class="ra-est">' + '★'.repeat(r.calificacion) +
            '☆'.repeat(5 - r.calificacion) + '</span>' +
            '<b>' + esc(r.nombre) + '</b>' +
            '<span class="sug">' + fecha(r.creado_en, true) +
            (r.email ? ' · ' + esc(r.email) : '') + '</span>' +
            '<div class="sp"></div>' +
            '<span class="pill ' + (r.estado === 'publicada' ? 'ok'
              : r.estado === 'rechazada' ? 'bad' : 'warn') + '">' +
            esc(r.estado) + '</span></div>' +
            '<div class="ra-txt">' + esc(r.comentario || '') + '</div>' +
            (r.respuesta
              ? '<div class="ra-resp"><b>Su respuesta:</b> ' + esc(r.respuesta) + '</div>'
              : '') +
            '<div class="btns">' +
            (r.estado !== 'publicada'
              ? '<button class="btn btn-sm btn-g" data-act="webModerar" data-id="' + r.id +
                '" data-e="publicada">Publicar</button>' : '') +
            (r.estado !== 'rechazada'
              ? '<button class="btn btn-sm btn-d" data-act="webModerar" data-id="' + r.id +
                '" data-e="rechazada">Rechazar</button>' : '') +
            '<button class="btn btn-sm" data-act="webResponder" data-id="' + r.id +
            '" data-r="' + esc(r.respuesta || '') + '">Responder</button>' +
            '</div></div>';
        });
        h += '<p class="nota">Responder en público a una crítica es la mejor herramienta ' +
          'que tiene un restaurante pequeño. Quien lee las opiniones también lee las ' +
          'respuestas.</p>';
      }
      h += '</div></div>';
    }

    document.getElementById('web-cuerpo').innerHTML = h;
  }

  function kpi(k, v, d, clase) {
    return '<div class="kpi ' + (clase || '') + '"><div class="k">' + k + '</div>' +
      '<div class="v">' + v + '</div><div class="d">' + esc(d) + '</div></div>';
  }

  // ══════════════════════════════════════════════════════════════════
  window.webCopiar = function () {
    var el = this;
    var u = el.getAttribute('data-u');
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(u)
        .then(function () { toast('Dirección copiada', 'ok'); })
        .catch(function () { seleccionar(u); });
    } else {
      seleccionar(u);
    }
  };

  /** Respaldo cuando el portapapeles está bloqueado: se deja seleccionada para
   *  que un Ctrl+C la tome. Es preferible a un mensaje de error sin salida. */
  function seleccionar(u) {
    var i = document.createElement('input');
    i.value = u; document.body.appendChild(i); i.select();
    try { document.execCommand('copy'); toast('Dirección copiada', 'ok'); }
    catch (e) { toast('Copie la dirección con Ctrl+C', 'warn'); }
    document.body.removeChild(i);
  }

  window.webGuardar = function () {
    api('/api/sitio/perfil', {
      method: 'PUT',
      body: {
        titular: val('wp-t'), lema: val('wp-l'), descripcion: val('wp-d'),
        direccion: val('wp-dir'), ciudad: val('wp-c'), telefono: val('wp-tel'),
        whatsapp: val('wp-wa'), email: val('wp-e'), instagram: val('wp-ig'),
        facebook: val('wp-fb'), horarios: val('wp-h'), mapa_url: val('wp-m'),
        acepta_reservas: document.getElementById('wp-ar').checked,
        publicado: document.getElementById('wp-pu').checked,
        aforo_max: parseInt(val('wp-af') || '0', 10)
      }
    }).then(function (r) { toast(r.mensaje, 'ok'); cargar(); }).catch(errToast);
  };

  window.webCarta = function () {
    var el = this;
    var id = el.getAttribute('data-id');
    api('/api/sitio/carta/' + id, {
      method: 'PUT',
      body: {
        visible: document.getElementById('cw-v' + id).checked,
        destacado: document.getElementById('cw-d' + id).checked,
        descripcion: val('cw-t' + id),
        orden: parseInt(val('cw-o' + id) || '0', 10)
      }
    }).then(function () { toast('Carta actualizada', 'ok'); }).catch(errToast);
  };

  window.webModerar = function () {
    var el = this;
    api('/api/sitio/resenas/' + el.getAttribute('data-id'), {
      method: 'PUT', body: { estado: el.getAttribute('data-e') }
    }).then(function (r) { toast(r.mensaje, 'ok'); cargar(); }).catch(errToast);
  };

  window.webResponder = function () {
    var el = this;
    var id = el.getAttribute('data-id');
    modal('Responder a la opinión',
      '<div class="campo"><label for="rr-t">Su respuesta</label>' +
      '<textarea id="rr-t" rows="4">' + esc(el.getAttribute('data-r') || '') +
      '</textarea></div>' +
      '<p class="nota">Se publica junto a la opinión, firmada por el restaurante. ' +
      'Una respuesta corta y concreta vale más que una disculpa larga.</p>',
      'Publicar respuesta', function () {
        api('/api/sitio/resenas/' + id, {
          method: 'PUT', body: { respuesta: val('rr-t') }
        }).then(function (r) { modalCerrar(); toast(r.mensaje, 'ok'); cargar(); })
          .catch(errToast);
      });
  };
})();
