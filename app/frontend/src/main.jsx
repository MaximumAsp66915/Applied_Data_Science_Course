import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { UserProvider } from "./context/UserContext";
import { PlayerProvider } from "./context/PlayerContext";
import { initTelegram } from "./lib/telegram";
import "./index.css";

initTelegram();

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <UserProvider>
        <PlayerProvider>
          <App />
        </PlayerProvider>
      </UserProvider>
    </BrowserRouter>
  </React.StrictMode>
);
