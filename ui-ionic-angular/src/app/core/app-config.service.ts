import { Injectable, signal } from '@angular/core';
import { environment } from '../../environments/environment';

import { ClientConfig } from './models';

const STORAGE_KEY = 'nego_frontend_config_v1';

const DEFAULT_CONFIG: ClientConfig = {
  apiBaseUrl: environment.apiBaseUrl,
  tenantId: '',
  apiKey: '',
  bootstrapToken: '',
};

@Injectable({ providedIn: 'root' })
export class AppConfigService {
  private readonly _config = signal<ClientConfig>(this.load());

  readonly config = this._config.asReadonly();

  patch(partial: Partial<ClientConfig>): void {
    const sanitized = { ...partial, apiBaseUrl: environment.apiBaseUrl };
    const next = { ...this._config(), ...sanitized };
    this._config.set(next);
    this.persist(next);
  }

  reset(): void {
    this._config.set(DEFAULT_CONFIG);
    this.persist(DEFAULT_CONFIG);
  }

  private load(): ClientConfig {
    if (typeof localStorage === 'undefined') {
      return DEFAULT_CONFIG;
    }

    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return DEFAULT_CONFIG;
    }

    try {
      const parsed = JSON.parse(raw) as Partial<ClientConfig>;
      return {
        ...DEFAULT_CONFIG,
        ...parsed,
        apiBaseUrl: environment.apiBaseUrl,
      };
    } catch {
      return DEFAULT_CONFIG;
    }
  }

  private persist(value: ClientConfig): void {
    if (typeof localStorage === 'undefined') {
      return;
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  }
}
