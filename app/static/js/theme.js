(() => {
  const root = document.documentElement;
  const button = document.getElementById('themeToggle');
  const syncIcon = () => {
    if (!button) return;
    button.querySelector('i').className = root.dataset.bsTheme === 'dark' ? 'bi bi-sun' : 'bi bi-moon-stars';
  };
  syncIcon();
  button?.addEventListener('click', () => {
    root.dataset.bsTheme = root.dataset.bsTheme === 'dark' ? 'light' : 'dark';
    localStorage.setItem('student-theme', root.dataset.bsTheme);
    syncIcon();
  });
  document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => new bootstrap.Tooltip(el));
})();
