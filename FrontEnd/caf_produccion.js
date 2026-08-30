/* ══════════════════════════════════════════════════════════════════════
   RESTAURANTE · Módulo PRODUCCIÓN

   Lo que la cafetería fabrica en vez de comprar: el pan de las cuatro de la
   mañana, la olla de arroz, los fríjoles, la carne guisada.

   La pieza que hace este módulo distinto de un simple «armar recetas» es el
   RENDIMIENTO REAL. La ficha dice que salen cuarenta panes; salieron treinta
   y ocho. Esos dos panes no se perdieron en el aire: son merma, y el sistema
   la pide al terminar la orden en vez de asumir que la ficha se cumplió.
   Asumirlo produciría, mes a mes, un inventario teórico que nadie encuentra
   en la bodega.

   Backend: /api/produccion/*
   ══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var COLOR = '#D97706';
  var fichas = [];

  window.produccionInyectar = function () {
    crearPagina('produccion', '🥖', 'Producción propia',
      'Las ollas y las horneadas del día. Lo que se fabrica aquí entra al ' +
      'inventario como insumo.', COLOR);
    document.getElementById('acc-produccion').innerHTML =
      '<button class="btn btn-p" data-act="prdNueva">＋ Programar producción</button>';
  };

  window.produccionAlAbrir = function () { cargar(); };

  function cargar() {
    cargando('cont-produccion');
    Promise.all([api('/api/produccion/ordenes'), api('/api/produccion/fichas')])
      .then(function (r) { fichas = r[1].items || []; pintar(r[0], r[1]); })
      .catch(errToast);
  }

  function pintar(ord, fi) {
    var k = ord.kpis || {};
    var h = '<div class="grid g4" style="margin-bottom:16px">' +
      kpi('Programadas', k.programadas || 0, 'Todavía sin empezar', 'info') +
      kpi('En proceso', k.en_proceso || 0, 'En el horno o en la estufa', 'warn') +
      kpi('Terminadas', k.terminadas || 0, 'Ya entraron a inventario', 'ok') +
      kpi('Costo del período', money(k.costo_periodo), 'Insumos + mano de obra', '') +
      '</div>';

    // ── Fichas ────────────────────────────────────────────────────────
    h += '<div class="card" style="margin-bottom:16px"><div class="card-h">' +
      '📋 Fichas técnicas · lo que se sabe fabricar</div><div class="card-b">' +
      '<div class="grid g3">';
    (fi.items || []).forEach(function (f) {
      h += '<div class="ficha-prod" style="border-top:3px solid ' +
        (f.estacion_color || COLOR) + '">' +
        '<div class="fp-nom">' + esc(f.nombre) + '</div>' +
        '<div class="fp-dest">→ ' + esc(f.destino) + '</div>' +
        '<div class="fp-datos"><span>Rinde <b>' + numero(f.rendimiento, 0) + ' ' +
        esc(f.unidad || '') + '</b></span><span>' + f.minutos + ' min</span></div>' +
        '<div class="sug">' + esc(f.estacion || '') + ' · en bodega ' +
        numero(f.stock_destino, 0) + '</div>' +
        '<button class="btn btn-sm btn-p ancho" data-act="prdNueva" data-f="' + f.id +
        '">Producir</button></div>';
    });
    h += '</div></div></div>';

    // ── Órdenes ───────────────────────────────────────────────────────
    h += '<div class="card"><div class="card-h">🔥 Órdenes de producción</div>' +
      '<div class="card-b">';
    if (!(ord.items || []).length) {
      h += vacio('🥖', 'No hay órdenes. Programe una desde las fichas de arriba.');
    } else {
      h += '<div class="tabla-wrap"><table><thead><tr><th>Orden</th><th>Qué</th>' +
        '<th class="num">Lotes</th><th class="num">Producido</th><th class="num">Merma</th>' +
        '<th class="num">Costo</th><th>Estado</th><th></th></tr></thead><tbody>';
      ord.items.forEach(function (o) {
        var f = fichas.filter(function (x) { return x.id === o.ficha_id; })[0] || {};
        var merma = parseFloat(o.merma || 0);
        h += '<tr><td><b>' + esc(o.numero || o.id) + '</b>' +
          '<div class="sug">' + fecha(o.programada_ts, true) + '</div></td>' +
          '<td>' + esc(f.nombre || '—') +
          '<div class="sug">' + esc(o.responsable || '') + '</div></td>' +
          '<td class="num">' + numero(o.lotes, 0) + '</td>' +
          '<td class="num">' + numero(o.cantidad_prod, 0) + '</td>' +
          '<td class="num">' + (merma > 0
            ? '<span class="pill bad">' + numero(merma, 0) + '</span>' : '—') + '</td>' +
          '<td class="num">' + money(parseFloat(o.costo_insumos || 0) +
            parseFloat(o.costo_mo || 0)) + '</td>' +
          '<td><span class="pill ' + pill(o.estado) + '">' + esc(o.estado) + '</span></td>' +
          '<td>' + acciones(o) + '</td></tr>';
      });
      h += '</tbody></table></div>';
    }
    h += '</div></div>';
    document.getElementById('cont-produccion').innerHTML = h;
  }

  function acciones(o) {
    if (o.estado === 'programada') {
      return '<button class="btn btn-sm" data-act="prdIniciar" data-id="' + o.id +
        '">Iniciar</button>';
    }
    if (o.estado === 'en_proceso') {
      var f = fichas.filter(function (x) { return x.id === o.ficha_id; })[0] || {};
      return '<button class="btn btn-sm btn-g" data-act="prdTerminar" data-id="' + o.id +
        '" data-esp="' + (parseFloat(f.rendimiento || 0) * parseFloat(o.lotes || 1)) +
        '" data-u="' + esc(f.unidad || '') + '">Terminar</button>';
    }
    return '';
  }

  function pill(e) {
    return ({ programada: 'info', en_proceso: 'warn', terminada: 'ok', anulada: 'bad' })[e] || '';
  }

  function kpi(k, v, d, clase) {
    return '<div class="kpi ' + (clase || '') + '"><div class="k">' + k + '</div>' +
      '<div class="v">' + v + '</div><div class="d">' + esc(d) + '</div></div>';
  }

  // ══════════════════════════════════════════════════════════════════
  window.prdNueva = function () {
    var el = this;
    var pre = el && el.getAttribute ? el.getAttribute('data-f') : null;
    var ops = fichas.map(function (f) {
      return '<option value="' + f.id + '"' + (String(f.id) === String(pre) ? ' selected' : '') +
        ' data-r="' + f.rendimiento + '" data-u="' + esc(f.unidad || '') + '">' +
        esc(f.nombre) + ' · rinde ' + numero(f.rendimiento, 0) + '</option>';
    }).join('');
    modal('Programar producción',
      '<div class="campo"><label for="pr-f">¿Qué se va a preparar?</label>' +
      '<select id="pr-f">' + ops + '</select></div>' +
      '<div class="campo"><label for="pr-l">¿Cuántos lotes?</label>' +
      '<input type="number" id="pr-l" min="1" value="1"></div>' +
      '<p class="nota">Al iniciar la orden se descuentan los insumos de la receta. ' +
      'Al terminarla se pide cuánto salió <b>de verdad</b>: esa diferencia es la merma.</p>',
      'Programar', function () {
        api('/api/produccion/ordenes', {
          method: 'POST',
          body: { ficha_id: parseInt(document.getElementById('pr-f').value, 10),
                  cantidad: parseFloat(val('pr-l') || '1') }
        }).then(function () { modalCerrar(); toast('Orden programada', 'ok'); cargar(); })
          .catch(errToast);
      });
  };

  window.prdIniciar = function () {
    var el = this;
    api('/api/produccion/ordenes/' + el.getAttribute('data-id') + '/iniciar',
        { method: 'POST' })
      .then(function (r) { toast(r.mensaje || 'Producción iniciada', 'ok'); cargar(); })
      .catch(errToast);
  };

  window.prdTerminar = function () {
    var el = this;
    var id = el.getAttribute('data-id');
    var esp = el.getAttribute('data-esp');
    var u = el.getAttribute('data-u');
    modal('Terminar producción',
      '<p>La ficha dice que deben salir <b>' + numero(esp, 0) + ' ' + esc(u) + '</b>.</p>' +
      '<div class="campo"><label for="pt-r">¿Cuánto salió realmente?</label>' +
      '<input type="number" id="pt-r" step="0.01" min="0" value="' + esp + '"></div>' +
      '<p class="nota">Si salió menos, la diferencia se registra como merma de producción. ' +
      'Anotarla es lo que evita que el inventario teórico se despegue del de la bodega.</p>',
      'Terminar', function () {
        api('/api/produccion/ordenes/' + id + '/terminar', {
          method: 'POST', body: { rendimiento_real: parseFloat(val('pt-r') || '0') }
        }).then(function (r) {
          modalCerrar(); toast(r.mensaje || 'Producción terminada', 'ok'); cargar();
        }).catch(errToast);
      });
  };
})();
