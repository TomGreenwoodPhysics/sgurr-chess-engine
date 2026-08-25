async function readNdjson(response, onEvent) {
  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error("This browser cannot read the live search stream");
  }

  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (line.trim()) {
        onEvent(JSON.parse(line));
      }
    }
    if (done) {
      break;
    }
  }
  if (buffer.trim()) {
    onEvent(JSON.parse(buffer));
  }
}

export { readNdjson };
