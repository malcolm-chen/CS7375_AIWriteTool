import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';

/** /demo: creates a fresh participant session and jumps into it. */
export function DemoPage() {
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    api
      .startDemo()
      .then(({ id, token }) => navigate(`/session/${id}?t=${encodeURIComponent(token)}`, { replace: true }))
      .catch((e) => setError((e as Error).message));
  }, [navigate]);

  return <p className="center-msg">{error ?? 'Starting a demo session…'}</p>;
}
