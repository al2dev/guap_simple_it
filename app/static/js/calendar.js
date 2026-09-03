(() => {
  const panelEl = document.getElementById('cellOffcanvas');
  const scroll = document.querySelector('.calendar-scroll');
  if (!panelEl || !scroll) return;

  const panel = bootstrap.Offcanvas.getOrCreateInstance(panelEl);
  const body = panelEl.querySelector('[data-panel-body]');
  const title = panelEl.querySelector('[data-panel-title]');
  const dateLabel = panelEl.querySelector('[data-panel-date]');
  const monthLabel = document.querySelector('[data-visible-month]');
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  let activeCell = null;
  let activeDay = null;

  const esc = value => String(value ?? '').replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
  const prettyDate = value => new Date(`${value}T12:00:00`).toLocaleDateString('ru-RU', {weekday:'long', day:'numeric', month:'long'});
  const skeleton = () => '<div class="panel-skeleton"><span></span><span></span><span></span></div>';
  const empty = text => `<div class="panel-empty">${esc(text)}</div>`;
  const toast = (message, error=false) => {
    const element = document.getElementById('appToast');
    element.querySelector('[data-toast-message]').textContent = message;
    element.querySelector('i').className = error ? 'bi bi-exclamation-circle-fill text-danger' : 'bi bi-check-circle-fill text-success';
    bootstrap.Toast.getOrCreateInstance(element, {delay:2600}).show();
  };

  async function request(url, options={}) {
    options.headers = {...(options.headers || {}), 'X-CSRFToken':csrf};
    if (options.body && typeof options.body !== 'string') {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(options.body);
    }
    const response = await fetch(url, options);
    const data = response.status === 204 ? null : await response.json().catch(() => ({error:'Ошибка сервера'}));
    if (!response.ok) throw new Error(data?.error || 'Не удалось выполнить действие');
    return data;
  }

  function eventCards(events) {
    if (!events.length) return empty('Событий на этот день нет');
    return events.map(event => `<article class="event-panel-card" style="--event-color:${esc(event.color)}"><div class="d-flex align-items-start gap-2"><div class="flex-grow-1"><strong>${esc(event.title)}</strong><small>${esc(event.type)}${event.start_time ? ` · ${event.start_time}` : ''}${event.location ? ` · ${esc(event.location)}` : ''}</small>${event.description ? `<small>${esc(event.description)}</small>` : ''}</div>${window.CALENDAR_DATA.isAdmin ? `<button class="comment-delete" data-delete-event="${event.id}" title="Удалить событие"><i class="bi bi-trash"></i></button>` : ''}</div></article>`).join('');
  }

  function scheduleCards(items) {
    if (!items.length) return empty('В расписании нет занятий');
    return items.map(item => `<article class="schedule-panel-row"><time>${item.start_time}</time><span class="flex-grow-1"><strong>${esc(item.subject)}</strong><small>${esc(item.type)}${item.room ? ` · ауд. ${esc(item.room)}` : ''}${item.teacher ? ` · ${esc(item.teacher)}` : ''}</small>${item.description ? `<small>${esc(item.description)}</small>` : ''}</span>${window.CALENDAR_DATA.isAdmin ? `<button class="comment-delete" data-delete-schedule="${item.id}" title="Удалить занятие"><i class="bi bi-trash"></i></button>` : ''}</article>`).join('');
  }

  async function refreshDecorations() {
    try {
      const data = await request(`/api/calendar?start=${window.CALENDAR_DATA.start}&days=${window.CALENDAR_DATA.days}`);
      const tags = {};
      const events = {};
      const scheduleDates = new Set(data.schedule.map(item => item.date));
      data.tags.forEach(tag => (tags[`${tag.student_id}-${tag.date}`] ||= []).push(tag));
      data.events.forEach(event => (events[event.date] ||= []).push(event));
      document.querySelectorAll('.calendar-cell').forEach(cell => {
        const cellTags = tags[`${cell.dataset.studentId}-${cell.dataset.date}`] || [];
        const dayEvents = events[cell.dataset.date] || [];
        cell.querySelector('[data-cell-dots]').innerHTML = cellTags.slice(0, 3).map(tag => `<i style="background:${esc(tag.color)}" title="${esc(tag.name)}"></i>`).join('');
        cell.querySelector('[data-event-indicator]').innerHTML = dayEvents.length ? `<span class="event-dot" style="--dot-color:${esc(dayEvents[0].color)}" title="${esc(dayEvents[0].title)}"></span>` : '';
        cell.classList.toggle('has-schedule', scheduleDates.has(cell.dataset.date));
        cell.classList.toggle('has-content', cellTags.length > 0 || dayEvents.length > 0);
      });
      document.querySelectorAll('[data-schedule-date]').forEach(header => header.classList.toggle('has-schedule', scheduleDates.has(header.dataset.scheduleDate)));
    } catch (error) {
      toast(error.message, true);
    }
  }

  function renderCell(data) {
    title.textContent = data.student.name;
    dateLabel.textContent = prettyDate(data.date);
    const tags = data.tags.length ? `<div class="tag-list">${data.tags.map(tag => `<span class="tag-pill" style="--tag-color:${esc(tag.color)}" title="${esc(tag.description)}"><i></i>${esc(tag.name)}${tag.can_delete ? `<button data-delete-tag="${tag.cell_tag_id}" aria-label="Удалить"><i class="bi bi-x"></i></button>` : ''}</span>`).join('')}</div>` : empty('Меток пока нет');
    const tagForm = data.can_edit ? `<form class="add-tag-box" data-tag-form><label class="form-label">Добавить метку</label><div class="d-flex gap-2"><select class="form-select form-select-sm" name="tag_id"><option value="">Выберите…</option>${data.available_tags.map(tag => `<option value="${tag.id}">${esc(tag.name)}</option>`).join('')}<option value="custom">Своя метка…</option></select><button class="btn btn-primary btn-sm"><i class="bi bi-plus-lg"></i></button></div><div class="custom-tag-fields d-none mt-2"><input class="form-control form-control-sm mb-2" name="name" maxlength="80" placeholder="Название"><div class="d-flex gap-2"><input class="form-control form-control-color" name="color" type="color" value="#6366f1"><input class="form-control form-control-sm" name="description" maxlength="255" placeholder="Короткое описание"></div></div></form>` : '';
    const comments = data.comments.length ? data.comments.map(comment => `<article class="comment"><span class="comment-avatar">${esc(comment.author.split(' ').map(part => part[0]).join('').slice(0, 2))}</span><div><strong>${esc(comment.author)}</strong><time>${new Date(comment.created_at).toLocaleString('ru-RU', {day:'numeric', month:'short', hour:'2-digit', minute:'2-digit'})}</time><p>${esc(comment.text)}</p></div>${comment.can_delete ? `<button class="comment-delete" data-delete-comment="${comment.id}" title="Удалить"><i class="bi bi-trash"></i></button>` : ''}</article>`).join('') : empty('Начните обсуждение первым');
    body.innerHTML = `<section class="panel-section"><h3 class="panel-section-title"><i class="bi bi-tags"></i>Метки</h3>${tags}${tagForm}</section><section class="panel-section"><h3 class="panel-section-title"><i class="bi bi-calendar-event"></i>События дня</h3>${eventCards(data.events)}</section><section class="panel-section"><h3 class="panel-section-title"><i class="bi bi-journal-text"></i>Расписание</h3>${scheduleCards(data.schedule)}</section><section class="panel-section"><h3 class="panel-section-title"><i class="bi bi-chat-left-text"></i>Комментарии</h3>${comments}<form class="comment-form" data-comment-form><textarea class="form-control" name="text" maxlength="2000" required placeholder="Комментарий или @login…"></textarea><button class="btn btn-primary" title="Отправить"><i class="bi bi-send"></i></button></form></section>`;
  }

  async function openCell(cell) {
    activeDay = null;
    activeCell = {studentId:cell.dataset.studentId, date:cell.dataset.date};
    title.textContent = 'Загрузка…';
    dateLabel.textContent = prettyDate(activeCell.date);
    body.innerHTML = skeleton();
    panel.show();
    try { renderCell(await request(`/api/cell/${activeCell.studentId}/${activeCell.date}`)); }
    catch (error) { body.innerHTML = empty(error.message); }
  }

  function adminEventForm(day) {
    if (!window.CALENDAR_DATA.isAdmin) return '';
    return `<section class="panel-section"><h3 class="panel-section-title"><i class="bi bi-plus-lg"></i>Общее событие</h3><form class="add-tag-box" data-day-event-form><div class="mb-2"><label class="form-label">Название</label><input class="form-control" name="title" maxlength="160" required placeholder="Экзамен по математике"></div><div class="row g-2 mb-2"><div class="col-7"><label class="form-label">Тип</label><select class="form-select" name="type"><option>Экзамен</option><option>Зачёт</option><option>Контрольная</option><option>Лабораторная</option><option>Встреча</option><option>Другое</option></select></div><div class="col-5"><label class="form-label">Время</label><input class="form-control" type="time" name="start_time"></div></div><div class="row g-2 mb-2"><div class="col-8"><label class="form-label">Место</label><input class="form-control" name="location" maxlength="120" placeholder="Аудитория 302"></div><div class="col-4"><label class="form-label">Цвет</label><input class="form-control form-control-color w-100" type="color" name="color" value="#ef4444"></div></div><div class="mb-2"><label class="form-label">Описание</label><textarea class="form-control" name="description" rows="2"></textarea></div><input type="hidden" name="date" value="${day}"><button class="btn btn-primary w-100"><i class="bi bi-calendar-plus me-1"></i>Добавить всей группе</button></form></section>`;
  }

  function adminScheduleForm(day) {
    if (!window.CALENDAR_DATA.isAdmin) return '';
    return `<section class="panel-section"><h3 class="panel-section-title"><i class="bi bi-journal-plus"></i>Дополнительное занятие</h3><form class="add-tag-box" data-day-schedule-form><div class="mb-2"><label class="form-label">Предмет</label><input class="form-control" name="subject" maxlength="160" required placeholder="Название предмета"></div><div class="row g-2 mb-2"><div class="col-6"><label class="form-label">Начало</label><input class="form-control" type="time" name="start_time" required></div><div class="col-6"><label class="form-label">Окончание</label><input class="form-control" type="time" name="end_time"></div></div><div class="row g-2 mb-2"><div class="col-6"><label class="form-label">Тип</label><select class="form-select" name="type"><option>Лекция</option><option>Практическое занятие</option><option>Лабораторное занятие</option><option>Занятие</option></select></div><div class="col-6"><label class="form-label">Аудитория</label><input class="form-control" name="room" maxlength="80"></div></div><div class="mb-2"><label class="form-label">Преподаватель</label><input class="form-control" name="teacher" maxlength="160"></div><div class="mb-2"><label class="form-label">Описание</label><textarea class="form-control" name="description" rows="2"></textarea></div><input type="hidden" name="date" value="${day}"><button class="btn btn-primary w-100"><i class="bi bi-plus-lg me-1"></i>Добавить занятие</button></form></section>`;
  }

  async function openDay(day) {
    activeCell = null;
    activeDay = day;
    title.textContent = window.CALENDAR_DATA.isAdmin ? 'День группы' : 'Расписание';
    dateLabel.textContent = prettyDate(day);
    body.innerHTML = skeleton();
    panel.show();
    try {
      const data = await request(`/api/day/${day}`);
      body.innerHTML = `<section class="panel-section"><h3 class="panel-section-title"><i class="bi bi-journal-text"></i>Расписание</h3>${scheduleCards(data.schedule)}</section><section class="panel-section"><h3 class="panel-section-title"><i class="bi bi-calendar-event"></i>События дня</h3>${eventCards(data.events)}</section>${adminEventForm(day)}${adminScheduleForm(day)}`;
    } catch (error) { body.innerHTML = empty(error.message); }
  }

  async function reloadCell(message) {
    const cell = document.querySelector(`.calendar-cell[data-student-id="${activeCell.studentId}"][data-date="${activeCell.date}"]`);
    if (cell) await openCell(cell);
    await refreshDecorations();
    if (message) toast(message);
  }

  function updateVisibleMonth() {
    const headers = [...document.querySelectorAll('[data-schedule-date]')];
    const width = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--day-width')) || 72;
    const index = Math.max(0, Math.min(headers.length - 1, Math.round(scroll.scrollLeft / width)));
    const value = headers[index]?.dataset.scheduleDate;
    if (value) monthLabel.textContent = new Date(`${value}T12:00:00`).toLocaleDateString('ru-RU', {month:'long', year:'numeric'});
  }

  function scrollToDate(value, behavior='smooth') {
    const header = document.querySelector(`[data-schedule-date="${value}"]`);
    if (!header) return;
    const studentWidth = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--student-width')) || 230;
    scroll.scrollTo({left:Math.max(0, header.offsetLeft - studentWidth - 12), behavior});
  }

  function applyScale(days, keepDate) {
    const studentWidth = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--student-width')) || 230;
    const width = Math.max(44, Math.min(112, (scroll.clientWidth - studentWidth) / Number(days)));
    document.documentElement.style.setProperty('--day-width', `${width}px`);
    document.querySelectorAll('[data-calendar-scale]').forEach(button => button.classList.toggle('active', button.dataset.calendarScale === String(days)));
    localStorage.setItem('calendar-scale', days);
    requestAnimationFrame(() => { scrollToDate(keepDate || window.CALENDAR_DATA.focusDate, 'auto'); updateVisibleMonth(); });
  }

  document.querySelectorAll('.calendar-cell').forEach(cell => {
    cell.addEventListener('click', () => openCell(cell));
    cell.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); openCell(cell); } });
  });
  document.querySelectorAll('[data-schedule-date]').forEach(header => {
    const open = () => openDay(header.dataset.scheduleDate);
    header.addEventListener('click', open);
    header.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); open(); } });
  });
  document.querySelector('[data-scroll-today]')?.addEventListener('click', () => scrollToDate(new Date().toISOString().slice(0, 10)));
  document.querySelectorAll('[data-calendar-scale]').forEach(button => button.addEventListener('click', () => applyScale(button.dataset.calendarScale, document.querySelector('.day-heading.today')?.dataset.scheduleDate)));
  scroll.addEventListener('scroll', updateVisibleMonth, {passive:true});
  window.addEventListener('resize', () => applyScale(localStorage.getItem('calendar-scale') || window.CALENDAR_DATA.initialScale, document.querySelector('.day-heading.today')?.dataset.scheduleDate));

  body.addEventListener('change', event => {
    if (event.target.name === 'tag_id') body.querySelector('.custom-tag-fields')?.classList.toggle('d-none', event.target.value !== 'custom');
  });
  body.addEventListener('submit', async event => {
    event.preventDefault();
    try {
      const form = event.target;
      const values = new FormData(form);
      if (form.matches('[data-tag-form]')) {
        const payload = values.get('tag_id') === 'custom' ? {name:values.get('name'), color:values.get('color'), description:values.get('description')} : {tag_id:Number(values.get('tag_id'))};
        if (!payload.tag_id && !payload.name) throw new Error('Выберите или создайте метку');
        await request(`/api/cell/${activeCell.studentId}/${activeCell.date}/tag`, {method:'POST', body:payload});
        await reloadCell('Метка добавлена');
      } else if (form.matches('[data-comment-form]')) {
        await request(`/api/cell/${activeCell.studentId}/${activeCell.date}/comment`, {method:'POST', body:{text:values.get('text')}});
        await reloadCell('Комментарий отправлен');
      } else if (form.matches('[data-day-event-form]')) {
        const payload = Object.fromEntries(values.entries());
        payload.group_name = window.CALENDAR_DATA.groupName;
        await request('/api/admin/events', {method:'POST', body:payload});
        await refreshDecorations();
        await openDay(activeDay);
        toast('Событие добавлено всей группе');
      } else if (form.matches('[data-day-schedule-form]')) {
        const payload = Object.fromEntries(values.entries());
        payload.group_name = window.CALENDAR_DATA.groupName;
        await request('/api/admin/schedule', {method:'POST', body:payload});
        await refreshDecorations();
        await openDay(activeDay);
        toast('Занятие добавлено в расписание');
      }
    } catch (error) { toast(error.message, true); }
  });
  body.addEventListener('click', async event => {
    const tag = event.target.closest('[data-delete-tag]');
    const comment = event.target.closest('[data-delete-comment]');
    const dayEvent = event.target.closest('[data-delete-event]');
    const scheduleItem = event.target.closest('[data-delete-schedule]');
    try {
      if (tag) {
        await request(`/api/cell/${activeCell.studentId}/${activeCell.date}/tag/${tag.dataset.deleteTag}`, {method:'DELETE'});
        await reloadCell('Метка удалена');
      } else if (comment && confirm('Удалить комментарий?')) {
        await request(`/api/comments/${comment.dataset.deleteComment}`, {method:'DELETE'});
        await reloadCell('Комментарий удалён');
      } else if (dayEvent && confirm('Удалить событие у всей группы?')) {
        await request(`/api/admin/events/${dayEvent.dataset.deleteEvent}`, {method:'DELETE'});
        await refreshDecorations();
        if (activeDay) await openDay(activeDay);
        else if (activeCell) await reloadCell();
        toast('Событие удалено');
      } else if (scheduleItem && confirm('Удалить занятие из расписания на этот день?')) {
        await request(`/api/admin/schedule/${scheduleItem.dataset.deleteSchedule}`, {method:'DELETE'});
        await refreshDecorations();
        if (activeDay) await openDay(activeDay);
        else if (activeCell) await reloadCell();
        toast('Занятие удалено');
      }
    } catch (error) { toast(error.message, true); }
  });

  refreshDecorations();
  applyScale(localStorage.getItem('calendar-scale') || window.CALENDAR_DATA.initialScale);
  const params = new URLSearchParams(location.search);
  const openStudent = params.get('open_student');
  const openDate = params.get('open_date');
  if (openStudent && openDate) {
    const target = document.querySelector(`.calendar-cell[data-student-id="${openStudent}"][data-date="${openDate}"]`);
    if (target) setTimeout(() => openCell(target), 150);
  }
})();
