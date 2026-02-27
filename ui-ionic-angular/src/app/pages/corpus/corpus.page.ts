import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Subscription } from 'rxjs';
import {
  AlertController,
  IonContent,
  IonHeader,
  IonTitle,
  IonToolbar,
  ToastController,
} from '@ionic/angular/standalone';

import { BackendApiService } from '../../core/backend-api.service';
import { CorpusSourceStatus, CorpusLearnRequest, CorpusLearnResponse, CorpusScanRequest, CorpusStatusResponse } from '../../core/models';

@Component({
  selector: 'app-corpus-page',
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
        <ion-title>Corpus Learning</ion-title>
      </ion-toolbar>
    </ion-header>

    <ion-content [fullscreen]="true" class="ion-padding">
      <div class="container-fluid compact-ui">
        <div class="row g-3">
          <div class="col-12">
            <div class="card shadow-sm border-0">
              <div class="card-header bg-white">
                <div class="text-uppercase text-muted tiny">Guided Workflow</div>
                <h6 class="mb-0">Scan + Learn Corpus</h6>
              </div>
              <div class="card-body">
                <form [formGroup]="form">
                  <div class="row g-2">
                    <div class="col-12 col-md-4">
                      <label class="form-label tiny">Client Mode</label>
                      <select class="form-select form-select-sm" formControlName="client_mode">
                        <option value="existing">Select Existing Client</option>
                        <option value="new">Create New Client</option>
                      </select>
                    </div>
                    <div class="col-12 col-md-4" *ngIf="form.getRawValue().client_mode === 'existing'">
                      <label class="form-label tiny">Client ID</label>
                      <select class="form-select form-select-sm" formControlName="client_id">
                        <option *ngFor="let id of knownClientIds()" [value]="id">{{ id }}</option>
                      </select>
                    </div>
                    <div class="col-12 col-md-4" *ngIf="form.getRawValue().client_mode === 'new'">
                      <label class="form-label tiny">New Client ID</label>
                      <input class="form-control form-control-sm" formControlName="new_client_id" placeholder="client_acme" />
                    </div>
                    <div class="col-12">
                      <label class="form-label tiny">Source Folder Path (server path)</label>
                      <input class="form-control form-control-sm" formControlName="source_path" placeholder="D:/nego/corpus/tenant_acme" />
                    </div>
                    <div class="col-12 col-md-4">
                      <label class="form-label tiny">Source Label (optional)</label>
                      <input class="form-control form-control-sm" formControlName="source_label" placeholder="Acme Contract Corpus" />
                    </div>
                    <div class="col-12 col-md-4">
                      <label class="form-label tiny">Max Files</label>
                      <input class="form-control form-control-sm" type="number" formControlName="max_files" />
                    </div>
                    <div class="col-12 col-md-4">
                      <label class="form-label tiny">File Extensions CSV</label>
                      <input class="form-control form-control-sm" formControlName="file_extensions" placeholder="docx,pdf,txt,md,rtf" />
                    </div>
                    <div class="col-12 col-md-4">
                      <label class="form-label tiny">Default Doc Type</label>
                      <input class="form-control form-control-sm" formControlName="default_doc_type" placeholder="MSA" />
                    </div>
                    <div class="col-12 col-md-4">
                      <label class="form-label tiny">Counterparty (optional)</label>
                      <input class="form-control form-control-sm" formControlName="counterparty_name" placeholder="Vendor A" />
                    </div>
                    <div class="col-12 col-md-4">
                      <label class="form-label tiny">Contract Value (optional)</label>
                      <input class="form-control form-control-sm" type="number" formControlName="contract_value" placeholder="250000" />
                    </div>
                    <div class="col-12 col-md-6">
                      <label class="form-label tiny">Degree of Protection</label>
                      <select class="form-select form-select-sm" formControlName="degree_of_protection">
                        <option value="strict">High Protection</option>
                        <option value="balanced">Balanced Protection</option>
                        <option value="lenient">Flexible Protection</option>
                      </select>
                    </div>
                    <div class="col-12 col-md-6">
                      <label class="form-label tiny">Comment Signal Engine</label>
                      <select class="form-select form-select-sm" formControlName="comment_signal_engine">
                        <option value="llm">llm</option>
                        <option value="rules">rules</option>
                      </select>
                    </div>
                    <div class="col-12 col-md-4">
                      <div class="form-check mt-2">
                        <input class="form-check-input" type="checkbox" formControlName="include_subdirectories" id="corpus-subdir" />
                        <label class="form-check-label tiny" for="corpus-subdir">Include subdirectories</label>
                      </div>
                    </div>
                    <div class="col-12 col-md-4">
                      <div class="form-check mt-2">
                        <input class="form-check-input" type="checkbox" formControlName="create_outcomes_from_redlines" id="corpus-redlines" />
                        <label class="form-check-label tiny" for="corpus-redlines">Create outcomes from redlines</label>
                      </div>
                    </div>
                    <div class="col-12 col-md-4">
                      <div class="form-check mt-2">
                        <input class="form-check-input" type="checkbox" formControlName="create_outcomes_from_comments" id="corpus-comments" />
                        <label class="form-check-label tiny" for="corpus-comments">Create outcomes from comments</label>
                      </div>
                    </div>
                    <div class="col-12 col-md-4">
                      <label class="form-label tiny">Custom Accept Phrases (CSV)</label>
                      <input class="form-control form-control-sm" formControlName="comment_accept_phrases_csv" placeholder="acceptable,works for us" />
                    </div>
                    <div class="col-12 col-md-4">
                      <label class="form-label tiny">Custom Reject Phrases (CSV)</label>
                      <input class="form-control form-control-sm" formControlName="comment_reject_phrases_csv" placeholder="must delete,deal breaker" />
                    </div>
                    <div class="col-12 col-md-4">
                      <label class="form-label tiny">Custom Revise Phrases (CSV)</label>
                      <input class="form-control form-control-sm" formControlName="comment_revise_phrases_csv" placeholder="replace with,subject to" />
                    </div>
                    <div class="col-12 d-flex gap-2">
                      <button type="button" class="btn btn-sm btn-primary" [disabled]="form.invalid" (click)="submitCorpus()">Submit Corpus</button>
                      <button type="button" class="btn btn-sm btn-outline-primary" (click)="loadStatus()">Refresh Status</button>
                    </div>
                  </div>
                </form>

                <div class="tiny text-muted mt-2">One click runs scan first, then learn, then refreshes status.</div>
                <div class="tiny text-success mt-1" *ngIf="submitSummary()">
                  Learned {{ submitSummary()?.learned_documents }} docs, skipped {{ submitSummary()?.skipped_unchanged }}, failed
                  {{ submitSummary()?.failed_files }}.
                </div>
                <details class="result-accordion mt-3">
                  <summary>Result Details</summary>
                  <pre class="result-box">{{ submitText() }}</pre>
                </details>
              </div>
            </div>

            <div class="card shadow-sm border-0 mt-3">
              <div class="card-header bg-white">
                <div class="text-uppercase text-muted tiny">Discovered Corpora</div>
                <h6 class="mb-0">Corpus Status</h6>
              </div>
              <div class="card-body">
                <div class="list-group list-group-flush" *ngIf="statusSummary()?.sources?.length; else noSources">
                  <div class="list-group-item" *ngFor="let source of statusSummary()?.sources">
                    <div class="fw-semibold">{{ source.source_label || source.source_path }}</div>
                    <div class="tiny">Client: {{ source.client_id }}</div>
                    <div class="tiny">Path: {{ source.source_path }}</div>
                    <div class="tiny">
                      total {{ source.total_files }} | learned {{ source.learned_files }} | changed {{ source.changed_files }} |
                      pending {{ source.pending_files }} | missing {{ source.missing_files }} | error {{ source.error_files }}
                    </div>
                    <div class="tiny">last scanned: {{ source.last_scanned_at || 'never' }} | last learned: {{ source.last_learned_at || 'never' }}</div>
                    <button type="button" class="btn btn-sm btn-outline-primary mt-2" (click)="selectSource(source.client_id, source.source_path, source.source_label || '')">
                      Use This Source
                    </button>
                  </div>
                </div>
                <ng-template #noSources>
                  <div class="tiny text-muted">No corpus sources found for this tenant yet.</div>
                </ng-template>

                <details class="result-accordion mt-3">
                  <summary>Result Details</summary>
                  <pre class="result-box">{{ statusText() }}</pre>
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
export class CorpusPageComponent implements OnInit, OnDestroy {
  private static readonly FORM_KEY = 'nego.corpus.form';
  private static readonly KNOWN_CLIENTS_KEY = 'nego.corpus.knownClients';
  private static readonly KNOWN_CLIENT_PATHS_KEY = 'nego.corpus.clientPaths';
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(BackendApiService);
  private readonly alert = inject(AlertController);
  private readonly toast = inject(ToastController);
  private readonly subs: Subscription[] = [];

  readonly knownClientIds = signal<string[]>([]);
  readonly knownClientPaths = signal<Record<string, { source_path: string; source_label: string }>>({});
  readonly submitResult = signal<{ scan: unknown; learn: CorpusLearnResponse } | Error | null>(null);
  readonly statusResult = signal<CorpusStatusResponse | Error | null>(null);

  readonly submitText = computed(() => this.pretty(this.submitResult()));
  readonly statusText = computed(() => this.pretty(this.statusResult()));

  readonly submitSummary = computed(() => {
    const value = this.submitResult();
    return value && !(value instanceof Error) ? value.learn : null;
  });

  readonly statusSummary = computed(() =>
    this.statusResult() && !(this.statusResult() instanceof Error) ? (this.statusResult() as CorpusStatusResponse) : null,
  );

  readonly form = this.fb.nonNullable.group({
    client_mode: ['existing', [Validators.required]],
    client_id: [''],
    new_client_id: [''],
    source_path: ['', [Validators.required]],
    source_label: [''],
    include_subdirectories: [true],
    max_files: ['4000', [Validators.required]],
    file_extensions: ['docx,pdf,txt,md,rtf'],
    default_doc_type: [''],
    counterparty_name: [''],
    contract_value: [''],
    degree_of_protection: ['balanced', [Validators.required]],
    comment_signal_engine: ['llm', [Validators.required]],
    create_outcomes_from_redlines: [false],
    create_outcomes_from_comments: [true],
    comment_accept_phrases_csv: [''],
    comment_reject_phrases_csv: [''],
    comment_revise_phrases_csv: [''],
  });

  ngOnInit(): void {
    this.restoreFormState(CorpusPageComponent.FORM_KEY, this.form);
    this.knownClientIds.set(this.loadKnownClients());
    this.knownClientPaths.set(this.loadKnownClientPaths());
    if (this.knownClientIds().length > 0 && !this.form.getRawValue().client_id.trim()) {
      this.form.patchValue({ client_id: this.knownClientIds()[0] });
    }
    this.subs.push(this.form.valueChanges.subscribe(() => this.persistFormState(CorpusPageComponent.FORM_KEY, this.form.getRawValue())));
    this.subs.push(this.form.controls.client_mode.valueChanges.subscribe(() => this.onClientSelectionChanged()));
    this.subs.push(this.form.controls.client_id.valueChanges.subscribe(() => this.onClientSelectionChanged()));
    this.subs.push(this.form.controls.new_client_id.valueChanges.subscribe(() => this.onClientSelectionChanged()));
    this.subs.push(this.form.controls.source_path.valueChanges.subscribe(() => this.persistCurrentClientPath()));
    this.subs.push(this.form.controls.source_label.valueChanges.subscribe(() => this.persistCurrentClientPath()));
    this.onClientSelectionChanged();
    void this.bootstrapStatus();
  }

  ngOnDestroy(): void {
    for (const sub of this.subs) {
      sub.unsubscribe();
    }
  }

  async submitCorpus(): Promise<void> {
    try {
      const scanRequest = this.buildScanRequest();
      const raw = this.form.getRawValue();
      let plan: { proceed: boolean; existing: boolean; mode: 'new_or_changed' | 'all' } = {
        proceed: true,
        existing: false,
        mode: 'all',
      };
      if (raw.client_mode === 'existing') {
        plan = await this.resolveCorpusPlan(scanRequest);
        if (!plan.proceed) {
          return;
        }
      }
      const learnRequest = this.buildLearnRequest({ mode: plan.mode });
      const scan = await this.api.scanCorpus(scanRequest);
      const learn = plan.existing ? await this.api.updateCorpus(learnRequest) : await this.api.learnCorpus(learnRequest);
      this.submitResult.set({ scan, learn });
      this.pushKnownClient(scanRequest.client_id);
      this.pushKnownClientPath(scanRequest.client_id, scanRequest.source_path, scanRequest.source_label || '');
      await this.toastMessage('Corpus submit completed');
      await this.loadStatus();
    } catch (error) {
      this.submitResult.set(this.asError(error));
      await this.toastMessage(this.asError(error).message, 'danger');
    }
  }

  async loadStatus(): Promise<void> {
    try {
      const sourcePath = this.form.getRawValue().source_path.trim();
      const clientId = this.resolveClientId();
      const result = await this.api.corpusStatus(sourcePath || undefined, clientId || undefined);
      this.statusResult.set(result);
      this.mergeClientsFromStatus(result);
    } catch (error) {
      this.statusResult.set(this.asError(error));
      await this.toastMessage(this.asError(error).message, 'danger');
    }
  }

  selectSource(clientId: string, path: string, label: string): void {
    this.form.patchValue({
      client_mode: 'existing',
      client_id: clientId,
      source_path: path,
      source_label: label,
    });
    this.pushKnownClient(clientId);
    this.pushKnownClientPath(clientId, path, label);
  }

  private resolveClientId(): string {
    const raw = this.form.getRawValue();
    const mode = raw.client_mode;
    const existing = raw.client_id.trim();
    const created = raw.new_client_id.trim();

    if (mode === 'new') {
      if (!created) {
        throw new Error('new_client_id is required when creating a new client');
      }
      return created;
    }

    if (!existing) {
      throw new Error('client_id is required');
    }
    return existing;
  }

  private buildScanRequest(): CorpusScanRequest {
    const raw = this.form.getRawValue();
    const clientId = this.resolveClientId();
    const maxFiles = Number(raw.max_files);
    if (!Number.isInteger(maxFiles) || maxFiles <= 0) {
      throw new Error('max_files must be a positive integer');
    }

    const fileExtensions = raw.file_extensions
      .split(',')
      .map((x) => x.trim())
      .filter((x) => x.length > 0);

    const sourcePath = raw.source_path.trim();
    if (!sourcePath) {
      throw new Error('source_path is required');
    }

    return {
      client_id: clientId,
      source_path: sourcePath,
      source_label: raw.source_label.trim() || null,
      include_subdirectories: raw.include_subdirectories,
      max_files: maxFiles,
      file_extensions: fileExtensions,
    };
  }

  private buildLearnRequest(overrides: Partial<CorpusLearnRequest> = {}): CorpusLearnRequest {
    const scan = this.buildScanRequest();
    const learn = this.form.getRawValue();

    const contractValue = this.parseOptionalNumber(learn.contract_value);
    const base: CorpusLearnRequest = {
      ...scan,
      default_doc_type: learn.default_doc_type.trim() || null,
      counterparty_name: learn.counterparty_name.trim() || null,
      contract_value: contractValue,
      mode: 'all',
      create_outcomes_from_redlines: learn.create_outcomes_from_redlines,
      create_outcomes_from_comments: learn.create_outcomes_from_comments,
      comment_signal_engine: learn.comment_signal_engine as 'rules' | 'llm',
      comment_rule_profile: learn.degree_of_protection as 'strict' | 'balanced' | 'lenient',
      comment_accept_phrases: this.parseCsv(learn.comment_accept_phrases_csv),
      comment_reject_phrases: this.parseCsv(learn.comment_reject_phrases_csv),
      comment_revise_phrases: this.parseCsv(learn.comment_revise_phrases_csv),
    };
    return { ...base, ...overrides };
  }

  private parseOptionalNumber(value: string): number | null {
    const clean = value.trim();
    if (!clean) {
      return null;
    }
    const parsed = Number(clean);
    if (Number.isNaN(parsed) || parsed < 0) {
      throw new Error('contract_value must be a non-negative number');
    }
    return parsed;
  }

  private parseCsv(value: string): string[] {
    return value
      .split(',')
      .map((x) => x.trim())
      .filter((x) => x.length > 0);
  }

  private pushKnownClient(clientId: string): void {
    const clean = clientId.trim();
    if (!clean) {
      return;
    }
    const merged = Array.from(new Set([clean, ...this.knownClientIds()])).sort();
    this.knownClientIds.set(merged);
    localStorage.setItem(CorpusPageComponent.KNOWN_CLIENTS_KEY, JSON.stringify(merged));
  }

  private mergeClientsFromStatus(status: CorpusStatusResponse): void {
    const fromStatus = status.sources.map((s) => s.client_id).filter((x) => x && x.trim().length > 0);
    const merged = Array.from(new Set([...this.knownClientIds(), ...fromStatus])).sort();
    this.knownClientIds.set(merged);
    localStorage.setItem(CorpusPageComponent.KNOWN_CLIENTS_KEY, JSON.stringify(merged));

    const current = { ...this.knownClientPaths() };
    const seenInBatch = new Set<string>();
    for (const source of status.sources) {
      const key = source.client_id.trim();
      if (!key) {
        continue;
      }
      // Prefer latest source returned by backend for each client, and overwrite stale local cache.
      if (seenInBatch.has(key)) {
        continue;
      }
      seenInBatch.add(key);
      current[key] = {
        source_path: source.source_path,
        source_label: source.source_label || '',
      };
    }
    this.knownClientPaths.set(current);
    localStorage.setItem(CorpusPageComponent.KNOWN_CLIENT_PATHS_KEY, JSON.stringify(current));
  }

  private onClientSelectionChanged(): void {
    if (this.form.getRawValue().client_mode === 'new') {
      this.form.patchValue({ source_path: '', source_label: '' }, { emitEvent: false });
      return;
    }
    this.form.patchValue({ source_path: '', source_label: '' }, { emitEvent: false });
    this.applyKnownPathForCurrentClient(true);
    void this.ensureClientPathFromServer();
  }

  private applyKnownPathForCurrentClient(force: boolean): void {
    const clientId = this.currentClientFromForm();
    if (!clientId) {
      return;
    }
    const known = this.knownClientPaths()[clientId];
    if (!known) {
      return;
    }
    const raw = this.form.getRawValue();
    if (!force && raw.source_path.trim()) {
      return;
    }
    this.form.patchValue(
      {
        source_path: known.source_path,
        source_label: raw.source_label.trim() ? raw.source_label : known.source_label,
      },
      { emitEvent: false },
    );
  }

  private persistCurrentClientPath(): void {
    const clientId = this.currentClientFromForm();
    if (!clientId) {
      return;
    }
    const raw = this.form.getRawValue();
    this.pushKnownClient(clientId);
    this.pushKnownClientPath(clientId, raw.source_path, raw.source_label);
  }

  private async bootstrapStatus(): Promise<void> {
    try {
      const status = await this.api.corpusStatus();
      this.statusResult.set(status);
      this.mergeClientsFromStatus(status);
      this.applyKnownPathForCurrentClient(true);
    } catch {
      // no-op: status may fail before API key/setup is complete
    }
  }

  private async ensureClientPathFromServer(): Promise<void> {
    const clientId = this.currentClientFromForm();
    if (!clientId || this.form.getRawValue().client_mode !== 'existing') {
      return;
    }
    try {
      const status = await this.api.corpusStatus(undefined, clientId);
      this.mergeClientsFromStatus(status);
      this.applyKnownPathForCurrentClient(true);
    } catch {
      // no-op: keep UI usable even if backend status isn't reachable
    }
  }

  private async resolveCorpusPlan(
    scan: CorpusScanRequest,
  ): Promise<{ proceed: boolean; existing: boolean; mode: 'new_or_changed' | 'all' }> {
    const status = await this.api.corpusStatus(scan.source_path, scan.client_id);
    this.statusResult.set(status);
    this.mergeClientsFromStatus(status);
    const existing = this.findSourceStatus(status, scan.client_id, scan.source_path);
    if (!existing) {
      return { proceed: true, existing: false, mode: 'all' };
    }

    const pending = existing.pending_files;
    const changed = existing.changed_files;
    const hasUpdates = pending > 0 || changed > 0;
    const message = hasUpdates
      ? `Existing corpus found for "${scan.client_id}" at "${scan.source_path}". Pending: ${pending}, Changed: ${changed}. Choose learning mode and update.`
      : `No new/changed files found for "${scan.client_id}" at "${scan.source_path}". Choose learning mode and update anyway if needed.`;

    const mode = await this.openUpdateModePopup(message);
    if (!mode) {
      return { proceed: false, existing: true, mode: 'all' };
    }
    return { proceed: true, existing: true, mode };
  }

  private async openUpdateModePopup(message: string): Promise<'new_or_changed' | 'all' | null> {
    const alert = await this.alert.create({
      header: 'Update Corpus',
      message,
      inputs: [
        {
          type: 'radio',
          label: 'all (default)',
          value: 'all',
          checked: true,
        },
        {
          type: 'radio',
          label: 'new_or_changed',
          value: 'new_or_changed',
        },
      ],
      buttons: [
        {
          text: 'Cancel',
          role: 'cancel',
        },
        {
          text: 'Update Corpus',
          role: 'confirm',
          handler: (value: unknown) => ({ mode: value }),
        },
      ],
    });
    await alert.present();
    const { role, data } = await alert.onDidDismiss<{ mode?: 'new_or_changed' | 'all' }>();
    if (role !== 'confirm') {
      return null;
    }
    if (data?.mode === 'new_or_changed') {
      return 'new_or_changed';
    }
    return 'all';
  }

  private findSourceStatus(status: CorpusStatusResponse, clientId: string, sourcePath: string): CorpusSourceStatus | null {
    const wantedClient = clientId.trim().toLowerCase();
    const wantedPath = this.normalizePath(sourcePath);
    const match = status.sources.find((source) => {
      return source.client_id.trim().toLowerCase() === wantedClient && this.normalizePath(source.source_path) === wantedPath;
    });
    return match || null;
  }

  private normalizePath(path: string): string {
    return path.trim().replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase();
  }

  private currentClientFromForm(): string {
    const raw = this.form.getRawValue();
    if (raw.client_mode === 'new') {
      return raw.new_client_id.trim();
    }
    return raw.client_id.trim();
  }

  private pushKnownClientPath(clientId: string, sourcePath: string, sourceLabel: string): void {
    const key = clientId.trim();
    const path = sourcePath.trim();
    if (!key || !path) {
      return;
    }
    const next = {
      ...this.knownClientPaths(),
      [key]: {
        source_path: path,
        source_label: sourceLabel.trim(),
      },
    };
    this.knownClientPaths.set(next);
    localStorage.setItem(CorpusPageComponent.KNOWN_CLIENT_PATHS_KEY, JSON.stringify(next));
  }

  private loadKnownClients(): string[] {
    try {
      const raw = localStorage.getItem(CorpusPageComponent.KNOWN_CLIENTS_KEY);
      if (!raw) {
        return [];
      }
      const parsed = JSON.parse(raw) as string[];
      return Array.isArray(parsed) ? parsed.filter((x) => typeof x === 'string' && x.trim().length > 0) : [];
    } catch {
      return [];
    }
  }

  private loadKnownClientPaths(): Record<string, { source_path: string; source_label: string }> {
    try {
      const raw = localStorage.getItem(CorpusPageComponent.KNOWN_CLIENT_PATHS_KEY);
      if (!raw) {
        return {};
      }
      const parsed = JSON.parse(raw) as Record<string, { source_path?: string; source_label?: string }>;
      const output: Record<string, { source_path: string; source_label: string }> = {};
      for (const [key, value] of Object.entries(parsed || {})) {
        const clientId = key.trim();
        const sourcePath = (value?.source_path || '').trim();
        if (!clientId || !sourcePath) {
          continue;
        }
        output[clientId] = {
          source_path: sourcePath,
          source_label: (value?.source_label || '').trim(),
        };
      }
      return output;
    } catch {
      return {};
    }
  }

  private persistFormState(key: string, value: unknown): void {
    localStorage.setItem(key, JSON.stringify(value));
  }

  private restoreFormState(key: string, form: { patchValue: (value: Record<string, unknown>) => void }): void {
    try {
      const raw = localStorage.getItem(key);
      if (!raw) {
        return;
      }
      form.patchValue(JSON.parse(raw) as Record<string, unknown>);
    } catch {
      // ignore invalid local state
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
      duration: 2200,
      color,
      position: 'top',
    });
    await toast.present();
  }
}


