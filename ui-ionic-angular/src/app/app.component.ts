import { CommonModule } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { IonApp } from '@ionic/angular/standalone';

import { AppConfigService } from './core/app-config.service';
import { SessionService } from './core/session.service';

type AppPage = {
  key: 'auth' | 'upload-suggest' | 'clause-suggest' | 'corpus' | 'audit';
  label: string;
  minRole: 'viewer' | 'analyst' | 'legal_reviewer' | 'admin';
};

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, RouterLink, RouterLinkActive, RouterOutlet, IonApp],
  template: `
    <ion-app>
      <div class="app-backdrop" aria-hidden="true">
        <span class="orb orb-a"></span>
        <span class="orb orb-b"></span>
        <span class="orb orb-c"></span>
      </div>
      <ng-container *ngIf="canShowShell(); else authOnly">
        <div class="customer-shell" [class.collapsed]="sidebarCollapsed()">
          <aside class="customer-sidebar">
            <div class="sidebar-head">
              <button class="icon-btn" type="button" (click)="toggleSidebar()" title="Toggle menu">{{ sidebarCollapsed() ? '>>' : '<<' }}</button>
              <div class="brand-block" *ngIf="!sidebarCollapsed()">
                <div class="brand-title">Nego Console</div>
                <div class="brand-sub">Customer Console</div>
              </div>
            </div>

            <nav class="menu-list">
              <a
                *ngFor="let page of visiblePages()"
                [routerLink]="'/' + page.key"
                routerLinkActive="menu-active"
                class="menu-link"
                [title]="page.label"
              >
                <span class="menu-icon">{{ shortLabel(page.label) }}</span>
                <span class="menu-text" *ngIf="!sidebarCollapsed()">{{ page.label }}</span>
              </a>
            </nav>

            <div class="sidebar-foot" *ngIf="!sidebarCollapsed()">
              <div class="meta-row">
                <span>Tenant</span>
                <strong>{{ contextLabel() }}</strong>
              </div>
              <div class="meta-row">
                <span>Role</span>
                <strong>{{ roleLabel() }}</strong>
              </div>
              <button class="btn btn-sm btn-outline-danger w-100 mt-2" type="button" (click)="logout()">Logout</button>
            </div>
          </aside>

          <main class="customer-main">
            <section class="page-host">
              <router-outlet></router-outlet>
            </section>
          </main>
        </div>
      </ng-container>

      <ng-template #authOnly>
        <div class="auth-stage">
          <router-outlet></router-outlet>
        </div>
      </ng-template>
    </ion-app>
  `,
  styles: [
    `
      .app-backdrop {
        position: fixed;
        inset: 0;
        overflow: hidden;
        z-index: 0;
        pointer-events: none;
      }

      .orb {
        position: absolute;
        border-radius: 50%;
        filter: blur(2px);
        opacity: 0.4;
        animation: drift 16s ease-in-out infinite alternate;
      }

      .orb-a {
        width: 36vw;
        height: 36vw;
        min-width: 300px;
        min-height: 300px;
        background: radial-gradient(circle at 30% 30%, rgba(34, 211, 238, 0.8), rgba(14, 116, 144, 0));
        top: -8vw;
        left: -8vw;
      }

      .orb-b {
        width: 34vw;
        height: 34vw;
        min-width: 280px;
        min-height: 280px;
        background: radial-gradient(circle at 30% 30%, rgba(250, 204, 21, 0.75), rgba(217, 119, 6, 0));
        bottom: -10vw;
        right: -8vw;
        animation-delay: 1.5s;
      }

      .orb-c {
        width: 28vw;
        height: 28vw;
        min-width: 220px;
        min-height: 220px;
        background: radial-gradient(circle at 30% 30%, rgba(59, 130, 246, 0.72), rgba(30, 64, 175, 0));
        top: 30%;
        left: 44%;
        animation-delay: 0.7s;
      }

      .auth-stage {
        position: relative;
        z-index: 1;
      }

      .customer-shell {
        position: relative;
        z-index: 1;
        min-height: 100vh;
        display: grid;
        grid-template-columns: 260px 1fr;
        background: var(--app-surface-gradient);
      }

      .customer-shell.collapsed {
        grid-template-columns: 84px 1fr;
      }

      .customer-sidebar {
        background: var(--shell-sidebar-bg);
        color: var(--shell-sidebar-ink);
        border-right: 1px solid var(--shell-sidebar-border);
        display: grid;
        grid-template-rows: auto 1fr auto;
        min-height: 100vh;
        padding: 12px;
        gap: 12px;
        backdrop-filter: blur(8px);
      }

      .sidebar-head {
        display: flex;
        align-items: center;
        gap: 10px;
      }

      .icon-btn {
        border: 1px solid rgba(255, 255, 255, 0.2);
        background: rgba(255, 255, 255, 0.08);
        color: #fff;
        border-radius: 10px;
        width: 38px;
        height: 34px;
        transition: transform 0.2s ease, background 0.2s ease;
      }

      .icon-btn:hover {
        transform: translateY(-1px);
        background: rgba(255, 255, 255, 0.2);
      }

      .brand-title {
        font-weight: 700;
        letter-spacing: 0.02em;
      }

      .brand-sub {
        font-size: 12px;
        color: var(--shell-sidebar-muted);
      }

      .menu-list {
        display: grid;
        gap: 6px;
        align-content: start;
      }

      .menu-link {
        display: flex;
        align-items: center;
        gap: 10px;
        text-decoration: none;
        color: var(--shell-sidebar-muted);
        border: 1px solid transparent;
        border-radius: 12px;
        min-height: 42px;
        padding: 6px 8px;
        transition: all 0.22s ease;
      }

      .menu-link:hover {
        color: #fff;
        background: rgba(255, 255, 255, 0.08);
        transform: translateX(3px);
      }

      .menu-active {
        color: #fff;
        background: linear-gradient(135deg, rgba(16, 185, 129, 0.22), rgba(59, 130, 246, 0.2));
        border-color: rgba(148, 163, 184, 0.22);
      }

      .menu-icon {
        width: 26px;
        height: 26px;
        border-radius: 8px;
        display: grid;
        place-items: center;
        background: rgba(255, 255, 255, 0.14);
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.03em;
        color: #fff;
        flex-shrink: 0;
      }

      .menu-text {
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        font-size: 14px;
      }

      .sidebar-foot {
        border: 1px solid rgba(148, 163, 184, 0.24);
        border-radius: 12px;
        padding: 10px;
        background: rgba(15, 23, 42, 0.4);
      }

      .meta-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        font-size: 12px;
        margin-bottom: 4px;
      }

      .meta-row span {
        color: var(--shell-sidebar-muted);
      }

      .customer-main {
        padding: 14px;
        display: block;
      }

      .page-host {
        min-height: 0;
        animation: surface-enter 450ms ease both;
      }

      @keyframes drift {
        from {
          transform: translate3d(0, 0, 0) scale(1);
        }
        to {
          transform: translate3d(28px, -18px, 0) scale(1.08);
        }
      }

      @keyframes surface-enter {
        from {
          opacity: 0;
          transform: translateY(8px);
        }
        to {
          opacity: 1;
          transform: translateY(0);
        }
      }

      @media (max-width: 992px) {
        .customer-shell,
        .customer-shell.collapsed {
          grid-template-columns: 1fr;
        }

        .customer-sidebar {
          min-height: auto;
        }

        .customer-shell.collapsed .menu-text,
        .customer-shell.collapsed .sidebar-foot,
        .customer-shell.collapsed .brand-block {
          display: block;
        }
      }
    `,
  ],
})
export class AppComponent {
  private readonly config = inject(AppConfigService);
  private readonly session = inject(SessionService);
  private readonly router = inject(Router);

  private readonly roleRank: Record<string, number> = {
    viewer: 1,
    analyst: 2,
    legal_reviewer: 3,
    admin: 4,
  };

  readonly sidebarCollapsed = signal(false);

  readonly pages: AppPage[] = [
    { key: 'auth', label: 'User Management', minRole: 'admin' },
    { key: 'upload-suggest', label: 'Negotiation Flow', minRole: 'viewer' },
    { key: 'clause-suggest', label: 'Clause Suggest', minRole: 'viewer' },
    { key: 'corpus', label: 'Corpus', minRole: 'analyst' },
    { key: 'audit', label: 'Audit Logs', minRole: 'analyst' },
  ];

  readonly contextLabel = computed(() => this.config.config().tenantId || 'Not set');
  readonly roleLabel = computed(() => this.currentSession()?.me.role || 'guest');
  readonly currentSession = computed(() => this.session.session());
  readonly canShowShell = computed(() => !!this.currentSession());
  readonly visiblePages = computed(() => {
    const role = this.currentSession()?.me.role || 'viewer';
    const rank = this.roleRank[role] || 0;
    return this.pages.filter((page) => rank >= (this.roleRank[page.minRole] || 99));
  });

  constructor() {}

  shortLabel(label: string): string {
    return label
      .split(' ')
      .slice(0, 2)
      .map((part) => part[0])
      .join('')
      .toUpperCase();
  }

  toggleSidebar(): void {
    this.sidebarCollapsed.update((v) => !v);
  }

  async logout(): Promise<void> {
    this.session.clear();
    await this.router.navigateByUrl('/login');
  }
}
