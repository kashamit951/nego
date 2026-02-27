import { Injectable, signal } from '@angular/core';

import { MeResponse } from './models';

const SESSION_KEY = 'nego_ui_ionic_session_v1';

export interface SessionState {
  loggedInAt: string;
  me: MeResponse;
}

@Injectable({ providedIn: 'root' })
export class SessionService {
  private readonly _session = signal<SessionState | null>(this.load());

  readonly session = this._session.asReadonly();

  setSession(me: MeResponse): void {
    const next: SessionState = {
      loggedInAt: new Date().toISOString(),
      me,
    };
    this._session.set(next);
    this.persist(next);
  }

  clear(): void {
    this._session.set(null);
    if (typeof localStorage !== 'undefined') {
      localStorage.removeItem(SESSION_KEY);
    }
  }

  private load(): SessionState | null {
    if (typeof localStorage === 'undefined') {
      return null;
    }
    const raw = localStorage.getItem(SESSION_KEY);
    if (!raw) {
      return null;
    }
    try {
      return JSON.parse(raw) as SessionState;
    } catch {
      return null;
    }
  }

  private persist(value: SessionState): void {
    if (typeof localStorage === 'undefined') {
      return;
    }
    localStorage.setItem(SESSION_KEY, JSON.stringify(value));
  }
}
