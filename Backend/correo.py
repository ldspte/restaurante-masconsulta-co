# -*- coding: utf-8 -*-
"""
================================================================
  RESTAURANTE · MOTOR DE CORREO
================================================================
Un único punto de salida para todo el correo del sistema.

POR QUÉ HTTPS Y NO SMTP
-----------------------
El hosting compartido de GoDaddy **bloquea los puertos SMTP salientes**. Un
sistema que intente enviar con `smtplib` no falla de forma ruidosa: se queda
esperando hasta que expira el tiempo y el usuario ve una pantalla congelada.
Ya ocurrió en otro sistema de la casa y la solución fue la misma: enviar por la
API HTTPS de **Resend**, que sale por el 443 como cualquier otra petición.

EL CORREO NUNCA TUMBA LA OPERACIÓN
----------------------------------
`enviar()` **jamás lanza**. Si no hay clave configurada, si Resend está caído o
si el correo del cliente está mal escrito, la reserva se guarda igual y el
cliente ve su código en pantalla. Al revés —dejar que un fallo de correo
deshaga una reserva— sería cambiar un problema pequeño por uno grave.

Lo que sí hace es dejar rastro en el registro, para que quien administre sepa
que el correo no salió y por qué.

MISMAS VARIABLES QUE LOS DEMÁS SISTEMAS DE LA CASA
--------------------------------------------------
Se reutilizan los nombres que ya usa NIGC (`RESEND_API_KEY`, `EMAIL_FROM`,
`SMTP_*`) en vez de inventar otros con prefijo propio. Así un mismo `.env`
sirve para los dos y quien administre no tiene que recordar dos convenciones
para la misma cosa.

ORDEN DE TRANSPORTE
-------------------
    1. Resend por HTTPS   si hay RESEND_API_KEY
    2. SMTP               si hay SMTP_PASS
    3. Modo ensayo        si no hay ninguno: se escribe en el registro

La configuración se lee EN CADA LLAMADA, no al importar. Así el orden de los
imports frente a `load_dotenv` nunca cambia el comportamiento — un error sutil
y muy difícil de rastrear cuando ocurre.

SIN CLAVE, MODO ENSAYO
----------------------
El sistema funciona completo en desarrollo sin cuenta de correo y sin mandarle
mensajes de prueba a nadie.

CONFIGURACIÓN  (Backend/.env)
    RESEND_API_KEY=re_...
    EMAIL_FROM=Restaurante Central <reservas@masconsulta.co>
    RST_SITIO_URL=https://restaurante.masconsulta.co

Autor: Arquitectura de Software · Unidad 1
================================================================
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request

log = logging.getLogger("restaurante.correo")

API = "https://api.resend.com/emails"
TIEMPO_LIMITE = 8          # segundos; si Resend no responde, se abandona

_EMAIL_OK = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def _cfg() -> dict:
    """Lee la configuración EN CADA LLAMADA.

    Deliberado: si se leyera al importar, bastaría con que este módulo se
    cargara antes de `load_dotenv` para que el correo quedara mudo sin que
    nada lo delatara. Leerla siempre elimina esa clase de error.
    """
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_from = os.getenv("SMTP_FROM", "").strip() or smtp_user
    return {
        "resend_key": os.getenv("RESEND_API_KEY", "").strip(),
        "email_from": (os.getenv("EMAIL_FROM", "").strip() or smtp_from
                       or "Restaurante <onboarding@resend.dev>"),
        "smtp_host": os.getenv("SMTP_HOST", "smtp.zoho.com").strip(),
        "smtp_port": int(os.getenv("SMTP_PORT", "587") or 587),
        "smtp_user": smtp_user,
        "smtp_pass": os.getenv("SMTP_PASS", ""),
        "smtp_from": smtp_from,
        # A donde contesta el cliente. Si no se configura, se usa el remitente
        # de SMTP, que suele ser un buzon real de la casa.
        "reply_to": (os.getenv("RST_REPLY_TO", "").strip() or smtp_from or ""),
    }


def transportes() -> dict:
    """Que hay disponible y en que orden se intenta.

    Se expone para poder responder «por que no llegan los correos» sin entrar
    al servidor: la respuesta casi siempre esta en el remitente, no en el
    codigo.
    """
    c = _cfg()
    return {"preferido": backend_activo(),
            "resend": bool(c["resend_key"]),
            "smtp": bool(c["smtp_pass"]),
            "respaldo_smtp": bool(c["resend_key"] and c["smtp_pass"]),
            "remitente": c["email_from"],
            "responder_a": c["reply_to"] or None,
            "smtp_host": c["smtp_host"] if c["smtp_pass"] else None}


def backend_activo() -> str:
    """`resend` | `smtp` | `ninguno` — qué transporte se usaría ahora mismo.

    Se expone en `/api/health` para poder responder «¿por qué no llegan los
    correos?» sin entrar al servidor a mirar el `.env`.
    """
    c = _cfg()
    if c["resend_key"]:
        return "resend"
    if c["smtp_pass"]:
        return "smtp"
    return "ninguno"


def sitio_url() -> str:
    return os.getenv("RST_SITIO_URL", "http://127.0.0.1:8100").strip().rstrip("/")


# Identificador del ultimo mensaje aceptado por Resend. Sirve para PREGUNTARLE
# despues que paso con el: un 200 de Resend significa «lo recibi para
# entregarlo», no «llego». Sin este id hay que ir al panel web a buscarlo a
# mano, y esa es la diferencia entre diagnosticar en diez segundos o en media
# hora.
_ULTIMO_ID: str = ""


def ultimo_id() -> str:
    return _ULTIMO_ID


def _por_resend(c: dict, destino: str, asunto: str, html: str, texto: str) -> bool:
    global _ULTIMO_ID
    # `reply_to` no es cosmetico: un remitente sin direccion de respuesta
    # valida es una de las senales que los filtros usan para clasificar como
    # correo no deseado. Ademas, un cliente que responda la confirmacion de su
    # reserva espera que alguien la lea.
    datos = {
        "from": c["email_from"],
        "to": [destino],
        "subject": asunto,
        "html": html,
        "text": texto,
    }
    if c["reply_to"]:
        datos["reply_to"] = c["reply_to"]
    cuerpo = json.dumps(datos).encode("utf-8")

    pet = urllib.request.Request(API, data=cuerpo, method="POST")
    pet.add_header("Authorization", "Bearer " + c["resend_key"])
    pet.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(pet, timeout=TIEMPO_LIMITE) as r:
        crudo = r.read().decode("utf-8", "replace")
        try:
            _ULTIMO_ID = (json.loads(crudo) or {}).get("id") or ""
        except Exception:
            _ULTIMO_ID = ""
        return r.status in (200, 201)


def estado_resend(id_mensaje: str) -> dict:
    """Le pregunta a Resend que paso con un mensaje concreto.

    `last_event` responde lo unico que importa cuando «se envio pero no llego»:

        delivered   el servidor del destinatario lo acepto -> mirar spam
        bounced     lo rechazaron -> el motivo viene en la respuesta
        complained  lo marcaron como correo no deseado
        sent        aun en camino
    """
    c = _cfg()
    if not c["resend_key"]:
        return {"ok": False, "detalle": "No hay RESEND_API_KEY configurada."}
    if not id_mensaje:
        return {"ok": False, "detalle": "No hay id de mensaje que consultar."}

    pet = urllib.request.Request(API + "/" + id_mensaje, method="GET")
    pet.add_header("Authorization", "Bearer " + c["resend_key"])
    try:
        with urllib.request.urlopen(pet, timeout=TIEMPO_LIMITE) as r:
            d = json.loads(r.read().decode("utf-8", "replace") or "{}")
        return {"ok": True, "id": id_mensaje,
                "estado": d.get("last_event") or d.get("status") or "desconocido",
                "de": d.get("from"), "para": d.get("to"),
                "asunto": d.get("subject"), "creado": d.get("created_at")}
    except urllib.error.HTTPError as e:
        detalle = ""
        try:
            detalle = e.read().decode()[:220]
        except Exception:
            pass
        return {"ok": False, "detalle": "Resend respondio %s: %s" % (e.code, detalle)}
    except Exception as e:
        return {"ok": False, "detalle": "%s: %s" % (type(e).__name__, e)}


def _por_smtp(c: dict, destino: str, asunto: str, html: str, texto: str) -> bool:
    """Respaldo. En hosting compartido de GoDaddy el puerto SMTP saliente suele
    estar BLOQUEADO: el envío no falla rápido, se queda esperando. Por eso
    Resend va primero y esto queda solo para servidores que sí lo permitan."""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    msg = MIMEMultipart("alternative")
    msg["Subject"] = asunto
    msg["From"] = c["smtp_from"] or c["email_from"]
    msg["To"] = destino
    msg.attach(MIMEText(texto, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP(c["smtp_host"], c["smtp_port"], timeout=TIEMPO_LIMITE) as s:
        s.starttls()
        s.login(c["smtp_user"], c["smtp_pass"])
        s.send_message(msg)
    return True


# Ultimo fallo de envio. Existe para poder responder «por que no llegan los
# correos» sin entrar al servidor a leer un registro. Guarda el MOTIVO, nunca
# la clave ni el contenido del mensaje.
_ULTIMO_ERROR = ""


def ultimo_error() -> str:
    return _ULTIMO_ERROR


def remitente() -> str:
    """El `From` configurado. Es la causa mas frecuente de rechazo: Resend
    exige que el dominio del remitente este VERIFICADO en la cuenta."""
    return _cfg()["email_from"]


def probar(destino: str):
    """Manda un correo de prueba y devuelve (ok, motivo).

    El modo de fallo tipico —dominio del remitente sin verificar en Resend—
    produce un rechazo que solo se ve en el log del servidor. Sin esto hay que
    pedirle a alguien que entre por FTP para responder algo de treinta
    segundos.
    """
    ok = enviar(destino, "Prueba de correo - Restaurante",
                "<p>Si recibe este mensaje, el correo del sistema funciona.</p>",
                "Si recibe este mensaje, el correo del sistema funciona.")
    if ok:
        return True, "Enviado por %s desde %s" % (backend_activo(), remitente())
    return False, _ULTIMO_ERROR or "No se envio y no se registro un motivo."


def enviar(destino: str, asunto: str, html: str, texto: str = "") -> bool:
    """Envía un correo. Devuelve si salió, pero NUNCA lanza.

    El llamador puede ignorar el resultado con tranquilidad: la operación de
    negocio ya está guardada cuando esto se ejecuta. Dejar que un fallo de
    correo deshaga una reserva sería cambiar un problema pequeño por uno grave.
    """
    global _ULTIMO_ERROR
    _ULTIMO_ERROR = ""
    destino = (destino or "").strip()
    if not destino or not _EMAIL_OK.match(destino):
        _ULTIMO_ERROR = "Destino invalido o vacio: %r" % destino[:40]
        log.info("Correo omitido: destino inválido o vacío (%r)", destino[:40])
        return False

    c = _cfg()
    texto = texto or re.sub(r"<[^>]+>", " ", html)
    via = backend_activo()

    if via == "ninguno":
        _ULTIMO_ERROR = "No hay transporte: falta RESEND_API_KEY (o SMTP_PASS)."
        log.info("[ENSAYO] Correo NO enviado · falta RESEND_API_KEY o SMTP_PASS\n"
                 "         Para: %s\n         Asunto: %s", destino, asunto)
        return False

    # ── Intento 1: el transporte preferido ────────────────────────────
    try:
        salio = (_por_resend(c, destino, asunto, html, texto) if via == "resend"
                 else _por_smtp(c, destino, asunto, html, texto))
        if salio:
            log.info("Correo enviado por %s a %s · %s", via, destino, asunto)
            return True
        _ULTIMO_ERROR = "%s no confirmó el envío." % via
    except urllib.error.HTTPError as e:
        detalle = ""
        try:
            detalle = e.read().decode()[:220]
        except Exception:
            pass
        _ULTIMO_ERROR = "Resend respondio %s: %s" % (e.code, detalle)
        log.error("Resend rechazó el correo a %s: %s %s", destino, e.code, detalle)
    except Exception as e:
        _ULTIMO_ERROR = "%s: %s" % (type(e).__name__, e)
        log.error("No se pudo enviar el correo a %s por %s: %s", destino, via, e)

    # ── Intento 2: SMTP como red de seguridad ─────────────────────────
    #
    # Si Resend rechaza —el caso tipico es un remitente de dominio sin
    # verificar, que devuelve 403— y hay SMTP configurado, se intenta por ahi
    # antes de darse por vencido. Son dos caminos independientes: que falle uno
    # no dice nada del otro, y rendirse con el segundo disponible es perder un
    # correo que si podia salir.
    #
    # El motivo del PRIMER fallo se conserva: es el que hay que corregir. El
    # respaldo entrega hoy, no arregla la configuracion.
    if via == "resend" and c["smtp_pass"]:
        motivo_resend = _ULTIMO_ERROR
        try:
            if _por_smtp(c, destino, asunto, html, texto):
                log.warning("Resend falló (%s) · el correo a %s salió por SMTP",
                            motivo_resend, destino)
                _ULTIMO_ERROR = ("Resend falló (%s) pero el correo salió por SMTP. "
                                 "Conviene arreglar Resend igual." % motivo_resend)
                return True
        except Exception as e:
            log.error("El respaldo SMTP también falló para %s: %s", destino, e)
            _ULTIMO_ERROR = ("Resend: %s | SMTP: %s: %s"
                             % (motivo_resend, type(e).__name__, e))

    return False


# ══════════════════════════════════════════════════════════════════════
#  PLANTILLA
#  Una sola, con la identidad del restaurante. Los clientes de correo
#  ignoran las hojas de estilo externas y muchos recortan el CSS del
#  <head>, así que todo va en línea: es feo de escribir y es lo que
#  funciona en Gmail, Outlook y el correo del celular.
# ══════════════════════════════════════════════════════════════════════
VERDE = "#1B4332"
LATON = "#C9A227"
CREMA = "#FBF7F0"
ARENA = "#F2EADF"


def _marco(titular: str, cuerpo: str, pie: str = "") -> str:
    return f"""\
<div style="background:{CREMA};padding:28px 16px;font-family:Segoe UI,Helvetica,Arial,sans-serif">
  <div style="max-width:520px;margin:0 auto;background:#fff;border-radius:14px;
              overflow:hidden;border:1px solid #E5DFD4">
    <div style="background:{VERDE};padding:22px 26px">
      <div style="color:#fff;font-family:Georgia,serif;font-size:21px;font-weight:700">
        {titular}</div>
    </div>
    <div style="padding:26px">
      {cuerpo}
    </div>
    <div style="background:{ARENA};padding:16px 26px;font-size:12px;color:#6B6B63;
                line-height:1.6">
      {pie or "Este correo se envió automáticamente. No hace falta responderlo."}
    </div>
  </div>
</div>"""


def _boton(url: str, texto: str) -> str:
    return (f'<a href="{url}" style="display:inline-block;background:{VERDE};color:#fff;'
            f'text-decoration:none;padding:13px 28px;border-radius:100px;'
            f'font-weight:600;font-size:15px">{texto}</a>')


# ══════════════════════════════════════════════════════════════════════
#  CORREOS DEL DOMINIO
# ══════════════════════════════════════════════════════════════════════
def reserva_creada(reserva: dict, perfil: dict) -> bool:
    """Confirma la reserva y entrega el código.

    El código va GRANDE y con espacio alrededor: es el dato que la persona va a
    buscar tres días después, con el correo abierto en el celular y a medio
    leer. Todo lo demás del mensaje existe para acompañarlo.

    El enlace lleva el código, no el teléfono. Un dato personal en una URL
    queda en el historial del navegador, en los registros del servidor y en el
    referente de cualquier enlace que se pulse después. El teléfono se pide en
    la página, que es donde debe pedirse.
    """
    titular = perfil.get("titular") or "Restaurante"
    url = f"{sitio_url()}/?reserva={reserva['codigo']}"

    fecha = reserva.get("fecha", "")
    hora = reserva.get("hora", "")
    personas = reserva.get("personas", "")

    contacto = []
    if perfil.get("telefono"):
        contacto.append(f"Tel. {perfil['telefono']}")
    if perfil.get("direccion"):
        contacto.append(perfil["direccion"])

    cuerpo = f"""
<p style="font-size:16px;color:#1A1A18;margin:0 0 6px">
  Hola, {reserva.get('nombre', '')}.</p>
<p style="font-size:15px;color:#6B6B63;line-height:1.7;margin:0 0 22px">
  Su mesa quedó apartada. Le confirmaremos por teléfono.</p>

<div style="background:{ARENA};border-radius:12px;padding:20px;text-align:center;
            margin-bottom:22px">
  <div style="font-size:11px;letter-spacing:1.6px;text-transform:uppercase;
              color:#6B6B63;font-weight:700;margin-bottom:8px">
    Código de su reserva</div>
  <div style="font-family:Georgia,serif;font-size:34px;font-weight:700;
              color:{VERDE};letter-spacing:3px">{reserva['codigo']}</div>
</div>

<table style="width:100%;font-size:15px;color:#1A1A18;border-collapse:collapse;
              margin-bottom:24px">
  <tr><td style="padding:7px 0;color:#6B6B63;width:110px">Fecha</td>
      <td style="padding:7px 0"><b>{fecha}</b></td></tr>
  <tr><td style="padding:7px 0;color:#6B6B63">Hora</td>
      <td style="padding:7px 0"><b>{hora}</b></td></tr>
  <tr><td style="padding:7px 0;color:#6B6B63">Personas</td>
      <td style="padding:7px 0"><b>{personas}</b></td></tr>
</table>

<p style="font-size:14.5px;color:#6B6B63;line-height:1.7;margin:0 0 18px">
  <b style="color:#1A1A18">¿Le cambiaron los planes?</b> Puede cancelar desde la
  página con este código y el teléfono con el que reservó. Avisar nos permite
  darle la mesa a alguien más.</p>

<div style="text-align:center;margin-bottom:6px">{_boton(url, 'Ver o cancelar mi reserva')}</div>
"""
    return enviar(
        reserva.get("email", ""),
        f"Su reserva en {titular} · {reserva['codigo']}",
        _marco(titular, cuerpo,
               " · ".join(contacto) if contacto else ""),
        texto=(f"Su reserva en {titular}\n\n"
               f"Código: {reserva['codigo']}\n"
               f"Fecha: {fecha} a las {hora}\n"
               f"Personas: {personas}\n\n"
               f"Para consultarla o cancelarla: {url}"))


def reserva_cancelada(reserva: dict, perfil: dict) -> bool:
    """Deja constancia de la cancelación.

    Existe por una razón concreta: si alguien cancela una reserva que no era
    suya, el dueño legítimo se entera por este correo. Es la única señal que
    tendría.
    """
    titular = perfil.get("titular") or "Restaurante"
    cuerpo = f"""
<p style="font-size:16px;color:#1A1A18;margin:0 0 6px">
  Hola, {reserva.get('nombre', '')}.</p>
<p style="font-size:15px;color:#6B6B63;line-height:1.7;margin:0 0 20px">
  Su reserva <b style="color:#1A1A18">{reserva['codigo']}</b> del
  {reserva.get('fecha', '')} a las {reserva.get('hora', '')} quedó
  <b style="color:#B91C1C">cancelada</b>.</p>
<p style="font-size:14.5px;color:#6B6B63;line-height:1.7;margin:0 0 20px">
  Gracias por avisarnos: así podemos darle la mesa a alguien más.</p>
<p style="font-size:14.5px;color:#6B6B63;line-height:1.7;margin:0">
  <b style="color:#1A1A18">¿No fue usted?</b> Llámenos de inmediato y lo
  resolvemos.</p>
"""
    return enviar(
        reserva.get("email", ""),
        f"Reserva cancelada · {reserva['codigo']}",
        _marco(titular, cuerpo,
               f"Tel. {perfil['telefono']}" if perfil.get("telefono") else ""),
        texto=(f"Su reserva {reserva['codigo']} del {reserva.get('fecha')} "
               f"a las {reserva.get('hora')} quedó cancelada.\n"
               f"Si no fue usted, llámenos de inmediato."))


def factura_emitida(doc: dict, cliente: dict, emisor: dict) -> bool:
    """Entrega la factura al adquiriente.

    POR QUE EXISTE
    --------------
    El correo del adquiriente es OBLIGATORIO para facturar, y el sistema lo
    exigia... para despues no mandar nada. Se le pedia un dato al cliente en el
    mostrador y no se usaba: la factura quedaba guardada en el servidor y el
    cliente esperando.

    EN MODO SIMULADO SE DICE
    ------------------------
    Mientras no haya proveedor tecnologico, el documento NO esta firmado ni
    transmitido a la DIAN. Mandarlo como «su factura electronica» seria
    afirmar algo falso, asi que el correo lo advierte en el cuerpo, no en
    letra pequena. Cuando se contrate el proveedor, desaparece el aviso.
    """
    destino = (cliente.get("email") or "").strip()
    if not destino:
        return False

    simulado = (doc.get("estado") or "") == "simulado"
    total = float(doc.get("total") or 0)
    propina = float(doc.get("propina") or 0)

    filas = ""
    for it in (doc.get("items") or []):
        filas += (
            f'<tr><td style="padding:7px 0;border-bottom:1px solid #F0EBE3">'
            f'{it.get("nombre","")}<br>'
            f'<span style="color:#8A8578;font-size:12px">'
            f'{_moneda(it.get("cantidad"))} x {_moneda(it.get("precio_unit"))}</span></td>'
            f'<td style="padding:7px 0;border-bottom:1px solid #F0EBE3;text-align:right;'
            f'white-space:nowrap">{_moneda(it.get("total"))}</td></tr>')

    aviso = ""
    if simulado:
        aviso = ('<div style="background:#FFF7ED;border-left:4px solid #EA580C;'
                 'padding:12px 14px;border-radius:8px;margin-bottom:18px;font-size:13px;'
                 'color:#7C2D12"><b>Documento de prueba.</b> Todavia no esta firmado '
                 'digitalmente ni transmitido a la DIAN, asi que <b>no tiene validez '
                 'fiscal</b>. Sirve como comprobante de su consumo.</div>')

    cuerpo = (
        f'{aviso}'
        f'<p style="font-size:15px;color:#2B2B26;margin:0 0 6px">'
        f'Hola {cliente.get("razon_social","")},</p>'
        f'<p style="color:#6B6B63;font-size:14px;margin:0 0 20px">'
        f'Este es el detalle de su consumo en {emisor.get("razon_social","")}.</p>'
        f'<div style="background:{ARENA};border-radius:10px;padding:16px 18px;'
        f'margin-bottom:18px">'
        f'<div style="font-size:12px;color:#8A8578;letter-spacing:.5px">DOCUMENTO</div>'
        f'<div style="font-size:19px;font-weight:700;color:{VERDE}">'
        f'{doc.get("numero","")}</div>'
        f'<div style="font-size:12px;color:#8A8578;margin-top:8px">'
        f'CUFE {str(doc.get("cufe",""))[:32]}…</div></div>'
        f'<table style="width:100%;border-collapse:collapse;font-size:14px;'
        f'color:#2B2B26">{filas}</table>'
        f'<table style="width:100%;border-collapse:collapse;font-size:14px;'
        f'margin-top:14px">'
        f'<tr><td style="padding:4px 0;color:#6B6B63">Consumo</td>'
        f'<td style="text-align:right">{_moneda(doc.get("subtotal"))}</td></tr>'
        f'<tr><td style="padding:4px 0;color:#6B6B63">Impuesto al consumo</td>'
        f'<td style="text-align:right">{_moneda(doc.get("impuestos"))}</td></tr>'
        + (f'<tr><td style="padding:4px 0;color:#6B6B63">Propina voluntaria</td>'
           f'<td style="text-align:right">{_moneda(propina)}</td></tr>' if propina else '')
        + f'<tr><td style="padding:10px 0 0;font-weight:700;font-size:17px;'
        f'border-top:2px solid {VERDE}">Total</td>'
        f'<td style="padding:10px 0 0;text-align:right;font-weight:700;font-size:17px;'
        f'border-top:2px solid {VERDE}">{_moneda(total)}</td></tr></table>'
        + ('<p style="color:#8A8578;font-size:12px;margin-top:16px">La propina es '
           'voluntaria, va completa al personal y no forma parte de la base '
           'gravable.</p>' if propina else '')
    )

    pie = (f'{emisor.get("razon_social","")} · NIT {emisor.get("nit","")}'
           f'<br>{emisor.get("direccion","") or ""}')

    return enviar(destino,
                  f'Su documento {doc.get("numero","")} · {emisor.get("razon_social","")}',
                  _marco("Gracias por su visita", cuerpo, pie))


def _moneda(v) -> str:
    """Formato colombiano: punto de miles, sin decimales. Los clientes de
    correo no ejecutan JavaScript, así que se arma aquí."""
    try:
        return "$" + f"{float(v or 0):,.0f}".replace(",", ".")
    except Exception:
        return "$0"
