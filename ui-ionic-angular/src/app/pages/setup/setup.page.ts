import { Component, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
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
  IonNote,
  IonTitle,
  IonToolbar,
  ToastController,
} from '@ionic/angular/standalone';

import { AppConfigService } from '../../core/app-config.service';
import { BackendApiService } from '../../core/backend-api.service';
import { HealthResponse } from '../../core/models';

@Component({
  selector: 'app-setup-page',
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
    IonNote,
  ],
  template: `
    <ion-header translucent="true">
      <ion-toolbar color="primary">
        <ion-title>Setup and Health</ion-title>
      </ion-toolbar>
    </ion-header>

    <ion-content [fullscreen]="true" class="ion-padding boot-ui">
      <div class="page-shell">
        <ion-card class="section-card">
          <ion-card-header>
            <ion-card-subtitle>Global API Context</ion-card-subtitle>
            <ion-card-title>Connection and Tenant Headers</ion-card-title>
          </ion-card-header>
          <ion-card-content>
            <form [formGroup]="setupForm" class="page-shell">
              <ion-item>
                <ion-label position="stacked">Tenant ID</ion-label>
                <ion-input formControlName="tenantId" placeholder="tenant_acme"></ion-input>
              </ion-item>
              <ion-item>
                <ion-label position="stacked">API Key</ion-label>
                <ion-input type="password" formControlName="apiKey" placeholder="nego_xxx_yyy"></ion-input>
              </ion-item>
              <ion-item>
                <ion-label position="stacked">Bootstrap Token</ion-label>
                <ion-input type="password" formControlName="bootstrapToken" placeholder="Provided by your organization"></ion-input>
              </ion-item>

              <div class="data-grid">
                <ion-button type="button" color="primary" (click)="saveConfig()" [disabled]="setupForm.invalid">Save Configuration</ion-button>
                <ion-button type="button" color="secondary" (click)="checkHealth()">Run Health Check</ion-button>
                <ion-button type="button" color="medium" fill="outline" (click)="resetConfig()">Reset</ion-button>
              </div>
            </form>

            <ion-note color="medium">
              This page controls headers used by all other pages: X-Tenant-Id, X-Api-Key, and bootstrap token.
            </ion-note>
          </ion-card-content>
        </ion-card>

        <ion-card class="section-card">
          <ion-card-header>
            <ion-card-title>Health Result</ion-card-title>
          </ion-card-header>
          <ion-card-content>
            <details class="result-accordion">
              <summary>Result Details</summary>
              <pre class="result-box">{{ healthResultText() }}</pre>
            </details>
          </ion-card-content>
        </ion-card>
      </div>
    </ion-content>
  `,
})
export class SetupPageComponent {
  private readonly fb = inject(FormBuilder);
  private readonly appConfig = inject(AppConfigService);
  private readonly api = inject(BackendApiService);
  private readonly toast = inject(ToastController);

  readonly config = this.appConfig.config;
  readonly healthResult = signal<HealthResponse | Error | null>(null);
  readonly healthResultText = computed(() => {
    const value = this.healthResult();
    if (!value) {
      return 'No checks run yet.';
    }
    if (value instanceof Error) {
      return value.message;
    }
    return JSON.stringify(value, null, 2);
  });

  readonly setupForm = this.fb.nonNullable.group({
    tenantId: [this.config().tenantId, [Validators.required]],
    apiKey: [this.config().apiKey],
    bootstrapToken: [this.config().bootstrapToken],
  });

  async saveConfig(): Promise<void> {
    this.appConfig.patch(this.setupForm.getRawValue());
    await this.toastMessage('Configuration saved');
  }

  async checkHealth(): Promise<void> {
    await this.saveConfig();
    try {
      const result = await this.api.health();
      this.healthResult.set(result);
      await this.toastMessage('Health check succeeded');
    } catch (error) {
      this.healthResult.set(error instanceof Error ? error : new Error('Health check failed'));
      await this.toastMessage(this.healthResultText(), 'danger');
    }
  }

  async resetConfig(): Promise<void> {
    this.appConfig.reset();
    this.setupForm.setValue({
      tenantId: this.appConfig.config().tenantId,
      apiKey: this.appConfig.config().apiKey,
      bootstrapToken: this.appConfig.config().bootstrapToken,
    });
    this.healthResult.set(null);
    await this.toastMessage('Configuration reset');
  }

  private async toastMessage(message: string, color: 'success' | 'danger' | 'medium' = 'success') {
    const toast = await this.toast.create({
      message,
      duration: 1800,
      position: 'top',
      color,
    });
    await toast.present();
  }
}


