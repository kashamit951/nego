import { HttpClient, HttpErrorResponse, HttpHeaders, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { AppConfigService } from './app-config.service';
import {
  ApiErrorShape,
  ApiKeyCreateRequest,
  ApiKeyCreateResponse,
  ApiKeyRevokeRequest,
  ApiKeyRevokeResponse,
  AuditLogListResponse,
  CorpusLearnRequest,
  CorpusLearnResponse,
  CorpusScanRequest,
  CorpusScanResponse,
  CorpusStatusResponse,
  HealthResponse,
  LearnedCounterpartyListResponse,
  MeResponse,
  RedlineApplyDecision,
  NegotiationFlowSuggestUploadResponse,
  StrategySuggestUploadResponse,
  UserCreateRequest,
  UserResponse,
} from './models';

interface RequestOptions {
  withApiKey?: boolean;
  withBootstrapToken?: boolean;
  query?: HttpParams;
}

interface UploadStrategyRequest {
  file: File;
  analysis_scope: 'single_client' | 'all_clients';
  client_id?: string | null;
  doc_type?: string | null;
  counterparty_name?: string | null;
  contract_value?: number | null;
  clause_type?: string | null;
  top_k: number;
  max_clauses: number;
}

interface UploadNegotiationRequest {
  file: File;
  analysis_scope: 'single_client' | 'all_clients';
  client_id?: string | null;
  doc_type?: string | null;
  counterparty_name?: string | null;
  contract_value?: number | null;
  top_k: number;
  max_signals: number;
}

@Injectable({ providedIn: 'root' })
export class BackendApiService {
  private readonly http = inject(HttpClient);
  private readonly configService = inject(AppConfigService);

  async health(): Promise<HealthResponse> {
    return this.get<HealthResponse>('/health', { withApiKey: false });
  }

  async me(): Promise<MeResponse> {
    return this.get<MeResponse>('/v1/auth/me');
  }

  async bootstrapAdmin(request: UserCreateRequest): Promise<ApiKeyCreateResponse> {
    return this.post<ApiKeyCreateResponse>('/v1/auth/bootstrap-admin', request, {
      withApiKey: false,
      withBootstrapToken: true,
    });
  }

  async createUser(request: UserCreateRequest): Promise<UserResponse> {
    return this.post<UserResponse>('/v1/auth/users', request);
  }

  async createApiKey(request: ApiKeyCreateRequest): Promise<ApiKeyCreateResponse> {
    return this.post<ApiKeyCreateResponse>('/v1/auth/keys', request);
  }

  async revokeApiKey(request: ApiKeyRevokeRequest): Promise<ApiKeyRevokeResponse> {
    return this.post<ApiKeyRevokeResponse>('/v1/auth/keys/revoke', request);
  }

  async suggestStrategyFromUpload(request: UploadStrategyRequest): Promise<StrategySuggestUploadResponse> {
    const body = new FormData();
    body.append('file', request.file, request.file.name);
    body.append('analysis_scope', request.analysis_scope);
    if (request.doc_type && request.doc_type.trim()) {
      body.append('doc_type', request.doc_type.trim());
    }
    body.append('top_k', String(request.top_k));
    body.append('max_clauses', String(request.max_clauses));
    if (request.client_id && request.client_id.trim()) {
      body.append('client_id', request.client_id.trim());
    }
    if (request.counterparty_name && request.counterparty_name.trim()) {
      body.append('counterparty_name', request.counterparty_name.trim());
    }
    if (request.contract_value !== undefined && request.contract_value !== null) {
      body.append('contract_value', String(request.contract_value));
    }
    if (request.clause_type && request.clause_type.trim()) {
      body.append('clause_type', request.clause_type.trim());
    }
    return this.post<StrategySuggestUploadResponse>('/v1/strategy/clause-suggest-upload', body);
  }

  async suggestNegotiationFlowFromUpload(
    request: UploadNegotiationRequest,
  ): Promise<NegotiationFlowSuggestUploadResponse> {
    const body = new FormData();
    body.append('file', request.file, request.file.name);
    body.append('analysis_scope', request.analysis_scope);
    if (request.doc_type && request.doc_type.trim()) {
      body.append('doc_type', request.doc_type.trim());
    }
    body.append('top_k', String(request.top_k));
    body.append('max_signals', String(request.max_signals));
    if (request.client_id && request.client_id.trim()) {
      body.append('client_id', request.client_id.trim());
    }
    if (request.counterparty_name && request.counterparty_name.trim()) {
      body.append('counterparty_name', request.counterparty_name.trim());
    }
    if (request.contract_value !== undefined && request.contract_value !== null) {
      body.append('contract_value', String(request.contract_value));
    }
    return this.post<NegotiationFlowSuggestUploadResponse>('/v1/strategy/negotiation-suggest-upload', body);
  }

  async applyRedlineDecisionsToUpload(file: File, decisions: RedlineApplyDecision[]): Promise<Blob> {
    const body = new FormData();
    body.append('file', file, file.name);
    body.append('decisions_json', JSON.stringify(decisions));
    return this.postBlob('/v1/strategy/redline-apply-upload', body);
  }

  async listLearnedCounterparties(clientId?: string): Promise<LearnedCounterpartyListResponse> {
    let query = new HttpParams();
    if (clientId && clientId.trim()) {
      const cleaned = clientId.trim().replace(/^client_id=?/i, '');
      query = query.set('client_id', cleaned || clientId.trim());
    }
    return this.get<LearnedCounterpartyListResponse>('/v1/strategy/counterparties', { query });
  }

  async auditLogs(params: {
    limit: number;
    action?: string;
    actor_user_id?: string;
  }): Promise<AuditLogListResponse> {
    let query = new HttpParams().set('limit', String(params.limit));
    if (params.action) {
      query = query.set('action', params.action);
    }
    if (params.actor_user_id) {
      query = query.set('actor_user_id', params.actor_user_id);
    }
    return this.get<AuditLogListResponse>('/v1/audit/logs', { query });
  }

  async scanCorpus(request: CorpusScanRequest): Promise<CorpusScanResponse> {
    return this.post<CorpusScanResponse>('/v1/corpus/scan', request);
  }

  async learnCorpus(request: CorpusLearnRequest): Promise<CorpusLearnResponse> {
    return this.post<CorpusLearnResponse>('/v1/corpus/learn', request);
  }

  async updateCorpus(request: CorpusLearnRequest): Promise<CorpusLearnResponse> {
    return this.post<CorpusLearnResponse>('/v1/corpus/update', request);
  }

  async corpusStatus(sourcePath?: string, clientId?: string): Promise<CorpusStatusResponse> {
    let query = new HttpParams();
    if (sourcePath && sourcePath.trim()) {
      query = query.set('source_path', sourcePath.trim());
    }
    if (clientId && clientId.trim()) {
      query = query.set('client_id', clientId.trim());
    }
    return this.get<CorpusStatusResponse>('/v1/corpus/status', { query });
  }

  private async get<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const headers = this.buildHeaders(options);
    const url = this.url(path);
    try {
      const response = await firstValueFrom(
        this.http.get<T>(url, {
          headers,
          params: options.query,
        }),
      );
      return response;
    } catch (error) {
      throw this.normalizeError(error);
    }
  }

  private async post<T>(path: string, body: unknown, options: RequestOptions = {}): Promise<T> {
    const isFormData = typeof FormData !== 'undefined' && body instanceof FormData;
    const headers = this.buildHeaders(options, !isFormData);
    const url = this.url(path);
    try {
      const response = await firstValueFrom(
        this.http.post<T>(url, body, {
          headers,
          params: options.query,
        }),
      );
      return response;
    } catch (error) {
      throw this.normalizeError(error);
    }
  }

  private async postBlob(path: string, body: unknown, options: RequestOptions = {}): Promise<Blob> {
    const isFormData = typeof FormData !== 'undefined' && body instanceof FormData;
    const headers = this.buildHeaders(options, !isFormData);
    const url = this.url(path);
    try {
      const response = await firstValueFrom(
        this.http.post(url, body, {
          headers,
          params: options.query,
          responseType: 'blob',
        }),
      );
      return response;
    } catch (error) {
      throw this.normalizeError(error);
    }
  }

  private buildHeaders(options: RequestOptions, withJsonContentType = true): HttpHeaders {
    const cfg = this.configService.config();
    const base = cfg.apiBaseUrl.trim();
    const tenantId = cfg.tenantId.trim();

    if (!base) {
      throw new Error('API Base URL is required. Set it in Setup and Health.');
    }
    if (!tenantId) {
      throw new Error('Tenant ID is required. Set it in Setup and Health.');
    }

    let headers = new HttpHeaders({
      'X-Tenant-Id': tenantId,
      'X-Request-Id': this.requestId(),
    });
    if (withJsonContentType) {
      headers = headers.set('Content-Type', 'application/json');
    }

    const withApiKey = options.withApiKey ?? true;
    if (withApiKey) {
      const apiKey = cfg.apiKey.trim();
      if (!apiKey) {
        throw new Error('API key is required for this action. Set it in Setup and Health.');
      }
      headers = headers.set('X-Api-Key', apiKey);
    }

    if (options.withBootstrapToken) {
      const token = cfg.bootstrapToken.trim();
      if (!token) {
        throw new Error('Bootstrap token is required for bootstrap-admin. Set it in Setup and Health.');
      }
      headers = headers.set('X-Bootstrap-Token', token);
    }

    return headers;
  }

  private url(path: string): string {
    const base = this.configService.config().apiBaseUrl.trim().replace(/\/$/, '');
    return `${base}${path}`;
  }

  private requestId(): string {
    if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
      return crypto.randomUUID();
    }
    return `req-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  private normalizeError(error: unknown): Error {
    if (error instanceof HttpErrorResponse) {
      const body = error.error as ApiErrorShape | string | undefined;
      if (typeof body === 'string') {
        return new Error(`HTTP ${error.status}: ${body}`);
      }
      const detail = body?.detail;
      if (detail) {
        return new Error(`HTTP ${error.status}: ${detail}`);
      }
      return new Error(`HTTP ${error.status}: ${error.message}`);
    }

    if (error instanceof Error) {
      return error;
    }

    return new Error('Unexpected request error');
  }
}
