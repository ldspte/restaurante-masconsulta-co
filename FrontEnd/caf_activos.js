/* ══════════════════════════════════════════════════════════════════════
   RESTAURANTE · Módulo MAQUINARIA Y EQUIPO

   Tres preguntas, y la pantalla responde en ese orden:

     1. ¿Qué tengo y cuánto vale hoy?      → tablero y maestro
     2. ¿Qué se me va a dañar pronto?      → agenda de mantenimiento
     3. ¿Qué gasto lleva el mes?           → depreciación

   La tercera se presenta SIEMPRE como una previa antes de contabilizar. Un
   cierre contable no debería ser la primera vez que alguien ve las cifras.

   Backend: /api/activos/*
   ══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var COLOR = '#7C3AED';
  var datos = null, cats = [], ax = {};

  window.activosInyectar = function () {
    crearPagina('activos', '🏭', 'Maquinaria y equipo',
      'El horno, las neveras y la cafetera: cuánto valen, cuánto se han ' +
      'desgastado y cuándo toca mantenimiento.', COLOR);
    document.getElementById('acc-activos').innerHTML =
      '<button class="btn" data-act="actDeprec">📉 Depreciar el mes</button>' +
      '<button class="btn btn-p" data-act="actNuevo">＋ Registrar equipo</button>';
  };

  window.activosAlAbrir = function () {
    window.anexosAlCerrar = cargar;
    cargar();
  };

  function cargar() {
    cargando('cont-activos');
    Promise.all([api('/api/activos'), api('/api/activos/tablero'),
                 api('/api/activos/mantenimientos/agenda'), anexosContar('activo')])
      .then(function (r) {
        datos = r[0]; cats = r[0].categorias || []; ax = r[3] || {};
        pintar(r[0], r[1], r[2]);
      }).catch(errToast);
  }

  function pintar(lista, tab, ag) {
    var c = document.getElementById('cont-activos');
    var h = '<div class="grid g4" style="margin-bottom:16px">' +
      kpi('Equipo al costo', money(tab.valor_compra), tab.unidades + ' unidades', 'info') +
      kpi('Valor en libros', money(tab.valor_libros),
          'Ya descontado el desgaste', 'ok') +
      kpi('Gasto mensual', money(tab.cuota_mensual),
          'Depreciación de ' + tab.periodo_actual, 'warn') +
      kpi('Mantenimiento ' + new Date().getFullYear(), money(tab.mantenimiento_anio),
          tab.mantenimientos + ' intervenciones', '') +
      '</div>';

    if (ag.vencidos) {
      h += '<div class="aviso-alerta" style="margin-bottom:14px">🔧 Hay ' + ag.vencidos +
        ' mantenimiento(s) vencido(s). El equipo que no recibe preventivo se ' +
        'detiene el sábado a las seis de la mañana.</div>';
    }

    // ── Agenda ────────────────────────────────────────────────────────
    h += '<div class="grid g2" style="margin-bottom:16px">';
    h += '<div class="card"><div class="card-h">🔧 Agenda de mantenimiento</div>' +
      '<div class="card-b">';
    if (!(ag.items || []).length) {
      h += vacio('🔧', 'No hay mantenimientos programados.');
    } else {
      h += '<div class="tabla-wrap"><table><thead><tr><th>Equipo</th><th>Próximo</th>' +
        '<th class="num">Días</th></tr></thead><tbody>';
      ag.items.forEach(function (i) {
        h += '<tr><td><b>' + esc(i.codigo) + '</b> ' + esc(i.activo) +
          '<div class="sug">' + esc(i.ubicacion || '') + '</div></td>' +
          '<td>' + fecha(i.proximo) + '</td>' +
          '<td class="num"><span class="pill ' + pillMant(i.alerta) + '">' +
          (i.dias < 0 ? 'hace ' + Math.abs(i.dias) : 'en ' + i.dias) + ' d</span></td></tr>';
      });
      h += '</tbody></table></div>';
    }
    h += '</div></div>';

    // ── Por categoría ─────────────────────────────────────────────────
    h += '<div class="card"><div class="card-h">📊 Por categoría</div><div class="card-b">';
    (tab.por_categoria || []).forEach(function (g) {
      var pct = g.valor_compra ? (g.deprec_acum / g.valor_compra * 100) : 0;
      h += '<div class="cat-linea">' +
        '<div class="cat-cab"><b>' + esc(g.categoria) + '</b>' +
        '<span>' + money(g.valor_libros) + ' de ' + money(g.valor_compra) + '</span></div>' +
        '<div class="cat-barra"><div style="width:' + Math.min(pct, 100).toFixed(0) +
        '%"></div></div>' +
        '<div class="sug">' + g.unidades + ' unidades · ' + pct.toFixed(0) +
        ' % depreciado</div></div>';
    });
    if ((tab.totalmente_depreciados || []).length) {
      h += '<div class="aviso-suave" style="margin-top:12px"><b>Ya cumplieron su vida útil ' +
        'pero siguen trabajando (' + tab.totalmente_depreciados.length + '):</b><br>' +
        tab.totalmente_depreciados.map(function (a) { return esc(a.nombre); }).join(' · ') +
        '<div class="sug">Valen cero en libros. El día que fallen hay que reponerlos ' +
        'de contado.</div></div>';
    }
    h += '</div></div></div>';

    // ── Maestro ───────────────────────────────────────────────────────
    h += '<div class="card"><div class="card-h">🏭 Maestro de equipo</div><div class="card-b">' +
      '<div class="tabla-wrap"><table><thead><tr>' +
      '<th>Código</th><th>Equipo</th><th>Ubicación</th>' +
      '<th class="num">Costo</th><th class="num">Depreciado</th>' +
      '<th class="num">En libros</th><th class="num">Cuota/mes</th>' +
      '<th style="width:60px">📎</th><th></th>' +
      '</tr></thead><tbody>';
    (lista.items || []).forEach(function (a) {
      var baja = a.estado === 'baja' || a.estado === 'vendido';
      h += '<tr' + (baja ? ' class="fila-baja"' : '') + '>' +
        '<td><b>' + esc(a.codigo) + '</b></td>' +
        '<td>' + esc(a.nombre) +
        '<div class="sug">' + esc([a.marca, a.modelo].filter(Boolean).join(' ')) +
        (baja ? ' · <b>' + esc(a.estado) + '</b>' : '') + '</div></td>' +
        '<td>' + esc(a.ubicacion || '—') + '</td>' +
        '<td class="num">' + money(a.valor_compra) + '</td>' +
        '<td class="num">' + numero(a.avance_pct, 0) + ' %</td>' +
        '<td class="num">' + money(a.valor_libros) + '</td>' +
        '<td class="num">' + (baja ? '—' : money(a.cuota_mensual)) + '</td>' +
        '<td>' + anexosBoton('activo', a.id, a.codigo + ' · ' + a.nombre,
                    ax[a.id]) + '</td>' +
        '<td><button class="btn btn-sm" data-act="actFicha" data-id="' + a.id +
        '">Ver</button></td></tr>';
    });
    h += '</tbody></table></div></div></div>';
    c.innerHTML = h;
  }

  function pillMant(a) {
    return a === 'vencido' ? 'bad' : a === 'urgente' ? 'warn' : a === 'pronto' ? 'info' : 'ok';
  }

  function kpi(k, v, d, clase) {
    return '<div class="kpi ' + (clase || '') + '"><div class="k">' + k + '</div>' +
      '<div class="v">' + v + '</div><div class="d">' + esc(d) + '</div></div>';
  }

  // ══════════════════════════════════════════════════════════════════
  //  FICHA
  // ══════════════════════════════════════════════════════════════════
  window.actFicha = function () {
    var el = this;
    var id = el.getAttribute('data-id');
    api('/api/activos/' + id).then(function (d) {
      var a = d.activo;
      var h = '<div class="grid g3" style="margin-bottom:14px">' +
        chip('Costo', money(a.valor_compra)) +
        chip('Depreciado', money(a.deprec_acum) + ' (' + numero(a.avance_pct, 0) + ' %)') +
        chip('En libros', money(a.valor_libros)) +
        '</div>' +
        '<table class="ficha"><tbody>' +
        fila('Categoría', a.categoria) +
        fila('Marca y modelo', [a.marca, a.modelo].filter(Boolean).join(' ') || '—') +
        fila('Serie', a.serie || '—') +
        fila('Comprado', fecha(a.fecha_compra) + ' a ' + (a.proveedor || '—')) +
        fila('Vida útil', a.vida_util_meses + ' meses · quedan ' + a.meses_restantes) +
        fila('Valor residual', money(a.valor_residual)) +
        fila('Cuota mensual', money(a.cuota_mensual)) +
        fila('Ubicación', (a.ubicacion || '—') + ' · ' + (a.responsable || '')) +
        fila('Cuentas', a.cuenta_activo + ' / ' + a.cuenta_deprec + ' / ' + a.cuenta_gasto) +
        '</tbody></table>';

      h += '<h4 class="sub-t">🔧 Mantenimientos · ' + money(d.costo_mantenimiento) +
        ' acumulado</h4>';
      if (!d.mantenimientos.length) {
        h += '<p class="nota">Sin mantenimientos registrados.</p>';
      } else {
        h += '<div class="tabla-wrap"><table><thead><tr><th>Fecha</th><th>Tipo</th>' +
          '<th>Descripción</th><th class="num">Costo</th></tr></thead><tbody>';
        d.mantenimientos.forEach(function (m) {
          h += '<tr><td>' + fecha(m.fecha) + '</td><td>' + esc(m.tipo) + '</td>' +
            '<td>' + esc(m.descripcion || '') + '</td>' +
            '<td class="num">' + money(m.costo) + '</td></tr>';
        });
        h += '</tbody></table></div>';
      }

      if (d.proyeccion.length) {
        h += '<h4 class="sub-t">📉 Próximos meses</h4><div class="mini-serie">';
        d.proyeccion.forEach(function (p) {
          h += '<div><span>' + p.periodo + '</span><b>' + money(p.valor_libros) +
            '</b></div>';
        });
        h += '</div>';
      }

      h += '<div class="btns" style="margin-top:16px">' +
        '<button class="btn" data-act="actMant" data-id="' + a.id + '">🔧 Registrar mantenimiento</button>' +
        (a.estado === 'activo'
          ? '<button class="btn btn-d" data-act="actBaja" data-id="' + a.id +
            '" data-n="' + esc(a.nombre) + '" data-l="' + a.valor_libros + '">Dar de baja</button>'
          : '') +
        '</div>';

      modal(a.codigo + ' · ' + a.nombre, h);
    }).catch(errToast);
  };

  function chip(k, v) {
    return '<div class="chip-dato"><span>' + k + '</span><b>' + v + '</b></div>';
  }
  function fila(k, v) {
    return '<tr><th>' + k + '</th><td>' + esc(String(v == null ? '—' : v)) + '</td></tr>';
  }

  // ══════════════════════════════════════════════════════════════════
  //  ALTA
  // ══════════════════════════════════════════════════════════════════
  window.actNuevo = function () {
    var ops = cats.map(function (c) {
      return '<option value="' + c.id + '" data-m="' + c.vida_util_meses + '">' +
        esc(c.nombre) + ' · ' + c.vida_util_meses + ' meses</option>';
    }).join('');

    modal('Registrar equipo',
      '<div class="campo"><label for="ac-n">¿Qué se compró?</label>' +
      '<input type="text" id="ac-n" placeholder="Nevera vertical 2 puertas"></div>' +
      '<div class="campo"><label for="ac-c">Categoría</label>' +
      '<select id="ac-c" data-act="actCatCambio">' + ops + '</select></div>' +
      '<div class="fila"><div class="campo"><label for="ac-ma">Marca</label>' +
      '<input type="text" id="ac-ma"></div>' +
      '<div class="campo"><label for="ac-mo">Modelo</label>' +
      '<input type="text" id="ac-mo"></div>' +
      '<div class="campo"><label for="ac-se">Serie</label>' +
      '<input type="text" id="ac-se"></div></div>' +
      '<div class="fila"><div class="campo"><label for="ac-f">Fecha de compra</label>' +
      '<input type="date" id="ac-f" value="' + new Date().toISOString().slice(0, 10) + '"></div>' +
      '<div class="campo"><label for="ac-v">Valor</label>' +
      '<input type="number" id="ac-v" min="0" step="1000"></div>' +
      '<div class="campo"><label for="ac-r">Valor residual</label>' +
      '<input type="number" id="ac-r" min="0" step="1000" value="0"></div></div>' +
      '<div class="fila"><div class="campo"><label for="ac-vu">Vida útil (meses)</label>' +
      '<input type="number" id="ac-vu" min="1" value="' +
      (cats[0] ? cats[0].vida_util_meses : 120) + '"></div>' +
      '<div class="campo"><label for="ac-fp">Forma de pago</label>' +
      '<select id="ac-fp"><option value="contado">Contado</option>' +
      '<option value="credito">A crédito del proveedor</option></select></div></div>' +
      '<div class="fila"><div class="campo"><label for="ac-u">Ubicación</label>' +
      '<input type="text" id="ac-u" placeholder="Cocina caliente"></div>' +
      '<div class="campo"><label for="ac-re">Responsable</label>' +
      '<input type="text" id="ac-re"></div></div>' +
      '<div class="fila"><div class="campo"><label for="ac-pr">Proveedor</label>' +
      '<input type="text" id="ac-pr"></div>' +
      '<div class="campo"><label for="ac-fa">Factura</label>' +
      '<input type="text" id="ac-fa"></div></div>' +
      '<p class="nota">El valor residual es lo que valdrá el equipo cuando termine su ' +
      'vida útil. Un horno de diez años no vale cero: vale su chatarra y su mercado ' +
      'de segunda.</p>',
      'Registrar', function () {
        api('/api/activos', {
          method: 'POST',
          body: {
            nombre: val('ac-n'),
            categoria_id: parseInt(document.getElementById('ac-c').value, 10),
            marca: val('ac-ma'), modelo: val('ac-mo'), serie: val('ac-se'),
            fecha_compra: val('ac-f'),
            valor_compra: parseFloat(val('ac-v') || '0'),
            valor_residual: parseFloat(val('ac-r') || '0'),
            vida_util_meses: parseInt(val('ac-vu') || '0', 10),
            ubicacion: val('ac-u'), responsable: val('ac-re'),
            proveedor: val('ac-pr'), factura: val('ac-fa'),
            forma_pago: document.getElementById('ac-fp').value
          }
        }).then(function (r) {
          modalCerrar();
          toast(r.mensaje + ' Cuota mensual: ' + money(r.cuota_mensual), 'ok');
          cargar();
        }).catch(errToast);
      });
  };

  /** La vida útil sigue a la categoría mientras nadie la toque a mano. */
  window.actCatCambio = function () {
    var el = this;
    var op = el.options[el.selectedIndex];
    document.getElementById('ac-vu').value = op.getAttribute('data-m') || 120;
  };

  // ══════════════════════════════════════════════════════════════════
  //  MANTENIMIENTO Y BAJA
  // ══════════════════════════════════════════════════════════════════
  window.actMant = function () {
    var el = this;
    var id = el.getAttribute('data-id');
    modal('Registrar mantenimiento',
      '<div class="fila"><div class="campo"><label for="mt-f">Fecha</label>' +
      '<input type="date" id="mt-f" value="' + new Date().toISOString().slice(0, 10) + '"></div>' +
      '<div class="campo"><label for="mt-t">Tipo</label>' +
      '<select id="mt-t"><option value="preventivo">Preventivo</option>' +
      '<option value="correctivo">Correctivo</option>' +
      '<option value="calibracion">Calibración</option></select></div></div>' +
      '<div class="campo"><label for="mt-d">¿Qué se hizo?</label>' +
      '<textarea id="mt-d" rows="2" placeholder="Cambio de termostato, lavado de filtros…"></textarea></div>' +
      '<div class="fila"><div class="campo"><label for="mt-c">Costo</label>' +
      '<input type="number" id="mt-c" min="0" step="1000" value="0"></div>' +
      '<div class="campo"><label for="mt-p">Proveedor</label>' +
      '<input type="text" id="mt-p"></div>' +
      '<div class="campo"><label for="mt-x">Próximo</label>' +
      '<input type="date" id="mt-x"></div></div>' +
      '<p class="nota">El costo va al gasto, no al valor del equipo. Solo se capitaliza ' +
      'lo que aumenta la capacidad o alarga la vida útil; cambiar un termostato ' +
      'repone la condición original.</p>',
      'Registrar', function () {
        api('/api/activos/' + id + '/mantenimiento', {
          method: 'POST',
          body: {
            fecha: val('mt-f'), tipo: document.getElementById('mt-t').value,
            descripcion: val('mt-d'), costo: parseFloat(val('mt-c') || '0'),
            proveedor: val('mt-p'), proximo: val('mt-x')
          }
        }).then(function (r) {
          modalCerrar(); toast(r.mensaje, 'ok'); cargar();
        }).catch(errToast);
      });
  };

  window.actBaja = function () {
    var el = this;
    var id = el.getAttribute('data-id');
    modal('Dar de baja',
      '<p>Se retira <b>' + esc(el.getAttribute('data-n')) + '</b>. ' +
      'Su valor en libros es <b>' + money(el.getAttribute('data-l')) + '</b>.</p>' +
      '<div class="campo"><label for="bj-m">Motivo</label>' +
      '<input type="text" id="bj-m" placeholder="Se dañó sin reparación, se vendió, obsoleto"></div>' +
      '<div class="fila"><div class="campo"><label for="bj-v">¿Se vendió? Valor recibido</label>' +
      '<input type="number" id="bj-v" min="0" step="1000" value="0"></div>' +
      '<div class="campo"><label for="bj-f">Fecha</label>' +
      '<input type="date" id="bj-f" value="' + new Date().toISOString().slice(0, 10) + '"></div>' +
      '</div><p class="nota">Lo que quede sin depreciar es pérdida del período: es la ' +
      'parte del equipo que se pagó y no se alcanzó a usar.</p>',
      'Dar de baja', function () {
        api('/api/activos/' + id + '/baja', {
          method: 'POST',
          body: { motivo: val('bj-m'), valor_venta: parseFloat(val('bj-v') || '0'),
                  fecha: val('bj-f') }
        }).then(function (r) {
          modalCerrar(); toast(r.mensaje, 'ok'); cargar();
        }).catch(errToast);
      });
  };

  // ══════════════════════════════════════════════════════════════════
  //  DEPRECIACIÓN
  // ══════════════════════════════════════════════════════════════════
  window.actDeprec = function () {
    api('/api/activos/depreciacion/previa').then(function (d) {
      var h = '<p class="nota">Así quedaría el gasto de <b>' + d.periodo +
        '</b>. Todavía no se ha contabilizado nada.</p>' +
        '<div class="tabla-wrap"><table><thead><tr><th>Equipo</th>' +
        '<th class="num">Meses</th><th class="num">Cuota</th>' +
        '<th class="num">Acumulado</th></tr></thead><tbody>';
      d.detalle.forEach(function (x) {
        h += '<tr><td><b>' + esc(x.codigo) + '</b> ' + esc(x.nombre) + '</td>' +
          '<td class="num">' + x.meses + '</td>' +
          '<td class="num">' + money(x.cuota) + '</td>' +
          '<td class="num">' + money(x.acum_despues) + '</td></tr>';
      });
      h += '</tbody><tfoot><tr><th colspan="2">Total del mes</th>' +
        '<th class="num">' + money(d.total) + '</th><th></th></tr></tfoot></table></div>' +
        '<p class="nota">Al aceptar se contabiliza el asiento (gasto contra depreciación ' +
        'acumulada) y el período queda cerrado. No se puede repetir.</p>';

      modal('📉 Depreciación de ' + d.periodo, h, 'Contabilizar', function () {
        api('/api/activos/depreciacion/cerrar', { method: 'POST', body: { periodo: d.periodo } })
          .then(function (r) { modalCerrar(); toast(r.mensaje, 'ok'); cargar(); })
          .catch(errToast);
      });
    }).catch(errToast);
  };
})();
