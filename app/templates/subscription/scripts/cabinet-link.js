document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-cabinet-link]').forEach((link) => {
    link.addEventListener('click', (event) => {
      if (window.matchMedia('(min-width: 1024px)').matches) {
        event.preventDefault();
        window.open(link.href, '_blank', 'noopener,noreferrer');
      }
    });
  });
});
