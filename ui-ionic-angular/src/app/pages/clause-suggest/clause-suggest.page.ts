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
import { StrategySuggestUploadResponse, UploadedClauseSuggestion } from '../../core/models';

@Component({
  selector: 'app-clause-suggest-page',
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
        <ion-title>Clause Suggest</ion-title>
      </ion-toolbar>
    </ion-header>
    <ion-content [fullscreen]="true" class="ion-padding">
      <div class="container-fluid compact-ui">
        <div class="row g-3">
          <div class="col-12">
            <div class="card shadow-sm border-0">
              <div class="card-header bg-white">
                <div class="text-uppercase text-muted tiny">Secondary Workflow</div>
                <h6 class="mb-0">Clause-by-Clause Suggestion</h6>
              </div>
              <div class="card-body">
                <form [formGroup]="form" class="page-shell">
                  <div class="data-grid">
                    <div>
                      <label class="form-label tiny">Analysis Scope</label>
                      <select class="form-select form-select-sm" formControlName="analysis_scope">
                        <option value="single_client">single_client</option>
                        <option value="all_clients">all_clients</option>
                      </select>
                    </div>
                    <div>
                      <label class="form-label tiny">Client ID</label>
                      <input class="form-control form-control-sm" formControlName="client_id" placeholder="client_acme" />
                    </div>
                    <div>
                      <label class="form-label tiny">Doc Type (optional)</label>
                      <input class="form-control form-control-sm" formControlName="doc_type" />
                    </div>
                    <div>
                      <label class="form-label tiny">Counterparty</label>
                      <input class="form-control form-control-sm" formControlName="counterparty_name" />
                    </div>
                    <div>
                      <label class="form-label tiny">Clause Type</label>
                      <input class="form-control form-control-sm" formControlName="clause_type" />
                    </div>
                    <div>
                      <label class="form-label tiny">Top K</label>
                      <input class="form-control form-control-sm" type="number" formControlName="top_k" />
                    </div>
                    <div>
                      <label class="form-label tiny">Max Clauses</label>
                      <input class="form-control form-control-sm" type="number" formControlName="max_clauses" />
                    </div>
                  </div>
                  <div>
                    <label class="form-label tiny">Document File</label>
                    <input type="file" accept=".docx,.pdf,.txt,.md,.rtf" (change)="onFileChange($event)" />
                  </div>
                  <button type="button" class="btn btn-sm btn-primary" [disabled]="!canSubmit()" (click)="generate()">
                    Generate Clause Suggestions
                  </button>
                </form>
              </div>
            </div>

            <div class="card shadow-sm border-0 mt-3" *ngIf="rows().length > 0">
              <div class="card-header bg-white">
                <div class="text-uppercase text-muted tiny">Clause Output</div>
                <h6 class="mb-0">{{ summary()?.file_name }}</h6>
              </div>
              <div class="card-body">
                <div class="tiny text-muted mb-2">Clause suggestions are secondary to negotiation flow suggestions.</div>
                <div class="list-group list-group-flush">
                  <div class="list-group-item d-flex justify-content-between align-items-start" *ngFor="let row of rows()">
                    <div>
                      <div class="fw-semibold">Clause {{ row.clause_index + 1 }}</div>
                      <div class="tiny"><strong>Incoming:</strong> {{ row.clause_text }}</div>
                      <div class="tiny"><strong>Proposed:</strong> {{ row.suggestion.proposed_redline }}</div>
                      <div class="tiny"><strong>Fallback:</strong> {{ row.suggestion.fallback_position }}</div>
                    </div>
                    <span class="badge text-bg-secondary">Risk {{ row.suggestion.risk_score }}</span>
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
export class ClauseSuggestPageComponent {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(BackendApiService);
  private readonly toast = inject(ToastController);
  private readonly selectedFile = signal<File | null>(null);
  readonly result = signal<StrategySuggestUploadResponse | Error | null>(null);

  readonly form = this.fb.nonNullable.group({
    analysis_scope: ['single_client', [Validators.required]],
    client_id: [''],
    doc_type: [''],
    counterparty_name: [''],
    clause_type: [''],
    top_k: ['4', [Validators.required]],
    max_clauses: ['4', [Validators.required]],
  });

  readonly summary = computed(() =>
    this.result() && !(this.result() instanceof Error) ? (this.result() as StrategySuggestUploadResponse) : null,
  );
  readonly rows = computed<UploadedClauseSuggestion[]>(() => this.summary()?.clause_suggestions ?? []);
  readonly canSubmit = computed(() => this.form.valid && !!this.selectedFile());

  onFileChange(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.selectedFile.set(input.files && input.files.length > 0 ? input.files[0] : null);
  }

  async generate(): Promise<void> {
    try {
      const file = this.selectedFile();
      if (!file) {
        throw new Error('Select a file');
      }
      const raw = this.form.getRawValue();
      const response = await this.api.suggestStrategyFromUpload({
        file,
        analysis_scope: raw.analysis_scope as 'single_client' | 'all_clients',
        client_id: raw.client_id.trim() || null,
        doc_type: raw.doc_type.trim() || null,
        counterparty_name: raw.counterparty_name.trim() || null,
        contract_value: null,
        clause_type: raw.clause_type.trim() || null,
        top_k: this.parseRequiredInt(raw.top_k, 'top_k', 1, 50),
        max_clauses: this.parseRequiredInt(raw.max_clauses, 'max_clauses', 1, 100),
      });
      this.result.set(response);
      await this.toastMessage('Clause suggestions generated');
    } catch (error) {
      this.result.set(error instanceof Error ? error : new Error('Request failed'));
      await this.toastMessage(error instanceof Error ? error.message : 'Request failed', 'danger');
    }
  }

  private parseRequiredInt(raw: string, field: string, min: number, max: number): number {
    const parsed = Number(raw);
    if (!Number.isInteger(parsed) || parsed < min || parsed > max) {
      throw new Error(`${field} must be an integer between ${min} and ${max}`);
    }
    return parsed;
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
