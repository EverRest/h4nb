// Sends the token of this server with every /api/ request. The server writes the token into the page.
// Other origins cannot read the page, so they cannot read the token (see server.py).
const TOKEN = document.querySelector('meta[name="h4nb-token"]')?.content || "";
const nativeFetch = window.fetch.bind(window);

window.fetch = (input, init = {}) => {
  const url = typeof input === "string" ? input : input.url;
  if (url.startsWith("/api/")) {
    const headers = new Headers(init.headers || {});
    headers.set("X-H4NB-Token", TOKEN);
    init = { ...init, headers };
  }
  return nativeFetch(input, init);
};
