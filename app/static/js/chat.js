(() => {
  const socket = window.appSocket;
  const realtimeUser = window.REALTIME_USER || {};
  const feed = document.querySelector('[data-chat-feed]');
  const panel = document.getElementById('chatThreadPanel');
  const body = document.querySelector('[data-thread-body]');
  const threadForm = document.querySelector('[data-thread-form]');
  const chatForm = document.querySelector('[data-chat-compose]');
  const newMessagesButton = document.querySelector('[data-new-messages]');
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content;
  let activeMessageId = null;
  let pendingMessages = 0;
  let syncCursor = Math.max(0, ...[...document.querySelectorAll('[data-message-id]')].map(item => Number(item.dataset.messageId)));
  const escape = value => String(value ?? '').replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
  const time = value => new Date(value).toLocaleString('ru-RU', {day:'numeric', month:'short', hour:'2-digit', minute:'2-digit'});
  const clock = value => new Date(value).toLocaleTimeString('ru-RU', {hour:'2-digit', minute:'2-digit'});

  function socketRequest(eventName, payload) {
    return new Promise((resolve, reject) => {
      if (!socket?.connected) return reject(new Error('Нет соединения с сервером'));
      socket.timeout(6000).emit(eventName, payload, (error, response) => {
        if (error) reject(new Error('Сервер не ответил'));
        else if (response?.error) reject(new Error('Не удалось получить данные'));
        else resolve(response);
      });
    });
  }

  function grow(textarea) {
    textarea.style.height = 'auto';
    textarea.style.height = `${Math.min(textarea.scrollHeight, 120)}px`;
  }

  document.querySelectorAll('.chat-compose textarea, .chat-thread-compose textarea').forEach(textarea => {
    textarea.addEventListener('input', () => grow(textarea));
    textarea.addEventListener('keydown', event => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        if (textarea.value.trim()) textarea.form.requestSubmit();
      }
    });
  });

  function normalizeMessage(message) {
    const mine = Number(message.author_id) === Number(realtimeUser.id);
    return {...message, mine, can_delete: Boolean(realtimeUser.isAdmin || mine)};
  }

  function normalizeReply(reply) {
    return {...reply, can_delete:Boolean(realtimeUser.isAdmin || Number(reply.author_id) === Number(realtimeUser.id))};
  }

  function replyHtml(value) {
    const reply = normalizeReply(value);
    return `<div class="thread-reply" data-thread-reply-id="${reply.id}"><span class="comment-avatar">${escape(reply.initials)}</span><div><header><strong>${escape(reply.author)}</strong><time>${time(reply.created_at)}</time></header><p>${escape(reply.text)}</p></div>${reply.can_delete ? `<button class="chat-delete" data-delete-reply="${reply.id}" title="Удалить"><i class="bi bi-trash"></i></button>` : ''}</div>`;
  }

  function updateCount(messageId, count) {
    const target = document.querySelector(`[data-reply-count-for="${messageId}"]`);
    if (target) target.textContent = Number(count) || 0;
  }

  function isNearBottom(element = feed) {
    return !element || element.scrollHeight - element.scrollTop - element.clientHeight < 100;
  }

  function showPendingMessages(count) {
    pendingMessages += count;
    if (!newMessagesButton || !pendingMessages) return;
    newMessagesButton.querySelector('span').textContent = `Новые сообщения: ${pendingMessages}`;
    newMessagesButton.classList.remove('d-none');
  }

  function scrollToBottom() {
    if (feed) feed.scrollTo({top:feed.scrollHeight, behavior:'smooth'});
    pendingMessages = 0;
    newMessagesButton?.classList.add('d-none');
  }

  function messageHtml(value) {
    const message = normalizeMessage(value);
    const avatar = message.mine ? '' : `<span class="comment-avatar chat-avatar">${escape(message.initials)}</span>`;
    const author = message.mine ? '' : `<strong class="chat-author">${escape(message.author)}</strong>`;
    const remove = message.can_delete ? `<form method="post" action="/chat/messages/${message.id}/delete"><input type="hidden" name="csrf_token" value="${escape(csrf)}"><button class="chat-delete" title="Удалить сообщение"><i class="bi bi-trash"></i></button></form>` : '';
    return `<article class="chat-message-row ${message.mine ? 'mine' : ''}" id="message-${message.id}" data-message-id="${message.id}">${avatar}<div class="chat-bubble">${author}<div class="chat-text">${escape(message.text)}</div><footer><button class="chat-reply-link" type="button" data-open-thread="${message.id}" data-bs-toggle="offcanvas" data-bs-target="#chatThreadPanel"><i class="bi bi-reply"></i><span>Ответить</span><span class="chat-reply-dot" aria-hidden="true"></span><span class="chat-reply-count" data-reply-count-for="${message.id}">${Number(message.reply_count) || 0}</span></button><time>${clock(message.created_at)}</time>${remove}</footer></div></article>`;
  }

  function insertMessage(value, announce = true) {
    const message = normalizeMessage(value);
    if (!feed || document.querySelector(`[data-message-id="${message.id}"]`)) return false;
    const pinned = isNearBottom();
    feed.querySelector('.chat-empty')?.remove();
    const holder = document.createElement('div');
    holder.innerHTML = messageHtml(message);
    const next = [...feed.querySelectorAll('[data-message-id]')].find(item => Number(item.dataset.messageId) > message.id);
    feed.insertBefore(holder.firstElementChild, next || null);
    if (announce && pinned) scrollToBottom();
    else if (announce) showPendingMessages(1);
    return true;
  }

  function applyReplyCreated(data) {
    updateCount(data.message_id, data.reply_count);
    if (String(data.message_id) !== activeMessageId || !body) return;
    if (body.querySelector(`[data-thread-reply-id="${data.reply.id}"]`)) return;
    const pinned = isNearBottom(body);
    body.querySelector('.thread-empty')?.remove();
    const replies = body.querySelector('.thread-replies');
    if (replies) replies.insertAdjacentHTML('beforeend', replyHtml(data.reply));
    document.querySelector('[data-thread-subtitle]').textContent = `${data.reply_count} ответов`;
    if (pinned) body.scrollTo({top:body.scrollHeight, behavior:'smooth'});
  }

  function applyReplyDeleted(data) {
    updateCount(data.message_id, data.reply_count);
    if (String(data.message_id) !== activeMessageId || !body) return;
    body.querySelector(`[data-thread-reply-id="${data.reply_id}"]`)?.remove();
    document.querySelector('[data-thread-subtitle]').textContent = `${data.reply_count} ответов`;
    const replies = body.querySelector('.thread-replies');
    if (replies && !replies.querySelector('.thread-reply')) replies.innerHTML = '<div class="thread-empty">Ответов пока нет</div>';
  }

  async function syncMessages() {
    const visibleIds = [...document.querySelectorAll('[data-message-id]')].map(item => item.dataset.messageId);
    try {
      const data = await socketRequest('chat:sync', {after_id:syncCursor, message_ids:visibleIds});
      Object.entries(data.reply_counts || {}).forEach(([messageId, count]) => updateCount(messageId, count));
      data.messages.forEach(message => {
        insertMessage(message);
        syncCursor = Math.max(syncCursor, Number(message.id));
      });
    } catch { /* Socket.IO выполнит повторную синхронизацию после reconnect. */ }
  }

  async function loadThread(messageId) {
    activeMessageId = String(messageId);
    body.innerHTML = '<div class="notification-empty">Загрузка…</div>';
    try {
      const data = await socketRequest('chat:thread', {message_id:messageId});
      if (String(messageId) !== activeMessageId) return;
      document.querySelector('[data-thread-subtitle]').textContent = `${data.replies.length} ответов`;
      body.innerHTML = `<div class="thread-source"><strong>${escape(data.message.author)}</strong><p>${escape(data.message.text)}</p><time>${time(data.message.created_at)}</time></div><div class="thread-replies">${data.replies.length ? data.replies.map(replyHtml).join('') : '<div class="thread-empty">Ответов пока нет</div>'}</div>`;
      body.scrollTop = body.scrollHeight;
      threadForm.action = `/chat/messages/${messageId}/replies`;
      updateCount(messageId, data.replies.length);
    } catch (error) { body.innerHTML = `<div class="notification-empty text-danger">${escape(error.message)}</div>`; }
  }

  document.addEventListener('click', event => {
    const trigger = event.target.closest('[data-open-thread]');
    if (trigger) loadThread(trigger.dataset.openThread);
  });

  threadForm?.addEventListener('submit', async event => {
    event.preventDefault();
    if (!activeMessageId) return;
    const textarea = threadForm.querySelector('textarea');
    const button = threadForm.querySelector('button');
    button.disabled = true;
    try {
      const response = await fetch(threadForm.action, {method:'POST', body:new FormData(threadForm), headers:{Accept:'application/json'}});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Не удалось отправить ответ');
      applyReplyCreated({message_id:activeMessageId, reply:data, reply_count:data.reply_count});
      textarea.value = ''; grow(textarea);
    } catch (error) { window.alert(error.message); }
    finally { button.disabled = false; textarea.focus(); }
  });

  chatForm?.addEventListener('submit', async event => {
    event.preventDefault();
    const textarea = chatForm.querySelector('textarea');
    const button = chatForm.querySelector('button');
    button.disabled = true;
    try {
      const response = await fetch(chatForm.action, {method:'POST', body:new FormData(chatForm), headers:{Accept:'application/json'}});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Не удалось отправить сообщение');
      insertMessage(data.message); textarea.value = ''; grow(textarea); scrollToBottom();
    } catch (error) { window.alert(error.message); }
    finally { button.disabled = false; textarea.focus(); }
  });

  body?.addEventListener('click', async event => {
    const button = event.target.closest('[data-delete-reply]');
    if (!button || !confirm('Удалить ответ?')) return;
    const response = await fetch(`/chat/replies/${button.dataset.deleteReply}/delete`, {method:'POST', headers:{'X-CSRFToken':csrf, Accept:'application/json'}});
    if (response.ok) applyReplyDeleted(await response.json());
  });

  socket?.on('chat:message_created', message => {
    insertMessage(message);
    syncCursor = Math.max(syncCursor, Number(message.id));
  });
  socket?.on('chat:message_deleted', data => {
    document.querySelector(`[data-message-id="${data.message_id}"]`)?.remove();
    if (String(data.message_id) === activeMessageId) bootstrap.Offcanvas.getOrCreateInstance(panel).hide();
  });
  socket?.on('chat:reply_created', applyReplyCreated);
  socket?.on('chat:reply_deleted', applyReplyDeleted);
  socket?.on('connect', () => { syncMessages(); if (activeMessageId) loadThread(activeMessageId); });

  const highlightedMessage = location.hash ? document.getElementById(location.hash.slice(1)) : null;
  if (highlightedMessage) highlightedMessage.scrollIntoView({block:'center'});
  else if (feed) feed.scrollTop = feed.scrollHeight;
  const threadFromUrl = new URLSearchParams(location.search).get('thread');
  if (threadFromUrl && panel) {
    bootstrap.Offcanvas.getOrCreateInstance(panel).show();
    if (socket?.connected) loadThread(threadFromUrl);
    else socket?.once('connect', () => loadThread(threadFromUrl));
  }
  newMessagesButton?.addEventListener('click', scrollToBottom);
  feed?.addEventListener('scroll', () => { if (isNearBottom()) { pendingMessages = 0; newMessagesButton?.classList.add('d-none'); } });
  panel?.addEventListener('hidden.bs.offcanvas', () => { activeMessageId = null; });
  if (socket?.connected) syncMessages();
})();
