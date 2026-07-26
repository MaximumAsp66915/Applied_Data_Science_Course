// Thin wrapper around the Telegram WebApp JS bridge (window.Telegram.WebApp).
// SUT Music is opened as a Telegram Mini App from the bot's menu button / inline
// button, which is what gives us `initData` (signed) and `initDataUnsafe.user`.

const tg = typeof window !== "undefined" ? window.Telegram?.WebApp : null;

export function initTelegram() {
  if (!tg) return null;
  tg.ready();
  tg.expand();
  try {
    tg.setHeaderColor("#14121C");
    tg.setBackgroundColor("#14121C");
  } catch (e) {
    // older clients may not support these calls
  }
  return tg;
}

// The Mini App user object Telegram gives us for free (name, username, photo).
// This is what powers the "dynamic profile button" -- if it's missing (e.g. the
// app was opened outside Telegram, in a browser, during local dev) we fall back
// to a null/guest profile everywhere in the UI.
export function getTelegramUser() {
  return tg?.initDataUnsafe?.user ?? null;
}

// Whatever was appended after `?startapp=` on the https://t.me/{bot}?startapp=...
// link that opened this Mini App (e.g. "track_123"), or null if it was opened
// any other way (menu button, direct chat button, local dev). This is what
// lets a shared song link put the user straight onto that song's page -- see
// the deep-link redirect in App.jsx.
export function getStartParam() {
  return tg?.initDataUnsafe?.start_param ?? null;
}

// Raw signed init data string. This MUST be sent as the `X-Telegram-Init-Data`
// header on every API call so the backend can verify the request really came
// from Telegram (HMAC check against the bot token) and extract the telegram_id
// server-side -- never trust a client-supplied user id directly.
export function getInitData() {
  return tg?.initData ?? "";
}

// Native Telegram popup -- used for one-off confirmations/warnings (e.g.
// the download button's "sent!" / "start the bot first" messages) so we
// don't need to build/maintain our own toast component for this. Falls back
// to a plain browser alert outside Telegram (local dev in a normal tab).
export function showAlert(message) {
  if (tg?.showAlert) {
    tg.showAlert(message);
  } else if (typeof window !== "undefined") {
    window.alert(message);
  }
}

export function hapticImpact(style = "light") {
  tg?.HapticFeedback?.impactOccurred(style);
}

export function hapticSelection() {
  tg?.HapticFeedback?.selectionChanged();
}

export function showBackButton(onClick) {
  if (!tg) return () => {};
  tg.BackButton.show();
  tg.BackButton.onClick(onClick);
  return () => {
    tg.BackButton.offClick(onClick);
    tg.BackButton.hide();
  };
}

export function hideBackButton() {
  tg?.BackButton.hide();
}

export const isInsideTelegram = Boolean(tg && tg.initData);
