import type { Metadata, Viewport } from 'next'
import './globals.css'
import ThemeProvider from '@/components/ThemeProvider'
import KeyboardShortcuts from '@/components/KeyboardShortcuts'
import PwaRegister from '@/components/PwaRegister'
import DevConsoleNoiseFilter from '@/components/DevConsoleNoiseFilter'
import { ToastProvider } from '@/components/ui/Toast'
import { ConfirmDialogProvider } from '@/components/ui/ConfirmDialog'
import { RealtimeProvider } from '@/contexts/RealtimeContext'

export const metadata: Metadata = {
    title: 'SentinelCV - Visitor Tracking Dashboard',
    description: 'AI-powered visitor tracking and face recognition system',
    manifest: '/manifest.webmanifest',
}

export const viewport: Viewport = {
    themeColor: '#0f172a',
}

export default function RootLayout({
    children,
}: {
    children: React.ReactNode
}) {
    return (
        <html lang="en" className="dark" suppressHydrationWarning>
            <body className="bg-[#050505] text-white min-h-screen" suppressHydrationWarning>
                <ThemeProvider>
                    <ToastProvider>
                        <ConfirmDialogProvider>
                            <RealtimeProvider>
                                <DevConsoleNoiseFilter />
                                <KeyboardShortcuts />
                                <PwaRegister />
                                {children}
                            </RealtimeProvider>
                        </ConfirmDialogProvider>
                    </ToastProvider>
                </ThemeProvider>
            </body>
        </html>
    )
}
