// Run with: node --test tests/js/notifications.test.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const vm = require('node:vm');

const source = readFileSync(join(__dirname, '../../app/static/js/notifications.js'), 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));
const notification = id => ({id, text: `Notification ${id}`, actor: 'Student',
  target_url: `/materials?subject=1&material=${id}`, created_at: '2026-09-06T12:00:00Z'});
const reply = data => ({ok: true, json: async () => data});

function page(fetch, socket) {
  const element = dataset => ({dataset, innerHTML: '', textContent: '', handlers: {},
    classList: {toggle() {}},
    addEventListener(name, handler) { this.handlers[name] = handler; },
    replaceChildren() {}, querySelector() { return null; },
    insertAdjacentHTML(_position, html) { this.innerHTML = html + this.innerHTML; },
  });
  const active = element({notificationList: 'active'});
  const history = element({notificationList: 'history'});
  const count = element({});
  const toggle = element({});
  const historyTab = element({});
  const handlers = {};
  const document = {
    querySelectorAll: selector => selector === '[data-notification-list]' ? [active, history] : [],
    querySelector: selector => ({
      '[data-notification-toggle]': toggle, '.notification-count': count,
      '[data-bs-target="#notificationHistory"]': historyTab,
    })[selector] || null,
    addEventListener: (name, handler) => { handlers[name] = handler; },
  };
  const location = {};
  vm.runInNewContext(source, {window: {appSocket: socket}, document, fetch, location,
    AbortController, setTimeout, clearTimeout});
  return {active, history, count, toggle, handlers, location};
}

test('remaining notifications load after navigation without a WebSocket connection', async () => {
  const items = [notification(1), notification(2)];
  const fetch = async (url, options) => {
    if (options.method === 'POST') {
      const item = items.find(item => url === `/api/notifications/${item.id}/read`);
      item.is_read = true;
      return reply({target_url: item.target_url});
    }
    assert.equal(options.cache, 'no-store');
    const history = url.endsWith('status=history');
    return reply({unread: items.filter(item => !item.is_read).length,
      notifications: items.filter(item => Boolean(item.is_read) === history)});
  };
  const first = page(fetch, {connected: false, on() {}});
  await flush();
  assert.match(first.active.innerHTML, /Notification 1/);
  const button = {dataset: {openNotification: '1'}};
  await first.handlers.click({target: {closest: selector => selector.includes('data-open-notification') ? button : null}});
  assert.equal(first.location.href, items[0].target_url);

  const next = page(fetch); // Socket.IO may still be loading on the destination page.
  next.toggle.handlers.click();
  await flush();
  assert.match(next.active.innerHTML, /Notification 2/);
  assert.doesNotMatch(next.active.innerHTML, /Notification 1/);
  assert.match(next.history.innerHTML, /Notification 1/);
  assert.equal(next.count.textContent, 1);
});

test('a connected socket with no acknowledgement does not block the panel; live push remains', async () => {
  const handlers = {};
  const socket = {connected: true, on(name, handler) { handlers[name] = handler; },
    timeout() { throw new Error('The list must not depend on socket acknowledgements'); }};
  const view = page(async () => reply({unread: 0, notifications: []}), socket);
  await flush();
  assert.match(view.active.innerHTML, /Активных уведомлений нет/);
  handlers['notification:new'](notification(3));
  assert.match(view.active.innerHTML, /Notification 3/);
  assert.equal(view.count.textContent, 1);
});

test('HTTP failures can be retried without reloading the page', async () => {
  let fail = true;
  const view = page(async () => fail ? {ok: false} : reply({unread: 1, notifications: [notification(4)]}));
  await flush();
  assert.match(view.active.innerHTML, /data-retry-notifications="active"/);
  fail = false;
  await view.handlers.click({target: {closest: () => ({dataset: {retryNotifications: 'active'}})}});
  await flush();
  assert.match(view.active.innerHTML, /Notification 4/);
  assert.doesNotMatch(view.active.innerHTML, /Не удалось/);
});

test('an older HTTP response cannot overwrite a newer panel refresh', async () => {
  let resolveOld;
  let calls = 0;
  const view = page(async url => {
    if (url.endsWith('status=active') && calls++ === 0) return new Promise(resolve => { resolveOld = resolve; });
    return reply({unread: 0, notifications: []});
  });
  view.toggle.handlers.click();
  await flush();
  resolveOld(reply({unread: 1, notifications: [notification(5)]}));
  await flush();
  assert.doesNotMatch(view.active.innerHTML, /Notification 5/);
  assert.equal(view.count.textContent, 0);
});
