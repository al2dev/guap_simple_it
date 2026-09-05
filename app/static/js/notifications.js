(() => {
  const socket = window.appSocket;
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content;
  const lists = Object.fromEntries([...document.querySelectorAll('[data-notification-list]')].map(element => [element.dataset.notificationList, element]));
  const count = document.querySelector('.notification-count');
  const toastContainer = document.querySelector('.toast-container');
  let knownActiveIds = new Set();
  const syncVersions = {};
  const escape = value => String(value ?? '').replace(/[&<>'"]/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[character]));
  const icons = {chat_mention:'bi-at',chat_reply:'bi-reply-fill',material_mention:'bi-chat-left-text',material_created:'bi-file-earmark-plus',material_deleted:'bi-file-earmark-x',subject_created:'bi-journal-plus',subject_deleted:'bi-journal-x',event_created:'bi-calendar-plus',event_updated:'bi-calendar-check',event_deleted:'bi-calendar-x',schedule_created:'bi-clock-history',schedule_updated:'bi-clock',schedule_deleted:'bi-calendar-minus'};
  const formatDate = value => new Date(value).toLocaleString('ru-RU',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'});
  const render = (items, status) => items.length ? items.map(notification => `<button class="notification-mini ${notification.is_read?'':'unread'}" data-open-notification="${notification.id}" data-target-url="${escape(notification.target_url)}"><span class="notification-mini-icon"><i class="bi ${icons[notification.kind] || 'bi-bell'}"></i></span><span><strong>${escape(notification.text)}</strong><small>${escape(notification.actor)} · ${formatDate(notification.created_at)}${status === 'history' && notification.read_at ? ` · просмотрено ${formatDate(notification.read_at)}` : ''}</small></span><i class="bi bi-chevron-right ms-auto"></i></button>`).join('') : `<div class="notification-empty"><i class="bi ${status === 'active' ? 'bi-bell-slash' : 'bi-clock-history'}"></i><p>${status === 'active' ? 'Активных уведомлений нет' : 'История пока пуста'}</p></div>`;

  function updateCount(value) {
    if (count) {
      count.textContent = value;
      count.classList.toggle('d-none', !value);
    }
    document.querySelector('[data-active-count]')?.replaceChildren(document.createTextNode(value));
  }

  async function sync(status = 'active') {
    const list = lists[status];
    if (!list) return;
    const version = syncVersions[status] = (syncVersions[status] || 0) + 1;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      // Page navigation recreates the socket; the panel must work while it reconnects.
      const response = await fetch(`/api/notifications?status=${encodeURIComponent(status)}`, {
        cache: 'no-store', headers: {'Accept': 'application/json'}, signal: controller.signal,
      });
      if (!response.ok) throw new Error('Не удалось загрузить уведомления');
      const data = await response.json();
      if (version !== syncVersions[status]) return;
      updateCount(data.unread);
      list.innerHTML = render(data.notifications, status);
      if (status === 'active') knownActiveIds = new Set(data.notifications.map(item => item.id));
    } catch {
      if (version !== syncVersions[status]) return;
      list.innerHTML = `<div class="p-3 text-danger small">Не удалось загрузить уведомления. <button type="button" class="btn btn-sm btn-link" data-retry-notifications="${status}">Повторить</button></div>`;
    } finally {
      clearTimeout(timeout);
    }
  }

  function showLiveNotification(notification) {
    if (!toastContainer) return;
    const element = document.createElement('div');
    element.className = 'toast live-notification-toast border-0 shadow';
    element.setAttribute('role', 'status');
    element.innerHTML = `<button type="button" data-open-notification="${notification.id}"><span class="notification-mini-icon"><i class="bi ${icons[notification.kind] || 'bi-bell'}"></i></span><span><strong>${escape(notification.text)}</strong><small>${escape(notification.actor)} · только что</small></span><i class="bi bi-chevron-right"></i></button>`;
    toastContainer.appendChild(element);
    element.addEventListener('hidden.bs.toast', () => element.remove(), {once:true});
    bootstrap.Toast.getOrCreateInstance(element, {delay:7000}).show();
  }

  function addActive(notification) {
    if (knownActiveIds.has(notification.id)) return;
    knownActiveIds.add(notification.id);
    const active = lists.active;
    active?.querySelector('.notification-empty')?.remove();
    active?.insertAdjacentHTML('afterbegin', render([notification], 'active'));
    updateCount((Number(count?.textContent) || 0) + 1);
    showLiveNotification(notification);
  }

  function markRead(notification) {
    const activeItem = lists.active?.querySelector(`[data-open-notification="${notification.id}"]`);
    if (activeItem) {
      activeItem.remove();
      knownActiveIds.delete(notification.id);
      updateCount(Math.max(0, (Number(count?.textContent) || 0) - 1));
      if (!lists.active.querySelector('[data-open-notification]')) lists.active.innerHTML = render([], 'active');
    }
    const history = lists.history;
    history?.querySelector(`[data-open-notification="${notification.id}"]`)?.remove();
    history?.querySelector('.notification-empty')?.remove();
    history?.insertAdjacentHTML('afterbegin', render([notification], 'history'));
  }

  document.querySelector('[data-notification-toggle]')?.addEventListener('click', () => { sync('active'); sync('history'); });
  document.querySelector('[data-bs-target="#notificationHistory"]')?.addEventListener('shown.bs.tab', () => sync('history'));
  document.addEventListener('click', async event => {
    const retry = event.target.closest('[data-retry-notifications]');
    if (retry) { sync(retry.dataset.retryNotifications); return; }
    const button = event.target.closest('[data-open-notification], [data-notification-id]');
    if (!button) return;
    const id = button.dataset.openNotification || button.dataset.notificationId;
    const response = await fetch(`/api/notifications/${id}/read`, {method:'POST',headers:{'X-CSRFToken':csrf}});
    if (response.ok) {
      const data = await response.json();
      location.href = data.target_url || button.dataset.targetUrl || '/';
    }
  });
  document.querySelectorAll('[data-read-all]').forEach(button => button.addEventListener('click', async () => {
    const response = await fetch('/api/notifications/read-all',{method:'POST',headers:{'X-CSRFToken':csrf}});
    if (response.ok) {
      knownActiveIds.clear(); updateCount(0);
      if (lists.active) lists.active.innerHTML = render([], 'active');
      sync('history');
    }
  }));

  socket?.on('notification:new', addActive);
  socket?.on('notification:read', markRead);
  socket?.on('notification:read_all', () => {
    knownActiveIds.clear(); updateCount(0);
    if (lists.active) lists.active.innerHTML = render([], 'active');
    sync('history');
  });
  socket?.on('connect', () => { sync('active'); sync('history'); });
  sync('active');
})();
