// Mantiene viva la sesion mientras el usuario tenga el portal abierto.
// admin_session tiene TTL de 1h en Redis (authservise) y expira por
// inactividad aunque la pestana siga abierta -- este ping cada 10 min
// (bien por debajo de 1h) evita ese 401 sorpresivo en /api/redirect-to-service.
(function () {
    const REFRESH_INTERVAL_MS = 10 * 60 * 1000;

    async function refreshSession() {
        try {
            const resp = await fetch('/api/refresh-session', { method: 'POST' });
            if (resp.status === 401) {
                window.location.href = '/';
            }
        } catch (err) {
            // Error de red transitorio: se reintenta en el proximo ciclo.
        }
    }

    setInterval(refreshSession, REFRESH_INTERVAL_MS);
})();
