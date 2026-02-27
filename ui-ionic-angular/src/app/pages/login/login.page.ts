import { Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router } from '@angular/router';
import {
  IonButton,
  IonCard,
  IonCardContent,
  IonCardHeader,
  IonCardSubtitle,
  IonCardTitle,
  IonContent,
  IonHeader,
  IonInput,
  IonItem,
  IonLabel,
  IonTitle,
  IonToolbar,
  ToastController,
} from '@ionic/angular/standalone';

import { AppConfigService } from '../../core/app-config.service';
import { BackendApiService } from '../../core/backend-api.service';
import { SessionService } from '../../core/session.service';

@Component({
  selector: 'app-login-page',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    IonHeader,
    IonToolbar,
    IonTitle,
    IonContent,
    IonCard,
    IonCardHeader,
    IonCardTitle,
    IonCardSubtitle,
    IonCardContent,
    IonItem,
    IonLabel,
    IonInput,
    IonButton,
  ],
  template: `
    <ion-header translucent="true">
      <ion-toolbar color="primary">
        <ion-title>Sign In</ion-title>
      </ion-toolbar>
    </ion-header>

    <ion-content [fullscreen]="true" class="auth-page boot-ui">
      <div class="auth-shell">
        <div class="row g-0">
          <div class="col-lg-5 auth-hero p-4 p-md-5 d-flex flex-column justify-content-between">
            <div>
              <span class="auth-chip">Contract Intelligence Platform</span>
              <h2 class="mt-3 fw-bold">Tenant Workspace Login</h2>
              <p class="mb-0 opacity-90">
                Authenticate with tenant credentials and continue into your negotiation operations dashboard.
              </p>
            </div>
            <div class="small opacity-75">
              Secure tenant context | RBAC enforcement | Audit ready
            </div>
          </div>

          <div class="col-lg-7 auth-form-pane p-4 p-md-5">
            <div class="auth-title">Welcome Back</div>
            <div class="auth-sub mb-3">Use the API identity issued for your tenant.</div>

            <form [formGroup]="form">
              <ion-item class="auth-item">
                <ion-label position="stacked">Tenant ID</ion-label>
                <ion-input formControlName="tenantId" placeholder="tenant_acme"></ion-input>
              </ion-item>
              <ion-item class="auth-item">
                <ion-label position="stacked">API Key</ion-label>
                <ion-input formControlName="apiKey" type="password" placeholder="nego_xxx_xxx"></ion-input>
              </ion-item>

              <div class="auth-actions mt-2">
                <ion-button type="button" color="primary" expand="block" [disabled]="form.invalid || loading()" (click)="login()">
                  Sign In
                </ion-button>
                <ion-button type="button" color="tertiary" fill="outline" expand="block" (click)="goToRegister()">
                  Create Company / Tenant
                </ion-button>
              </div>
            </form>

            <details class="result-accordion mt-3">
              <summary>Result Details</summary>
              <pre class="result-box">{{ status() }}</pre>
            </details>
          </div>
        </div>
      </div>
    </ion-content>
  `,
})
export class LoginPageComponent {
  private readonly fb = inject(FormBuilder);
  readonly config = inject(AppConfigService);
  private readonly api = inject(BackendApiService);
  private readonly session = inject(SessionService);
  private readonly router = inject(Router);
  private readonly toast = inject(ToastController);

  readonly loading = signal(false);
  readonly status = signal('Sign in with tenant credentials.');

  readonly form = this.fb.nonNullable.group({
    tenantId: [this.config.config().tenantId, [Validators.required]],
    apiKey: [this.config.config().apiKey, [Validators.required]],
  });

  async login(): Promise<void> {
    if (this.loading()) {
      return;
    }
    this.loading.set(true);
    try {
      const raw = this.form.getRawValue();
      this.config.patch({
        tenantId: raw.tenantId.trim(),
        apiKey: raw.apiKey.trim(),
      });
      const me = await this.api.me();
      this.session.setSession(me);
      this.status.set(`Signed in as ${me.email} (${me.role}) for ${me.tenant_id}`);
      await this.toastMessage('Login successful');
      await this.router.navigateByUrl('/upload-suggest');
    } catch (error) {
      this.status.set(error instanceof Error ? error.message : 'Login failed');
      await this.toastMessage(this.status(), 'danger');
    } finally {
      this.loading.set(false);
    }
  }

  async goToRegister(): Promise<void> {
    await this.router.navigateByUrl('/register');
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

