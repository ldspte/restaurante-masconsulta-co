/* ══════════════════════════════════════════════════════════════════════
   CAFETERÍA · Módulo PRODUCTOS
   Catálogo de venta y receta. La receta es lo que conecta cada producto con
   el inventario: define qué se descuenta al venderlo y cuánto cuesta hacerlo.
   Backend: /api/productos/*
   ══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var COLOR = '#6F4E37';
  var datos = null, cats = null, editando = null, receta = [];

  window.productosInyectar = function () {
    crearPagina('productos', '☕', 'Productos',
      'Catálogo de venta con precio, margen y receta de insumos.', COLOR);
    var acc = document.getElementById('acc-productos');
    if (acc && !acc.innerHTML) {
      acc.innerHTML = '<button class="btn btn-p" data-act="productosNuevo">+ Nuevo producto</button>' +
        '<button class="btn" data-act="productosAlAbrir">↻</button>';
    }
  };

  window.productosAlAbrir = function () {
    cargando('cont-productos');
    Promise.all([api('/api/productos'), api('/api/productos/catalogos')])
      .then(function (r) { datos = r[0]; cats = r[1]; pintar(); })
      .catch(function (e) {
        document.getElementById('cont-productos').innerHTML =
          '<div class="aviso e">' + esc(e.message) + '</div>';
      });
  };

  function pintar() {
    var k = datos.kpis;
    var h = '<div class="grid g3 mb">' +
      chip('Productos activos', String(k.total), 'En el catálogo', '') +
      chip('Margen promedio', k.margen_promedio + '%', 'Sobre el precio de venta',
           k.margen_promedio >= 50 ? 'ok' : 'warn') +
      chip('Sin receta', String(k.sin_receta),
           k.sin_receta ? 'No descuentan inventario' : 'Todos configurados',
           k.sin_receta ? 'bad' : 'ok') +
      '</div>';

    if (k.sin_receta) {
      h += '<div class="aviso w">Hay <b>' + k.sin_receta + ' producto(s) sin receta</b>. ' +
        'Al venderse no descontarán insumos y su costo se registrará en cero, lo que ' +
        'infla artificialmente la utilidad.</div>';
    }

    h += '<div class="card"><div class="tabla-wrap"><table><thead><tr>' +
      '<th>Código</th><th>Producto</th><th>Categoría</th><th class="num">Precio</th>' +
      '<th class="num">Costo</th><th class="num">Margen</th><th>Receta</th><th></th>' +
      '</tr></thead><tbody>';

    if (!datos.items.length) {
      h += '<tr><td colspan="8">' + vacio('☕', 'Aún no hay productos.') + '</td></tr>';
    }
    datos.items.forEach(function (p) {
      var clase = p.margen_pct == null ? 't-gris' : (p.margen_pct >= 60 ? 't-ok'
                  : (p.margen_pct >= 35 ? 't-warn' : 't-bad'));
      h += '<tr><td class="peq mut">' + esc(p.codigo) + '</td>' +
        '<td><b>' + (p.emoji || '') + ' ' + esc(p.nombre) + '</b></td>' +
        '<td><span class="tag" style="background:' + esc(p.color) + '22;color:' + esc(p.color) + '">' +
        esc(p.categoria) + '</span></td>' +
        '<td class="num">' + money(p.precio) + '</td>' +
        '<td class="num">' + money(p.costo) + '</td>' +
        '<td class="num"><span class="tag ' + clase + '">' +
        (p.margen_pct == null ? '—' : p.margen_pct + '%') + '</span></td>' +
        '<td>' + (p.items_receta ? p.items_receta + ' insumo(s)'
                  : '<span class="tag t-bad">Sin receta</span>') + '</td>' +
        '<td class="num">' +
        '<button class="btn btn-sm" data-act="productosEditar" data-args="' + arg(p.id) + '">✎</button> ' +
        '<button class="btn btn-sm" data-act="productosReceta" data-args="' + arg(p.id) + '">🧪</button> ' +
        '<button class="btn btn-sm" data-act="productosEliminar" data-args="' + arg(p.id) + '">🗑</button>' +
        '</td></tr>';
    });

    document.getElementById('cont-productos').innerHTML = h + '</tbody></table></div></div>';
  }

  // ── Alta y edición ────────────────────────────────────────────────
  window.productosNuevo = function () { abrirFormulario(null); };
  window.productosEditar = function (id) {
    abrirFormulario(datos.items.filter(function (p) { return String(p.id) === String(id); })[0]);
  };

  function abrirFormulario(p) {
    editando = p ? p.id : null;
    var opciones = cats.categorias.map(function (c) {
      return '<option value="' + c.id + '"' +
        (p && p.categoria_id === c.id ? ' selected' : '') + '>' + esc(c.nombre) + '</option>';
    }).join('');

    modal(p ? 'Editar producto' : 'Nuevo producto',
      '<div class="fila">' +
      campo('pr-nombre', 'Nombre', 'text', p ? p.nombre : '') +
      campo('pr-emoji', 'Ícono', 'text', p ? (p.emoji || '') : '☕') +
      '</div>' +
      '<div class="campo"><label for="pr-cat">Categoría</label>' +
      '<select id="pr-cat" data-act="productosCategoriaCambio">' + opciones +
      // Regla de diseño: ningún desplegable cerrado. La última opción crea.
      '<option value="__nueva">➕ Otra categoría…</option></select></div>' +
      '<div class="fila">' +
      campo('pr-precio', 'Precio de venta', 'number', p ? p.precio : '') +
      campo('pr-iva', 'IVA %', 'number', p ? p.iva_pct : 8) +
      '</div>',
      p ? 'Guardar cambios' : 'Crear', guardar);
  }

  window.productosCategoriaCambio = function () {
    if (val('pr-cat') !== '__nueva') return;
    var nombre = prompt('Nombre de la nueva categoría:');
    if (!nombre) { document.getElementById('pr-cat').selectedIndex = 0; return; }
    api('/api/productos/categorias', { method: 'POST', body: { nombre: nombre } })
      .then(function () { return api('/api/productos/catalogos'); })
      .then(function (r) {
        cats = r;
        var sel = document.getElementById('pr-cat');
        sel.innerHTML = cats.categorias.map(function (c) {
          return '<option value="' + c.id + '">' + esc(c.nombre) + '</option>';
        }).join('') + '<option value="__nueva">➕ Otra categoría…</option>';
        var nueva = cats.categorias.filter(function (c) {
          return c.nombre.toLowerCase() === nombre.toLowerCase();
        })[0];
        if (nueva) sel.value = nueva.id;
        toast('Categoría creada', 'ok');
      }).catch(errToast);
  };

  function guardar() {
    var cuerpo = {
      nombre: val('pr-nombre'),
      emoji: val('pr-emoji'),
      categoria_id: val('pr-cat') === '__nueva' ? null : Number(val('pr-cat')),
      precio: Number(val('pr-precio') || 0),
      iva_pct: Number(val('pr-iva') || 0)
    };
    if (!cuerpo.nombre) return toast('El nombre es obligatorio', 'warn');

    var p = editando
      ? api('/api/productos/' + editando, { method: 'PUT', body: cuerpo })
      : api('/api/productos', { method: 'POST', body: cuerpo });

    p.then(function () {
      modalCerrar();
      toast(editando ? 'Producto actualizado' : 'Producto creado', 'ok');
      productosAlAbrir();
    }).catch(errToast);
  }

  window.productosEliminar = function (id) {
    var p = datos.items.filter(function (x) { return String(x.id) === String(id); })[0];
    modalConfirmar('¿Desactivar «' + (p ? p.nombre : '') + '»? Dejará de aparecer en la caja, ' +
      'pero se conserva en las ventas ya registradas.', function () {
      api('/api/productos/' + id, { method: 'DELETE' })
        .then(function () { toast('Producto desactivado', 'ok'); productosAlAbrir(); })
        .catch(errToast);
    });
  };

  // ── Receta ────────────────────────────────────────────────────────
  window.productosReceta = function (id) {
    editando = id;
    api('/api/productos/' + id + '/receta').then(function (r) {
      receta = r.items.map(function (i) {
        return { insumo_id: i.insumo_id, cantidad: i.cantidad };
      });
      pintarReceta();
    }).catch(errToast);
  };

  function pintarReceta() {
    var p = datos.items.filter(function (x) { return String(x.id) === String(editando); })[0];
    var opciones = cats.insumos.map(function (i) {
      return '<option value="' + i.id + '">' + esc(i.nombre) + ' (' + esc(i.unidad) + ')</option>';
    }).join('');

    var costo = 0;
    var filas = receta.map(function (r, idx) {
      var ins = cats.insumos.filter(function (i) { return i.id === r.insumo_id; })[0] || {};
      var sub = (Number(r.cantidad) || 0) * Number(ins.costo_prom || 0);
      costo += sub;
      return '<tr><td>' + esc(ins.nombre || '?') + '</td>' +
        '<td class="num"><input type="number" step="0.001" value="' + r.cantidad +
        '" data-act="recetaCantidad" data-args="' + idx + '" style="width:92px;text-align:right"></td>' +
        '<td class="peq mut">' + esc(ins.unidad || '') + '</td>' +
        '<td class="num">' + money(sub) + '</td>' +
        '<td class="num"><button class="btn btn-sm" data-act="recetaQuitar" data-args="' +
        idx + '">✕</button></td></tr>';
    }).join('');

    var precio = p ? Number(p.precio) : 0;
    var margen = precio ? ((precio - costo) / precio * 100).toFixed(1) : null;

    modal('🧪 Receta · ' + (p ? p.nombre : ''),
      '<p class="mut peq mb">Cantidad de cada insumo por UNA unidad del producto. ' +
      'Es lo que el sistema descuenta del inventario en cada venta.</p>' +
      '<div class="flex mb"><select id="rc-insumo" style="flex:1">' + opciones + '</select>' +
      '<input type="number" id="rc-cant" placeholder="Cantidad" step="0.001" style="width:110px">' +
      '<button class="btn btn-p" data-act="recetaAgregar">Agregar</button></div>' +
      '<div class="tabla-wrap"><table><thead><tr><th>Insumo</th><th class="num">Cantidad</th>' +
      '<th>Unidad</th><th class="num">Costo</th><th></th></tr></thead><tbody>' +
      (filas || '<tr><td colspan="5" class="mut peq" style="padding:16px;text-align:center">' +
       'Sin insumos. El producto no descontará inventario.</td></tr>') +
      '</tbody></table></div>' +
      '<div class="aviso ' + (margen == null ? 'i' : (margen >= 50 ? 'g' : 'w')) + ' mt">' +
      'Costo unitario <b>' + money(costo) + '</b> · Precio <b>' + money(precio) + '</b> · ' +
      'Margen <b>' + (margen == null ? '—' : margen + '%') + '</b></div>',
      'Guardar receta', guardarReceta);
  }

  window.recetaAgregar = function () {
    var id = Number(val('rc-insumo'));
    var cant = Number(val('rc-cant') || 0);
    if (!id || cant <= 0) return toast('Elija el insumo e indique una cantidad', 'warn');
    if (receta.some(function (r) { return r.insumo_id === id; })) {
      return toast('Ese insumo ya está en la receta', 'warn');
    }
    receta.push({ insumo_id: id, cantidad: cant });
    pintarReceta();
  };

  window.recetaCantidad = function (idx, ev) {
    var v = Number(ev.target.value || 0);
    if (receta[idx]) receta[idx].cantidad = v;
    pintarReceta();
  };

  window.recetaQuitar = function (idx) { receta.splice(Number(idx), 1); pintarReceta(); };

  function guardarReceta() {
    api('/api/productos/' + editando + '/receta', { method: 'PUT', body: { items: receta } })
      .then(function () { modalCerrar(); toast('Receta guardada', 'ok'); productosAlAbrir(); })
      .catch(errToast);
  }

  function campo(id, etiqueta, tipo, valor) {
    return '<div class="campo"><label for="' + id + '">' + esc(etiqueta) + '</label>' +
      '<input type="' + tipo + '" id="' + id + '" value="' + esc(valor == null ? '' : valor) + '"></div>';
  }

  function chip(t, v, d, c) {
    return '<div class="kpi ' + (c || '') + '"><div class="k">' + esc(t) + '</div>' +
      '<div class="v">' + esc(v) + '</div><div class="d">' + esc(d) + '</div></div>';
  }
})();
