"""Configuracion de bloques del panel de metricas (auth/secretos/sintesis/
transcripcion). Un typo en un dict suelto se traduce en Jinja2 en un
Undefined silencioso (se renderiza como texto vacio, no rompe nada) -- con
dataclass revienta con AttributeError al importar. Dado que coupertech-portal
no tiene tests, esa diferencia importa: preferimos fallar ruidoso.

Que bloques mostrar y con que parametros es una decision de PRESENTACION de
este panel Jinja concreto -- no un dato de dominio de catalogo de
servicios/planes (couper/catalago ya expone lo que le corresponde: nombre,
slug, precio). Por eso vive aca y no en catalago.
"""
from dataclasses import dataclass, field

_LABEL_ACCESO_COMPLETO = "Acceso completo"
_NOMBRE_SINTESIS = "Síntesis"
_NOMBRE_TRANSCRIPCION = "Transcripción"


@dataclass(frozen=True)
class ConfigApiKeys:
    # Exactamente uno de los dos filtros aplica -- nunca "sin filtro" (esa
    # mezcla es justo lo que se elimino: gestionar sin querer la key de un
    # servicio ajeno desde el panel equivocado).
    filtro_servicio: str | None        # "secretos"/"sintesis"/"transcripcion": solo esas
    filtro_sin_servicio: bool          # True solo en auth: solo credenciales de acceso
                                        # general (sin scope de ningun servicio especifico)
    # None en auth (la seccion se llama "API Keys, aplicaciones de terceros"
    # en ese caso); en el resto vale "Secretos"/_NOMBRE_SINTESIS/_NOMBRE_TRANSCRIPCION.
    nombre_display: str | None


@dataclass(frozen=True)
class ConfigNuevaApiKey:
    nombre_display: str | None
    # [(value, label), ...]. Un solo elemento => no hay eleccion real de
    # permisos (el servicio no tiene modelo de roles detras, ej.
    # sintesis/transcripcion): no se muestra <select>, se manda ese scope
    # fijo sin pedirselo al usuario ("acceso completo" es la unica opcion).
    # Mas de un elemento => si hay un modelo de permisos real (secretos,
    # via empleados con permiso leer/escribir) y se muestra el <select>.
    opciones_scope: list[tuple[str, str]]


@dataclass(frozen=True)
class ConfigDocumentacion:
    variante: str          # "larga" (solo auth) | "corta" (resto)
    servicio_codigo: str   # interpolado en la variante corta: "secretos"/"sintesis"/"transcripcion"


@dataclass(frozen=True)
class ConfigServicio:
    es_auth: bool
    # Slug usado en GET /suscripcion-activa Y en el link /planes/{slug} --
    # mismo valor en los dos usos. Ojo: el slug de catalogo de secretos
    # sigue siendo "vault" (legado historico), no "secretos".
    servicio_slug_catalago: str
    titulo_topbar: str
    template_stats_propias: str
    # authservice SI gestiona sus propias credenciales M2M, pero solo las
    # de acceso general (sin scope de un servicio especifico) -- nunca
    # mezcladas con las de secretos/sintesis/transcripcion en una misma
    # tabla (decision revertida: antes /metricas mostraba las de toda la
    # organizacion juntas, lo cual permitia gestionar sin querer una key
    # de otro servicio desde el panel equivocado -- ver nota de seguridad
    # del dueño del proyecto). Cada servicio gestiona exclusivamente las
    # suyas en su propio panel.
    api_keys: ConfigApiKeys | None
    nueva_api_key: ConfigNuevaApiKey | None
    documentacion: ConfigDocumentacion | None
    # Partials extra, en orden, exclusivos de este servicio (hoy solo auth:
    # tabla de usuarios + alta de admin). Agregar un bloque nuevo a un
    # servicio (Funcionalidad, salud, cuota, pagos, auditoria, soporte) es
    # sumar una entrada aca, sin tocar el template generico.
    bloques_extra_html: list[str] = field(default_factory=list)
    # Contenido interno de un <script> extra, exclusivo de este servicio
    # (hoy solo auth: crearUsuario/eliminarUsuario). None = no hay.
    template_scripts_extra: str | None = None
    # Los siguientes 3 son None en auth (no llama a obtener_metricas_servicio).
    metricas_servicio_nombre: str | None = None   # "secretos"/"sintesis"/"transcripcion"
    metricas_scope: str | None = None             # "secretos:leer"/etc.
    metricas_context_key: str | None = None       # "metricas_secretos"/etc.


# Solo 2 opciones: coinciden 1 a 1 con el unico modelo de permisos real que
# existe hoy (secretos.empleados.permiso in {leer, escribir}). Antes habia
# una 3ra opcion "Acceso completo (por defecto)" que en la practica
# duplicaba "escribir" (acceso total sin restriccion) -- redundante y
# confuso, se saca.
_OPCIONES_SCOPE_SECRETOS = [
    ("secretos:leer", "Solo lectura"),
    ("secretos:escribir", "Lectura y escritura"),
]

CONFIG_SERVICIOS: dict[str, ConfigServicio] = {
    "auth": ConfigServicio(
        es_auth=True,
        servicio_slug_catalago="auth",
        titulo_topbar="Authservise",
        template_stats_propias="bloques/stats_auth.html",
        bloques_extra_html=["bloques/tabla_usuarios.html", "bloques/alta_admin.html"],
        template_scripts_extra="bloques/usuarios_admins.js.html",
        api_keys=ConfigApiKeys(filtro_servicio=None, filtro_sin_servicio=True, nombre_display=None),
        # Sin modelo de roles propio (no hay "empleados" de authservice) --
        # unica opcion "acceso completo", sin scope de ningun servicio.
        nueva_api_key=ConfigNuevaApiKey(nombre_display=None, opciones_scope=[
            ("", _LABEL_ACCESO_COMPLETO),
        ]),
        documentacion=ConfigDocumentacion(variante="larga", servicio_codigo="authservise"),
    ),
    "secretos": ConfigServicio(
        es_auth=False,
        servicio_slug_catalago="vault",  # legado: el slug de catalogo sigue siendo "vault"
        titulo_topbar="Secretos",
        template_stats_propias="bloques/stats_secretos.html",
        metricas_servicio_nombre="secretos", metricas_scope="secretos:leer",
        metricas_context_key="metricas_secretos",
        api_keys=ConfigApiKeys(filtro_servicio="secretos", filtro_sin_servicio=False, nombre_display="Secretos"),
        # Unico servicio con modelo de roles real hoy (empleados con
        # permiso leer/escribir) -- por eso es el unico que conserva el
        # select. El resto no tiene con que justificar la eleccion.
        nueva_api_key=ConfigNuevaApiKey(nombre_display="Secretos", opciones_scope=_OPCIONES_SCOPE_SECRETOS),
        documentacion=ConfigDocumentacion(variante="corta", servicio_codigo="secretos"),
    ),
    "sintesis": ConfigServicio(
        es_auth=False,
        servicio_slug_catalago="sintesis",
        titulo_topbar=_NOMBRE_SINTESIS,
        template_stats_propias="bloques/stats_sintesis.html",
        metricas_servicio_nombre="sintesis", metricas_scope="sintesis:leer",
        metricas_context_key="metricas_sintesis",
        api_keys=ConfigApiKeys(filtro_servicio="sintesis", filtro_sin_servicio=False, nombre_display=_NOMBRE_SINTESIS),
        # Sintesis no tiene modelo de roles/permisos por usuario (no hay
        # "empleados" como en secretos) -- un select de leer/escribir no
        # protege nada real, se saca y la key se crea siempre con acceso
        # completo, sin preguntarle nada al usuario.
        nueva_api_key=ConfigNuevaApiKey(nombre_display=_NOMBRE_SINTESIS, opciones_scope=[
            ("sintesis:escribir", _LABEL_ACCESO_COMPLETO),
        ]),
        documentacion=ConfigDocumentacion(variante="corta", servicio_codigo="sintesis"),
    ),
    "transcripcion": ConfigServicio(
        es_auth=False,
        servicio_slug_catalago="transcripcion",
        titulo_topbar=_NOMBRE_TRANSCRIPCION,
        template_stats_propias="bloques/stats_transcripcion.html",
        metricas_servicio_nombre="transcripcion", metricas_scope="transcripcion:leer",
        metricas_context_key="metricas_transcripcion",
        api_keys=ConfigApiKeys(filtro_servicio="transcripcion", filtro_sin_servicio=False, nombre_display=_NOMBRE_TRANSCRIPCION),
        # Mismo caso que sintesis: sin modelo de roles/permisos, sin select.
        nueva_api_key=ConfigNuevaApiKey(nombre_display=_NOMBRE_TRANSCRIPCION, opciones_scope=[
            ("transcripcion:escribir", _LABEL_ACCESO_COMPLETO),
        ]),
        documentacion=ConfigDocumentacion(variante="corta", servicio_codigo="transcripcion"),
    ),
}
