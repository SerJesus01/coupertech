"""CouperTech Portal - Frontend unificado de la plataforma"""

import asyncio
import os
import time
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

from metricas_config import CONFIG_SERVICIOS, ConfigServicio

load_dotenv()

# Sin default hardcodeado (misma regla que PG_PASS en authservise): las
# URLs de authservice/catalago vienen de Vault (secret/urls) via el deploy
# -- si el host o el puerto cambian, se actualiza en un solo lugar.
AUTH_URL = os.getenv("AUTH_SERVICE_URL", "")
# couper/gestor-apikeys: unico servicio que genera/gestiona credenciales
# M2M de la plataforma (extraido de authservise el 08/jul/2026) -- todo lo
# que antes era /oauth/* contra AUTH_URL ahora va aca. AUTH_URL se sigue
# usando para login/sesion/usuario final, sin cambios.
GESTOR_APIKEYS_URL = os.getenv("GESTOR_APIKEYS_URL", "")
# couper/catalago: catalogo de servicios (nombre/descripcion/icono), de
# solo lectura -- el portal ya no tiene credenciales de Postgres propias
# (ver get_user_servicios: todo lo que antes era SQL directo a
# metrics_vault_db ahora sale de authservice + catalago via HTTP).
CATALAGO_URL = os.getenv("CATALAGO_URL", "")
# Coincide con GENERIC_SESSION_TTL en authservice (4h) -- antes quedaba en
# 1h por defecto mientras la sesion real duraba 4h, forzando un re-login
# prematuro (hallazgo de auditoria B2, 06/jul/2026).
SESSION_TTL = int(os.getenv("SESSION_TTL", str(4 * 60 * 60)))
# HTTPS real (Cloudflare Tunnel, etc.) debe setear esto en true -- en LAN
# plana (hoy) la cookie no puede exigir Secure o el navegador la descarta.
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"

# Slug con el que este portal se identifica ante el login GENERICO de
# authservice (POST /auth/login, mismo mecanismo que usa pronunciation-scorer
# con servicio="score"). El HTML de login es un template GENERICO (pensado
# para poder reusarse en otros puntos de entrada de CouperTech), asi que el
# slug no va hardcodeado en el <script> -- se inyecta aqui como config y el
# JS lo manda tal cual en el body del POST.
SERVICIO_SLUG = os.getenv("SERVICIO_SLUG", "portal")

# Site key de Cloudflare Turnstile (publica, va al HTML). La secret key
# vive solo en authservice (Vault secret/authservice), nunca aqui.
TURNSTILE_SITE_KEY = os.getenv("TURNSTILE_SITE_KEY", "")

# SSO best-effort hacia pronunciation-scorer (ingles.coupertech.com): al
# loguearse aca, se pide TAMBIEN un JWT con servicio="score" (misma
# password que ya se recibio en este request) y se guarda con
# Domain=.coupertech.com -- el navegador la manda sola cuando el usuario
# navega a cualquier subdominio de coupertech.com, y pronunciation-scorer
# la valida con su MISMA cookie ps_session, sin tocar su codigo (decision
# Sergio, 07/jul/2026). Vacio (default local/dev): no se fija Domain, la
# cookie queda scopeada solo a este host, como cualquier cookie normal.
SSO_COOKIE_DOMAIN = os.getenv("SSO_COOKIE_DOMAIN", "")
SCORE_SSO_COOKIE_NAME = "ps_session"

# couper/secretos: servicio de gestion de secretos (wrapper sobre Vault),
# expone metricas via M2M (Bearer), nunca via session_uuid.
SECRETOS_URL = os.getenv("SECRETOS_URL", "")
# couper/transcripcion (Whisper STT) y couper/sintesis (Kokoro TTS):
# mismo patron M2M que secretos, metricas minimas (contador de
# minutos/palabras, ver commit del 08/jul/2026).
TRANSCRIPCION_URL = os.getenv("TRANSCRIPCION_URL", "")
SINTESIS_URL = os.getenv("SINTESIS_URL", "")
# Vault propio del portal, permisos acotados SOLO a
# secret/coupertech-portal-tokens/* (ver docs/DECISIONES o commit del
# 08/jul/2026) -- usado para guardar/reusar la credencial M2M de
# "metricas de {servicio}" por organizacion, sin pedirle al usuario que
# pegue un token cada vez que visita el panel.
VAULT_ADDR = os.getenv("VAULT_ADDR", "")
VAULT_TOKEN = os.getenv("VAULT_TOKEN", "")

app = FastAPI(title="CouperTech Portal")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

_MSG_NO_AUTENTICADO = "No autenticado."
_MSG_NO_AUTORIZADO = "No autorizado"
_MSG_SESION_INVALIDA = "Sesión inválida."
_MSG_AUTH_NO_DISPONIBLE = "Servicio de autenticación no disponible"
_URL_DASHBOARD = "/dashboard"

# ─── Helpers ───

async def verify_session(session_uuid: str) -> dict | None:
    """Verifica sesion contra authservise. Retorna payload o None."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{AUTH_URL}/auth/session/{session_uuid}")
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "active":
                    return data
    except httpx.HTTPError:
        pass
    return None


# --- Metricas de servicios M2M (secretos, transcripcion, sintesis): el
# panel resuelve cliente_id + rol admin via session_uuid (igual que el
# resto de /metricas), pero estos servicios SOLO aceptan Bearer M2M --
# nunca session_uuid. En vez de pedirle al usuario que pegue un token
# cada vez, el portal aprovisiona (una sola vez por (servicio,
# cliente_id), la primera vez que un admin visita el panel) una
# credencial M2M propia con el scope indicado, y guarda su client_secret
# en Vault (secret/coupertech-portal-tokens/{servicio}/{cliente_id}) para
# reusarla despues -- nunca en memoria del portal ni en el navegador. El
# token M2M en si (de corta vida, 1h) SI se cachea en memoria del
# proceso, para no pedir uno nuevo en cada request.
_TOKENS_METRICAS_CACHE: dict[tuple[str, int], tuple[str, float]] = {}  # (servicio, cliente_id) -> (token, expira_epoch)

async def _vault_get_secret(path: str) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{VAULT_ADDR}/v1/secret/data/{path}", headers={"X-Vault-Token": VAULT_TOKEN},
            )
            if resp.status_code == 200:
                return resp.json()["data"]["data"]
    except httpx.HTTPError:
        pass
    return None

async def _vault_put_secret(path: str, data: dict) -> None:
    async with httpx.AsyncClient(timeout=5.0) as client:
        await client.post(
            f"{VAULT_ADDR}/v1/secret/data/{path}",
            headers={"X-Vault-Token": VAULT_TOKEN},
            json={"data": data},
        )

async def _obtener_o_crear_credencial_metricas(servicio: str, scope: str, cliente_id: int, session_uuid: str) -> tuple[str, str] | None:
    """(client_id, client_secret) de la app 'portal-metricas-{servicio}'
    de este cliente -- la crea si es la primera vez, con el scope indicado.

    gestor-apikeys exige `servicio` (mismo valor que el parametro de esta
    funcion, coincide 1 a 1 con su enum) y una vigencia obligatoria al
    crear -- 90 dias es la mas larga disponible (no existe "sin
    vencimiento" para credenciales nuevas). Esta credencial se cachea
    indefinidamente en Vault sin volver a validar que siga vigente, asi
    que pasados esos 90 dias el panel de metricas de este servicio se
    queda sin datos silenciosamente (obtener_metricas_servicio ya esta
    pensado para no romper el panel si esto falla) hasta que alguien
    borre el secret de Vault a mano para forzar una re-provision. Pendiente
    de una re-provision automatica antes de expirar (fuera de alcance de
    este fix)."""
    vault_path = f"coupertech-portal-tokens/{servicio}/{cliente_id}"
    existente = await _vault_get_secret(vault_path)
    if existente:
        return existente["client_id"], existente["client_secret"]

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{GESTOR_APIKEYS_URL}/oauth/aplicaciones",
                headers={"X-Session-UUID": session_uuid},
                json={
                    "nombre": f"portal-metricas-{servicio}", "servicio": servicio,
                    "scopes": [scope], "vigencia_dias": 90,
                },
            )
    except httpx.HTTPError:
        return None
    if resp.status_code != 201:
        return None

    creada = resp.json()
    await _vault_put_secret(
        vault_path,
        {"client_id": creada["client_id"], "client_secret": creada["client_secret"]},
    )
    return creada["client_id"], creada["client_secret"]

async def _obtener_token_m2m(servicio: str, scope: str, cliente_id: int, session_uuid: str) -> str | None:
    clave = (servicio, cliente_id)
    cacheado = _TOKENS_METRICAS_CACHE.get(clave)
    if cacheado and cacheado[1] > time.time():
        return cacheado[0]

    credencial = await _obtener_o_crear_credencial_metricas(servicio, scope, cliente_id, session_uuid)
    if credencial is None:
        return None
    client_id, client_secret = credencial

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{GESTOR_APIKEYS_URL}/oauth/token",
                auth=(client_id, client_secret),
                data={"grant_type": "client_credentials"},
            )
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None

    body = resp.json()
    token = body["access_token"]
    # Renueva 60s antes de que expire de verdad, margen de seguridad.
    _TOKENS_METRICAS_CACHE[clave] = (token, time.time() + body["expires_in"] - 60)
    return token

async def _resolver_sesion_y_cliente(request: Request):
    """Comun a /metricas y /metricas-secretos: resuelve session_uuid ->
    payload -> cliente_id via /auth/mi-cliente. Devuelve
    (session_uuid, payload, cliente, cliente_id, None) en el camino
    feliz, o (None, None, None, None, respuesta) si hay que cortar ahi
    -- el caller debe `return` ese 5to elemento si no es None."""
    session_uuid = request.cookies.get("session_uuid")
    if not session_uuid:
        return None, None, None, None, RedirectResponse(url="/")

    payload = await verify_session(session_uuid)
    if not payload:
        resp = RedirectResponse(url="/")
        resp.delete_cookie("session_uuid")
        return None, None, None, None, resp

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            mi_cliente_resp = await client.get(
                f"{AUTH_URL}/auth/mi-cliente", headers={"X-Session-UUID": session_uuid}
            )
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail=_MSG_AUTH_NO_DISPONIBLE)

    if mi_cliente_resp.status_code != 200:
        return None, None, None, None, RedirectResponse(url=_URL_DASHBOARD)
    cliente = mi_cliente_resp.json()
    return session_uuid, payload, cliente, cliente["cliente_id"], None

async def obtener_metricas_servicio(servicio_url: str, servicio: str, scope: str, cliente_id: int, session_uuid: str) -> dict | None:
    """None si servicio_url no esta configurada (deploys que no usan
    este servicio todavia) o si algo falla -- el panel debe seguir
    funcionando sin esta seccion, nunca 500 por esto."""
    if not servicio_url or not VAULT_ADDR or not VAULT_TOKEN:
        return None
    token = await _obtener_token_m2m(servicio, scope, cliente_id, session_uuid)
    if token is None:
        return None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{servicio_url}/metricas", headers={"Authorization": f"Bearer {token}"})
            if resp.status_code == 200:
                return resp.json()
    except httpx.HTTPError:
        pass
    return None

async def _fetch_datos_panel(config: ConfigServicio, cliente_id: int, session_uuid: str):
    """Dispara las llamadas HTTP de /metricas* (auth pide 4, el resto de
    servicios pide 3) -- separado de _render_panel_metricas para bajar su
    complejidad cognitiva (python:S3776)."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            if config.es_auth:
                return await asyncio.gather(
                    client.get(f"{AUTH_URL}/auth/clientes/{cliente_id}/metricas",
                               headers={"X-Session-UUID": session_uuid}),
                    client.get(f"{AUTH_URL}/auth/clientes/{cliente_id}/usuarios",
                               headers={"X-Session-UUID": session_uuid}),
                    client.get(f"{CATALAGO_URL}/suscripcion-activa",
                               params={"cliente_id": cliente_id, "servicio_slug": config.servicio_slug_catalago}),
                    client.get(f"{GESTOR_APIKEYS_URL}/oauth/reporte",
                               headers={"X-Session-UUID": session_uuid}),
                )
            return await asyncio.gather(
                client.get(f"{AUTH_URL}/auth/clientes/{cliente_id}/metricas",
                           headers={"X-Session-UUID": session_uuid}),
                client.get(f"{CATALAGO_URL}/suscripcion-activa",
                           params={"cliente_id": cliente_id, "servicio_slug": config.servicio_slug_catalago}),
                client.get(f"{GESTOR_APIKEYS_URL}/oauth/reporte",
                           headers={"X-Session-UUID": session_uuid}),
            )
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail=_MSG_AUTH_NO_DISPONIBLE)

async def _obtener_respuestas_panel(config: ConfigServicio, cliente_id: int, session_uuid: str):
    """Fetch + valida las respuestas de /metricas*. None si hay que
    redirigir a dashboard (autorizacion insuficiente); si no, la tupla
    (metricas_resp, usuarios_resp, suscripcion_resp, aplicaciones_resp)
    -- metricas_resp/usuarios_resp quedan en None fuera de auth, ver
    _render_panel_metricas. Separado para bajar su complejidad cognitiva
    (python:S3776)."""
    respuestas = await _fetch_datos_panel(config, cliente_id, session_uuid)
    if config.es_auth:
        metricas_resp, usuarios_resp, suscripcion_resp, aplicaciones_resp = respuestas
        if metricas_resp.status_code != 200 or usuarios_resp.status_code != 200:
            return None
        return metricas_resp, usuarios_resp, suscripcion_resp, aplicaciones_resp
    admin_check_resp, suscripcion_resp, aplicaciones_resp = respuestas
    if admin_check_resp.status_code != 200:
        return None
    return None, None, suscripcion_resp, aplicaciones_resp

def _filtrar_aplicaciones(config: ConfigServicio, todas_aplicaciones: list) -> list | None:
    """None si esta pantalla no muestra API Keys; si no, ya filtradas por
    servicio (ver ConfigApiKeys.filtro_sin_servicio)."""
    if not config.api_keys:
        return None
    if config.api_keys.filtro_sin_servicio:
        return [a for a in todas_aplicaciones if not a.get("servicio")]
    return [a for a in todas_aplicaciones if a.get("servicio") == config.api_keys.filtro_servicio]

async def _render_panel_metricas(request: Request, config: ConfigServicio, metricas_url: str | None = None):
    """Renderiza cualquiera de las 4 pantallas de /metricas* segun `config`
    (ver metricas_config.py) -- reemplaza los 4 endpoints casi duplicados
    que existian antes de la modularizacion en bloques. `config.es_auth`
    sigue una rama propia porque auth no encaja en el mismo shape que los
    otros 3 (llama a /auth/.../usuarios). authservice SI gestiona API
    Keys, pero solo las de acceso general (sin scope de un servicio
    especifico) -- cada servicio administra exclusivamente las suyas,
    nunca mezcladas en una misma tabla (ver ConfigApiKeys.filtro_sin_servicio)."""
    session_uuid, payload, cliente, cliente_id, early = await _resolver_sesion_y_cliente(request)
    if early:
        return early

    resultado = await _obtener_respuestas_panel(config, cliente_id, session_uuid)
    if resultado is None:
        return RedirectResponse(url=_URL_DASHBOARD)
    metricas_resp, usuarios_resp, suscripcion_resp, aplicaciones_resp = resultado

    suscripcion = suscripcion_resp.json() if suscripcion_resp.status_code == 200 else {"suscrito": False}
    todas_aplicaciones = aplicaciones_resp.json().get("credenciales", []) if aplicaciones_resp.status_code == 200 else []

    contexto = {
        "request": request, "user": payload, "cliente": cliente,
        "suscripcion": suscripcion, "config": config,
    }

    aplicaciones_filtradas = _filtrar_aplicaciones(config, todas_aplicaciones)
    if aplicaciones_filtradas is not None:
        contexto["aplicaciones"] = aplicaciones_filtradas

    if config.es_auth:
        contexto["metricas"] = metricas_resp.json()
        contexto["usuarios"] = usuarios_resp.json().get("usuarios", [])
    else:
        contexto[config.metricas_context_key] = await obtener_metricas_servicio(
            metricas_url, config.metricas_servicio_nombre, config.metricas_scope, cliente_id, session_uuid)

    return templates.TemplateResponse("metricas_generico.html", contexto)

async def _servicios_con_estado(identidad_id: int) -> tuple[set, list]:
    """Combina la suscripcion real (catalago: GET /mis-suscripciones/{id},
    la fuente de verdad de "esta suscrito" -- NO authservice.usuario_servicios,
    que es otro concepto: asignacion manual de plataforma, no suscripcion
    pagada) con la metadata de catalogo (GET /servicios). Devuelve (ids
    asignados, catalogo completo con flag "registrado" por servicio)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            asignados_resp, catalogo_resp = await asyncio.gather(
                client.get(f"{CATALAGO_URL}/mis-suscripciones/{identidad_id}"),
                client.get(f"{CATALAGO_URL}/servicios"),
            )
    except httpx.HTTPError as e:
        print(f"Error consultando servicios: {e}")
        return set(), []

    if asignados_resp.status_code != 200 or catalogo_resp.status_code != 200:
        return set(), []

    asignados = set(asignados_resp.json().get("servicios_ids", []))
    catalogo = catalogo_resp.json()

    con_estado = [{**svc, "registrado": svc["id"] in asignados} for svc in catalogo]
    return asignados, con_estado


async def get_user_servicios(identidad_id: int) -> list:
    """Servicios contratados/pendientes de la identidad (sidebar)."""
    asignados_ids, con_estado = await _servicios_con_estado(identidad_id)
    return [svc for svc in con_estado if svc["id"] in asignados_ids]


async def get_todos_servicios_con_estado(identidad_id: int) -> list:
    """Catalogo completo (para las tarjetas de servicio del dashboard),
    marcando cuales ya tiene registrados la identidad de la sesion."""
    _, con_estado = await _servicios_con_estado(identidad_id)
    return con_estado


async def fetch_planes_servicio(slug: str) -> dict:
    """Llama a couper/catalago para obtener los planes de un servicio."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{CATALAGO_URL}/planes/{slug}")
            if resp.status_code == 200:
                return resp.json()
    except httpx.HTTPError as e:
        print(f"Error consultando planes en catalago: {e}")
    return {"servicio": None, "planes": []}


async def _intentar_sso_score(email: str, password: str, respuesta: JSONResponse) -> None:
    """Best-effort: si falla (score inactivo, credenciales no validas para
    ESE servicio en particular, etc.) no debe romper el login del portal --
    el usuario ya quedo logueado en el portal igual, simplemente no se
    beneficia del SSO hacia score esta vez (tendria que loguearse ahi
    directo, como hoy)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{AUTH_URL}/auth/login", json={
                "email": email, "password": password, "servicio": "score",
            })
        if resp.status_code != 200:
            return
        jwt = resp.json().get("jwt")
        if not jwt:
            return
        respuesta.set_cookie(
            SCORE_SSO_COOKIE_NAME, jwt, max_age=SESSION_TTL, httponly=True,
            secure=SESSION_COOKIE_SECURE, samesite="lax",
            domain=SSO_COOKIE_DOMAIN or None,
        )
    except httpx.HTTPError as e:
        print(f"SSO hacia score no disponible (no bloqueante): {e}")


# ─── Routes ───

@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    """Landing page con login."""
    session_uuid = request.cookies.get("session_uuid")
    if session_uuid:
        payload = await verify_session(session_uuid)
        if payload:
            return RedirectResponse(url=_URL_DASHBOARD)
    return templates.TemplateResponse("login.html", {
        "request": request,
        "servicio_slug": SERVICIO_SLUG,
        "turnstile_site_key": TURNSTILE_SITE_KEY,
    })

@app.get("/registro", response_class=HTMLResponse)
async def registro_page(request: Request):
    """Alta de usuario -- registro.html pega directo a authservice
    (AUTH_SERVICE_PUBLIC_URL/auth/registro), no pasa por este backend."""
    return templates.TemplateResponse("registro.html", {
        "request": request,
        "turnstile_site_key": TURNSTILE_SITE_KEY,
    })

@app.get("/alta-cliente", response_class=HTMLResponse)
async def alta_cliente_page(request: Request):
    """Alta de cliente (organizacion/tenant) -- alta_cliente.html pega
    directo a authservice (AUTH_SERVICE_PUBLIC_URL/auth/clientes), no pasa
    por este backend."""
    return templates.TemplateResponse("alta_cliente.html", {
        "request": request,
        "turnstile_site_key": TURNSTILE_SITE_KEY,
    })

@app.get("/olvide-password", response_class=HTMLResponse)
async def olvide_password_page(request: Request):
    """Recuperacion de contraseña -- olvide_password.html pega directo a
    authservice (AUTH_SERVICE_PUBLIC_URL/auth/forgot-password y
    /auth/reset-password), no pasa por este backend (mismo patron que
    registro.html/alta_cliente.html: son operaciones anonimas, sin cookie
    de sesion, no requieren proxy)."""
    return templates.TemplateResponse("olvide_password.html", {"request": request})

@app.get(
    "/planes/{slug}", response_class=HTMLResponse,
    responses={404: {"description": "Servicio no encontrado"}},
)
async def planes_servicio(request: Request, slug: str):
    """Tarjetas de planes de un servicio, para usuarios no registrados."""
    data = await fetch_planes_servicio(slug)
    if not data.get("servicio"):
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    return templates.TemplateResponse("tarjetas.html", {
        "request": request,
        "servicio": data["servicio"],
        "planes": data["planes"],
    })

@app.get(
    "/suscribirse", response_class=HTMLResponse,
    responses={404: {"description": "Servicio o plan no encontrado"}},
)
async def suscribirse_page(request: Request, servicio: str, plan: int):
    """Pagina de confirmacion de suscripcion -- para identidades YA
    logueadas (no es un alta de cuenta nueva, ver POST /api/suscribirse).
    Si no hay sesion, se manda a loguearse, no a registrarse de nuevo."""
    session_uuid = request.cookies.get("session_uuid")
    if not session_uuid:
        return RedirectResponse(url="/")

    payload = await verify_session(session_uuid)
    if not payload:
        resp = RedirectResponse(url="/")
        resp.delete_cookie("session_uuid")
        return resp

    data = await fetch_planes_servicio(servicio)
    plan_elegido = next((p for p in data.get("planes", []) if p["id"] == plan), None)
    if not data.get("servicio") or not plan_elegido:
        raise HTTPException(status_code=404, detail="Servicio o plan no encontrado")

    return templates.TemplateResponse("suscribirse.html", {
        "request": request,
        "servicio": data["servicio"],
        "plan": plan_elegido,
    })

@app.post("/api/suscribirse")
async def api_suscribirse(request: Request):
    """Registra la suscripcion (POST /suscripciones en catalago, gestor de
    pago dummy -- no cobra nada real todavia). Resuelve el cliente_id de
    la identidad logueada via GET /auth/mi-cliente (se auto-crea una
    organizacion de un solo usuario si todavia no pertenece a ninguna)."""
    session_uuid = request.cookies.get("session_uuid")
    if not session_uuid:
        return JSONResponse({"error": _MSG_NO_AUTENTICADO}, status_code=401)

    payload = await verify_session(session_uuid)
    if not payload:
        return JSONResponse({"error": _MSG_SESION_INVALIDA}, status_code=401)

    body = await request.json()
    servicio_slug = body.get("servicio_slug", "")
    plan_id = body.get("plan_id")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            mi_cliente_resp = await client.get(
                f"{AUTH_URL}/auth/mi-cliente", headers={"X-Session-UUID": session_uuid}
            )
    except httpx.HTTPError:
        return JSONResponse({"error": "No se pudo conectar con el servicio de autenticación."}, status_code=503)

    if mi_cliente_resp.status_code != 200:
        return JSONResponse({"error": _MSG_SESION_INVALIDA}, status_code=401)
    cliente_id = mi_cliente_resp.json()["cliente_id"]

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            sub_resp = await client.post(
                f"{CATALAGO_URL}/suscripciones",
                json={
                    "cliente_id": cliente_id, "servicio_slug": servicio_slug, "plan_id": plan_id,
                    "identidad_id": payload["user_id"],
                },
            )
    except httpx.HTTPError:
        return JSONResponse({"error": "No se pudo conectar con el servicio de catálogo."}, status_code=503)

    if sub_resp.status_code != 201:
        detail = sub_resp.json().get("detail", "No se pudo completar la suscripción.")
        return JSONResponse({"error": detail}, status_code=sub_resp.status_code)

    return JSONResponse(sub_resp.json(), status_code=201)

@app.post("/api/login")
async def api_login(request: Request):
    """Login via el login GENERICO de authservise (identidades).

    La cookie de sesion se fija ACA, server-side, con httponly=True -- antes
    el JSON devolvia el session_uuid y login.html lo escribia con
    `document.cookie` desde JS, lo que la dejaba legible (y robable via XSS)
    para cualquier script en la pagina (hallazgo de auditoria A1,
    06/jul/2026). El JSON de respuesta ya no expone el session_uuid."""
    data = await request.json()
    email = (data.get("email") or "").strip()
    password = data.get("password", "")
    servicio = data.get("servicio") or SERVICIO_SLUG
    turnstile_token = data.get("turnstile_token")

    if not email or not password:
        return JSONResponse({"error": "Correo y contraseña requeridos"}, status_code=400)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{AUTH_URL}/auth/login", json={
                "email": email,
                "password": password,
                "servicio": servicio,
                "turnstile_token": turnstile_token,
            })
            if resp.status_code == 200:
                result = resp.json()
                if result.get("status") == "success":
                    respuesta = JSONResponse({
                        "status": "ok",
                        "user": {
                            "id": result.get("user_id"),
                            "email": result.get("email", email),
                            "nombre": result.get("nombre"),
                            "servicio": result.get("servicio"),
                        }
                    })
                    respuesta.set_cookie(
                        "session_uuid",
                        result["session_uuid"],
                        max_age=SESSION_TTL,
                        httponly=True,
                        secure=SESSION_COOKIE_SECURE,
                        samesite="lax",
                    )
                    if servicio != "score":
                        await _intentar_sso_score(email, password, respuesta)
                    return respuesta
            # Mensaje generico: no se reenvia el detail de authservise tal
            # cual (podia distinguir cuenta inexistente/desactivada/bloqueada
            # -- oraculo de enumeracion, hallazgo de auditoria A2/M1).
            return JSONResponse({"error": "Correo o contraseña incorrectos"}, status_code=401)
    except httpx.ConnectError:
        return JSONResponse({"error": _MSG_AUTH_NO_DISPONIBLE}, status_code=503)

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Dashboard principal con sidebar de servicios."""
    session_uuid = request.cookies.get("session_uuid")
    if not session_uuid:
        return RedirectResponse(url="/")

    payload = await verify_session(session_uuid)
    if not payload:
        resp = RedirectResponse(url="/")
        resp.delete_cookie("session_uuid")
        return resp

    asignados_ids, todos_servicios = await _servicios_con_estado(payload["user_id"])
    servicios = [svc for svc in todos_servicios if svc["id"] in asignados_ids]

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": payload,
        "servicios": servicios,        # sidebar: solo los de la identidad
        "todos_servicios": todos_servicios,  # tarjetas: catalogo completo
    })

@app.get(
    "/metricas", response_class=HTMLResponse,
    responses={503: {"description": "Servicio de autenticación no disponible"}},
)
async def metricas_page(request: Request):
    """Panel de metricas del cliente (organizacion): sesiones activas,
    usuarios con su ultima actividad, alta/baja de usuarios. Reusa la
    MISMA sesion generica del dashboard (no hay un login separado para
    esto) -- la autorizacion real la hace authservice via
    cliente_usuarios.es_admin, aca solo se resuelve el cliente_id.

    Gestiona API Keys (aplicaciones de terceros), pero SOLO las de acceso
    general (sin scope de un servicio especifico, filtro_sin_servicio=True
    en ConfigApiKeys) -- ya no muestra el reporte cruzado de las keys de
    secretos/sintesis/transcripcion que tenia antes: permitia gestionar
    (rotar, desactivar, eliminar) sin querer la credencial de un servicio
    ajeno desde el panel equivocado. Cada servicio gestiona exclusivamente
    las suyas en su propio panel. Esto revierte la decision anterior de
    unificarlas todas en /metricas (Sergio, 08/jul/2026) tras detectarse
    el riesgo de mezclar credenciales de distintos servicios en una sola
    vista/tabla."""
    return await _render_panel_metricas(request, CONFIG_SERVICIOS["auth"])


@app.get(
    "/metricas-secretos", response_class=HTMLResponse,
    responses={503: {"description": "Servicio de autenticación no disponible"}},
)
async def metricas_secretos_page(request: Request):
    """Panel de metricas de couper/secretos: secretos guardados,
    versiones, llamadas a la API, y su facturacion -- deliberadamente
    SEPARADO de /metricas (Autenticacion CouperTech), son productos
    distintos que solo comparten el mismo login/sesion. Las API Keys
    (aplicaciones de terceros) NO viven aca: son un concepto de
    autenticacion de la organizacion, se gestionan desde /metricas
    (decision Sergio, 08/jul/2026 -- revertido tras mezclar ambos
    conceptos en el primer intento de separacion)."""
    return await _render_panel_metricas(request, CONFIG_SERVICIOS["secretos"], metricas_url=SECRETOS_URL)


@app.get(
    "/metricas-transcripcion", response_class=HTMLResponse,
    responses={503: {"description": "Servicio de autenticación no disponible"}},
)
async def metricas_transcripcion_page(request: Request):
    """Panel de metricas de couper/transcripcion (Whisper STT): solo
    minutos procesados + facturacion -- mismo criterio que
    /metricas-secretos, las API Keys se gestionan desde /metricas."""
    return await _render_panel_metricas(request, CONFIG_SERVICIOS["transcripcion"], metricas_url=TRANSCRIPCION_URL)


@app.get(
    "/metricas-sintesis", response_class=HTMLResponse,
    responses={503: {"description": "Servicio de autenticación no disponible"}},
)
async def metricas_sintesis_page(request: Request):
    """Panel de metricas de couper/sintesis (Kokoro TTS): solo palabras
    procesadas + facturacion -- mismo criterio que /metricas-secretos,
    las API Keys se gestionan desde /metricas."""
    return await _render_panel_metricas(request, CONFIG_SERVICIOS["sintesis"], metricas_url=SINTESIS_URL)


@app.post("/api/aplicaciones")
async def api_crear_aplicacion(request: Request):
    """Alta de una credencial M2M (POST /oauth/aplicaciones en authservise).
    El client_secret que devuelve se muestra una sola vez -- no se persiste
    en ningun lado de este portal, solo se reenvia tal cual al navegador."""
    session_uuid = request.cookies.get("session_uuid")
    if not session_uuid:
        return JSONResponse({"error": _MSG_NO_AUTENTICADO}, status_code=401)

    body = await request.json()
    # servicio, scopes y vigencia vienen del frontend (nueva_api_key.html,
    # ya fijados por config del panel, no elegidos libremente salvo la
    # vigencia) -- gestor-apikeys es quien valida todo esto en serio del
    # lado del servidor (enum de servicio, scopes contra su allowlist,
    # vigencia obligatoria); este portal solo reenvia.
    payload = {
        "nombre": body.get("nombre", ""),
        "servicio": body.get("servicio", "acceso-general"),
    }
    if body.get("scopes"):
        payload["scopes"] = body["scopes"]
    if body.get("uso_unico"):
        payload["uso_unico"] = True
    elif body.get("vigencia_dias"):
        payload["vigencia_dias"] = body["vigencia_dias"]
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{GESTOR_APIKEYS_URL}/oauth/aplicaciones",
                headers={"X-Session-UUID": session_uuid},
                json=payload,
            )
    except httpx.HTTPError:
        return JSONResponse({"error": _MSG_AUTH_NO_DISPONIBLE}, status_code=503)

    if resp.status_code != 201:
        detail = resp.json().get("detail", resp.json().get("message", "No se pudo crear la aplicación."))
        return JSONResponse({"error": detail}, status_code=resp.status_code)
    return JSONResponse(resp.json(), status_code=201)

@app.post("/api/aplicaciones/{client_id}/rotar-secreto")
async def api_rotar_secreto_aplicacion(request: Request, client_id: str):
    session_uuid = request.cookies.get("session_uuid")
    if not session_uuid:
        return JSONResponse({"error": _MSG_NO_AUTENTICADO}, status_code=401)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{GESTOR_APIKEYS_URL}/oauth/aplicaciones/{client_id}/rotar-secreto",
                headers={"X-Session-UUID": session_uuid},
            )
    except httpx.HTTPError:
        return JSONResponse({"error": _MSG_AUTH_NO_DISPONIBLE}, status_code=503)

    if resp.status_code != 200:
        detail = resp.json().get("detail", "No se pudo rotar el secreto.")
        return JSONResponse({"error": detail}, status_code=resp.status_code)
    return JSONResponse(resp.json(), status_code=200)

@app.post("/api/aplicaciones/{client_id}/desactivar")
async def api_desactivar_aplicacion(request: Request, client_id: str):
    session_uuid = request.cookies.get("session_uuid")
    if not session_uuid:
        return JSONResponse({"error": _MSG_NO_AUTENTICADO}, status_code=401)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{GESTOR_APIKEYS_URL}/oauth/aplicaciones/{client_id}/desactivar",
                headers={"X-Session-UUID": session_uuid},
            )
    except httpx.HTTPError:
        return JSONResponse({"error": _MSG_AUTH_NO_DISPONIBLE}, status_code=503)

    if resp.status_code != 200:
        detail = resp.json().get("detail", "No se pudo desactivar la aplicación.")
        return JSONResponse({"error": detail}, status_code=resp.status_code)
    return JSONResponse(resp.json(), status_code=200)

@app.post("/api/aplicaciones/{client_id}/reactivar")
async def api_reactivar_aplicacion(request: Request, client_id: str):
    session_uuid = request.cookies.get("session_uuid")
    if not session_uuid:
        return JSONResponse({"error": _MSG_NO_AUTENTICADO}, status_code=401)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{GESTOR_APIKEYS_URL}/oauth/aplicaciones/{client_id}/reactivar",
                headers={"X-Session-UUID": session_uuid},
            )
    except httpx.HTTPError:
        return JSONResponse({"error": _MSG_AUTH_NO_DISPONIBLE}, status_code=503)

    if resp.status_code != 200:
        detail = resp.json().get("detail", "No se pudo reactivar la aplicación.")
        return JSONResponse({"error": detail}, status_code=resp.status_code)
    return JSONResponse(resp.json(), status_code=200)

@app.delete("/api/aplicaciones/{client_id}")
async def api_eliminar_aplicacion(request: Request, client_id: str):
    session_uuid = request.cookies.get("session_uuid")
    if not session_uuid:
        return JSONResponse({"error": _MSG_NO_AUTENTICADO}, status_code=401)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.delete(
                f"{GESTOR_APIKEYS_URL}/oauth/aplicaciones/{client_id}",
                headers={"X-Session-UUID": session_uuid},
            )
    except httpx.HTTPError:
        return JSONResponse({"error": _MSG_AUTH_NO_DISPONIBLE}, status_code=503)

    if resp.status_code != 200:
        detail = resp.json().get("detail", "No se pudo eliminar la aplicación.")
        return JSONResponse({"error": detail}, status_code=resp.status_code)
    return JSONResponse(resp.json(), status_code=200)

@app.get("/api/aplicaciones/reporte")
async def api_reporte_aplicaciones(request: Request):
    """Reporte unificado de credenciales M2M por cliente (GET /oauth/reporte
    en couper/gestor-apikeys) -- metadata (nombre, scopes, servicio
    inferido, activo, fechas), nunca numeros de uso: esos se siguen
    consultando por separado a cada servicio consumidor."""
    session_uuid = request.cookies.get("session_uuid")
    if not session_uuid:
        return JSONResponse({"error": _MSG_NO_AUTENTICADO}, status_code=401)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{GESTOR_APIKEYS_URL}/oauth/reporte",
                headers={"X-Session-UUID": session_uuid},
            )
    except httpx.HTTPError:
        return JSONResponse({"error": _MSG_AUTH_NO_DISPONIBLE}, status_code=503)

    if resp.status_code != 200:
        detail = resp.json().get("detail", "No se pudo obtener el reporte de apikeys.")
        return JSONResponse({"error": detail}, status_code=resp.status_code)
    return JSONResponse(resp.json(), status_code=200)

@app.post("/api/metricas/usuarios")
async def api_crear_usuario_cliente(request: Request):
    """Alta de administrador directo en la organizacion (POST
    /auth/clientes/{id}/usuarios) -- este panel es solo para admins (ven
    metricas/usuarios/facturacion de la organizacion). rol se fuerza a
    'admin' del lado del servidor, ignorando lo que mande el cliente: los
    empleados/usuarios normales se dan de alta por el registro general de
    login, no por aca (decision Sergio, 07/jul/2026)."""
    session_uuid = request.cookies.get("session_uuid")
    if not session_uuid:
        return JSONResponse({"error": _MSG_NO_AUTENTICADO}, status_code=401)

    body = await request.json()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            mi_cliente_resp = await client.get(
                f"{AUTH_URL}/auth/mi-cliente", headers={"X-Session-UUID": session_uuid}
            )
            if mi_cliente_resp.status_code != 200:
                return JSONResponse({"error": _MSG_SESION_INVALIDA}, status_code=401)
            cliente_id = mi_cliente_resp.json()["cliente_id"]

            resp = await client.post(
                f"{AUTH_URL}/auth/clientes/{cliente_id}/usuarios",
                headers={"X-Session-UUID": session_uuid},
                json={
                    "email": body.get("email", ""),
                    "password": body.get("password", ""),
                    "nombre": body.get("nombre", ""),
                    "rol": "admin",
                },
            )
    except httpx.HTTPError:
        return JSONResponse({"error": _MSG_AUTH_NO_DISPONIBLE}, status_code=503)

    if resp.status_code != 200:
        detail = resp.json().get("detail", "No se pudo crear el usuario.")
        return JSONResponse({"error": detail}, status_code=resp.status_code)
    return JSONResponse(resp.json(), status_code=200)

@app.delete("/api/metricas/usuarios/{identidad_id}")
async def api_eliminar_usuario_cliente(request: Request, identidad_id: int):
    session_uuid = request.cookies.get("session_uuid")
    if not session_uuid:
        return JSONResponse({"error": _MSG_NO_AUTENTICADO}, status_code=401)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            mi_cliente_resp = await client.get(
                f"{AUTH_URL}/auth/mi-cliente", headers={"X-Session-UUID": session_uuid}
            )
            if mi_cliente_resp.status_code != 200:
                return JSONResponse({"error": _MSG_SESION_INVALIDA}, status_code=401)
            cliente_id = mi_cliente_resp.json()["cliente_id"]

            resp = await client.delete(
                f"{AUTH_URL}/auth/clientes/{cliente_id}/usuarios/{identidad_id}",
                headers={"X-Session-UUID": session_uuid},
            )
    except httpx.HTTPError:
        return JSONResponse({"error": _MSG_AUTH_NO_DISPONIBLE}, status_code=503)

    if resp.status_code != 200:
        detail = resp.json().get("detail", "No se pudo eliminar el usuario.")
        return JSONResponse({"error": detail}, status_code=resp.status_code)
    return JSONResponse(resp.json(), status_code=200)

@app.post("/api/metricas/usuarios/{identidad_id}/resetear-password")
async def api_resetear_password_usuario(request: Request, identidad_id: int):
    session_uuid = request.cookies.get("session_uuid")
    if not session_uuid:
        return JSONResponse({"error": _MSG_NO_AUTENTICADO}, status_code=401)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            mi_cliente_resp = await client.get(
                f"{AUTH_URL}/auth/mi-cliente", headers={"X-Session-UUID": session_uuid}
            )
            if mi_cliente_resp.status_code != 200:
                return JSONResponse({"error": _MSG_SESION_INVALIDA}, status_code=401)
            cliente_id = mi_cliente_resp.json()["cliente_id"]

            resp = await client.post(
                f"{AUTH_URL}/auth/clientes/{cliente_id}/usuarios/{identidad_id}/resetear-password",
                headers={"X-Session-UUID": session_uuid},
            )
    except httpx.HTTPError:
        return JSONResponse({"error": _MSG_AUTH_NO_DISPONIBLE}, status_code=503)

    if resp.status_code != 200:
        detail = resp.json().get("detail", "No se pudo resetear la contraseña.")
        return JSONResponse({"error": detail}, status_code=resp.status_code)
    return JSONResponse(resp.json(), status_code=200)

@app.get("/api/servicios")
async def api_servicios(request: Request):
    """API: servicios del usuario logueado."""
    session_uuid = request.cookies.get("session_uuid")
    if not session_uuid:
        return JSONResponse({"error": _MSG_NO_AUTORIZADO}, status_code=401)

    payload = await verify_session(session_uuid)
    if not payload:
        return JSONResponse({"error": "Sesión inválida"}, status_code=401)

    servicios = await get_user_servicios(payload["user_id"])
    return JSONResponse({"servicios": servicios})

@app.get("/api/verify")
async def api_verify(request: Request):
    """API: verificar sesión activa."""
    session_uuid = request.cookies.get("session_uuid")
    if not session_uuid:
        return JSONResponse({"status": "inactive"}, status_code=401)
    payload = await verify_session(session_uuid)
    if payload:
        return JSONResponse({"status": "active", "user": payload})
    return JSONResponse({"status": "inactive"}, status_code=401)

@app.post("/api/refresh-session")
async def api_refresh_session(request: Request):
    """Extiende el TTL de la sesion activa contra authservise -- sin esto,
    admin_session (TTL 1h en Redis) expira por inactividad aunque el usuario
    siga con la pestana del portal abierta (ver static/session-refresh.js,
    que llama aca cada 10 min)."""
    session_uuid = request.cookies.get("session_uuid")
    if not session_uuid:
        return JSONResponse({"error": _MSG_NO_AUTORIZADO}, status_code=401)

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{AUTH_URL}/auth/refresh", json={"session_uuid": session_uuid})
    except httpx.HTTPError:
        return JSONResponse({"error": _MSG_AUTH_NO_DISPONIBLE}, status_code=503)

    if resp.status_code != 200:
        response = JSONResponse({"error": _MSG_SESION_INVALIDA}, status_code=401)
        response.delete_cookie("session_uuid")
        return response

    return JSONResponse({"status": "success"})

@app.post("/api/logout")
async def api_logout(request: Request):
    """Logout: invalida sesión en authservise y elimina cookie."""
    session_uuid = request.cookies.get("session_uuid")
    if session_uuid:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(f"{AUTH_URL}/auth/logout", json={"session_uuid": session_uuid})
        except httpx.HTTPError:
            pass

    resp = RedirectResponse(url="/")
    resp.delete_cookie("session_uuid")
    return resp

@app.post("/api/redirect-to-service")
async def redirect_to_service(request: Request):
    """Determina a dónde redirigir según el servicio y registro."""
    data = await request.json()
    slug = data.get("slug", "")
    session_uuid = request.cookies.get("session_uuid")

    if not session_uuid:
        return JSONResponse({"error": _MSG_NO_AUTORIZADO}, status_code=401)

    payload = await verify_session(session_uuid)
    if not payload:
        return JSONResponse({"error": "Sesión inválida"}, status_code=401)

    todos_servicios = await get_todos_servicios_con_estado(payload["user_id"])
    svc = next((s for s in todos_servicios if s["slug"] == slug), None)

    if not svc:
        return JSONResponse({"error": "Servicio no encontrado"}, status_code=404)

    if not svc.get("registrado"):
        # No registrado → redirect a la página de planes del servicio
        return JSONResponse({
            "redirect": True,
            "url": f"/planes/{slug}",
            "mensaje": f"Conoce los planes de {svc['nombre']}"
        })

    # Registrado → redirect al servicio
    return JSONResponse({
        "redirect": True,
        "url": svc.get("url_base", f"/{slug}"),
        "mensaje": f"Redirigiendo a {svc['nombre']}..."
    })

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
