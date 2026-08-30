/* ══════════════════════════════════════════════════════════════════════
   RESTAURANTE · Módulo COMANDAS

   La comanda es el pedido de una mesa mientras está viva: se abre, se le van
   agregando platos y se envía a las estaciones. No es una venta todavía —eso
   ocurre en Caja, al cobrar—, y separarlas importa: una mesa puede pedir tres
   veces antes de pagar una sola cuenta.

   PRIMERO SE CUENTAN LAS PERSONAS
   -------------------------------
   Antes de tomar ningún plato hay que declarar cuántos se sentaron. No es
   burocracia: sin ese número no existe la lista de asientos contra la cual
   verificar, y verificar es justamente lo que evita el error más caro del
   salón —que alguien se quede sin pedir y nadie lo note hasta que los demás
   ya están comiendo.

   TRES ESTADOS POR ASIENTO, NO DOS
   --------------------------------
   Un asiento sin platos puede significar dos cosas opuestas:

     · «todavía no le he preguntado», o
     · «ya le pregunté y no quiere nada».

   Para el mesero son situaciones contrarias: una exige volver a la mesa, la
   otra no. Mostrarlas iguales —en blanco— hace inútil la lista. Por eso el
   asiento tiene estado propio: **pidió**, **no consume** o **pendiente**.

   Backend: /api/comandas/*
   ══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var COLOR = '#7C3AED';
  var abierta = null, catalogo = [], reloj = null;

  var ESTADOS = {
    abierta: 'Abierta', en_cocina: 'En cocina', preparando: 'Preparando',
    listo: 'Listo', servida: 'Servida', cerrada: 'Cerrada'
  };

  window.comandasInyectar = function () {
    crearPagina('comandas', '📝', 'Comandas',
      'Los pedidos que están en curso. Se abren desde el salón y se cobran ' +
      'en caja.', COLOR);
    document.getElementById('acc-comandas').innerHTML =
      '<button class="btn" data-act="cmdHistorico">🗄 Histórico</button>' +
      '<button class="btn btn-p" data-act="cmdRefrescar">↻ Actualizar</button>';
  };

  window.comandasAlAbrir = function () {
    cargar();
    clearInterval(reloj);
    reloj = setInterval(function () {
      var p = document.getElementById('page-comandas');
      if (p && p.classList.contains('on')) cargar();
    }, 20000);
  };

  window.cmdRefrescar = function () { cargar(); };

  window.cmdIrACaja = function () { nav('caja'); };

  // ══════════════════════════════════════════════════════════════════
  //  HISTÓRICO
  //
  //  Lo cobrado sale del tablero —si no, en una semana el mesero no
  //  encuentra sus mesas entre cien cerradas— pero NO se pierde: queda en la
  //  base y se consulta aquí. El listado se pide al servidor con
  //  `?estado=cerrada`; no se guarda copia en el navegador, porque una copia
  //  que se desactualiza sola es peor que no tenerla.
  // ══════════════════════════════════════════════════════════════════
  window.cmdHistorico = function () {
    modal('🗄 Comandas cerradas',
          '<div id="hist-cuerpo"><p class="nota">Consultando…</p></div>', '', null);
    api('/api/comandas?estado=cerrada')
      .then(function (r) {
        var l = r.items || [];
        var cuerpo = document.getElementById('hist-cuerpo');
        if (!cuerpo) return;
        if (!l.length) {
          cuerpo.innerHTML = '<p class="nota">Todavía no se ha cerrado ninguna ' +
            'comanda. Una comanda se cierra cuando la caja la cobra.</p>';
          return;
        }
        var suma = l.reduce(function (a, o) { return a + Number(o.subtotal || 0); }, 0);
        var h = '<p class="nota">' + l.length +
          (l.length === 1 ? ' comanda cerrada · ' : ' comandas cerradas · ') +
          money(suma) + ' cobrados.</p>' +
          '<div class="tabla-wrap"><table><thead><tr><th>Comanda</th><th>Mesa</th>' +
          '<th>Mesero</th><th>Cerrada</th><th class="num">Valor</th></tr></thead><tbody>';
        l.forEach(function (o) {
          h += '<tr><td>' + esc(o.numero || ('#' + o.id)) + '</td>' +
            '<td>' + esc(o.mesa || '—') + '</td>' +
            '<td>' + esc(o.mesero || '—') + '</td>' +
            '<td>' + (o.cierre_ts ? fecha(o.cierre_ts, true)
                                  : (o.apertura_ts ? fecha(o.apertura_ts, true) : '—')) + '</td>' +
            '<td class="num">' + money(o.subtotal) + '</td></tr>';
        });
        cuerpo.innerHTML = h + '</tbody></table></div>';
      })
      .catch(function (e) {
        var cuerpo = document.getElementById('hist-cuerpo');
        if (cuerpo) cuerpo.innerHTML = '<div class="aviso e">' + esc(e.message) + '</div>';
      });
  };

  function cargar() {
    Promise.all([api('/api/comandas'), api('/api/productos')])
      .then(function (r) {
        catalogo = r[1].items || [];
        var abiertas = (r[0].items || []).filter(function (c) {
          return c.estado !== 'cerrada';
        });
        if (!abiertas.length) { pintar([]); return; }
        // El detalle de cada mesa, en paralelo. `GET /api/comandas` devuelve
        // solo un resumen —lo consulta el salón cada veinte segundos y traer
        // todos los renglones sería desperdicio—, pero aquí sí hacen falta
        // los platos y el estado de cada asiento.
        return Promise.all(abiertas.map(function (c) {
          return api('/api/comandas/' + c.id)
            .then(function (d) {
              return { c: d.comanda || c, items: d.items || [],
                       puestos: d.puestos || [], tot: d.totales || {} };
            })
            .catch(function () { return { c: c, items: null, puestos: [], tot: {} }; });
        })).then(pintar);
      })
      .catch(errToast);
  }

  // ══════════════════════════════════════════════════════════════════
  //  PINTADO
  // ══════════════════════════════════════════════════════════════════
  function pintar(lista) {
    var c = document.getElementById('cont-comandas');
    if (!lista.length) {
      c.innerHTML = vacio('📝', 'No hay comandas abiertas. Se abren desde el Salón, ' +
        'al sentar una mesa.');
      return;
    }

    // El tablero se parte en dos.
    //
    // «Servida» NO quiere decir terminada: quiere decir que la comida esta en
    // la mesa y falta cobrarla. Mandarlas al historico sin mas escondia dinero
    // servido y no facturado — al revisar habia $107.500 en tres mesas. Asi
    // que bajan, pero a una franja propia que dice cuanto se debe, no al
    // olvido. Al historico solo va lo CERRADO, que es lo ya cobrado.
    var enCurso = lista.filter(function (x) { return x.c.estado !== 'servida'; });
    var porCobrar = lista.filter(function (x) { return x.c.estado === 'servida'; });

    var h = '';
    if (porCobrar.length) {
      var deuda = porCobrar.reduce(function (a, x) {
        return a + Number((x.tot && x.tot.total != null) ? x.tot.total : (x.c.subtotal || 0));
      }, 0);
      h += '<div class="aviso w" style="display:flex;align-items:center;gap:12px">' +
        '<b>🧾 ' + porCobrar.length +
        (porCobrar.length === 1 ? ' mesa servida sin cobrar' : ' mesas servidas sin cobrar') +
        ' · ' + money(deuda) + '</b>' +
        '<span class="sp" style="flex:1"></span>' +
        '<button class="btn btn-sm btn-p" data-act="cmdIrACaja">Ir a Caja</button></div>';
    }

    h += seccion('En curso', enCurso) + seccion('Servidas · por cobrar', porCobrar);
    c.innerHTML = h;
  }

  /** Un bloque del tablero. Se saca a funcion para que «en curso» y «por
   *  cobrar» se pinten exactamente igual y no se desincronicen al cambiar una. */
  function seccion(titulo, lista) {
    if (!lista.length) return '';
    var h = '<div class="sec-tit">' + esc(titulo) +
      '<span class="tag t-info">' + lista.length + '</span></div>' +
      '<div class="grid g3 mb">';
    lista.forEach(function (x) {
      var o = x.c, items = x.items, pu = x.puestos, t = x.tot;
      var min = o.apertura_ts
        ? Math.round((Date.now() - new Date(o.apertura_ts)) / 60000) : null;
      var total = t.total != null ? t.total : o.subtotal;
      var pendientes = pu.filter(function (p) { return p.estado === 'pendiente'; }).length;

      h += '<div class="card comanda"><div class="card-h" style="border-left:4px solid ' +
        COLOR + '">' +
        '<b>' + esc(o.mesa || ('Comanda ' + o.id)) + '</b>' +
        '<div class="sp"></div>' +
        '<span class="pill ' + pillEstado(o.estado) + '">' +
        esc(ESTADOS[o.estado] || o.estado) + '</span>' +
        '</div><div class="card-b">' +
        '<div class="sug">' + esc(o.mesero || '') +
        (min != null ? ' · ' + min + ' min' : '') +
        (o.numero ? ' · ' + esc(o.numero) : '') + '</div>';

      if (o.notas) {
        // «Celiaco» o «alérgico al maní» no puede quedar en letra pequeña.
        h += '<div class="comanda-nota">⚠️ ' + esc(o.notas) + '</div>';
      }

      // ── Sin comensales declarados no se puede pedir ────────────────
      if (!o.personas) {
        h += '<div class="pide-personas">' +
          '<label for="pe-' + o.id + '">¿Cuántas personas se sentaron?</label>' +
          '<div class="pp-fila">' +
          '<input type="number" id="pe-' + o.id + '" min="1" max="40" value="2">' +
          '<button class="btn btn-p" data-act="cmdPersonas" data-id="' + o.id +
          '">Confirmar</button></div>' +
          '<div class="sug">Se necesita para llevar la cuenta de quién ya pidió ' +
          'y quién no.</div></div>' +
          '</div></div>';
        return;
      }

      h += barraAsientos(o, pu, pendientes) +
        renderPuestos(o, items, pu) +
        '<div class="comanda-total"><span>Total' +
        (t.impuestos ? ' <small>(imp. consumo ' + money(t.impuestos) + ')</small>' : '') +
        '</span><b>' + money(total) + '</b></div>' +
        '<div class="btns" style="margin-top:10px">' +
        '<button class="btn btn-sm" data-act="cmdAgregar" data-id="' + o.id +
        '" data-pers="' + o.personas + '">＋ Plato</button>' +
        (tieneSinEnviar(items, o)
          ? '<button class="btn btn-sm btn-a" data-act="cmdEnviar" data-id="' + o.id +
            '">🔥 Enviar a cocina</button>'
          : '') +
        // Un mesero no lleva los platos de uno en uno: cuando la tanda sale
        // junta, la marca junta. Sin esto tendria que dar seis toques por
        // mesa, y lo que se hace incomodo se deja de hacer.
        (listosDe(items)
          ? '<button class="btn btn-sm btn-g" data-act="cmdEntregarTodo" data-id="' +
            o.id + '">🛎 Entregar lo listo (' + listosDe(items) + ')</button>'
          : '') +
        '</div></div></div>';
    });
    return h + '</div>';
  }

  /** Resumen de atención de la mesa. Es lo primero que mira el mesero al
   *  pasar: le dice si le falta alguien sin tener que leer la lista. */
  function barraAsientos(o, pu, pendientes) {
    var atendidos = pu.length - pendientes;
    return '<div class="asientos-barra' + (pendientes ? ' falta' : '') + '">' +
      '<span class="ab-txt">' +
      (pendientes
        ? '👋 Faltan <b>' + pendientes + '</b> por pedir de ' + o.personas
        : '✅ Los ' + o.personas + ' asientos están atendidos') +
      '</span>' +
      '<button class="btn btn-sm" data-act="cmdCambiarPersonas" data-id="' + o.id +
      '" data-p="' + o.personas + '">' + o.personas + ' pers. ✎</button>' +
      '</div>';
  }

  /** Se recorren TODOS los asientos, no solo los que tienen platos: un
   *  asiento ausente de la lista sería indistinguible de uno sin atender. */
  function renderPuestos(o, items, pu) {
    if (items === null) {
      return '<p class="nota">No se pudo cargar el detalle de esta mesa.</p>';
    }
    var porPuesto = {};
    items.forEach(function (i) {
      var p = Number(i.puesto || 0);
      (porPuesto[p] = porPuesto[p] || []).push(i);
    });

    var h = '';

    // Lo de la mesa va primero: es de todos.
    if ((porPuesto[0] || []).length) {
      h += cabecera(0, 'De la mesa', subtotal(porPuesto[0]), '') + lineas(porPuesto[0]);
    }

    pu.forEach(function (p) {
      var mios = porPuesto[p.puesto] || [];
      h += cabecera(p.puesto, p.nombre || ('Asiento ' + p.puesto),
                    p.valor, p.estado);
      if (mios.length) {
        h += lineas(mios);
      } else if (p.estado === 'sin_consumo') {
        h += '<div class="puesto-vacio sin">No quiere nada · ya se le preguntó' +
          '<button class="btn btn-sm" data-act="cmdPuesto" data-id="' + o.id +
          '" data-p="' + p.puesto + '" data-s="0">Deshacer</button></div>';
      } else {
        h += '<div class="puesto-vacio">Sin pedir todavía' +
          '<button class="btn btn-sm" data-act="cmdPuesto" data-id="' + o.id +
          '" data-p="' + p.puesto + '" data-s="1">No quiere nada</button></div>';
      }
    });
    return h;
  }

  function cabecera(n, etiqueta, valor, estado) {
    var clase = n === 0 ? ' mesa'
      : estado === 'pendiente' ? ' pendiente'
      : estado === 'sin_consumo' ? ' sin' : '';
    return '<div class="puesto-cab">' +
      '<span class="puesto-num' + clase + '">' + (n === 0 ? '·' : n) + '</span>' +
      esc(etiqueta) +
      '<span class="sp-linea"></span>' +
      '<span class="puesto-sub">' + (valor ? money(valor) : '') + '</span>' +
      '</div>';
  }

  function subtotal(g) {
    return g.reduce(function (a, i) {
      return a + Number(i.cantidad || 0) * Number(i.precio_unit || 0);
    }, 0);
  }

  function lineas(lista) {
    var h = '<ul class="lista-comanda">';
    lista.forEach(function (i) {
      var est = i.entregado_ts ? 'entregado'
        : i.listo_ts ? 'listo'
        : i.enviado_ts ? 'en cocina' : 'sin enviar';
      h += '<li><span class="cant">' + numero(i.cantidad, 0) + '×</span>' +
        '<span class="nom">' + esc(i.nombre) +
        (i.notas ? '<em> · ' + esc(i.notas) + '</em>' : '') +
        (i.estacion ? '<span class="est-punto" style="background:' +
          esc(i.estacion_color || '#94a3b8') + '" title="' + esc(i.estacion) +
          '"></span>' : '') +
        '</span>' +
        // El plato listo NO se queda mirando: aqui es donde el mesero cierra
        // el circulo. Sin este boton la linea se queda en «listo» para
        // siempre y la comanda nunca pasa a «servida», asi que la caja no
        // sabe que ya puede cobrar.
        (est === 'listo'
          ? '<button class="btn btn-sm btn-g entregar" data-act="cmdEntregar" ' +
            'data-id="' + i.id + '" title="El mesero ya lo llevo a la mesa">' +
            '🛎 Entregar</button>'
          : '<span class="est ' + pillItem(est) + '">' + est + '</span>') +
        '<span class="val">' +
        money(Number(i.cantidad || 0) * Number(i.precio_unit || 0)) + '</span></li>';
    });
    return h + '</ul>';
  }

  /** Cuantas lineas salieron de cocina y siguen esperando al mesero. */
  function listosDe(items) {
    if (items === null) return 0;
    return items.filter(function (i) {
      return i.listo_ts && !i.entregado_ts;
    }).length;
  }

  function tieneSinEnviar(items, o) {
    if (items === null) return (o.sin_enviar || 0) > 0;
    return items.some(function (i) { return !i.enviado_ts; });
  }
  function pillEstado(e) {
    return ({ abierta: 'info', en_cocina: 'warn', preparando: 'warn',
              listo: 'ok', servida: 'ok', cerrada: '' })[e] || 'info';
  }
  function pillItem(e) {
    return ({ 'sin enviar': 'info', 'en cocina': 'warn',
              listo: 'ok', entregado: 'ok' })[e] || '';
  }

  // ══════════════════════════════════════════════════════════════════
  //  ACCIONES
  // ══════════════════════════════════════════════════════════════════
  window.cmdPersonas = function () {
    var id = this.getAttribute('data-id');
    guardarPersonas(id, parseInt(val('pe-' + id) || '0', 10));
  };

  window.cmdCambiarPersonas = function () {
    var id = this.getAttribute('data-id');
    var actual = this.getAttribute('data-p');
    modal('¿Cuántas personas hay en la mesa?',
      '<div class="campo"><label for="cp-n">Comensales</label>' +
      '<input type="number" id="cp-n" min="1" max="40" value="' + actual + '"></div>' +
      '<p class="nota">Si llegó alguien más, súbalo y aparecerá su asiento. ' +
      'No se puede bajar por debajo de un asiento que ya pidió: esos platos ' +
      'quedarían sin dueño.</p>',
      'Guardar', function () {
        guardarPersonas(id, parseInt(val('cp-n') || '0', 10));
      });
  };

  function guardarPersonas(id, n) {
    if (!(n > 0)) { toast('Indique cuántas personas hay en la mesa.', 'warn'); return; }
    api('/api/comandas/' + id + '/personas', { method: 'PUT', body: { personas: n } })
      .then(function (r) { modalCerrar(); toast(r.mensaje, 'ok'); cargar(); })
      .catch(errToast);
  }

  window.cmdPuesto = function () {
    var id = this.getAttribute('data-id');
    api('/api/comandas/' + id + '/puestos/' + this.getAttribute('data-p'), {
      method: 'PUT', body: { sin_consumo: this.getAttribute('data-s') === '1' }
    }).then(function (r) { toast(r.mensaje, 'ok'); cargar(); }).catch(errToast);
  };

  window.cmdAgregar = function () {
    abierta = this.getAttribute('data-id');
    var personas = Number(this.getAttribute('data-pers') || 0);
    var agregados = [];      // lo que se lleva pedido SIN cerrar la ventana

    var ops = catalogo.filter(function (p) { return p.activo; })
      .sort(function (a, b) { return a.nombre.localeCompare(b.nombre); })
      .map(function (p) {
        return '<option value="' + p.id + '">' + esc(p.nombre) + ' · ' +
          money(p.precio) + '</option>';
      }).join('');

    var asientos = '';
    for (var a = 1; a <= (personas || 8); a++) {
      asientos += '<option value="' + a + '"' + (a === 1 ? ' selected' : '') +
        '>Asiento ' + a + '</option>';
    }
    asientos += '<option value="0">De la mesa · para compartir</option>';

    modal('Agregar al pedido',
      '<div class="campo"><label for="cm-a">¿Para qué asiento?</label>' +
      '<select id="cm-a">' + asientos + '</select></div>' +
      '<div class="campo"><label for="cm-p">Plato</label>' +
      '<select id="cm-p">' + ops + '</select></div>' +
      '<div class="fila"><div class="campo"><label for="cm-c">Cantidad</label>' +
      '<input type="number" id="cm-c" min="1" step="1" value="1"></div>' +
      '<div class="campo" style="flex:2"><label for="cm-n">Nota para la cocina</label>' +
      '<input type="text" id="cm-n" placeholder="Sin cebolla, término medio…"></div></div>' +
      '<p class="nota">El asiento viaja con el plato hasta la pantalla de la cocina: ' +
      'cuando salga, el mesero sabe a quién se lo entrega sin preguntar en voz alta. ' +
      'La nota también.</p>' +
      '<div id="cm-estado"></div>',
      'Agregar', function () {
        var cant = parseFloat(val('cm-c') || '1');
        if (!(cant > 0)) { toast('La cantidad debe ser mayor que cero.', 'warn'); return; }
        var selP = document.getElementById('cm-p');
        var selA = document.getElementById('cm-a');
        var nombre = selP.options[selP.selectedIndex].text.split(' · ')[0];
        var puesto = parseInt(selA.value, 10);

        api('/api/comandas/' + abierta + '/items', {
          method: 'POST',
          body: {
            items: [{
              producto_id: parseInt(selP.value, 10),
              cantidad: cant,
              puesto: puesto,
              notas: val('cm-n')
            }]
          }
        }).then(function () {
          // La ventana NO se cierra. Una mesa se toma de corrido: una misma
          // persona pide varias cosas y hay que dar la vuelta a todos los
          // asientos. Cerrar en cada plato obligaba a volver a abrir, volver a
          // elegir el asiento y volver a buscar en la lista — y es en esa
          // fricción donde el mesero termina anotando en papel.
          //
          // Cada plato queda guardado apenas se agrega, así que cerrar en
          // cualquier momento no pierde nada.
          agregados.push({ n: cant, nombre: nombre, puesto: puesto });
          document.getElementById('cm-c').value = '1';
          document.getElementById('cm-n').value = '';
          selP.selectedIndex = 0;
          selP.focus();
          toast(cant + '× ' + nombre + ' agregado', 'ok');
          pintarEstado();
          cargar();          // el tablero de atrás se actualiza solo
        }).catch(errToast);
      });

    // ── Lo agregado en esta sesión y a quién le falta pedir ──────────
    function pintarEstado() {
      var caja = document.getElementById('cm-estado');
      if (!caja) return;

      var h = '';
      if (agregados.length) {
        h += '<div class="aviso g"><b>Agregado en esta mesa</b><br>' +
          agregados.map(function (x) {
            return x.n + '× ' + esc(x.nombre) +
              (x.puesto > 0 ? ' · asiento ' + x.puesto : ' · de la mesa');
          }).join('<br>') + '</div>';
      }
      caja.innerHTML = h + '<div id="cm-faltan"></div>';

      // Quién falta se pregunta al servidor: es la misma verdad que ve el
      // resto del sistema, no una cuenta paralela que se desincroniza.
      api('/api/comandas/' + abierta).then(function (d) {
        var faltan = (d.puestos || []).filter(function (p) {
          return p.estado === 'pendiente';
        });
        var c = document.getElementById('cm-faltan');
        if (!c) return;
        c.innerHTML = faltan.length
          ? '<div class="aviso w">Falta pedir: ' +
            faltan.map(function (p) { return 'asiento ' + p.puesto; }).join(', ') +
            '. Si alguno no quiere nada, márquelo en la mesa para que no quede ' +
            'como olvidado.</div>'
          : '<div class="aviso g">Todos los asientos están atendidos. ' +
            'Puede cerrar y enviar a cocina.</div>';
      }).catch(function () { /* el aviso es una ayuda, no bloquea el pedido */ });
    }

    pintarEstado();
  };

  window.cmdEnviar = function () {
    api('/api/comandas/' + this.getAttribute('data-id') + '/enviar', { method: 'POST' })
      .then(function (r) {
        toast(r.mensaje || 'Pedido enviado a la cocina', 'ok');
        cargar();
      }).catch(errToast);
  };

  // ══════════════════════════════════════════════════════════════════
  //  ENTREGA — el mesero cierra el circulo
  //
  //  Cocina marca «listo»; el mesero marca «entregado». Que sean dos
  //  personas distintas no es burocracia: es lo unico que permite medir
  //  cuanto tarda un plato listo en llegar a la mesa, que es justo donde
  //  se pierde la temperatura. El backend lo exige por rol.
  //
  //  Sin confirmacion, igual que en cocina: en servicio, un modal por
  //  plato es inoperante.
  // ══════════════════════════════════════════════════════════════════
  function marcarEntregado(itemId) {
    return api('/api/cocina/items/' + itemId + '/estado',
               { method: 'POST', body: { estado: 'entregado' } });
  }

  window.cmdEntregar = function () {
    marcarEntregado(this.getAttribute('data-id'))
      .then(function () { toast('Plato entregado', 'ok'); cargar(); })
      .catch(errToast);
  };

  window.cmdEntregarTodo = function () {
    var id = this.getAttribute('data-id');
    api('/api/comandas/' + id)
      .then(function (d) {
        var pendientes = (d.items || []).filter(function (i) {
          return i.listo_ts && !i.entregado_ts;
        });
        if (!pendientes.length) {
          toast('No hay platos listos por entregar.', 'warn');
          cargar();
          return;
        }
        // Se marcan de uno en uno contra el mismo endpoint que valida la
        // transicion. Inventar una ruta «entregar todo» duplicaria esa
        // validacion en dos sitios, y el dia que cambie solo se corrige uno.
        return Promise.all(pendientes.map(function (i) {
          return marcarEntregado(i.id).then(
            function () { return true; },
            function () { return false; }
          );
        })).then(function (r) {
          var ok = r.filter(Boolean).length;
          if (ok === r.length) {
            toast(ok + (ok === 1 ? ' plato entregado' : ' platos entregados'), 'ok');
          } else {
            // Se dice el numero exacto: «algo fallo» obliga a contar a mano.
            toast('Se entregaron ' + ok + ' de ' + r.length +
                  '. Revise los que quedaron marcados como listos.', 'warn');
          }
          cargar();
        });
      })
      .catch(errToast);
  };
})();
