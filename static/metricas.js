// Compartido entre templates/metricas.html y templates/metricas_secretos.html.

function mostrarMsg(id, texto, tipo) {
    const el = document.getElementById(id);
    el.textContent = texto;
    el.className = 'msg ' + tipo;
}

// Formatea en hora local (no ISO crudo) todos los elementos que matcheen
// el selector y tengan data-ts -- usado tanto para "ultima actividad" de
// usuarios como para "creada"/"ultimo uso" de aplicaciones M2M.
function formatearFechas(selector) {
    document.querySelectorAll(selector).forEach(td => {
        const ts = td.dataset.ts;
        if (ts) {
            td.textContent = new Date(ts).toLocaleString('es-MX', { dateStyle: 'medium', timeStyle: 'short' });
        }
    });
}
