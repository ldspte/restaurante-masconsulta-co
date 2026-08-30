/* ══════════════════════════════════════════════════════════════════════
   RESTAURANTE · ANEXOS  ·  componente compartido

   No es una pantalla: es una ventana que cualquier módulo abre sobre una
   ficha suya. Se usa igual desde un estándar del SG-SST, un período de
   nómina o una orden de compra:

       anexosAbrir('sst_estandar', 12, 'Estándar 1.1.1');

   Está en un archivo aparte y no dentro de SG-SST porque el problema —«a
   esta ficha le falta el soporte»— es el mismo en seis módulos. Copiarlo
   seis veces garantizaría que las validaciones se desincronizaran.

   EL CONTADOR EN LA TABLA
   ----------------------
   `anexosContar(entidad)` trae de una sola llamada cuántos anexos tiene cada
   ficha. Una tabla de treinta estándares no puede hacer treinta peticiones
   para pintar treinta clips.

   Backend: /api/anexos/*
   ══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  var ctx = { entidad: null, id: null, titulo: '', alCerrar: null };

  var ICONO = {
    pdf: '📕', png: '🖼️', jpg: '🖼️', jpeg: '🖼️', webp: '🖼️',
    xlsx: '📊', xls: '📊', docx: '📄', doc: '📄', csv: '📈', txt: '📃', zip: '🗜️'
  };

  function extension(n) {
    var p = String(n || '').split('.');
    return p.length > 1 ? p.pop().toLowerCase() : '';
  }

  /**
   * Abre la ventana de anexos de una ficha.
   * @param {string} entidad  clave de la lista blanca del backend
   * @param {number} id       identificador de la ficha
   * @param {string} titulo   qué se está anexando, para que se vea en la ventana
   * @param {function} alCerrar  se llama al cerrar si hubo cambios
   */
  window.anexosAbrir = function (entidad, id, titulo, alCerrar) {
    ctx = { entidad: entidad, id: id, titulo: titulo || '', alCerrar: alCerrar || null,
            hubo: false };
    modal('📎 Anexos', '<div id="ax-cuerpo" class="ax-cargando">Cargando…</div>');
    pintar();
  };

  /** Contadores de todas las fichas de una entidad, en una sola llamada. */
  window.anexosContar = function (entidad) {
    return api('/api/anexos/resumen/' + encodeURIComponent(entidad))
      .then(function (d) { return d.conteo || {}; })
      .catch(function () { return {}; });
  };

  /** Botón de clip listo para pegar en una celda de tabla. */
  window.anexosBoton = function (entidad, id, titulo, n) {
    n = Number(n || 0);
    return '<button class="clip' + (n ? ' con' : '') + '" data-act="anexosDesde" ' +
      'data-e="' + esc(entidad) + '" data-i="' + id + '" data-t="' + esc(titulo) + '" ' +
      'title="' + (n ? n + ' anexo(s)' : 'Sin soportes') + '">📎' +
      (n ? '<span>' + n + '</span>' : '') + '</button>';
  };

  window.anexosDesde = function () {
    anexosAbrir(this.getAttribute('data-e'), this.getAttribute('data-i'),
                this.getAttribute('data-t'), window.anexosAlCerrar || null);
  };

  // ══════════════════════════════════════════════════════════════════
  function pintar() {
    api('/api/anexos/' + ctx.entidad + '/' + ctx.id).then(function (d) {
      var c = document.getElementById('ax-cuerpo');
      if (!c) return;
      var items = d.items || [];

      var h = '<p class="ax-ficha">' + esc(ctx.titulo) + '</p>';

      h += '<div class="ax-zona">' +
        '<input type="file" id="ax-file" data-act="anexosElegido" ' +
        'accept=".pdf,.png,.jpg,.jpeg,.webp,.xlsx,.xls,.docx,.doc,.csv,.txt,.zip">' +
        '<div class="campo"><label for="ax-desc">¿Qué es este documento?</label>' +
        '<input type="text" id="ax-desc" placeholder="Acta 12 · listado de asistencia"></div>' +
        '<button class="btn btn-p ancho" data-act="anexosSubir" id="ax-btn">' +
        'Adjuntar</button>' +
        '<div id="ax-msg" class="form-msg"></div>' +
        '</div>';

      if (!items.length) {
        h += '<p class="ax-vacio">Todavía no hay soportes.<br>' +
          '<span>Marcar «cumple» sin adjuntar el documento es una afirmación; ' +
          'el inspector pide el papel.</span></p>';
      } else {
        h += '<ul class="ax-lista">';
        items.forEach(function (a) {
          h += '<li>' +
            '<span class="ax-ico">' + (ICONO[extension(a.nombre)] || '📎') + '</span>' +
            '<div class="ax-datos">' +
            '<b>' + esc(a.nombre) + '</b>' +
            (a.descripcion ? '<div class="ax-desc">' + esc(a.descripcion) + '</div>' : '') +
            '<div class="ax-meta">' + esc(a.tamano_humano) + ' · ' +
            esc(a.subido_por || '') + ' · ' + fecha(a.subido_en, true) + '</div>' +
            '</div>' +
            '<button class="btn btn-sm" data-act="anexosBajar" data-id="' + a.id +
            '" data-n="' + esc(a.nombre) + '">Descargar</button>' +
            '<button class="btn btn-sm btn-d" data-act="anexosBorrar" data-id="' + a.id +
            '" data-n="' + esc(a.nombre) + '">✕</button>' +
            '</li>';
        });
        h += '</ul>';
        h += '<p class="nota">' + items.length + ' de ' + d.tope + ' anexos. ' +
          'Se admiten PDF, imágenes, Excel, Word, CSV y ZIP, hasta 10 MB.</p>';
      }
      c.innerHTML = h;
      c.className = '';
    }).catch(errToast);
  }

  window.anexosElegido = function () {
    var f = this.files && this.files[0];
    if (!f) return;
    var d = document.getElementById('ax-desc');
    // Se propone el nombre del archivo como descripción, sin el sufijo. Es
    // mejor punto de partida que un campo en blanco y se puede reemplazar.
    if (d && !d.value) d.value = f.name.replace(/\.[^.]+$/, '');
  };

  window.anexosSubir = function () {
    var inp = document.getElementById('ax-file');
    var msg = document.getElementById('ax-msg');
    var btn = document.getElementById('ax-btn');
    if (!inp.files || !inp.files[0]) {
      toast('Elija un archivo primero.', 'warn');
      return;
    }
    var fd = new FormData();
    fd.append('archivo', inp.files[0]);
    fd.append('descripcion', val('ax-desc'));

    btn.disabled = true; btn.textContent = 'Subiendo…';
    msg.className = 'form-msg'; msg.textContent = '';

    // FormData va sin Content-Type: el navegador lo pone con su frontera.
    fetch('/api/anexos/' + ctx.entidad + '/' + ctx.id, {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + RST.token },
      body: fd
    }).then(function (r) {
      return r.text().then(function (t) {
        var d; try { d = JSON.parse(t); } catch (e) { d = { detail: t }; }
        if (!r.ok) throw new Error(d.detail || 'No se pudo adjuntar');
        return d;
      });
    }).then(function (d) {
      ctx.hubo = true;
      toast(d.mensaje, 'ok');
      pintar();
      if (typeof ctx.alCerrar === 'function') ctx.alCerrar();
    }).catch(function (e) {
      msg.className = 'form-msg err';
      msg.textContent = e.message;
      btn.disabled = false; btn.textContent = 'Adjuntar';
    });
  };

  /** La descarga NO usa un enlace directo: la API exige el token en la
   *  cabecera y un `<a href>` no la lleva. Se pide con fetch y se dispara
   *  desde un blob. */
  window.anexosBajar = function () {
    var id = this.getAttribute('data-id');
    var nombre = this.getAttribute('data-n');
    fetch('/api/anexos/' + id + '/descargar', {
      headers: { 'Authorization': 'Bearer ' + RST.token }
    }).then(function (r) {
      if (!r.ok) throw new Error('No se pudo descargar el archivo');
      return r.blob();
    }).then(function (b) {
      var u = URL.createObjectURL(b);
      var a = document.createElement('a');
      a.href = u; a.download = nombre;
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      setTimeout(function () { URL.revokeObjectURL(u); }, 4000);
    }).catch(errToast);
  };

  window.anexosBorrar = function () {
    var id = this.getAttribute('data-id');
    var nombre = this.getAttribute('data-n');
    if (!confirm('¿Borrar «' + nombre + '»? No se puede deshacer.')) return;
    api('/api/anexos/' + id, { method: 'DELETE' })
      .then(function (r) {
        ctx.hubo = true;
        toast(r.mensaje, 'ok');
        pintar();
        if (typeof ctx.alCerrar === 'function') ctx.alCerrar();
      }).catch(errToast);
  };
})();
