import { Component, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import {
  IonContent,
  IonHeader,
  IonTitle,
  IonToolbar,
  ToastController,
} from '@ionic/angular/standalone';

import { AppConfigService } from '../../core/app-config.service';
import { BackendApiService } from '../../core/backend-api.service';
import { UserCreateRequest } from '../../core/models';

@Component({
  selector: 'app-auth-page',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    IonHeader,
    IonToolbar,
    IonTitle,
    IonContent,
  ],
  template: `
    <ion-header translucent="true">
      <ion-toolbar color="primary">
        <ion-title>User Management</ion-title>
      </ion-toolbar>
    </ion-header>

    <ion-content [fullscreen]="true" class="ion-padding">
      <div class="container-fluid compact-ui">
        <div class="row g-3">
          <div class="col-12">
            <div class="card shadow-sm border-0">
              <div class="card-header bg-white">
                <div class="text-uppercase text-muted tiny">Guided Access Setup</div>
                <h6 class="mb-0">Create New User with Role</h6>
              </div>
              <div class="card-body">
                <form [formGroup]="form">
                  <div class="row g-2">
                    <div class="col-12 col-md-6">
                      <label class="form-label tiny">User Email</label>
                      <input class="form-control form-control-sm" formControlName="email" placeholder="user@company.com" />
                    </div>
                    <div class="col-12 col-md-6">
                      <label class="form-label tiny">Role</label>
                      <select class="form-select form-select-sm" formControlName="role">
                        <option value="admin">admin</option>
                        <option value="legal_reviewer">legal_reviewer</option>
                        <option value="analyst">analyst</option>
                        <option value="viewer">viewer</option>
                      </select>
                    </div>
                    <div class="col-12 col-md-6 d-flex align-items-center">
                      <div class="form-check mt-2">
                        <input class="form-check-input" type="checkbox" formControlName="generateApiKey" id="auth-generate-key" />
                        <label class="form-check-label tiny" for="auth-generate-key">Generate API key for this user</label>
                      </div>
                    </div>
                    <div class="col-12 col-md-6 d-flex align-items-center">
                      <div class="form-check mt-2">
                        <input class="form-check-input" type="checkbox" formControlName="setAsActive" id="auth-set-active" />
                        <label class="form-check-label tiny" for="auth-set-active">Set generated key as current active key</label>
                      </div>
                    </div>
                    <div class="col-12">
                      <label class="form-label tiny">Scopes (optional, CSV)</label>
                      <input class="form-control form-control-sm" formControlName="scopesCsv" placeholder="leave empty for role defaults" />
                    </div>
                    <div class="col-12 d-flex gap-2">
                      <button type="button" class="btn btn-sm btn-primary" [disabled]="form.invalid || submitting()" (click)="createUserFlow()">
                        Create User
                      </button>
                    </div>
                  </div>
                </form>

                <details class="result-accordion mt-3">
                  <summary>Result Details</summary>
                  <pre class="result-box">{{ resultText() }}</pre>
                </details>
              </div>
            </div>
          </div>
        </div>
      </div>
    </ion-content>
  `,
  styles: [
    `
      .compact-ui {
        font-size: 0.875rem;
      }
      .tiny {
        font-size: 0.75rem;
      }
    `,
  ],
})
export class AuthPageComponent {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(BackendApiService);
  private readonly config = inject(AppConfigService);
  private readonly toast = inject(ToastController);

  readonly submitting = signal(false);
  readonly result = signal<unknown>(null);
  readonly resultText = computed(() => {
    const value = this.result();
    if (!value) {
      return 'Create a user with role and optional API key in one action.';
    }
    if (value instanceof Error) {
      return value.message;
    }
    return JSON.stringify(value, null, 2);
  });

  readonly form = this.fb.nonNullable.group({
    email: ['', [Validators.required, Validators.email]],
    role: ['legal_reviewer', [Validators.required]],
    generateApiKey: [true],
    setAsActive: [false],
    scopesCsv: [''],
  });

  async createUserFlow(): Promise<void> {
    if (this.submitting()) {
      return;
    }

    this.submitting.set(true);
    try {
      const raw = this.form.getRawValue();
      const payload: UserCreateRequest = {
        email: raw.email.trim(),
        role: raw.role as UserCreateRequest['role'],
      };

      const user = await this.api.createUser(payload);
      let keyResponse: unknown = null;

      if (raw.generateApiKey) {
        const scopes = raw.scopesCsv
          .split(',')
          .map((x) => x.trim())
          .filter((x) => x.length > 0);
        const key = await this.api.createApiKey({
          user_id: user.user_id,
          scopes,
        });
        keyResponse = key;
        if (raw.setAsActive) {
          this.config.patch({ apiKey: key.api_key });
        }
      }

      this.result.set({ user, api_key: keyResponse });
      await this.toastMessage('User creation completed');
    } catch (error) {
      const err = error instanceof Error ? error : new Error('Request failed');
      this.result.set(err);
      await this.toastMessage(err.message, 'danger');
    } finally {
      this.submitting.set(false);
    }
  }

  private async toastMessage(message: string, color: 'success' | 'danger' = 'success') {
    const toast = await this.toast.create({
      message,
      color,
      duration: 2200,
      position: 'top',
    });
    await toast.present();
  }
}


