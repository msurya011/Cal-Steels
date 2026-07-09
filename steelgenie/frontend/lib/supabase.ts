import { createBrowserClient } from '@supabase/ssr'

const isMock = !process.env.NEXT_PUBLIC_SUPABASE_URL ||
               process.env.NEXT_PUBLIC_SUPABASE_URL.includes('cfsrdgoapoziffjesllw') ||
               process.env.NEXT_PUBLIC_SUPABASE_URL.includes('your_supabase_project_url') ||
               process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY === 'your_supabase_anon_key';

let supabaseClient: any;

if (isMock) {
  if (typeof window !== 'undefined') {
    console.warn("Using mock frontend Supabase client for local offline execution");
  }
  const listeners = new Set<(event: string, session: any) => void>();
  
  supabaseClient = {
    auth: {
      async getSession() {
        if (typeof window === 'undefined') return { data: { session: null }, error: null };
        const sessionStr = localStorage.getItem('mock_supabase_session');
        if (sessionStr) {
          try {
            const session = JSON.parse(sessionStr);
            return { data: { session }, error: null };
          } catch {
            return { data: { session: null }, error: null };
          }
        }
        return { data: { session: null }, error: null };
      },
      onAuthStateChange(callback: (event: string, session: any) => void) {
        listeners.add(callback);
        this.getSession().then(({ data }) => {
          callback('SIGNED_IN', data.session);
        });
        return {
          data: {
            subscription: {
              unsubscribe() {
                listeners.delete(callback);
              }
            }
          }
        };
      },
      async signInWithPassword({ email, password }: any) {
        if (!email || !password) {
          return { data: { user: null, session: null }, error: new Error("Email and password are required") };
        }
        const session = {
          access_token: "mock-session-token",
          token_type: "bearer",
          expires_in: 3600,
          user: {
            id: "dev-user",
            email: email,
            role: "authenticated",
          }
        };
        localStorage.setItem('mock_supabase_session', JSON.stringify(session));
        listeners.forEach(cb => cb('SIGNED_IN', session));
        return { data: { user: session.user, session }, error: null };
      },
      async signUp({ email, password }: any) {
        if (!email || !password) {
          return { data: { user: null, session: null }, error: new Error("Email and password are required") };
        }
        const session = {
          access_token: "mock-session-token",
          token_type: "bearer",
          expires_in: 3600,
          user: {
            id: "dev-user",
            email: email,
            role: "authenticated",
          }
        };
        localStorage.setItem('mock_supabase_session', JSON.stringify(session));
        listeners.forEach(cb => cb('SIGNED_IN', session));
        return { data: { user: session.user, session }, error: null };
      },
      async signOut() {
        localStorage.removeItem('mock_supabase_session');
        listeners.forEach(cb => cb('SIGNED_OUT', null));
        return { error: null };
      }
    }
  };
} else {
  supabaseClient = createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
  )
}

export const supabase = supabaseClient;

