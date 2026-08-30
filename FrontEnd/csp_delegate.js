/* ══════════════════════════════════════════════════════════════════════
   CAFETERÍA · Delegación de eventos compatible con CSP

   POR QUÉ EXISTE ESTE ARCHIVO
   El backend envía una Content-Security-Policy con `script-src 'self'`, sin
   'unsafe-inline'. Bajo esa política el navegador IGNORA los atributos
   onclick="…" del HTML. Es una restricción deseada —cierra la vía principal
   de explotación de un XSS— pero obliga a resolver de otra forma el problema
   de asociar comportamiento a elementos que se crean dinámicamente.

   La solución es un ÚNICO escucha a nivel de documento que despacha según el
   atributo `data-act`:

       <button data-act="guardarProducto" data-args="12">Guardar</button>
       → llama a window.guardarProducto('12', evento)

   Ventaja adicional sobre asignar .onclick a cada elemento: funciona con HTML
   generado después, sin volver a enlazar nada tras cada re-render.

   Gana el elemento MÁS INTERNO con [data-act], así que un botón dentro de una
   tarjeta clicable no necesita detener la propagación.
   ══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  function despachar(e) {
    var objetivo = e.target;
    var el = objetivo && objetivo.closest ? objetivo.closest('[data-act]') : null;
    if (!el) return;

    var nombre = el.getAttribute('data-act');
    if (!nombre) return;

    // Un <select> se comunica por 'change', nunca por 'click' ni 'input'.
    // Sin esta guarda, abrir el desplegable dispararía la acción y, si el
    // manejador vuelve a pintar, el <select> se reconstruye y el usuario no
    // alcanza a elegir nada.
    if (el.tagName === 'SELECT' && e.type !== 'change') return;
    // Los campos de texto no deben reaccionar al click de enfoque.
    if (el.tagName === 'INPUT' && el.type !== 'checkbox' && e.type === 'click') return;

    var fn = nombre.indexOf('.') === -1
      ? window[nombre]
      : nombre.split('.').reduce(function (o, k) { return o && o[k]; }, window);

    if (typeof fn !== 'function') {
      console.warn('[csp] Acción no encontrada:', nombre);
      return;
    }

    // Un enlace que delega su acción no debe navegar al ancla.
    if (e.type === 'click' && el.tagName === 'A') e.preventDefault();

    var crudo = el.getAttribute('data-args');
    var args = crudo ? crudo.split('|').map(function (s) {
      try { return decodeURIComponent(s); } catch (x) { return s; }
    }) : [];
    args.push(e);

    try {
      fn.apply(el, args);
    } catch (err) {
      console.error('[csp] Error en la acción «' + nombre + '»:', err);
    }
  }

  document.addEventListener('click', despachar);
  document.addEventListener('change', despachar);

  // Envío de formularios: evita la recarga completa de la página.
  document.addEventListener('submit', function (e) {
    var f = e.target;
    if (f && f.hasAttribute && f.hasAttribute('data-act')) {
      e.preventDefault();
      despachar(e);
    }
  });

  // Primitivas de interfaz reutilizables, para sustituir el manejo de DOM que
  // antes vivía dentro de los atributos inline.
  function porId(id) { return document.getElementById(id); }
  window.__mostrar = function (id) { var e = porId(id); if (e) e.classList.add('on'); };
  window.__ocultar = function (id) { var e = porId(id); if (e) e.classList.remove('on'); };
  window.__click = function (id) { var e = porId(id); if (e) e.click(); };

  // Escape obligatorio de todo texto que provenga de datos.
  // Sin esto, un producto llamado <img onerror=…> ejecutaría código al
  // pintarse la tabla: la CSP bloquea el script inline del documento, pero no
  // salva de un innerHTML mal construido.
  window.esc = function (s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  };

  // Codificación para data-args: el separador es '|', así que un valor que lo
  // contenga partiría los argumentos en dos.
  window.arg = function (v) { return encodeURIComponent(String(v == null ? '' : v)); };
})();
