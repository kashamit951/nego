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
  selector: 'app-register-page',
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
        <ion-title>Company Registration</ion-title>
      </ion-toolbar>
    </ion-header>

    <ion-content [fullscreen]="true" class="auth-page boot-ui">
      <div class="auth-shell">
        <div class="row g-0">
          <div class="col-lg-5 auth-hero p-4 p-md-5 d-flex flex-column justify-content-between">
            <div>
              <span class="auth-chip">Onboarding</span>
              <h2 class="mt-3 fw-bold">Create New Tenant Workspace</h2>
              <p class="mb-0 opacity-90">
                Register company context and bootstrap the first admin account.
              </p>
            </div>
            <div class="small opacity-75">
              Step 1: health check | Step 2: bootstrap admin
            </div>
          </div>

          <div class="col-lg-7 auth-form-pane p-4 p-md-5">
            <div class="auth-title">Registration Flow</div>
            <div class="auth-sub mb-3">All fields are tenant-scoped and saved for subsequent sessions.</div>

            <form [formGroup]="form">
              <div class="data-grid">
                <ion-item class="auth-item">
                  <ion-label position="stacked">Company / Tenant ID</ion-label>
                  <ion-input formControlName="tenantId" placeholder="tenant_acme"></ion-input>
                </ion-item>
                <ion-item class="auth-item">
                  <ion-label position="stacked">Bootstrap Token</ion-label>
                  <ion-input formControlName="bootstrapToken" type="password"></ion-input>
                </ion-item>
                <ion-item class="auth-item">
                  <ion-label position="stacked">Admin Email</ion-label>
                  <ion-input formControlName="adminEmail" placeholder="admin@company.com"></ion-input>
                </ion-item>
              </div>

              <div class="auth-actions mt-2">
                <ion-button type="button" color="primary" expand="block" [disabled]="form.invalid || loading()" (click)="registerCompany()">
                  Complete Registration
                </ion-button>
                <ion-button type="button" color="medium" fill="outline" expand="block" (click)="goToLogin()">
                  Back to Login
                </ion-button>
              </div>
            </form>

            <details class="result-accordion mt-3">
              <summary>Result Details</summary>
              <pre class="result-box">{{ resultText() }}</pre>
            </details>
          </div>
        </div>
      </div>
    </ion-content>
  `,
})
export class RegisterPageComponent {
  private readonly fb = inject(FormBuilder);
  readonly config = inject(AppConfigService);
  private readonly api = inject(BackendApiService);
  private readonly session = inject(SessionService);
  private readonly router = inject(Router);
  private readonly toast = inject(ToastController);

  readonly loading = signal(false);
  readonly resultText = signal('Run registration to initialize tenant and bootstrap admin.');

  readonly form = this.fb.nonNullable.group({
    tenantId: ['', [Validators.required]],
    bootstrapToken: ['', [Validators.required]],
    adminEmail: ['', [Validators.required, Validators.email]],
  });

  async registerCompany(): Promise<void> {
    if (this.loading()) {
      return;
    }
    this.loading.set(true);
    try {
      const raw = this.form.getRawValue();
      this.config.patch({
        tenantId: raw.tenantId.trim(),
        bootstrapToken: raw.bootstrapToken.trim(),
        apiKey: '',
      });

      const health = await this.api.health();
      const bootstrap = await this.api.bootstrapAdmin({ email: raw.adminEmail.trim(), role: 'admin' });
      this.config.patch({ apiKey: bootstrap.api_key });

      const me = await this.api.me();
      this.session.setSession(me);
      this.resultText.set(
        JSON.stringify(
          {
            registration: 'ok',
            health,
            bootstrap_admin: bootstrap,
            active_session: me,
          },
          null,
          2,
        ),
      );
      await this.toastMessage('Tenant registration complete');
      await this.router.navigateByUrl('/upload-suggest');
    } catch (error) {
      this.resultText.set(error instanceof Error ? error.message : 'Registration failed');
      await this.toastMessage(this.resultText(), 'danger');
    } finally {
      this.loading.set(false);
    }
  }

  async goToLogin(): Promise<void> {
    await this.router.navigateByUrl('/login');
  }

  private async toastMessage(message: string, color: 'success' | 'danger' = 'success') {
    const toast = await this.toast.create({
      message,
      color,
      duration: 2500,
      position: 'top',
    });
    await toast.present();
  }
}

