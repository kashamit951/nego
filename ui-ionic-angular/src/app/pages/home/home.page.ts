import { Component, computed, inject } from '@angular/core';
import {
  IonBadge,
  IonCard,
  IonCardContent,
  IonCardHeader,
  IonCardSubtitle,
  IonCardTitle,
  IonContent,
  IonGrid,
  IonHeader,
  IonItem,
  IonLabel,
  IonList,
  IonRow,
  IonCol,
  IonTitle,
  IonToolbar,
} from '@ionic/angular/standalone';

import { AppConfigService } from '../../core/app-config.service';

@Component({
  selector: 'app-home-page',
  standalone: true,
  imports: [
    IonHeader,
    IonToolbar,
    IonTitle,
    IonContent,
    IonGrid,
    IonRow,
    IonCol,
    IonCard,
    IonCardHeader,
    IonCardTitle,
    IonCardSubtitle,
    IonCardContent,
    IonList,
    IonItem,
    IonLabel,
    IonBadge,
  ],
  template: `
    <ion-header translucent="true">
      <ion-toolbar color="primary">
        <ion-title>Platform Overview</ion-title>
      </ion-toolbar>
    </ion-header>

    <ion-content [fullscreen]="true" class="ion-padding boot-ui">
      <div class="page-shell">
        <ion-card class="section-card">
          <ion-card-header>
            <ion-card-subtitle>Current Workspace</ion-card-subtitle>
            <ion-card-title>Workspace Configuration</ion-card-title>
          </ion-card-header>
          <ion-card-content>
            <div class="data-grid">
              <ion-item lines="none">
                <ion-label>
                  <h2>API Base URL</h2>
                  <p>{{ configState().apiBaseUrl || 'Not set' }}</p>
                </ion-label>
              </ion-item>
              <ion-item lines="none">
                <ion-label>
                  <h2>Tenant ID</h2>
                  <p>{{ configState().tenantId || 'Not set' }}</p>
                </ion-label>
              </ion-item>
              <ion-item lines="none">
                <ion-label>
                  <h2>API Key</h2>
                  <p>{{ hasApiKey() ? 'Configured' : 'Missing' }}</p>
                </ion-label>
                <ion-badge [color]="hasApiKey() ? 'success' : 'warning'">{{ hasApiKey() ? 'Ready' : 'Pending' }}</ion-badge>
              </ion-item>
              <ion-item lines="none">
                <ion-label>
                  <h2>Bootstrap Token</h2>
                  <p>{{ hasBootstrapToken() ? 'Configured' : 'Missing' }}</p>
                </ion-label>
                <ion-badge [color]="hasBootstrapToken() ? 'success' : 'medium'">{{ hasBootstrapToken() ? 'Ready' : 'Optional' }}</ion-badge>
              </ion-item>
            </div>
          </ion-card-content>
        </ion-card>

        <ion-grid>
          <ion-row>
            <ion-col size="12">
              <ion-card class="section-card">
                <ion-card-header>
                  <ion-card-title>What You Can Do</ion-card-title>
                </ion-card-header>
                <ion-card-content>
                  <ion-list>
                    <ion-item><ion-label>Service health status</ion-label></ion-item>
                    <ion-item><ion-label>Set up first workspace admin</ion-label></ion-item>
                    <ion-item><ion-label>View signed-in user profile</ion-label></ion-item>
                    <ion-item><ion-label>Create workspace users</ion-label></ion-item>
                    <ion-item><ion-label>Issue access keys</ion-label></ion-item>
                    <ion-item><ion-label>Revoke access keys</ion-label></ion-item>
                    <ion-item><ion-label>Ingest contract documents</ion-label></ion-item>
                    <ion-item><ion-label>Record negotiation outcomes</ion-label></ion-item>
                    <ion-item><ion-label>Generate negotiation playbooks from uploads</ion-label></ion-item>
                    <ion-item><ion-label>Generate clause suggestions from uploads</ion-label></ion-item>
                    <ion-item><ion-label>Scan contract corpus</ion-label></ion-item>
                    <ion-item><ion-label>Learn from contract corpus</ion-label></ion-item>
                    <ion-item><ion-label>Update learned corpus</ion-label></ion-item>
                    <ion-item><ion-label>View corpus status</ion-label></ion-item>
                    <ion-item><ion-label>Explore audit logs</ion-label></ion-item>
                  </ion-list>
                </ion-card-content>
              </ion-card>
            </ion-col>

            <ion-col size="12">
              <ion-card class="section-card">
                <ion-card-header>
                  <ion-card-title>Recommended Workflow</ion-card-title>
                </ion-card-header>
                <ion-card-content>
                  <ion-list>
                    <ion-item>
                      <ion-label>
                        <h3>1. Setup and Health</h3>
                        <p>Configure API base, tenant, and credentials.</p>
                      </ion-label>
                    </ion-item>
                    <ion-item>
                      <ion-label>
                        <h3>2. Auth and RBAC</h3>
                        <p>Bootstrap admin, create users, issue/revoke keys.</p>
                      </ion-label>
                    </ion-item>
                    <ion-item>
                      <ion-label>
                        <h3>3. Negotiation Intelligence</h3>
                        <p>Generate negotiation playbooks and clause suggestions from uploaded documents.</p>
                      </ion-label>
                    </ion-item>
                    <ion-item>
                      <ion-label>
                        <h3>4. Corpus Learning</h3>
                        <p>Scan client folders, learn changed files, and keep corpus fresh.</p>
                      </ion-label>
                    </ion-item>
                    <ion-item>
                      <ion-label>
                        <h3>5. Audit Logs</h3>
                        <p>Review tenant actions and trace requests.</p>
                      </ion-label>
                    </ion-item>
                  </ion-list>
                </ion-card-content>
              </ion-card>
            </ion-col>
          </ion-row>
        </ion-grid>
      </div>
    </ion-content>
  `,
})
export class HomePageComponent {
  private readonly config = inject(AppConfigService);

  readonly configState = this.config.config;
  readonly hasApiKey = computed(() => this.configState().apiKey.trim().length > 0);
  readonly hasBootstrapToken = computed(() => this.configState().bootstrapToken.trim().length > 0);
}


