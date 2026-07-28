import { createContext, useContext, useEffect, useState } from "react";
import { getTelegramUser, isInsideTelegram } from "../lib/telegram";
import { api } from "../lib/api";

const UserContext = createContext(null);

// This is what powers the "dynamic profile button": it always resolves to
// either a real Telegram-backed profile or a `null`/guest profile, never
// leaves the button in a broken/unknown state.
const GUEST_PROFILE = {
  isGuest: true,
  user_id: null,
  first_name: "Guest",
  last_name: "",
  username: null,
  profile_photo: null,
};

export function UserProvider({ children }) {
  const [profile, setProfile] = useState(null); // null while resolving
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;

    async function boot() {
      const tgUser = getTelegramUser();

      if (!isInsideTelegram || !tgUser) {
        if (!cancelled) {
          setProfile(GUEST_PROFILE);
          setLoading(false);
        }
        return;
      }

      try {
        // Backend verifies X-Telegram-Init-Data, upserts the user row, and
        // returns the merged Telegram + database profile (see auth.py).
        const { data } = await api.login();
        if (!cancelled) setProfile(data.user);
      } catch (e) {
        if (!cancelled) {
          setError(e);
          // Fall back to the raw Telegram payload so the UI still has a name
          // and photo to show even if the backend call failed -- but
          // `user_id` stays null rather than the Telegram chat id: they are
          // NOT the same id, and anything that later trusts profile.user_id
          // (e.g. Profile.jsx's /stats, /relations, /tracks calls) would
          // silently 404 against the wrong id instead of it being obvious
          // that login() itself is what actually failed here.
          setProfile({
            isGuest: false,
            user_id: null,
            first_name: tgUser.first_name,
            last_name: tgUser.last_name,
            username: tgUser.username,
            profile_photo: tgUser.photo_url ?? null,
          });
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    boot();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <UserContext.Provider value={{ profile, loading, error }}>
      {children}
    </UserContext.Provider>
  );
}

export function useUser() {
  const ctx = useContext(UserContext);
  if (!ctx) throw new Error("useUser must be used within UserProvider");
  return ctx;
}
