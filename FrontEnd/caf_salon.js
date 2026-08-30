/* ══════════════════════════════════════════════════════════════════════
   RESTAURANTE · Módulo SALÓN

   El mapa de mesas es la pantalla que el mesero mira todo el turno. Su
   requisito dominante no es riqueza funcional sino LEGIBILIDAD A DISTANCIA:
   hay que saber de un vistazo, desde el otro lado del salón, qué mesa está
   libre y cuál lleva demasiado tiempo esperando.

   Por eso el estado se comunica con color y el tiempo con un contador, en vez
   de con texto que haya que leer de cerca.

   Se refresca solo cada 20 segundos porque el salón cambia sin que este
   navegador intervenga: otro mesero ocupa una mesa desde su terminal y esta
   pantalla debe enterarse.

   Backend: /api/salon/*
   ══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var COLOR = '#0891B2';
  var datos = null, reloj = null, zonaActiva = '';

  window.salonInyectar = function () {
    crearPagina('salon', '🪑', 'Salón',
      'Mapa de mesas en vivo, reservas del día y apertura de cuentas.', COLOR);
    var acc = document.getElementById('acc-salon');
    if (acc && !acc.innerHTML) {
      acc.innerHTML =
        '<button class="btn" data-act="salonReservas">🗓 Ver reservas</button>' +
        '<button class="btn btn-p" data-act="salonNuevaReserva">📅 Nueva reserva</button>' +
        '<button class="btn" data-act="salonAlAbrir">↻ Actualizar</button>';
    }
  };

  window.salonAlAbrir = function () {
    cargando('cont-salon');
    cargar();
    // Un salón cambia por acción de OTRAS terminales. Sin refresco automático,
    // el mesero vería un mapa congelado y ocuparía una mesa ya tomada.
    clearInterval(reloj);
    reloj = setInterval(function () {
      if (document.getElementById('page-salon').classList.contains('on')) cargar(true);
      else clearInterval(reloj);
    }, 20000);
  };

  function cargar(silencioso) {
    api('/api/salon/mapa').then(function (r) { datos = r; pintar(); })
      .catch(function (e) {
        if (!silencioso) {
          document.getElementById('cont-salon').innerHTML =
            '<div class="aviso e">' + esc(e.message) + '</div>';
        }
      });
  }

  function pintar() {
    var k = datos.kpis;
    var h = '<div class="grid g4 mb">' +
      kpi('Ocupación', k.ocupacion_pct + '%', k.ocupadas + ' de ' + k.total + ' mesas',
          k.ocupacion_pct > 80 ? 'warn' : 'ok') +
      kpi('Comensales', String(k.comensales), 'Personas en el salón', 'info') +
      kpi('Consumo en curso', money(k.consumo_salon), 'Cuentas abiertas', '') +
      kpi('Por limpiar', String(k.limpieza),
          k.limpieza ? 'Mesas fuera de servicio' : 'Salón al día',
          k.limpieza ? 'warn' : 'ok') +
      '</div>';

    // Reservas del día: van arriba porque condicionan qué mesas pueden ocuparse.
    if (!(datos.reservas_hoy || []).length) {
      // La sección desaparecía cuando no había ninguna para HOY, y entonces no
      // había forma de distinguir «no hay reservas» de «el sistema no las
      // muestra». Una reserva para mañana existe y no se veía en ningún lado.
      h += '<div class="aviso i mb">📅 No hay reservas para hoy. ' +
        '<b data-act="salonReservas" style="cursor:pointer;text-decoration:underline">' +
        'Ver todas las reservas</b> — las de mañana y las siguientes se ' +
        'consultan ahí.</div>';
    }

    if ((datos.reservas_hoy || []).length) {
      h += '<div class="card mb"><div class="card-h">📅 Reservas de hoy ' +
        '<span class="tag t-info">' + datos.reservas_hoy.length + '</span></div>' +
        '<div class="card-b"><div class="flex">';
      datos.reservas_hoy.forEach(function (r) {
        h += '<div style="border:1px solid var(--linea);border-radius:10px;padding:9px 12px;min-width:190px">' +
          '<b>' + esc(r.hora) + '</b> · ' + esc(r.nombre) +
          '<div class="peq mut">' + r.personas + ' pers.' +
          (r.mesa_codigo ? ' · mesa ' + esc(r.mesa_codigo) : ' · sin mesa asignada') +
          (r.origen === 'web' ? ' · <span class="tag t-info">web</span>' : '') + '</div>' +
          '<div class="btns mt">' +
          '<button class="btn btn-sm btn-p" data-act="salonSentar" data-args="' + arg(r.id) +
          '">Sentar</button>' +
          // Asignar la mesa ANTES de que llegue el cliente es media operación
          // de un restaurante con reservas: se arma el salón de la noche por
          // la tarde. Hacerlo solo al sentar obliga a improvisar con la
          // persona de pie en la puerta.
          '<button class="btn btn-sm" data-act="salonAsignarMesa" data-id="' + r.id +
          '">' + (r.mesa_codigo ? '✎ Cambiar mesa' : '🪑 Asignar mesa') + '</button>' +
          '</div></div>';
      });
      h += '</div></div></div>';
    }

    // Filtro por zona
    var zonas = [];
    datos.mesas.forEach(function (m) { if (zonas.indexOf(m.zona) === -1) zonas.push(m.zona); });
    h += '<div class="tabs"><button class="tab' + (zonaActiva === '' ? ' on' : '') +
      '" data-act="salonZona" data-args="">Todo el salón</button>';
    zonas.forEach(function (z) {
      h += '<button class="tab' + (zonaActiva === z ? ' on' : '') +
        '" data-act="salonZona" data-args="' + arg(z) + '">' + esc(z) + '</button>';
    });
    h += '</div>';

    // Leyenda: sin ella los colores hay que adivinarlos.
    h += '<div class="flex mb peq">';
    Object.keys(datos.estados).forEach(function (e) {
      h += '<span><i style="display:inline-block;width:11px;height:11px;border-radius:3px;' +
        'background:' + datos.estados[e].color + ';margin-right:5px"></i>' +
        esc(datos.estados[e].label) + '</span>';
    });
    h += '</div>';

    h += '<div class="mesas">';
    var visibles = datos.mesas.filter(function (m) { return !zonaActiva || m.zona === zonaActiva; });
    if (!visibles.length) h += vacio('🪑', 'No hay mesas en esta zona.');

    visibles.forEach(function (m) {
      var libre = m.estado === 'libre';
      // El tiempo en mesa es la señal que el mesero necesita: más de hora y
      // media suele significar que la mesa ya debería estar cobrando.
      var alerta = m.minutos != null && m.minutos > 90;
      h += '<div class="mesa" style="border-color:' + m.estado_color + ';' +
        (libre ? '' : 'background:' + m.estado_color + '10') + '" ' +
        'data-act="salonMesa" data-args="' + arg(m.id) + '">' +
        '<div class="mesa-cod">' + esc(m.codigo) + '</div>' +
        '<div class="mesa-est" style="background:' + m.estado_color + '">' +
        esc(m.estado_label) + '</div>' +
        '<div class="mesa-cap">👤 ' + (m.comensales || m.capacidad) + '/' + m.capacidad + '</div>' +
        (m.comanda ? '<div class="mesa-cta">' + money(m.consumo) + '</div>' : '') +
        (m.minutos != null ? '<div class="mesa-min' + (alerta ? ' alerta' : '') + '">⏱ ' +
          m.minutos + ' min</div>' : '') +
        (m.mesero ? '<div class="peq mut">' + esc(String(m.mesero).split(' ')[0]) + '</div>' : '') +
        '</div>';
    });
    h += '</div>';

    document.getElementById('cont-salon').innerHTML = h;
  }

  window.salonZona = function (z) { zonaActiva = z || ''; pintar(); };

  // ── Acción sobre una mesa ─────────────────────────────────────────
  window.salonMesa = function (id) {
    var m = datos.mesas.filter(function (x) { return String(x.id) === String(id); })[0];
    if (!m) return;

    if (m.estado === 'libre' || m.estado === 'reservada') {
      modal('Sentar en la mesa ' + m.codigo,
        '<p class="mut peq mb">Capacidad de la mesa: ' + m.capacidad + ' personas. ' +
        'Al sentar se abre la cuenta automáticamente.</p>' +
        '<div class="campo"><label for="sl-pers">¿Cuántas personas?</label>' +
        '<input type="number" id="sl-pers" value="' + m.capacidad + '" min="1"></div>' +
        '<div class="campo"><label for="sl-notas">Nota (opcional)</label>' +
        '<input type="text" id="sl-notas" placeholder="Cumpleaños, alergia, silla de bebé…"></div>',
        'Sentar y abrir cuenta', function () { ocupar(id, false); });

    } else if (m.estado === 'ocupada') {
      modal('Mesa ' + m.codigo + ' · ' + money(m.consumo || 0),
        '<p class="mut peq mb">Comanda <b>' + esc(m.comanda || '—') + '</b> · ' +
        (m.comensales || 0) + ' comensales · ' + (m.minutos || 0) + ' minutos.</p>' +
        '<button class="btn btn-p mb" style="width:100%" data-act="salonIrComanda" ' +
        'data-args="' + arg(m.comanda_id) + '">📝 Ver y agregar a la comanda</button>' +
        '<button class="btn btn-g mb" style="width:100%" data-act="salonCobrar" ' +
        'data-args="' + arg(m.comanda_id) + '">💵 Llevar a caja para cobrar</button>' +
        // Se sientan, miran la carta y se van. Pasa todos los días, y hasta
        // ahora la única salida era cobrar una cuenta que no existe: la mesa
        // quedaba trabada. El botón solo aparece si el consumo es CERO —con
        // comida servida, liberar sin registro sería un hueco de caja.
        (Number(m.consumo || 0) === 0
          ? '<button class="btn mb" style="width:100%" data-act="salonLiberarVacia" ' +
            'data-id="' + m.id + '">🚪 Se fueron sin consumir · liberar</button>' +
            '<div class="aviso i peq">Esta mesa no tiene consumo. Se puede liberar sin cobrar.</div>'
          : '<div class="aviso i peq">Para liberar la mesa primero hay que cobrar la cuenta.</div>'),
        null, null);

    } else {   // limpieza
      modalConfirmar('¿La mesa ' + m.codigo + ' ya está limpia y lista?', function () {
        api('/api/salon/mesas/' + id + '/liberar', { method: 'POST', body: { directo: true } })
          .then(function () { toast('Mesa ' + m.codigo + ' disponible', 'ok'); cargar(); })
          .catch(errToast);
      });
    }
  };

  /**
   * Liberar una mesa donde nadie consumió.
   *
   * Se pide el motivo pero no se obliga: en el mostrador, un campo obligatorio
   * que nadie quiere llenar se llena con «xxx». Se propone el caso típico y se
   * deja cambiarlo. Lo que sí queda siempre es quién lo hizo y cuándo.
   */
  window.salonLiberarVacia = function () {
    var id = this.getAttribute('data-id');
    var m = (datos.mesas || []).filter(function (x) {
      return String(x.id) === String(id);
    })[0] || {};

    modal('🚪 Liberar la mesa ' + esc(m.codigo || ''),
      '<p class="nota">La mesa no tiene consumo, así que no hay nada que cobrar. ' +
      'Se libera y su cuenta queda anulada con el motivo.</p>' +
      '<div class="campo"><label for="lv-motivo">¿Qué pasó?</label>' +
      '<input type="text" id="lv-motivo" style="width:100%;display:block" ' +
      'value="Se retiraron sin consumir"></div>' +
      '<label class="peq" style="display:flex;align-items:center;gap:7px;cursor:pointer">' +
      '<input type="checkbox" id="lv-limpiar" style="width:auto">' +
      'Marcarla «por limpiar» en vez de libre</label>',
      'Liberar mesa', function () {
        api('/api/salon/mesas/' + id + '/liberar-sin-consumo', {
          method: 'POST',
          body: { motivo: val('lv-motivo'),
                  limpiar: document.getElementById('lv-limpiar').checked }
        }).then(function (r) {
          modalCerrar();
          toast(r.mensaje || 'Mesa liberada', 'ok');
          cargar();
        }).catch(errToast);
      });
  };

  function ocupar(id, forzar) {
    api('/api/salon/mesas/' + id + '/ocupar', {
      method: 'POST',
      body: { personas: Number(val('sl-pers') || 1), notas: val('sl-notas'), forzar: !!forzar }
    }).then(function (r) {
      modalCerrar();
      toast('Cuenta ' + r.comanda.numero + ' abierta', 'ok');
      cargar();
      if (window.comandasAbrir) window.comandasAbrir(r.comanda.id);
    }).catch(function (e) {
      // El servidor avisa si se exceden las sillas. Se ofrece confirmar en vez
      // de bloquear: juntar sillas de otra mesa es normal en un restaurante.
      if (e.status === 409 && /personas/.test(e.message)) {
        modalConfirmar(e.message, function () { ocupar(id, true); });
      } else errToast(e);
    });
  }

  window.salonIrComanda = function (cid) {
    modalCerrar();
    nav('comandas');
    if (window.comandasAbrir) setTimeout(function () { window.comandasAbrir(cid); }, 120);
  };

  window.salonCobrar = function (cid) {
    modalCerrar();
    nav('caja');
    // Sin `setTimeout`. Los 120 ms de antes eran una apuesta: si la caja
    // tardaba mas en pintar, el ticket se armaba y se sobreescribia. La caja
    // guarda la mesa en su propio estado y la pinta cuando le toca, sin
    // importar cual de las dos cosas termine primero.
    if (window.cajaCobrarComanda) window.cajaCobrarComanda(cid);
  };

  // ══════════════════════════════════════════════════════════════════
  //  RESERVAS · la lista completa
  //
  //  El mapa del salón solo muestra las de HOY, porque son las que deciden
  //  qué mesa se puede ocupar ahora. Pero una reserva para mañana existe
  //  desde que el cliente la hace, y hasta ahora no se veía en ninguna
  //  pantalla: el restaurante se enteraba el mismo día. Esto lo resuelve.
  // ══════════════════════════════════════════════════════════════════
  var filtroRes = 'proximas';

  window.salonReservas = function () {
    modal('🗓 Reservas', '<div id="rv-cuerpo"><p class="nota">Consultando…</p></div>',
          '', null);
    cargarReservas();
  };

  window.salonFiltroRes = function (f) { filtroRes = f || 'proximas'; cargarReservas(); };

  var todasReservas = [];   // lo ultimo consultado, para poder sentar desde ahi

  function cargarReservas() {
    api('/api/salon/reservas')
      .then(function (r) {
        todasReservas = r.items || [];
        pintarReservas(todasReservas, r.kpis || {});
      })
      .catch(function (e) {
        var c = document.getElementById('rv-cuerpo');
        if (c) c.innerHTML = '<div class="aviso e">' + esc(e.message) + '</div>';
      });
  }

  function pintarReservas(todas, kpis) {
    var c = document.getElementById('rv-cuerpo');
    if (!c) return;

    var hoyISO = new Date().toISOString().slice(0, 10);
    var vivas = function (r) {
      return r.estado === 'pendiente' || r.estado === 'confirmada';
    };
    var lista = todas.filter(function (r) {
      if (filtroRes === 'hoy') return r.fecha === hoyISO && vivas(r);
      if (filtroRes === 'proximas') return r.fecha >= hoyISO && vivas(r);
      return true;                                   // «todas», historial incluido
    }).sort(function (a, b) {
      return (a.fecha + a.hora).localeCompare(b.fecha + b.hora);
    });

    var pestana = function (k, t) {
      return '<button class="tab' + (filtroRes === k ? ' on' : '') +
        '" data-act="salonFiltroRes" data-args="' + k + '">' + t + '</button>';
    };

    var h = '<div class="tabs">' + pestana('proximas', 'Próximas') +
      pestana('hoy', 'Hoy') + pestana('todas', 'Todas') + '</div>';

    if (!lista.length) {
      h += '<div class="vacio" style="padding:30px 10px"><span class="e">📅</span>' +
        (filtroRes === 'todas' ? 'Todavía no hay reservas.'
                               : 'No hay reservas en este filtro.') + '</div>';
      c.innerHTML = h;
      return;
    }

    h += '<div class="tabla-wrap"><table><thead><tr>' +
      '<th>Cuándo</th><th>Quién</th><th class="num">Pers.</th>' +
      '<th>Mesa</th><th>Origen</th><th>Estado</th><th></th></tr></thead><tbody>';

    lista.forEach(function (r) {
      var esHoy = r.fecha === hoyISO;
      h += '<tr>' +
        '<td><b>' + esc(r.hora) + '</b>' +
        '<div class="peq mut">' + (esHoy ? 'HOY' : esc(r.fecha)) + '</div></td>' +
        '<td>' + esc(r.nombre || '—') +
        (r.telefono ? '<div class="peq mut">' + esc(r.telefono) + '</div>' : '') +
        (r.codigo ? '<div class="peq mut">cód. ' + esc(r.codigo) + '</div>' : '') +
        '</td>' +
        '<td class="num">' + (r.personas || 0) + '</td>' +
        '<td>' + (r.mesa_codigo ? esc(r.mesa_codigo)
                                : '<span class="mut peq">sin asignar</span>') + '</td>' +
        '<td>' + (r.origen === 'web'
                  ? '<span class="tag t-info">web</span>'
                  : '<span class="tag t-gris">interno</span>') + '</td>' +
        '<td><span class="pill ' + pillReserva(r.estado) + '">' +
        esc(r.estado) + '</span></td>' +
        '<td>' + (vivas(r)
          ? '<div class="btns">' +
            '<button class="btn btn-sm btn-p" data-act="salonSentarDesdeLista" ' +
            'data-id="' + r.id + '">Sentar</button>' +
            '<button class="btn btn-sm" data-act="salonAsignarMesa" ' +
            'data-id="' + r.id + '" data-lista="1">' +
            (r.mesa_codigo ? '✎' : '🪑') + '</button></div>'
          : '') + '</td></tr>';
    });

    c.innerHTML = h + '</tbody></table></div>' +
      '<p class="nota">' + lista.length + ' de ' + todas.length +
      ' · las reservas del sitio web entran marcadas como «web» y llegan ' +
      '<b>sin mesa</b>: la asigna quien las siente.</p>';
  }

  function pillReserva(e) {
    return ({ pendiente: 'warn', confirmada: 'info', sentada: 'ok',
              cancelada: '', no_asistio: 'bad' })[e] || '';
  }

  /**
   * Asignar (o cambiar) la mesa de una reserva SIN sentar a nadie.
   *
   * Al guardar, la mesa queda «reservada» en el mapa. Eso es lo que impide
   * que otro mesero siente ahí a quien llegue de paso, que es justo el
   * accidente que una reserva debería evitar.
   */
  window.salonAsignarMesa = function () {
    var rid = this.getAttribute('data-id');
    var desdeLista = this.getAttribute('data-lista') === '1';
    var mismo = function (x) { return String(x.id) === String(rid); };
    var r = (datos.reservas_hoy || []).filter(mismo)[0] ||
            todasReservas.filter(mismo)[0] || {};
    var personas = Number(r.personas || 1);

    // Sirven las libres y también las ya reservadas para OTRA reserva: el
    // encargado puede reorganizar el salón. Las ocupadas no: hay gente comiendo.
    var candidatas = (datos.mesas || []).filter(function (m) {
      return m.estado !== 'ocupada';
    }).sort(function (a, b) {
      var ca = a.capacidad >= personas, cb = b.capacidad >= personas;
      if (ca !== cb) return ca ? -1 : 1;
      return a.capacidad - b.capacidad;
    });

    if (!candidatas.length) {
      toast('No hay mesas disponibles para asignar.', 'warn');
      return;
    }

    var ops = '<option value="">— sin mesa asignada —</option>' +
      candidatas.map(function (m) {
        return '<option value="' + m.id + '"' +
          (String(m.id) === String(r.mesa_id || '') ? ' selected' : '') + '>' +
          esc(m.codigo) + ' · ' + esc(m.zona) + ' (' + m.capacidad + ' pers.)' +
          (m.capacidad < personas ? ' ⚠ queda chica' : '') +
          (m.estado === 'reservada' ? ' · ya reservada' : '') +
          '</option>';
      }).join('');

    modal('🪑 Mesa para ' + esc(r.nombre || 'la reserva'),
      '<p class="nota">' + personas + (personas === 1 ? ' persona' : ' personas') +
      (r.hora ? ' · ' + esc(r.hora) : '') + (r.fecha ? ' · ' + esc(r.fecha) : '') +
      '</p>' +
      '<div class="campo"><label for="am-mesa">Mesa</label>' +
      '<select id="am-mesa" style="width:100%;display:block">' + ops + '</select></div>' +
      '<p class="nota">Al guardar, la mesa queda <b>reservada</b> en el mapa para ' +
      'que nadie más la ocupe. Dejarla «sin mesa» la libera.</p>',
      'Guardar', function () {
        var mesa = Number(val('am-mesa')) || null;
        api('/api/salon/reservas/' + rid, { method: 'PUT', body: { mesa_id: mesa } })
          .then(function () {
            modalCerrar();
            toast(mesa ? 'Mesa asignada' : 'Reserva sin mesa', 'ok');
            cargar();
            if (desdeLista) setTimeout(window.salonReservas, 350);
          }).catch(errToast);
      });
  };

  /** Sentar desde la lista: se cierra el modal para que se vea el salón. */
  window.salonSentarDesdeLista = function () {
    var rid = this.getAttribute('data-id');
    modalCerrar();
    cargar();
    setTimeout(function () { window.salonSentar(rid); }, 400);
  };

  // ── Reservas ──────────────────────────────────────────────────────
  window.salonNuevaReserva = function () {
    var libres = (datos.mesas || []).filter(function (m) { return m.estado === 'libre'; });
    var opciones = '<option value="">Sin mesa asignada</option>' +
      libres.map(function (m) {
        return '<option value="' + m.id + '">' + esc(m.codigo) + ' · ' + esc(m.zona) +
          ' (' + m.capacidad + ' pers.)</option>';
      }).join('');
    var hoy = new Date().toISOString().slice(0, 10);

    modal('📅 Nueva reserva',
      '<div class="campo"><label for="rs-nombre">Nombre de quien reserva</label>' +
      '<input type="text" id="rs-nombre"></div>' +
      '<div class="fila">' +
      '<div class="campo"><label for="rs-fecha">Fecha</label>' +
      '<input type="date" id="rs-fecha" value="' + hoy + '"></div>' +
      '<div class="campo"><label for="rs-hora">Hora</label>' +
      '<input type="text" id="rs-hora" placeholder="19:30"></div>' +
      '<div class="campo"><label for="rs-pers">Personas</label>' +
      '<input type="number" id="rs-pers" value="2" min="1"></div></div>' +
      '<div class="fila">' +
      '<div class="campo"><label for="rs-tel">Teléfono</label>' +
      '<input type="text" id="rs-tel"></div>' +
      '<div class="campo"><label for="rs-mesa">Mesa</label>' +
      '<select id="rs-mesa">' + opciones + '</select></div></div>' +
      '<div class="campo"><label for="rs-notas">Notas</label>' +
      '<input type="text" id="rs-notas" placeholder="Preferencia de ubicación, celebración…"></div>',
      'Crear reserva', function () {
        if (!val('rs-nombre')) return toast('Indique el nombre', 'warn');
        if (!val('rs-hora')) return toast('Indique la hora', 'warn');
        api('/api/salon/reservas', {
          method: 'POST',
          body: { nombre: val('rs-nombre'), fecha: val('rs-fecha'), hora: val('rs-hora'),
                  personas: Number(val('rs-pers') || 2), telefono: val('rs-tel'),
                  mesa_id: Number(val('rs-mesa')) || null, notas: val('rs-notas') }
        }).then(function (r) {
          modalCerrar();
          toast('Reserva ' + r.codigo + ' creada', 'ok');
          cargar();
        }).catch(errToast);
      });
  };

  /**
   * Sentar una reserva.
   *
   * Una reserva hecha desde la web NO trae mesa: el cliente reserva a las
   * siete de la tarde y quien decide en cual mesa lo sienta es el mesero, con
   * el salon delante. Por eso, si no hay mesa asignada, hay que preguntarla
   * ANTES de llamar al servidor. Enviar el cuerpo vacio -como se hacia- dejaba
   * el boton muerto para toda reserva web: el backend respondia «Indique en
   * que mesa se sienta» y no habia forma de indicarla.
   */
  window.salonSentar = function (rid) {
    // Se busca en las de HOY y tambien en la lista completa: desde «Ver
    // reservas» se puede sentar una de otro dia —alguien que llega antes, o
    // una reserva que se adelanta—, y esa no esta en `reservas_hoy`.
    var mismo = function (x) { return String(x.id) === String(rid); };
    var r = (datos.reservas_hoy || []).filter(mismo)[0] ||
            todasReservas.filter(mismo)[0] || {};

    if (r.mesa_id) { sentarEn(rid, null); return; }

    // Solo mesas libres, y se avisa cuando la mesa queda chica en vez de
    // esconderla: a veces se juntan sillas y esa decision es del mesero.
    var libres = (datos.mesas || []).filter(function (m) {
      return m.estado === 'libre';
    });
    if (!libres.length) {
      toast('No hay mesas libres en este momento.', 'warn');
      return;
    }
    var personas = Number(r.personas || 1);
    var opciones = libres.sort(function (a, b) {
      // Primero las que le sirven, y entre esas la mas ajustada: sentar a dos
      // personas en la mesa de seis deja sin sitio al grupo que llegue luego.
      var ca = a.capacidad >= personas, cb = b.capacidad >= personas;
      if (ca !== cb) return ca ? -1 : 1;
      return a.capacidad - b.capacidad;
    }).map(function (m) {
      return '<option value="' + m.id + '">' + esc(m.codigo) + ' · ' + esc(m.zona) +
        ' (' + m.capacidad + ' pers.)' +
        (m.capacidad < personas ? ' ⚠ queda chica' : '') + '</option>';
    }).join('');

    modal('Sentar a ' + esc(r.nombre || 'la reserva'),
      '<p class="nota">' + personas +
      (personas === 1 ? ' persona' : ' personas') +
      (r.hora ? ' · reservó para las ' + esc(r.hora) : '') +
      '. Al sentar se abre la cuenta automáticamente.</p>' +
      '<div class="campo"><label for="se-mesa">¿En qué mesa se sienta?</label>' +
      '<select id="se-mesa">' + opciones + '</select></div>',
      'Sentar y abrir cuenta', function () {
        var mesa = Number(val('se-mesa')) || 0;
        if (!mesa) { toast('Elija una mesa.', 'warn'); return; }
        sentarEn(rid, mesa);
      });
  };

  function sentarEn(rid, mesaId) {
    api('/api/salon/reservas/' + rid + '/sentar', {
      method: 'POST',
      body: mesaId ? { mesa_id: mesaId } : {}
    }).then(function (r) {
      modalCerrar();
      toast('Cuenta ' + r.comanda.numero + ' abierta', 'ok');
      cargar();
    }).catch(errToast);
  }

  function kpi(t, v, d, c) {
    return '<div class="kpi ' + (c || '') + '"><div class="k">' + esc(t) + '</div>' +
      '<div class="v">' + esc(v) + '</div><div class="d">' + esc(d) + '</div></div>';
  }
})();
