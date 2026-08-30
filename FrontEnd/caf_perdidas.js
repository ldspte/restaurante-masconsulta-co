/* ══════════════════════════════════════════════════════════════════════
   CAFETERÍA · Módulo PÉRDIDAS
   Registro de mermas y análisis por causa. El indicador que importa no es
   cuánto se perdió sino qué proporción de las ventas representa.
   Backend: /api/perdidas/*
   ══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var COLOR = '#DC2626';
  var vista = 'registro', cats = null, datos = null, reporte = null;

  window.perdidasInyectar = function () {
    crearPagina('perdidas', '⚠️', 'Pérdidas',
      'Mermas por vencimiento, daño o sustracción, con su causa y su costo.', COLOR);
    var acc = document.getElementById('acc-perdidas');
    if (acc && !acc.innerHTML) {
      acc.innerHTML = '<button class="btn btn-d" data-act="perdidasNueva">+ Registrar pérdida</button>' +
        '<button class="btn" data-act="perdidasAlAbrir">↻</button>';
    }
  };

  window.perdidasAlAbrir = function () {
    cargando('cont-perdidas');
    Promise.all([api('/api/perdidas'), api('/api/perdidas/catalogos')])
      .then(function (r) {
        datos = r[0]; cats = r[1];
        return api('/api/perdidas/reporte').catch(function () { return null; });
      })
      .then(function (r) { reporte = r; pintar(); })
      .catch(function (e) {
        document.getElementById('cont-perdidas').innerHTML =
          '<div class="aviso e">' + esc(e.message) + '</div>';
      });
  };

  window.perdidasVista = function (v) { vista = v; pintar(); };

  function pintar() {
    var k = datos.kpis;
    var pct = reporte && reporte.pct_sobre_ventas;

    var h = '<div class="grid g3 mb">' +
      chip('Registros', String(k.registros), 'Pérdidas documentadas', '') +
      chip('Costo total', money(k.costo_total), 'Valorizado al costo promedio', 'bad') +
      chip('Sobre las ventas', pct == null ? '—' : pct + '%',
           pct == null ? 'Sin ventas en el período'
             : (pct > 3 ? 'Por encima de lo razonable' : 'Dentro de lo esperado'),
           pct == null ? '' : (pct > 3 ? 'bad' : 'ok')) +
      '</div>';

    if (pct != null && pct > 3) {
      h += '<div class="aviso e">La merma representa <b>' + pct + '% de las ventas</b>. ' +
        'En una cafetería, por encima del 3% suele indicar un problema de manejo, ' +
        'de porcionamiento o de control, no una fluctuación normal.</div>';
    }

    h += '<div class="tabs">' + tab('registro', '📝 Registro') + tab('analisis', '📊 Análisis por causa') + '</div>';
    h += '<div id="pd-cuerpo"></div>';
    document.getElementById('cont-perdidas').innerHTML = h;

    vista === 'analisis' ? pintarAnalisis() : pintarRegistro();
  }

  function tab(v, etiqueta) {
    return '<button class="tab' + (vista === v ? ' on' : '') + '" data-act="perdidasVista" data-args="' +
      v + '">' + etiqueta + '</button>';
  }

  function pintarRegistro() {
    var h = '<div class="card"><div class="tabla-wrap"><table><thead><tr>' +
      '<th>Fecha</th><th>Insumo</th><th class="num">Cantidad</th><th>Unidad</th>' +
      '<th class="num">Costo</th><th>Motivo</th><th>Observación</th><th>Registró</th>' +
      '</tr></thead><tbody>';
    if (!datos.items.length) {
      h += '<tr><td colspan="8">' + vacio('✅', 'No hay pérdidas registradas. Buena señal.') + '</td></tr>';
    }
    datos.items.forEach(function (p) {
      h += '<tr><td class="peq">' + fecha(p.ts, true) + '</td>' +
        '<td><b>' + esc(p.insumo) + '</b></td>' +
        '<td class="num">' + numero(p.cantidad, 3) + '</td>' +
        '<td class="peq mut">' + esc(p.unidad || '') + '</td>' +
        '<td class="num">' + money(p.costo_total) + '</td>' +
        '<td><span class="tag t-warn">' + esc(p.motivo || '') + '</span></td>' +
        '<td class="peq mut">' + esc(p.observacion || '') + '</td>' +
        '<td class="peq mut">' + esc(p.usuario || '') + '</td></tr>';
    });
    document.getElementById('pd-cuerpo').innerHTML = h + '</tbody></table></div></div>';
  }

  function pintarAnalisis() {
    if (!reporte) {
      document.getElementById('pd-cuerpo').innerHTML =
        '<div class="aviso i">El análisis por causa está disponible para supervisores y administradores.</div>';
      return;
    }
    var total = reporte.total || 0;
    var h = '<div class="grid g2">';

    h += '<div class="card"><div class="card-h">🎯 Por motivo</div><div class="card-b">';
    if (!(reporte.por_motivo || []).length) {
      h += vacio('📭', 'Sin datos.');
    } else {
      h += '<table><thead><tr><th>Motivo</th><th class="num">Casos</th>' +
        '<th class="num">Costo</th><th class="num">%</th></tr></thead><tbody>';
      reporte.por_motivo.forEach(function (m) {
        var pct = total ? (Number(m.costo) / total * 100).toFixed(1) : '0.0';
        h += '<tr><td>' + esc(m.motivo) + '</td><td class="num">' + m.n + '</td>' +
          '<td class="num">' + money(m.costo) + '</td><td class="num"><b>' + pct + '%</b></td></tr>';
      });
      h += '</tbody></table>';
    }
    h += '</div></div>';

    h += '<div class="card"><div class="card-h">📦 Insumos más afectados</div><div class="card-b">';
    if (!(reporte.por_insumo || []).length) {
      h += vacio('📭', 'Sin datos.');
    } else {
      h += '<table><thead><tr><th>Insumo</th><th class="num">Casos</th>' +
        '<th class="num">Cantidad</th><th class="num">Costo</th></tr></thead><tbody>';
      reporte.por_insumo.forEach(function (i) {
        h += '<tr><td>' + esc(i.insumo) + '</td><td class="num">' + i.n + '</td>' +
          '<td class="num">' + numero(i.cantidad, 3) + '</td>' +
          '<td class="num">' + money(i.costo) + '</td></tr>';
      });
      h += '</tbody></table>';
    }
    h += '</div></div></div>';

    document.getElementById('pd-cuerpo').innerHTML = h;
  }

  // ── Registro de una pérdida ───────────────────────────────────────
  window.perdidasNueva = function () {
    var insumos = cats.insumos.map(function (i) {
      return '<option value="' + i.id + '" data-stock="' + i.stock + '">' + esc(i.nombre) +
        ' (' + numero(i.stock, 2) + ' ' + esc(i.unidad) + ')</option>';
    }).join('');
    var motivos = cats.motivos.map(function (m) {
      return '<option value="' + m.id + '">' + esc(m.nombre) + '</option>';
    }).join('');

    modal('⚠️ Registrar pérdida',
      '<div class="campo"><label for="pd-insumo">Insumo</label>' +
      '<select id="pd-insumo">' + insumos + '</select></div>' +
      '<div class="campo"><label for="pd-cant">Cantidad perdida</label>' +
      '<input type="number" id="pd-cant" step="0.001" placeholder="0"></div>' +
      '<div class="campo"><label for="pd-motivo">Motivo</label>' +
      '<select id="pd-motivo" data-act="perdidasMotivoCambio">' + motivos +
      '<option value="__nuevo">➕ Otro motivo…</option></select></div>' +
      '<div class="campo"><label for="pd-obs">Observación</label>' +
      '<textarea id="pd-obs" rows="2" placeholder="Detalle de lo ocurrido"></textarea></div>' +
      '<div class="aviso w peq">Se descuenta del inventario y se registra como gasto por ' +
      'merma, separado del costo de ventas. Esa separación es lo que permite medir la pérdida.</div>',
      'Registrar', function () {
        var cant = Number(val('pd-cant') || 0);
        if (cant <= 0) return toast('Indique una cantidad mayor que cero', 'warn');
        if (val('pd-motivo') === '__nuevo') return toast('Elija o cree un motivo válido', 'warn');
        api('/api/perdidas', {
          method: 'POST',
          body: { insumo_id: Number(val('pd-insumo')), cantidad: cant,
                  motivo_id: Number(val('pd-motivo')), observacion: val('pd-obs') }
        }).then(function (r) {
          modalCerrar();
          toast('Pérdida registrada por ' + money(r.costo_total), 'warn');
          perdidasAlAbrir();
        }).catch(errToast);
      });
  };

  window.perdidasMotivoCambio = function () {
    if (val('pd-motivo') !== '__nuevo') return;
    var nombre = prompt('Nuevo motivo de pérdida:');
    if (!nombre) { document.getElementById('pd-motivo').selectedIndex = 0; return; }
    api('/api/perdidas/motivos', { method: 'POST', body: { nombre: nombre } })
      .then(function () { return api('/api/perdidas/catalogos'); })
      .then(function (r) {
        cats = r;
        var sel = document.getElementById('pd-motivo');
        sel.innerHTML = cats.motivos.map(function (m) {
          return '<option value="' + m.id + '">' + esc(m.nombre) + '</option>';
        }).join('') + '<option value="__nuevo">➕ Otro motivo…</option>';
        var nuevo = cats.motivos.filter(function (m) {
          return m.nombre.toLowerCase() === nombre.toLowerCase();
        })[0];
        if (nuevo) sel.value = nuevo.id;
        toast('Motivo creado', 'ok');
      }).catch(errToast);
  };

  function chip(t, v, d, c) {
    return '<div class="kpi ' + (c || '') + '"><div class="k">' + esc(t) + '</div>' +
      '<div class="v">' + esc(v) + '</div><div class="d">' + esc(d) + '</div></div>';
  }
})();
