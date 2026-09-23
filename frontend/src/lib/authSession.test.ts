import {
  clearAccessToken,
  getAccessToken,
  hasAccessToken,
  registerAccessTokenRestorer,
  restoreAccessToken,
  setAccessToken,
  subscribeToAccessToken,
} from './authSession';

describe('authSession', () => {
  beforeEach(() => {
    clearAccessToken();
    // reset module-level restorer between tests
    registerAccessTokenRestorer((async () => null) as any);
  });

  it('setAccessToken trims whitespace and notifies subscribers', () => {
    const observed: (string | null)[] = [];
    const unsubscribe = subscribeToAccessToken((t) => observed.push(t));
    setAccessToken('  abc.def  ');
    expect(getAccessToken()).toBe('abc.def');
    expect(hasAccessToken()).toBe(true);
    expect(observed).toEqual(['abc.def']);
    unsubscribe();
  });

  it('empty / whitespace-only token is treated as null', () => {
    setAccessToken('   ');
    expect(getAccessToken()).toBeNull();
    expect(hasAccessToken()).toBe(false);
  });

  it('clearAccessToken returns getAccessToken to null', () => {
    setAccessToken('xyz');
    clearAccessToken();
    expect(getAccessToken()).toBeNull();
  });

  it('restoreAccessToken caches the in-flight promise (no double restorer call)', async () => {
    let calls = 0;
    registerAccessTokenRestorer(async () => {
      calls += 1;
      return 'restored';
    });

    const [a, b] = await Promise.all([restoreAccessToken(), restoreAccessToken()]);
    expect(a).toBe('restored');
    expect(b).toBe('restored');
    expect(calls).toBe(1);
  });

  it('restoreAccessToken short-circuits when a token is already present', async () => {
    setAccessToken('cached');
    let calls = 0;
    registerAccessTokenRestorer(async () => {
      calls += 1;
      return 'should-not-be-called';
    });
    const result = await restoreAccessToken();
    expect(result).toBe('cached');
    expect(calls).toBe(0);
  });

  it('restoreAccessToken(force=true) ignores cached token and calls restorer again', async () => {
    setAccessToken('stale');
    let calls = 0;
    registerAccessTokenRestorer(async () => {
      calls += 1;
      return 'fresh';
    });
    const result = await restoreAccessToken(true);
    expect(result).toBe('fresh');
    expect(calls).toBe(1);
  });

  it('restoreAccessToken(force=true) reuses an in-flight refresh request', async () => {
    let calls = 0;
    let resolveToken: ((value: string) => void) | null = null;
    registerAccessTokenRestorer(
      () =>
        new Promise<string>((resolve) => {
          calls += 1;
          resolveToken = resolve;
        }),
    );

    const first = restoreAccessToken(true);
    const second = restoreAccessToken(true);

    expect(calls).toBe(1);
    resolveToken?.('fresh');

    await expect(first).resolves.toBe('fresh');
    await expect(second).resolves.toBe('fresh');
  });

  it('subscribeToAccessToken unsubscribe stops further notifications', () => {
    const observed: (string | null)[] = [];
    const unsubscribe = subscribeToAccessToken((t) => observed.push(t));
    setAccessToken('one');
    unsubscribe();
    setAccessToken('two');
    expect(observed).toEqual(['one']);
  });

  it('restoreAccessToken without force skips restorer when token present (no concurrent call)', async () => {
    setAccessToken('present');
    let calls = 0;
    registerAccessTokenRestorer(async () => {
      calls += 1;
      return 'should-not-be-called';
    });
    const [a, b] = await Promise.all([restoreAccessToken(), restoreAccessToken()]);
    expect(a).toBe('present');
    expect(b).toBe('present');
    expect(calls).toBe(0);
  });

  it('restoreAccessToken notifies subscribers after successful restore', async () => {
    const observed: (string | null)[] = [];
    subscribeToAccessToken((t) => observed.push(t));
    registerAccessTokenRestorer(async () => 'restored-token');
    await restoreAccessToken(true);
    expect(observed).toContain('restored-token');
  });

  it('restoreAccessToken restorer throwing does not leave promise stuck', async () => {
    registerAccessTokenRestorer(async () => {
      throw new Error('network error');
    });
    // Should resolve (not hang), even if restorer throws.
    const result = await restoreAccessToken(true).catch(() => 'caught');
    // Either null or 'caught' — the key is it resolves.
    expect(['caught', null]).toContain(result);
  });

  it('clearAccessToken notifies subscribers with null', () => {
    const observed: (string | null)[] = [];
    subscribeToAccessToken((t) => observed.push(t));
    setAccessToken('abc');
    clearAccessToken();
    expect(observed).toEqual(['abc', null]);
  });
});
