/* ══════════════════════════════════════════════════════════════════════
   RESTAURANTE · Módulo PROPINAS

   La propina NO es ingreso del restaurante. En Colombia es voluntaria y
   pertenece al personal; el negocio solo la custodia mientras la reparte.

   Por eso vive en la cuenta 2335 —un PASIVO— y no en la 4135. La diferencia
   no es formal: contarla como ingreso infla las ventas, sube la base del IVA
   y del impuesto de renta sobre plata que nunca fue del negocio.

   El reparto usa PUNTOS, no partes iguales. Un mesero de tiempo completo y
   uno que entra los sábados no aportaron lo mismo al servicio, y el punto es
   la forma más simple de decirlo sin discutirlo cada quincena.

   Backend: /api/propinas/*
   ══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var COLOR = '#B45309';
  var pozo = null;

  window.propinasInyectar = function () {
    crearPagina('propinas', '🪙', 'Propinas',
      'El pozo que se les debe a los meseros y a la cocina, y cómo se reparte.',
      COLOR);
    document.getElementById('acc-propinas').innerHTML =
      '<button class="btn btn-p" data-act="proRepartir">💰 Repartir el pozo</button>';
  };

  window.propinasAlAbrir = function () { cargar(); };

  function cargar() {
    cargando('cont-propinas');
    api('/api/propinas/pozo').then(function (d) { pozo = d; pintar(d); }).catch(errToast);
  }

  function pintar(d) {
    var p = d.pozo || {};
    var h = '<div class="grid g3" style="margin-bottom:16px">' +
      kpi('En el pozo', money(p.total), 'Pendiente de repartir',
          parseFloat(p.total || 0) > 0 ? 'warn' : 'ok') +
      kpi('Propinas recibidas', p.registros || 0,
          'Desde ' + (p.desde ? fecha(p.desde) : '—'), 'info') +
      kpi('Personal con puntos', (d.empleados || []).length,
          'Participan del reparto', '') +
      '</div>' +
      '<div class="aviso-suave" style="margin-bottom:16px">' +
      'La propina está en la cuenta <b>2335 · propinas por pagar</b>, que es un pasivo. ' +
      'No es ingreso del restaurante: es plata del personal que el negocio custodia ' +
      'mientras la entrega.</div>';

    h += '<div class="grid g2" style="margin-bottom:16px">';

    // ── Quién la recibió ──────────────────────────────────────────────
    h += '<div class="card"><div class="card-h">🧾 Quién la recibió en la mesa</div>' +
      '<div class="card-b">';
    if (!(d.por_mesero || []).length) {
      h += vacio('🪙', 'No hay propinas registradas en el período.');
    } else {
      h += '<div class="tabla-wrap"><table><thead><tr><th>Mesero</th>' +
        '<th class="num">Veces</th><th class="num">Total</th></tr></thead><tbody>';
      d.por_mesero.forEach(function (m) {
        h += '<tr><td>' + esc(m.mesero || '—') + '</td>' +
          '<td class="num">' + (m.registros || m.n) + '</td>' +
          '<td class="num">' + money(m.total) + '</td></tr>';
      });
      h += '</tbody></table></div>' +
        '<p class="nota">Quién la recibió no es quién se la queda. El pozo se junta ' +
        'y se reparte por puntos, porque el plato también lo hizo alguien.</p>';
    }
    h += '</div></div>';

    // ── Puntos ────────────────────────────────────────────────────────
    h += '<div class="card"><div class="card-h">⚖️ Puntos del personal</div>' +
      '<div class="card-b">';
    var tot = (d.empleados || []).reduce(function (a, e) {
      return a + parseFloat(e.puntos_propina || 0); }, 0);
    if (!tot) {
      h += vacio('⚖️', 'Nadie tiene puntos asignados. Configúrelos en Nómina.');
    } else {
      h += '<div class="tabla-wrap"><table><thead><tr><th>Persona</th><th>Cargo</th>' +
        '<th class="num">Puntos</th><th class="num">Le tocaría</th></tr></thead><tbody>';
      (d.empleados || []).forEach(function (e) {
        var pts = parseFloat(e.puntos_propina || 0);
        if (!pts) return;
        h += '<tr><td>' + esc(e.nombre) + '</td><td>' + esc(e.cargo || '') + '</td>' +
          '<td class="num">' + numero(pts, 1) + '</td>' +
          '<td class="num">' + money(parseFloat(p.total || 0) * pts / tot) + '</td></tr>';
      });
      h += '</tbody><tfoot><tr><th colspan="2">Total</th>' +
        '<th class="num">' + numero(tot, 1) + '</th>' +
        '<th class="num">' + money(p.total) + '</th></tr></tfoot></table></div>';
    }
    h += '</div></div></div>';

    // ── Repartos ──────────────────────────────────────────────────────
    h += '<div class="card"><div class="card-h">📆 Repartos hechos</div><div class="card-b">';
    if (!(d.repartos || []).length) {
      h += vacio('💰', 'No se ha repartido el pozo todavía.');
    } else {
      h += '<div class="tabla-wrap"><table><thead><tr><th>Fecha</th><th>Período</th>' +
        '<th class="num">Personas</th><th class="num">Monto</th><th>Estado</th>' +
        '<th></th></tr></thead><tbody>';
      d.repartos.forEach(function (r) {
        h += '<tr><td>' + fecha(r.ts || r.creado_en, true) + '</td>' +
          '<td>' + esc((r.desde || '') + ' – ' + (r.hasta || '')) + '</td>' +
          '<td class="num">' + (r.personas || r.beneficiarios || '—') + '</td>' +
          '<td class="num">' + money(r.total) + '</td>' +
          '<td><span class="pill ' + (r.estado === 'pagado' ? 'ok' : 'warn') + '">' +
          esc(r.estado) + '</span></td>' +
          '<td>' + (r.estado !== 'pagado'
            ? '<button class="btn btn-sm btn-g" data-act="proPagar" data-id="' + r.id +
              '">Marcar pagado</button>' : '') +
          ' <button class="btn btn-sm" data-act="proVer" data-id="' + r.id +
          '">Ver</button></td></tr>';
      });
      h += '</tbody></table></div>';
    }
    h += '</div></div>';
    document.getElementById('cont-propinas').innerHTML = h;
  }

  function kpi(k, v, d, clase) {
    return '<div class="kpi ' + (clase || '') + '"><div class="k">' + k + '</div>' +
      '<div class="v">' + v + '</div><div class="d">' + esc(d) + '</div></div>';
  }

  // ══════════════════════════════════════════════════════════════════
  window.proRepartir = function () {
    var p = (pozo && pozo.pozo) || {};
    if (!(parseFloat(p.total || 0) > 0)) {
      toast('No hay nada en el pozo para repartir.', 'warn');
      return;
    }
    var hoy = new Date().toISOString().slice(0, 10);
    modal('Repartir el pozo',
      '<p>Hay <b>' + money(p.total) + '</b> por repartir entre quienes tienen puntos.</p>' +
      '<div class="fila"><div class="campo"><label for="rp-d">Desde</label>' +
      '<input type="date" id="rp-d" value="' + (p.desde || hoy).slice(0, 10) + '"></div>' +
      '<div class="campo"><label for="rp-h">Hasta</label>' +
      '<input type="date" id="rp-h" value="' + hoy + '"></div></div>' +
      '<div class="campo"><label for="rp-o">Observación</label>' +
      '<input type="text" id="rp-o" placeholder="Quincena del 1 al 15"></div>' +
      '<p class="nota">El reparto genera el asiento que saca la plata del pasivo 2335. ' +
      'Marcarlo como pagado es un segundo paso, cuando ya se entregó de verdad.</p>',
      'Repartir', function () {
        api('/api/propinas/repartos', {
          method: 'POST',
          body: { desde: val('rp-d'), hasta: val('rp-h'), observacion: val('rp-o') }
        }).then(function (r) {
          modalCerrar(); toast(r.mensaje || 'Pozo repartido', 'ok'); cargar();
        }).catch(errToast);
      });
  };

  window.proVer = function () {
    var el = this;
    api('/api/propinas/repartos/' + el.getAttribute('data-id')).then(function (d) {
      var det = d.detalle || d.items || [];
      var h = '<div class="tabla-wrap"><table><thead><tr><th>Persona</th>' +
        '<th class="num">Puntos</th><th class="num">Monto</th></tr></thead><tbody>';
      det.forEach(function (x) {
        h += '<tr><td>' + esc(x.nombre || x.empleado) + '</td>' +
          '<td class="num">' + numero(x.puntos, 1) + '</td>' +
          '<td class="num">' + money(x.monto) + '</td></tr>';
      });
      h += '</tbody></table></div>';
      modal('Detalle del reparto', h);
    }).catch(errToast);
  };

  window.proPagar = function () {
    var el = this;
    modalConfirmar('¿Confirma que ya se le entregó la plata al personal?', function () {
      api('/api/propinas/repartos/' + el.getAttribute('data-id') + '/pagar',
          { method: 'POST' })
        .then(function (r) { toast(r.mensaje || 'Reparto marcado como pagado', 'ok'); cargar(); })
        .catch(errToast);
    });
  };
})();
