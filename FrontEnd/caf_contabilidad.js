/* ══════════════════════════════════════════════════════════════════════
   CAFETERÍA · Módulo CONTABILIDAD
   Libro diario, balance de prueba y estado de resultados. Todo se alimenta de
   asientos que el sistema genera solo: aquí no se digita nada.
   Backend: /api/contabilidad/*
   ══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var COLOR = '#7C3AED';
  var vista = 'diario';

  window.contabilidadInyectar = function () {
    crearPagina('contabilidad', '📒', 'Contabilidad',
      'Partida doble automática: cada venta, compra y merma genera su asiento.', COLOR);
    var acc = document.getElementById('acc-contabilidad');
    if (acc && !acc.innerHTML) {
      acc.innerHTML = '<button class="btn" data-act="contabilidadAlAbrir">↻ Actualizar</button>';
    }
  };

  window.contabilidadAlAbrir = function () {
    var c = document.getElementById('cont-contabilidad');
    c.innerHTML = '<div class="tabs">' +
      tab('diario', '📖 Libro diario') +
      tab('balance', '⚖️ Balance de prueba') +
      tab('resultados', '📈 Estado de resultados') +
      tab('asientos', '🧾 Asientos') +
      '</div><div id="ct-cuerpo"><div class="vacio">⏳ Cargando…</div></div>';
    cargar();
  };

  window.contabilidadVista = function (v) { vista = v; contabilidadAlAbrir(); };

  function tab(v, etiqueta) {
    return '<button class="tab' + (vista === v ? ' on' : '') +
      '" data-act="contabilidadVista" data-args="' + v + '">' + etiqueta + '</button>';
  }

  function cargar() {
    var rutas = {
      diario: '/api/contabilidad/libro-diario',
      balance: '/api/contabilidad/balance-prueba',
      resultados: '/api/contabilidad/estado-resultados',
      asientos: '/api/contabilidad/asientos'
    };
    api(rutas[vista])
      .then({ diario: pintarDiario, balance: pintarBalance,
              resultados: pintarResultados, asientos: pintarAsientos }[vista])
      .catch(function (e) {
        document.getElementById('ct-cuerpo').innerHTML =
          '<div class="aviso e">' + esc(e.message) + '</div>';
      });
  }

  // ── Libro diario ──────────────────────────────────────────────────
  function pintarDiario(r) {
    var h = '<div class="card"><div class="card-h">📖 Libro diario ' +
      '<span class="peq mut">· ' + r.items.length + ' líneas</span></div>' +
      '<div class="tabla-wrap"><table><thead><tr><th>Asiento</th><th>Fecha</th>' +
      '<th>Concepto</th><th>Cuenta</th><th>Nombre</th><th class="num">Débito</th>' +
      '<th class="num">Crédito</th></tr></thead><tbody>';

    if (!r.items.length) {
      h += '<tr><td colspan="7">' + vacio('📖', 'Todavía no hay movimientos contables.') + '</td></tr>';
    }
    var anterior = null;
    r.items.forEach(function (l) {
      var nuevo = l.numero !== anterior;
      anterior = l.numero;
      h += '<tr' + (nuevo ? ' style="border-top:2px solid #E5E7EB"' : '') + '>' +
        '<td class="peq">' + (nuevo ? '<b>' + esc(l.numero) + '</b>' : '') + '</td>' +
        '<td class="peq mut">' + (nuevo ? fecha(l.ts, true) : '') + '</td>' +
        '<td class="peq">' + (nuevo ? esc(l.concepto) : '') + '</td>' +
        '<td class="peq"><b>' + esc(l.cuenta) + '</b></td>' +
        '<td class="peq mut">' + esc(l.nombre || '') + '</td>' +
        '<td class="num">' + (Number(l.debito) ? money(l.debito) : '') + '</td>' +
        '<td class="num">' + (Number(l.credito) ? money(l.credito) : '') + '</td></tr>';
    });
    h += '</tbody><tfoot><tr style="background:#F9FAFB;font-weight:700">' +
      '<td colspan="5">TOTALES</td><td class="num">' + money(r.totales.debitos) + '</td>' +
      '<td class="num">' + money(r.totales.creditos) + '</td></tr></tfoot>';
    document.getElementById('ct-cuerpo').innerHTML = h + '</table></div></div>';
  }

  // ── Balance de prueba ─────────────────────────────────────────────
  function pintarBalance(r) {
    var t = r.totales;
    var h = '<div class="aviso ' + (t.cuadra ? 'g' : 'e') + '">' +
      (t.cuadra
        ? '<b>✅ La contabilidad cuadra.</b> Débitos y créditos coinciden en ' + money(t.debitos) + '.'
        : '<b>⛔ Descuadre de ' + money(Math.abs(t.diferencia)) + '.</b> ' +
          'Hay un asiento mal registrado: ningún reporte contable es confiable hasta corregirlo.') +
      '</div>';

    h += '<div class="card"><div class="tabla-wrap"><table><thead><tr>' +
      '<th>Cuenta</th><th>Nombre</th><th>Tipo</th><th class="num">Débitos</th>' +
      '<th class="num">Créditos</th><th class="num">Saldo</th></tr></thead><tbody>';

    if (!r.items.length) {
      h += '<tr><td colspan="6">' + vacio('⚖️', 'Sin movimientos.') + '</td></tr>';
    }
    r.items.forEach(function (c) {
      h += '<tr><td><b>' + esc(c.cuenta) + '</b></td><td>' + esc(c.nombre || '') + '</td>' +
        '<td><span class="tag t-gris">' + esc(c.tipo || '—') + '</span></td>' +
        '<td class="num">' + money(c.debitos) + '</td>' +
        '<td class="num">' + money(c.creditos) + '</td>' +
        '<td class="num"><b>' + money(c.saldo) + '</b></td></tr>';
    });
    h += '</tbody><tfoot><tr style="background:#F9FAFB;font-weight:700">' +
      '<td colspan="3">TOTALES</td><td class="num">' + money(t.debitos) + '</td>' +
      '<td class="num">' + money(t.creditos) + '</td><td class="num">' +
      money(t.diferencia) + '</td></tr></tfoot>';
    document.getElementById('ct-cuerpo').innerHTML = h + '</table></div></div>';
  }

  // ── Estado de resultados ──────────────────────────────────────────
  function pintarResultados(r) {
    var s = r.resumen;
    var h = '<div class="grid g4 mb">' +
      chip('Ingresos', money(s.ingresos), 'Ventas netas', 'ok') +
      chip('Costo de ventas', money(s.costos), 'Insumos consumidos', '') +
      chip('Utilidad bruta', money(s.utilidad_bruta),
           s.margen_bruto_pct == null ? '—' : 'Margen ' + s.margen_bruto_pct + '%',
           s.utilidad_bruta >= 0 ? 'ok' : 'bad') +
      chip('Utilidad neta', money(s.utilidad_neta),
           s.margen_neto_pct == null ? '—' : 'Margen ' + s.margen_neto_pct + '%',
           s.utilidad_neta >= 0 ? 'ok' : 'bad') +
      '</div>';

    h += '<div class="card"><div class="card-h">📈 Estado de resultados</div>' +
      '<div class="tabla-wrap"><table><tbody>';
    h += seccion('INGRESOS', r.ingresos, s.ingresos);
    h += seccion('COSTOS', r.costos, s.costos);
    h += totalFila('UTILIDAD BRUTA', s.utilidad_bruta, '#F0FDF4');
    h += seccion('GASTOS', r.gastos, s.gastos);
    h += totalFila('UTILIDAD NETA', s.utilidad_neta,
                   s.utilidad_neta >= 0 ? '#DCFCE7' : '#FEE2E2');
    document.getElementById('ct-cuerpo').innerHTML = h + '</tbody></table></div></div>';
  }

  function seccion(titulo, filas, total) {
    var h = '<tr style="background:#F9FAFB"><td colspan="2"><b>' + titulo + '</b></td></tr>';
    if (!(filas || []).length) {
      h += '<tr><td class="mut peq" style="padding-left:22px">Sin movimientos</td><td class="num">—</td></tr>';
    }
    (filas || []).forEach(function (f) {
      h += '<tr><td style="padding-left:22px">' + esc(f.cuenta) + ' · ' + esc(f.nombre) + '</td>' +
        '<td class="num">' + money(f.valor) + '</td></tr>';
    });
    return h + '<tr><td style="padding-left:22px"><i>Total ' + titulo.toLowerCase() + '</i></td>' +
      '<td class="num"><b>' + money(total) + '</b></td></tr>';
  }

  function totalFila(titulo, valor, fondo) {
    return '<tr style="background:' + fondo + ';font-weight:800;font-size:15px">' +
      '<td>' + titulo + '</td><td class="num">' + money(valor) + '</td></tr>';
  }

  // ── Asientos ──────────────────────────────────────────────────────
  function pintarAsientos(r) {
    var h = '<div class="card"><div class="tabla-wrap"><table><thead><tr>' +
      '<th>Número</th><th>Fecha</th><th>Tipo</th><th>Concepto</th>' +
      '<th class="num">Débitos</th><th class="num">Créditos</th><th>Estado</th><th></th>' +
      '</tr></thead><tbody>';

    if (!r.items.length) {
      h += '<tr><td colspan="8">' + vacio('🧾', 'Sin asientos registrados.') + '</td></tr>';
    }
    r.items.forEach(function (a) {
      var cuadra = Math.abs(Number(a.debitos || 0) - Number(a.creditos || 0)) < 0.01;
      h += '<tr><td><b>' + esc(a.numero) + '</b></td>' +
        '<td class="peq mut">' + fecha(a.ts, true) + '</td>' +
        '<td><span class="tag t-info">' + esc(a.tipo) + '</span></td>' +
        '<td class="peq">' + esc(a.concepto || '') + '</td>' +
        '<td class="num">' + money(a.debitos) + '</td>' +
        '<td class="num">' + money(a.creditos) + '</td>' +
        '<td><span class="tag ' + (cuadra ? 't-ok">Cuadra' : 't-bad">Descuadrado') + '</span></td>' +
        '<td class="num"><button class="btn btn-sm" data-act="contabilidadVerAsiento" data-args="' +
        arg(a.id) + '">👁</button></td></tr>';
    });
    document.getElementById('ct-cuerpo').innerHTML = h + '</tbody></table></div></div>';
  }

  window.contabilidadVerAsiento = function (id) {
    api('/api/contabilidad/asientos/' + id).then(function (r) {
      var a = r.asiento;
      var h = '<p class="peq mut mb">' + fecha(a.ts, true) + ' · ' + esc(a.tipo) +
        (a.ref_tipo ? ' · ref. ' + esc(a.ref_tipo) + ' #' + a.ref_id : '') + '</p>' +
        '<table><thead><tr><th>Cuenta</th><th>Nombre</th><th class="num">Débito</th>' +
        '<th class="num">Crédito</th></tr></thead><tbody>';
      var d = 0, c = 0;
      r.lineas.forEach(function (l) {
        d += Number(l.debito || 0); c += Number(l.credito || 0);
        h += '<tr><td><b>' + esc(l.cuenta) + '</b></td><td>' + esc(l.nombre || '') + '</td>' +
          '<td class="num">' + (Number(l.debito) ? money(l.debito) : '') + '</td>' +
          '<td class="num">' + (Number(l.credito) ? money(l.credito) : '') + '</td></tr>';
      });
      h += '</tbody><tfoot><tr style="font-weight:700;background:#F9FAFB"><td colspan="2">TOTALES</td>' +
        '<td class="num">' + money(d) + '</td><td class="num">' + money(c) + '</td></tr></tfoot></table>';
      modal('🧾 ' + a.numero + ' · ' + (a.concepto || ''), h, null, null);
    }).catch(errToast);
  };

  function chip(t, v, d, c) {
    return '<div class="kpi ' + (c || '') + '"><div class="k">' + esc(t) + '</div>' +
      '<div class="v">' + esc(v) + '</div><div class="d">' + esc(d) + '</div></div>';
  }
})();
