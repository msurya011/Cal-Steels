'use client'

import React from 'react'
import { QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'sonner'
import { queryClient } from '../lib/queryClient'
import './globals.css'

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <head>
        <link rel="icon" href="/favicon.ico" sizes="any" />
        <title>CalSteel</title>
      </head>
      <body style={{
        margin: 0,
        padding: 0,
        backgroundColor: '#090D1A',
        color: '#F1F5F9',
        fontFamily: "'Inter', system-ui, -apple-system, sans-serif",
      }}>
        <QueryClientProvider client={queryClient}>
          {children}
          <Toaster theme="dark" position="top-right" closeButton richColors />
        </QueryClientProvider>
      </body>
    </html>
  )
}
