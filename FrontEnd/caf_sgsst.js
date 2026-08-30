/* ══════════════════════════════════════════════════════════════════════
   RESTAURANTE · Módulo SG-SST

   Una cocina es de los sitios de trabajo más peligrosos del comercio: fuego
   abierto, aceite a ciento ochenta grados, cuchillos, pisos mojados y prisa.
   La normativa no es papeleo: es la respuesta a que alguien se queme el
   sábado a las nueve de la noche.

   POR QUÉ EL EJE ES EL CICLO PHVA
   -------------------------------
   La Resolución 0312 de 2019 no ordena los sesenta estándares mínimos por
   tema, sino por FASE DEL CICLO: Planear, Hacer, Verificar, Actuar. Y los
   pondera distinto — Hacer pesa 60 de los 100 puntos.

   Presentarlos como una lista plana obliga a que la persona reconstruya esa
   estructura en su cabeza cada vez. Presentarlos por fase responde de un
   vistazo la pregunta que de verdad importa: «¿en qué parte del ciclo estoy
   fallando?». Una empresa puede tener un 70 % global y estar en cero en
   Verificar, que es exactamente el caso que un inspector sanciona.

   LA MATRIZ GTC 45 SE DIBUJA, NO SE LISTA
   ---------------------------------------
   El nivel de riesgo es el producto de tres factores. Una tabla de números
   los muestra; solo una matriz de doble entrada —probabilidad contra
   consecuencia— deja ver la concentración. Es la diferencia entre saber que
   hay seis peligros críticos y ver que los seis están en la misma casilla.

   Backend: /api/sgsst/*
   ══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var COLOR = '#F59E0B';
  var pestana = 'ciclo';
  var cicloFiltro = '';
  var D = {};   // último paquete de datos cargado

  /* Las cuatro fases, en el orden del ciclo. El color no es decorativo:
     acompaña al mismo dato en la rueda, en la tabla y en el filtro. */
  var FASES = [
    { k: 'I', nombre: 'Planear',   c: '#2563EB', d: 'Recursos, política, objetivos y plan anual' },
    { k: 'H', nombre: 'Hacer',     c: '#16A34A', d: 'Ejecución: capacitación, peligros, emergencias' },
    { k: 'V', nombre: 'Verificar', c: '#D97706', d: 'Indicadores, auditoría y revisión por la dirección' },
    { k: 'A', nombre: 'Actuar',    c: '#DC2626', d: 'Acciones preventivas y correctivas' }
  ];

  /* Matriz GTC 45. Filas: nivel de consecuencia. Columnas: nivel de
     probabilidad. Cada casilla es el nivel de riesgo resultante. */
  var NP_COLS = [
    { v: 40, r: '24-40', et: 'Muy alto' },
    { v: 20, r: '10-20', et: 'Alto' },
    { v: 8,  r: '6-8',   et: 'Medio' },
    { v: 4,  r: '2-4',   et: 'Bajo' }
  ];
  var NC_ROWS = [
    { v: 100, et: 'Mortal o catastrófico' },
    { v: 60,  et: 'Muy grave' },
    { v: 25,  et: 'Grave' },
    { v: 10,  et: 'Leve' }
  ];

  window.sgsstInyectar = function () {
    crearPagina('sgsst', '🦺', 'Seguridad y salud en el trabajo',
      'Autoevaluación por ciclo PHVA, matriz de peligros, plan anual e ' +
      'indicadores de accidentalidad.', COLOR);
    document.getElementById('acc-sgsst').innerHTML =
      '<button class="btn" data-act="sstExportar">⬇ Excel</button>' +
      '<button class="btn" data-act="sstImportar">⬆ Importar</button>' +
      '<button class="btn" data-act="sstIncidente">🚨 Reportar incidente</button>' +
      '<button class="btn btn-p" data-act="sstActividad">＋ Actividad del plan</button>';
  };

  window.sgsstAlAbrir = function () {
    // El componente de anexos avisa cuando algo cambió, para que el
    // contador de la tabla no quede mintiendo.
    window.anexosAlCerrar = cargar;
    cargar();
  };

  function cargar() {
    cargando('cont-sgsst');
    Promise.all([api('/api/sgsst/estandares'), api('/api/sgsst/peligros'),
                 api('/api/sgsst/actividades'), api('/api/sgsst/incidentes'),
                 api('/api/sgsst/indicadores'),
                 anexosContar('sst_estandar'), anexosContar('sst_actividad')])
      .then(function (r) {
        D = { est: r[0], pel: r[1], act: r[2], inc: r[3], ind: r[4],
              axEst: r[5], axAct: r[6] };
        pintar();
      }).catch(errToast);
  }

  // ══════════════════════════════════════════════════════════════════
  //  CABECERA
  // ══════════════════════════════════════════════════════════════════
  function pintar() {
    var re = D.est.resumen || {}, kp = D.pel.kpis || {},
        ka = D.act.kpis || {}, ki = D.inc.kpis || {};
    var pct = Number(re.porcentaje || 0);

    var h = '<div class="grid g4" style="margin-bottom:16px">' +
      kpi('Autoevaluación', numero(pct, 1) + ' %', re.valoracion || '', nivelAuto(pct)) +
      kpi('Peligros críticos', kp.criticos || 0,
          'De ' + (kp.total || 0) + ' identificados', (kp.criticos || 0) > 0 ? 'bad' : 'ok') +
      kpi('Plan anual', numero(ka.cumplimiento, 0) + ' %',
          (ka.ejecutadas || 0) + ' de ' + (ka.total || 0) + ' actividades',
          (ka.vencidas || 0) > 0 ? 'warn' : 'ok') +
      kpi('Accidentes del año', ki.accidentes || 0,
          (ki.dias_incapacidad || 0) + ' días de incapacidad',
          (ki.accidentes || 0) > 0 ? 'bad' : 'ok') +
      '</div>';

    if (ki.sin_reportar_arl) {
      h += alerta('🚨 Hay ' + ki.sin_reportar_arl + ' accidente(s) sin reportar a la ARL. ' +
        'El plazo legal es de dos días hábiles y el incumplimiento deja al ' +
        'trabajador sin cobertura.');
    }
    if (ka.vencidas) {
      h += alerta('📅 ' + ka.vencidas + ' actividad(es) del plan anual están vencidas.');
    }

    h += '<div class="tabs">' +
      tab('ciclo', '🔄 Ciclo PHVA') +
      tab('peligros', '⚠️ Matriz de peligros') +
      tab('plan', '📅 Plan anual') +
      tab('incidentes', '🚨 Incidentes') +
      tab('indicadores', '📈 Indicadores') +
      '</div><div id="sst-cuerpo"></div>';

    document.getElementById('cont-sgsst').innerHTML = h;
    cuerpo();
  }

  function nivelAuto(p) { return p >= 86 ? 'ok' : p >= 61 ? 'warn' : 'bad'; }
  function alerta(t) {
    return '<div class="aviso-alerta" style="margin-bottom:14px">' + t + '</div>';
  }
  function tab(k, t) {
    return '<button class="tab' + (pestana === k ? ' on' : '') +
      '" data-act="sstTab" data-k="' + k + '">' + t + '</button>';
  }
  function kpi(k, v, d, clase) {
    return '<div class="kpi ' + (clase || '') + '"><div class="k">' + k + '</div>' +
      '<div class="v">' + v + '</div><div class="d">' + esc(d) + '</div></div>';
  }

  window.sstTab = function () { pestana = this.getAttribute('data-k'); pintar(); };

  function cuerpo() {
    var h = '';
    if (pestana === 'ciclo')       h = vistaCiclo();
    if (pestana === 'peligros')    h = vistaPeligros();
    if (pestana === 'plan')        h = vistaPlan();
    if (pestana === 'incidentes')  h = vistaIncidentes();
    if (pestana === 'indicadores') h = vistaIndicadores();
    document.getElementById('sst-cuerpo').innerHTML = h;
  }

  // ══════════════════════════════════════════════════════════════════
  //  1 · CICLO PHVA
  // ══════════════════════════════════════════════════════════════════
  function vistaCiclo() {
    var re = D.est.resumen || {};
    var pct = Number(re.porcentaje || 0);
    var porCiclo = {};
    (D.est.por_ciclo || []).forEach(function (c) { porCiclo[c.ciclo] = c; });

    /* Semáforo grande con la CONSECUENCIA legal, no solo el número. Un «0 %»
       no dice nada; «crítico: plan de mejora inmediato y reporte a la ARL» sí. */
    var h = '<div class="card" style="margin-bottom:16px"><div class="card-b">' +
      '<div class="sst-semaforo ' + nivelAuto(pct) + '">' +
      anillo(pct, nivelAuto(pct)) +
      '<div class="sem-txt">' +
      '<div class="sem-val">' + esc(re.valoracion || '—') + '</div>' +
      '<div class="sem-pts">' + numero(re.puntaje, 2) + ' de ' + numero(re.maximo, 0) +
      ' puntos · ' + (re.cumplidos || 0) + ' de ' + (re.total || 0) + ' estándares</div>' +
      '<div class="sem-que">' + esc(queSignifica(pct)) + '</div>' +
      '</div></div></div></div>';

    // ── Los cuatro carriles ─────────────────────────────────────────
    h += '<div class="phva">';
    FASES.forEach(function (f, i) {
      var c = porCiclo[f.k] || { peso: 0, obtenido: 0, items: 0 };
      var p = c.peso ? (c.obtenido / c.peso * 100) : 0;
      h += '<div class="fase' + (cicloFiltro === f.k ? ' on' : '') + '" ' +
        'data-act="sstCiclo" data-k="' + f.k + '" style="--fc:' + f.c + '">' +
        '<div class="fase-cab"><span class="fase-let">' + f.k + '</span>' +
        '<span class="fase-nom">' + f.nombre + '</span></div>' +
        '<div class="fase-pct">' + numero(p, 0) + '<small>%</small></div>' +
        '<div class="fase-barra"><div style="width:' + Math.min(p, 100).toFixed(0) + '%"></div></div>' +
        '<div class="fase-pts">' + numero(c.obtenido, 2) + ' / ' + numero(c.peso, 0) +
        ' puntos · ' + (c.items || 0) + ' ítems</div>' +
        '<div class="fase-desc">' + f.d + '</div>' +
        (i < FASES.length - 1 ? '<span class="fase-flecha">→</span>' : '') +
        '</div>';
    });
    h += '</div>';

    h += '<p class="nota" style="margin-bottom:16px">La Resolución 0312 pondera las fases ' +
      'distinto: <b>Hacer vale 60 de los 100 puntos</b>. Un porcentaje global alto con ' +
      'la fase Verificar en cero es exactamente lo que un inspector señala primero.' +
      (cicloFiltro ? ' <b>Filtrando por ' + esc(nombreFase(cicloFiltro)) +
        '.</b> <button class="btn btn-sm" data-act="sstCiclo" data-k="">Ver todas</button>' : '') +
      '</p>';

    // ── Estándares ──────────────────────────────────────────────────
    var items = (D.est.items || []).filter(function (i) {
      return !cicloFiltro || i.ciclo === cicloFiltro;
    });
    // Un estándar marcado sin soporte es el hallazgo más común de una visita.
    var sinSoporte = items.filter(function (i) {
      return i.cumple && !((D.axEst || {})[i.id]);
    }).length;
    if (sinSoporte) {
      h += '<div class="aviso-alerta" style="margin-bottom:14px">📎 Hay <b>' +
        sinSoporte + '</b> estándar(es) marcados como cumplidos <b>sin documento ' +
        'adjunto</b>. Es lo primero que pide un inspector.</div>';
    }

    h += '<div class="card"><div class="card-h">📋 Estándares mínimos · ' +
      items.length + ' ítems</div><div class="card-b"><div class="tabla-wrap">' +
      '<table><thead><tr><th style="width:70px">Ítem</th><th>Descripción</th>' +
      '<th style="width:60px">Fase</th><th class="num" style="width:60px">Peso</th>' +
      '<th style="width:80px">Cumple</th>' +
      '<th style="width:70px">Soporte</th></tr></thead><tbody>';
    items.forEach(function (i) {
      var f = faseDe(i.ciclo);
      h += '<tr class="' + (i.cumple ? 'est-ok' : '') + '">' +
        '<td><b>' + esc(i.item) + '</b></td>' +
        '<td>' + esc(i.descripcion) +
        (i.justifica ? '<div class="sug">' + esc(i.justifica) + '</div>' : '') + '</td>' +
        '<td><span class="fase-chip" style="background:' + f.c + '">' + f.k + '</span></td>' +
        '<td class="num">' + numero(i.peso, 2) + '</td>' +
        '<td><label class="check"><input type="checkbox" data-act="sstCumple" ' +
        'data-id="' + i.id + '"' + (i.cumple ? ' checked' : '') + '><span></span></label></td>' +
        '<td>' + anexosBoton('sst_estandar', i.id, i.item + ' · ' + i.descripcion,
                             (D.axEst || {})[i.id]) + '</td>' +
        '</tr>';
    });
    h += '</tbody></table></div></div></div>';
    return h;
  }

  /** Anillo de progreso en SVG. Un número suelto no comunica «cuánto falta»;
   *  un arco incompleto sí, y sin necesidad de leerlo. */
  function anillo(pct, clase) {
    var r = 52, c = 2 * Math.PI * r;
    var av = c * Math.min(Math.max(pct, 0), 100) / 100;
    var col = clase === 'ok' ? '#16A34A' : clase === 'warn' ? '#D97706' : '#DC2626';
    return '<svg class="anillo" viewBox="0 0 130 130">' +
      '<circle cx="65" cy="65" r="' + r + '" fill="none" stroke="rgba(0,0,0,.08)" ' +
      'stroke-width="13"/>' +
      '<circle cx="65" cy="65" r="' + r + '" fill="none" stroke="' + col + '" ' +
      'stroke-width="13" stroke-linecap="round" stroke-dasharray="' + av + ' ' + c + '" ' +
      'transform="rotate(-90 65 65)"/>' +
      '<text x="65" y="61" text-anchor="middle" class="an-num">' + numero(pct, 1) + '</text>' +
      '<text x="65" y="82" text-anchor="middle" class="an-pct">POR CIENTO</text>' +
      '</svg>';
  }

  function queSignifica(p) {
    if (p >= 86) return 'Cumplimiento aceptable. Mantener y actualizar el plan anual.';
    if (p >= 61) return 'Moderadamente aceptable: exige plan de mejora y seguimiento semestral.';
    return 'Crítico. Requiere plan de mejoramiento inmediato, envío a la ARL y ' +
           'seguimiento mensual hasta superar el 60 %.';
  }
  function faseDe(k) {
    return FASES.filter(function (f) { return f.k === k; })[0] ||
           { k: k, nombre: k, c: '#94A3B8' };
  }
  function nombreFase(k) { return faseDe(k).nombre; }

  window.sstCiclo = function () {
    var el = this;
    var k = el.getAttribute('data-k');
    cicloFiltro = (cicloFiltro === k) ? '' : k;
    cuerpo();
  };

  // ══════════════════════════════════════════════════════════════════
  //  2 · MATRIZ DE PELIGROS
  // ══════════════════════════════════════════════════════════════════
  function vistaPeligros() {
    var items = D.pel.items || [];
    var kp = D.pel.kpis || {};
    var pn = kp.por_nivel || {};

    // Distribución por nivel de riesgo
    var h = '<div class="grid g4" style="margin-bottom:16px">';
    [['I', 'No aceptable', 'bad'], ['II', 'Con control específico', 'bad'],
     ['III', 'Mejorable', 'warn'], ['IV', 'Aceptable', 'ok']].forEach(function (n) {
      h += '<div class="nivel-card ' + n[2] + '"><div class="nv-rom">' + n[0] + '</div>' +
        '<div class="nv-n">' + (pn[n[0]] || 0) + '</div>' +
        '<div class="nv-et">' + n[1] + '</div></div>';
    });
    h += '</div>';

    // ── La matriz ───────────────────────────────────────────────────
    var celdas = {};
    items.forEach(function (p) {
      var np = Number(p.nivel_deficiencia) * Number(p.nivel_exposicion);
      var col = NP_COLS.filter(function (c) { return np <= c.v; }).pop() || NP_COLS[0];
      var fila = Number(p.nivel_consecuencia);
      var clave = fila + '|' + col.v;
      (celdas[clave] = celdas[clave] || []).push(p);
    });

    h += '<div class="card" style="margin-bottom:16px"><div class="card-h">' +
      '🎯 Matriz de riesgo · GTC 45</div><div class="card-b">' +
      '<div class="tabla-wrap"><table class="matriz"><thead><tr>' +
      '<th class="mx-esq">Consecuencia ↓ &nbsp; Probabilidad →</th>';
    NP_COLS.forEach(function (c) {
      h += '<th><b>' + c.et + '</b><span>' + c.r + '</span></th>';
    });
    h += '</tr></thead><tbody>';

    NC_ROWS.forEach(function (f) {
      h += '<tr><th class="mx-fila"><b>' + f.et + '</b><span>NC ' + f.v + '</span></th>';
      NP_COLS.forEach(function (c) {
        var nr = f.v * c.v;
        var niv = nivelRiesgo(nr);
        var aqui = celdas[f.v + '|' + c.v] || [];
        h += '<td class="mx-celda n' + niv + '">' +
          '<span class="mx-niv">' + niv + '</span>' +
          (aqui.length
            ? '<div class="mx-puntos">' + aqui.map(function (p) {
                return '<span class="mx-punto" title="' + esc(p.peligro) + ' · ' +
                  esc(p.proceso) + ' (NR ' + p.nivel_riesgo + ')">' +
                  esc(p.peligro.slice(0, 22)) + '</span>';
              }).join('') + '</div>'
            : '') +
          '</td>';
      });
      h += '</tr>';
    });
    h += '</tbody></table></div>' +
      '<p class="nota">Nivel de riesgo = deficiencia × exposición × consecuencia. ' +
      'La interpretación la calcula el sistema, no la persona: escrita a mano, toda ' +
      'matriz de peligros termina diciendo «bajo». Los niveles <b>I y II</b> exigen ' +
      'intervención documentada y son lo primero que revisa un inspector.</p>' +
      '</div></div>';

    // ── Detalle ─────────────────────────────────────────────────────
    h += '<div class="card"><div class="card-h">⚠️ Peligros identificados</div>' +
      '<div class="card-b"><div class="tabla-wrap"><table><thead><tr>' +
      '<th>Proceso</th><th>Peligro</th><th>Efecto posible</th>' +
      '<th class="num">ND</th><th class="num">NE</th><th class="num">NC</th>' +
      '<th class="num">NR</th><th>Nivel</th><th>Controles</th>' +
      '</tr></thead><tbody>';
    items.slice().sort(function (a, b) { return b.nivel_riesgo - a.nivel_riesgo; })
      .forEach(function (p) {
        var niv = nivelRiesgo(p.nivel_riesgo);
        h += '<tr><td>' + esc(p.proceso) +
          '<div class="sug">' + esc(p.actividad || '') + '</div></td>' +
          '<td><b>' + esc(p.peligro) + '</b>' +
          '<div class="sug">' + esc(p.clasificacion || '') + '</div></td>' +
          '<td>' + esc(p.efecto || '') + '</td>' +
          '<td class="num">' + p.nivel_deficiencia + '</td>' +
          '<td class="num">' + p.nivel_exposicion + '</td>' +
          '<td class="num">' + p.nivel_consecuencia + '</td>' +
          '<td class="num"><b>' + p.nivel_riesgo + '</b></td>' +
          '<td><span class="pill ' + pillNivel(niv) + '">' + niv + '</span>' +
          '<div class="sug">' + esc(p.aceptabilidad || '') + '</div></td>' +
          '<td>' + esc(p.controles || '—') +
          (p.epp ? '<div class="sug">EPP: ' + esc(p.epp) + '</div>' : '') + '</td></tr>';
      });
    h += '</tbody></table></div></div></div>';
    return h;
  }

  function nivelRiesgo(nr) {
    nr = Number(nr || 0);
    return nr >= 600 ? 'I' : nr >= 150 ? 'II' : nr >= 40 ? 'III' : 'IV';
  }
  function pillNivel(n) {
    return n === 'I' ? 'bad' : n === 'II' ? 'bad' : n === 'III' ? 'warn' : 'ok';
  }

  // ══════════════════════════════════════════════════════════════════
  //  3 · PLAN ANUAL
  // ══════════════════════════════════════════════════════════════════
  var MESES = ['E', 'F', 'M', 'A', 'M', 'J', 'J', 'A', 'S', 'O', 'N', 'D'];

  function vistaPlan() {
    var items = D.act.items || [];
    var hoy = new Date().toISOString().slice(0, 10);

    var h = '<div class="card"><div class="card-h">📅 Plan de trabajo anual ' +
      (D.act.anio || '') + '</div><div class="card-b">';

    if (!items.length) {
      h += vacio('📅', 'El plan anual está vacío. Agregue las actividades del año ' +
        'con «＋ Actividad del plan».') + '</div></div>';
      return h;
    }

    /* Cronograma: cada actividad es una fila y los doce meses son columnas.
       Es la forma en que el plan anual se entrega a la ARL, y verlo así hace
       evidente el vicio más común: todo programado para diciembre. */
    h += '<div class="tabla-wrap"><table class="crono"><thead><tr>' +
      '<th>Actividad</th><th>Responsable</th><th style="width:60px">📎</th>';
    MESES.forEach(function (m, i) {
      h += '<th class="cr-mes' + (i === new Date().getMonth() ? ' cr-hoy' : '') + '">' +
        m + '</th>';
    });
    h += '<th>Estado</th><th></th></tr></thead><tbody>';

    items.forEach(function (a) {
      var mesProg = a.fecha_plan ? Number(String(a.fecha_plan).slice(5, 7)) - 1 : -1;
      var mesEjec = a.fecha_real ? Number(String(a.fecha_real).slice(5, 7)) - 1 : -1;
      var hecha = a.estado === 'ejecutada';
      var venc = a.estado === 'planeada' && a.fecha_plan &&
                 String(a.fecha_plan).slice(0, 10) < hoy;
      h += '<tr><td><b>' + esc(a.nombre) + '</b>' +
        '<div class="sug">' + esc(a.tipo || '') +
        (a.evidencia ? ' · 📎 ' + esc(a.evidencia) : '') + '</div></td>' +
        '<td>' + esc(a.responsable || '—') + '</td>' +
        '<td>' + anexosBoton('sst_actividad', a.id, a.nombre,
                             (D.axAct || {})[a.id]) + '</td>';
      for (var m = 0; m < 12; m++) {
        var cls = m === mesEjec ? 'cr-ok' : m === mesProg
          ? (venc ? 'cr-venc' : 'cr-prog') : '';
        h += '<td class="cr-c ' + cls + '"></td>';
      }
      h += '<td><span class="pill ' + (hecha ? 'ok' : venc ? 'bad' : 'info') + '">' +
        (hecha ? 'ejecutada' : venc ? 'vencida' : 'planeada') + '</span></td>' +
        '<td>' + (!hecha
          ? '<button class="btn btn-sm btn-g" data-act="sstEjecutar" data-id="' + a.id +
            '" data-n="' + esc(a.nombre) + '">Marcar hecha</button>' : '') +
        '</td></tr>';
    });
    h += '</tbody></table></div>' +
      '<div class="crono-leyenda">' +
      '<span><i class="cr-prog"></i> Programada</span>' +
      '<span><i class="cr-ok"></i> Ejecutada</span>' +
      '<span><i class="cr-venc"></i> Vencida</span>' +
      '<span><i class="cr-hoy-l"></i> Mes actual</span>' +
      '</div></div></div>';
    return h;
  }

  // ══════════════════════════════════════════════════════════════════
  //  4 · INCIDENTES
  // ══════════════════════════════════════════════════════════════════
  function vistaIncidentes() {
    var items = D.inc.items || [];
    var h = '<div class="card"><div class="card-h">🚨 Incidentes y accidentes de trabajo' +
      '</div><div class="card-b">';
    if (!items.length) {
      h += vacio('✅', 'No hay incidentes registrados. Que siga así.') +
        '<p class="nota">Registre también los <b>casi accidentes</b>: el aceite que se ' +
        'derramó y nadie pisó. Son gratis de anotar y son la única advertencia que ' +
        'llega antes del accidente.</p></div></div>';
      return h;
    }
    h += '<div class="tabla-wrap"><table><thead><tr><th>Fecha</th><th>Persona</th>' +
      '<th>Qué pasó</th><th>Tipo</th><th class="num">Días</th><th>ARL</th>' +
      '</tr></thead><tbody>';
    items.forEach(function (i) {
      h += '<tr><td>' + fecha(i.fecha) + '</td>' +
        '<td>' + esc(i.afectado || '') + '</td>' +
        '<td>' + esc(i.descripcion || '') +
        (i.parte_cuerpo ? '<div class="sug">' + esc(i.parte_cuerpo) + '</div>' : '') + '</td>' +
        '<td><span class="pill ' + (i.tipo === 'accidente' ? 'bad' : 'warn') + '">' +
        esc(i.tipo) + '</span></td>' +
        '<td class="num">' + (i.dias_incapacidad || 0) + '</td>' +
        '<td>' + (i.reportado_arl
          ? '<span class="pill ok">reportado</span>'
          : '<span class="pill bad">sin reportar</span>') + '</td></tr>';
    });
    h += '</tbody></table></div>' +
      '<p class="nota">Un accidente de trabajo se reporta a la ARL dentro de los ' +
      '<b>dos días hábiles</b> siguientes. No hacerlo es una sanción y, sobre todo, ' +
      'deja al trabajador sin cobertura.</p></div></div>';
    return h;
  }

  // ══════════════════════════════════════════════════════════════════
  //  5 · INDICADORES
  // ══════════════════════════════════════════════════════════════════
  function vistaIndicadores() {
    var ind = D.ind || {};
    var h = '<div class="card"><div class="card-h">📈 Indicadores mínimos · ' +
      (ind.anio || '') + ' · ' + (ind.trabajadores || 0) + ' trabajadores</div>' +
      '<div class="card-b"><div class="grid g2">';
    (ind.indicadores || []).forEach(function (i) {
      h += '<div class="ind-card">' +
        '<div class="ind-nom">' + esc(i.nombre) + '</div>' +
        '<div class="ind-val">' + numero(i.valor, 2) +
        '<small> ' + esc(i.unidad || '') + '</small></div>' +
        '<div class="ind-det">' + esc(i.detalle || '') + '</div>' +
        '</div>';
    });
    h += '</div><p class="nota">El artículo 30 de la Resolución 0312 exige llevar ' +
      'estos indicadores <b>con su ficha técnica</b>: definición, fórmula, fuente, ' +
      'periodicidad y responsable. Aquí se calculan solos a partir de los incidentes ' +
      'y del plan, que es la única forma de que no se inventen en diciembre.</p>' +
      '</div></div>';
    return h;
  }

  // ══════════════════════════════════════════════════════════════════
  //  ACCIONES
  // ══════════════════════════════════════════════════════════════════

  // ══════════════════════════════════════════════════════════════════
  //  PLAN ANUAL EN EXCEL
  //
  //  El plan no se construye en esta pantalla: se arma en una reunión, se
  //  pasa a una hoja, la revisa la ARL y vuelve corregida. Obligar a teclear
  //  quince actividades una por una garantiza que el plan viva por fuera del
  //  sistema, que es lo que hay que evitar.
  //
  //  La descarga NO usa un enlace directo: la API exige el token en la
  //  cabecera y un `<a href>` no la lleva. Se pide con fetch, se arma un
  //  blob y se dispara la descarga desde ahí.
  // ══════════════════════════════════════════════════════════════════
  window.sstExportar = function () {
    var anio = (D.act && D.act.anio) || new Date().getFullYear();
    fetch('/api/sgsst/actividades/excel?anio=' + anio, {
      headers: { 'Authorization': 'Bearer ' + RST.token }
    }).then(function (r) {
      if (!r.ok) throw new Error('No se pudo generar el archivo');
      return r.blob();
    }).then(function (b) {
      var u = URL.createObjectURL(b);
      var a = document.createElement('a');
      a.href = u; a.download = 'plan-anual-sgsst-' + anio + '.xlsx';
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      setTimeout(function () { URL.revokeObjectURL(u); }, 4000);
      toast('Plan descargado', 'ok');
    }).catch(errToast);
  };

  window.sstImportar = function () {
    modal('Importar el plan desde Excel',
      '<p class="nota" style="margin-top:0">Suba la misma hoja que descargó, con sus ' +
      'cambios. Las filas <b>con ID</b> actualizan una actividad existente; las que ' +
      'no lo tienen crean una nueva.</p>' +
      '<div class="campo"><label for="im-f">Archivo (.xlsx)</label>' +
      '<input type="file" id="im-f" accept=".xlsx,.xlsm"></div>' +
      '<div id="im-msg" class="form-msg"></div>' +
      '<p class="nota"><b>La importación es todo o nada.</b> Si una fila tiene un ' +
      'error, no entra ninguna y se le indica cuál corregir: un plan a medio ' +
      'importar es peor que uno no importado, porque nadie sabe qué falta.</p>',
      'Importar', function () {
        var inp = document.getElementById('im-f');
        if (!inp.files || !inp.files[0]) { toast('Elija un archivo.', 'warn'); return; }
        var fd = new FormData();
        fd.append('archivo', inp.files[0]);
        fd.append('anio', String((D.act && D.act.anio) || new Date().getFullYear()));

        var msg = document.getElementById('im-msg');
        msg.className = 'form-msg'; msg.textContent = 'Leyendo el archivo…';

        fetch('/api/sgsst/actividades/importar', {
          method: 'POST',
          headers: { 'Authorization': 'Bearer ' + RST.token },
          body: fd
        }).then(function (r) {
          return r.text().then(function (t) {
            var d; try { d = JSON.parse(t); } catch (e) { d = { detail: t }; }
            if (!r.ok) throw new Error(d.detail || 'No se pudo importar');
            return d;
          });
        }).then(function (d) {
          modalCerrar(); toast(d.mensaje, 'ok'); cargar();
        }).catch(function (e) {
          // Los errores por fila llegan en varias líneas: se respetan.
          msg.className = 'form-msg err';
          msg.innerHTML = esc(e.message).replace(/\n/g, '<br>');
        });
      });
  };

  window.sstCumple = function () {
    var el = this;
    api('/api/sgsst/estandares/' + el.getAttribute('data-id'), {
      method: 'PUT', body: { cumple: el.checked ? 1 : 0 }
    }).then(function () { cargar(); }).catch(function (e) {
      el.checked = !el.checked; errToast(e);
    });
  };

  window.sstActividad = function () {
    modal('Actividad del plan anual',
      '<div class="campo"><label for="sa-n">Actividad</label>' +
      '<input type="text" id="sa-n" placeholder="Capacitación en manejo de extintores"></div>' +
      '<div class="fila"><div class="campo"><label for="sa-t">Tipo</label>' +
      '<select id="sa-t"><option value="capacitacion">Capacitación</option>' +
      '<option value="inspeccion">Inspección de puestos</option>' +
      '<option value="simulacro">Simulacro de evacuación</option>' +
      '<option value="examen">Examen médico ocupacional</option>' +
      '<option value="mantenimiento">Mantenimiento de equipos</option>' +
      '<option value="copasst">Reunión del COPASST</option></select></div>' +
      '<div class="campo"><label for="sa-f">Fecha programada</label>' +
      '<input type="date" id="sa-f"></div></div>' +
      '<div class="campo"><label for="sa-r">Responsable</label>' +
      '<input type="text" id="sa-r"></div>' +
      '<p class="nota">Reparta las actividades a lo largo del año. Un plan con todo ' +
      'programado para diciembre no es un plan: es una lista de buenos deseos, y en ' +
      'el cronograma se nota de inmediato.</p>',
      'Agregar', function () {
        api('/api/sgsst/actividades', {
          method: 'POST',
          body: { nombre: val('sa-n'), tipo: document.getElementById('sa-t').value,
                  fecha_plan: val('sa-f'), responsable: val('sa-r') }
        }).then(function () { modalCerrar(); toast('Actividad agregada', 'ok'); cargar(); })
          .catch(errToast);
      });
  };

  /** Marcar ejecutada EXIGE evidencia, y el backend la rechaza sin ella. Se
   *  pide aquí para que el «no» llegue antes del clic y no después: sin ese
   *  requisito la ejecución del plan sería una casilla que alguien marca la
   *  víspera de la visita, y el indicador dejaría de significar algo. */
  window.sstEjecutar = function () {
    var id = this.getAttribute('data-id');
    modal('Marcar como ejecutada',
      '<p class="nota" style="margin-top:0">' + esc(this.getAttribute('data-n') || '') +
      '</p>' +
      '<div class="fila"><div class="campo"><label for="se-f">¿Cuándo se hizo?</label>' +
      '<input type="date" id="se-f" value="' + new Date().toISOString().slice(0, 10) +
      '"></div></div>' +
      '<div class="campo"><label for="se-e">Evidencia</label>' +
      '<input type="text" id="se-e" placeholder="Acta 12 · listado de asistencia de 9 personas"></div>' +
      '<p class="nota">Sin evidencia no se puede cerrar. Es lo que un inspector pide ' +
      'cuando pregunta si la capacitación de verdad se dictó.</p>',
      'Marcar hecha', function () {
        var ev = val('se-e');
        if (!ev) { toast('Registre la evidencia.', 'warn'); return; }
        api('/api/sgsst/actividades/' + id, {
          method: 'PUT',
          body: { estado: 'ejecutada', fecha_real: val('se-f'), evidencia: ev }
        }).then(function () {
          modalCerrar(); toast('Actividad marcada como ejecutada', 'ok'); cargar();
        }).catch(errToast);
      });
  };

  window.sstIncidente = function () {
    modal('Reportar incidente',
      '<div class="fila"><div class="campo"><label for="si-f">Fecha</label>' +
      '<input type="date" id="si-f" value="' + new Date().toISOString().slice(0, 10) +
      '"></div>' +
      '<div class="campo"><label for="si-t">Tipo</label>' +
      '<select id="si-t"><option value="incidente">Incidente (sin lesión)</option>' +
      '<option value="accidente">Accidente de trabajo</option></select></div></div>' +
      '<div class="campo"><label for="si-a">¿A quién?</label>' +
      '<input type="text" id="si-a"></div>' +
      '<div class="campo"><label for="si-d">¿Qué pasó?</label>' +
      '<textarea id="si-d" rows="3" placeholder="Quemadura con aceite al voltear la freidora…"></textarea></div>' +
      '<div class="fila"><div class="campo"><label for="si-p">Parte del cuerpo</label>' +
      '<input type="text" id="si-p"></div>' +
      '<div class="campo"><label for="si-i">Días de incapacidad</label>' +
      '<input type="number" id="si-i" min="0" value="0"></div></div>' +
      '<div class="campo"><label class="check-linea">' +
      '<input type="checkbox" id="si-r"> Ya se reportó a la ARL</label></div>' +
      '<p class="nota">Registre también los <b>casi accidentes</b>: el aceite que se ' +
      'derramó y nadie pisó. Son gratis de anotar y son la única advertencia que llega ' +
      'antes del accidente de verdad.</p>',
      'Reportar', function () {
        api('/api/sgsst/incidentes', {
          method: 'POST',
          body: { fecha: val('si-f'), tipo: document.getElementById('si-t').value,
                  afectado: val('si-a'), descripcion: val('si-d'),
                  parte_cuerpo: val('si-p'),
                  dias_incapacidad: parseInt(val('si-i') || '0', 10),
                  reportado_arl: document.getElementById('si-r').checked ? 1 : 0 }
        }).then(function () { modalCerrar(); toast('Incidente registrado', 'ok'); cargar(); })
          .catch(errToast);
      });
  };
})();
