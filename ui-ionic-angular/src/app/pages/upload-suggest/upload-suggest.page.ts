import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit, ViewEncapsulation, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Subscription } from 'rxjs';
import {
  IonContent,
  IonHeader,
  IonTitle,
  IonToolbar,
  ToastController,
} from '@ionic/angular/standalone';

import { BackendApiService } from '../../core/backend-api.service';
import {
  LearnedCounterpartyItem,
  RedlineApplyDecision,
  NegotiationFlowItem,
  NegotiationFlowSuggestUploadResponse,
} from '../../core/models';

@Component({
  selector: 'app-upload-suggest-page',
  standalone: true,
  encapsulation: ViewEncapsulation.None,
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
        <ion-title>Negotiation Flow Suggest</ion-title>
      </ion-toolbar>
    </ion-header>

    <ion-content [fullscreen]="true" class="ion-padding">
      <div class="container-fluid compact-ui">
        <div class="row g-3">
          <div class="col-12 col-xl-8">
            <div class="card shadow-sm border-0">
              <div class="card-header bg-white">
                <div class="text-uppercase text-muted tiny">Primary Workflow</div>
                <h6 class="mb-0">Upload Redlines and Comments</h6>
              </div>
              <div class="card-body">
                <form [formGroup]="form">
                  <div class="row g-2">
                    <div class="col-12 col-md-6">
                      <label class="form-label tiny">Analysis Scope</label>
                      <select class="form-select form-select-sm" formControlName="analysis_scope" (change)="onScopeChanged()">
                        <option value="single_client">single_client</option>
                        <option value="all_clients">all_clients</option>
                      </select>
                    </div>
                    <div class="col-12 col-md-6" *ngIf="showClientField()">
                      <label class="form-label tiny">Client ID</label>
                      <select
                        *ngIf="clientOptions().length > 0"
                        class="form-select form-select-sm"
                        formControlName="client_id"
                        (change)="onClientChanged()"
                      >
                        <option *ngFor="let c of clientOptions()" [value]="c">{{ c }}</option>
                      </select>
                      <input
                        *ngIf="clientOptions().length === 0"
                        class="form-control form-control-sm"
                        formControlName="client_id"
                        (blur)="onClientChanged()"
                        placeholder="Enter client id"
                      />
                    </div>
                    <div class="col-12 col-md-6">
                      <label class="form-label tiny">Doc Type</label>
                      <input class="form-control form-control-sm" formControlName="doc_type" placeholder="auto match" />
                    </div>
                    <div class="col-12 col-md-6">
                      <label class="form-label tiny">Counterparty</label>
                      <select *ngIf="counterpartyOptions().length > 0" class="form-select form-select-sm" formControlName="counterparty_name">
                        <option value="">All counterparties</option>
                        <option *ngFor="let cp of counterpartyOptions()" [value]="cp.counterparty_name">
                          {{ cp.counterparty_name }} ({{ cp.document_count }})
                        </option>
                      </select>
                      <input *ngIf="counterpartyOptions().length === 0" class="form-control form-control-sm" formControlName="counterparty_name" />
                    </div>
                    <div class="col-6 col-md-4">
                      <label class="form-label tiny">Contract Value</label>
                      <input type="number" class="form-control form-control-sm" formControlName="contract_value" />
                    </div>
                    <div class="col-6 col-md-4">
                      <label class="form-label tiny">Top K</label>
                      <input type="number" class="form-control form-control-sm" formControlName="top_k" />
                    </div>
                    <div class="col-6 col-md-4">
                      <label class="form-label tiny">Max Signals</label>
                      <input type="number" class="form-control form-control-sm" formControlName="max_signals" />
                    </div>
                    <div class="col-12">
                      <div class="text-muted tiny mb-1">Set 0 to process all extracted redlines/comments.</div>
                      <label class="form-label tiny">Document File</label>
                      <input class="form-control form-control-sm" type="file" accept=".docx,.pdf,.txt,.md,.rtf" (change)="onFileChange($event)" />
                    </div>
                    <div class="col-12 d-flex gap-2">
                      <button type="button" class="btn btn-sm btn-primary" [disabled]="!canSubmit()" (click)="generateSuggestions()">
                        Generate Negotiation Playbook
                      </button>
                    </div>
                  </div>
                </form>
              </div>
            </div>

            <div class="card shadow-sm border-0 mt-3" *ngIf="summary()">
              <div class="card-header bg-white">
                <div class="text-uppercase text-muted tiny">Negotiation Plan</div>
                <h6 class="mb-0">{{ summary()?.file_name }}</h6>
              </div>
              <div class="card-body">
                <div class="tiny text-primary mb-1">{{ summary()?.playbook_summary }}</div>
                <div class="tiny text-muted mb-2">Fastest path: {{ summary()?.fastest_path_hint }}</div>
                <div class="row g-2 tiny">
                  <div class="col-6 col-md-3"><strong>Redlines:</strong> {{ summary()?.redline_events_detected }}</div>
                  <div class="col-6 col-md-3"><strong>Comments:</strong> {{ summary()?.comments_detected }}</div>
                  <div class="col-6 col-md-3"><strong>ETA:</strong> {{ summary()?.expected_days_to_close }}d</div>
                  <div class="col-6 col-md-3"><strong>P(7d):</strong> {{ summary()?.probability_close_in_7_days }}</div>
                </div>
              </div>
            </div>

            <div class="card shadow-sm border-0 mt-3" *ngIf="items().length > 0">
              <div class="card-header bg-white d-flex align-items-center justify-content-between">
                <h6 class="mb-0">Signal-Level Guidance</h6>
                <div class="d-flex align-items-center gap-2">
                  <select class="form-select form-select-sm" style="min-width: 220px;" (change)="setClauseTypeFilter(($any($event.target)).value)">
                    <option value="all">All Clause Types</option>
                    <option *ngFor="let clauseType of availableClauseTypes()" [value]="clauseType">{{ clauseType }}</option>
                  </select>
                  <span class="badge text-bg-secondary">{{ filteredItems().length }}</span>
                </div>
              </div>
              <div class="card-body p-2">
                  <div class="list-group list-group-flush signal-list">
                    <div class="list-group-item py-2 px-2" *ngFor="let row of filteredItems()" (mouseenter)="onSignalHover(row)">
                      <div class="d-flex justify-content-between align-items-start gap-2">
                        <div class="w-100">
                          <div class="fw-semibold tiny mb-1">{{ row.source_type }} {{ row.source_index + 1 }}</div>
                        <div class="tiny mb-1 text-muted">
                          <strong>Clause Type:</strong> {{ primaryClauseTypeForRow(row) || 'others' }}
                        </div>
                        <div class="tiny mb-1" *ngIf="row.source_type === 'redline'"><strong>Incoming Redline:</strong> {{ row.incoming_text }}</div>
                        <div class="tiny mb-1 text-muted" *ngIf="row.source_type === 'redline' && row.redline_event_type">
                          <strong>Redline Type:</strong> {{ row.redline_event_type }}
                        </div>
                        <div class="tiny mb-1 text-muted" *ngIf="row.source_type === 'redline' && row.incoming_previous_text">
                          <strong>Previous/Modified Text:</strong> {{ row.incoming_previous_text }}
                        </div>
                        <div class="tiny mb-1 incoming-comment" *ngIf="row.source_type === 'redline' && row.linked_comment_text">
                          <strong>Incoming Comment:</strong> {{ row.linked_comment_text }}
                        </div>
                        <div class="tiny text-warning mb-1" *ngIf="row.source_type === 'redline' && isTrackChangeMetadataComment(row)">
                          Track-change metadata detected. Reply is available only for real DOCX comment threads.
                        </div>
                        <div class="tiny mb-1 incoming-comment" *ngIf="row.source_type === 'comment'"><strong>Incoming Comment:</strong> {{ row.incoming_text }}</div>
                        <div class="mb-1" *ngIf="row.source_type === 'redline'">
                          <label class="form-label tiny mb-1">Suggested Redline (Editable)</label>
                          <textarea
                            class="form-control form-control-sm viewer-input"
                            [value]="modifiedTextForRow(row)"
                            (input)="onModifiedTextInput(row, $event)"
                          ></textarea>
                          <div class="btn-group btn-group-sm mt-1" role="group">
                            <button type="button" class="btn btn-outline-success decision-accept" [class.active]="decisionForRow(row) === 'accept'" (click)="setDecision(row, 'accept')">Accept</button>
                            <button type="button" class="btn btn-outline-warning decision-modify" [class.active]="decisionForRow(row) === 'modify'" (click)="setDecision(row, 'modify')">Modify</button>
                            <button type="button" class="btn btn-outline-danger decision-reject" [class.active]="decisionForRow(row) === 'reject'" (click)="setDecision(row, 'reject')">Reject</button>
                          </div>
                        </div>
                        <div class="mb-1" *ngIf="canEditSuggestedComment(row)">
                          <label class="form-label tiny mb-1">Suggested Comment (Editable)</label>
                          <textarea
                            class="form-control form-control-sm viewer-input"
                            [value]="suggestedCommentForRow(row)"
                            (input)="onSuggestedCommentInput(row, $event)"
                          ></textarea>
                          <div class="mt-1" *ngIf="canReplyToRow(row)">
                            <button type="button" class="btn btn-sm btn-outline-primary decision-reply" [class.active]="replySelectedForRow(row)" (click)="setReplyComment(row)">
                              Reply Comment
                            </button>
                          </div>
                          <div class="tiny text-success mt-1" *ngIf="replySelectedForRow(row)">
                            Reply comment ready.
                          </div>
                        </div>
                        <div class="tiny text-muted mb-1">
                          <strong>Evidence:</strong>
                          <span
                            class="badge ms-1"
                            [class.text-bg-success]="row.evidence_status === 'supported'"
                            [class.text-bg-warning]="row.evidence_status === 'weak'"
                            [class.text-bg-secondary]="row.evidence_status === 'none'"
                          >
                            {{ row.evidence_status }}
                          </span>
                          <span class="ms-1">score {{ row.evidence_score | number:'1.2-2' }}, citations {{ row.citation_count }}</span>
                        </div>
                        <div class="tiny text-muted"><strong>Expected:</strong> {{ row.expected_outcome }} | <strong>Conf:</strong> {{ row.confidence }}</div>
                        <div class="tiny text-danger mt-1" *ngIf="!isSupported(row)">
                          Suggestion withheld due to insufficient evidence.
                        </div>
                        <div class="tiny text-muted"><strong>Rationale:</strong> {{ row.rationale }}</div>
                      </div>
                    </div>
                  </div>
                </div>
                <div class="d-flex align-items-center justify-content-between mt-2">
                  <div class="tiny text-muted">In-file update supports DOCX track changes only.</div>
                  <button type="button" class="btn btn-sm btn-success" [disabled]="!canApplyDocxDecisions()" (click)="applyDocumentChanges()">
                    Apply Decisions and Download DOCX
                  </button>
                </div>
              </div>
            </div>

            <div class="card shadow-sm border-0 mt-3" *ngIf="resultText()">
              <div class="card-header bg-white"><h6 class="mb-0">Debug Response</h6></div>
              <div class="card-body">
                <details class="result-accordion">
                  <summary>Result Details</summary>
                  <pre class="result-box">{{ resultText() }}</pre>
                </details>
              </div>
            </div>
          </div>

          <div class="col-12 col-xl-4">
            <div class="card shadow-sm border-0 viewer-card" *ngIf="summary()">
              <div class="card-header bg-white">
                <h6 class="mb-0">Document Viewer</h6>
                <div class="tiny text-muted">Hover a row to jump</div>
              </div>
              <div class="card-body">
                <div class="tiny text-muted mb-2">{{ viewerMessage() }}</div>
                <div id="doc-text-viewer" class="form-control form-control-sm doc-text-viewer" [innerHTML]="viewerHtml()"></div>
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
      .viewer-card {
        position: sticky;
        top: 8px;
      }
      .doc-text-viewer {
        min-height: 60vh;
        max-height: 70vh;
        font-family: Consolas, 'Courier New', monospace;
        font-size: 11px;
        line-height: 1.35;
        white-space: pre-wrap;
        overflow: auto;
      }
      .doc-text-viewer mark {
        background: transparent;
        color: inherit;
        border-bottom: 2px solid #dc2626;
        border-radius: 1px;
        box-decoration-break: clone;
        -webkit-box-decoration-break: clone;
        padding: 0;
      }
      .doc-line {
        min-height: 1.2em;
      }
      .doc-line-hit {
        background: transparent;
      }
      .viewer-input {
        min-height: 78px;
        font-size: 0.75rem;
      }
      .incoming-comment {
        white-space: pre-line;
      }
      .signal-list {
        max-height: 56vh;
        overflow: auto;
      }
      .signal-list .btn-group .btn,
      .signal-list .btn.btn-sm {
        border-width: 1px !important;
      }
      .signal-list .btn-outline-success {
        color: #0f766e !important;
        border-color: #0f766e !important;
        background: rgba(15, 118, 110, 0.1) !important;
      }
      .signal-list .btn-outline-success:hover,
      .signal-list .btn-outline-success.active {
        color: #ffffff !important;
        border-color: #0f766e !important;
        background: linear-gradient(135deg, #14b8a6, #0f766e) !important;
      }
      .signal-list .btn-outline-warning {
        color: #b45309 !important;
        border-color: #b45309 !important;
        background: rgba(245, 158, 11, 0.12) !important;
      }
      .signal-list .btn-outline-warning:hover,
      .signal-list .btn-outline-warning.active {
        color: #ffffff !important;
        border-color: #b45309 !important;
        background: linear-gradient(135deg, #f59e0b, #d97706) !important;
      }
      .signal-list .btn-outline-danger {
        color: #b91c1c !important;
        border-color: #b91c1c !important;
        background: rgba(239, 68, 68, 0.1) !important;
      }
      .signal-list .btn-outline-danger:hover,
      .signal-list .btn-outline-danger.active {
        color: #ffffff !important;
        border-color: #b91c1c !important;
        background: linear-gradient(135deg, #ef4444, #dc2626) !important;
      }
      .signal-list .btn-outline-primary {
        color: #1d4ed8 !important;
        border-color: #1d4ed8 !important;
        background: rgba(37, 99, 235, 0.08) !important;
      }
      .signal-list .btn-outline-primary:hover,
      .signal-list .btn-outline-primary.active {
        color: #ffffff !important;
        border-color: #1d4ed8 !important;
        background: linear-gradient(135deg, #0ea5e9, #2563eb) !important;
      }
      @media (max-width: 1199.98px) {
        .viewer-card {
          position: static;
        }
        .doc-text-viewer {
          min-height: 36vh;
          max-height: 44vh;
        }
        .signal-list {
          max-height: none;
        }
      }
    `,
  ],
})
export class UploadSuggestPageComponent implements OnInit, OnDestroy {
  private static readonly FORM_KEY = 'nego.uploadSuggest.form';
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(BackendApiService);
  private readonly toast = inject(ToastController);
  private formSub?: Subscription;

  private readonly selectedFile = signal<File | null>(null);
  private readonly rowDecisions = signal<Record<string, 'accept' | 'modify' | 'reject'>>({});
  private readonly rowModifiedText = signal<Record<string, string>>({});
  private readonly rowReplyComment = signal<Record<string, string>>({});
  private readonly rowReplySelected = signal<Record<string, boolean>>({});
  private readonly highlightedRange = signal<{ start: number; end: number } | null>(null);
  private readonly clauseTypeFilter = signal<string>('all');
  readonly result = signal<NegotiationFlowSuggestUploadResponse | Error | null>(null);
  readonly viewerMessage = signal<string>('Hover a redline or comment to jump to matching text.');
  readonly clientOptions = signal<string[]>([]);
  readonly counterpartyOptions = signal<LearnedCounterpartyItem[]>([]);

  readonly form = this.fb.nonNullable.group({
    analysis_scope: ['single_client', [Validators.required]],
    client_id: [''],
    doc_type: [''],
    counterparty_name: [''],
    contract_value: [''],
    top_k: ['4', [Validators.required]],
    max_signals: ['0', [Validators.required]],
  });

  readonly summary = computed(() =>
    this.result() && !(this.result() instanceof Error) ? (this.result() as NegotiationFlowSuggestUploadResponse) : null,
  );
  readonly items = computed<NegotiationFlowItem[]>(() => this.summary()?.items ?? []);
  readonly availableClauseTypes = computed<string[]>(() => {
    const set = new Set<string>();
    for (const row of this.items()) {
      const ct = this.primaryClauseTypeForRow(row) || 'others';
      if (ct) {
        set.add(ct);
      }
    }
    return Array.from(set).sort((a, b) => a.localeCompare(b));
  });
  readonly filteredItems = computed<NegotiationFlowItem[]>(() => {
    const selected = this.clauseTypeFilter();
    if (!selected || selected === 'all') {
      return this.items();
    }
    return this.items().filter((row) => {
      const ct = this.primaryClauseTypeForRow(row) || 'others';
      return ct === selected;
    });
  });
  readonly documentText = computed(() => this.summary()?.document_text ?? '');
  readonly viewerHtml = computed(() => {
    const raw = this.documentText();
    const range = this.highlightedRange();
    if (!raw) {
      return '';
    }
    const safeStart = range ? Math.max(0, Math.min(raw.length, range.start)) : -1;
    const safeEnd = range ? Math.max(safeStart, Math.min(raw.length, range.end)) : -1;
    const lines = raw.split('\n');
    let cursor = 0;
    const htmlParts: string[] = [];
    for (let i = 0; i < lines.length; i += 1) {
      const line = lines[i];
      const lineStart = cursor;
      const lineEnd = cursor + line.length;
      let lineHtml = this.escapeHtml(line);
      let lineClass = 'doc-line';
      if (range && safeEnd > lineStart && safeStart <= lineEnd) {
        const localStart = Math.max(0, safeStart - lineStart);
        const localEnd = Math.max(localStart, Math.min(line.length, safeEnd - lineStart));
        lineClass = 'doc-line doc-line-hit';
        const before = this.escapeHtml(line.slice(0, localStart));
        const mid = this.escapeHtml(line.slice(localStart, localEnd));
        const after = this.escapeHtml(line.slice(localEnd));
        lineHtml = `${before}<mark id="doc-hit" style="background:transparent;color:inherit;border-bottom:2px solid #dc2626;border-radius:1px;box-decoration-break:clone;-webkit-box-decoration-break:clone;">${mid || '&nbsp;'}</mark>${after}`;
      }
      htmlParts.push(`<div id="doc-line-${i}" class="${lineClass}">${lineHtml || '&nbsp;'}</div>`);
      cursor = lineEnd + 1;
    }
    return htmlParts.join('');
  });
  readonly showClientField = computed(() => this.form.getRawValue().analysis_scope === 'single_client');
  readonly canSubmit = computed(() => {
    if (this.form.invalid || !this.selectedFile()) {
      return false;
    }
    const raw = this.form.getRawValue();
    return raw.analysis_scope !== 'single_client' || !!raw.client_id.trim();
  });
  readonly resultText = computed(() => {
    const value = this.result();
    if (!value) {
      return '';
    }
    if (value instanceof Error) {
      return value.message;
    }
    return JSON.stringify(value, null, 2);
  });
  readonly canApplyDocxDecisions = computed(() => {
    const file = this.selectedFile();
    if (!file || !file.name.toLowerCase().endsWith('.docx')) {
      return false;
    }
    return this.buildRedlineDecisions().length > 0;
  });

  async ngOnInit(): Promise<void> {
    this.restoreFormState();
    this.formSub = this.form.valueChanges.subscribe(() => this.persistFormState());
    await this.loadClientOptions();
    await this.onScopeChanged();
  }

  ngOnDestroy(): void {
    this.formSub?.unsubscribe();
  }

  onFileChange(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files && input.files.length > 0 ? input.files[0] : null;
    this.selectedFile.set(file);
    this.rowDecisions.set({});
    this.rowModifiedText.set({});
    this.rowReplyComment.set({});
    this.rowReplySelected.set({});
  }

  async onScopeChanged(): Promise<void> {
    const scope = this.form.getRawValue().analysis_scope as 'single_client' | 'all_clients';
    if (scope === 'all_clients') {
      this.form.patchValue({ client_id: '' });
      await this.loadCounterpartyOptions();
      return;
    }
    const current = this.form.getRawValue().client_id.trim();
    if (!current && this.clientOptions().length > 0) {
      this.form.patchValue({ client_id: this.clientOptions()[0] });
    }
    await this.loadCounterpartyOptions();
  }

  async onClientChanged(): Promise<void> {
    await this.loadCounterpartyOptions();
  }

  async generateSuggestions(): Promise<void> {
    try {
      const file = this.selectedFile();
      if (!file) {
        throw new Error('Select a file to upload');
      }
      const raw = this.form.getRawValue();
      const scope = raw.analysis_scope as 'single_client' | 'all_clients';
      const clientId = raw.client_id.trim();
      if (scope === 'single_client' && !clientId) {
        throw new Error('client_id is required for single_client analysis scope');
      }
      const response = await this.api.suggestNegotiationFlowFromUpload({
        file,
        analysis_scope: scope,
        client_id: clientId || null,
        doc_type: raw.doc_type.trim() || null,
        counterparty_name: raw.counterparty_name.trim() || null,
        contract_value: this.parseOptionalNumber(raw.contract_value),
        top_k: this.parseRequiredInt(raw.top_k, 'top_k', 1, 50),
        max_signals: this.parseRequiredInt(raw.max_signals, 'max_signals', 0, 10000),
      });
      this.result.set(response);
      this.highlightedRange.set(null);
      this.rowDecisions.set({});
      this.rowModifiedText.set({});
      this.rowReplyComment.set({});
      this.rowReplySelected.set({});
      this.clauseTypeFilter.set('all');
      await this.toastMessage('Negotiation playbook generated');
    } catch (error) {
      this.result.set(this.asError(error));
      await this.toastMessage(this.asError(error).message, 'danger');
    }
  }

  private async loadClientOptions(): Promise<void> {
    try {
      const status = await this.api.corpusStatus();
      const unique = Array.from(new Set((status.sources || []).map((s) => s.client_id).filter(Boolean)));
      unique.sort((a, b) => a.localeCompare(b));
      this.clientOptions.set(unique);
      if (!this.form.getRawValue().client_id.trim() && unique.length > 0) {
        this.form.patchValue({ client_id: unique[0] });
      }
    } catch {
      this.clientOptions.set([]);
    }
  }

  private async loadCounterpartyOptions(): Promise<void> {
    try {
      const raw = this.form.getRawValue();
      const scope = raw.analysis_scope as 'single_client' | 'all_clients';
      const clientId = scope === 'single_client' ? raw.client_id.trim() : '';
      const response = await this.api.listLearnedCounterparties(clientId || undefined);
      this.counterpartyOptions.set(response.items || []);
    } catch {
      this.counterpartyOptions.set([]);
    }
  }

  private parseOptionalNumber(raw: string): number | null {
    const value = raw.trim();
    if (!value) {
      return null;
    }
    const parsed = Number(value);
    if (Number.isNaN(parsed) || parsed < 0) {
      throw new Error('contract_value must be a non-negative number');
    }
    return parsed;
  }

  private parseRequiredInt(raw: string, field: string, min: number, max: number): number {
    const parsed = Number(raw);
    if (!Number.isInteger(parsed) || parsed < min || parsed > max) {
      throw new Error(`${field} must be an integer between ${min} and ${max}`);
    }
    return parsed;
  }

  signalKey(row: NegotiationFlowItem): string {
    return `${row.source_type}-${row.source_index}`;
  }

  setClauseTypeFilter(value: string): void {
    this.clauseTypeFilter.set((value || 'all').trim() || 'all');
  }

  primaryClauseTypeForRow(row: NegotiationFlowItem): string {
    const direct = (row.clause_type || '').trim();
    if (this.isValidDisplayClauseType(direct)) {
      return direct;
    }
    const counts = new Map<string, number>();
    for (const ex of row.retrieved_examples || []) {
      if (!ex.is_clause) {
        continue;
      }
      const key = (ex.clause_type || '').trim();
      if (!this.isValidDisplayClauseType(key)) {
        continue;
      }
      if (!key) {
        continue;
      }
      counts.set(key, (counts.get(key) || 0) + 1);
    }
    if (counts.size === 0) {
      return '';
    }
    const sorted = Array.from(counts.entries()).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
    return sorted[0][0];
  }

  private isValidDisplayClauseType(value: string): boolean {
    const key = (value || '').trim().toLowerCase();
    if (!key) {
      return false;
    }
    if (key === 'other') {
      return false;
    }
    if (key.startsWith('redline_')) {
      return false;
    }
    return true;
  }

  onSignalHover(row: NegotiationFlowItem): void {
    const text = this.documentText();
    if (!text) {
      this.viewerMessage.set('No parsed document text available for this file.');
      return;
    }
    const sourcePos = typeof row.source_position === 'number' ? row.source_position : null;
    const queries = this.hoverQueries(row);
    if (sourcePos !== null && sourcePos >= 0 && sourcePos < text.length) {
      for (const query of queries) {
        const near = this.findBestMatchNear(text, query, sourcePos, 4000);
        if (near) {
          this.highlightedRange.set({ start: near.start, end: near.end });
          this.scrollViewerToIndex(near.start, text.length);
          this.viewerMessage.set(`Jumped to ${row.source_type} ${row.source_index + 1} (anchored/refined).`);
          return;
        }
      }
      const approxLen = Math.max(18, Math.min(260, (row.incoming_text || '').length || 60));
      const end = Math.min(text.length, sourcePos + approxLen);
      this.highlightedRange.set({ start: sourcePos, end });
      this.scrollViewerToIndex(sourcePos, text.length);
      this.viewerMessage.set(`Jumped to ${row.source_type} ${row.source_index + 1} (anchored).`);
      return;
    }
    let match: { start: number; end: number } | null = null;
    for (const q of queries) {
      match = this.findBestMatch(text, q);
      if (match) {
        break;
      }
    }
    if (!match) {
      this.highlightedRange.set(null);
      this.viewerMessage.set('Could not find this signal text in parsed document.');
      return;
    }
    const index = match.start;
    const end = match.end;
    this.highlightedRange.set({ start: index, end });
    this.scrollViewerToIndex(index, text.length);
    this.viewerMessage.set(`Jumped to ${row.source_type} ${row.source_index + 1}.`);
  }

  private hoverQueries(row: NegotiationFlowItem): string[] {
    const linked = (row.linked_comment_text ?? '').trim();
    const incoming = (row.incoming_text ?? '').trim();
    const shortIncoming = incoming.split(/\s+/).slice(0, 16).join(' ').trim();
    if (row.source_type === 'comment') {
      return [incoming, shortIncoming].filter((v) => !!v);
    }
    return [incoming, shortIncoming, linked].filter((v) => !!v);
  }

  private findBestMatch(haystack: string, needle: string): { start: number; end: number } | null {
    const cleanNeedle = needle.trim();
    if (!cleanNeedle) {
      return null;
    }

    const directIndex = haystack.toLowerCase().indexOf(cleanNeedle.toLowerCase());
    if (directIndex >= 0) {
      return { start: directIndex, end: Math.min(haystack.length, directIndex + cleanNeedle.length) };
    }

    const normalizedHaystack = this.normalizeWithMap(haystack);
    const normalizedNeedle = this.normalizeWithMap(cleanNeedle).normalized;
    if (!normalizedNeedle) {
      return null;
    }

    const fullNormIndex = normalizedHaystack.normalized.indexOf(normalizedNeedle);
    if (fullNormIndex >= 0) {
      return this.expandNormalizedRangeToOriginal(normalizedHaystack.map, fullNormIndex, normalizedNeedle.length, haystack.length);
    }

    const tokens = normalizedNeedle.split(' ').filter((t) => t.length > 2);
    const fallbackPhrases: string[] = [];
    if (tokens.length > 0) {
      fallbackPhrases.push(tokens.slice(0, Math.min(10, tokens.length)).join(' '));
      fallbackPhrases.push(tokens.slice(0, Math.min(6, tokens.length)).join(' '));
      if (tokens.length > 8) {
        fallbackPhrases.push(tokens.slice(Math.floor(tokens.length / 3), Math.floor(tokens.length / 3) + 6).join(' '));
      }
    }

    for (const phrase of fallbackPhrases) {
      if (!phrase) {
        continue;
      }
      const idx = normalizedHaystack.normalized.indexOf(phrase);
      if (idx >= 0) {
        return this.expandNormalizedRangeToOriginal(normalizedHaystack.map, idx, phrase.length, haystack.length);
      }
    }

    return null;
  }

  private findBestMatchNear(
    haystack: string,
    needle: string,
    approxPos: number,
    windowRadius: number,
  ): { start: number; end: number } | null {
    const start = Math.max(0, approxPos - windowRadius);
    const end = Math.min(haystack.length, approxPos + windowRadius);
    const windowText = haystack.slice(start, end);
    const match = this.findBestMatch(windowText, needle);
    if (!match) {
      return null;
    }
    return { start: start + match.start, end: start + match.end };
  }

  private normalizeWithMap(text: string): { normalized: string; map: number[] } {
    const out: string[] = [];
    const map: number[] = [];
    let lastWasSpace = true;
    for (let i = 0; i < text.length; i += 1) {
      const ch = text[i];
      const lower = ch.toLowerCase();
      const isAlnum = /[a-z0-9]/.test(lower);
      if (isAlnum) {
        out.push(lower);
        map.push(i);
        lastWasSpace = false;
        continue;
      }
      const isSpaceLike = /\s/.test(ch) || /[.,;:()[\]{}"'`~!@#$%^&*_+=<>/?\\|-]/.test(ch);
      if (isSpaceLike && !lastWasSpace) {
        out.push(' ');
        map.push(i);
        lastWasSpace = true;
      }
    }
    const normalized = out.join('').trim();
    const shift = out.findIndex((c) => c !== ' ');
    if (shift > 0) {
      return { normalized, map: map.slice(shift, shift + normalized.length) };
    }
    return { normalized, map: map.slice(0, normalized.length) };
  }

  private expandNormalizedRangeToOriginal(
    map: number[],
    normStart: number,
    normLength: number,
    originalLength: number,
  ): { start: number; end: number } {
    const safeStart = Math.max(0, Math.min(map.length - 1, normStart));
    const safeEndIdx = Math.max(safeStart, Math.min(map.length - 1, normStart + Math.max(1, normLength) - 1));
    const start = map[safeStart];
    const end = Math.min(originalLength, map[safeEndIdx] + 1);
    return { start, end };
  }

  private escapeHtml(value: string): string {
    return value
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#39;')
      .replaceAll('\n', '<br/>');
  }

  private scrollViewerToIndex(startIndex: number, totalLength: number): void {
    requestAnimationFrame(() => {
      const viewer = document.getElementById('doc-text-viewer') as HTMLDivElement | null;
      if (!viewer) {
        return;
      }
      const line = this.charIndexToLine(this.documentText(), startIndex);
      const downBiasPx = line <= 20 ? 0 : 18 * 16;
      const lineEl = document.getElementById(`doc-line-${line}`) as HTMLDivElement | null;
      if (lineEl) {
        const targetTop = Math.max(0, lineEl.offsetTop - viewer.clientHeight * 0.3 + downBiasPx);
        viewer.scrollTop = targetTop;
        return;
      }
      const maxScroll = Math.max(0, viewer.scrollHeight - viewer.clientHeight);
      if (maxScroll > 0 && totalLength > 0) {
        const ratio = Math.max(0, Math.min(1, startIndex / totalLength));
        viewer.scrollTop = Math.max(0, ratio * maxScroll - viewer.clientHeight * 0.3 + downBiasPx);
      }
      requestAnimationFrame(() => {
        const marker = document.getElementById('doc-hit') as HTMLElement | null;
        if (marker) {
          const targetTop = Math.max(0, marker.offsetTop - viewer.clientHeight * 0.3 + downBiasPx);
          viewer.scrollTop = targetTop;
        }
      });
    });
  }

  private charIndexToLine(text: string, index: number): number {
    if (!text || index <= 0) {
      return 0;
    }
    let line = 0;
    const end = Math.min(index, text.length);
    for (let i = 0; i < end; i += 1) {
      if (text[i] === '\n') {
        line += 1;
      }
    }
    return line;
  }

  decisionForRow(row: NegotiationFlowItem): 'accept' | 'modify' | 'reject' | null {
    return this.rowDecisions()[this.signalKey(row)] ?? null;
  }

  hasIncomingComment(row: NegotiationFlowItem): boolean {
    return !!((row.source_type === 'redline' && row.linked_comment_text) || row.source_type === 'comment');
  }

  canEditSuggestedComment(row: NegotiationFlowItem): boolean {
    if (!this.hasIncomingComment(row)) {
      return false;
    }
    if (row.source_type === 'comment') {
      return true;
    }
    return !this.isTrackChangeMetadataComment(row);
  }

  isTrackChangeMetadataComment(row: NegotiationFlowItem): boolean {
    if (row.source_type !== 'redline') {
      return false;
    }
    const text = (row.linked_comment_text || '').trim().toLowerCase();
    return text.startsWith('track change by ');
  }

  canReplyToRow(row: NegotiationFlowItem): boolean {
    if (!this.hasIncomingComment(row)) {
      return false;
    }
    if (row.source_type === 'comment') {
      return true;
    }
    return !this.isTrackChangeMetadataComment(row);
  }

  isSupported(row: NegotiationFlowItem): boolean {
    return row.evidence_status === 'supported';
  }

  replySelectedForRow(row: NegotiationFlowItem): boolean {
    return !!this.rowReplySelected()[this.signalKey(row)];
  }

  suggestedCommentForRow(row: NegotiationFlowItem): string {
    const key = this.signalKey(row);
    const existing = this.rowReplyComment()[key];
    if (typeof existing === 'string') {
      return existing;
    }
    return row.suggested_comment || '';
  }

  modifiedTextForRow(row: NegotiationFlowItem): string {
    const key = this.signalKey(row);
    const existing = this.rowModifiedText()[key];
    if (typeof existing === 'string') {
      return existing;
    }
    if (row.suggested_redline === 'NO_SUGGESTION_INSUFFICIENT_EVIDENCE') {
      return row.incoming_text;
    }
    return row.suggested_redline || row.incoming_text;
  }

  setDecision(row: NegotiationFlowItem, action: 'accept' | 'modify' | 'reject'): void {
    if (row.source_type !== 'redline') {
      return;
    }
    const key = this.signalKey(row);
    this.rowDecisions.set({ ...this.rowDecisions(), [key]: action });
    if (action === 'modify' && !(key in this.rowModifiedText())) {
      this.rowModifiedText.set({ ...this.rowModifiedText(), [key]: row.suggested_redline || row.incoming_text });
    }
  }

  onModifiedTextInput(row: NegotiationFlowItem, event: Event): void {
    const key = this.signalKey(row);
    const target = event.target as { value?: string | number | null } | null;
    const value = typeof target?.value === 'string' ? target.value : String(target?.value ?? '');
    this.rowModifiedText.set({ ...this.rowModifiedText(), [key]: value });
  }

  setReplyComment(row: NegotiationFlowItem): void {
    const key = this.signalKey(row);
    this.rowReplySelected.set({ ...this.rowReplySelected(), [key]: true });
    if (!(key in this.rowReplyComment())) {
      this.rowReplyComment.set({
        ...this.rowReplyComment(),
        [key]: (row.suggested_comment || 'Please review this comment and confirm proposed wording.'),
      });
    }
  }

  onSuggestedCommentInput(row: NegotiationFlowItem, event: Event): void {
    const key = this.signalKey(row);
    const target = event.target as { value?: string | number | null } | null;
    const value = typeof target?.value === 'string' ? target.value : String(target?.value ?? '');
    this.rowReplyComment.set({ ...this.rowReplyComment(), [key]: value });
  }

  async applyDocumentChanges(): Promise<void> {
    try {
      const file = this.selectedFile();
      if (!file) {
        throw new Error('Select a file to apply decisions');
      }
      if (!file.name.toLowerCase().endsWith('.docx')) {
        throw new Error('In-file update is supported only for .docx');
      }
      const decisions = this.buildRedlineDecisions();
      if (decisions.length === 0) {
        throw new Error('Choose at least one redline decision');
      }
      const blob = await this.api.applyRedlineDecisionsToUpload(file, decisions);
      this.downloadBlob(blob, this.buildUpdatedFileName(file.name));
      await this.toastMessage('Updated DOCX downloaded');
    } catch (error) {
      await this.toastMessage(this.asError(error).message, 'danger');
    }
  }

  private buildRedlineDecisions(): RedlineApplyDecision[] {
    const decisions = this.rowDecisions();
    const modifiedTexts = this.rowModifiedText();
    const replyFlags = this.rowReplySelected();
    const replyTexts = this.rowReplyComment();
    const output: RedlineApplyDecision[] = [];

    for (const row of this.items()) {
      const key = this.signalKey(row);
      const action = decisions[key] ?? null;
      const hasReply = !!replyFlags[key];
      if (!action && !hasReply) {
        continue;
      }
      const payload: RedlineApplyDecision = {
        source_type: row.source_type,
        source_index: row.source_index,
        source_position: typeof row.source_position === 'number' ? row.source_position : null,
        source_comment_id: row.source_comment_id || null,
        source_text: row.incoming_text || null,
        source_context_text: (row.source_type === 'redline' ? row.incoming_previous_text : row.incoming_text) || null,
        action: (action ?? 'reply'),
      };
      if (row.source_type === 'comment') {
        payload.action = 'reply';
      }
      if (action === 'modify') {
        const modifiedText = (modifiedTexts[key] ?? row.suggested_redline ?? row.incoming_text ?? '').trim();
        if (!modifiedText) {
          continue;
        }
        payload.modified_text = modifiedText;
      }
      if (hasReply) {
        const replyComment = (replyTexts[key] ?? row.suggested_comment ?? '').trim();
        if (replyComment) {
          payload.reply_comment = replyComment;
        }
      }
      if (payload.action === 'reply' && !payload.reply_comment) {
        continue;
      }
      output.push(payload);
    }
    return output;
  }

  private buildUpdatedFileName(original: string): string {
    const dot = original.lastIndexOf('.');
    if (dot <= 0) {
      return `${original || 'document'}.updated.docx`;
    }
    return `${original.slice(0, dot)}.updated.docx`;
  }

  private downloadBlob(blob: Blob, fileName: string): void {
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);
    try {
      link.href = url;
      link.download = fileName;
      link.click();
    } finally {
      URL.revokeObjectURL(url);
    }
  }

  private persistFormState(): void {
    localStorage.setItem(UploadSuggestPageComponent.FORM_KEY, JSON.stringify(this.form.getRawValue()));
  }

  private restoreFormState(): void {
    try {
      const raw = localStorage.getItem(UploadSuggestPageComponent.FORM_KEY);
      if (!raw) {
        return;
      }
      const parsed = JSON.parse(raw) as Record<string, unknown>;
      this.form.patchValue({
        analysis_scope: typeof parsed['analysis_scope'] === 'string' ? parsed['analysis_scope'] : 'single_client',
        client_id: typeof parsed['client_id'] === 'string' ? parsed['client_id'] : '',
        doc_type: typeof parsed['doc_type'] === 'string' ? parsed['doc_type'] : '',
        counterparty_name: typeof parsed['counterparty_name'] === 'string' ? parsed['counterparty_name'] : '',
        contract_value: typeof parsed['contract_value'] === 'string' ? parsed['contract_value'] : '',
        top_k: typeof parsed['top_k'] === 'string' ? parsed['top_k'] : '4',
        max_signals: typeof parsed['max_signals'] === 'string' ? parsed['max_signals'] : '0',
      });
    } catch {
      // ignore invalid saved state
    }
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

