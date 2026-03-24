export function parseSseFrames(buffer) {
  const normalized = buffer.replace(/\r\n/g, "\n");
  const frames = normalized.split("\n\n");
  return {
    frames: frames.slice(0, -1),
    rest: frames.at(-1) || "",
  };
}

export function parseSseEvent(frame) {
  let event = "message";
  const dataLines = [];

  for (const line of frame.split("\n")) {
    if (!line || line.startsWith(":")) {
      continue;
    }
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
      continue;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  }

  const rawData = dataLines.join("\n");
  return {
    event,
    data: rawData ? JSON.parse(rawData) : {},
  };
}
