// Movie recording and file export of h4nb-viz (S2, S3, research R5).
// MediaRecorder writes WebM. Safari writes MP4. The server adds MP4 when ffmpeg exists (T026).

const MIME_CANDIDATES = ["video/webm;codecs=vp9", "video/webm", "video/mp4"];

export function pickMimeType() {
  if (typeof MediaRecorder === "undefined") return "";
  return MIME_CANDIDATES.find((type) => MediaRecorder.isTypeSupported(type)) || "";
}

export function extensionFor(mime) {
  return mime.startsWith("video/mp4") ? "mp4" : "webm";
}

// Records the canvas at 30 frames per second. Call stop() to get the movie as a Blob.
export class Recorder {
  constructor(canvas) {
    this.canvas = canvas;
    this.recorder = null;
    this.chunks = [];
    this.mime = "";
  }

  start() {
    this.mime = pickMimeType();
    if (!this.mime) throw new Error("this browser cannot record video");
    this.chunks = [];
    const stream = this.canvas.captureStream(30);
    this.recorder = new MediaRecorder(stream, { mimeType: this.mime });
    this.recorder.addEventListener("dataavailable", (event) => {
      if (event.data.size > 0) this.chunks.push(event.data);
    });
    this.recorder.start(1000);
  }

  stop() {
    return new Promise((resolve) => {
      this.recorder.addEventListener("stop", () => {
        resolve({ blob: new Blob(this.chunks, { type: this.mime }), mime: this.mime });
      }, { once: true });
      this.recorder.stop();
    });
  }
}

// Save a Blob or a data URL as a file download.
export function saveFile(name, source) {
  const url = typeof source === "string" ? source : URL.createObjectURL(source);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  if (typeof source !== "string") setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// Send a file to the server. The server writes it into the export directory and returns its path.
export async function uploadExport(name, blob) {
  const response = await fetch(`/api/export?name=${encodeURIComponent(name)}`, {
    method: "POST",
    headers: { "Content-Type": blob.type || "application/octet-stream" },
    body: blob,
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
  return body;
}

export function stamp() {
  return new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
}
