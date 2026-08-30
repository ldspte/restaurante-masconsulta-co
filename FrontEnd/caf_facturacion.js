/* ══════════════════════════════════════════════════════════════════════
   RESTAURANTE · Módulo FACTURACIÓN ELECTRÓNICA (DIAN)

   Una cafetería emite dos documentos distintos y confundirlos cuesta caro:

   · DOCUMENTO EQUIVALENTE POS — el 90 % de las ventas. Nadie pide datos.
   · FACTURA ELECTRÓNICA DE VENTA — cuando el cliente se identifica porque
     va a deducir el gasto. Exige adquiriente completo y numeración de la
     resolución vigente.

   El sistema decide solo: si la venta trae cliente identificado, factura; si
   no, POS. Dejar esa decisión al cajero garantiza que en hora pico todo salga
   como POS y que el cliente reclame después, cuando ya no se puede cambiar.

   La pantalla vigila lo que de verdad se daña: que se acabe el rango de
   numeración autorizado. Una resolución agotada un sábado es una caja que no
   puede facturar.

   Backend: /api/facturacion/*
   ══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var COLOR = '#0284C7';

  window.facturacionInyectar = function () {
    crearPagina('facturacion', '🧮', 'Facturación electrónica',
      'Documentos emitidos a la DIAN, clientes y la resolución de numeración.',
      COLOR);
    document.getElementById('acc-facturacion').innerHTML =
      '<button class="btn" data-act="facCliente">＋ Cliente</button>' +
      '<button class="btn btn-p" data-act="facConfig">⚙️ Resolución</button>';
  };

  window.facturacionAlAbrir = function () { cargar(); };

  function cargar() {
    cargando('cont-facturacion');
    Promise.all([api('/api/facturacion/documentos'), api('/api/facturacion/config'),
                 api('/api/facturacion/clientes')])
      .then(function (r) { pintar(r[0], r[1], r[2]); })
      .catch(errToast);
  }

  function pintar(doc, cfg, cli) {
    var k = doc.kpis || {}, r = cfg.rango || {}, c = cfg.config || {};
    var h = '<div class="grid g4" style="margin-bottom:16px">' +
      kpi('Documentos', k.total || 0, 'Emitidos en el período', 'info') +
      kpi('Facturas', k.facturas || 0, 'Con cliente identificado', 'ok') +
      kpi('POS', k.pos || 0, 'Documento equivalente', '') +
      // Las propinas cobradas son plata del PERSONAL en poder de la empresa,
      // no ingreso. Verlas junto a los documentos evita el error de sumarlas a
      // la venta al cuadrar el turno.
      kpi('Propinas', money(k.propinas || 0), 'Del personal, no del negocio',
          (k.propinas || 0) > 0 ? 'warn' : '') +
      kpi('Numeración', (r.disponibles || 0), 'Disponibles del rango',
          r.alerta ? 'bad' : 'ok') +
      '</div>';

    if (cfg.advertencia) {
      h += '<div class="aviso-alerta" style="margin-bottom:14px">⚠️ ' +
        esc(cfg.advertencia) + '</div>';
    }

    // ── Resolución ────────────────────────────────────────────────────
    var usado = (r.consumidos || 0), tope = usado + (r.disponibles || 0);
    var pct = tope ? (usado / tope * 100) : 0;
    h += '<div class="grid g2" style="margin-bottom:16px">' +
      '<div class="card"><div class="card-h">📜 Resolución de facturación</div>' +
      '<div class="card-b">' +
      '<table class="ficha"><tbody>' +
      fila('Emisor', (c.emisor_razon || '') + ' · NIT ' + (c.emisor_nit || '') +
           (c.emisor_dv != null ? '-' + c.emisor_dv : '')) +
      fila('Resolución', c.resolucion || '—') +
      fila('Vigente desde', fecha(c.fecha_resolucion)) +
      fila('Prefijo', c.prefijo || '—') +
      fila('Rango', (c.rango_desde || 0) + ' – ' + (c.rango_hasta || 0)) +
      fila('Ambiente', (c.ambiente === 'produccion' ? 'Producción' : 'Pruebas')) +
      '</tbody></table>' +
      '<div class="cat-barra" style="margin-top:12px"><div style="width:' +
      Math.min(pct, 100).toFixed(0) + '%;background:' +
      (pct > 85 ? 'var(--rojo)' : pct > 60 ? 'var(--acento)' : 'var(--verde)') +
      '"></div></div>' +
      '<div class="sug">' + usado + ' de ' + tope + ' consumidos (' + pct.toFixed(0) +
      ' %)</div></div></div>';

    // ── Clientes ──────────────────────────────────────────────────────
    h += '<div class="card"><div class="card-h">👥 Clientes identificados · ' +
      (cli.total || 0) + '</div><div class="card-b">';
    if (!(cli.items || []).length) {
      h += vacio('👥', 'Todavía no hay clientes registrados. Se crean cuando alguien ' +
        'pide factura.');
    } else {
      h += '<div class="tabla-wrap"><table><thead><tr><th>Documento</th><th>Nombre</th>' +
        '<th>Correo</th></tr></thead><tbody>';
      cli.items.slice(0, 12).forEach(function (x) {
        h += '<tr><td>' + esc(x.tipo_doc || '') + ' ' + esc(x.numero_doc || '') +
          (x.dv != null ? '-' + x.dv : '') + '</td>' +
          '<td>' + esc(x.razon_social || '') + '</td>' +
          '<td>' + esc(x.email || '—') + '</td></tr>';
      });
      h += '</tbody></table></div>';
    }
    h += '</div></div></div>';

    // ── Documentos ────────────────────────────────────────────────────
    h += '<div class="card"><div class="card-h">🧾 Documentos emitidos</div>' +
      '<div class="card-b">';
    if (!(doc.items || []).length) {
      h += vacio('🧾', 'No se ha emitido ningún documento todavía.');
    } else {
      h += '<div class="tabla-wrap"><table><thead><tr><th>Número</th>' +
        '<th>Fecha</th><th>Tipo</th>' +
        '<th>Cliente</th><th class="num">Subtotal</th>' +
        '<th class="num">Imp. consumo</th>' +
        '<th class="num">Propina</th>' +
        '<th class="num">Total</th><th>Estado</th><th></th></tr></thead><tbody>';
      doc.items.forEach(function (x) {
        var prop = Number(x.propina || 0);
        h += '<tr><td><b>' + esc(x.numero_full || x.numero) + '</b>' +
          (x.cufe ? '<div class="sug cufe">' + esc(String(x.cufe).slice(0, 22)) +
            '…</div>' : '') + '</td>' +
          // Con hora, no solo el día: en un restaurante el turno de la noche y
          // el del almuerzo se separan por la hora, y un arqueo que no cuadra
          // se busca por ahí.
          '<td class="peq">' + fecha(x.emitido_en || x.venta_ts, true) + '</td>' +
          '<td><span class="pill ' + (x.tipo === 'factura' ? 'ok' : '') + '">' +
          (x.tipo === 'factura' ? 'Factura' : 'POS') + '</span></td>' +
          '<td>' + esc(x.cliente || '—') + '</td>' +
          '<td class="num">' + money(x.subtotal) + '</td>' +
          '<td class="num">' + money(x.impuestos) + '</td>' +
          // La propina se muestra apagada cuando es cero: así la columna no
          // grita en las ventas que no la llevan, que son la mayoría.
          '<td class="num' + (prop ? '' : ' mut') + '">' + money(prop) + '</td>' +
          '<td class="num"><b>' + money(x.total) + '</b></td>' +
          '<td><span class="pill ' + pill(x.estado) + '">' + esc(x.estado) + '</span></td>' +
          '<td>' + (x.estado === 'generado' || x.estado === 'pendiente'
            ? '<button class="btn btn-sm" data-act="facTransmitir" data-id="' + x.id +
              '">Transmitir</button>' : '') + '</td></tr>';
      });
      h += '</tbody></table></div>' +
        '<p class="nota">El CUFE es la huella del documento: se calcula con los datos ' +
        'de la venta y la clave técnica. Dos documentos distintos no pueden compartirlo.<br>' +
        'La <b>propina</b> se cobró con el documento pero <b>no es base gravable</b> ' +
        '(art. 512-9 E.T.) ni ingreso del restaurante: es del personal.</p>';
    }
    h += '</div></div>';
    document.getElementById('cont-facturacion').innerHTML = h;
  }

  function pill(e) {
    return ({ aceptado: 'ok', transmitido: 'ok', generado: 'info',
              pendiente: 'warn', rechazado: 'bad' })[e] || '';
  }
  function fila(k, v) {
    return '<tr><th>' + k + '</th><td>' + esc(String(v == null ? '—' : v)) + '</td></tr>';
  }
  function kpi(k, v, d, clase) {
    return '<div class="kpi ' + (clase || '') + '"><div class="k">' + k + '</div>' +
      '<div class="v">' + v + '</div><div class="d">' + esc(d) + '</div></div>';
  }

  // ══════════════════════════════════════════════════════════════════
  window.facTransmitir = function () {
    var el = this;
    api('/api/facturacion/documentos/' + el.getAttribute('data-id') + '/transmitir',
        { method: 'POST' })
      .then(function (r) { toast(r.mensaje || 'Documento transmitido', 'ok'); cargar(); })
      .catch(errToast);
  };

  window.facCliente = function () {
    modal('Nuevo cliente',
      '<div class="fila"><div class="campo"><label for="fc-t">Tipo</label>' +
      '<select id="fc-t"><option value="NIT">NIT</option>' +
      '<option value="CC">Cédula</option><option value="CE">Cédula de extranjería</option>' +
      '<option value="PAS">Pasaporte</option></select></div>' +
      '<div class="campo"><label for="fc-n">Número</label>' +
      '<input type="text" id="fc-n" data-act="facDV"></div>' +
      '<div class="campo"><label for="fc-dv">DV</label>' +
      '<input type="text" id="fc-dv" readonly placeholder="—"></div></div>' +
      '<div class="campo"><label for="fc-r">Razón social o nombre completo</label>' +
      '<input type="text" id="fc-r"></div>' +
      '<div class="fila"><div class="campo"><label for="fc-e">Correo</label>' +
      '<input type="email" id="fc-e" placeholder="Ahí llega la factura"></div>' +
      '<div class="campo"><label for="fc-tel">Teléfono</label>' +
      '<input type="text" id="fc-tel"></div></div>' +
      '<div class="fila"><div class="campo"><label for="fc-d">Dirección</label>' +
      '<input type="text" id="fc-d"></div>' +
      '<div class="campo"><label for="fc-c">Ciudad</label>' +
      '<input type="text" id="fc-c" value="Bogotá D.C."></div></div>' +
      '<p class="nota">El dígito de verificación se calcula solo a partir del NIT. ' +
      'Escribirlo a mano es la fuente número uno de rechazos de la DIAN.</p>',
      'Guardar', function () {
        api('/api/facturacion/clientes', {
          method: 'POST',
          body: { tipo_doc: document.getElementById('fc-t').value,
                  numero_doc: val('fc-n'), razon_social: val('fc-r'),
                  email: val('fc-e'), telefono: val('fc-tel'),
                  direccion: val('fc-d'), ciudad: val('fc-c') }
        }).then(function () { modalCerrar(); toast('Cliente creado', 'ok'); cargar(); })
          .catch(errToast);
      });
  };

  /** El DV lo calcula el backend: es un algoritmo con pesos fijos y tenerlo en
   *  un solo lado evita que dos implementaciones se desincronicen. */
  window.facDV = function () {
    var el = this;
    var n = el.value.replace(/\D/g, '');
    if (n.length < 5) { document.getElementById('fc-dv').value = ''; return; }
    api('/api/facturacion/dv?nit=' + n)
      .then(function (d) { document.getElementById('fc-dv').value = d.dv; })
      .catch(function () { });
  };

  window.facConfig = function () {
    api('/api/facturacion/config').then(function (d) {
      var c = d.config || {};
      modal('Resolución de facturación',
        '<div class="campo"><label for="cf-r">Número de resolución</label>' +
        '<input type="text" id="cf-r" value="' + esc(c.resolucion || '') + '"></div>' +
        '<div class="fila"><div class="campo"><label for="cf-f">Fecha</label>' +
        '<input type="date" id="cf-f" value="' + esc(c.fecha_resolucion || '') + '"></div>' +
        '<div class="campo"><label for="cf-p">Prefijo</label>' +
        '<input type="text" id="cf-p" value="' + esc(c.prefijo || '') + '"></div></div>' +
        '<div class="fila"><div class="campo"><label for="cf-d">Desde</label>' +
        '<input type="number" id="cf-d" value="' + (c.rango_desde || 1) + '"></div>' +
        '<div class="campo"><label for="cf-h">Hasta</label>' +
        '<input type="number" id="cf-h" value="' + (c.rango_hasta || 0) + '"></div>' +
        '<div class="campo"><label for="cf-a">Ambiente</label>' +
        '<select id="cf-a"><option value="pruebas"' +
        (c.ambiente !== 'produccion' ? ' selected' : '') + '>Pruebas</option>' +
        '<option value="produccion"' + (c.ambiente === 'produccion' ? ' selected' : '') +
        '>Producción</option></select></div></div>' +
        '<p class="nota">Cambiar el rango cuando todavía quedan números disponibles ' +
        'deja huecos en la numeración, y la DIAN los pregunta.</p>',
        'Guardar', function () {
          api('/api/facturacion/config', {
            method: 'PUT',
            body: { resolucion: val('cf-r'), fecha_resolucion: val('cf-f'),
                    prefijo: val('cf-p'),
                    rango_desde: parseInt(val('cf-d') || '1', 10),
                    rango_hasta: parseInt(val('cf-h') || '0', 10),
                    ambiente: document.getElementById('cf-a').value }
          }).then(function () { modalCerrar(); toast('Resolución actualizada', 'ok'); cargar(); })
            .catch(errToast);
        });
    }).catch(errToast);
  };
})();
