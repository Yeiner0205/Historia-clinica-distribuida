/* ===========================================================================
   sesion.js — manejo del token y llamadas autenticadas para las vistas.

   El token JWT se guarda en localStorage del navegador. Es suficiente para la
   demostración académica; en producción iría en una cookie HttpOnly con
   SameSite. Lo importante del parcial es que los permisos se verifican en la
   API: borrar el token o cambiar el rol en el navegador no da acceso.
   ======================================================================== */
const Sesion = (() => {
    const CLAVE = 'hc_token';
    const CLAVE_USUARIO = 'hc_usuario';

    const guardar = (datos) => {
        localStorage.setItem(CLAVE, datos.access_token);
        localStorage.setItem(CLAVE_USUARIO, JSON.stringify({
            usuario: datos.usuario || null,
            nombre: datos.nombre,
            rol: datos.rol,
            documento: datos.documento,
            sede_id: datos.sede_id,
            permisos: datos.permisos || []
        }));
    };

    const token = () => localStorage.getItem(CLAVE);

    const usuario = () => {
        try { return JSON.parse(localStorage.getItem(CLAVE_USUARIO) || 'null'); }
        catch { return null; }
    };

    const cerrar = () => {
        localStorage.removeItem(CLAVE);
        localStorage.removeItem(CLAVE_USUARIO);
        window.location.href = '/login';
    };

    const puede = (permiso) => (usuario()?.permisos || []).includes(permiso);

    /* Exige sesión y, si se indica, uno de los roles permitidos.
       Se puede llamar desde <head>: el mensaje de rol equivocado se pinta
       cuando el documento esté listo. */
    const exigir = (roles) => {
        const u = usuario();
        if (!token() || !u) {
            window.location.href = '/login?volver=' + encodeURIComponent(window.location.pathname);
            return null;
        }
        if (roles && roles.length && !roles.includes(u.rol)) {
            const pintar = () => {
                document.body.innerHTML =
                    `<div class="contenedor" style="max-width:760px;margin:0 auto;padding:40px 18px">
                       <div class="aviso error" role="alert" style="border:1px solid #ef4444;border-radius:12px;padding:16px">
                         <strong>Esta vista no corresponde a su rol.</strong><br>
                         Su sesión es <b>${u.rol}</b> y esta pantalla es para: ${roles.join(', ')}.
                         <p style="margin-top:12px">
                           <a class="boton secundario" href="/home">Volver al inicio</a>
                           <button type="button" onclick="Sesion.cerrar()">Cambiar de usuario</button></p>
                       </div>
                     </div>`;
            };
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', pintar);
            } else {
                pintar();
            }
            return null;
        }
        return u;
    };

    /* Añade el token a todas las llamadas a la API que haga la página.
       Permite que las vistas heredadas (admisión y médico) sigan usando sus
       `fetch` sin cambiar su código: la autorización se añade aquí y se
       verifica en el servidor. */
    const interceptarFetch = () => {
        if (window.__fetchInterceptado) return;
        window.__fetchInterceptado = true;
        const original = window.fetch.bind(window);
        window.fetch = async (recurso, opciones = {}) => {
            const url = typeof recurso === 'string' ? recurso : (recurso && recurso.url) || '';
            const esApi = url.startsWith('/api/') || url.startsWith('/auth/');
            if (esApi && token()) {
                opciones = Object.assign({}, opciones);
                opciones.headers = Object.assign({}, opciones.headers || {},
                    { Authorization: 'Bearer ' + token() });
            }
            const respuesta = await original(recurso, opciones);
            if (esApi && respuesta.status === 401) cerrar();
            return respuesta;
        };
    };

    /* Inserta una tira con el usuario y el botón de salir en las vistas
       heredadas, que no tienen la barra `data-barra`. */
    const insertarCabeceraSesion = (titulo) => {
        const u = usuario();
        if (!u || document.getElementById('tira-sesion')) return;
        const tira = document.createElement('div');
        tira.id = 'tira-sesion';
        tira.setAttribute('role', 'status');
        tira.style.cssText =
            'display:flex;gap:12px;align-items:center;flex-wrap:wrap;padding:8px 16px;' +
            'background:#12121f;border-bottom:1px solid rgba(99,102,241,.25);color:#e8edf5;' +
            "font:500 13px/1.4 'Inter',system-ui,sans-serif";
        tira.innerHTML = `
            <strong>${titulo}</strong>
            <span style="background:rgba(99,102,241,.18);border:1px solid rgba(99,102,241,.3);
                         border-radius:99px;padding:2px 10px;text-transform:uppercase;font-size:11px;
                         letter-spacing:.07em;color:#a5b4fc">${u.rol}</span>
            <span style="flex:1"></span>
            <span style="color:#a3b0c2">${u.nombre}</span>
            <a href="/home" style="color:#a5b4fc;text-decoration:none">Inicio</a>
            <button type="button" onclick="Sesion.cerrar()"
                style="font:inherit;cursor:pointer;background:#1a1a2e;color:#e8edf5;
                       border:1px solid rgba(99,102,241,.3);border-radius:8px;padding:5px 12px">Salir</button>`;
        document.body.prepend(tira);
    };

    /* fetch con el token puesto y manejo uniforme de 401/403. */
    const pedir = async (url, opciones = {}) => {
        const cabeceras = Object.assign({}, opciones.headers || {});
        if (token()) cabeceras['Authorization'] = 'Bearer ' + token();
        const respuesta = await fetch(url, Object.assign({}, opciones, { headers: cabeceras }));

        if (respuesta.status === 401) {
            cerrar();
            throw new Error('La sesión expiró. Vuelva a iniciar sesión.');
        }
        if (!respuesta.ok) {
            let detalle = respuesta.statusText;
            try {
                const cuerpo = await respuesta.json();
                detalle = typeof cuerpo.detail === 'string' ? cuerpo.detail : JSON.stringify(cuerpo.detail || cuerpo);
            } catch { /* respuesta sin JSON */ }
            const error = new Error(detalle);
            error.estado = respuesta.status;
            throw error;
        }
        const tipo = respuesta.headers.get('content-type') || '';
        return tipo.includes('application/json') ? respuesta.json() : respuesta.text();
    };

    /* Pinta la barra superior con el usuario y el botón de salir. */
    const pintarBarra = (titulo) => {
        const u = usuario();
        const barra = document.querySelector('[data-barra]');
        if (!barra || !u) return;
        barra.innerHTML = `
            <h1>${titulo}</h1>
            <span class="rol">${u.rol}</span>
            <span class="espacio"></span>
            <span class="sub">${u.nombre}${u.documento ? ' · doc. ' + u.documento : ''}</span>
            <a class="boton secundario" href="/home">Inicio</a>
            <button class="secundario" type="button" onclick="Sesion.cerrar()">Salir</button>`;
    };

    return { guardar, token, usuario, cerrar, puede, exigir, pedir, pintarBarra,
             interceptarFetch, insertarCabeceraSesion };
})();

/* Utilidades de presentación compartidas por las vistas. */
const Fmt = {
    fecha: (valor) => {
        if (!valor) return '—';
        const d = new Date(valor);
        return isNaN(d) ? String(valor) : d.toLocaleString('es-CO', {
            year: 'numeric', month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit'
        });
    },
    soloFecha: (valor) => {
        if (!valor) return '—';
        const d = new Date(valor);
        return isNaN(d) ? String(valor) : d.toLocaleDateString('es-CO');
    },
    texto: (valor) => (valor === null || valor === undefined || valor === '' ? '—' : String(valor)),
    escapar: (valor) => String(valor ?? '').replace(/[&<>"']/g,
        (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])),
    descargarJson: (datos, nombre) => {
        const blob = new Blob([JSON.stringify(datos, null, 2)], { type: 'application/fhir+json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = nombre; a.click();
        URL.revokeObjectURL(url);
    }
};
