/* ══════════════════════════════════════════════════════════════════════
   RESTAURANTE · Módulo CONSUMO INTERNO  ·  el desayuno del personal

   El panadero entra a las cuatro de la mañana. A las siete desayuna, y ese
   desayuno sale de la misma cocina que vende.

   Un sistema que no lo modela obliga a elegir entre dos mentiras: registrarlo
   como venta —inflando ingresos que nadie pagó— o no registrarlo —dejando un
   hueco en el inventario que al final del mes aparece como merma inexplicable.

   Aquí tiene cuenta propia (5165, alimentación del personal). No es venta ni
   es pérdida: es una prestación, y el dueño puede ver cuánto le cuesta
   alimentar a su equipo, que es una decisión de gestión y no un accidente.

   Backend: /api/consumo
   ══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var COLOR = '#65A30D';
  var productos = [], empleados = [], tipos = [];

  window.consumoInyectar = function () {
    crearPagina('consumo', '🍳', 'Consumo del personal',
      'El desayuno del panadero y el almuerzo del equipo: qué se consumió, ' +
      'quién y cuánto cuesta.', COLOR);
    document.getElementById('acc-consumo').innerHTML =
      '<button class="btn btn-p" data-act="conNuevo">＋ Registrar consumo</button>';
  };

  window.consumoAlAbrir = function () { cargar(); };

  function cargar() {
    cargando('cont-consumo');
    Promise.all([api('/api/consumo'), api('/api/productos'),
                 api('/api/consumo/reporte'), api('/api/nomina/empleados')])
      .then(function (r) {
        productos = r[1].items || [];
        tipos = r[0].tipos || [];
        empleados = (r[3] && r[3].items) || [];
        pintar(r[0], r[2]);
      }).catch(errToast);
  }

  function pintar(d, rep) {
    var k = d.kpis || {};
    var h = '<div class="grid g3" style="margin-bottom:16px">' +
      kpi('Raciones', k.raciones || 0, 'Servidas en el período', 'info') +
      kpi('Costo', money(k.costo_total), 'Cuenta 5165 · prestación', 'warn') +
      kpi('Registros', k.registros || 0, 'Movimientos anotados', '') +
      '</div>';

    // ── Por beneficiario ──────────────────────────────────────────────
    var porPersona = (rep && (rep.por_beneficiario || rep.items)) || [];
    h += '<div class="grid g2" style="margin-bottom:16px">' +
      '<div class="card"><div class="card-h">👥 Quién consume</div><div class="card-b">';
    if (!porPersona.length) {
      h += vacio('👥', 'Sin datos en el período.');
    } else {
      h += '<div class="tabla-wrap"><table><thead><tr><th>Persona</th>' +
        '<th class="num">Raciones</th><th class="num">Costo</th></tr></thead><tbody>';
      porPersona.forEach(function (p) {
        h += '<tr><td>' + esc(p.beneficiario || p.nombre) + '</td>' +
          '<td class="num">' + numero(p.raciones || p.cantidad, 0) + '</td>' +
          '<td class="num">' + money(p.costo_total || p.costo) + '</td></tr>';
      });
      h += '</tbody></table></div>';
    }
    h += '</div></div>';

    // ── Por tipo ──────────────────────────────────────────────────────
    var porTipo = (rep && rep.por_tipo) || [];
    h += '<div class="card"><div class="card-h">🍽️ Por momento del día</div>' +
      '<div class="card-b">';
    if (!porTipo.length) {
      h += vacio('🍽️', 'Sin datos en el período.');
    } else {
      porTipo.forEach(function (t) {
        var tot = porTipo.reduce(function (a, x) {
          return a + parseFloat(x.costo_total || 0); }, 0);
        var pct = tot ? (parseFloat(t.costo_total || 0) / tot * 100) : 0;
        h += '<div class="cat-linea"><div class="cat-cab"><b>' + esc(t.tipo) + '</b>' +
          '<span>' + money(t.costo_total) + '</span></div>' +
          '<div class="cat-barra"><div style="width:' + pct.toFixed(0) + '%"></div></div>' +
          '<div class="sug">' + numero(t.raciones, 0) + ' raciones</div></div>';
      });
    }
    h += '</div></div></div>';

    // ── Detalle ───────────────────────────────────────────────────────
    h += '<div class="card"><div class="card-h">📋 Registros</div><div class="card-b">';
    if (!(d.items || []).length) {
      h += vacio('🍳', 'Todavía no se ha registrado ningún consumo del personal.');
    } else {
      h += '<div class="tabla-wrap"><table><thead><tr><th>Fecha</th><th>Persona</th>' +
        '<th>Qué</th><th>Momento</th><th class="num">Cant.</th>' +
        '<th class="num">Costo</th><th>Autorizó</th></tr></thead><tbody>';
      d.items.forEach(function (x) {
        h += '<tr><td>' + fecha(x.ts, true) + '</td>' +
          '<td>' + esc(x.beneficiario) + '</td>' +
          '<td>' + esc(x.nombre || '') +
          (x.observacion ? '<div class="sug">' + esc(x.observacion) + '</div>' : '') + '</td>' +
          '<td><span class="pill info">' + esc(x.tipo) + '</span></td>' +
          '<td class="num">' + numero(x.cantidad, 0) + '</td>' +
          '<td class="num">' + money(x.costo_total) + '</td>' +
          '<td class="sug">' + esc(x.autorizado_por || '') + '</td></tr>';
      });
      h += '</tbody></table></div>';
    }
    h += '</div></div>';
    document.getElementById('cont-consumo').innerHTML = h;
  }

  function kpi(k, v, d, clase) {
    return '<div class="kpi ' + (clase || '') + '"><div class="k">' + k + '</div>' +
      '<div class="v">' + v + '</div><div class="d">' + esc(d) + '</div></div>';
  }

  // ══════════════════════════════════════════════════════════════════
  window.conNuevo = function () {
    var pOps = productos.map(function (p) {
      return '<option value="' + p.id + '">' + esc(p.nombre) + '</option>';
    }).join('');
    var eOps = '<option value="">— escribir otro nombre —</option>' +
      empleados.map(function (e) {
        var n = (e.nombres || '') + ' ' + (e.apellidos || '');
        return '<option value="' + e.id + '" data-n="' + esc(n.trim()) + '">' +
          esc(n.trim()) + ' · ' + esc(e.cargo || '') + '</option>';
      }).join('');
    var tOps = (tipos.length ? tipos : ['desayuno', 'almuerzo', 'refrigerio', 'cena'])
      .map(function (t) {
        var v = t.nombre || t;
        return '<option value="' + esc(v) + '">' +
          esc(v.charAt(0).toUpperCase() + v.slice(1)) + '</option>';
      }).join('');

    modal('Registrar consumo del personal',
      '<div class="campo"><label for="co-e">¿Quién?</label>' +
      '<select id="co-e" data-act="conPersona">' + eOps + '</select></div>' +
      '<div class="campo" id="co-wrap-n" style="display:none">' +
      '<label for="co-n">Nombre</label><input type="text" id="co-n"></div>' +
      '<div class="campo"><label for="co-p">¿Qué consumió?</label>' +
      '<select id="co-p">' + pOps + '</select></div>' +
      '<div class="fila"><div class="campo"><label for="co-c">Cantidad</label>' +
      '<input type="number" id="co-c" min="1" value="1"></div>' +
      '<div class="campo"><label for="co-t">Momento</label>' +
      '<select id="co-t">' + tOps + '</select></div></div>' +
      '<div class="campo"><label for="co-o">Observación</label>' +
      '<input type="text" id="co-o" placeholder="Turno de madrugada, cumpleaños…"></div>' +
      '<p class="nota">Se descuenta del inventario al costo y se lleva a la cuenta ' +
      '5165. No es venta ni es merma: es lo que cuesta alimentar al equipo.</p>',
      'Registrar', function () {
        var sel = document.getElementById('co-e');
        var op = sel.options[sel.selectedIndex];
        api('/api/consumo', {
          method: 'POST',
          body: {
            empleado_id: sel.value ? parseInt(sel.value, 10) : null,
            beneficiario: sel.value ? op.getAttribute('data-n') : val('co-n'),
            producto_id: parseInt(document.getElementById('co-p').value, 10),
            cantidad: parseFloat(val('co-c') || '1'),
            tipo: document.getElementById('co-t').value,
            observacion: val('co-o')
          }
        }).then(function (r) {
          modalCerrar(); toast(r.mensaje || 'Consumo registrado', 'ok'); cargar();
        }).catch(errToast);
      });
  };

  /** Permite registrar a alguien que no está en nómina (un practicante, un
   *  refuerzo del sábado) sin obligar a crearle una ficha de empleado. */
  window.conPersona = function () {
    var el = this;
    document.getElementById('co-wrap-n').style.display = el.value ? 'none' : '';
  };
})();
