(() => {
  const socket = io({transports:['websocket'], reconnection:true, reconnectionDelay:500, reconnectionDelayMax:5000});
  window.appSocket = socket;
  socket.on('connect', () => window.dispatchEvent(new CustomEvent('realtime:connected')));
  socket.on('disconnect', reason => window.dispatchEvent(new CustomEvent('realtime:disconnected', {detail:{reason}})));
})();
