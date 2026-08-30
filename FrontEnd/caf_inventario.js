/* ══════════════════════════════════════════════════════════════════════
   CAFETERÍA · Módulo INVENTARIO
   Insumos, entradas, ajustes por conteo y kardex.
   Backend: /api/inventario/*
   ══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var COLOR = '#D97706';
  var vista = 'insumos', datos = null, cats = null;

  window.inventarioInyectar = function () {
    crearPagina('inventario', '📦', 'Inventario',
      'Existencias valorizadas, entradas de compra, ajustes por conteo y kardex.', COLOR);
    var acc = document.getElementById('acc-inventario');
    if (acc && !acc.innerHTML) {
      acc.innerHTML = '<button class="btn btn-a" data-act="invEntrada">↓ Registrar entrada</button>' +
        '<button class="btn" data-act="invNuevoInsumo">+ Insumo</button>' +
        '<button class="btn" data-act="inventarioAlAbrir">↻</button>';
    }
  };

  window.inventarioAlAbrir = function () {
    cargando('cont-inventario');
    Promise.all([api('/api/inventario/insumos'), api('/api/productos/catalogos')])
      .then(function (r) { datos = r[0]; cats = r[1]; pintar(); })
      .catch(function (e) {
        document.getElementById('cont-inventario').innerHTML =
          '<div class="aviso e">' + esc(e.message) + '</div>';
      });
  };

  window.invVista = function (v) { vista = v; pintar(); };

  function pintar() {
    var k = datos.kpis;
    var h = '<div class="grid g4 mb">' +
      chip('Insumos activos', String(k.total), 'En el catálogo', '') +
      chip('Valor del inventario', money(k.valor_total), 'Al costo promedio', 'info') +
      chip('Bajo el mínimo', String(k.bajo_minimo), 'Requieren compra',
           k.bajo_minimo ? 'warn' : 'ok') +
      chip('Agotados', String(k.agotados), 'Sin existencias',
           k.agotados ? 'bad' : 'ok') +
      '</div>';

    h += '<div class="tabs">' +
      tab('insumos', '📦 Existencias') + tab('kardex', '📋 Kardex') + '</div>';
    h += '<div id="inv-cuerpo"></div>';
    document.getElementById('cont-inventario').innerHTML = h;

    vista === 'kardex' ? pintarKardex() : pintarInsumos();
  }

  function tab(v, etiqueta) {
    return '<button class="tab' + (vista === v ? ' on' : '') + '" data-act="invVista" data-args="' +
      v + '">' + etiqueta + '</button>';
  }

  function pintarInsumos() {
    var h = '<div class="card"><div class="tabla-wrap"><table><thead><tr>' +
      '<th>Código</th><th>Insumo</th><th class="num">Existencia</th><th>Unidad</th>' +
      '<th class="num">Mínimo</th><th class="num">Costo prom.</th><th class="num">Valor</th>' +
      '<th>Estado</th><th></th></tr></thead><tbody>';

    if (!datos.items.length) {
      h += '<tr><td colspan="9">' + vacio('📦', 'Aún no hay insumos.') + '</td></tr>';
    }
    datos.items.forEach(function (i) {
      var etiqueta = { ok: '<span class="tag t-ok">Normal</span>',
                       bajo: '<span class="tag t-warn">Bajo mínimo</span>',
                       agotado: '<span class="tag t-bad">Agotado</span>' }[i.alerta];
      h += '<tr><td class="peq mut">' + esc(i.codigo) + '</td>' +
        '<td><b>' + esc(i.nombre) + '</b></td>' +
        '<td class="num"><b>' + numero(i.stock, 3) + '</b></td>' +
        '<td class="peq mut">' + esc(i.unidad) + '</td>' +
        '<td class="num">' + numero(i.stock_min, 3) + '</td>' +
        '<td class="num">' + money(i.costo_prom) + '</td>' +
        '<td class="num">' + money(i.valor) + '</td>' +
        '<td>' + etiqueta + '</td>' +
        '<td class="num">' +
        '<button class="btn btn-sm" data-act="invEntrada" data-args="' + arg(i.id) + '" title="Entrada">↓</button> ' +
        '<button class="btn btn-sm" data-act="invAjuste" data-args="' + arg(i.id) + '" title="Ajuste por conteo">⚖</button> ' +
        '<button class="btn btn-sm" data-act="invKardexDe" data-args="' + arg(i.id) + '" title="Kardex">📋</button>' +
        '</td></tr>';
    });
    document.getElementById('inv-cuerpo').innerHTML = h + '</tbody></table></div></div>';
  }

  window.invKardexDe = function (id) { vista = 'kardex'; pintar(); setTimeout(function () {
    var s = document.getElementById('kx-insumo'); if (s) { s.value = id; invCargarKardex(); }
  }, 60); };

  function pintarKardex() {
    var opciones = '<option value="">Todos los insumos</option>' +
      datos.items.map(function (i) {
        return '<option value="' + i.id + '">' + esc(i.nombre) + '</option>';
      }).join('');
    document.getElementById('inv-cuerpo').innerHTML =
      '<div class="card"><div class="card-h">📋 Movimientos' +
      '<div class="sp" style="flex:1"></div>' +
      '<select id="kx-insumo" data-act="invCargarKardex" style="width:250px">' + opciones + '</select>' +
      '</div><div id="kx-tabla"><div class="vacio">⏳ Cargando…</div></div></div>';
    invCargarKardex();
  }

  window.invCargarKardex = function () {
    var sel = document.getElementById('kx-insumo');
    var id = sel ? sel.value : '';
    api('/api/inventario/kardex?limite=200' + (id ? '&insumo_id=' + id : ''))
      .then(function (r) {
        var h = '<div class="tabla-wrap"><table><thead><tr><th>Fecha</th><th>Insumo</th>' +
          '<th>Tipo</th><th class="num">Cantidad</th><th class="num">Saldo</th>' +
          '<th class="num">Costo unit.</th><th>Motivo</th><th>Usuario</th></tr></thead><tbody>';
        if (!r.items.length) {
          h += '<tr><td colspan="8">' + vacio('📋', 'Sin movimientos.') + '</td></tr>';
        }
        r.items.forEach(function (m) {
          var clase = { entrada: 't-ok', salida: 't-info', merma: 't-bad', ajuste: 't-warn' }[m.tipo] || 't-gris';
          var signo = m.tipo === 'entrada' ? '+' : '−';
          h += '<tr><td class="peq">' + fecha(m.ts, true) + '</td>' +
            '<td>' + esc(m.insumo) + '</td>' +
            '<td><span class="tag ' + clase + '">' + esc(m.tipo) + '</span></td>' +
            '<td class="num">' + signo + numero(m.cantidad, 3) + '</td>' +
            '<td class="num"><b>' + numero(m.saldo, 3) + '</b></td>' +
            '<td class="num">' + money(m.costo_unit) + '</td>' +
            '<td class="peq mut">' + esc(m.motivo || '') + '</td>' +
            '<td class="peq mut">' + esc(m.usuario || '') + '</td></tr>';
        });
        document.getElementById('kx-tabla').innerHTML = h + '</tbody></table></div>';
      }).catch(errToast);
  };

  // ── Acciones ──────────────────────────────────────────────────────
  window.invNuevoInsumo = function () {
    var opciones = cats.unidades.map(function (u) {
      return '<option value="' + u.id + '">' + esc(u.nombre) + '</option>';
    }).join('');
    modal('Nuevo insumo',
      '<div class="campo"><label for="in-nombre">Nombre</label>' +
      '<input type="text" id="in-nombre" placeholder="Café en grano"></div>' +
      '<div class="fila">' +
      '<div class="campo"><label for="in-unidad">Unidad de medida</label>' +
      '<select id="in-unidad">' + opciones + '</select></div>' +
      '<div class="campo"><label for="in-min">Existencia mínima</label>' +
      '<input type="number" id="in-min" value="0" step="0.001"></div></div>' +
      '<div class="fila">' +
      '<div class="campo"><label for="in-costo">Costo unitario</label>' +
      '<input type="number" id="in-costo" value="0" step="0.0001"></div>' +
      '<div class="campo"><label for="in-inicial">Existencia inicial</label>' +
      '<input type="number" id="in-inicial" value="0" step="0.001"></div></div>' +
      '<div class="aviso i peq">La existencia inicial se registra como una entrada en el ' +
      'kardex, no como un dato suelto: el inventario nace trazable.</div>',
      'Crear insumo', function () {
        if (!val('in-nombre')) return toast('El nombre es obligatorio', 'warn');
        api('/api/inventario/insumos', {
          method: 'POST',
          body: { nombre: val('in-nombre'), unidad_id: Number(val('in-unidad')),
                  stock_min: Number(val('in-min') || 0),
                  costo_prom: Number(val('in-costo') || 0),
                  stock_inicial: Number(val('in-inicial') || 0) }
        }).then(function () { modalCerrar(); toast('Insumo creado', 'ok'); inventarioAlAbrir(); })
          .catch(errToast);
      });
  };

  window.invEntrada = function (id) {
    var opciones = datos.items.map(function (i) {
      return '<option value="' + i.id + '"' + (String(i.id) === String(id) ? ' selected' : '') +
        '>' + esc(i.nombre) + ' (' + esc(i.unidad) + ')</option>';
    }).join('');
    modal('↓ Registrar entrada de inventario',
      '<div class="campo"><label for="en-insumo">Insumo</label>' +
      '<select id="en-insumo">' + opciones + '</select></div>' +
      '<div class="fila">' +
      '<div class="campo"><label for="en-cant">Cantidad</label>' +
      '<input type="number" id="en-cant" step="0.001" placeholder="0"></div>' +
      '<div class="campo"><label for="en-costo">Costo unitario</label>' +
      '<input type="number" id="en-costo" step="0.0001" placeholder="0"></div></div>' +
      '<div class="campo"><label for="en-motivo">Motivo</label>' +
      '<input type="text" id="en-motivo" value="Compra a proveedor"></div>' +
      '<div class="campo"><label><input type="checkbox" id="en-contado" style="width:auto"> ' +
      'Pagada de contado</label></div>' +
      '<div class="aviso i peq">La entrada recalcula el costo promedio ponderado y genera ' +
      'el asiento contable automáticamente (inventario contra caja o proveedores).</div>',
      'Registrar entrada', function () {
        var cant = Number(val('en-cant') || 0);
        if (cant <= 0) return toast('Indique una cantidad mayor que cero', 'warn');
        api('/api/inventario/entradas', {
          method: 'POST',
          body: { insumo_id: Number(val('en-insumo')), cantidad: cant,
                  costo_unit: Number(val('en-costo') || 0), motivo: val('en-motivo'),
                  contado: document.getElementById('en-contado').checked }
        }).then(function (r) {
          modalCerrar();
          toast('Entrada registrada · saldo ' + numero(r.movimiento.saldo, 3), 'ok');
          inventarioAlAbrir();
        }).catch(errToast);
      });
  };

  window.invAjuste = function (id) {
    var i = datos.items.filter(function (x) { return String(x.id) === String(id); })[0];
    if (!i) return;
    modal('⚖ Ajuste por conteo físico · ' + i.nombre,
      '<div class="aviso i mb">El sistema registra <b>' + numero(i.stock, 3) + ' ' +
      esc(i.unidad) + '</b>. Indique lo que realmente contó.</div>' +
      '<div class="campo"><label for="aj-contado">Existencia contada</label>' +
      '<input type="number" id="aj-contado" step="0.001" value="' + i.stock + '"></div>' +
      '<div class="campo"><label for="aj-motivo">Motivo del ajuste</label>' +
      '<input type="text" id="aj-motivo" placeholder="Conteo físico mensual"></div>' +
      '<div class="aviso w peq">El motivo es obligatorio. Un ajuste sin explicación es ' +
      'indistinguible de un faltante encubierto.</div>',
      'Aplicar ajuste', function () {
        if (!val('aj-motivo')) return toast('El motivo es obligatorio', 'warn');
        api('/api/inventario/ajustes', {
          method: 'POST',
          body: { insumo_id: i.id, stock_contado: Number(val('aj-contado') || 0),
                  motivo: val('aj-motivo') }
        }).then(function (r) {
          modalCerrar();
          toast(r.sin_cambios ? 'El conteo coincide con el sistema'
                : 'Ajuste aplicado (' + numero(r.movimiento.diferencia, 3) + ')', 'ok');
          inventarioAlAbrir();
        }).catch(errToast);
      });
  };

  function chip(t, v, d, c) {
    return '<div class="kpi ' + (c || '') + '"><div class="k">' + esc(t) + '</div>' +
      '<div class="v">' + esc(v) + '</div><div class="d">' + esc(d) + '</div></div>';
  }
})();
