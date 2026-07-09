'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '../features/auth/hooks/useAuth'
import { Spinner } from '../components/ui/Spinner'

const SCALE_OPTIONS = [
  { label: '1/32" = 1\'-0"',  ratio: 384 },
  { label: '3/64" = 1\'-0"',  ratio: 256 },
  { label: '1/16" = 1\'-0"',  ratio: 192 },
  { label: '3/32" = 1\'-0"',  ratio: 128 },
  { label: '1/8" = 1\'-0"',   ratio: 96  },
  { label: '3/16" = 1\'-0"',  ratio: 64  },
  { label: '1/4" = 1\'-0"',   ratio: 48  },
  { label: '3/8" = 1\'-0"',   ratio: 32  },
  { label: '1/2" = 1\'-0"',   ratio: 24  },
  { label: '3/4" = 1\'-0"',   ratio: 16  },
  { label: '1" = 1\'-0"',     ratio: 12  },
  { label: '1-1/2" = 1\'-0"', ratio: 8   },
  { label: '3" = 1\'-0"',     ratio: 4   },
  { label: '1" = 10\'-0"',    ratio: 120 },
  { label: '1" = 20\'-0"',    ratio: 240 },
  { label: '1" = 30\'-0"',    ratio: 360 },
  { label: '1" = 40\'-0"',    ratio: 480 },
  { label: '1" = 50\'-0"',    ratio: 600 },
  { label: '1" = 60\'-0"',    ratio: 720 },
  { label: '1" = 100\'-0"',   ratio: 1200 },
]

export default function RootPage() {
  const router = useRouter()
  const { session, loading } = useAuth(false)

  useEffect(() => {
    const timer = setTimeout(() => {
      router.push('/login')
    }, 2000)

    if (!loading) {
      clearTimeout(timer)
      if (session) {
        router.push('/projects')
      } else {
        router.push('/login')
      }
    }

    return () => clearTimeout(timer)
  }, [session, loading, router])

  return (
    <div style={{ display: 'flex', minHeight: '100vh', alignItems: 'center', justifyContent: 'center', backgroundColor: '#090D1A' }}>
      <Spinner size="lg" />
    </div>
  )
}
