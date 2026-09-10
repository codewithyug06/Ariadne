import { useEffect, useState, type FormEvent } from 'react';
import { Link, Navigate } from 'react-router-dom';
import { ArrowLeft, CheckCircle2, Key, Lock, Mail, Shield, Sparkles } from 'lucide-react';
import { ApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { AuthSwitch } from '../components/ui/auth-switch';

const GOOGLE_CLIENT_ID = '775204572064-2c7ts9jlfjtlh92j1thj92rit4k0vdg8.apps.googleusercontent.com';

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (config: Record<string, unknown>) => void;
          prompt: (callback?: (notification: { isNotDisplayed: () => boolean; isSkippedMoment: () => boolean; getNotDisplayedReason: () => string; getSkippedReason: () => string }) => void) => void;
          renderButton: (parent: HTMLElement, options: Record<string, unknown>) => void;
          disableAutoSelect: () => void;
        };
        oauth2: {
          initTokenClient: (config: {
            client_id: string;
            scope: string;
            callback: (response: { access_token?: string; error?: string; error_description?: string }) => void;
            error_callback?: (error: { type: string; message?: string }) => void;
          }) => {
            requestAccessToken: () => void;
          };
        };
      };
    };
  }
}

export function Login() {
  const { login, loginWithGoogle, status } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [googleSubmitting, setGoogleSubmitting] = useState(false);
  const [activeTab, setActiveTab] = useState<'credentials' | 'demo'>('credentials');
  const [demoNotice, setDemoNotice] = useState<string | null>(null);

  useEffect(() => {
    // If Google Identity Services script is loaded, initialize ID token listener
    if (window.google?.accounts?.id) {
      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: async (credentialResponse: { credential?: string }) => {
          if (credentialResponse.credential) {
            setGoogleSubmitting(true);
            setError(null);
            try {
              await loginWithGoogle({ credential: credentialResponse.credential });
            } catch (err) {
              setError(err instanceof ApiError ? err.message : 'Google authentication failed.');
            } finally {
              setGoogleSubmitting(false);
            }
          }
        },
        auto_select: false,
      });
    }
  }, [loginWithGoogle]);

  if (status === 'authenticated') return <Navigate to="/" replace />;

  const handleTabChange = (tab: 'credentials' | 'demo') => {
    setActiveTab(tab);
    setError(null);
    if (tab === 'demo') {
      setEmail('admin@example.com');
      setPassword('password123');
      setDemoNotice('Demo operator credentials populated (admin@example.com / password123)');
    } else {
      setDemoNotice(null);
    }
  };

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Authentication failed.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleGoogleLogin = () => {
    setError(null);
    if (!window.google?.accounts) {
      setError('Google Sign-In is loading. Please check your internet connection or try again in a moment.');
      return;
    }

    setGoogleSubmitting(true);

    try {
      const tokenClient = window.google.accounts.oauth2.initTokenClient({
        client_id: GOOGLE_CLIENT_ID,
        scope: 'openid email profile',
        callback: async (tokenResponse) => {
          if (tokenResponse.error) {
            setError(`Google Sign-In error: ${tokenResponse.error_description || tokenResponse.error}`);
            setGoogleSubmitting(false);
            return;
          }
          if (!tokenResponse.access_token) {
            setError('No access token received from Google.');
            setGoogleSubmitting(false);
            return;
          }
          try {
            await loginWithGoogle({ access_token: tokenResponse.access_token });
          } catch (err) {
            setError(err instanceof ApiError ? err.message : 'Google authentication failed.');
          } finally {
            setGoogleSubmitting(false);
          }
        },
        error_callback: (err) => {
          setGoogleSubmitting(false);
          if (err.type !== 'popup_closed') {
            setError('Google Sign-In was cancelled or encountered an issue.');
          }
        },
      });

      tokenClient.requestAccessToken();
    } catch (err) {
      setGoogleSubmitting(false);
      setError(err instanceof Error ? err.message : 'Failed to launch Google Sign-In.');
    }
  };

  return (
    <div
      className="login-viewport-wrapper"
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: 'calc(100vh - 80px)',
        padding: '32px 16px',
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      {/* Dynamic ambient gradient orbs matching website purple & coral palette */}
      <div
        aria-hidden="true"
        style={{
          position: 'absolute',
          top: '15%',
          left: '50%',
          transform: 'translateX(-50%)',
          width: '600px',
          height: '350px',
          background: 'radial-gradient(circle, rgba(124, 58, 237, 0.18) 0%, rgba(79, 70, 229, 0.08) 50%, transparent 70%)',
          filter: 'blur(60px)',
          pointerEvents: 'none',
          zIndex: 0,
        }}
      />
      <div
        aria-hidden="true"
        style={{
          position: 'absolute',
          bottom: '10%',
          right: '20%',
          width: '320px',
          height: '240px',
          background: 'radial-gradient(circle, rgba(255, 87, 69, 0.12) 0%, transparent 70%)',
          filter: 'blur(50px)',
          pointerEvents: 'none',
          zIndex: 0,
        }}
      />

      <div
        style={{
          width: '100%',
          maxWidth: 440,
          position: 'relative',
          zIndex: 1,
        }}
      >
        {/* Security Status Pill */}
        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 8,
            padding: '5px 14px',
            borderRadius: '9999px',
            background: 'rgba(124, 58, 237, 0.12)',
            border: '1px solid rgba(124, 58, 237, 0.28)',
            color: '#A78BFA',
            fontSize: '11.5px',
            fontWeight: 600,
            letterSpacing: '0.04em',
            textTransform: 'uppercase',
            marginBottom: 16,
            marginInline: 'auto',
          }}
        >
          <span
            style={{
              width: 7,
              height: 7,
              borderRadius: '50%',
              background: '#10B981',
              boxShadow: '0 0 10px #10B981',
              display: 'inline-block',
            }}
          />
          <span>Fail-Closed Gateway · MCP Proxy Active</span>
        </div>

        {/* Card Frame */}
        <form
          className="login-card-container"
          onSubmit={onSubmit}
          style={{
            width: '100%',
            background: 'var(--surface)',
            borderRadius: 24,
            padding: '36px 32px',
            boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.45), 0 0 35px -5px rgba(124, 58, 237, 0.2)',
            border: '1px solid rgba(124, 58, 237, 0.22)',
            backdropFilter: 'blur(20px)',
            transition: 'all 0.3s ease',
          }}
        >
          {/* Brand Header */}
          <div style={{ textAlign: 'center', marginBottom: 24 }}>
            <img
              src="/assets/logo1.png"
              alt="Ariadne — AI Agent Provenance Firewall"
              className="brand-logo-light"
              style={{
                width: 120,
                height: 'auto',
                margin: '0 auto 14px',
                filter: 'drop-shadow(0 4px 12px rgba(109, 40, 217, 0.25))',
              }}
            />
            <img
              src="/assets/logo1-dark.png"
              alt="Ariadne — AI Agent Provenance Firewall"
              className="brand-logo-dark"
              style={{
                width: 120,
                height: 'auto',
                margin: '0 auto 14px',
                filter: 'drop-shadow(0 4px 12px rgba(167, 139, 250, 0.35))',
              }}
            />

            <h1
              style={{
                fontSize: 22,
                fontWeight: 700,
                letterSpacing: '-0.02em',
                margin: 0,
                color: 'var(--text-bright)',
                fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
              }}
            >
              Sign in to Ariadne
            </h1>
            <p
              style={{
                color: 'var(--text-dim)',
                fontSize: 13,
                marginTop: 6,
                marginBottom: 0,
              }}
            >
              Causal Provenance Firewall &amp; Agent Drift Guardrail
            </p>
          </div>

          {/* Integrated Auth Switch Component */}
          <div style={{ marginBottom: 20 }}>
            <AuthSwitch
              activeTab={activeTab}
              onTabChange={handleTabChange}
              showCounter={false}
            />
          </div>

          {/* Demo Notice Banner */}
          {demoNotice && (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '8px 12px',
                borderRadius: 10,
                background: 'rgba(16, 185, 129, 0.12)',
                border: '1px solid rgba(16, 185, 129, 0.3)',
                color: '#34D399',
                fontSize: '12px',
                marginBottom: 16,
              }}
            >
              <CheckCircle2 size={15} style={{ flexShrink: 0 }} />
              <span>{demoNotice}</span>
            </div>
          )}

          {/* Error Banner */}
          {error && (
            <div
              className="card error"
              style={{
                marginBottom: 16,
                borderRadius: 10,
                padding: '10px 14px',
                fontSize: '12.5px',
                border: '1px solid rgba(239, 68, 68, 0.4)',
                background: 'rgba(239, 68, 68, 0.1)',
                color: '#F87171',
              }}
            >
              {error}
            </div>
          )}

          {/* Email Field */}
          <div className="field" style={{ marginBottom: 16 }}>
            <label
              htmlFor="login-email"
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                fontSize: '12px',
                fontWeight: 600,
                color: 'var(--text-muted)',
                marginBottom: 6,
              }}
            >
              <Mail size={13} style={{ color: '#7C3AED' }} />
              <span>Operator Email</span>
            </label>
            <div style={{ position: 'relative' }}>
              <input
                id="login-email"
                type="email"
                autoComplete="username"
                required
                placeholder="admin@example.com"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                style={{
                  width: '100%',
                  padding: '10px 14px',
                  borderRadius: 10,
                  fontSize: '13.5px',
                  border: '1px solid var(--border)',
                  background: 'var(--bg)',
                  color: 'var(--text)',
                  outline: 'none',
                  transition: 'border-color 0.2s ease, box-shadow 0.2s ease',
                }}
                onFocus={(e) => {
                  e.target.style.borderColor = '#7C3AED';
                  e.target.style.boxShadow = '0 0 0 3px rgba(124, 58, 237, 0.18)';
                }}
                onBlur={(e) => {
                  e.target.style.borderColor = 'var(--border)';
                  e.target.style.boxShadow = 'none';
                }}
              />
            </div>
          </div>

          {/* Password Field */}
          <div className="field" style={{ marginBottom: 20 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <label
                htmlFor="login-password"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  fontSize: '12px',
                  fontWeight: 600,
                  color: 'var(--text-muted)',
                }}
              >
                <Lock size={13} style={{ color: '#7C3AED' }} />
                <span>Password</span>
              </label>
              <span style={{ fontSize: '11px', color: 'var(--text-dim)', cursor: 'default' }}>
                Single-Sign-On / Token
              </span>
            </div>
            <div style={{ position: 'relative' }}>
              <input
                id="login-password"
                type="password"
                autoComplete="current-password"
                required
                placeholder="••••••••••••"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                style={{
                  width: '100%',
                  padding: '10px 14px',
                  borderRadius: 10,
                  fontSize: '13.5px',
                  border: '1px solid var(--border)',
                  background: 'var(--bg)',
                  color: 'var(--text)',
                  outline: 'none',
                  transition: 'border-color 0.2s ease, box-shadow 0.2s ease',
                }}
                onFocus={(e) => {
                  e.target.style.borderColor = '#7C3AED';
                  e.target.style.boxShadow = '0 0 0 3px rgba(124, 58, 237, 0.18)';
                }}
                onBlur={(e) => {
                  e.target.style.borderColor = 'var(--border)';
                  e.target.style.boxShadow = 'none';
                }}
              />
            </div>
          </div>

          {/* Submit Button */}
          <button
            type="submit"
            disabled={submitting || googleSubmitting}
            style={{
              width: '100%',
              padding: '11px 18px',
              borderRadius: 10,
              fontSize: '13.5px',
              fontWeight: 600,
              color: '#FFFFFF',
              background: 'linear-gradient(135deg, #7C3AED 0%, #4F46E5 100%)',
              border: 'none',
              cursor: submitting || googleSubmitting ? 'not-allowed' : 'pointer',
              boxShadow: '0 10px 25px -5px rgba(109, 40, 217, 0.45)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 8,
              transition: 'transform 0.15s ease, box-shadow 0.15s ease, opacity 0.15s ease',
              opacity: submitting || googleSubmitting ? 0.75 : 1,
            }}
            onMouseEnter={(e) => {
              if (!submitting && !googleSubmitting) (e.currentTarget as HTMLButtonElement).style.transform = 'translateY(-1px)';
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLButtonElement).style.transform = 'translateY(0)';
            }}
          >
            {submitting ? (
              <span>Authenticating Gateway…</span>
            ) : (
              <>
                <Key size={15} />
                <span>Authorize &amp; Access Dashboard</span>
              </>
            )}
          </button>

          {/* Divider */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              margin: '18px 0 14px',
              color: 'var(--text-dim)',
              fontSize: '11px',
              fontWeight: 500,
            }}
          >
            <div style={{ flex: 1, height: '1px', background: 'var(--border)' }} />
            <span
              style={{
                padding: '0 12px',
                textTransform: 'uppercase',
                letterSpacing: '0.06em',
                fontSize: '10.5px',
                color: 'var(--text-dim)',
              }}
            >
              Or continue with
            </span>
            <div style={{ flex: 1, height: '1px', background: 'var(--border)' }} />
          </div>

          {/* Continue with Google Button */}
          <button
            type="button"
            id="google-signin-button"
            disabled={submitting || googleSubmitting}
            onClick={handleGoogleLogin}
            style={{
              width: '100%',
              padding: '10px 18px',
              borderRadius: 10,
              fontSize: '13.5px',
              fontWeight: 600,
              color: 'var(--text-bright)',
              background: 'var(--surface-hover, rgba(255, 255, 255, 0.04))',
              border: '1px solid var(--border)',
              cursor: submitting || googleSubmitting ? 'not-allowed' : 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 10,
              transition: 'all 0.2s ease',
              opacity: submitting || googleSubmitting ? 0.75 : 1,
              boxShadow: '0 2px 8px rgba(0, 0, 0, 0.1)',
            }}
            onMouseEnter={(e) => {
              if (!submitting && !googleSubmitting) {
                e.currentTarget.style.transform = 'translateY(-1px)';
                e.currentTarget.style.borderColor = 'rgba(124, 58, 237, 0.4)';
                e.currentTarget.style.background = 'rgba(124, 58, 237, 0.08)';
              }
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.transform = 'translateY(0)';
              e.currentTarget.style.borderColor = 'var(--border)';
              e.currentTarget.style.background = 'var(--surface-hover, rgba(255, 255, 255, 0.04))';
            }}
          >
            <svg width="17" height="17" viewBox="0 0 24 24" style={{ flexShrink: 0 }}>
              <path
                fill="#4285F4"
                d="M23.745 12.27c0-.7-.06-1.4-.19-2.07H12v4.51h6.6c-.29 1.52-1.14 2.82-2.4 3.68v3.05h3.88c2.27-2.09 3.665-5.17 3.665-9.17z"
              />
              <path
                fill="#34A853"
                d="M12 24c3.24 0 5.95-1.08 7.93-2.91l-3.88-3.05c-1.08.72-2.45 1.16-4.05 1.16-3.12 0-5.77-2.1-6.72-4.93H1.25v3.15C3.26 21.36 7.33 24 12 24z"
              />
              <path
                fill="#FBBC05"
                d="M5.28 14.27c-.25-.72-.38-1.49-.38-2.27s.13-1.55.38-2.27V6.58H1.25C.45 8.18 0 10.03 0 12s.45 3.82 1.25 5.42l4.03-3.15z"
              />
              <path
                fill="#EA4335"
                d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.42-3.42C17.95 1.19 15.24 0 12 0 7.33 0 3.26 2.64 1.25 6.58l4.03 3.15c.95-2.83 3.6-4.98 6.72-4.98z"
              />
            </svg>
            <span>{googleSubmitting ? 'Connecting with Google…' : 'Continue with Google'}</span>
          </button>

          {/* Micro Security Features Row */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 16,
              marginTop: 22,
              paddingTop: 18,
              borderTop: '1px solid var(--border)',
              fontSize: '11.5px',
              color: 'var(--text-dim)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
              <Shield size={12} style={{ color: '#10B981' }} />
              <span>TLS 1.3 Verified</span>
            </div>
            <span>•</span>
            <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
              <Sparkles size={12} style={{ color: '#A78BFA' }} />
              <span>Zero-Side-Effects</span>
            </div>
          </div>

          {/* Back to Product Overview */}
          <div style={{ textAlign: 'center', marginTop: 18 }}>
            <Link
              to="/landing"
              style={{
                fontSize: '12.5px',
                color: 'var(--text-dim)',
                textDecoration: 'none',
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                transition: 'color 0.15s ease',
              }}
              onMouseEnter={(e) => ((e.currentTarget as HTMLAnchorElement).style.color = '#7C3AED')}
              onMouseLeave={(e) => ((e.currentTarget as HTMLAnchorElement).style.color = 'var(--text-dim)')}
            >
              <ArrowLeft size={13} />
              <span>Back to Product Overview</span>
            </Link>
          </div>
        </form>
      </div>
    </div>
  );
}
