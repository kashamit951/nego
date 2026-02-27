import { Routes } from '@angular/router';
import { authGuard } from './core/auth.guard';
import { guestGuard } from './core/guest.guard';

import { HomePageComponent } from './pages/home/home.page';
import { SetupPageComponent } from './pages/setup/setup.page';
import { AuthPageComponent } from './pages/auth/auth.page';
import { AuditPageComponent } from './pages/audit/audit.page';
import { CorpusPageComponent } from './pages/corpus/corpus.page';
import { UploadSuggestPageComponent } from './pages/upload-suggest/upload-suggest.page';
import { ClauseSuggestPageComponent } from './pages/clause-suggest/clause-suggest.page';
import { LoginPageComponent } from './pages/login/login.page';
import { RegisterPageComponent } from './pages/register/register.page';

export const appRoutes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'login' },
  { path: 'login', component: LoginPageComponent, canActivate: [guestGuard] },
  { path: 'register', component: RegisterPageComponent, canActivate: [guestGuard] },
  { path: 'home', component: HomePageComponent, canActivate: [authGuard] },
  { path: 'setup', component: SetupPageComponent, canActivate: [authGuard] },
  { path: 'auth', component: AuthPageComponent, canActivate: [authGuard] },
  { path: 'upload-suggest', component: UploadSuggestPageComponent, canActivate: [authGuard] },
  { path: 'clause-suggest', component: ClauseSuggestPageComponent, canActivate: [authGuard] },
  { path: 'corpus', component: CorpusPageComponent, canActivate: [authGuard] },
  { path: 'audit', component: AuditPageComponent, canActivate: [authGuard] },
  { path: '**', redirectTo: 'login' },
];
