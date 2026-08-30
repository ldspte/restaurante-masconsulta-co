/* ══════════════════════════════════════════════════════════════════════
   RESTAURANTE · Módulo COMPRAS

   La pantalla arranca en SUGERENCIAS, no en el maestro de proveedores. Es
   deliberado: quien entra aquí a las siete de la mañana no viene a
   administrar proveedores, viene a saber qué se está acabando.

   El sistema propone la orden —qué insumo, a qué proveedor, cuánto— a partir
   del stock mínimo y del proveedor preferido de cada insumo. Pero la emite
   una persona. Una compra automática de verdad, sin nadie mirando, termina
   pidiendo veinte kilos de mora un lunes festivo.

   Backend: /api/compras/*
   ══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var COLOR = '#0D9488';
  var proveedores = [];
  var ax = {};

  window.comprasInyectar = function () {
    crearPagina('compras', '🚚', 'Compras y proveedores',
      'Qué se está acabando, a quién se le compra y qué órdenes están en camino.',
      COLOR);
    document.getElementById('acc-compras').innerHTML =
      '<button class="btn" data-act="cmpProveedor">＋ Proveedor</button>' +
      '<button class="btn btn-p" data-act="cmpAuto">🤖 Generar orden sugerida</button>';
  };

  window.comprasAlAbrir = function () {
    window.anexosAlCerrar = cargar;
    cargar();
  };

  function cargar() {
    cargando('cont-compras');
    Promise.all([api('/api/compras/sugerencias'), api('/api/compras/ordenes'),
                 api('/api/compras/proveedores'), anexosContar('orden_compra')])
      .then(function (r) {
        proveedores = r[2].items || []; ax = r[3] || {};
        pintar(r[0], r[1], r[2]);
      }).catch(errToast);
  }

  function pintar(sug, ord, prov) {
    var ks = sug.kpis || {}, ko = ord.kpis || {};
    var h = '<div class="grid g4" style="margin-bottom:16px">' +
      kpi('Bajo mínimo', ks.total || 0, 'Insumos por reponer',
          (ks.total || 0) > 0 ? 'warn' : 'ok') +
      kpi('Agotados', ks.agotados || 0, 'Ya están en cero',
          (ks.agotados || 0) > 0 ? 'bad' : 'ok') +
      kpi('Compra estimada', money(ks.costo_estimado), 'Si se pide todo', 'info') +
      kpi('Órdenes abiertas', ko.emitidas || 0, money(ko.valor_abierto) + ' en camino', '') +
      '</div>';

    if (ks.sin_proveedor) {
      h += '<div class="aviso-alerta" style="margin-bottom:14px">⚠️ ' + ks.sin_proveedor +
        ' insumo(s) por reponer no tienen proveedor asignado. El sistema no puede ' +
        'sugerir a quién comprarlos.</div>';
    }

    // ── Sugerencias ───────────────────────────────────────────────────
    h += '<div class="card" style="margin-bottom:16px"><div class="card-h">' +
      '📉 Se está acabando</div><div class="card-b">';
    if (!(sug.items || []).length) {
      h += vacio('✅', 'Todo por encima del mínimo. No hay nada urgente que comprar.');
    } else {
      h += '<div class="tabla-wrap"><table><thead><tr><th>Insumo</th>' +
        '<th class="num">Existencia</th><th class="num">Mínimo</th>' +
        '<th class="num">Sugerido</th><th>Proveedor</th>' +
        '<th class="num">Costo est.</th></tr></thead><tbody>';
      sug.items.forEach(function (s) {
        var cero = parseFloat(s.stock || 0) <= 0;
        h += '<tr><td><b>' + esc(s.nombre) + '</b>' +
          '<div class="sug">' + esc(s.codigo || '') + '</div></td>' +
          '<td class="num">' + (cero
            ? '<span class="pill bad">agotado</span>'
            : numero(s.stock, 1) + ' ' + esc(s.unidad || '')) + '</td>' +
          '<td class="num">' + numero(s.stock_min, 1) + '</td>' +
          '<td class="num"><b>' + numero(s.sugerido || s.cantidad, 1) + '</b></td>' +
          '<td>' + esc(s.proveedor || '<span class="sug">sin asignar</span>') + '</td>' +
          '<td class="num">' + money(s.costo_estimado) + '</td></tr>';
      });
      h += '</tbody></table></div>' +
        '<p class="nota">El sistema propone; la orden la emite una persona. ' +
        'Una compra automática sin nadie mirando termina pidiendo mora un festivo.</p>';
    }
    h += '</div></div>';

    // ── Órdenes ───────────────────────────────────────────────────────
    h += '<div class="card" style="margin-bottom:16px"><div class="card-h">' +
      '📦 Órdenes de compra</div><div class="card-b">';
    if (!(ord.items || []).length) {
      h += vacio('📦', 'No hay órdenes de compra.');
    } else {
      h += '<div class="tabla-wrap"><table><thead><tr><th>Orden</th><th>Proveedor</th>' +
        '<th>Fecha</th><th class="num">Ítems</th><th class="num">Valor</th>' +
        '<th>Estado</th><th style="width:60px">📎</th><th></th></tr></thead><tbody>';
      ord.items.forEach(function (o) {
        h += '<tr><td><b>' + esc(o.numero || o.id) + '</b></td>' +
          '<td>' + esc(o.proveedor || '—') + '</td>' +
          '<td>' + fecha(o.fecha || o.creado_en) + '</td>' +
          '<td class="num">' + (o.items_n || o.lineas || '—') + '</td>' +
          '<td class="num">' + money(o.total) + '</td>' +
          '<td><span class="pill ' + pill(o.estado) + '">' +
          esc((ord.estados || {})[o.estado] || o.estado) + '</span></td>' +
          '<td>' + anexosBoton('orden_compra', o.id,
                    'Orden ' + (o.numero || o.id), ax[o.id]) + '</td>' +
          '<td>' + accion(o) + '</td></tr>';
      });
      h += '</tbody></table></div>';
    }
    h += '</div></div>';

    // ── Proveedores ───────────────────────────────────────────────────
    h += '<div class="card"><div class="card-h">🤝 Proveedores · ' + (prov.total || 0) +
      '</div><div class="card-b"><div class="grid g3">';
    (prov.items || []).forEach(function (p) {
      h += '<div class="prov">' +
        '<div class="prov-nom">' + esc(p.razon_social) + '</div>' +
        '<div class="sug">NIT ' + esc(p.nit) + (p.dv != null ? '-' + p.dv : '') + '</div>' +
        '<div class="prov-dato">👤 ' + esc(p.contacto || '—') + '</div>' +
        '<div class="prov-dato">📞 ' + esc(p.telefono || '—') + '</div>' +
        '<div class="prov-dato">✉️ ' + esc(p.email || '—') + '</div>' +
        '<div class="prov-pie"><span>' + esc(p.condicion_pago || 'Contado') + '</span>' +
        '<span>entrega ' + (p.dias_entrega || 0) + ' d</span></div>' +
        '</div>';
    });
    h += '</div></div></div>';
    document.getElementById('cont-compras').innerHTML = h;
  }

  function accion(o) {
    if (o.estado === 'sugerida') {
      return '<button class="btn btn-sm btn-p" data-act="cmpEmitir" data-id="' + o.id +
        '">Emitir</button>';
    }
    if (o.estado === 'emitida' || o.estado === 'recibida_parcial') {
      return '<button class="btn btn-sm btn-g" data-act="cmpRecibir" data-id="' + o.id +
        '">Recibir</button>';
    }
    return '';
  }

  function pill(e) {
    return ({ sugerida: 'info', emitida: 'warn', recibida_parcial: 'warn',
              recibida: 'ok', anulada: 'bad' })[e] || '';
  }

  function kpi(k, v, d, clase) {
    return '<div class="kpi ' + (clase || '') + '"><div class="k">' + k + '</div>' +
      '<div class="v">' + v + '</div><div class="d">' + esc(d) + '</div></div>';
  }

  // ══════════════════════════════════════════════════════════════════
  window.cmpAuto = function () {
    modalConfirmar('Se van a crear órdenes sugeridas para todo lo que esté bajo ' +
      'mínimo, agrupadas por proveedor. Quedan en estado «sugerida»: todavía no ' +
      'se le envían a nadie.', function () {
        api('/api/compras/generar-automatica', { method: 'POST' })
          .then(function (r) { toast(r.mensaje || 'Órdenes generadas', 'ok'); cargar(); })
          .catch(errToast);
      });
  };

  window.cmpEmitir = function () {
    var el = this;
    api('/api/compras/ordenes/' + el.getAttribute('data-id') + '/emitir', { method: 'POST' })
      .then(function (r) { toast(r.mensaje || 'Orden emitida', 'ok'); cargar(); })
      .catch(errToast);
  };

  window.cmpRecibir = function () {
    var el = this;
    var id = el.getAttribute('data-id');
    api('/api/compras/ordenes/' + id).then(function (d) {
      var o = d.orden || d;
      var lineas = d.items || o.items || [];
      var h = '<p class="nota">Cuente lo que llegó de verdad. Lo que se reciba entra al ' +
        'inventario al costo de esta factura, no al costo viejo.</p>' +
        '<div class="tabla-wrap"><table><thead><tr><th>Insumo</th>' +
        '<th class="num">Pedido</th><th style="width:110px">Recibido</th>' +
        '<th style="width:120px">Costo unit.</th></tr></thead><tbody>';
      lineas.forEach(function (l, n) {
        h += '<tr><td>' + esc(l.insumo || l.nombre) + '</td>' +
          '<td class="num">' + numero(l.cantidad, 1) + '</td>' +
          '<td><input type="number" id="rc-c' + n + '" step="0.01" min="0" value="' +
          l.cantidad + '"></td>' +
          '<td><input type="number" id="rc-p' + n + '" step="0.01" min="0" value="' +
          (l.costo_unit || l.precio_unit || 0) + '"></td></tr>';
      });
      h += '</tbody></table></div>' +
        '<div class="campo" style="margin-top:12px"><label for="rc-f">Factura del proveedor</label>' +
        '<input type="text" id="rc-f" placeholder="FV-12345"></div>';

      modal('Recibir orden ' + (o.numero || id), h, 'Recibir', function () {
        var items = lineas.map(function (l, n) {
          return {
            item_id: l.id, insumo_id: l.insumo_id,
            cantidad: parseFloat(val('rc-c' + n) || '0'),
            costo_unit: parseFloat(val('rc-p' + n) || '0')
          };
        }).filter(function (x) { return x.cantidad > 0; });
        api('/api/compras/ordenes/' + id + '/recibir', {
          method: 'POST', body: { items: items, factura: val('rc-f') }
        }).then(function (r) {
          modalCerrar(); toast(r.mensaje || 'Mercancía recibida', 'ok'); cargar();
        }).catch(errToast);
      });
    }).catch(errToast);
  };

  window.cmpProveedor = function () {
    modal('Nuevo proveedor',
      '<div class="fila"><div class="campo"><label for="pv-n">NIT</label>' +
      '<input type="text" id="pv-n" placeholder="900123456"></div>' +
      '<div class="campo" style="flex:2"><label for="pv-r">Razón social</label>' +
      '<input type="text" id="pv-r"></div></div>' +
      '<div class="fila"><div class="campo"><label for="pv-c">Contacto</label>' +
      '<input type="text" id="pv-c"></div>' +
      '<div class="campo"><label for="pv-t">Teléfono</label>' +
      '<input type="text" id="pv-t"></div></div>' +
      '<div class="campo"><label for="pv-e">Correo</label>' +
      '<input type="email" id="pv-e"></div>' +
      '<div class="fila"><div class="campo"><label for="pv-d">Días de entrega</label>' +
      '<input type="number" id="pv-d" min="0" value="2"></div>' +
      '<div class="campo"><label for="pv-p">Condición de pago</label>' +
      '<input type="text" id="pv-p" placeholder="Crédito 30 días"></div></div>',
      'Guardar', function () {
        api('/api/compras/proveedores', {
          method: 'POST',
          body: { nit: val('pv-n'), razon_social: val('pv-r'), contacto: val('pv-c'),
                  telefono: val('pv-t'), email: val('pv-e'),
                  dias_entrega: parseInt(val('pv-d') || '0', 10),
                  condicion_pago: val('pv-p') }
        }).then(function () { modalCerrar(); toast('Proveedor creado', 'ok'); cargar(); })
          .catch(errToast);
      });
  };
})();
