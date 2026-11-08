// The API token of this server. The server sends it once, in the URL fragment of the page
// (#token=...). This module moves it to sessionStorage, removes the fragment from the address,
// and sends the token in the X-H4NB-Token header of every /api/ request.
// The token is not in the page source and not in any cookie.
const KEY = "h4nb-viz.token";
let memoryToken = "";

function storeToken(token) {
  memoryToken = token;
  try {
    sessionStorage.setItem(KEY, token);
  } catch (error) {
    // Storage can be blocked. The token then lasts until the page is reloaded.
  }
}

function readToken() {
  if (memoryToken) return memoryToken;
  try {
    return sessionStorage.getItem(KEY) || "";
  } catch (error) {
    return "";
  }
}

const fragmentToken = new URLSearchParams(location.hash.slice(1)).get("token");
if (fragmentToken) {
  storeToken(fragmentToken);
  history.replaceState(null, "", location.pathname + location.search);
}

export function hasToken() {
  return readToken() !== "";
}

const nativeFetch = window.fetch.bind(window);

window.fetch = (input, init = {}) => {
  const url = typeof input === "string" ? input : input.url;
  if (url.startsWith("/api/")) {
    const headers = new Headers(init.headers || {});
    headers.set("X-H4NB-Token", readToken());
    init = { ...init, headers };
  }
  return nativeFetch(input, init);
};
