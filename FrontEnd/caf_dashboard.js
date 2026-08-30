/* ══════════════════════════════════════════════════════════════════════
   CAFETERÍA · Módulo TABLERO
   Vista consolidada del negocio. Solo lee: no modifica nada.
   Backend: GET /api/dashboard
   ══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var COLOR = '#2563EB', DIAS = 7;

  window.dashboardInyectar = function () {
    crearPagina('dashboard', '📊', 'Tablero',
      'Ventas, márgenes, mermas y alertas de existencias del período.', COLOR);
    var acc = document.getElementById('acc-dashboard');
    if (acc && !acc.innerHTML) {
      acc.innerHTML =
        '<select id="db-dias" data-act="dashboardPeriodo" style="width:auto">' +
        '<option value="1">Hoy</option><option value="7" selected>Últimos 7 días</option>' +
        '<option value="30">Últimos 30 días</option><option value="90">Últimos 90 días</option>' +
        '</select>' +
        '<button class="btn" data-act="dashboardAlAbrir">↻ Actualizar</button>';
    }
  };

  window.dashboardPeriodo = function () {
    DIAS = Number(document.getElementById('db-dias').value) || 7;
    dashboardAlAbrir();
  };

  window.dashboardAlAbrir = function () {
    cargando('cont-dashboard');
    api('/api/dashboard?dias=' + DIAS).then(pintar).catch(function (e) {
      document.getElementById('cont-dashboard').innerHTML =
        '<div class="aviso e">No se pudo cargar el tablero: ' + esc(e.message) + '</div>';
    });
  };

  function pintar(d) {
    var k = d.kpis;
    var h = '';

    // Aviso de existencias: lo primero que debe ver quien administra.
    if (k.inventario_alertas > 0) {
      h += '<div class="aviso w"><b>' + k.inventario_alertas + ' insumo(s) en o por debajo del mínimo.</b> ' +
        (d.alertas_stock || []).map(function (a) {
          return esc(a.nombre) + ' (' + numero(a.stock) + ')';
        }).join(' · ') + '</div>';
    }

    // ── Indicadores ──
    h += '<div class="grid g4 mb">';
    h += kpi('Ventas del período', money(k.ventas_total), k.ventas_num + ' transacciones', 'ok');
    h += kpi('Ventas de hoy', money(k.hoy_total), k.hoy_num + ' transacciones', 'info');
    h += kpi('Utilidad bruta', money(k.utilidad_bruta),
      k.margen_pct == null ? 'Sin ventas aún' : 'Margen ' + k.margen_pct + '%',
      k.utilidad_bruta >= 0 ? 'ok' : 'bad');
    h += kpi('Ticket promedio', k.ticket_promedio == null ? '—' : money(k.ticket_promedio),
      'Por transacción', '');
    h += '</div>';

    h += '<div class="grid g4 mb">';
    h += kpi('Valor del inventario', money(k.inventario_valor),
      k.insumos_total + ' insumos activos', 'info');
    h += kpi('Alertas de stock', String(k.inventario_alertas), 'En o bajo el mínimo',
      k.inventario_alertas ? 'warn' : 'ok');
    h += kpi('Pérdidas', money(k.perdidas_costo),
      k.perdidas_pct_ventas == null ? k.perdidas_num + ' registros'
        : k.perdidas_pct_ventas + '% de las ventas',
      k.perdidas_pct_ventas > 3 ? 'bad' : 'warn');
    h += kpi('Costo de ventas', money(k.costo_ventas), 'Consumo de insumos', '');
    h += '</div>';

    // ── Tendencia ──
    h += '<div class="grid g2">';
    h += '<div class="card"><div class="card-h">📈 Tendencia de ventas</div><div class="card-b">' +
      grafica(d.serie) + '</div></div>';

    // ── Productos más vendidos ──
    h += '<div class="card"><div class="card-h">🏆 Más vendidos</div><div class="card-b">';
    if (!(d.top_productos || []).length) {
      h += vacio('📭', 'Todavía no hay ventas en el período.');
    } else {
      h += '<div class="tabla-wrap"><table><thead><tr><th>Producto</th>' +
        '<th class="num">Unidades</th><th class="num">Ingreso</th></tr></thead><tbody>';
      d.top_productos.forEach(function (p) {
        h += '<tr><td>' + esc(p.nombre) + '</td><td class="num">' + numero(p.unidades) +
          '</td><td class="num">' + money(p.ingreso) + '</td></tr>';
      });
      h += '</tbody></table></div>';
    }
    h += '</div></div></div>';

    // ── Medios de pago ──
    if ((d.medios_pago || []).length) {
      var totalMedios = d.medios_pago.reduce(function (a, m) { return a + Number(m.monto || 0); }, 0);
      h += '<div class="card mt"><div class="card-h">💳 Medios de pago</div><div class="card-b">' +
        '<div class="tabla-wrap"><table><thead><tr><th>Medio</th><th class="num">Operaciones</th>' +
        '<th class="num">Monto</th><th class="num">Participación</th></tr></thead><tbody>';
      d.medios_pago.forEach(function (m) {
        var pct = totalMedios ? (Number(m.monto) / totalMedios * 100).toFixed(1) : '0.0';
        h += '<tr><td>' + esc(m.metodo) + '</td><td class="num">' + m.n + '</td>' +
          '<td class="num">' + money(m.monto) + '</td><td class="num">' + pct + '%</td></tr>';
      });
      h += '</tbody></table></div></div></div>';
    }

    document.getElementById('cont-dashboard').innerHTML = h;
  }

  function kpi(titulo, valor, detalle, clase) {
    return '<div class="kpi ' + (clase || '') + '"><div class="k">' + esc(titulo) + '</div>' +
      '<div class="v">' + esc(valor) + '</div><div class="d">' + esc(detalle) + '</div></div>';
  }

  function grafica(serie) {
    if (!(serie || []).length) return vacio('📊', 'Sin datos en el período seleccionado.');
    var max = Math.max.apply(null, serie.map(function (s) { return Number(s.total || 0); })) || 1;
    var h = '<div class="barras">';
    serie.forEach(function (s) {
      var alto = Math.max(3, Math.round(Number(s.total || 0) / max * 118));
      var etiqueta = (s.dia || '').slice(5).replace('-', '/');
      h += '<div class="barra" title="' + esc(s.dia) + ': ' + money(s.total) + '">' +
        '<span class="v">' + Math.round(Number(s.total || 0) / 1000) + 'k</span>' +
        '<div class="b" style="height:' + alto + 'px"></div>' +
        '<span class="l">' + esc(etiqueta) + '</span></div>';
    });
    return h + '</div>';
  }
})();
