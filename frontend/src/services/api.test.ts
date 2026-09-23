/**
 * Light-touch tests for the realtime websocket URL builder. The full axios
 * interceptor surface is exercised by integration tests; here we lock in
 * the contract that was the audit fix's payload: the websocket URL must
 * carry the access token (the backend derives organization_id from the
 * JWT, never trusting it from the query string).
 */

import { realtimeService } from './api';
import { setAccessToken, clearAccessToken } from '@/lib/authSession';

describe('realtimeService.dashboardSocketUrl', () => {
  beforeEach(() => {
    clearAccessToken();
  });

  it('upgrades http -> ws and keeps the api-prefix path', () => {
    setAccessToken('jwt-abc');
    const url = realtimeService.dashboardSocketUrl();
    expect(url.startsWith('ws://') || url.startsWith('wss://')).toBe(true);
    expect(url).toContain('/api/v1/ws/dashboard');
  });

  it('attaches the access token via ?token=', () => {
    setAccessToken('jwt-abc');
    const url = realtimeService.dashboardSocketUrl();
    expect(url).toContain('token=jwt-abc');
  });

  it('omits the token query parameter entirely when no token is present', () => {
    const url = realtimeService.dashboardSocketUrl();
    expect(url).not.toContain('token=');
  });

  it('does not leak the legacy organization_id query parameter', () => {
    // The previous implementation accepted an organization_id and trusted it.
    // The new implementation must derive it server-side from the JWT.
    setAccessToken('jwt-abc');
    const url = realtimeService.dashboardSocketUrl('any-org-uuid');
    expect(url).not.toContain('organization_id=');
  });
});
