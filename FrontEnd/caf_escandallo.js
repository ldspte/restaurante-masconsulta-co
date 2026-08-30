/* ══════════════════════════════════════════════════════════════════════
   RESTAURANTE · Módulo COSTO DE PLATOS (escandallo)

   Implementa la ficha técnica de costo: ingredientes primarios y secundarios,
   costos indirectos y food cost.

   La pantalla está organizada alrededor de UNA pregunta —¿qué plato me está
   costando de más?— y por eso la lista llega ordenada por food cost
   descendente. Un listado alfabético obligaría a buscar el problema; este lo
   pone primero.

   Backend: /api/escandallo/*
   ══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var COLOR = '#CA8A04';
  var datos = null, ficha = null, insumos = [], conceptos = [];

  var SEM = {
    ok:         { label: 'Saludable',  clase: 't-ok' },
    atencion:   { label: 'Atención',   clase: 't-warn' },
    alto:       { label: 'Crítico',    clase: 't-bad' },
    revisar:    { label: 'Revisar',    clase: 't-info' },
    sin_precio: { label: 'Sin precio', clase: 't-gris' }
  };

  window.escandalloInyectar = function () {
    crearPagina('escandallo', '💰', 'Costo de platos',
      'Ficha técnica de costo: ingredientes, costos indirectos y food cost por plato.', COLOR);
    var acc = document.getElementById('acc-escandallo');
    if (acc && !acc.innerHTML) {
      acc.innerHTML =
        '<button class="btn" data-act="escandalloPlantilla">⚙ Aplicar costos indirectos</button>' +
        '<button class="btn" data-act="escandalloAlAbrir">↻</button>';
    }
  };

  window.escandalloAlAbrir = function () {
    cargando('cont-escandallo');
    Promise.all([api('/api/escandallo'),
                 api('/api/productos/catalogos'),
                 api('/api/escandallo/catalogos/costos')])
      .then(function (r) {
        datos = r[0]; insumos = r[1].insumos || []; conceptos = r[2].conceptos || [];
        pintar();
      })
      .catch(function (e) {
        document.getElementById('cont-escandallo').innerHTML =
          '<div class="aviso e">' + esc(e.message) + '</div>';
      });
  };

  function pintar() {
    var k = datos.kpis;
    var prom = k.food_cost_promedio;

    var h = '<div class="grid g4 mb">' +
      kpi('Food cost promedio', prom == null ? '—' : prom + '%',
          'Objetivo del sector: ' + k.objetivo_pct + '%',
          prom == null ? '' : (prom > 35 ? 'bad' : (prom > 30 ? 'warn' : 'ok'))) +
      kpi('Platos críticos', String(k.criticos), 'Por encima del 35 %',
          k.criticos ? 'bad' : 'ok') +
      kpi('Sin costos indirectos', String(k.sin_indirectos),
          k.sin_indirectos ? 'Su costo está subestimado' : 'Todos configurados',
          k.sin_indirectos ? 'warn' : 'ok') +
      kpi('Productos en la carta', String(k.productos), 'Con ficha de costo', '') +
      '</div>';

    // El concepto que hace útil este módulo, dicho una vez y de frente.
    h += '<div class="aviso i mb"><b>Qué es el food cost.</b> Es cuánto del precio de venta ' +
      'se va en producir el plato. La referencia del sector ronda el <b>30 %</b>: por encima ' +
      'del 35 % el plato compromete la rentabilidad; muy por debajo del 25 % suele estar caro ' +
      'para su mercado. El cálculo incluye <b>ingredientes y costos indirectos</b> ' +
      '—preparación, gas, energía, agua, empaque—, que es donde se esconde el margen real.</div>';

    if (k.sin_indirectos) {
      h += '<div class="aviso w mb"><b>' + k.sin_indirectos + ' plato(s) sin costos ' +
        'indirectos.</b> Su food cost aparece más bajo de lo real. Use «Aplicar costos ' +
        'indirectos» para cargarlos desde la plantilla.</div>';
    }

    h += '<div class="card"><div class="tabla-wrap"><table><thead><tr>' +
      '<th>Producto</th><th class="num">Precio</th><th class="num">Ingredientes</th>' +
      '<th class="num">Indirectos</th><th class="num">Costo total</th>' +
      '<th class="num">Food cost</th><th class="num">Utilidad</th>' +
      '<th class="num">Sugerido</th><th></th></tr></thead><tbody>';

    datos.items.forEach(function (p) {
      var s = SEM[p.semaforo] || SEM.ok;
      var ingr = (p.primarios || 0) + (p.secundarios || 0);
      h += '<tr><td><b>' + (p.emoji || '') + ' ' + esc(p.nombre) + '</b>' +
        '<div class="peq mut">' + esc(p.categoria) + '</div></td>' +
        '<td class="num">' + money(p.precio_venta) + '</td>' +
        '<td class="num">' + money(ingr) + '</td>' +
        '<td class="num">' + money(p.indirectos) + '</td>' +
        '<td class="num"><b>' + money(p.costo_total) + '</b></td>' +
        '<td class="num"><span class="tag ' + s.clase + '">' +
        (p.food_cost_pct == null ? '—' : p.food_cost_pct + '%') + '</span></td>' +
        '<td class="num">' + money(p.utilidad) + '</td>' +
        '<td class="num peq mut">' + (p.semaforo === 'alto' ? money(p.precio_sugerido) : '—') + '</td>' +
        '<td class="num"><button class="btn btn-sm" data-act="escandalloVer" data-args="' +
        arg(p.id) + '">Ver ficha</button></td></tr>';
    });

    document.getElementById('cont-escandallo').innerHTML = h + '</tbody></table></div></div>';
  }

  // ── Ficha detallada ───────────────────────────────────────────────
  window.escandalloVer = function (pid) {
    api('/api/escandallo/' + pid).then(function (r) { ficha = r; pintarFicha(); })
      .catch(errToast);
  };

  function pintarFicha() {
    var t = ficha.totales, ev = ficha.evaluacion;
    var s = SEM[ev.semaforo] || SEM.ok;

    function bloque(titulo, lineas, total, peso, secundario) {
      var h = '<tr style="background:#F9FAFB"><td colspan="4"><b>' + titulo + '</b>' +
        '<span class="peq mut"> · ' + peso + '% del costo</span></td>' +
        '<td class="num"><b>' + money(total) + '</b></td></tr>';
      if (!lineas.length) {
        h += '<tr><td colspan="5" class="mut peq" style="padding-left:20px">Sin líneas</td></tr>';
      }
      lineas.forEach(function (x, i) {
        h += '<tr><td style="padding-left:20px">' + esc(x.nombre) + '</td>' +
          '<td class="num">' + numero(x.cantidad, 3) + '</td>' +
          '<td class="peq mut">' + esc(x.unidad || '') +
          (x.merma_pct ? ' <span class="tag t-warn">merma ' + x.merma_pct + '%</span>' : '') + '</td>' +
          '<td class="num peq mut">' + money(x.costo_unitario) + '</td>' +
          '<td class="num">' + money(x.costo_total) + '</td></tr>';
      });
      return h;
    }

    var h = '<div class="aviso ' + (ev.semaforo === 'alto' ? 'e' :
              (ev.semaforo === 'ok' ? 'g' : 'w')) + '">' +
      '<b>Food cost ' + (t.food_cost_pct == null ? '—' : t.food_cost_pct + '%') + '</b> · ' +
      esc(ev.mensaje) +
      (ev.semaforo === 'alto'
        ? '<br>Para alcanzar el ' + ev.objetivo_pct + '% habría que venderlo en <b>' +
          money(ev.precio_sugerido) + '</b>.'
        : '') + '</div>';

    h += '<div class="tabla-wrap"><table><thead><tr><th>Concepto</th>' +
      '<th class="num">Cant.</th><th>Unidad</th><th class="num">Costo unit.</th>' +
      '<th class="num">Total</th></tr></thead><tbody>';
    h += bloque('INGREDIENTES PRIMARIOS', ficha.primarios, t.primarios, t.peso_primarios);
    h += bloque('INGREDIENTES SECUNDARIOS', ficha.secundarios, t.secundarios, t.peso_secundarios);

    h += '<tr style="background:#F9FAFB"><td colspan="4"><b>COSTOS INDIRECTOS</b>' +
      '<span class="peq mut"> · ' + t.peso_indirectos + '% del costo</span></td>' +
      '<td class="num"><b>' + money(t.indirectos) + '</b></td></tr>';
    if (!ficha.indirectos.length) {
      h += '<tr><td colspan="5" class="peq" style="padding-left:20px;color:#B45309">' +
        'Sin costos indirectos: el costo de este plato está subestimado.</td></tr>';
    }
    ficha.indirectos.forEach(function (x) {
      h += '<tr><td style="padding-left:20px">' + esc(x.concepto) + '</td>' +
        '<td colspan="3"></td><td class="num">' + money(x.valor) + '</td></tr>';
    });

    h += '</tbody><tfoot>' +
      '<tr style="font-weight:800;background:#F3F4F6"><td colspan="4">COSTO TOTAL DEL PLATO</td>' +
      '<td class="num">' + money(t.costo_total) + '</td></tr>' +
      '<tr><td colspan="4">Precio de venta</td><td class="num">' + money(t.precio_venta) + '</td></tr>' +
      '<tr style="font-weight:800;background:' + (t.utilidad >= 0 ? '#DCFCE7' : '#FEE2E2') + '">' +
      '<td colspan="4">UTILIDAD POR PLATO</td><td class="num">' + money(t.utilidad) + '</td></tr>' +
      '</tfoot></table></div>';

    h += '<div class="flex mt">' +
      '<button class="btn btn-p" data-act="escandalloEditarIndirectos">✎ Editar costos indirectos</button>' +
      '<button class="btn" data-act="escandalloEditarReceta">🧪 Editar receta</button></div>';

    modal('💰 ' + (ficha.producto.emoji || '') + ' ' + ficha.producto.nombre, h, null, null);
  }

  // ── Edición de costos indirectos ──────────────────────────────────
  window.escandalloEditarIndirectos = function () {
    var actuales = ficha.indirectos.slice();
    // Se ofrecen también los conceptos de la plantilla que este plato no tiene,
    // para no tener que recordar cuáles faltan.
    conceptos.forEach(function (c) {
      if (!actuales.some(function (a) { return a.concepto === c.nombre; })) {
        actuales.push({ concepto: c.nombre, valor: 0 });
      }
    });

    var h = '<p class="mut peq mb">Valor por porción. Deje en cero lo que no aplique a ' +
      'este plato.</p>';
    actuales.forEach(function (x, i) {
      h += '<div class="fila" style="margin-bottom:8px">' +
        '<div class="campo" style="margin:0"><input type="text" id="ci-c' + i + '" value="' +
        esc(x.concepto) + '"></div>' +
        '<div class="campo" style="margin:0;max-width:140px"><input type="number" id="ci-v' + i +
        '" value="' + Number(x.valor || 0) + '" step="10"></div></div>';
    });
    h += '<input type="hidden" id="ci-n" value="' + actuales.length + '">';

    modal('Costos indirectos · ' + ficha.producto.nombre, h, 'Guardar', function () {
      var n = Number(val('ci-n')), items = [];
      for (var i = 0; i < n; i++) {
        var c = val('ci-c' + i), v = Number(val('ci-v' + i) || 0);
        if (c) items.push({ concepto: c, valor: v });
      }
      api('/api/escandallo/' + ficha.producto.id + '/indirectos',
          { method: 'PUT', body: { items: items } })
        .then(function (r) {
          ficha = r; toast('Costos actualizados', 'ok');
          pintarFicha(); escandalloAlAbrir();
        }).catch(errToast);
    });
  };

  // ── Edición de receta con tipo y merma ────────────────────────────
  window.escandalloEditarReceta = function () {
    var lineas = ficha.primarios.map(function (x) { return Object.assign({}, x, { tipo: 'primario' }); })
      .concat(ficha.secundarios.map(function (x) { return Object.assign({}, x, { tipo: 'secundario' }); }));

    var opciones = insumos.map(function (i) {
      return '<option value="' + i.id + '">' + esc(i.nombre) + ' (' + esc(i.unidad) + ')</option>';
    }).join('');

    var h = '<p class="mut peq mb"><b>Primario</b> es el eje del plato; <b>secundario</b>, las ' +
      'guarniciones y salsas. La <b>merma</b> es lo que se pierde al limpiar o porcionar: un ' +
      'kilo de papa no rinde un kilo pelado.</p>' +
      '<div class="tabla-wrap"><table><thead><tr><th>Insumo</th><th class="num">Cantidad</th>' +
      '<th>Tipo</th><th class="num">Merma %</th><th></th></tr></thead><tbody id="rc-body">';

    lineas.forEach(function (x, i) {
      h += filaReceta(i, x, opciones);
    });
    h += '</tbody></table></div><input type="hidden" id="rc-n" value="' + lineas.length + '">' +
      '<button class="btn btn-sm mt" data-act="escandalloAgregarLinea">+ Agregar insumo</button>';

    modal('🧪 Receta · ' + ficha.producto.nombre, h, 'Guardar receta', function () {
      var n = Number(val('rc-n')), items = [];
      for (var i = 0; i < n; i++) {
        var sel = document.getElementById('rc-i' + i);
        if (!sel) continue;
        var cant = Number(val('rc-q' + i) || 0);
        if (cant <= 0) continue;
        items.push({ insumo_id: Number(sel.value), cantidad: cant,
                     tipo: val('rc-t' + i), merma_pct: Number(val('rc-m' + i) || 0) });
      }
      api('/api/escandallo/' + ficha.producto.id + '/receta',
          { method: 'PUT', body: { items: items } })
        .then(function (r) {
          ficha = r; toast('Receta guardada', 'ok');
          pintarFicha(); escandalloAlAbrir();
        }).catch(errToast);
    });
  };

  function filaReceta(i, x, opciones) {
    var sel = opciones.replace('value="' + (x ? x.insumo_id : '') + '"',
                               'value="' + (x ? x.insumo_id : '') + '" selected');
    return '<tr><td><select id="rc-i' + i + '">' + sel + '</select></td>' +
      '<td class="num"><input type="number" id="rc-q' + i + '" step="0.001" value="' +
      (x ? x.cantidad : 0) + '" style="width:96px;text-align:right"></td>' +
      '<td><select id="rc-t' + i + '">' +
      '<option value="primario"' + (x && x.tipo === 'primario' ? ' selected' : '') + '>Primario</option>' +
      '<option value="secundario"' + (x && x.tipo === 'secundario' ? ' selected' : '') + '>Secundario</option>' +
      '</select></td>' +
      '<td class="num"><input type="number" id="rc-m' + i + '" step="1" min="0" max="99" value="' +
      (x ? (x.merma_pct || 0) : 0) + '" style="width:72px;text-align:right"></td>' +
      '<td class="num"><button class="btn btn-sm" data-act="escandalloQuitarLinea" data-args="' +
      i + '">✕</button></td></tr>';
  }

  window.escandalloAgregarLinea = function () {
    var n = Number(val('rc-n'));
    var opciones = insumos.map(function (i) {
      return '<option value="' + i.id + '">' + esc(i.nombre) + ' (' + esc(i.unidad) + ')</option>';
    }).join('');
    var tbody = document.getElementById('rc-body');
    var tr = document.createElement('tbody');
    tr.innerHTML = filaReceta(n, null, opciones);
    tbody.appendChild(tr.firstChild);
    document.getElementById('rc-n').value = n + 1;
  };

  window.escandalloQuitarLinea = function (i) {
    var q = document.getElementById('rc-q' + i);
    if (q) { q.value = 0; q.closest('tr').style.opacity = '.35'; }
  };

  window.escandalloPlantilla = function () {
    modalConfirmar('¿Cargar los costos indirectos de la plantilla en los platos que aún no ' +
      'los tienen? No se modifica lo ya configurado.', function () {
      api('/api/escandallo/aplicar-plantilla-masivo', { method: 'POST' })
        .then(function (r) {
          toast(r.productos + ' plato(s) actualizados', 'ok');
          escandalloAlAbrir();
        }).catch(errToast);
    });
  };

  function kpi(t, v, d, c) {
    return '<div class="kpi ' + (c || '') + '"><div class="k">' + esc(t) + '</div>' +
      '<div class="v">' + esc(v) + '</div><div class="d">' + esc(d) + '</div></div>';
  }
})();
