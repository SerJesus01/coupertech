const navToggle = document.querySelector('.nav-toggle');
const mainNav = document.querySelector('.main-nav');

if (navToggle && mainNav) {
    const closeMenu = () => {
        navToggle.setAttribute('aria-expanded', 'false');
        mainNav.classList.remove('open');
        document.body.classList.remove('menu-open');
    };

    navToggle.addEventListener('click', () => {
        const open = navToggle.getAttribute('aria-expanded') === 'true';
        navToggle.setAttribute('aria-expanded', String(!open));
        mainNav.classList.toggle('open', !open);
        document.body.classList.toggle('menu-open', !open);
    });

    mainNav.querySelectorAll('a').forEach(link => link.addEventListener('click', closeMenu));
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape') closeMenu();
    });
}
