'use client'

import { useState, FormEvent } from 'react'
import { useRouter } from 'next/navigation'
import { supabase } from '../../../lib/supabase'

type Tab = 'login' | 'signup'

export default function LoginPage() {
  const router = useRouter()
  const [tab, setTab] = useState<Tab>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [resending, setResending] = useState(false)
  const [resendSuccess, setResendSuccess] = useState(false)

  function handleDevLogin() {
    const mockSession = {
      access_token: 'mock-dev-jwt-token',
      user: {
        id: '00000000-0000-0000-0000-000000000000',
        email: 'admin@calsteel.local'
      }
    }
    localStorage.setItem('dev_auth_session', JSON.stringify(mockSession))
    setSuccess('Developer offline mode authenticated!')
    setError(null)
    setTimeout(() => {
      router.push('/projects')
    }, 400)
  }

  async function handleResendEmail() {
    if (!email) return
    setResending(true)
    try {
      const { error: resendErr } = await supabase.auth.resend({
        type: 'signup',
        email,
      })
      if (resendErr) throw resendErr
      setResendSuccess(true)
      setError(null)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to resend confirmation email')
    } finally {
      setResending(false)
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSuccess(null)
    setResendSuccess(false)
    setLoading(true)

    // Developer Offline Bypass Login ID
    if (email === 'admin@calsteel.local' && password === 'adminpassword123') {
      handleDevLogin()
      setLoading(false)
      return
    }

    try {
      if (tab === 'login') {
        const { error: err } = await supabase.auth.signInWithPassword({ email, password })
        if (err) throw err
        setSuccess('Signed in! Redirecting…')
        router.push('/projects')
      } else {
        const { data, error: err } = await supabase.auth.signUp({ email, password })
        if (err) throw err

        // If Supabase provides a session immediately (email confirmation disabled)
        if (data?.session) {
          setSuccess('Account created! Signing you in…')
          router.push('/projects')
          return
        }

        // Try signing in immediately in case auto-confirmation is enabled
        const { data: signInData, error: err2 } = await supabase.auth.signInWithPassword({ email, password })
        if (!err2 && signInData?.session) {
          setSuccess('Account created! Signing you in…')
          router.push('/projects')
          return
        }

        // Email confirmation is required by Supabase
        if (err2 && err2.message.toLowerCase().includes('email not confirmed')) {
          setSuccess('Account created! A confirmation email has been sent to ' + email + '. Please verify your email, then sign in.')
          setTab('login')
          return
        }

        if (err2) throw err2
        setSuccess('Account created! Please check your email to confirm your account.')
        setTab('login')
      }
    } catch (err: unknown) {
      setSuccess(null)
      const msg = err instanceof Error ? err.message : 'Something went wrong'
      if (msg.toLowerCase().includes('email not confirmed')) {
        setError('Email not confirmed yet. Please verify the confirmation email sent to ' + email + ', or request a new one below.')
      } else {
        setError(msg)
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ minHeight:'100vh', backgroundColor:'#0F172A', display:'flex', alignItems:'center',
        justifyContent:'center', position:'relative', overflow:'hidden',
        fontFamily:"'Inter', system-ui, sans-serif" }}>
      {/* Grid */}
      <div style={{ position:'absolute', inset:0, pointerEvents:'none',
        backgroundImage:'linear-gradient(rgba(59,130,246,0.04) 1px,transparent 1px),linear-gradient(90deg,rgba(59,130,246,0.04) 1px,transparent 1px)',
        backgroundSize:'40px 40px' }} />
      {/* Glow blobs */}
      <div style={{ position:'absolute', top:'-15%', left:'-10%', width:'600px', height:'600px',
        borderRadius:'50%', background:'radial-gradient(circle,rgba(59,130,246,0.14) 0%,transparent 70%)', pointerEvents:'none' }} />
      <div style={{ position:'absolute', bottom:'-15%', right:'-10%', width:'600px', height:'600px',
        borderRadius:'50%', background:'radial-gradient(circle,rgba(99,102,241,0.10) 0%,transparent 70%)', pointerEvents:'none' }} />

      <div style={{ position:'relative', zIndex:10, width:'100%', maxWidth:'420px', margin:'0 16px',
          backgroundColor:'rgba(15,23,42,0.85)', border:'1px solid rgba(59,130,246,0.2)',
          borderRadius:'16px', padding:'40px 36px', backdropFilter:'blur(20px)',
          boxShadow:'0 25px 60px rgba(0,0,0,0.5)' }}>
        {/* Logo */}
        <div style={{ display:'flex', alignItems:'center', gap:'10px', marginBottom:'28px' }}>
          <div style={{ width:'40px', height:'40px', backgroundColor:'rgba(59,130,246,0.12)',
              border:'1px solid rgba(59,130,246,0.3)', borderRadius:'10px',
              display:'flex', alignItems:'center', justifyContent:'center' }}>
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
              <path d="M4 4h16v4H4zM4 10h10v4H4zM4 16h7v4H4z" fill="#3B82F6" />
            </svg>
          </div>
          <span style={{ fontSize:'18px', fontWeight:700, color:'#F1F5F9', letterSpacing:'-0.3px' }}>SteelGenie</span>
        </div>

        <h1 style={{ margin:'0 0 6px', fontSize:'26px', fontWeight:700, color:'#F1F5F9', letterSpacing:'-0.5px' }}>
          {tab === 'login' ? 'Welcome back' : 'Create account'}
        </h1>
        <p style={{ margin:'0 0 28px', fontSize:'14px', color:'#64748B' }}>
          {tab === 'login' ? 'Sign in to your structural workspace' : 'Start your free structural analysis workspace'}
        </p>

        {/* Tabs */}
        <div style={{ display:'flex', gap:'4px', backgroundColor:'rgba(30,41,59,0.8)',
            border:'1px solid rgba(59,130,246,0.1)', borderRadius:'10px', padding:'4px', marginBottom:'28px' }}>
          {(['login','signup'] as Tab[]).map(t => (
            <button key={t} onClick={() => { setTab(t); setError(null); setSuccess(null) }}
              style={{ flex:1, padding:'8px 0', border:'none', borderRadius:'7px', fontSize:'13px',
                fontWeight:600, cursor:'pointer', transition:'all 0.2s', fontFamily:'inherit',
                backgroundColor: tab===t ? '#3B82F6' : 'transparent',
                color: tab===t ? '#fff' : '#64748B',
                boxShadow: tab===t ? '0 2px 8px rgba(59,130,246,0.35)' : 'none' }}>
              {t === 'login' ? 'Sign In' : 'Sign Up'}
            </button>
          ))}
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} style={{ display:'flex', flexDirection:'column', gap:'18px' }}>
          {['email','password'].map(field => (
            <div key={field} style={{ display:'flex', flexDirection:'column', gap:'6px' }}>
              <label htmlFor={field} style={{ fontSize:'12px', fontWeight:600, color:'#94A3B8',
                  textTransform:'uppercase', letterSpacing:'0.6px' }}>
                {field === 'email' ? 'Email address' : 'Password'}
              </label>
              <input id={field} type={field} required minLength={field==='password' ? 6 : undefined}
                value={field==='email' ? email : password}
                onChange={e => field==='email' ? setEmail(e.target.value) : setPassword(e.target.value)}
                placeholder={field==='email' ? 'engineer@firm.com' : '••••••••'}
                style={{ padding:'11px 14px', backgroundColor:'rgba(30,41,59,0.8)',
                  border:'1px solid rgba(59,130,246,0.2)', borderRadius:'8px', color:'#F1F5F9',
                  fontSize:'14px', outline:'none', fontFamily:'inherit' }} />
            </div>
          ))}

          {error && (
            <div style={{ display:'flex', flexDirection:'column', gap:'8px', padding:'10px 14px',
                backgroundColor:'rgba(239,68,68,0.08)', border:'1px solid rgba(239,68,68,0.2)',
                borderRadius:'8px', color:'#F87171', fontSize:'13px' }}>
              <div style={{ display:'flex', alignItems:'center', gap:'8px' }}>
                <span>⚠ {error}</span>
              </div>
              {error.toLowerCase().includes('email not confirmed') && email && (
                <button
                  type="button"
                  onClick={handleResendEmail}
                  disabled={resending}
                  style={{ alignSelf:'flex-start', background:'none', border:'none', color:'#60A5FA',
                    fontSize:'12px', fontWeight:600, cursor: resending ? 'not-allowed' : 'pointer',
                    padding:0, textDecoration:'underline', fontFamily:'inherit' }}>
                  {resending ? 'Sending verification email…' : 'Resend confirmation email'}
                </button>
              )}
            </div>
          )}
          {resendSuccess && (
            <div style={{ display:'flex', alignItems:'center', gap:'8px', padding:'10px 14px',
                backgroundColor:'rgba(52,211,153,0.08)', border:'1px solid rgba(52,211,153,0.2)',
                borderRadius:'8px', color:'#34D399', fontSize:'13px' }}>
              ✓ Verification email sent! Please check your inbox.
            </div>
          )}
          {success && (
            <div style={{ display:'flex', alignItems:'center', gap:'8px', padding:'10px 14px',
                backgroundColor:'rgba(52,211,153,0.08)', border:'1px solid rgba(52,211,153,0.2)',
                borderRadius:'8px', color:'#34D399', fontSize:'13px' }}>
              ✓ {success}
            </div>
          )}

          <button type="submit" disabled={loading}
            style={{ marginTop:'4px', padding:'13px', backgroundColor: loading ? '#1E40AF' : '#3B82F6',
              border:'none', borderRadius:'9px', color:'#fff', fontSize:'15px', fontWeight:600,
              cursor: loading ? 'not-allowed' : 'pointer', fontFamily:'inherit',
              boxShadow: loading ? 'none' : '0 4px 14px rgba(59,130,246,0.35)', transition:'all 0.2s' }}>
            {loading ? 'Please wait…' : tab==='login' ? 'Sign In' : 'Create Account'}
          </button>
        </form>

        <p style={{ marginTop:'24px', textAlign:'center', fontSize:'13px', color:'#475569' }}>
          {tab==='login' ? "Don't have an account? " : 'Already have an account? '}
          <button onClick={() => { setTab(tab==='login' ? 'signup' : 'login'); setError(null); setSuccess(null) }}
            style={{ background:'none', border:'none', color:'#60A5FA', fontSize:'13px',
              fontWeight:600, cursor:'pointer', padding:0, fontFamily:'inherit' }}>
            {tab==='login' ? 'Sign up free' : 'Sign in'}
          </button>
        </p>

        {/* Developer Offline Bypass Quick Action */}
        <div style={{ marginTop:'20px', paddingTop:'16px', borderTop:'1px solid rgba(255,255,255,0.08)', textAlign:'center' }}>
          <button
            type="button"
            onClick={handleDevLogin}
            style={{ background:'rgba(59,130,246,0.08)', border:'1px solid rgba(59,130,246,0.2)',
              borderRadius:'7px', color:'#93C5FD', fontSize:'12px', fontWeight:500,
              padding:'6px 12px', cursor:'pointer', fontFamily:'inherit', transition:'all 0.2s' }}>
            ⚡ Continue as Developer (Offline Mode)
          </button>
        </div>
      </div>
    </div>
  )
}
