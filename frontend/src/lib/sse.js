/**
 * Read a text/event-stream body from fetch(). Unlike EventSource this works with POST
 * bodies and AbortController, which the editor needs to cancel a stale generation.
 */
export async function readSSE(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf('\n\n')) !== -1) {
      const raw = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      let event = 'message';
      let data = '';
      for (const line of raw.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim();
        else if (line.startsWith('data:')) data += line.slice(5).trimStart();
      }
      if (!data) continue;
      let parsed = data;
      try { parsed = JSON.parse(data); } catch { /* plain-text event */ }
      onEvent(event, parsed);
    }
  }
}
