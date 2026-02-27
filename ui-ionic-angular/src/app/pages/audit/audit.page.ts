import { CommonModule } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import {
  IonContent,
  IonHeader,
  IonTitle,
  IonToolbar,
  ToastController,
} from '@ionic/angular/standalone';

import { BackendApiService } from '../../core/backend-api.service';
import { AuditLogListResponse } from '../../core/models';

@Component({
  selector: 'app-audit-page',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    IonHeader,
    IonToolbar,
    IonTitle,
    IonContent,
  ],
  template: `
    <ion-header translucent="true">
      <ion-toolbar color="primary">
        <ion-title>Audit Logs</ion-title>
      </ion-toolbar>
    </ion-header>

    <ion-content [fullscreen]="true" class="ion-padding">
      <div class="container-fluid compact-ui">
        <div class="row g-3">
          <div class="col-12">
            <div class="card shadow-sm border-0">
              <div class="card-header bg-white">
                <div class="text-uppercase text-muted tiny">Audit Query</div>
                <h6 class="mb-0">Activity Log Search</h6>
              </div>
              <div class="card-body">
                <form [formGroup]="auditForm">
                  <div class="row g-2">
                    <div class="col-12 col-md-4">
                      <label class="form-label tiny">Limit</label>
                      <input class="form-control form-control-sm" type="number" formControlName="limit" />
                    </div>
                    <div class="col-12 col-md-4">
                      <label class="form-label tiny">Action (optional)</label>
                      <input class="form-control form-control-sm" formControlName="action" placeholder="strategy.suggest" />
                    </div>
                    <div class="col-12 col-md-4">
                      <label class="form-label tiny">Actor User ID (optional)</label>
                      <input class="form-control form-control-sm" formControlName="actor_user_id" placeholder="UUID" />
                    </div>
                    <div class="col-12 d-flex gap-2">
                      <button type="button" class="btn btn-sm btn-primary" [disabled]="auditForm.invalid" (click)="loadLogs()">Fetch Logs</button>
                    </div>
                  </div>
                </form>

                <div class="tiny text-muted mt-2" *ngIf="auditSummary()">Returned {{ auditSummary()?.count }} rows.</div>

                <details class="result-accordion mt-3">
                  <summary>Result Details</summary>
                  <pre class="result-box">{{ logsText() }}</pre>
                </details>
              </div>
            </div>

            <div class="card shadow-sm border-0 mt-3" *ngIf="auditSummary()?.items?.length">
              <div class="card-header bg-white">
                <h6 class="mb-0">Readable Log List</h6>
              </div>
              <div class="card-body">
                <div class="list-group list-group-flush">
                  <div class="list-group-item" *ngFor="let item of auditSummary()?.items">
                    <div class="fw-semibold">{{ item.action }} | {{ item.resource_type }}</div>
                    <div class="tiny">Time: {{ item.created_at }}</div>
                    <div class="tiny">Actor: {{ item.actor_user_id || 'N/A' }}</div>
                    <div class="tiny">Request: {{ item.request_id || 'N/A' }} | IP: {{ item.ip_address || 'N/A' }}</div>
                    <div class="tiny">Resource ID: {{ item.resource_id || 'N/A' }}</div>
                    <div class="tiny">Metadata: {{ item.metadata | json }}</div>
                  </div>
                </div>
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
export class AuditPageComponent {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(BackendApiService);
  private readonly toast = inject(ToastController);

  readonly logs = signal<AuditLogListResponse | Error | null>(null);
  readonly logsText = computed(() => this.pretty(this.logs()));
  readonly auditSummary = computed(() =>
    this.logs() && !(this.logs() instanceof Error) ? (this.logs() as AuditLogListResponse) : null,
  );

  readonly auditForm = this.fb.nonNullable.group({
    limit: ['50', [Validators.required]],
    action: [''],
    actor_user_id: [''],
  });

  async loadLogs(): Promise<void> {
    try {
      const raw = this.auditForm.getRawValue();
      const limit = Number(raw.limit);
      if (!Number.isInteger(limit) || limit <= 0 || limit > 200) {
        throw new Error('limit must be an integer between 1 and 200');
      }
      this.logs.set(
        await this.api.auditLogs({
          limit,
          action: raw.action.trim() || undefined,
          actor_user_id: raw.actor_user_id.trim() || undefined,
        }),
      );
      await this.toastMessage('Audit logs loaded');
    } catch (error) {
      this.logs.set(this.asError(error));
      await this.toastMessage(this.asError(error).message, 'danger');
    }
  }

  private pretty(value: unknown): string {
    if (!value) {
      return 'No request run yet.';
    }
    if (value instanceof Error) {
      return value.message;
    }
    return JSON.stringify(value, null, 2);
  }

  private asError(error: unknown): Error {
    return error instanceof Error ? error : new Error('Request failed');
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


