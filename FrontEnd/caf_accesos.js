/* ══════════════════════════════════════════════════════════════════════
   CAFETERÍA · Módulo ACCESOS
   Usuarios, roles, sedes y bitácora de auditoría. Solo para administradores.
   Backend: /api/accesos/*
   ══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var COLOR = '#0891B2';
  var vista = 'usuarios', usuarios = null, roles = [];

  window.accesosInyectar = function () {
    crearPagina('accesos', '🔐', 'Accesos',
      'Usuarios, roles por sede y bitácora de auditoría.', COLOR);
    var acc = document.getElementById('acc-accesos');
    if (acc && !acc.innerHTML) {
      acc.innerHTML = '<button class="btn btn-p" data-act="accesosNuevoUsuario">+ Usuario</button>' +
        '<button class="btn" data-act="accesosNuevaSede">🏪 Nueva sede</button>' +
        '<button class="btn" data-act="accesosAlAbrir">↻</button>';
    }
  };

  window.accesosAlAbrir = function () {
    var c = document.getElementById('cont-accesos');
    c.innerHTML = '<div class="tabs">' +
      tab('usuarios', '👥 Usuarios') + tab('sedes', '🏪 Sedes') +
      tab('auditoria', '📜 Auditoría') + tab('perfil', '⚙️ Mi cuenta') +
      '</div><div id="ac-cuerpo"><div class="vacio">⏳ Cargando…</div></div>';
    cargar();
  };

  window.accesosVista = function (v) { vista = v; accesosAlAbrir(); };

  function tab(v, etiqueta) {
    return '<button class="tab' + (vista === v ? ' on' : '') + '" data-act="accesosVista" data-args="' +
      v + '">' + etiqueta + '</button>';
  }

  function cargar() {
    if (vista === 'perfil') return pintarPerfil();
    var rutas = { usuarios: '/api/accesos/usuarios', sedes: '/api/accesos/sedes',
                  auditoria: '/api/accesos/auditoria?limite=150' };
    api(rutas[vista])
      .then({ usuarios: pintarUsuarios, sedes: pintarSedes, auditoria: pintarAuditoria }[vista])
      .catch(function (e) {
        document.getElementById('ac-cuerpo').innerHTML =
          '<div class="aviso e">' + esc(e.message) + '</div>';
      });
  }

  // ── Usuarios ──────────────────────────────────────────────────────
  function pintarUsuarios(r) {
    usuarios = r.items;
    roles = r.roles || [];

    var h = '<div class="card mb"><div class="card-b">' +
      '<div class="peq mut mb"><b>Roles del sistema.</b> Definen qué módulos ve cada persona ' +
      'y qué operaciones puede ejecutar. El servidor los verifica en cada petición: ocultar ' +
      'un botón no basta.</div><div class="grid g4">';
    roles.forEach(function (rol) {
      h += '<div style="padding:10px 12px;background:#F9FAFB;border-radius:9px">' +
        '<b class="peq">' + esc(rol.label) + '</b>' +
        '<div class="peq mut" style="margin-top:3px">' + esc(rol.desc) + '</div></div>';
    });
    h += '</div></div></div>';

    h += '<div class="card"><div class="tabla-wrap"><table><thead><tr>' +
      '<th>Nombre</th><th>Correo</th><th>Rol</th><th>Estado</th><th></th>' +
      '</tr></thead><tbody>';
    r.items.forEach(function (u) {
      var activo = Number(u.acceso_activo) === 1 && Number(u.activo) === 1;
      h += '<tr><td><b>' + esc(u.nombre) + '</b>' +
        (Number(u.es_superadmin) ? ' <span class="tag t-info">super</span>' : '') + '</td>' +
        '<td class="peq mut">' + esc(u.email) + '</td>' +
        '<td><span class="tag t-gris">' + esc(u.rol) + '</span></td>' +
        '<td><span class="tag ' + (activo ? 't-ok">Activo' : 't-bad">Inactivo') + '</span></td>' +
        '<td class="num">' +
        '<button class="btn btn-sm" data-act="accesosEditar" data-args="' + arg(u.id) + '">✎</button> ' +
        '<button class="btn btn-sm" data-act="accesosAlternar" data-args="' + arg(u.id) + '|' +
        (activo ? '0' : '1') + '">' + (activo ? '🚫' : '✅') + '</button>' +
        '</td></tr>';
    });
    document.getElementById('ac-cuerpo').innerHTML = h + '</tbody></table></div></div>';
  }

  window.accesosNuevoUsuario = function () {
    if (!roles.length) roles = [{ key: 'cajero', label: 'Cajero' }];
    var opciones = roles.map(function (r) {
      return '<option value="' + r.key + '">' + esc(r.label) + '</option>';
    }).join('');
    modal('Nuevo usuario',
      '<div class="campo"><label for="us-nombre">Nombre completo</label>' +
      '<input type="text" id="us-nombre"></div>' +
      '<div class="campo"><label for="us-email">Correo</label>' +
      '<input type="email" id="us-email" placeholder="persona@qmspm.com"></div>' +
      '<div class="campo"><label for="us-rol">Rol en esta sede</label>' +
      '<select id="us-rol">' + opciones + '</select></div>' +
      '<div class="campo"><label for="us-pass">Contraseña inicial</label>' +
      '<input type="password" id="us-pass" placeholder="Mínimo 8 caracteres"></div>' +
      '<div class="aviso i peq">Si el correo ya existe en otra sede, se le concede acceso a ' +
      'esta sin modificar su contraseña: una identidad puede trabajar en varias sedes.</div>',
      'Crear usuario', function () {
        if (!val('us-nombre') || !val('us-email')) return toast('Nombre y correo son obligatorios', 'warn');
        if (val('us-pass').length < 8) return toast('La contraseña debe tener al menos 8 caracteres', 'warn');
        api('/api/accesos/usuarios', {
          method: 'POST',
          body: { nombre: val('us-nombre'), email: val('us-email'),
                  rol: val('us-rol'), password: val('us-pass') }
        }).then(function (r) {
          modalCerrar();
          toast(r.reutilizado ? 'Se otorgó acceso a un usuario existente' : 'Usuario creado', 'ok');
          accesosAlAbrir();
        }).catch(errToast);
      });
  };

  window.accesosEditar = function (id) {
    var u = usuarios.filter(function (x) { return String(x.id) === String(id); })[0];
    if (!u) return;
    var opciones = roles.map(function (r) {
      return '<option value="' + r.key + '"' + (u.rol === r.key ? ' selected' : '') + '>' +
        esc(r.label) + '</option>';
    }).join('');
    modal('Editar · ' + u.nombre,
      '<div class="campo"><label for="ue-rol">Rol</label>' +
      '<select id="ue-rol">' + opciones + '</select></div>' +
      '<div class="campo"><label for="ue-pass">Nueva contraseña (opcional)</label>' +
      '<input type="password" id="ue-pass" placeholder="Dejar vacío para no cambiarla"></div>' +
      '<div class="aviso w peq">Cambiar la contraseña cierra todas las sesiones activas de ' +
      'esa persona.</div>',
      'Guardar', function () {
        var cuerpo = { rol: val('ue-rol') };
        if (val('ue-pass')) {
          if (val('ue-pass').length < 8) return toast('Mínimo 8 caracteres', 'warn');
          cuerpo.password = val('ue-pass');
        }
        api('/api/accesos/usuarios/' + id, { method: 'PUT', body: cuerpo })
          .then(function () { modalCerrar(); toast('Usuario actualizado', 'ok'); accesosAlAbrir(); })
          .catch(errToast);
      });
  };

  window.accesosAlternar = function (id, activo) {
    var u = usuarios.filter(function (x) { return String(x.id) === String(id); })[0];
    var accion = Number(activo) ? 'reactivar' : 'desactivar';
    modalConfirmar('¿Desea ' + accion + ' a «' + (u ? u.nombre : '') + '»?' +
      (Number(activo) ? '' : ' Sus sesiones activas se cerrarán de inmediato.'), function () {
      api('/api/accesos/usuarios/' + id, { method: 'PUT', body: { activo: Number(activo) } })
        .then(function () { toast('Usuario actualizado', 'ok'); accesosAlAbrir(); })
        .catch(errToast);
    });
  };

  // ── Sedes ─────────────────────────────────────────────────────────
  function pintarSedes(r) {
    var h = '<div class="aviso i mb">Cada sede tiene su <b>propia base de datos</b>. Crear una ' +
      'no afecta a las existentes y sus datos quedan aislados: es el modelo que permite ' +
      'crecer agregando sedes sin degradar el rendimiento de las anteriores.</div>';
    h += '<div class="card"><div class="tabla-wrap"><table><thead><tr>' +
      '<th>Sede</th><th>Código</th><th>Ciudad</th><th>Mi rol</th><th>Estado</th><th></th>' +
      '</tr></thead><tbody>';
    r.items.forEach(function (s) {
      var actual = CAF.sede && CAF.sede.id === s.id;
      h += '<tr><td><b>' + esc(s.nombre) + '</b>' +
        (actual ? ' <span class="tag t-ok">actual</span>' : '') + '</td>' +
        '<td class="peq mut">' + esc(s.slug) + '</td>' +
        '<td>' + esc(s.ciudad || '—') + '</td>' +
        '<td><span class="tag t-gris">' + esc(s.rol) + '</span></td>' +
        '<td><span class="tag ' + (Number(s.activo) ? 't-ok">Activa' : 't-bad">Inactiva') + '</span></td>' +
        '<td class="num">' + (actual ? '' :
          '<button class="btn btn-sm" data-act="accesosCambiarSede" data-args="' + arg(s.id) +
          '">Entrar</button>') + '</td></tr>';
    });
    document.getElementById('ac-cuerpo').innerHTML = h + '</tbody></table></div></div>';
  }

  window.accesosCambiarSede = function (id) {
    api('/api/auth/seleccionar-sede', { method: 'POST', body: { sede_id: Number(id) } })
      .then(function () { toast('Cambiando de sede…', 'ok'); location.reload(); })
      .catch(errToast);
  };

  window.accesosNuevaSede = function () {
    modal('🏪 Nueva sede',
      '<div class="campo"><label for="sd-nombre">Nombre</label>' +
      '<input type="text" id="sd-nombre" placeholder="Cafetería Norte"></div>' +
      '<div class="campo"><label for="sd-slug">Código interno</label>' +
      '<input type="text" id="sd-slug" placeholder="norte"></div>' +
      '<div class="fila">' +
      '<div class="campo"><label for="sd-ciudad">Ciudad</label>' +
      '<input type="text" id="sd-ciudad"></div>' +
      '<div class="campo"><label for="sd-nit">NIT</label>' +
      '<input type="text" id="sd-nit"></div></div>' +
      '<div class="aviso w peq">El código solo admite minúsculas, números y guion bajo: ' +
      'nombra el archivo de base de datos de la sede.</div>',
      'Crear sede', function () {
        if (!val('sd-nombre') || !val('sd-slug')) return toast('Nombre y código son obligatorios', 'warn');
        api('/api/accesos/sedes', {
          method: 'POST',
          body: { nombre: val('sd-nombre'), slug: val('sd-slug').toLowerCase(),
                  ciudad: val('sd-ciudad'), nit: val('sd-nit') }
        }).then(function () { modalCerrar(); toast('Sede creada y aprovisionada', 'ok'); accesosAlAbrir(); })
          .catch(errToast);
      });
  };

  // ── Auditoría ─────────────────────────────────────────────────────
  function pintarAuditoria(r) {
    var h = '<div class="card"><div class="card-h">📜 Bitácora de auditoría ' +
      '<span class="peq mut">· últimos ' + r.items.length + ' eventos</span></div>' +
      '<div class="tabla-wrap"><table><thead><tr><th>Fecha</th><th>Usuario</th>' +
      '<th>Acción</th><th>Entidad</th><th>Detalle</th><th>IP</th></tr></thead><tbody>';
    if (!r.items.length) {
      h += '<tr><td colspan="6">' + vacio('📜', 'Sin registros.') + '</td></tr>';
    }
    r.items.forEach(function (a) {
      var clase = a.accion === 'login_fallido' ? 't-bad'
        : (a.accion === 'login' ? 't-ok' : 't-gris');
      h += '<tr><td class="peq">' + fecha(a.ts, true) + '</td>' +
        '<td class="peq">' + esc(a.usuario || '') + '</td>' +
        '<td><span class="tag ' + clase + '">' + esc(a.accion) + '</span></td>' +
        '<td class="peq mut">' + esc(a.entidad || '') + '</td>' +
        '<td class="peq mut">' + esc(a.detalle || '') + '</td>' +
        '<td class="peq mut">' + esc(a.ip || '') + '</td></tr>';
    });
    document.getElementById('ac-cuerpo').innerHTML = h + '</tbody></table></div></div>';
  }

  // ── Mi cuenta ─────────────────────────────────────────────────────
  function pintarPerfil() {
    document.getElementById('ac-cuerpo').innerHTML =
      '<div class="card" style="max-width:460px"><div class="card-h">⚙️ Mi cuenta</div>' +
      '<div class="card-b">' +
      '<p class="peq mut mb"><b>' + esc(CAF.usuario ? CAF.usuario.nombre : '') + '</b><br>' +
      esc(CAF.usuario ? CAF.usuario.email : '') + ' · rol ' + esc(CAF.rol || '') + '</p>' +
      '<div class="campo"><label for="pw-actual">Contraseña actual</label>' +
      '<input type="password" id="pw-actual"></div>' +
      '<div class="campo"><label for="pw-nueva">Nueva contraseña</label>' +
      '<input type="password" id="pw-nueva" placeholder="Mínimo 8 caracteres"></div>' +
      '<button class="btn btn-p" data-act="accesosCambiarPassword">Cambiar contraseña</button>' +
      '<div class="aviso w peq mt">Al cambiarla se cerrarán todas sus sesiones, incluida esta.</div>' +
      '</div></div>';
  }

  window.accesosCambiarPassword = function () {
    if (val('pw-nueva').length < 8) return toast('La nueva contraseña debe tener al menos 8 caracteres', 'warn');
    api('/api/auth/cambiar-password', {
      method: 'POST', body: { actual: val('pw-actual'), nueva: val('pw-nueva') }
    }).then(function (r) {
      toast(r.mensaje, 'ok');
      setTimeout(function () { cerrarSesion(); }, 1400);
    }).catch(errToast);
  };
})();
