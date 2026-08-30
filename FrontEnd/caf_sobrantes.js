/* ══════════════════════════════════════════════════════════════════════
   RESTAURANTE · Módulo SOBRANTES  ·  el calentado

   Dos pantallas, y la diferencia entre ellas importa:

   · EL POOL se mira todo el día. Es una nevera en la pantalla: qué hay
     guardado y cuánto le queda de vida. Ordenado por el que vence primero,
     que es el orden en que hay que sacarlo.

   · EL CIERRE se hace una vez, de noche, con las manos ocupadas y con ganas
     de irse a la casa. Por eso pide CONTAR, no confirmar: el saldo que trae
     el sistema aparece como sugerencia gris, nunca precargado en el campo.
     Precargarlo garantizaría que todo el mundo le da a «guardar» sin mirar.

   Backend: /api/sobrantes/*
   ══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var COLOR = '#0891B2';
  var candidatos = [], reloj = null;

  window.sobrantesInyectar = function () {
    crearPagina('sobrantes', '🍲', 'Sobrantes y calentado',
      'Lo que queda en la cocina al cerrar: qué se guarda, qué se come el ' +
      'personal y qué se bota.', COLOR);
    document.getElementById('acc-sobrantes').innerHTML =
      '<button class="btn" data-act="sobVencer">🧹 Barrer vencidos</button>' +
      '<button class="btn btn-p" data-act="sobCierre">🌙 Cerrar cocina</button>';
  };

  window.sobrantesAlAbrir = function () {
    cargar();
    clearInterval(reloj);
    // Un minuto basta: lo que cambia es el contador de horas, no el contenido.
    reloj = setInterval(function () {
      if (document.getElementById('page-sobrantes').classList.contains('on')) cargar();
    }, 60000);
  };

  function cargar() {
    Promise.all([api('/api/sobrantes/pool'), api('/api/sobrantes/tablero'),
                 api('/api/sobrantes/cierres?limite=10')])
      .then(function (r) { pintar(r[0], r[1], r[2]); })
      .catch(errToast);
  }

  function pintar(pool, tab, cierres) {
    var c = document.getElementById('cont-sobrantes');
    var pct = tab.aprovechamiento_pct;

    var h = '<div class="grid g4" style="margin-bottom:16px">' +
      kpi('Guardado ahora', money(pool.valor_disponible),
          pool.items.length + ' lote(s) en nevera', 'info') +
      kpi('Aprovechamiento', pct == null ? '—' : pct + ' %',
          'Últimos 30 días', pct == null ? '' : pct >= 70 ? 'ok' : pct >= 45 ? 'warn' : 'bad') +
      kpi('Salvado del mes', money(tab.aprovechado_real),
          'Comida que volvió a venderse', 'ok') +
      kpi('Botado del mes', money(tab.merma_directa + tab.vencido_guardado),
          tab.lotes_vencidos + ' lote(s) vencidos', 'bad') +
      '</div>';

    if (pool.vencidos_sin_barrer) {
      h += '<div class="aviso-alerta" style="margin-bottom:14px">' +
        '⚠️ Hay ' + pool.vencidos_sin_barrer + ' lote(s) vencidos sin dar de baja. ' +
        'Oprima «Barrer vencidos» para registrarlos como pérdida.</div>';
    }

    // ── Pool ──────────────────────────────────────────────────────────
    h += '<div class="card" style="margin-bottom:16px"><div class="card-h">' +
      '❄️ En la nevera · lo que vence primero va arriba</div><div class="card-b">';
    if (!pool.items.length) {
      h += vacio('🍲', 'No hay nada guardado. Se llena al cerrar la cocina.');
    } else {
      h += '<div class="lotes">';
      pool.items.forEach(function (i) {
        var horas = i.horas_restantes;
        h += '<div class="lote ' + i.alerta + '">' +
          '<div class="lote-cab"><b>' + esc(i.insumo) + '</b>' +
          '<span class="lote-reloj">' +
          (horas == null ? '—' : horas < 0 ? 'VENCIDO' :
            horas < 1 ? Math.round(horas * 60) + ' min' : horas.toFixed(0) + ' h') +
          '</span></div>' +
          '<div class="lote-cant">' + numero(i.disponible, 1) + ' ' + esc(i.unidad) +
          (i.disponible < i.cantidad
            ? '<span class="lote-de"> de ' + numero(i.cantidad, 1) + '</span>' : '') +
          '</div>' +
          '<div class="lote-pie">' +
          '<span>' + money(i.valor) + '</span>' +
          '<span>' + (i.temperatura != null ? i.temperatura + ' °C' : '—') + '</span>' +
          '</div>' +
          '<button class="btn btn-sm btn-d ancho" data-act="sobDescartar" ' +
          'data-id="' + i.id + '" data-n="' + esc(i.insumo) + '">Descartar</button>' +
          '</div>';
      });
      h += '</div>';
    }
    h += '</div></div>';

    // ── Lo que más se bota ────────────────────────────────────────────
    h += '<div class="grid g2">';
    h += '<div class="card"><div class="card-h">🗑️ Lo que más se está botando</div>' +
      '<div class="card-b">';
    if (!(tab.peores || []).length) {
      h += vacio('👏', 'No se ha botado nada en el período.');
    } else {
      h += '<div class="tabla-wrap"><table><thead><tr><th>Insumo</th>' +
        '<th class="num">Veces</th><th class="num">Valor</th></tr></thead><tbody>';
      tab.peores.forEach(function (p) {
        h += '<tr><td>' + esc(p.nombre) + '</td><td class="num">' + p.veces + '</td>' +
          '<td class="num">' + money(p.valor) + '</td></tr>';
      });
      h += '</tbody></table></div>' +
        '<p class="nota">Esta lista dice qué olla se está preparando de más. ' +
        'Es más barato cocinar menos que aprender a guardar mejor.</p>';
    }
    h += '</div></div>';

    // ── Historial ─────────────────────────────────────────────────────
    h += '<div class="card"><div class="card-h">📅 Últimos cierres</div><div class="card-b">';
    if (!(cierres.items || []).length) {
      h += vacio('🌙', 'Todavía no se ha cerrado ninguna cocina.');
    } else {
      h += '<div class="tabla-wrap"><table><thead><tr><th>Fecha</th><th>Turno</th>' +
        '<th class="num">Guardado</th><th class="num">Botado</th>' +
        '<th class="num">Aprov.</th></tr></thead><tbody>';
      cierres.items.forEach(function (x) {
        var p = x.aprovechamiento_pct;
        h += '<tr><td>' + fecha(x.fecha) + '</td><td>' + esc(x.turno) + '</td>' +
          '<td class="num">' + money(x.val_calentado) + '</td>' +
          '<td class="num">' + money(x.val_merma) + '</td>' +
          '<td class="num">' + (p == null ? '—' :
            '<span class="pill ' + (p >= 70 ? 'ok' : p >= 45 ? 'warn' : 'bad') + '">' +
            p + ' %</span>') + '</td></tr>';
      });
      h += '</tbody></table></div>';
    }
    h += '</div></div></div>';

    c.innerHTML = h;
  }

  function kpi(k, v, d, clase) {
    return '<div class="kpi ' + (clase || '') + '"><div class="k">' + k + '</div>' +
      '<div class="v">' + v + '</div><div class="d">' + esc(d) + '</div></div>';
  }

  // ══════════════════════════════════════════════════════════════════
  //  CIERRE DE COCINA
  // ══════════════════════════════════════════════════════════════════
  window.sobCierre = function () {
    api('/api/sobrantes/candidatos').then(function (d) {
      candidatos = d.items || [];
      if (!candidatos.length) {
        toast('No hay insumos configurados para aprovechamiento.', 'warn');
        return;
      }
      var aviso = d.ya_cerrado_hoy
        ? '<div class="aviso-alerta">Ya se cerró la cocina hoy (' +
          esc(d.ultimo_cierre.turno) + '). Puede registrar otro turno.</div>' : '';

      var h = aviso +
        '<p class="nota">Cuente lo que <b>de verdad</b> quedó en las ollas. ' +
        'El saldo del sistema aparece al lado como referencia, pero casi nunca ' +
        'coincide: parte se sirvió de más y parte se pegó al fondo.</p>' +
        '<div class="fila">' +
        '<div class="campo"><label for="ci-fecha">Fecha</label>' +
        '<input type="date" id="ci-fecha" value="' + d.fecha + '"></div>' +
        '<div class="campo"><label for="ci-turno">Turno</label>' +
        '<select id="ci-turno"><option value="noche">Noche</option>' +
        '<option value="tarde">Tarde</option><option value="mañana">Mañana</option>' +
        '</select></div></div>' +
        '<div class="tabla-wrap"><table class="tabla-cierre"><thead><tr>' +
        '<th>Insumo</th><th style="width:120px">Cantidad</th>' +
        '<th style="width:150px">Destino</th><th style="width:90px">°C</th>' +
        '</tr></thead><tbody>';

      candidatos.forEach(function (c, n) {
        h += '<tr><td><b>' + esc(c.nombre) + '</b>' +
          '<div class="sug">en sistema: ' + numero(c.stock_teorico, 1) + ' ' +
          esc(c.unidad) + ' · dura ' + c.vida_util_horas + ' h</div></td>' +
          '<td><input type="number" step="0.01" min="0" id="ci-c' + n +
          '" placeholder="0" data-max="' + c.stock_teorico + '"></td>' +
          '<td><select id="ci-d' + n + '" data-act="sobDestino" data-n="' + n + '">' +
          '<option value="calentado">Guardar (calentado)</option>' +
          '<option value="consumo">Personal</option>' +
          '<option value="merma">Botar</option></select></td>' +
          '<td><input type="number" step="0.1" id="ci-t' + n + '" placeholder="4.0"></td>' +
          '</tr>';
      });
      h += '</tbody></table></div>' +
        '<div class="campo" style="margin-top:12px"><label for="ci-obs">Observaciones</label>' +
        '<textarea id="ci-obs" rows="2" placeholder="Novedades del turno…"></textarea></div>' +
        '<p class="nota">Lo que se guarda debe estar a 8 °C o menos. Por encima de eso ' +
        'el sistema no lo acepta: es la norma sanitaria, no una recomendación.</p>';

      modal('🌙 Cierre de cocina', h, 'Cerrar la cocina', enviarCierre);
    }).catch(errToast);
  };

  /** La temperatura solo aplica a lo que se guarda. Deshabilitarla evita el
   *  error más común del formulario: escribir grados en un renglón que se bota. */
  window.sobDestino = function () {
    var el = this;
    var n = el.getAttribute('data-n');
    var t = document.getElementById('ci-t' + n);
    var guarda = el.value === 'calentado';
    t.disabled = !guarda;
    if (!guarda) t.value = '';
    t.placeholder = guarda ? '4.0' : '—';
  };

  function enviarCierre() {
    var lineas = [];
    for (var n = 0; n < candidatos.length; n++) {
      var cant = parseFloat(val('ci-c' + n) || '0');
      if (!(cant > 0)) continue;
      var dest = document.getElementById('ci-d' + n).value;
      var t = val('ci-t' + n);
      lineas.push({
        insumo_id: candidatos[n].insumo_id,
        cantidad: cant,
        destino: dest,
        temperatura: dest === 'calentado' && t !== '' ? parseFloat(t) : null
      });
    }
    if (!lineas.length) { toast('No registró ninguna cantidad.', 'warn'); return; }

    api('/api/sobrantes/cierre', {
      method: 'POST',
      body: {
        fecha: val('ci-fecha'), turno: document.getElementById('ci-turno').value,
        lineas: lineas, observaciones: val('ci-obs')
      }
    }).then(function (r) {
      modalCerrar();
      toast(r.mensaje, 'ok');
      cargar();
    }).catch(errToast);
  }

  // ══════════════════════════════════════════════════════════════════
  window.sobVencer = function () {
    api('/api/sobrantes/vencer', { method: 'POST' }).then(function (r) {
      toast(r.mensaje, r.perdidos ? 'warn' : 'ok');
      cargar();
    }).catch(errToast);
  };

  window.sobDescartar = function () {
    var el = this;
    var id = el.getAttribute('data-id');
    modal('Descartar lote',
      '<p>Se va a botar todo el lote de <b>' + esc(el.getAttribute('data-n')) +
      '</b> y a registrarlo como pérdida.</p>' +
      '<div class="campo"><label for="ds-m">¿Por qué se descarta?</label>' +
      '<input type="text" id="ds-m" placeholder="Olió mal, se cortó, se cayó…"></div>',
      'Descartar', function () {
        var m = val('ds-m');
        if (!m) { toast('Diga por qué se descarta.', 'warn'); return; }
        api('/api/sobrantes/' + id + '/descartar', { method: 'POST', body: { motivo: m } })
          .then(function (r) { modalCerrar(); toast(r.mensaje, 'ok'); cargar(); })
          .catch(errToast);
      });
  };
})();
