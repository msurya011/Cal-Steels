import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { supabase } from '../../../lib/supabase'
import { Session, User } from '@supabase/supabase-js'

export function useAuth(requireAuth = true) {
  const router = useRouter()
  const [session, setSession] = useState<Session | null>(null)
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let active = true
    let subscription: any = null

    const initAuth = async () => {
      // 0. Check local storage for mock developer session bypass
      if (typeof window !== 'undefined') {
        const mockStr = localStorage.getItem('dev_auth_session')
        if (mockStr) {
          try {
            const parsed = JSON.parse(mockStr)
            if (active) {
              setSession(parsed as any)
              setUser(parsed.user as any)
              setLoading(false)
              return
            }
          } catch {
            // ignore parsing error
          }
        }
      }

      try {
        // 1. Get initial session
        const { data } = await supabase.auth.getSession()
        if (active) {
          setSession(data.session)
          setUser(data.session?.user ?? null)
          setLoading(false)

          if (requireAuth && !data.session) {
            router.push('/login')
          }
        }
      } catch (err) {
        console.error('Auth getSession error:', err)
        if (active) {
          setLoading(false)
          if (requireAuth) {
            router.push('/login')
          }
        }
      }

      try {
        // 2. Listen for auth state changes
        const { data } = supabase.auth.onAuthStateChange((_event: any, newSession: any) => {
          if (active) {
            setSession(newSession)
            setUser(newSession?.user ?? null)
            setLoading(false)

            if (requireAuth && !newSession) {
              router.push('/login')
            }
          }
        })
        subscription = data.subscription
      } catch (err) {
        console.error('Auth onAuthStateChange error:', err)
        if (active) {
          setLoading(false)
        }
      }
    }

    initAuth()

    return () => {
      active = false
      if (subscription) {
        subscription.unsubscribe()
      }
    }
  }, [requireAuth, router])

  const signOut = async () => {
    try {
      if (typeof window !== 'undefined') {
        localStorage.removeItem('dev_auth_session')
      }
      await supabase.auth.signOut()
    } catch (err) {
      console.error('Auth signOut error:', err)
    }
    router.push('/login')
  }

  return { session, user, loading, signOut }
}
