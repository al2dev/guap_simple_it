(() => {
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content;
  const list = document.querySelector('[data-notification-list]');
  const count = document.querySelector('.notification-count');
  const escape = value => String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  const updateCount = value => { if (!count) return; count.textContent = value; count.classList.toggle('d-none', !value); };
  async function load() {
    if (!list) return;
    try {
      const res = await fetch('/api/notifications'); const data = await res.json(); updateCount(data.unread);
      list.innerHTML = data.notifications.length ? data.notifications.slice(0, 6).map(n => `<button class="notification-mini ${n.is_read?'':'unread'}" data-open-notification="${n.id}"><i class="bi bi-chat-left-text"></i><span><strong>${escape(n.text)}</strong><small>${new Date(n.created_at).toLocaleString('ru-RU',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'})}</small></span></button>`).join('') : '<div class="p-4 text-center text-secondary small">Новых уведомлений нет</div>';
    } catch { list.innerHTML = '<div class="p-3 text-danger small">Не удалось загрузить уведомления</div>'; }
  }
  document.querySelector('[data-notification-toggle]')?.addEventListener('click', load);
  document.addEventListener('click', async e => {
    const button = e.target.closest('[data-open-notification], [data-notification-id]');
    if (!button) return;
    const id = button.dataset.openNotification || button.dataset.notificationId;
    const res = await fetch(`/api/notifications/${id}/read`, {method:'POST',headers:{'X-CSRFToken':csrf}});
    if (res.ok) { const data=await res.json(); location.href=`/?start=${data.date}&open_student=${data.student_id}&open_date=${data.date}`; }
  });
  document.querySelector('[data-read-all]')?.addEventListener('click', async () => { await fetch('/api/notifications/read-all',{method:'POST',headers:{'X-CSRFToken':csrf}}); updateCount(0); load(); });
})();
