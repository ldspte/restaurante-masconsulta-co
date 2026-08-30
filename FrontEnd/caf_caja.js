/* ══════════════════════════════════════════════════════════════════════
   CAFETERÍA · Módulo CAJA (punto de venta)

   Es la pantalla donde el sistema pasa más horas al día, así que prioriza
   velocidad de operación: un clic agrega producto, el ticket vive al lado y
   el cobro cabe en dos pasos.

   El carrito guarda ÚNICAMENTE producto y cantidad. Los precios que muestra
   son informativos para el cajero; el importe que se cobra lo calcula el
   servidor. Si esta pantalla se equivocara al sumar, el cobro seguiría siendo
   correcto.

   Backend: /api/caja/*
   ══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var COLOR = '#16A34A';
  var estado = null;        // respuesta de /api/caja/estado
  var carrito = [];         // [{producto_id, nombre, precio, iva_pct, cantidad}]
  var filtroCat = '';
  var enviando = false;     // evita el doble clic en «Cobrar»
  var comanda = null;       // {id, mesa, numero} si el ticket viene del salón
  var propina = null;       // null = todavía no se ha preguntado al cliente
  var cats = null;          // catálogos DIAN (tipos de documento)
  var adquiriente = null;   // {tipo_doc, numero_doc, razon_social, email, telefono}

  window.cajaInyectar = function () {
    crearPagina('caja', '🧾', 'Caja',
      'Apertura de turno, registro de ventas y arqueo de cierre.', COLOR);
    var acc = document.getElementById('acc-caja');
    if (acc && !acc.innerHTML) {
      acc.innerHTML = '<button class="btn" data-act="cajaAlAbrir">↻ Actualizar</button>' +
        '<button class="btn" id="btn-cerrar-caja" data-act="cajaCerrarTurno" style="display:none">🔒 Cerrar turno</button>';
    }
  };

  window.cajaAlAbrir = function () {
    cargando('cont-caja');
    api('/api/caja/estado').then(function (r) {
      estado = r;
      var btn = document.getElementById('btn-cerrar-caja');
      if (btn) btn.style.display = r.caja ? '' : 'none';
      r.caja ? pintarPOS() : pintarSinTurno();
    }).catch(function (e) {
      document.getElementById('cont-caja').innerHTML =
        '<div class="aviso e">' + esc(e.message) + '</div>';
    });
  };

  // ══════════════════════════════════════════════════════════════════
  //  SIN TURNO ABIERTO
  // ══════════════════════════════════════════════════════════════════
  function pintarSinTurno() {
    // Si el cajero llego aqui mandado desde una mesa, hay que decirselo: si no,
    // parece que el sistema perdio la cuenta. Se retoma sola al abrir el turno.
    var aviso = comanda
      ? '<div class="aviso i" style="text-align:left">Trae la cuenta de la mesa <b>' +
        esc(comanda.mesa || '') + '</b>. Abra el turno y la cuenta se carga sola: ' +
        'no se pierde.</div>'
      : '';
    document.getElementById('cont-caja').innerHTML =
      '<div class="card" style="max-width:440px;margin:40px auto"><div class="card-b" style="text-align:center">' +
      aviso +
      '<div style="font-size:48px">🔓</div>' +
      '<h3 style="margin:10px 0 6px">Abrir turno de caja</h3>' +
      '<p class="mut peq mb">Registre el efectivo con el que inicia. Al cerrar, el sistema ' +
      'comparará ese valor más las ventas en efectivo contra lo que usted cuente.</p>' +
      '<div class="campo" style="text-align:left"><label for="ca-base">Base inicial</label>' +
      '<input type="number" id="ca-base" value="100000" min="0" step="1000"></div>' +
      '<button class="btn btn-p" style="width:100%;padding:10px" data-act="cajaAbrirTurno">Abrir turno</button>' +
      '</div></div>';
  }

  window.cajaAbrirTurno = function () {
    var base = Number(val('ca-base') || 0);
    if (base < 0) return toast('La base no puede ser negativa', 'warn');
    api('/api/caja/abrir', { method: 'POST', body: { base_inicial: base } })
      .then(function () {
        toast('Turno abierto', 'ok');
        // Se recuerda la mesa que el cajero traia del salon. Antes se vaciaba
        // el carrito y se dejaba `comanda` puesta: el ticket quedaba con el
        // encabezado de la mesa y SIN lineas, sin boton de cobrar y sin
        // explicar por que. Volver a cargarla es lo unico correcto — el
        // cajero llego aqui precisamente para cobrar esa mesa.
        var pendiente = comanda && comanda.id;
        carrito = [];
        comanda = null;
        cajaAlAbrir();
        if (pendiente) window.cajaCobrarComanda(pendiente);
      })
      .catch(errToast);
  };

  // ══════════════════════════════════════════════════════════════════
  //  PUNTO DE VENTA
  // ══════════════════════════════════════════════════════════════════
  function pintarPOS() {
    var cats = [];
    estado.productos.forEach(function (p) {
      if (cats.indexOf(p.categoria) === -1) cats.push(p.categoria);
    });

    var h = '<div class="grid g4 mb">' +
      kpiChip('Turno', '#' + estado.caja.id, 'Abierto ' + fecha(estado.caja.apertura_ts, true)) +
      kpiChip('Base inicial', money(estado.caja.base_inicial), 'Efectivo de apertura') +
      kpiChip('Ventas del turno', estado.resumen ? String(estado.resumen.n) : '0', 'Transacciones') +
      kpiChip('Recaudo', estado.resumen ? money(estado.resumen.total) : money(0), 'Total cobrado') +
      '</div>';

    h += '<div class="pos"><div>';
    h += '<div class="tabs"><button class="tab' + (filtroCat === '' ? ' on' : '') +
      '" data-act="cajaFiltro" data-args="">Todos</button>';
    cats.forEach(function (c) {
      h += '<button class="tab' + (filtroCat === c ? ' on' : '') + '" data-act="cajaFiltro" data-args="' +
        arg(c) + '">' + esc(c) + '</button>';
    });
    h += '</div><div class="prods">';

    var visibles = estado.productos.filter(function (p) { return !filtroCat || p.categoria === filtroCat; });
    if (!visibles.length) {
      h += vacio('☕', 'No hay productos en esta categoría.');
    } else {
      visibles.forEach(function (p) {
        h += '<div class="prod" data-act="cajaAgregar" data-args="' + arg(p.id) + '">' +
          '<span class="em">' + (p.emoji || '☕') + '</span>' +
          '<div class="nm">' + esc(p.nombre) + '</div>' +
          '<div class="pr">' + money(p.precio) + '</div></div>';
      });
    }
    h += '</div></div><div id="tk-wrap">' + pintarTicket() + '</div></div>';

    document.getElementById('cont-caja').innerHTML = h;
  }

  window.cajaFiltro = function (c) { filtroCat = c || ''; pintarPOS(); };

  window.cajaAgregar = function (id) {
    var p = estado.productos.filter(function (x) { return String(x.id) === String(id); })[0];
    if (!p) return;
    var linea = carrito.filter(function (x) { return x.producto_id === p.id; })[0];
    if (linea) linea.cantidad += 1;
    else carrito.push({ producto_id: p.id, nombre: p.nombre, precio: Number(p.precio),
                        iva_pct: Number(p.iva_pct || 0), cantidad: 1 });
    refrescarTicket();
  };

  window.cajaCantidad = function (id, delta) {
    var linea = carrito.filter(function (x) { return String(x.producto_id) === String(id); })[0];
    if (!linea) return;
    linea.cantidad += Number(delta);
    if (linea.cantidad <= 0) {
      carrito = carrito.filter(function (x) { return x.producto_id !== linea.producto_id; });
    }
    refrescarTicket();
  };

  window.cajaVaciar = function () {
    carrito = []; comanda = null; propina = null; refrescarTicket();
  };

  // ══════════════════════════════════════════════════════════════════
  //  PROPINA
  //
  //  Ley 1935 de 2018: es voluntaria y hay que informarla. Por eso «Sin
  //  propina» esta al lado de la sugerida y es igual de facil de oprimir; no
  //  escondido detras de un campo que hay que borrar.
  //
  //  Y no entra en la base gravable del impuesto al consumo (art. 512-9
  //  E.T.): se suma DESPUES del impuesto, nunca antes.
  // ══════════════════════════════════════════════════════════════════
  // ══════════════════════════════════════════════════════════════════
  //  ADQUIRIENTE · solo para factura electronica
  //
  //  La DIAN entrega la factura POR CORREO, asi que el correo no es un
  //  «dato adicional»: sin el, el documento se emite y el cliente nunca lo
  //  recibe. Por eso el backend lo exige y aqui se pide en el mismo renglon
  //  que el nombre.
  //
  //  El DV del NIT NO se pide: lo calcula el servidor. Preguntarlo solo
  //  agrega un campo que se digita mal y que ademas es deducible.
  // ══════════════════════════════════════════════════════════════════
  window.cajaDocPOS = function () {
    adquiriente = null;
    marcarTipoDoc();
    pintarAdquiriente();
  };

  window.cajaDocFactura = function () {
    adquiriente = adquiriente || { tipo_doc: '13' };
    marcarTipoDoc();
    if (cats) { pintarAdquiriente(); return; }
    // Los tipos de documento vienen de la BASE, no escritos aqui: el catalogo
    // es editable y el sistema se usa fuera de Colombia.
    api('/api/facturacion/catalogos')
      .then(function (r) { cats = r; pintarAdquiriente(); })
      .catch(function (e) { errToast(e); window.cajaDocPOS(); });
  };

  function marcarTipoDoc() {
    var pos = document.getElementById('pg-tipo-pos');
    var fe = document.getElementById('pg-tipo-fe');
    if (pos) pos.className = 'btn btn-sm' + (adquiriente ? '' : ' on');
    if (fe) fe.className = 'btn btn-sm' + (adquiriente ? ' on' : '');
  }

  function pintarAdquiriente() {
    var caja = document.getElementById('pg-adq');
    if (!caja) return;

    if (!adquiriente) { caja.innerHTML = ''; return; }
    if (!cats) { caja.innerHTML = '<p class="nota">Cargando catálogos…</p>'; return; }

    var tipos = (cats.tipos_doc || []).map(function (t) {
      return '<option value="' + t.codigo + '"' +
        (String(t.codigo) === String(adquiriente.tipo_doc) ? ' selected' : '') +
        '>' + esc(t.sigla || t.codigo) + ' · ' + esc(t.nombre) + '</option>';
    }).join('');

    caja.innerHTML =
      '<div class="fila">' +
      '<div class="campo"><label for="ad-t">Tipo de documento</label>' +
      '<select id="ad-t" style="width:100%;display:block">' + tipos + '</select></div>' +
      '<div class="campo" style="flex:1.3"><label for="ad-n">Número</label>' +
      '<input type="text" id="ad-n" inputmode="numeric" style="width:100%;display:block" ' +
      'placeholder="Sin puntos ni guiones" ' +
      'value="' + esc(adquiriente.numero_doc || '') + '"></div>' +
      '</div>' +
      // El nombre va DENTRO de un `.fila`, igual que los demas, y con el ancho
      // escrito en el propio elemento. Suelto en un `.campo` a secas no se
      // pintaba en produccion: el recuadro quedaba pegado a la etiqueta y
      // encima del campo siguiente. En vez de perseguir que regla de estilos
      // lo causaba, se usa la estructura que ahi SI funciona y se deja de
      // depender de la hoja de estilos para algo tan basico como el ancho.
      '<div class="fila">' +
      '<div class="campo"><label for="ad-r">Nombre o razón social</label>' +
      '<input type="text" id="ad-r" style="width:100%;display:block" ' +
      'value="' + esc(adquiriente.razon_social || '') + '"></div>' +
      '</div>' +
      '<div class="fila">' +
      '<div class="campo"><label for="ad-e">Correo</label>' +
      '<input type="email" id="ad-e" style="width:100%;display:block" ' +
      'placeholder="donde llega la factura" ' +
      'value="' + esc(adquiriente.email || '') + '"></div>' +
      '<div class="campo"><label for="ad-c">Celular</label>' +
      '<input type="text" id="ad-c" inputmode="tel" style="width:100%;display:block" ' +
      'value="' + esc(adquiriente.telefono || '') + '"></div>' +
      '</div>' +
      '<div class="sug">Si el documento ya existe, se reutiliza el cliente y no ' +
      'se duplica. El dígito de verificación del NIT lo calcula el sistema.</div>';
  }

  /** Lo escrito en el formulario, o null si se factura como POS. */
  function leerAdquiriente() {
    if (!adquiriente) return null;
    return {
      tipo_doc: val('ad-t') || '13',
      numero_doc: (val('ad-n') || '').replace(/[.\s-]/g, ''),
      razon_social: val('ad-r'),
      email: val('ad-e'),
      telefono: val('ad-c')
    };
  }

  window.cajaPropina = function (valor) {
    propina = Math.max(0, Number(valor) || 0);
    refrescarTicket();
  };

  window.cajaPropinaOtra = function () {
    var t = totales();
    modal('Propina',
      '<p class="nota">Se pregunta al cliente. Va completa al personal: no es ' +
      'ingreso del restaurante ni causa impuesto.</p>' +
      '<div class="campo"><label for="pr-v">Valor</label>' +
      '<input type="number" id="pr-v" min="0" step="500" value="' +
      (propina === null ? 0 : propina) + '"></div>' +
      '<p class="nota">Consumo del ticket: ' + money(t.sub) + '</p>',
      'Aplicar', function () {
        modalCerrar();
        window.cajaPropina(val('pr-v'));
      });
  };

  // ══════════════════════════════════════════════════════════════════
  //  COBRAR UNA MESA DEL SALÓN
  //
  //  El salón llamaba a esta función desde «Llevar a caja para cobrar»…
  //  y la función NO EXISTÍA. El `if (window.cajaCobrarComanda)` de allá la
  //  hacía fallar en silencio: el cajero aterrizaba en Caja con el ticket
  //  vacío y tenía que buscar la mesa a mano. Un camino muerto que ninguna
  //  pantalla delataba.
  // ══════════════════════════════════════════════════════════════════
  window.cajaRecargarMesa = function () {
    if (comanda) window.cajaCobrarComanda(comanda.id);
  };

  window.cajaCobrarComanda = function (cid) {
    api('/api/comandas/' + cid)
      .then(function (d) {
        var o = d.comanda || {};
        if (o.estado === 'cerrada') {
          toast('Esa comanda ya fue cobrada.', 'warn');
          return;
        }
        var lineas = (d.items || []).filter(function (i) { return i.estado !== 'anulado'; });
        if (!lineas.length) {
          toast('La mesa no tiene nada que cobrar todavía.', 'warn');
          return;
        }
        // Se llena el ticket para que el cajero VEA lo que va a cobrar. El
        // importe de verdad lo recalcula el servidor desde la comanda.
        carrito = lineas.map(function (i) {
          return { producto_id: i.producto_id, nombre: i.nombre,
                   precio: Number(i.precio_unit || 0),
                   iva_pct: Number(i.iva_pct || 0),
                   cantidad: Number(i.cantidad || 0) };
        });
        comanda = { id: cid, mesa: o.mesa, numero: o.numero, personas: o.personas };
        refrescarTicket();
      })
      .catch(errToast);
  };

  function totales() {
    var sub = 0, iva = 0;
    carrito.forEach(function (l) {
      var s = l.precio * l.cantidad;
      sub += s;
      iva += s * (l.iva_pct || 0) / 100;
    });
    return { sub: Math.round(sub * 100) / 100, iva: Math.round(iva * 100) / 100,
             total: Math.round((sub + iva) * 100) / 100 };
  }

  function pintarTicket() {
    var t = totales();
    var h = '<div class="card ticket"><div class="card-h">' +
      (comanda ? '🍽 ' + esc(comanda.mesa || ('Comanda ' + comanda.id))
               : '🛒 Ticket') + ' ' +
      (carrito.length ? '<span class="tag t-info">' + carrito.length + '</span>' : '') +
      '</div><div class="card-b" id="tk-body">';

    // De donde salio este ticket. Sin esto el cajero ve una lista de platos y
    // no sabe a que mesa cobrarle: es justo lo que pasaba antes, cuando la
    // mesa se quedaba en el salon y a la caja no llegaba nada.
    if (comanda) {
      h += '<div class="aviso i" style="margin-bottom:10px">Cuenta de la mesa <b>' +
        esc(comanda.mesa || '—') + '</b>' +
        (comanda.numero ? ' · ' + esc(comanda.numero) : '') +
        (comanda.personas ? ' · ' + comanda.personas + ' pers.' : '') +
        '<br><span class="peq">Las líneas vienen de la comanda; el servidor cobra ' +
        'lo servido, no lo que se digite aquí.</span></div>';
    }

    if (!carrito.length) {
      // Si hay mesa pero no hay lineas, algo se perdio por el camino. Decirlo
      // y ofrecer recargar es mejor que mostrar «toque un producto», que
      // sugiere que la mesa no tenia nada cuando si tenia.
      h += comanda
        ? '<div class="aviso w">No se cargaron las líneas de esta mesa.' +
          '<br><button class="btn btn-sm mt" data-act="cajaRecargarMesa">' +
          'Volver a cargar la cuenta</button></div>'
        : '<div class="vacio" style="padding:26px 10px"><span class="e">🛒</span>' +
          'Toque un producto para agregarlo.</div>';
    } else {
      carrito.forEach(function (l) {
        h += '<div class="tk-item"><div class="n">' + esc(l.nombre) + '<br>' +
          '<span class="peq mut">' + money(l.precio) + ' c/u</span></div>' +
          '<div class="q">' +
          '<button data-act="cajaCantidad" data-args="' + arg(l.producto_id) + '|-1">−</button>' +
          '<b style="min-width:18px;text-align:center">' + l.cantidad + '</b>' +
          '<button data-act="cajaCantidad" data-args="' + arg(l.producto_id) + '|1">+</button>' +
          '</div><div class="s">' + money(l.precio * l.cantidad) + '</div></div>';
      });
      // La propina se decide AQUI, con el cliente delante, no escondida en la
      // ventana de cobro. El mesero le pregunta y la deja puesta; el cajero
      // solo confirma. Sugerida sobre el CONSUMO: no se da propina sobre el
      // impuesto.
      var pct = Number((estado || {}).propina_pct || 0);
      var sugerida = pct > 0 ? Math.round(t.sub * pct / 100) : 0;
      var prop = propina === null ? sugerida : propina;

      h += '<div class="mt">' +
        '<div class="tk-tot"><span class="mut">Subtotal</span><span>' + money(t.sub) + '</span></div>' +
        '<div class="tk-tot"><span class="mut">Imp. consumo (8%)</span><span>' +
        money(t.iva) + '</span></div>' +
        '<div class="tk-propina">' +
        '<div class="tk-tot"><span class="mut">Propina <i>voluntaria</i></span>' +
        '<span>' + money(prop) + '</span></div>' +
        '<div class="tk-prop-btns">' +
        '<button class="btn btn-sm' + (prop === 0 ? ' on' : '') +
        '" data-act="cajaPropina" data-args="0">Sin propina</button>' +
        (pct > 0
          ? '<button class="btn btn-sm' + (prop === sugerida && prop > 0 ? ' on' : '') +
            '" data-act="cajaPropina" data-args="' + sugerida + '">' + pct + '%</button>'
          : '') +
        '<button class="btn btn-sm" data-act="cajaPropinaOtra">Otra…</button>' +
        '</div></div>' +
        '<div class="tk-tot big"><span>Total</span><span>' +
        money(round2(t.total + prop)) + '</span></div></div>' +
        '<button class="btn btn-g mt" style="width:100%;padding:11px;font-size:15px" ' +
        'data-act="cajaCobrar">💵 Cobrar ' + money(round2(t.total + prop)) + '</button>' +
        '<button class="btn btn-sm mt" style="width:100%" data-act="cajaVaciar">Vaciar ticket</button>';
    }
    return h + '</div></div>';
  }

  /**
   * Repinta SOLO el ticket, no la retícula de productos.
   *
   * Volver a pintar todo el punto de venta en cada toque haría parpadear la
   * pantalla y perdería la posición de desplazamiento justo cuando el cajero
   * esta armando el pedido delante del cliente.
   */
  function refrescarTicket() {
    var envoltorio = document.getElementById('tk-wrap');
    if (envoltorio) envoltorio.innerHTML = pintarTicket();
  }

  // ══════════════════════════════════════════════════════════════════
  //  COBRO
  // ══════════════════════════════════════════════════════════════════
  window.cajaCobrar = function () {
    if (!carrito.length) return toast('El ticket está vacío', 'warn');
    var t = totales();
    var metodos = estado.metodos_pago || [];

    var opciones = metodos.map(function (m) {
      return '<option value="' + m.id + '">' + esc(m.nombre) + '</option>';
    }).join('');

    // La propina se SUGIERE sobre el consumo, no sobre el total: no se da
    // propina sobre el impuesto. Y se sugiere, no se impone — la ley 1935 de
    // 2018 la hace voluntaria y obliga a informarla, por eso el botón «Sin
    // propina» está al lado y es igual de fácil de oprimir.
    // Lo que ya se eligio en el ticket manda. Volver a proponer el porcentaje
    // aqui sobreescribiria en silencio la decision que el cliente ya tomo.
    var pct = Number((estado || {}).propina_pct || 0);
    var sugerida = propina !== null
      ? propina
      : (pct > 0 ? Math.round(t.sub * pct / 100) : 0);

    modal('Cobrar ' + money(round2(t.total + sugerida)),
      '<div class="campo"><label for="pg-metodo">Medio de pago</label>' +
      '<select id="pg-metodo" data-act="cajaCambioMetodo">' + opciones + '</select></div>' +
      '<div class="campo"><label for="pg-propina">Propina (voluntaria)</label>' +
      '<div class="flex">' +
      '<input type="number" id="pg-propina" value="' + sugerida + '" min="0" step="500" ' +
      'data-act="cajaCalcularVuelto" style="flex:1">' +
      '<button type="button" class="btn btn-sm" data-act="cajaSinPropina">Sin propina</button>' +
      '</div>' +
      '<div class="sug">' +
      (pct > 0 ? 'Sugerida: ' + pct + '% sobre el consumo. ' : '') +
      'Se pregunta al cliente y va completa al personal; no es ingreso del ' +
      'restaurante ni causa impuesto.</div></div>' +
      '<div class="campo" id="pg-caja-recibido"><label for="pg-recibido">Efectivo recibido</label>' +
      '<input type="number" id="pg-recibido" value="' + Math.ceil((t.total + sugerida) / 1000) * 1000 +
      '" min="0" step="500" data-act="cajaCalcularVuelto"></div>' +
      '<div class="aviso i" id="pg-vuelto">Cambio: —</div>' +
      // Documento equivalente POS o factura electronica. Son dos documentos
      // distintos ante la DIAN, no un campo opcional: el POS no necesita
      // adquiriente y la factura EXIGE identificarlo. Escribir un nombre
      // suelto no servia para ninguno de los dos —y ademas tumbaba el cobro.
      '<div class="campo"><label>Documento</label>' +
      '<div class="flex">' +
      '<button type="button" class="btn btn-sm' + (adquiriente ? '' : ' on') +
      '" id="pg-tipo-pos" data-act="cajaDocPOS">🧾 Equivalente POS</button>' +
      '<button type="button" class="btn btn-sm' + (adquiriente ? ' on' : '') +
      '" id="pg-tipo-fe" data-act="cajaDocFactura">📄 Factura electrónica</button>' +
      '</div>' +
      '<div class="sug" id="pg-doc-sug">El equivalente POS no pide datos. ' +
      'La factura electrónica exige identificar al adquiriente.</div></div>' +
      '<div id="pg-adq"></div>',
      'Confirmar cobro', confirmarCobro);

    pintarAdquiriente();

    setTimeout(cajaCalcularVuelto, 30);
  };

  window.cajaCambioMetodo = function () {
    var m = (estado.metodos_pago || []).filter(function (x) {
      return String(x.id) === val('pg-metodo');
    })[0];
    var esEfectivo = m && Number(m.es_efectivo) === 1;
    document.getElementById('pg-caja-recibido').style.display = esEfectivo ? '' : 'none';
    document.getElementById('pg-vuelto').style.display = esEfectivo ? '' : 'none';
  };

  window.cajaSinPropina = function () {
    var c = document.getElementById('pg-propina');
    if (c) { c.value = 0; cajaCalcularVuelto(); }
  };

  /** Cuánto se cobra en total: el consumo, su impuesto y la propina. */
  function aCobrar() {
    var t = totales();
    return round2(t.total + Math.max(0, Number(val('pg-propina') || 0)));
  }
  function round2(n) { return Math.round(n * 100) / 100; }

  window.cajaCalcularVuelto = function () {
    var recibido = Number(val('pg-recibido') || 0);
    var caja = document.getElementById('pg-vuelto');
    if (!caja) return;
    // El vuelto se calcula sobre lo que el cliente paga DE VERDAD. Olvidar la
    // propina aquí haría que el cajero devolviera de más en cada cuenta.
    var cobrar = aCobrar();
    var vuelto = recibido - cobrar;
    var propina = Math.max(0, Number(val('pg-propina') || 0));
    caja.className = 'aviso ' + (vuelto < 0 ? 'e' : 'g');
    caja.innerHTML = (propina > 0
        ? '<div class="peq">A cobrar ' + money(cobrar) + ' · incluye ' +
          money(propina) + ' de propina</div>'
        : '') +
      (vuelto < 0
        ? '<b>Faltan ' + money(Math.abs(vuelto)) + '</b>'
        : '<b>Cambio: ' + money(vuelto) + '</b>');
    var ok = document.getElementById('modal-ok');
    if (ok && !enviando) ok.textContent = 'Cobrar ' + money(cobrar);
  };

  function confirmarCobro() {
    if (enviando) return;
    var t = totales();
    var propina = Math.max(0, Number(val('pg-propina') || 0));
    var cobrar = round2(t.total + propina);
    var metodoId = Number(val('pg-metodo')) || null;
    var m = (estado.metodos_pago || []).filter(function (x) { return x.id === metodoId; })[0];

    // Se compara contra lo que se cobra CON propina. Contra el total sin ella,
    // el cajero podía confirmar con efectivo insuficiente y quedar corto.
    if (m && Number(m.es_efectivo) === 1 && Number(val('pg-recibido') || 0) < cobrar) {
      return toast('El efectivo recibido no cubre el total', 'warn');
    }

    // Se valida ANTES de bloquear el boton: si falta un dato, el cajero
    // corrige y vuelve a oprimir sin que el boton haya quedado en «Procesando».
    // Es lo minimo para no gastar un viaje; la regla de verdad vive en el
    // backend, porque el mismo cliente se crea tambien desde el maestro y
    // desde una importacion.
    var adq = leerAdquiriente();
    if (adq) {
      if (!adq.numero_doc) return toast('Falta el número de documento del adquiriente.', 'warn');
      if (!adq.razon_social) return toast('Falta el nombre o razón social.', 'warn');
      if (!adq.email) return toast('El correo es obligatorio: la factura se entrega por ahí.', 'warn');
    }

    enviando = true;
    var btn = document.getElementById('modal-ok');
    btn.disabled = true; btn.textContent = 'Procesando…';

    // La clave de idempotencia se genera AQUÍ, antes de enviar, y se conserva
    // si hay que reintentar. Es lo que impide cobrar dos veces cuando la red
    // falla después de que el servidor ya grabó.
    var idem = 'v-' + Date.now() + '-' + Math.random().toString(36).slice(2, 10);

    // Si el ticket viene de una mesa se manda `comanda_id` y NO las líneas: el
    // servidor las toma de la comanda. Volver a digitarlas aquí abriría la
    // puerta a cobrar algo distinto de lo servido, y el que paga es el cliente.
    var cuerpo = {
      pagos: [{ metodo_id: metodoId, monto: cobrar }],
      propina: propina || 0,
      cliente: adq,
      idem_key: idem
    };
    if (comanda) {
      cuerpo.comanda_id = comanda.id;
    } else {
      cuerpo.items = carrito.map(function (l) {
        return { producto_id: l.producto_id, cantidad: l.cantidad };
      });
    }

    api('/api/caja/ventas', { method: 'POST', body: cuerpo }).then(function (r) {
      modalCerrar();
      var mesa = comanda && comanda.mesa;
      carrito = [];
      comanda = null;
      propina = null;      // el siguiente cliente decide la suya
      adquiriente = null;  // y el siguiente puede no querer factura
      toast('Venta ' + r.folio + ' por ' + money(r.total) +
            (mesa ? ' · mesa ' + mesa + ' liberada' : ''), 'ok');
      cajaAlAbrir();
    }).catch(errToast).then(function () {
      enviando = false;
      if (btn) { btn.disabled = false; btn.textContent = 'Confirmar cobro'; }
    });
  }

  // ══════════════════════════════════════════════════════════════════
  //  CIERRE Y ARQUEO
  // ══════════════════════════════════════════════════════════════════
  window.cajaCerrarTurno = function () {
    if (!estado || !estado.caja) return toast('No hay turno abierto', 'warn');
    modal('Cerrar turno y hacer arqueo',
      '<p class="mut peq mb">Cuente el efectivo del cajón e indique el total. El sistema ' +
      'registrará la diferencia contra lo esperado; no la corrige ni la oculta.</p>' +
      '<div class="campo"><label for="ar-contado">Efectivo contado</label>' +
      '<input type="number" id="ar-contado" min="0" step="500" placeholder="0"></div>' +
      '<div class="campo"><label for="ar-obs">Observación (opcional)</label>' +
      '<textarea id="ar-obs" rows="2" placeholder="Novedades del turno"></textarea></div>',
      'Cerrar turno', function () {
        var contado = val('ar-contado');
        if (contado === '') return toast('Indique el efectivo contado', 'warn');
        api('/api/caja/cerrar', {
          method: 'POST',
          body: { efectivo_contado: Number(contado), observacion: val('ar-obs') }
        }).then(function (r) {
          modalCerrar();
          mostrarArqueo(r.arqueo);
        }).catch(errToast);
      });
  };

  function mostrarArqueo(a) {
    var clase = a.estado_arqueo === 'cuadrada' ? 'g' : (a.estado_arqueo === 'faltante' ? 'e' : 'w');
    var etiqueta = { cuadrada: '✅ Caja cuadrada', faltante: '⚠️ Faltante', sobrante: 'ℹ️ Sobrante' }[a.estado_arqueo];
    modal('Arqueo del turno #' + a.caja_id,
      '<div class="aviso ' + clase + '"><b>' + etiqueta + '</b>' +
      (a.estado_arqueo !== 'cuadrada' ? ' · ' + money(Math.abs(a.diferencia)) : '') + '</div>' +
      '<table><tbody>' +
      fila('Base inicial', money(a.base_inicial)) +
      fila('Ventas en efectivo', money(a.efectivo_ventas)) +
      fila('<b>Efectivo esperado</b>', '<b>' + money(a.efectivo_esperado) + '</b>') +
      fila('Efectivo contado', money(a.efectivo_contado)) +
      fila('<b>Diferencia</b>', '<b>' + money(a.diferencia) + '</b>') +
      fila('Transacciones', String(a.num_ventas)) +
      fila('Total vendido', money(a.total_ventas)) +
      '</tbody></table>', null, null);
    carrito = [];
    setTimeout(cajaAlAbrir, 100);
  }

  function fila(k, v) {
    return '<tr><td>' + k + '</td><td class="num">' + v + '</td></tr>';
  }

  function kpiChip(titulo, valor, detalle) {
    return '<div class="kpi"><div class="k">' + esc(titulo) + '</div>' +
      '<div class="v" style="font-size:20px">' + esc(valor) + '</div>' +
      '<div class="d">' + esc(detalle) + '</div></div>';
  }
})();
