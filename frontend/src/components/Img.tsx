import { useState } from "react";

/** Listing photo with a branded placeholder when the image host is unreachable (offline, low bandwidth). */
export default function Img({ src, alt, caption, className }: { src?: string; alt: string; caption?: string; className?: string }) {
  const [failed, setFailed] = useState(!src);
  if (failed)
    return (
      <div className={`img-fallback ${className ?? ""}`} role="img" aria-label={alt}>
        <span>{caption ?? alt}</span>
      </div>
    );
  return <img className={className} src={src} alt={alt} loading="lazy" onError={() => setFailed(true)} />;
}
