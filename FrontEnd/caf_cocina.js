/* ══════════════════════════════════════════════════════════════════════
   RESTAURANTE · Módulo COCINA (KDS · pantalla de preparación)

   Esta pantalla se mira desde metro y medio, con las manos ocupadas y a veces
   con vapor de por medio. Eso manda sobre todo lo demás:

     · Tipografía grande y contraste alto.
     · Un solo toque por acción; nada de menús ni modales.
     · El semáforo lo da el TIEMPO, no el número de comanda: en cocina manda
       quién lleva más esperando.

   Se refresca sola cada 10 segundos —los pedidos entran desde el salón— y
   nunca pide confirmación: confirmar cada plato listo sería inoperante en
   servicio.

   Backend: /api/cocina/*
   ══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var COLOR = '#DC2626';
  var datos = null, reloj = null, estacion = 0;

  window.cocinaInyectar = function () {
    crearPagina('cocina', '🔥', 'Cocina',
      'Cocina marca «listo» cuando el plato sale. El mesero marca que lo llevó a la mesa.',
      COLOR);
    var acc = document.getElementById('acc-cocina');
    if (acc && !acc.innerHTML) {
      acc.innerHTML = '<button class="btn" data-act="cocinaAlAbrir">↻ Actualizar</button>';
    }
  };

  window.cocinaAlAbrir = function () {
    cargando('cont-cocina');
    cargar();
    clearInterval(reloj);
    reloj = setInterval(function () {
      if (document.getElementById('page-cocina').classList.contains('on')) cargar(true);
      else clearInterval(reloj);
    }, 10000);
  };

  function cargar(silencioso) {
    api('/api/cocina/cola' + (estacion ? '?estacion_id=' + estacion : ''))
      .then(function (r) { datos = r; pintar(); })
      .catch(function (e) {
        if (!silencioso) {
          document.getElementById('cont-cocina').innerHTML =
            '<div class="aviso e">' + esc(e.message) + '</div>';
        }
      });
  }

  function pintar() {
    var k = datos.kpis;
    var h = '<div class="grid g3 mb">' +
      kpi('En preparación', String(k.en_preparacion), 'Platos en curso',
          k.en_preparacion ? 'warn' : 'ok') +
      kpi('Listos por entregar', String(k.listos), 'Esperando al mesero',
          k.listos ? 'info' : 'ok') +
      kpi('Retrasados', String(k.retrasados), 'Pasaron el doble del tiempo',
          k.retrasados ? 'bad' : 'ok') +
      '</div>';

    // Selector de estación: cada puesto ve lo suyo.
    h += '<div class="tabs"><button class="tab' + (estacion === 0 ? ' on' : '') +
      '" data-act="cocinaEstacion" data-args="0">Todas</button>';
    (datos.estaciones || []).forEach(function (e) {
      h += '<button class="tab' + (estacion === e.id ? ' on' : '') +
        '" data-act="cocinaEstacion" data-args="' + e.id + '">' +
        (e.icono || '') + ' ' + esc(e.nombre) +
        (e.pendientes ? ' <span class="tag t-warn">' + e.pendientes + '</span>' : '') +
        '</button>';
    });
    h += '</div>';

    if (!datos.items.length) {
      document.getElementById('cont-cocina').innerHTML = h +
        '<div class="vacio" style="padding:60px 20px"><span class="e" style="font-size:60px">✅</span>' +
        '<div style="font-size:18px;font-weight:700">Cocina al día</div>' +
        '<div class="mut">No hay platos pendientes de preparar.</div></div>';
      return;
    }

    h += '<div class="kds">';
    datos.items.forEach(function (it) {
      var listo = it.estado === 'listo';
      var clase = listo ? 'listo' : it.alerta;
      h += '<div class="kds-card ' + clase + '">' +
        '<div class="kds-top" style="background:' + esc(it.estacion_color) + '">' +
        '<span>' + (it.mesa ? 'Mesa ' + esc(it.mesa) : esc(it.tipo)) + '</span>' +
        // El puesto va aquí y no en letra pequeña: es el dato que evita que el
        // mesero llegue a la mesa preguntando de quién era cada plato.
        (Number(it.puesto) > 0
          ? '<span class="kds-puesto">Asiento ' + Number(it.puesto) + '</span>' : '') +
        '<span class="kds-min">' + (it.minutos != null ? it.minutos + '′' : '') + '</span>' +
        '</div>' +
        '<div class="kds-body">' +
        '<div class="kds-cant">' + numero(it.cantidad, 0) + '×</div>' +
        '<div class="kds-nom">' + esc(it.nombre) + '</div>' +
        (it.notas ? '<div class="kds-nota">⚠ ' + esc(it.notas) + '</div>' : '') +
        '<div class="peq mut">' + esc(it.estacion) +
        (it.mesero ? ' · ' + esc(String(it.mesero).split(' ')[0]) : '') + '</div>' +
        '</div>' +
        '<div class="kds-pie">' +
        (listo
          // Esta pantalla vive EN EL PASE, que es justo donde el mesero
          // recoge el plato. Dejar aqui solo el cartel «esperando al mesero»
          // obligaba a ir a otra pantalla a decir que ya se lo llevo, y la
          // comida no se lleva sola: el plato se quedaba en «listo» para
          // siempre. Quien no puede entregar sigue viendo el cartel.
          ? (puedeEntregar()
             ? '<button class="btn btn-g" style="width:100%;padding:13px;font-size:16px" ' +
               'data-act="cocinaEntregar" data-args="' + arg(it.id) + '">' +
               '🛎 LO LLEVO A LA MESA</button>'
             : '<div class="kds-espera">✅ Listo · esperando al mesero</div>')
          : '<button class="btn btn-g" style="width:100%;padding:13px;font-size:16px" ' +
            'data-act="cocinaListo" data-args="' + arg(it.id) + '">✓ LISTO</button>') +
        '</div></div>';
    });
    h += '</div>';

    document.getElementById('cont-cocina').innerHTML = h;
  }

  window.cocinaEstacion = function (id) { estacion = Number(id) || 0; cargar(); };

  /** Marcar la entrega es del personal de SALON: el backend lo exige y
   *  devuelve 403 a quien no lo sea. Ocultar el boton no protege nada —el
   *  endpoint tiene su propia guarda— pero evita ofrecer una accion que van a
   *  negar.
   *
   *  Se oculta por LISTA NEGRA, no blanca: solo a quien seguro no puede. Si el
   *  rol llega vacio o es uno nuevo que aun no esta en esta lista, el boton se
   *  muestra. Equivocarse hacia el otro lado deja la pantalla muerta sin
   *  explicar por que, que es exactamente el error que se acaba de corregir. */
  var ROLES_SIN_ENTREGA = ['cocina', 'bodega'];
  function puedeEntregar() {
    return ROLES_SIN_ENTREGA.indexOf((window.RST || {}).rol) === -1;
  }

  window.cocinaEntregar = function (id) {
    // Sin confirmacion, igual que «listo»: el mesero tiene la bandeja en la
    // mano. Un modal por plato es inoperante en pleno servicio.
    api('/api/cocina/items/' + id + '/estado',
        { method: 'POST', body: { estado: 'entregado' } })
      .then(function () { toast('Entregado en la mesa', 'ok'); cargar(); })
      .catch(errToast);
  };

  window.cocinaListo = function (id) {
    // Sin confirmación: en servicio, un modal por plato es inoperante. Si se
    // marca por error, el mesero lo devuelve a preparación desde su pantalla.
    api('/api/cocina/items/' + id + '/estado', { method: 'POST', body: { estado: 'listo' } })
      .then(function () { toast('Plato listo', 'ok'); cargar(); })
      .catch(errToast);
  };

  function kpi(t, v, d, c) {
    return '<div class="kpi ' + (c || '') + '"><div class="k">' + esc(t) + '</div>' +
      '<div class="v">' + esc(v) + '</div><div class="d">' + esc(d) + '</div></div>';
  }
})();
