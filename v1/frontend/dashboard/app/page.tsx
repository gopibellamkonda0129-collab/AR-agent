"use client";

import { useEffect, useState } from "react";
import { Spinner } from "../lib/components";

export default function Index() {
  const [go, setGo] = useState(false);
  const [stuck, setStuck] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setGo(true), 50);
    return () => clearTimeout(t);
  }, []);
  useEffect(() => {
    if (!go || typeof window === "undefined") return;
    // If this root page was served for a non-root URL (stale server with no
    // redirect), do NOT redirect — otherwise it loops forever.
    const p = window.location.pathname;
    if (p !== "/" && p !== "/index.html") {
      setStuck(true);
      return;
    }
    if (sessionStorage.getItem("ar-redirected")) {
      window.location.replace("/overview/");
      return;
    }
    sessionStorage.setItem("ar-redirected", "1");
    window.location.replace("/overview/");
  }, [go]);
  if (stuck) {
    return (
      <div className="full-center">
        <span className="muted">
          This looks like a stale server. Restart it (<code>python app.py</code>) and open{" "}
          <code>http://127.0.0.1:8000/overview/</code>
        </span>
      </div>
    );
  }
  return (
    <div className="full-center">
      <Spinner />
      <span className="muted">Opening your action queue…</span>
    </div>
  );
}