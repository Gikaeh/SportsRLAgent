import { useState } from "react";

type Props = { logo: string | null; abbr: string; size?: number };

/** ESPN logo with a text badge fallback (offline, mock mode, or a missing URL). */
export function TeamLogo({ logo, abbr, size = 32 }: Props) {
  const [failed, setFailed] = useState(false);
  if (!logo || failed) {
    return (
      <span className="logo-fallback" style={{ width: size, height: size, fontSize: size * 0.32 }} aria-hidden="true">
        {abbr}
      </span>
    );
  }
  return (
    <img
      className="logo"
      src={logo}
      alt=""
      width={size}
      height={size}
      loading="lazy"
      decoding="async"
      onError={() => setFailed(true)}
    />
  );
}
