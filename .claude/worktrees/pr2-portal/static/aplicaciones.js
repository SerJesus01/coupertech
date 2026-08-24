// API Keys (aplicaciones de terceros) -- compartido por las 4 pantallas de
// metricas (auth/secretos/sintesis/transcripcion). Depende de mostrarMsg y
// formatearFechas (metricas.js), cargar ese script antes que este.
formatearFechas('#tablaAplicaciones .fecha[data-ts]');

function mostrarSecreto(clientId, clientSecret) {
    document.getElementById('modalClientId').textContent = clientId;
    document.getElementById('modalClientSecret').textContent = clientSecret;
    document.getElementById('overlaySecreto').classList.add('visible');
}

function cerrarModal() {
    document.getElementById('overlaySecreto').classList.remove('visible');
    window.location.reload();
}

async function crearAplicacion(ev) {
    ev.preventDefault();
    const boton = ev.target.querySelector('button');
    boton.disabled = true;
    try {
        const scopeElegido = document.getElementById('nuevoScopeApp').value;
        const servicioElegido = document.getElementById('nuevoServicioApp').value;
        const vigenciaElegida = document.getElementById('nuevoVigenciaApp').value;
        const payload = {
            nombre: document.getElementById('nuevoNombreApp').value,
            servicio: servicioElegido,
        };
        if (scopeElegido) payload.scopes = [scopeElegido];
        if (vigenciaElegida === 'unico') {
            payload.uso_unico = true;
        } else {
            payload.vigencia_dias = parseInt(vigenciaElegida, 10);
        }
        const resp = await fetch('/api/aplicaciones', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await resp.json();
        if (resp.ok) {
            mostrarSecreto(data.client_id, data.client_secret);
        } else {
            mostrarMsg('msgAltaAplicacion', data.error || 'No se pudo crear la aplicación.', 'error');
        }
    } catch (err) {
        mostrarMsg('msgAltaAplicacion', 'Error de conexión.', 'error');
    }
    boton.disabled = false;
    return false;
}

async function rotarSecreto(clientId) {
    if (!confirm('¿Rotar el secreto de esta aplicación? El secreto anterior deja de funcionar de inmediato.')) return;
    try {
        const resp = await fetch(`/api/aplicaciones/${clientId}/rotar-secreto`, { method: 'POST' });
        const data = await resp.json();
        if (resp.ok) {
            mostrarSecreto(clientId, data.client_secret);
        } else {
            mostrarMsg('msgAplicaciones', data.error || 'No se pudo rotar el secreto.', 'error');
        }
    } catch (err) {
        mostrarMsg('msgAplicaciones', 'Error de conexión.', 'error');
    }
}

async function desactivarAplicacion(clientId) {
    if (!confirm('¿Desactivar esta aplicación? Podés reactivarla después.')) return;
    try {
        const resp = await fetch(`/api/aplicaciones/${clientId}/desactivar`, { method: 'POST' });
        const data = await resp.json();
        if (resp.ok) {
            window.location.reload();
        } else {
            mostrarMsg('msgAplicaciones', data.error || 'No se pudo desactivar la aplicación.', 'error');
        }
    } catch (err) {
        mostrarMsg('msgAplicaciones', 'Error de conexión.', 'error');
    }
}

async function reactivarAplicacion(clientId) {
    try {
        const resp = await fetch(`/api/aplicaciones/${clientId}/reactivar`, { method: 'POST' });
        const data = await resp.json();
        if (resp.ok) {
            window.location.reload();
        } else {
            mostrarMsg('msgAplicaciones', data.error || 'No se pudo reactivar la aplicación.', 'error');
        }
    } catch (err) {
        mostrarMsg('msgAplicaciones', 'Error de conexión.', 'error');
    }
}

async function eliminarAplicacion(clientId) {
    if (!confirm('¿Eliminar esta aplicación? Esta acción no se puede deshacer.')) return;
    try {
        const resp = await fetch(`/api/aplicaciones/${clientId}`, { method: 'DELETE' });
        const data = await resp.json();
        if (resp.ok) {
            document.querySelector(`tr[data-client-id="${clientId}"]`).remove();
        } else {
            mostrarMsg('msgAplicaciones', data.error || 'No se pudo eliminar la aplicación.', 'error');
        }
    } catch (err) {
        mostrarMsg('msgAplicaciones', 'Error de conexión.', 'error');
    }
}
