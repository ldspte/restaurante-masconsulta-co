/* ══════════════════════════════════════════════════════════════════════
   RESTAURANTE · Módulo NÓMINA

   Un restaurante de barrio con quince personas paga más en seguridad social
   y prestaciones de lo que cree. El factor prestacional ronda el 1,38: por
   cada peso de salario hay treinta y ocho centavos más que salen igual.

   Este módulo lo hace visible en vez de dejarlo como una sorpresa de fin de
   mes, y aplica dos reglas colombianas que casi todos los sistemas genéricos
   se saltan:

   · El AUXILIO DE TRANSPORTE no hace parte de la base de cotización.
     Incluirlo sobreestima los aportes de todo el personal que lo recibe.

   · La EXONERACIÓN del artículo 114-1 del Estatuto Tributario: quien gana
     menos de 10 SMMLV no causa SENA ni ICBF. Cobrarlos igual es regalarle
     plata al Estado.

   Backend: /api/nomina/*
   ══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var COLOR = '#4F46E5';
  var cat = { arl: [], estaciones: [] };
  var ax = {};

  window.rrhhInyectar = function () {
    crearPagina('rrhh', '👥', 'Nómina y seguridad social',
      'El equipo, lo que cuesta de verdad y la liquidación de cada período.',
      COLOR);
    document.getElementById('acc-rrhh').innerHTML =
      '<button class="btn" data-act="nomPila">📤 Planilla PILA</button>' +
      '<button class="btn" data-act="nomEmpleado">＋ Empleado</button>' +
      '<button class="btn btn-p" data-act="nomPeriodo">＋ Período</button>';
  };

  window.rrhhAlAbrir = function () {
    window.anexosAlCerrar = cargar;
    cargar();
  };

  function cargar() {
    cargando('cont-rrhh');
    Promise.all([api('/api/nomina/empleados'), api('/api/nomina/periodos'),
                 api('/api/nomina/parametros'), anexosContar('nomina_periodo')])
      .then(function (r) {
        cat.arl = r[0].arl || []; cat.estaciones = r[0].estaciones || [];
        ax = r[3] || {};
        pintar(r[0], r[1], r[2]);
      }).catch(errToast);
  }

  function pintar(emp, per, par) {
    var k = emp.kpis || {};
    var p = (par.items || [])[0] || par.parametros || {};
    var factor = p.factor_prestacional || 1.3798;

    var h = '<div class="grid g4" style="margin-bottom:16px">' +
      kpi('Personal', k.total || 0, 'Empleados activos', 'info') +
      kpi('Masa salarial', money(k.masa_salarial), 'Salarios básicos', '') +
      kpi('Costo real', money(parseFloat(k.masa_salarial || 0) * factor),
          'Con prestaciones y aportes', 'warn') +
      kpi('Con auxilio', k.con_auxilio || 0, 'Reciben auxilio de transporte', '') +
      '</div>';

    if (!p.vigente) {
      h += '<div class="aviso-alerta" style="margin-bottom:14px">⚠️ Los parámetros de ' +
        'nómina del año no están marcados como vigentes. No se puede liquidar hasta ' +
        'confirmar salario mínimo, auxilio y porcentajes.</div>';
    }

    // ── Períodos ──────────────────────────────────────────────────────
    h += '<div class="card" style="margin-bottom:16px"><div class="card-h">' +
      '📅 Períodos de nómina</div><div class="card-b">';
    if (!(per.items || []).length) {
      h += vacio('📅', 'No hay períodos. Cree uno para liquidar la quincena o el mes.');
    } else {
      h += '<div class="tabla-wrap"><table><thead><tr><th>Período</th><th>Rango</th>' +
        '<th class="num">Aportes patronales</th><th class="num">Devengado</th>' +
        '<th class="num">Deducciones</th><th class="num">Neto</th>' +
        '<th>Estado</th><th style="width:60px">📎</th><th></th></tr></thead><tbody>';
      per.items.forEach(function (x) {
        h += '<tr><td><b>' + esc(x.numero || x.nombre || x.id) + '</b>' +
          '<div class="sug">' + (x.dias || 30) + ' días</div></td>' +
          '<td>' + fecha(x.desde) + ' – ' + fecha(x.hasta) + '</td>' +
          '<td class="num">' + money(x.total_aportes) + '</td>' +
          '<td class="num">' + money(x.total_devengado) + '</td>' +
          '<td class="num">' + money(x.total_deducido) + '</td>' +
          '<td class="num"><b>' + money(x.total_neto) + '</b></td>' +
          '<td><span class="pill ' + pill(x.estado) + '">' + esc(x.estado) + '</span></td>' +
          '<td>' + anexosBoton('nomina_periodo', x.id,
                    'Nómina ' + (x.numero || x.id), ax[x.id]) + '</td>' +
          '<td>' + accionesPeriodo(x) + '</td></tr>';
      });
      h += '</tbody></table></div>';
    }
    h += '</div></div>';

    // ── Equipo ────────────────────────────────────────────────────────
    h += '<div class="card"><div class="card-h">👥 El equipo</div><div class="card-b">' +
      '<div class="tabla-wrap"><table><thead><tr><th>Persona</th><th>Cargo</th>' +
      '<th>Contrato</th><th class="num">Salario</th><th>ARL</th>' +
      '<th class="num">Costo mes</th><th></th></tr></thead><tbody>';
    (emp.items || []).forEach(function (e) {
      var sal = parseFloat(e.salario_base || 0);
      h += '<tr' + (e.fecha_retiro ? ' class="fila-baja"' : '') + '>' +
        '<td><b>' + esc((e.nombres || '') + ' ' + (e.apellidos || '')) + '</b>' +
        '<div class="sug">' + esc(e.tipo_doc || '') + ' ' + esc(e.numero_doc || '') +
        ' · desde ' + fecha(e.fecha_ingreso) + '</div></td>' +
        '<td>' + esc(e.cargo || '') + '</td>' +
        '<td>' + esc(e.tipo_contrato || '') + '</td>' +
        '<td class="num">' + money(sal) +
        (e.aplica_auxilio ? '<div class="sug">+ auxilio</div>' : '') + '</td>' +
        '<td>' + esc(e.arl || '—') +
        (e.clase_riesgo ? '<div class="sug">clase ' + esc(e.clase_riesgo) + '</div>' : '') +
        '</td>' +
        '<td class="num">' + money(sal * factor) + '</td>' +
        '<td><button class="btn btn-sm" data-act="nomEditar" data-id="' + e.id +
        '">Editar</button></td></tr>';
    });
    h += '</tbody></table></div>' +
      '<p class="nota">El «costo mes» aplica el factor prestacional ' +
      numero(factor, 4) + ': salario más cesantías, intereses, prima, vacaciones, ' +
      'salud, pensión, ARL y parafiscales. Es lo que de verdad sale de la caja.</p>' +
      '</div></div>';
    document.getElementById('cont-rrhh').innerHTML = h;
  }

  function accionesPeriodo(x) {
    var nov = '<button class="btn btn-sm" data-act="nomNovedades" data-id="' + x.id +
      '" data-n="' + esc(x.numero || x.id) + '" data-s="' + esc(x.estado) +
      '">Novedades</button> ';
    if (x.estado === 'abierto' || x.estado === 'borrador') {
      return nov + '<button class="btn btn-sm btn-p" data-act="nomLiquidar" data-id="' +
        x.id + '">Liquidar</button>';
    }
    if (x.estado === 'liquidado') {
      return nov +
        '<button class="btn btn-sm" data-act="nomVer" data-id="' + x.id + '">Ver</button> ' +
        '<button class="btn btn-sm btn-g" data-act="nomCerrar" data-id="' + x.id +
        '">Cerrar</button>';
    }
    // Un período cerrado no se edita: se anula con asientos de reversión y se
    // vuelve a liquidar. Editar un asiento registrado es falsificar el libro.
    return nov +
      '<button class="btn btn-sm" data-act="nomVer" data-id="' + x.id + '">Ver</button> ' +
      '<button class="btn btn-sm btn-d" data-act="nomAnular" data-id="' + x.id +
      '" data-n="' + esc(x.numero || x.id) + '">Anular</button>';
  }

  function pill(e) {
    return ({ abierto: 'info', borrador: 'info', liquidado: 'warn', cerrado: 'ok' })[e] || '';
  }
  function kpi(k, v, d, clase) {
    return '<div class="kpi ' + (clase || '') + '"><div class="k">' + k + '</div>' +
      '<div class="v">' + v + '</div><div class="d">' + esc(d) + '</div></div>';
  }


  // ══════════════════════════════════════════════════════════════════
  //  NOVEDADES DEL PERÍODO
  //
  //  Se registran cuando ocurren —el bono el día 5, el préstamo el 12— y la
  //  liquidación las recoge al cierre. Obligar a teclearlas todas el último
  //  día es la receta para que alguna se olvide.
  // ══════════════════════════════════════════════════════════════════
  var novPid = null, novCerrado = false;

  window.nomNovedades = function () {
    novPid = this.getAttribute('data-id');
    novCerrado = this.getAttribute('data-s') === 'cerrado';
    modal('Novedades de ' + this.getAttribute('data-n'),
          '<div id="nv-cuerpo" class="ax-cargando">Cargando…</div>');
    pintarNovedades();
  };

  function pintarNovedades() {
    Promise.all([api('/api/nomina/periodos/' + novPid + '/novedades'),
                 api('/api/nomina/empleados')])
      .then(function (r) {
        var d = r[0], emps = r[1].items || [];
        var c = document.getElementById('nv-cuerpo');
        if (!c) return;

        var eOps = emps.map(function (e) {
          return '<option value="' + e.id + '">' +
            esc((e.nombres || '') + ' ' + (e.apellidos || '')) + ' · ' +
            esc(e.cargo || '') + '</option>';
        }).join('');
        var tOps = (d.tipos || []).map(function (t) {
          return '<option value="' + t.clave + '">' + esc(t.etiqueta) + '</option>';
        }).join('');

        // En un período cerrado se consulta, no se registra: el formulario
        // no aparece en vez de dejar que el backend rechace el envío.
        var h = novCerrado
          ? '<p class="nota" style="margin-top:0">Período <b>cerrado</b>: las ' +
            'novedades quedan como consulta. Anúlelo si necesita corregir.</p>'
          : '<div class="ax-zona">' +
          '<div class="campo"><label for="nv-e">A quien</label>' +
          '<select id="nv-e">' + eOps + '</select></div>' +
          '<div class="campo"><label for="nv-t">Que novedad</label>' +
          '<select id="nv-t">' + tOps + '</select></div>' +
          '<div class="fila"><div class="campo"><label for="nv-v">Valor</label>' +
          '<input type="number" id="nv-v" min="0" step="1000"></div>' +
          '<div class="campo" style="flex:2"><label for="nv-c">Concepto</label>' +
          '<input type="text" id="nv-c" placeholder="12 horas extra del puente"></div></div>' +
          '<button class="btn btn-p ancho" data-act="nomNovGuardar">Registrar</button>' +
          '<p class="nota">Un <b>bono NO salarial</b> no cotiza ni genera prestaciones, ' +
          'pero solo hasta el <b>40 % de la remuneracion total</b>: el exceso si cotiza ' +
          '(art. 30, Ley 1393 de 2010). El sistema calcula ese exceso solo.</p>' +
          '</div>';

        if (!(d.items || []).length) {
          h += '<p class="ax-vacio">Sin novedades este periodo.</p>';
        } else {
          h += '<div class="tabla-wrap"><table><thead><tr><th>Persona</th>' +
            '<th>Novedad</th><th class="num">Valor</th><th></th></tr></thead><tbody>';
          d.items.forEach(function (n) {
            h += '<tr><td>' + esc(n.empleado) +
              '<div class="sug">' + esc(n.cargo || '') + '</div></td>' +
              '<td>' + esc(n.etiqueta) +
              (n.concepto ? '<div class="sug">' + esc(n.concepto) + '</div>' : '') + '</td>' +
              '<td class="num ' + (n.clase === 'deduccion' ? 'neg' : '') + '">' +
              (n.clase === 'deduccion' ? '\u2212' : '') + money(n.valor) + '</td>' +
              '<td>' + (novCerrado ? '' :
                '<button class="btn btn-sm btn-d" data-act="nomNovBorrar" data-id="' +
                n.id + '">\u2715</button>') + '</td></tr>';
          });
          h += '</tbody><tfoot><tr><th colspan="2">Devengados / Deducciones</th>' +
            '<th class="num">' + money(d.totales.devengados) + ' / \u2212' +
            money(d.totales.deducciones) + '</th><th></th></tr></tfoot></table></div>' +
            '<p class="nota">Vuelva a <b>liquidar</b> el periodo para que estas ' +
            'novedades se reflejen en el pago.</p>';
        }
        c.innerHTML = h;
        c.className = '';
      }).catch(errToast);
  }

  window.nomNovGuardar = function () {
    var v = parseFloat(val('nv-v') || '0');
    if (!(v > 0)) { toast('Indique un valor mayor que cero.', 'warn'); return; }
    api('/api/nomina/periodos/' + novPid + '/novedades', {
      method: 'POST',
      body: { empleado_id: parseInt(document.getElementById('nv-e').value, 10),
              tipo: document.getElementById('nv-t').value,
              valor: v, concepto: val('nv-c') }
    }).then(function (r) { toast(r.mensaje, 'ok'); pintarNovedades(); cargar(); })
      .catch(errToast);
  };

  window.nomNovBorrar = function () {
    api('/api/nomina/novedades/' + this.getAttribute('data-id'), { method: 'DELETE' })
      .then(function (r) { toast(r.mensaje, 'ok'); pintarNovedades(); })
      .catch(errToast);
  };

  window.nomAnular = function () {
    var id = this.getAttribute('data-id');
    modal('Anular ' + this.getAttribute('data-n'),
      '<p class="nota" style="margin-top:0">El periodo vuelve a <b>borrador</b> y se ' +
      'generan asientos que <b>revierten</b> los originales. Los asientos ya ' +
      'registrados no se tocan: un asiento no se edita, se corrige con otro.</p>' +
      '<div class="campo"><label for="an-m">Por que se anula</label>' +
      '<input type="text" id="an-m" placeholder="Se liquido con el salario minimo del ano anterior"></div>',
      'Anular', function () {
        var m = val('an-m');
        if (!m) { toast('Diga por que se anula.', 'warn'); return; }
        api('/api/nomina/periodos/' + id + '/anular', { method: 'POST', body: { motivo: m } })
          .then(function (r) { modalCerrar(); toast(r.mensaje, 'ok'); cargar(); })
          .catch(errToast);
      });
  };

  // ══════════════════════════════════════════════════════════════════
  window.nomPeriodo = function () {
    var hoy = new Date();
    var ini = new Date(hoy.getFullYear(), hoy.getMonth(), 1).toISOString().slice(0, 10);
    var fin = new Date(hoy.getFullYear(), hoy.getMonth() + 1, 0).toISOString().slice(0, 10);
    modal('Nuevo período de nómina',
      '<div class="campo"><label for="np-n">Nombre</label>' +
      '<input type="text" id="np-n" value="' +
      hoy.toLocaleDateString('es-CO', { month: 'long', year: 'numeric' }) + '"></div>' +
      '<div class="fila"><div class="campo"><label for="np-d">Desde</label>' +
      '<input type="date" id="np-d" value="' + ini + '"></div>' +
      '<div class="campo"><label for="np-h">Hasta</label>' +
      '<input type="date" id="np-h" value="' + fin + '"></div></div>',
      'Crear', function () {
        api('/api/nomina/periodos', {
          method: 'POST',
          body: { nombre: val('np-n'), desde: val('np-d'), hasta: val('np-h') }
        }).then(function () { modalCerrar(); toast('Período creado', 'ok'); cargar(); })
          .catch(errToast);
      });
  };

  window.nomLiquidar = function () {
    api('/api/nomina/periodos/' + this.getAttribute('data-id') + '/liquidar',
        { method: 'POST' })
      .then(function (r) {
        cargar();
        var bajo = r.bajo_minimo || [];
        if (!bajo.length) { toast(r.mensaje || 'Período liquidado', 'ok'); return; }

        // Un aviso que se desvanece no sirve para esto. Cada enero sube el
        // mínimo por decreto y quien estaba en el mínimo queda por debajo de
        // la ley de un día para otro; olvidar el ajuste es una sanción de
        // inspección y una deuda con el trabajador.
        modal('Personal por debajo del salario mínimo',
          '<p class="nota" style="margin-top:0">La nómina quedó liquidada, pero ' +
          '<b>' + bajo.length + ' persona(s)</b> tienen un salario básico inferior al ' +
          'mínimo legal vigente. Los aportes se calcularon sobre el piso legal, ' +
          'pero <b>el salario pagado sigue estando por debajo</b>.</p>' +
          '<div class="tabla-wrap"><table><thead><tr><th>Persona</th><th>Cargo</th>' +
          '<th class="num">Gana</th><th class="num">Le faltan</th></tr></thead><tbody>' +
          bajo.map(function (x) {
            return '<tr><td><b>' + esc(x.empleado) + '</b></td>' +
              '<td>' + esc(x.cargo || '') + '</td>' +
              '<td class="num">' + money(x.salario) + '</td>' +
              '<td class="num neg">+' + money(x.faltante) + '</td></tr>';
          }).join('') +
          '</tbody></table></div>' +
          '<p class="nota">Si es jornada parcial, el salario proporcional menor es ' +
          'legítimo y no hay nada que corregir. Si es jornada completa, ajuste el ' +
          'básico en la ficha del empleado y vuelva a liquidar.</p>');
      })
      .catch(errToast);
  };

  window.nomCerrar = function () {
    var el = this;
    modalConfirmar('Cerrar el período contabiliza la nómina y ya no se puede ' +
      'volver a liquidar. ¿Continuar?', function () {
        api('/api/nomina/periodos/' + el.getAttribute('data-id') + '/cerrar',
            { method: 'POST' })
          .then(function (r) { toast(r.mensaje || 'Período cerrado', 'ok'); cargar(); })
          .catch(errToast);
      });
  };

  window.nomVer = function () {
    var el = this;
    api('/api/nomina/periodos/' + el.getAttribute('data-id')).then(function (d) {
      var det = d.detalle || [];
      var t = d.periodo || {};
      var h = '<div class="tabla-wrap"><table><thead><tr><th>Persona</th>' +
        '<th class="num">Días</th><th class="num">Devengado</th>' +
        '<th class="num">Salud</th><th class="num">Pensión</th>' +
        '<th class="num">Neto</th></tr></thead><tbody>';
      det.forEach(function (x) {
        var dev = Number(x.salario || 0) + Number(x.auxilio_transporte || 0) +
          Number(x.horas_extra || 0) + Number(x.recargo_nocturno || 0);
        h += '<tr><td>' + esc(x.nombre || '') +
          '<div class="sug">' + esc(x.cargo || '') + '</div></td>' +
          '<td class="num">' + (x.dias || 30) + '</td>' +
          '<td class="num">' + money(x.devengado != null ? x.devengado : dev) + '</td>' +
          '<td class="num">' + money(x.salud_emp) + '</td>' +
          '<td class="num">' + money(x.pension_emp) + '</td>' +
          '<td class="num"><b>' + money(x.neto) + '</b></td></tr>';
      });
      h += '</tbody></table></div>';
      h += '<div class="grid g4" style="margin-top:14px">' +
        '<div class="chip-dato"><span>Devengado</span><b>' + money(t.total_devengado) +
        '</b></div>' +
        '<div class="chip-dato"><span>Deducciones</span><b>' +
        money(t.total_deducido) + '</b></div>' +
        '<div class="chip-dato"><span>Neto a pagar</span><b>' + money(t.total_neto) +
        '</b></div>' +
        '<div class="chip-dato"><span>Costo para la empresa</span><b>' +
        money(d.costo_total_empresa) + '</b></div></div>' +
        '<p class="nota">El costo para la empresa suma los aportes patronales y la ' +
        'provisión de prestaciones: es lo que de verdad sale de la caja, no el neto ' +
        'que ve el empleado en su cuenta.</p>';
      modal('Liquidación del período', h);
    }).catch(errToast);
  };

  window.nomPila = function () {
    api('/api/nomina/pila').then(function (d) {
      var h = '<p class="nota">Aportes agrupados por entidad, que es como se paga: ' +
        'una planilla por operador, no un pago por empleado.</p>';
      ['eps', 'afp', 'arl', 'caja'].forEach(function (grupo) {
        var filas = d[grupo] || [];
        if (!filas.length) return;
        h += '<h4 class="sub-t">' + grupo.toUpperCase() + '</h4>' +
          '<div class="tabla-wrap"><table><thead><tr><th>Entidad</th>' +
          '<th class="num">Personas</th><th class="num">Aporte</th></tr></thead><tbody>';
        filas.forEach(function (f) {
          h += '<tr><td>' + esc(f.entidad || f.nombre) + '</td>' +
            '<td class="num">' + (f.personas || f.n) + '</td>' +
            '<td class="num">' + money(f.total) + '</td></tr>';
        });
        h += '</tbody></table></div>';
      });
      if (d.exonerados) {
        h += '<div class="aviso-suave" style="margin-top:12px">' + d.exonerados +
          ' persona(s) exonerada(s) de SENA e ICBF por el artículo 114-1 del ' +
          'Estatuto Tributario (ganan menos de 10 salarios mínimos).</div>';
      }
      modal('📤 Planilla PILA', h);
    }).catch(errToast);
  };

  // ══════════════════════════════════════════════════════════════════
  window.nomEmpleado = function () { formEmpleado(null); };
  window.nomEditar = function () {
    var el = this;
    api('/api/nomina/empleados').then(function (d) {
      var e = (d.items || []).filter(function (x) {
        return String(x.id) === el.getAttribute('data-id'); })[0];
      formEmpleado(e);
    }).catch(errToast);
  };

  function formEmpleado(e) {
    e = e || {};
    var arlOps = cat.arl.map(function (a) {
      return '<option value="' + a.clase + '"' +
        (String(e.clase_riesgo) === String(a.clase) ? ' selected' : '') + '>Clase ' +
        a.clase + ' · ' + numero(a.tarifa, 3) + ' % · ' + esc(a.descripcion) + '</option>';
    }).join('');

    modal(e.id ? 'Editar empleado' : 'Nuevo empleado',
      '<div class="fila"><div class="campo"><label for="em-td">Documento</label>' +
      '<select id="em-td"><option value="CC">CC</option><option value="CE">CE</option>' +
      '<option value="PAS">Pasaporte</option><option value="PPT">PPT</option></select></div>' +
      '<div class="campo"><label for="em-nd">Número</label>' +
      '<input type="text" id="em-nd" value="' + esc(e.numero_doc || '') + '"></div></div>' +
      '<div class="fila"><div class="campo"><label for="em-n">Nombres</label>' +
      '<input type="text" id="em-n" value="' + esc(e.nombres || '') + '"></div>' +
      '<div class="campo"><label for="em-a">Apellidos</label>' +
      '<input type="text" id="em-a" value="' + esc(e.apellidos || '') + '"></div></div>' +
      '<div class="fila"><div class="campo"><label for="em-c">Cargo</label>' +
      '<input type="text" id="em-c" value="' + esc(e.cargo || '') + '"></div>' +
      '<div class="campo"><label for="em-tc">Contrato</label>' +
      '<select id="em-tc"><option value="indefinido">Indefinido</option>' +
      '<option value="fijo">Término fijo</option>' +
      '<option value="obra">Obra o labor</option>' +
      '<option value="aprendiz">Aprendiz SENA</option></select></div></div>' +
      '<div class="fila"><div class="campo"><label for="em-fi">Ingreso</label>' +
      '<input type="date" id="em-fi" value="' + esc(e.fecha_ingreso || '') + '"></div>' +
      '<div class="campo"><label for="em-s">Salario base</label>' +
      '<input type="number" id="em-s" step="1000" value="' + (e.salario_base || 0) + '"></div>' +
      '<div class="campo"><label for="em-pp">Puntos de propina</label>' +
      '<input type="number" id="em-pp" step="0.5" value="' + (e.puntos_propina || 1) +
      '"></div></div>' +
      '<div class="fila"><div class="campo"><label for="em-eps">EPS</label>' +
      '<input type="text" id="em-eps" value="' + esc(e.eps || '') + '"></div>' +
      '<div class="campo"><label for="em-afp">Fondo de pensiones</label>' +
      '<input type="text" id="em-afp" value="' + esc(e.afp || '') + '"></div></div>' +
      '<div class="fila"><div class="campo"><label for="em-arl">ARL</label>' +
      '<input type="text" id="em-arl" value="' + esc(e.arl || '') + '"></div>' +
      '<div class="campo"><label for="em-cr">Clase de riesgo</label>' +
      '<select id="em-cr">' + arlOps + '</select></div></div>' +
      '<p class="nota">La clase de riesgo define la tarifa de ARL. En una cocina la ' +
      'mayoría del personal está en clase III por manejo de fuego y cuchillos.</p>',
      'Guardar', function () {
        var body = {
          tipo_doc: document.getElementById('em-td').value,
          numero_doc: val('em-nd'), nombres: val('em-n'), apellidos: val('em-a'),
          cargo: val('em-c'), tipo_contrato: document.getElementById('em-tc').value,
          fecha_ingreso: val('em-fi'),
          salario_base: parseFloat(val('em-s') || '0'),
          puntos_propina: parseFloat(val('em-pp') || '1'),
          eps: val('em-eps'), afp: val('em-afp'), arl: val('em-arl'),
          clase_riesgo: document.getElementById('em-cr').value
        };
        api(e.id ? '/api/nomina/empleados/' + e.id : '/api/nomina/empleados',
            { method: e.id ? 'PUT' : 'POST', body: body })
          .then(function () { modalCerrar(); toast('Empleado guardado', 'ok'); cargar(); })
          .catch(errToast);
      });
  }
})();
